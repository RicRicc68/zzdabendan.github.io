"""Tests for the signed-JSON audit-trail export feature."""
import copy
import os
import re
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def archived_job_id(client):
    r = client.get(f"{BASE_URL}/api/jobs?limit=50", timeout=15)
    assert r.status_code == 200
    jobs = r.json()
    # pick a finished, non-running job that should be on-disk/Mongo only
    for j in jobs:
        if j.get("status") in ("not_found", "stopped", "failed", "found"):
            return j["job_id"]
    pytest.skip("No archived finished job available")


# --- Schema / signature -------------------------------------------------
class TestExportSchema:
    def test_default_export_schema(self, client, archived_job_id):
        r = client.get(f"{BASE_URL}/api/jobs/{archived_job_id}/export", timeout=15)
        assert r.status_code == 200
        p = r.json()
        assert p["schema"] == "seed-recovery-audit/v1"
        # job block
        for k in ("job_id", "label", "status", "started_at", "finished_at",
                  "duration_seconds", "error"):
            assert k in p["job"], f"missing job.{k}"
        assert p["job"]["job_id"] == archived_job_id
        # tool block
        for k in ("name", "path", "version"):
            assert k in p["tool"]
        assert "command" in p and isinstance(p["command"], list)
        assert "config_snapshot" in p
        assert "stats" in p
        # result with seed redacted by default
        assert p["result"]["seed"] is None
        assert "found" in p["result"] and "seed_redacted" in p["result"]
        # logs default: not included
        assert p["logs"]["included"] is False
        assert p["logs"]["lines"] is None
        assert isinstance(p["logs"]["count"], int)
        assert HEX64.match(p["logs"]["sha256"])
        # signature
        assert p["signature"]["algorithm"] == "HMAC-SHA256"
        assert HEX64.match(p["signature"]["value"])

    def test_include_logs_true(self, client, archived_job_id):
        import hashlib
        r = client.get(
            f"{BASE_URL}/api/jobs/{archived_job_id}/export",
            params={"include_logs": "true"}, timeout=15,
        )
        assert r.status_code == 200
        p = r.json()
        assert p["logs"]["included"] is True
        assert isinstance(p["logs"]["lines"], list)
        # Recompute hash exactly as backend does
        h = hashlib.sha256()
        for e in p["logs"]["lines"]:
            h.update(f"{e.get('stream','')}:{e.get('line','')}\n".encode("utf-8", errors="replace"))
        assert h.hexdigest() == p["logs"]["sha256"]
        assert p["logs"]["count"] == len(p["logs"]["lines"])

    def test_redact_seed_false_no_found(self, client, archived_job_id):
        # An archived job we picked is likely not "found" → seed stays None
        r = client.get(
            f"{BASE_URL}/api/jobs/{archived_job_id}/export",
            params={"redact_seed": "false"}, timeout=15,
        )
        assert r.status_code == 200
        p = r.json()
        # If no found_seed: seed is None and seed_redacted is False
        if not p["result"]["found"]:
            assert p["result"]["seed"] is None
            assert p["result"]["seed_redacted"] is False

    def test_missing_job_404(self, client):
        r = client.get(f"{BASE_URL}/api/jobs/does-not-exist-xyz/export", timeout=10)
        assert r.status_code == 404


# --- Verify endpoint ----------------------------------------------------
class TestVerify:
    def test_clean_payload_valid(self, client, archived_job_id):
        r = client.get(
            f"{BASE_URL}/api/jobs/{archived_job_id}/export",
            params={"include_logs": "true"}, timeout=15,
        )
        payload = r.json()
        v = client.post(f"{BASE_URL}/api/exports/verify", json=payload, timeout=15)
        assert v.status_code == 200
        data = v.json()
        assert data["valid"] is True
        assert data["expected"] == data["received"]
        assert data["logs_hash_ok"] is True

    def test_tampered_payload_invalid(self, client, archived_job_id):
        r = client.get(f"{BASE_URL}/api/jobs/{archived_job_id}/export", timeout=15)
        payload = r.json()
        tampered = copy.deepcopy(payload)
        tampered["job"]["label"] = "TAMPERED-LABEL-XYZ"
        v = client.post(f"{BASE_URL}/api/exports/verify", json=tampered, timeout=15)
        assert v.status_code == 200
        data = v.json()
        assert data["valid"] is False
        assert data["expected"] != data["received"]

    def test_missing_signature_400(self, client, archived_job_id):
        r = client.get(f"{BASE_URL}/api/jobs/{archived_job_id}/export", timeout=15)
        payload = r.json()
        payload.pop("signature", None)
        v = client.post(f"{BASE_URL}/api/exports/verify", json=payload, timeout=15)
        assert v.status_code == 400


# --- Passphrase redaction ----------------------------------------------
class TestPassphraseRedaction:
    def test_passphrase_redacted_in_export(self, client):
        # Create a job with passphrase set and verify export redacts it.
        cfg = {
            "seed_length": 12,
            "wallet_type": "electrum2",
            "language": "en",
            "known_words": ["abandon"] * 11 + [""],
            "address": "1Q1pE5vPGEEMqRcVRMbtBK842Y6Pzo6nK9",
            "addr_limit": 2,
            "threads": 1,
            "typos": 0,
            "passphrase_enabled": True,
            "passphrase": "secret123",
        }
        cj = client.post(
            f"{BASE_URL}/api/jobs",
            json={"config_snapshot": cfg, "label": "TEST_export_redact"},
            timeout=15,
        )
        assert cj.status_code == 200, cj.text
        job_id = cj.json()["job_id"]
        # Wait for job to finish (will quickly fail/exhaust with our masks)
        deadline = time.time() + 60
        status = None
        while time.time() < deadline:
            g = client.get(f"{BASE_URL}/api/jobs/{job_id}", timeout=10)
            if g.status_code == 200:
                status = g.json().get("status")
                if status in ("not_found", "stopped", "failed", "found"):
                    break
            time.sleep(1)
        # Export — even if running, we expect 200 (in-memory path)
        e = client.get(f"{BASE_URL}/api/jobs/{job_id}/export", timeout=15)
        assert e.status_code == 200, e.text
        p = e.json()
        cs = p.get("config_snapshot", {})
        assert cs.get("passphrase") == "***REDACTED***", cs
        # Signature verifies on the (redacted) payload
        v = client.post(f"{BASE_URL}/api/exports/verify", json=p, timeout=15)
        assert v.status_code == 200 and v.json()["valid"] is True
        # cleanup
        client.delete(f"{BASE_URL}/api/jobs/{job_id}", timeout=10)


# --- In-memory vs archived path ----------------------------------------
class TestInMemoryExport:
    def test_export_for_in_memory_job(self, client):
        cfg = {
            "seed_length": 12, "wallet_type": "electrum2", "language": "en",
            "known_words": ["abandon"] * 11 + [""],
            "address": "1Q1pE5vPGEEMqRcVRMbtBK842Y6Pzo6nK9",
            "addr_limit": 2, "threads": 1, "typos": 0,
        }
        cj = client.post(
            f"{BASE_URL}/api/jobs",
            json={"config_snapshot": cfg, "label": "TEST_export_inmem"},
            timeout=15,
        )
        assert cj.status_code == 200
        job_id = cj.json()["job_id"]
        # Immediately export while likely still running / just started
        e = client.get(f"{BASE_URL}/api/jobs/{job_id}/export", timeout=15)
        assert e.status_code == 200
        p = e.json()
        assert p["job"]["job_id"] == job_id
        assert HEX64.match(p["signature"]["value"])
        # cleanup after job finishes
        time.sleep(3)
        client.delete(f"{BASE_URL}/api/jobs/{job_id}", timeout=10)


# --- Smoke regression --------------------------------------------------
class TestSmokeRegression:
    @pytest.mark.parametrize("path", [
        "/api/config",
        "/api/wordlist",
        "/api/wordlists/presets",
        "/api/jobs?limit=5",
        "/api/system/status",
    ])
    def test_smoke_endpoints(self, client, path):
        r = client.get(f"{BASE_URL}{path}", timeout=10)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:200]}"

    def test_masks_preview(self, client):
        r = client.post(
            f"{BASE_URL}/api/masks/preview",
            json={"seed_length": 12, "known_words": ["abandon"] * 5 + [""] * 7},
            timeout=10,
        )
        assert r.status_code == 200
        assert "fixed_mask" in r.json()

    def test_estimate(self, client):
        r = client.post(
            f"{BASE_URL}/api/jobs/estimate",
            json={"seed_length": 12, "known_words": ["abandon"] * 11 + [""], "threads": 1},
            timeout=10,
        )
        assert r.status_code == 200
        assert "eta_human" in r.json()
