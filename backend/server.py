"""
FastAPI backend for BTC Seed Recovery Dashboard.
Wraps the `seedrecover.py` script from btcrecover (3rdIteration/btcrecover) as a
managed subprocess with live logs, progress parsing, and job history.
"""
from __future__ import annotations

import asyncio
import itertools
import math
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import psutil
import httpx
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from btc_address import validate_btc_mainnet_address

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
BTCRECOVER_DIR = Path(os.environ.get("BTCRECOVER_DIR", "/opt/btcrecover"))
WORDLISTS_DIR = BTCRECOVER_DIR / "btcrecover" / "wordlists"
JOB_WORKDIR = Path(os.environ.get("JOB_WORKDIR", str(ROOT_DIR / "data")))
JOB_WORKDIR.mkdir(parents=True, exist_ok=True)

# HMAC signing key for export audit trails. Persisted in JOB_WORKDIR so it
# stays stable across restarts (allows re-verification of older exports).
_SIGN_KEY_FILE = JOB_WORKDIR / ".sign_key"
if not _SIGN_KEY_FILE.exists():
    import secrets
    _SIGN_KEY_FILE.write_text(secrets.token_hex(32))
EXPORT_SIGNING_KEY = _SIGN_KEY_FILE.read_text().strip().encode()

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]


def _detect_seedrecover_version() -> Optional[str]:
    """Run `seedrecover.py --version` once at startup and cache the banner line."""
    import sys as _sys
    try:
        r = subprocess.run(
            [_sys.executable, str(BTCRECOVER_DIR / "seedrecover.py"), "--version"],
            capture_output=True, text=True, timeout=10, cwd=str(BTCRECOVER_DIR),
        )
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        for ln in out.splitlines():
            if ln.strip().lower().startswith("starting"):
                return ln.strip()
        return "seedrecover available"
    except Exception as e:
        return f"err: {e}"


SEEDRECOVER_VERSION = (
    _detect_seedrecover_version() if (BTCRECOVER_DIR / "seedrecover.py").exists() else None
)

app = FastAPI(title="Seed Recovery Dashboard")
api = APIRouter(prefix="/api")

origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Models ----------
def _to_str(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    return str(v)


PyObjectId = Annotated[str, BeforeValidator(_to_str)]


class SeedConfig(BaseModel):
    """Configuration of the seed recovery attempt."""
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    seed_length: int = 12  # 12, 15, 18, 21, 24
    wallet_type: str = "electrum2"  # electrum2, bip39, bip32, etc.
    language: str = "en"
    # Known words, list of length == seed_length, value "" or None == unknown ("?")
    known_words: List[str] = Field(default_factory=lambda: [""] * 12)
    # Candidate words for unknown positions
    candidate_words: List[str] = Field(default_factory=list)
    passphrase_enabled: bool = False
    passphrase: Optional[str] = None
    # Verification target — at least one needed for btcrecover to find a match
    address: Optional[str] = None  # BTC address to verify against
    mpk: Optional[str] = None  # master public key (xpub)
    wallet_file_path: Optional[str] = None  # path to wallet file
    addr_limit: int = 10
    threads: int = 2
    typos: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobCreateRequest(BaseModel):
    config_snapshot: Optional[dict] = None  # if provided, use this config instead of stored one
    label: Optional[str] = None


class JobStats(BaseModel):
    candidates_tested: int = 0
    candidates_per_sec: float = 0.0
    eta_seconds: Optional[float] = None
    progress_pct: float = 0.0
    current_candidate: Optional[str] = None
    total_candidates: Optional[int] = None


class JobModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    job_id: str
    label: Optional[str] = None
    status: str = "pending"  # pending | running | found | not_found | stopped | failed
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    pid: Optional[int] = None
    command: List[str] = Field(default_factory=list)
    config_snapshot: dict = Field(default_factory=dict)
    stats: JobStats = Field(default_factory=JobStats)
    found_seed: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- In-memory job manager ----------
class JobRuntime:
    """In-memory state for a running subprocess job."""
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.process: Optional[asyncio.subprocess.Process] = None
        self.logs: List[dict] = []  # [{ts, stream, line}]
        self.stats = JobStats()
        self.status = "pending"
        self.found_seed: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None
        self.command: List[str] = []
        self.workdir: Path = JOB_WORKDIR / job_id
        self.stop_requested = False
        self.error: Optional[str] = None
        # WebSocket subscribers for live log streaming
        self.subscribers: List[asyncio.Queue] = []
        # File handle for persisting logs to disk (NDJSON)
        self._log_file = None

    def open_log_file(self):
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._log_file = open(self.workdir / "output.ndjson", "a", encoding="utf-8")

    def close_log_file(self):
        try:
            if self._log_file:
                self._log_file.flush()
                self._log_file.close()
        except Exception:
            pass
        self._log_file = None

    def append_log(self, stream: str, line: str):
        import json as _json
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stream": stream,
            "line": line,
        }
        self.logs.append(entry)
        # Cap at 5000 lines in memory
        if len(self.logs) > 5000:
            self.logs = self.logs[-5000:]
        # Persist to disk
        if self._log_file:
            try:
                self._log_file.write(_json.dumps(entry) + "\n")
                self._log_file.flush()
            except Exception:
                pass
        # Broadcast to WebSocket subscribers (non-blocking)
        for q in list(self.subscribers):
            try:
                q.put_nowait({"type": "log", "entry": entry, "stats": self.stats.model_dump(), "status": self.status})
            except asyncio.QueueFull:
                pass


def load_logs_from_disk(job_id: str) -> List[dict]:
    """Load persisted logs (NDJSON) for a finished job from disk."""
    import json as _json
    p = JOB_WORKDIR / job_id / "output.ndjson"
    if not p.exists():
        return []
    out = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(_json.loads(ln))
                except Exception:
                    pass
    except Exception:
        pass
    return out


JOBS: dict[str, JobRuntime] = {}


# ---------- Mask generation ----------
def generate_masks(known_words: List[str], seed_length: int) -> List[str]:
    """
    Build a list of mnemonic-mask strings.
    Each mask is `seed_length` tokens separated by spaces. Known words have
    their value; unknown positions use '?' which btcrecover/seedrecover accepts.

    If positions are FIXED (the user already placed words at the right slot),
    we just return ONE mask line. Otherwise (positions unknown), we generate
    permutations of the known words across the unknown slots.
    """
    words = [w.strip() for w in known_words[:seed_length]]
    words += [""] * (seed_length - len(words))

    # If all positions either filled or '?' explicitly -> return single mask
    return [" ".join(w if w else "?" for w in words)]


def generate_permutation_masks(known_unpositioned: List[str], seed_length: int) -> List[str]:
    """If user knows some words but not their positions, build permutations."""
    known_clean = [w.strip() for w in known_unpositioned if w.strip()]
    if not known_clean or len(known_clean) > seed_length:
        return []
    # Guard against combinatorial explosion
    if len(known_clean) > 9:
        return []
    masks = []
    for positions in itertools.combinations(range(seed_length), len(known_clean)):
        for perm in itertools.permutations(known_clean):
            slots = ["?"] * seed_length
            for pos, w in zip(positions, perm):
                slots[pos] = w
            masks.append(" ".join(slots))
    # Deduplicate
    return list(dict.fromkeys(masks))


# ---------- Command builder ----------
def build_seedrecover_command(cfg: dict, workdir: Path) -> List[str]:
    """Build a `python3 seedrecover.py ...` argv for a given config."""
    import sys as _sys
    seedrecover = BTCRECOVER_DIR / "seedrecover.py"
    cmd = [
        _sys.executable, "-u", str(seedrecover),
        "--no-pause", "--no-gui", "--disablesecuritywarnings",
    ]

    # Mnemonic mask
    seed_length = int(cfg.get("seed_length", 12))
    known = cfg.get("known_words") or [""] * seed_length
    masks = generate_masks(known, seed_length)
    mnemonic_line = masks[0] if masks else " ".join(["?"] * seed_length)
    cmd += ["--mnemonic", mnemonic_line]
    cmd += ["--mnemonic-length", str(seed_length)]
    cmd += ["--language", cfg.get("language", "en")]

    wallet_type = cfg.get("wallet_type") or "electrum2"
    cmd += ["--wallet-type", wallet_type]

    # Verification target
    if cfg.get("address"):
        cmd += ["--addrs", cfg["address"], "--addr-limit", str(cfg.get("addr_limit", 10))]
    if cfg.get("mpk"):
        cmd += ["--mpk", cfg["mpk"]]
    if cfg.get("wallet_file_path"):
        cmd += ["--wallet", cfg["wallet_file_path"]]

    # Passphrase
    if cfg.get("passphrase_enabled") and cfg.get("passphrase"):
        cmd += ["--passphrase-arg", cfg["passphrase"]]

    # Typos / threads
    threads = int(cfg.get("threads", 2))
    cmd += ["--threads", str(threads)]
    typos = int(cfg.get("typos", 0))
    if typos > 0:
        cmd += ["--big-typos", str(typos)]

    return cmd


# ---------- Output parser ----------
PROGRESS_RE = re.compile(r"(\d+)\s+of\s+(\d+)\s*\((\d+\.?\d*)%\)")
RATE_RE = re.compile(r"([\d.]+)\s*(p/s|/s|pwords/sec|tried/sec)", re.IGNORECASE)
ETA_RE = re.compile(r"ETA[:\s]+([0-9:]+|[0-9.]+\s*(?:seconds|minutes|hours|days))", re.IGNORECASE)
FOUND_RE = re.compile(r"(seed found|Mnemonic found|Password found|password found)", re.IGNORECASE)
SEED_PHRASE_RE = re.compile(r"^[a-z]+(?: [a-z]+){11,23}$")
NOT_FOUND_RE = re.compile(r"(seed not found|Password search exhausted|password search exhausted)", re.IGNORECASE)


def parse_progress(line: str, stats: JobStats) -> JobStats:
    """Mutate stats from a stdout line."""
    m = PROGRESS_RE.search(line)
    if m:
        try:
            stats.candidates_tested = int(m.group(1))
            stats.total_candidates = int(m.group(2))
            stats.progress_pct = float(m.group(3))
        except Exception:
            pass
    m = RATE_RE.search(line)
    if m:
        try:
            stats.candidates_per_sec = float(m.group(1))
        except Exception:
            pass
    if stats.candidates_per_sec and stats.total_candidates:
        remaining = max(0, stats.total_candidates - stats.candidates_tested)
        if stats.candidates_per_sec > 0:
            stats.eta_seconds = remaining / stats.candidates_per_sec
    return stats


# ---------- Subprocess runner ----------
async def _stream_reader(stream, runtime: JobRuntime, name: str):
    try:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            runtime.append_log(name, line)
            parse_progress(line, runtime.stats)
            # Seed-found detection (defer status finalization to run_job)
            if FOUND_RE.search(line):
                runtime._found_hit = True
            # A line containing 12-24 lowercase words may be the recovered seed
            stripped = line.strip()
            if SEED_PHRASE_RE.match(stripped) and getattr(runtime, "_found_hit", False):
                runtime.found_seed = stripped
            # NOT_FOUND_RE matches per-phase; do not change status here
    except Exception as e:
        runtime.append_log("system", f"[stream-reader error] {e}")


async def run_job(runtime: JobRuntime, command: List[str]):
    runtime.workdir.mkdir(parents=True, exist_ok=True)
    runtime.open_log_file()
    runtime.command = command
    runtime.status = "running"
    runtime.started_at = datetime.now(timezone.utc)
    # Update Mongo immediately with started_at
    await db.jobs.update_one(
        {"job_id": runtime.job_id},
        {"$set": {"status": "running", "started_at": runtime.started_at, "command": command}},
    )
    runtime.append_log("system", f"$ {' '.join(command)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(BTCRECOVER_DIR),
            preexec_fn=os.setsid,
        )
        runtime.process = proc
        await asyncio.gather(
            _stream_reader(proc.stdout, runtime, "stdout"),
            _stream_reader(proc.stderr, runtime, "stderr"),
        )
        rc = await proc.wait()
        runtime.finished_at = datetime.now(timezone.utc)
        runtime.append_log("system", f"[process exit code={rc}]")
        if runtime.stop_requested:
            runtime.status = "stopped"
        elif runtime.found_seed or getattr(runtime, "_found_hit", False):
            runtime.status = "found"
        elif rc == 0:
            runtime.status = "not_found"
        else:
            runtime.status = "failed"
            runtime.error = f"Exit code {rc}"
    except FileNotFoundError as e:
        runtime.status = "failed"
        runtime.error = f"btcrecover not available: {e}"
        runtime.append_log("system", f"[error] {e}")
        runtime.finished_at = datetime.now(timezone.utc)
    except Exception as e:
        runtime.status = "failed"
        runtime.error = str(e)
        runtime.append_log("system", f"[error] {e}")
        runtime.finished_at = datetime.now(timezone.utc)
    finally:
        runtime.close_log_file()
        # Notify WebSocket subscribers of final state
        for q in list(runtime.subscribers):
            try:
                q.put_nowait({"type": "end", "status": runtime.status, "stats": runtime.stats.model_dump(), "found_seed": runtime.found_seed, "error": runtime.error})
            except asyncio.QueueFull:
                pass
    # Persist final state to MongoDB
    await db.jobs.update_one(
        {"job_id": runtime.job_id},
        {"$set": {
            "status": runtime.status,
            "started_at": runtime.started_at,
            "finished_at": runtime.finished_at,
            "pid": runtime.process.pid if runtime.process else None,
            "stats": runtime.stats.model_dump(),
            "found_seed": runtime.found_seed,
            "error": runtime.error,
            "command": runtime.command,
            "logs_tail": [l["line"] for l in runtime.logs[-200:]],
        }},
        upsert=True,
    )


# ---------- API endpoints ----------
@api.get("/")
async def root():
    return {"name": "Seed Recovery Dashboard API", "ok": True}


@api.get("/system/status")
async def system_status():
    """System / btcrecover availability + host vitals."""
    btcrecover_ok = (BTCRECOVER_DIR / "seedrecover.py").exists()
    seedrecover_version = SEEDRECOVER_VERSION
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "btcrecover": {
            "available": btcrecover_ok,
            "path": str(BTCRECOVER_DIR),
            "version": seedrecover_version,
        },
        "cpu_percent": cpu,
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_percent": mem.percent,
        "memory_total_gb": round(mem.total / (1024 ** 3), 2),
        "disk_percent": disk.percent,
        "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        "active_jobs": sum(1 for r in JOBS.values() if r.status == "running"),
    }


@api.get("/config")
async def get_config():
    doc = await db.config.find_one({"_id": "default"})
    if not doc:
        cfg = SeedConfig()
        await db.config.insert_one({"_id": "default", **cfg.model_dump()})
        return cfg.model_dump()
    doc.pop("_id", None)
    return doc


@api.put("/config")
async def update_config(payload: dict):
    payload = {k: v for k, v in payload.items() if k != "_id" and k != "id"}
    # Normalize known_words length
    seed_length = int(payload.get("seed_length", 12))
    kw = payload.get("known_words") or []
    kw = (kw + [""] * seed_length)[:seed_length]
    payload["known_words"] = kw
    payload["updated_at"] = datetime.now(timezone.utc)
    await db.config.update_one({"_id": "default"}, {"$set": payload}, upsert=True)
    doc = await db.config.find_one({"_id": "default"})
    doc.pop("_id", None)
    return doc


@api.post("/masks/preview")
async def preview_masks(payload: dict):
    seed_length = int(payload.get("seed_length", 12))
    known_words = payload.get("known_words") or []
    fixed_mask = generate_masks(known_words, seed_length)
    # Also build permutation masks if user has known-but-unpositioned words
    known_unpositioned = payload.get("known_unpositioned") or []
    perms = []
    if known_unpositioned:
        perms = generate_permutation_masks(known_unpositioned, seed_length)
    return {
        "fixed_mask": fixed_mask,
        "permutation_masks_count": len(perms),
        "permutation_masks_sample": perms[:25],
    }


@api.post("/jobs")
async def create_job(req: JobCreateRequest):
    # Load or use snapshot config
    if req.config_snapshot:
        cfg = req.config_snapshot
    else:
        doc = await db.config.find_one({"_id": "default"})
        if not doc:
            raise HTTPException(400, "No configuration found")
        doc.pop("_id", None)
        cfg = doc

    job_id = str(uuid.uuid4())
    runtime = JobRuntime(job_id)
    JOBS[job_id] = runtime
    command = build_seedrecover_command(cfg, runtime.workdir)

    await db.jobs.insert_one({
        "job_id": job_id,
        "label": req.label,
        "status": "pending",
        "command": command,
        "config_snapshot": cfg,
        "stats": JobStats().model_dump(),
        "created_at": datetime.now(timezone.utc),
    })

    asyncio.create_task(run_job(runtime, command))
    return {"job_id": job_id, "status": "starting", "command": command}


@api.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str):
    runtime = JOBS.get(job_id)
    if not runtime:
        raise HTTPException(404, "Job not in memory (maybe already completed)")
    if not runtime.process or runtime.process.returncode is not None:
        raise HTTPException(400, "Job not running")
    runtime.stop_requested = True
    try:
        os.killpg(os.getpgid(runtime.process.pid), signal.SIGTERM)
    except Exception:
        try:
            runtime.process.terminate()
        except Exception:
            pass
    return {"ok": True, "job_id": job_id}


@api.get("/jobs/{job_id}")
async def get_job(job_id: str):
    runtime = JOBS.get(job_id)
    if runtime:
        return {
            "job_id": job_id,
            "status": runtime.status,
            "started_at": runtime.started_at.isoformat() if runtime.started_at else None,
            "finished_at": runtime.finished_at.isoformat() if runtime.finished_at else None,
            "stats": runtime.stats.model_dump(),
            "found_seed": runtime.found_seed,
            "error": runtime.error,
            "command": runtime.command,
            "in_memory": True,
        }
    doc = await db.jobs.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "Job not found")
    doc["_id"] = str(doc["_id"])
    return doc


@api.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, since: int = 0):
    """Return logs[since:]. Cursor-style polling."""
    runtime = JOBS.get(job_id)
    if runtime:
        logs = runtime.logs[since:]
        return {
            "next": since + len(logs),
            "lines": logs,
            "status": runtime.status,
            "stats": runtime.stats.model_dump(),
            "found_seed": runtime.found_seed,
        }
    doc = await db.jobs.find_one({"job_id": job_id})
    if not doc:
        raise HTTPException(404, "Job not found")
    # Prefer persisted NDJSON log file over Mongo logs_tail
    disk_logs = load_logs_from_disk(job_id)
    if disk_logs:
        sliced = disk_logs[since:]
        return {
            "next": since + len(sliced),
            "lines": sliced,
            "status": doc.get("status"),
            "stats": doc.get("stats", {}),
            "found_seed": doc.get("found_seed"),
        }
    tail = doc.get("logs_tail", [])
    return {
        "next": len(tail),
        "lines": [{"ts": None, "stream": "archived", "line": l} for l in tail[since:]],
        "status": doc.get("status"),
        "stats": doc.get("stats", {}),
        "found_seed": doc.get("found_seed"),
    }


@api.get("/jobs")
async def list_jobs(limit: int = 50):
    cursor = db.jobs.find({}, {"logs_tail": 0}).sort("created_at", -1).limit(limit)
    out = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        # Overlay in-memory state if present
        rt = JOBS.get(doc["job_id"])
        if rt:
            doc["status"] = rt.status
            doc["stats"] = rt.stats.model_dump()
            doc["found_seed"] = rt.found_seed
        out.append(doc)
    return out


@api.delete("/jobs/{job_id}")
async def delete_job(job_id: str):
    runtime = JOBS.get(job_id)
    if runtime and runtime.process and runtime.process.returncode is None:
        raise HTTPException(400, "Cannot delete a running job; stop it first")
    JOBS.pop(job_id, None)
    await db.jobs.delete_one({"job_id": job_id})
    # Remove on-disk log file
    p = JOB_WORKDIR / job_id
    if p.exists():
        try:
            shutil.rmtree(p)
        except Exception:
            pass
    return {"ok": True}


# ---------- Export (signed audit trail) ----------
def _redact_seed_passphrase(cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        return cfg
    out = dict(cfg)
    if out.get("passphrase"):
        out["passphrase"] = "***REDACTED***"
    return out


def _sign_payload(payload: dict) -> str:
    import hashlib
    import hmac
    import json as _json

    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        try:
            return str(o)
        except Exception:
            return None

    canon = _json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_default).encode()
    return hmac.new(EXPORT_SIGNING_KEY, canon, hashlib.sha256).hexdigest()


def _hash_logs(lines: List[dict]) -> str:
    import hashlib
    h = hashlib.sha256()
    for entry in lines:
        s = f"{entry.get('stream','')}:{entry.get('line','')}\n"
        h.update(s.encode("utf-8", errors="replace"))
    return h.hexdigest()


@api.get("/jobs/{job_id}/export")
async def export_job(job_id: str, include_logs: bool = False, redact_seed: bool = True):
    """
    Return a JSON audit-trail document for a job (running or finished).
    - `include_logs=true`: embed full log lines (default false: only count + hash)
    - `redact_seed=false`: include recovered seed in clear (default true: redacted)
    Adds an HMAC-SHA256 signature over the canonical payload.
    """
    runtime = JOBS.get(job_id)
    doc = await db.jobs.find_one({"job_id": job_id})
    if not runtime and not doc:
        raise HTTPException(404, "Job not found")
    if runtime:
        lines = list(runtime.logs)
        status = runtime.status
        started_at = runtime.started_at
        finished_at = runtime.finished_at
        command = runtime.command
        stats = runtime.stats.model_dump()
        found_seed = runtime.found_seed
        error = runtime.error
        config_snapshot = (doc or {}).get("config_snapshot", {})
        label = (doc or {}).get("label")
        created_at = (doc or {}).get("created_at")
    else:
        config_snapshot = doc.get("config_snapshot", {})
        lines = load_logs_from_disk(job_id)
        if not lines and doc.get("logs_tail"):
            lines = [{"ts": None, "stream": "archived", "line": l} for l in doc["logs_tail"]]
        status = doc.get("status")
        started_at = doc.get("started_at")
        finished_at = doc.get("finished_at")
        command = doc.get("command", [])
        stats = doc.get("stats", {})
        found_seed = doc.get("found_seed")
        error = doc.get("error")
        label = doc.get("label")
        created_at = doc.get("created_at")

    def _iso(v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    duration_sec = None
    if started_at and finished_at:
        try:
            s = started_at if isinstance(started_at, datetime) else datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            f = finished_at if isinstance(finished_at, datetime) else datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
            duration_sec = (f - s).total_seconds()
        except Exception:
            duration_sec = None

    payload = {
        "schema": "seed-recovery-audit/v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "job": {
            "job_id": job_id,
            "label": label,
            "status": status,
            "created_at": _iso(created_at),
            "started_at": _iso(started_at),
            "finished_at": _iso(finished_at),
            "duration_seconds": duration_sec,
            "error": error,
        },
        "tool": {
            "name": "btcrecover/seedrecover.py",
            "path": str(BTCRECOVER_DIR),
            "version": SEEDRECOVER_VERSION,
        },
        "command": command,
        "config_snapshot": _redact_seed_passphrase(config_snapshot),
        "stats": stats,
        "result": {
            "found": bool(found_seed),
            "seed": (None if redact_seed else found_seed),
            "seed_redacted": bool(redact_seed and found_seed),
        },
        "logs": {
            "count": len(lines),
            "sha256": _hash_logs(lines),
            "included": bool(include_logs),
            "lines": (lines if include_logs else None),
        },
    }
    payload["signature"] = {
        "algorithm": "HMAC-SHA256",
        "value": _sign_payload(payload),
        "note": "Verify by re-signing the payload above with the server signing key (excluding this 'signature' field).",
    }
    return payload


@api.post("/exports/verify")
async def verify_export(payload: dict):
    """Verify a previously-exported audit JSON. Pass the full payload."""
    if not isinstance(payload, dict) or "signature" not in payload:
        raise HTTPException(400, "Missing signature")
    sig = payload.get("signature", {})
    received = sig.get("value")
    body = {k: v for k, v in payload.items() if k != "signature"}
    expected = _sign_payload(body)
    valid = (received == expected)
    logs_hash_ok = None
    if isinstance(body.get("logs"), dict) and body["logs"].get("included") and body["logs"].get("lines") is not None:
        logs_hash_ok = (_hash_logs(body["logs"]["lines"]) == body["logs"].get("sha256"))
    return {"valid": valid, "expected": expected, "received": received, "logs_hash_ok": logs_hash_ok}



# ---------- Search-space estimate ----------
@api.post("/jobs/estimate")
async def estimate_job(payload: dict):
    """
    Pre-flight estimate of search space and expected runtime BEFORE launching
    a job. Considers number of '?' (unknown positions), candidate wordlist
    size, typos, and reference benchmark rate (~50k candidates/sec).
    """
    seed_length = int(payload.get("seed_length", 12))
    known_words = payload.get("known_words") or []
    known_unpositioned = payload.get("known_unpositioned") or []
    typos = int(payload.get("typos", 0))
    wordlist_size = int(payload.get("wordlist_size") or 2048)  # BIP39 default
    threads = max(1, int(payload.get("threads", 2)))
    # Allow custom benchmark; default seedrecover bench ~50k/s/thread on this pod
    rate_per_thread = float(payload.get("rate_per_thread", 50000))

    unknown_count = sum(1 for w in (known_words[:seed_length] or []) if not (w or "").strip())
    # If we have positioned-known words, unknown_count is what we have
    # If we have unpositioned-known words, they reduce unknown count
    if known_unpositioned:
        unknown_count = max(0, unknown_count - len(known_unpositioned))

    # Search space: per unknown slot, you try `wordlist_size` words. seedrecover
    # actually iterates through valid mnemonics, but as a first approximation
    # the size is wordlist_size ** unknown_count (very rough upper bound).
    if unknown_count > 0:
        log_combos = unknown_count * math.log10(max(1, wordlist_size))
    else:
        log_combos = 0
    combos = 10 ** log_combos if log_combos < 18 else float("inf")

    # Add permutations of unpositioned known words
    if known_unpositioned:
        kup = len([w for w in known_unpositioned if w.strip()])
        if kup <= seed_length:
            # C(seed_length, kup) * kup!
            try:
                perms = math.factorial(seed_length) // math.factorial(seed_length - kup)
                combos = combos * perms if combos != float("inf") else float("inf")
                log_combos = math.log10(max(1, combos)) if combos != float("inf") else float("inf")
            except Exception:
                pass

    # Typo factor (rough): each big-typo multiplies by ~wordlist_size
    if typos > 0 and combos != float("inf"):
        combos = combos * (wordlist_size ** typos)
        log_combos = math.log10(max(1, combos)) if combos != float("inf") else float("inf")

    effective_rate = rate_per_thread * threads
    if combos == float("inf"):
        eta_seconds = float("inf")
        eta_human = "∞ (too large)"
    else:
        eta_seconds = combos / max(1, effective_rate)
        eta_human = _humanize_eta(eta_seconds)

    feasibility = "feasible"
    if eta_seconds == float("inf") or eta_seconds > 3650 * 86400:  # > 10 years
        feasibility = "impractical"
    elif eta_seconds > 365 * 86400:
        feasibility = "very_slow"
    elif eta_seconds > 86400:
        feasibility = "slow"
    elif eta_seconds > 3600:
        feasibility = "moderate"
    else:
        feasibility = "fast"

    return {
        "unknown_positions": unknown_count,
        "wordlist_size": wordlist_size,
        "typos": typos,
        "threads": threads,
        "rate_per_thread": rate_per_thread,
        "effective_rate": effective_rate,
        "log10_search_space": None if log_combos == float("inf") else round(log_combos, 2),
        "search_space_approx": "1e+inf" if combos == float("inf") else f"{combos:.3e}",
        "eta_seconds": None if eta_seconds == float("inf") else eta_seconds,
        "eta_human": eta_human,
        "feasibility": feasibility,
    }


def _humanize_eta(sec: float) -> str:
    if sec == float("inf"):
        return "∞"
    units = [
        ("y", 365 * 86400),
        ("d", 86400),
        ("h", 3600),
        ("m", 60),
        ("s", 1),
    ]
    out = []
    rem = int(sec)
    for u, v in units:
        if rem >= v:
            n = rem // v
            rem -= n * v
            out.append(f"{n}{u}")
        if len(out) >= 2:
            break
    return " ".join(out) if out else "<1s"


# ---------- Wordlist (candlist) ----------
WORDLIST_PATH = JOB_WORKDIR / "candlist.txt"


@api.get("/wordlist")
async def get_wordlist():
    if WORDLIST_PATH.exists():
        text = WORDLIST_PATH.read_text(encoding="utf-8")
        words = [w for w in text.split() if w.strip()]
        return {"count": len(words), "words": words, "raw": text}
    return {"count": 0, "words": [], "raw": ""}


@api.put("/wordlist")
async def put_wordlist(payload: dict):
    raw = payload.get("raw") or ""
    if not raw and payload.get("words"):
        raw = "\n".join(payload["words"])
    WORDLIST_PATH.write_text(raw, encoding="utf-8")
    words = [w for w in raw.split() if w.strip()]
    return {"count": len(words), "path": str(WORDLIST_PATH)}

# ---------- BTC Address verification (preflight check via blockchain explorer) ----------
EXPLORERS = [
    "https://mempool.space/api",
    "https://blockstream.info/api",
]


async def _fetch_address_stats(address: str) -> dict:
    """Try mempool.space first, then Blockstream Esplora as fallback."""
    timeout = httpx.Timeout(8.0, connect=4.0)
    last_error = None
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "seed-recovery-dashboard/1.0"}) as client:
        for base in EXPLORERS:
            try:
                resp = await client.get(f"{base}/address/{address}")
            except httpx.RequestError as e:
                last_error = f"{base}: {e}"
                continue
            if resp.status_code == 400:
                return {
                    "explorer": base, "reachable": True,
                    "exists": False, "error": "explorer rejected the address",
                }
            if resp.status_code == 404:
                return {
                    "explorer": base, "reachable": True,
                    "exists": False, "tx_count": 0, "balance_sats": 0, "has_history": False,
                }
            if resp.status_code == 429:
                last_error = f"{base}: rate limited"
                continue
            if resp.status_code >= 500:
                last_error = f"{base}: {resp.status_code}"
                continue
            try:
                data = resp.json()
            except Exception as e:
                last_error = f"{base}: invalid JSON ({e})"
                continue
            chain = data.get("chain_stats") or {}
            mem = data.get("mempool_stats") or {}
            tx_chain = int(chain.get("tx_count", 0) or 0)
            tx_mem = int(mem.get("tx_count", 0) or 0)
            funded = int(chain.get("funded_txo_sum", 0) or 0) + int(mem.get("funded_txo_sum", 0) or 0)
            spent = int(chain.get("spent_txo_sum", 0) or 0) + int(mem.get("spent_txo_sum", 0) or 0)
            balance = funded - spent
            return {
                "explorer": base,
                "reachable": True,
                "exists": True,
                "has_history": (tx_chain + tx_mem) > 0,
                "tx_count": tx_chain,
                "mempool_tx_count": tx_mem,
                "funded_sats": funded,
                "spent_sats": spent,
                "balance_sats": balance,
            }
    return {"explorer": None, "reachable": False, "error": last_error or "all explorers unreachable"}


@api.post("/address/verify")
async def verify_address(payload: dict):
    """
    Preflight check on a BTC verification target.
    - Validates address format locally (P2PKH/P2SH/P2WPKH/P2WSH/P2TR mainnet)
    - Queries mempool.space → Blockstream for on-chain history & balance
    Returns a recommendation string:
      ok          — valid + has history (good target)
      unused      — valid but no on-chain activity (probably wrong address)
      invalid     — format invalid
      unknown     — valid format but explorer unreachable
    """
    address = (payload.get("address") or "").strip()
    if not address:
        raise HTTPException(400, "address required")

    fmt = validate_btc_mainnet_address(address)
    out = {
        "address": address,
        "format": fmt,
        "onchain": None,
        "recommendation": "invalid",
        "message": None,
    }
    if not fmt["valid"]:
        out["message"] = f"Invalid address: {fmt.get('error')}"
        return out

    stats = await _fetch_address_stats(address)
    out["onchain"] = stats
    if not stats.get("reachable"):
        out["recommendation"] = "unknown"
        out["message"] = f"Address format OK ({fmt['type']}) but explorers unreachable: {stats.get('error')}"
        return out
    if stats.get("has_history"):
        out["recommendation"] = "ok"
        bal = stats.get("balance_sats", 0)
        out["message"] = (
            f"Valid {fmt['type']} address with {stats['tx_count']} confirmed tx · "
            f"current balance: {bal:,} sats ({bal/1e8:.8f} BTC)"
        )
    else:
        out["recommendation"] = "unused"
        out["message"] = (
            f"Address format OK ({fmt['type']}) but it has NO on-chain activity. "
            "Recovery against an unused address won't help unless you are sure it's yours."
        )
    return out




# ---------- Wordlist presets ----------
@api.get("/wordlists/presets")
async def list_wordlist_presets():
    """List the available BIP39 / Electrum wordlists shipped with btcrecover."""
    out = []
    if not WORDLISTS_DIR.exists():
        return {"presets": out}
    for f in sorted(WORDLISTS_DIR.glob("*.txt")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                count = sum(1 for _ in fh)
        except Exception:
            count = 0
        out.append({
            "name": f.stem,
            "language": (f.stem.split("-")[-1] if "-" in f.stem else "unknown"),
            "family": f.stem.split("-")[0],
            "size": count,
            "path": str(f),
        })
    return {"presets": out}


@api.post("/wordlist/load-preset")
async def load_preset_wordlist(payload: dict):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    src = WORDLISTS_DIR / f"{name}.txt"
    if not src.exists():
        raise HTTPException(404, f"Preset '{name}' not found")
    raw = src.read_text(encoding="utf-8")
    WORDLIST_PATH.write_text(raw, encoding="utf-8")
    words = [w for w in raw.split() if w.strip()]
    return {"count": len(words), "preset": name, "path": str(WORDLIST_PATH)}


# ---------- WebSocket live logs ----------
@app.websocket("/api/jobs/{job_id}/stream")
async def ws_job_stream(websocket: WebSocket, job_id: str):
    await websocket.accept()
    runtime = JOBS.get(job_id)
    if not runtime:
        await websocket.send_json({"type": "error", "message": "Job not found in memory"})
        await websocket.close()
        return
    # Send backlog of existing logs first
    try:
        await websocket.send_json({
            "type": "snapshot",
            "status": runtime.status,
            "stats": runtime.stats.model_dump(),
            "found_seed": runtime.found_seed,
            "logs": runtime.logs,
        })
    except Exception:
        return
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    runtime.subscribers.append(queue)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                await websocket.send_json(msg)
                if msg.get("type") == "end":
                    break
            except asyncio.TimeoutError:
                # heartbeat
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            runtime.subscribers.remove(queue)
        except ValueError:
            pass


app.include_router(api)


# ---------- Orphan cleanup on startup ----------
@app.on_event("startup")
async def cleanup_orphans():
    """
    Any job persisted as 'running'/'pending' in Mongo but not in JOBS memory
    means the backend restarted mid-job — mark them as failed (orphaned).
    """
    cur = db.jobs.find({"status": {"$in": ["running", "pending"]}})
    async for doc in cur:
        jid = doc["job_id"]
        if jid in JOBS:
            continue
        await db.jobs.update_one(
            {"job_id": jid},
            {"$set": {
                "status": "failed",
                "finished_at": datetime.now(timezone.utc),
                "error": "Backend restarted while job was running (orphaned)",
            }},
        )


@app.on_event("shutdown")
async def shutdown_event():
    client.close()
