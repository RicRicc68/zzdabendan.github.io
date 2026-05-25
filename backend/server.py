"""
FastAPI backend for BTC Seed Recovery Dashboard.
Wraps the `seedrecover.py` script from btcrecover (3rdIteration/btcrecover) as a
managed subprocess with live logs, progress parsing, and job history.
"""
from __future__ import annotations

import asyncio
import itertools
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, List, Optional

import psutil
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
BTCRECOVER_DIR = Path(os.environ.get("BTCRECOVER_DIR", "/opt/btcrecover"))
JOB_WORKDIR = Path(os.environ.get("JOB_WORKDIR", str(ROOT_DIR / "data")))
JOB_WORKDIR.mkdir(parents=True, exist_ok=True)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

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

    def append_log(self, stream: str, line: str):
        self.logs.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "stream": stream,
            "line": line,
        })
        # Cap at 5000 lines in memory
        if len(self.logs) > 5000:
            self.logs = self.logs[-5000:]


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
            # Seed found detection
            if FOUND_RE.search(line):
                runtime.status = "found"
            # Lines containing 12-24 lowercase words may be the recovered seed
            stripped = line.strip()
            if SEED_PHRASE_RE.match(stripped) and runtime.status in ("running", "found"):
                runtime.found_seed = stripped
                runtime.status = "found"
            if NOT_FOUND_RE.search(line):
                if runtime.status != "found":
                    runtime.status = "not_found"
    except Exception as e:
        runtime.append_log("system", f"[stream-reader error] {e}")


async def run_job(runtime: JobRuntime, command: List[str]):
    runtime.workdir.mkdir(parents=True, exist_ok=True)
    runtime.command = command
    runtime.status = "running"
    runtime.started_at = datetime.now(timezone.utc)
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
        elif runtime.status not in ("found", "not_found"):
            if rc == 0:
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
    seedrecover_version = None
    if btcrecover_ok:
        try:
            import sys as _sys
            r = subprocess.run(
                [_sys.executable, str(BTCRECOVER_DIR / "seedrecover.py"), "--version"],
                capture_output=True, text=True, timeout=10, cwd=str(BTCRECOVER_DIR),
            )
            out = (r.stdout or "") + "\n" + (r.stderr or "")
            for ln in out.splitlines():
                if ln.strip().lower().startswith("starting"):
                    seedrecover_version = ln.strip()
                    break
            if not seedrecover_version:
                seedrecover_version = "seedrecover available"
        except Exception as e:
            seedrecover_version = f"err: {e}"
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
    return {"ok": True}


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


app.include_router(api)


@app.on_event("shutdown")
async def shutdown_event():
    client.close()
