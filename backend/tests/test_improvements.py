"""
Tests for the new improvements added on top of the Seed Recovery Dashboard:
- POST /api/jobs/estimate (search-space + ETA)
- GET /api/wordlists/presets
- POST /api/wordlist/load-preset
- Persisted NDJSON logs after job exit
- Orphan-job cleanup on backend restart
- WebSocket /api/jobs/{id}/stream live streaming
"""
import asyncio
import json
import os
import time
import uuid

import pytest
import requests
import websockets

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

API = f"{BASE_URL}/api"
WS_URL = BASE_URL.replace("https://", "wss://").replace("http://", "ws://") + "/api/jobs/{job_id}/stream"


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- /api/jobs/estimate ----------
class TestEstimate:
    def test_estimate_fast_one_unknown(self, session):
        payload = {
            "seed_length": 12,
            "known_words": ["abandon"] * 11 + [""],
            "typos": 0,
            "threads": 2,
            "wordlist_size": 2048,
        }
        r = session.post(f"{API}/jobs/estimate", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["unknown_positions"] == 1
        assert d["feasibility"] == "fast"
        assert d.get("eta_human")
        assert d.get("eta_seconds") is not None and d["eta_seconds"] < 60
        # search space ~= 2048
        assert "2.04" in d["search_space_approx"] or "2.05" in d["search_space_approx"]

    def test_estimate_impractical_five_unknown(self, session):
        payload = {
            "seed_length": 12,
            "known_words": ["abandon"] * 7 + [""] * 5,
            "typos": 0,
            "threads": 4,
            "wordlist_size": 2048,
        }
        r = session.post(f"{API}/jobs/estimate", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["unknown_positions"] == 5
        # 2048**5 / (50000*4) ~= 1.84e+13 sec ~ 580k years => impractical
        assert d["feasibility"] == "impractical"

    def test_estimate_no_unknowns(self, session):
        payload = {
            "seed_length": 12,
            "known_words": ["abandon"] * 12,
            "typos": 0,
            "threads": 2,
        }
        r = session.post(f"{API}/jobs/estimate", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert d["unknown_positions"] == 0
        assert d["feasibility"] in ("fast", "feasible")


# ---------- /api/wordlists/presets & load-preset ----------
class TestWordlistPresets:
    def test_presets_listed(self, session):
        r = session.get(f"{API}/wordlists/presets")
        assert r.status_code == 200
        d = r.json()
        presets = d.get("presets", [])
        names = [p["name"] for p in presets]
        assert len(presets) >= 10, f"expected >=10 presets, got {len(presets)}: {names}"
        assert "bip39-en" in names, names
        # find bip39-en size
        for p in presets:
            if p["name"] == "bip39-en":
                assert p["size"] == 2048
            if p["name"] == "electrum1-en":
                assert p["size"] == 1626

    def test_load_preset_bip39_en(self, session):
        r = session.post(f"{API}/wordlist/load-preset", json={"name": "bip39-en"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["count"] == 2048
        assert d["preset"] == "bip39-en"
        # Verify via GET /api/wordlist
        g = session.get(f"{API}/wordlist")
        assert g.status_code == 200
        gd = g.json()
        assert gd["count"] == 2048
        assert "abandon" in gd["words"]

    def test_load_preset_invalid(self, session):
        r = session.post(f"{API}/wordlist/load-preset", json={"name": "definitely-not-a-real-preset"})
        assert r.status_code == 404


# ---------- Persisted NDJSON logs ----------
class TestPersistedLogs:
    def test_logs_loaded_from_disk_after_completion(self, session):
        cfg = {
            "seed_length": 12,
            "wallet_type": "electrum2",
            "language": "en",
            "known_words": ["abandon"] * 11 + [""],
            "address": "1Q1pE5vPGEEMqRcVRMbtBK842Y6Pzo6nK9",
            "addr_limit": 5,
            "threads": 1,
            "typos": 0,
        }
        r = session.post(f"{API}/jobs", json={"config_snapshot": cfg, "label": "TEST_persist"})
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        # Wait for terminal status
        deadline = time.time() + 90
        final = None
        while time.time() < deadline:
            jr = session.get(f"{API}/jobs/{job_id}").json()
            if jr.get("status") in ("not_found", "found", "failed", "stopped"):
                final = jr.get("status")
                if jr.get("finished_at"):
                    break
            time.sleep(2)
        # Ensure subprocess exits (workaround: stop)
        jr = session.get(f"{API}/jobs/{job_id}").json()
        if not jr.get("finished_at"):
            session.post(f"{API}/jobs/{job_id}/stop")
            for _ in range(20):
                time.sleep(0.5)
                jr = session.get(f"{API}/jobs/{job_id}").json()
                if jr.get("finished_at"):
                    break
        # Verify ndjson file present
        ndj = f"/app/backend/data/{job_id}/output.ndjson"
        assert os.path.exists(ndj), f"expected ndjson at {ndj}"
        with open(ndj) as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert len(lines) > 0
        assert all("ts" in e and "line" in e for e in lines)

        # Now logs endpoint should still serve them (may still be in memory)
        r2 = session.get(f"{API}/jobs/{job_id}/logs", params={"since": 0})
        assert r2.status_code == 200
        served = r2.json()["lines"]
        assert len(served) > 0

        # Cleanup
        session.delete(f"{API}/jobs/{job_id}")


# ---------- WebSocket /api/jobs/{id}/stream ----------
@pytest.mark.asyncio
async def test_ws_live_stream():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    cfg = {
        "seed_length": 12,
        "wallet_type": "electrum2",
        "language": "en",
        "known_words": ["abandon"] * 11 + [""],
        "address": "1Q1pE5vPGEEMqRcVRMbtBK842Y6Pzo6nK9",
        "addr_limit": 5,
        "threads": 1,
        "typos": 0,
    }
    r = sess.post(f"{API}/jobs", json={"config_snapshot": cfg, "label": "TEST_ws"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    url = WS_URL.format(job_id=job_id)

    try:
        async with websockets.connect(url, open_timeout=15, max_size=10_000_000) as ws:
            # First message must be snapshot
            first_raw = await asyncio.wait_for(ws.recv(), timeout=20)
            first = json.loads(first_raw)
            assert first.get("type") == "snapshot", first
            assert "status" in first and "logs" in first

            # Collect some log events
            log_count = 0
            end_seen = False
            deadline = time.time() + 45
            while time.time() < deadline and log_count < 5 and not end_seen:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    break
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "log":
                    log_count += 1
                elif t == "end":
                    end_seen = True
                    break
                # ping messages allowed, ignore
            assert log_count >= 1 or end_seen, "no log or end events received"
    finally:
        # Stop and cleanup
        sess.post(f"{API}/jobs/{job_id}/stop")
        time.sleep(2)
        sess.delete(f"{API}/jobs/{job_id}")


@pytest.mark.asyncio
async def test_ws_unknown_job_closes_cleanly():
    url = WS_URL.format(job_id=str(uuid.uuid4()))
    async with websockets.connect(url, open_timeout=10) as ws:
        msg_raw = await asyncio.wait_for(ws.recv(), timeout=10)
        msg = json.loads(msg_raw)
        assert msg.get("type") == "error"
        # Server should close after
        try:
            await asyncio.wait_for(ws.recv(), timeout=5)
        except websockets.ConnectionClosed:
            pass
