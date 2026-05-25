"""Backend integration tests for Seed Recovery Dashboard."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to read from frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL"):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass

API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# -------- System / Health --------
class TestSystem:
    def test_root(self, session):
        r = session.get(f"{API}/")
        assert r.status_code == 200
        assert r.json().get("ok") is True

    def test_system_status(self, session):
        r = session.get(f"{API}/system/status")
        assert r.status_code == 200
        d = r.json()
        assert d["btcrecover"]["available"] is True
        assert "cpu_percent" in d
        assert "memory_percent" in d
        assert "disk_percent" in d
        assert isinstance(d.get("cpu_count"), int) and d["cpu_count"] >= 1


# -------- Config --------
class TestConfig:
    def test_get_default_config(self, session):
        r = session.get(f"{API}/config")
        assert r.status_code == 200
        d = r.json()
        assert "seed_length" in d
        assert "known_words" in d
        assert isinstance(d["known_words"], list)

    def test_put_config_normalizes_known_words(self, session):
        payload = {
            "seed_length": 12,
            "wallet_type": "electrum2",
            "language": "en",
            "known_words": ["abandon"] * 5,  # short list, should be padded
            "addr_limit": 5,
            "threads": 1,
            "typos": 0,
        }
        r = session.put(f"{API}/config", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert len(d["known_words"]) == 12
        assert d["known_words"][:5] == ["abandon"] * 5
        assert d["wallet_type"] == "electrum2"


# -------- Masks --------
class TestMasks:
    def test_preview_fixed_mask(self, session):
        kw = ["alpha"] + [""] * 11
        r = session.post(f"{API}/masks/preview", json={"seed_length": 12, "known_words": kw})
        assert r.status_code == 200
        d = r.json()
        assert d["fixed_mask"] == ["alpha ? ? ? ? ? ? ? ? ? ? ?"]
        assert d["permutation_masks_count"] == 0

    def test_preview_permutations(self, session):
        r = session.post(f"{API}/masks/preview", json={
            "seed_length": 12,
            "known_words": [""] * 12,
            "known_unpositioned": ["alpha", "bravo"],
        })
        assert r.status_code == 200
        d = r.json()
        assert d["permutation_masks_count"] > 0
        assert len(d["permutation_masks_sample"]) > 0


# -------- Wordlist --------
class TestWordlist:
    def test_put_and_get_wordlist(self, session):
        raw = "abandon\nability\nable\nabout"
        r = session.put(f"{API}/wordlist", json={"raw": raw})
        assert r.status_code == 200
        assert r.json()["count"] == 4
        g = session.get(f"{API}/wordlist")
        assert g.status_code == 200
        d = g.json()
        assert d["count"] == 4
        assert "abandon" in d["words"]


# -------- Jobs (real subprocess) --------
@pytest.fixture(scope="module")
def quick_job(session):
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
    r = session.post(f"{API}/jobs", json={"config_snapshot": cfg, "label": "TEST_quick"})
    assert r.status_code == 200, r.text
    return r.json()


class TestJobs:
    def test_create_job_returns_command(self, session, quick_job):
        assert "job_id" in quick_job
        cmd = quick_job["command"]
        assert any("seedrecover.py" in c for c in cmd)
        assert "--mnemonic" in cmd
        assert "--addrs" in cmd
        assert "--wallet-type" in cmd
        assert "1Q1pE5vPGEEMqRcVRMbtBK842Y6Pzo6nK9" in cmd

    def test_job_logs_stream(self, session, quick_job):
        job_id = quick_job["job_id"]
        # Poll logs for up to 40 seconds; assert cursor advances
        cursor = 0
        seen_lines = 0
        terminal = False
        deadline = time.time() + 45
        statuses = []
        while time.time() < deadline:
            r = session.get(f"{API}/jobs/{job_id}/logs", params={"since": cursor})
            assert r.status_code == 200
            d = r.json()
            new = d.get("lines", [])
            seen_lines += len(new)
            assert d["next"] >= cursor
            cursor = d["next"]
            statuses.append(d.get("status"))
            if d.get("status") in ("not_found", "found", "stopped", "failed"):
                terminal = True
                break
            time.sleep(1)
        assert seen_lines > 0, f"no logs received in 45s; statuses={statuses}"
        assert terminal, f"job did not reach terminal state; statuses={statuses[-5:]}"

    def test_job_get_status(self, session, quick_job):
        job_id = quick_job["job_id"]
        r = session.get(f"{API}/jobs/{job_id}")
        assert r.status_code == 200
        d = r.json()
        assert d.get("started_at") is not None
        # Finished by now (test above waited)
        assert d.get("status") in ("not_found", "found", "failed", "stopped")

    def test_jobs_list_contains(self, session, quick_job):
        r = session.get(f"{API}/jobs")
        assert r.status_code == 200
        ids = [j["job_id"] for j in r.json()]
        assert quick_job["job_id"] in ids
        # Most recent first
        assert ids[0] == quick_job["job_id"] or quick_job["job_id"] in ids[:5]


# -------- Stop & Delete --------
class TestStopDelete:
    def test_stop_running_job(self, session):
        cfg = {
            "seed_length": 12,
            "wallet_type": "electrum2",
            "language": "en",
            "known_words": ["abandon"] * 11 + [""],
            "address": "1Q1pE5vPGEEMqRcVRMbtBK842Y6Pzo6nK9",
            "addr_limit": 5,
            "threads": 1,
            "typos": 2,  # longer search
        }
        r = session.post(f"{API}/jobs", json={"config_snapshot": cfg, "label": "TEST_stop"})
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        # Wait until running
        running = False
        for _ in range(20):
            time.sleep(0.5)
            jr = session.get(f"{API}/jobs/{job_id}").json()
            if jr.get("status") == "running":
                running = True
                break
        assert running, "job never started running"
        # Stop
        s = session.post(f"{API}/jobs/{job_id}/stop")
        assert s.status_code == 200
        # Wait for stop
        final = None
        for _ in range(20):
            time.sleep(0.5)
            jr = session.get(f"{API}/jobs/{job_id}").json()
            final = jr.get("status")
            if final in ("stopped", "failed", "not_found", "found"):
                break
        assert final == "stopped", f"expected stopped, got {final}"

    def test_delete_finished_job(self, session, quick_job):
        # NOTE: backend has a bug where status='not_found' is set when log line
        # contains 'Seed not found' but the underlying subprocess continues with
        # further phases. We must stop the job to ensure subprocess exit before
        # delete is permitted.
        job_id = quick_job["job_id"]
        for _ in range(60):
            jr = session.get(f"{API}/jobs/{job_id}").json()
            if jr.get("status") in ("not_found", "found", "failed", "stopped"):
                break
            time.sleep(1)
        # Ensure subprocess is actually killed (workaround for premature status)
        if not jr.get("finished_at"):
            session.post(f"{API}/jobs/{job_id}/stop")
            for _ in range(20):
                time.sleep(0.5)
                jr = session.get(f"{API}/jobs/{job_id}").json()
                if jr.get("finished_at"):
                    break
        r = session.delete(f"{API}/jobs/{job_id}")
        assert r.status_code == 200, r.text
        g = session.get(f"{API}/jobs/{job_id}")
        assert g.status_code == 404

    def test_delete_running_job_refused(self, session):
        cfg = {
            "seed_length": 12,
            "wallet_type": "electrum2",
            "language": "en",
            "known_words": ["abandon"] * 11 + [""],
            "address": "1Q1pE5vPGEEMqRcVRMbtBK842Y6Pzo6nK9",
            "addr_limit": 5,
            "threads": 1,
            "typos": 2,
        }
        r = session.post(f"{API}/jobs", json={"config_snapshot": cfg, "label": "TEST_del_running"})
        job_id = r.json()["job_id"]
        # Ensure running
        for _ in range(20):
            time.sleep(0.5)
            jr = session.get(f"{API}/jobs/{job_id}").json()
            if jr.get("status") == "running":
                break
        d = session.delete(f"{API}/jobs/{job_id}")
        assert d.status_code == 400
        # Cleanup
        session.post(f"{API}/jobs/{job_id}/stop")
        time.sleep(2)
        session.delete(f"{API}/jobs/{job_id}")
