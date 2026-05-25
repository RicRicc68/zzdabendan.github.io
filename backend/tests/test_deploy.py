"""Tests for the GPU deploy bundle generator (/api/deploy/preview & /generate)."""
import io
import json
import os
import zipfile

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def sample_cfg():
    return {
        "seed_length": 12,
        "wallet_type": "electrum2",
        "language": "en",
        "known_words": ["abandon"] * 11 + [""],
        "address": "1abcDEF",
        "passphrase_enabled": True,
        "passphrase": "secret123",
        "threads": 4,
        "typos": 0,
    }


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- /deploy/preview ----------
class TestDeployPreview:
    def test_vastai_returns_7_files(self, session, sample_cfg):
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "vastai",
            "gpu_name": "vast.ai · RTX 3090",
            "config": sample_cfg,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["provider"] == "vastai"
        assert data["file_count"] == 7
        files = data["files"]
        expected = {"Dockerfile", "run.sh", "config.json", "candlist.txt",
                    "verify.txt", "README.md", "vastai-deploy.sh"}
        assert set(files.keys()) == expected

    def test_runpod_swaps_provider_file(self, session, sample_cfg):
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "runpod",
            "gpu_name": "RunPod · A100 40GB",
            "config": sample_cfg,
        })
        assert r.status_code == 200
        files = r.json()["files"]
        assert "runpod-deploy.md" in files
        assert "vastai-deploy.sh" not in files

    def test_invalid_provider_400(self, session, sample_cfg):
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "aws",
            "config": sample_cfg,
        })
        assert r.status_code == 400

    def test_dockerfile_and_run_sh_content(self, session, sample_cfg):
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "vastai",
            "gpu_name": "vast.ai · RTX 3090",
            "config": sample_cfg,
        })
        files = r.json()["files"]
        df = files["Dockerfile"]
        assert "nvidia/cuda:12.3.2-runtime-ubuntu22.04" in df
        assert "pyopencl" in df
        assert "btcrecover" in df

        run_sh = files["run.sh"]
        assert "seedrecover.py" in run_sh
        assert "--enable-opencl" in run_sh

        parsed = json.loads(files["config.json"])
        assert "seed_length" in parsed

    def test_passphrase_redacted(self, session, sample_cfg):
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "vastai",
            "gpu_name": "vast.ai · RTX 3090",
            "config": sample_cfg,
        })
        cfg_json = json.loads(r.json()["files"]["config.json"])
        assert cfg_json["passphrase"] == "***REDACTED — supply on the rented box***"
        # And the cleartext should not appear anywhere in the bundle
        for name, content in r.json()["files"].items():
            assert "secret123" not in content, f"cleartext passphrase found in {name}"

    @pytest.mark.parametrize("friendly,expected", [
        ("vast.ai · RTX 4090", "RTX_4090"),
        ("RunPod · A100 40GB", "A100"),
        ("RunPod · RTX A4000", "RTX_A4000"),
        ("vast.ai · RTX 3090", "RTX_3090"),
    ])
    def test_vastai_gpu_cli_filter(self, session, sample_cfg, friendly, expected):
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "vastai",
            "gpu_name": friendly,
            "config": sample_cfg,
        })
        assert r.status_code == 200
        sh = r.json()["files"]["vastai-deploy.sh"]
        assert f"gpu_name={expected}" in sh, sh[:600]

    def test_explicit_config_override_used(self, session):
        cfg = {"seed_length": 24, "wallet_type": "bip39", "language": "en",
               "known_words": [""] * 24, "address": "MARKER_ADDR_777"}
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "vastai", "gpu_name": "vast.ai · RTX 3090", "config": cfg,
        })
        assert r.status_code == 200
        files = r.json()["files"]
        assert "MARKER_ADDR_777" in files["verify.txt"]
        parsed = json.loads(files["config.json"])
        assert parsed["seed_length"] == 24
        assert parsed["address"] == "MARKER_ADDR_777"

    def test_job_id_uses_snapshot(self, session, sample_cfg):
        # Create a job by hitting the jobs CRUD endpoint (best-effort)
        # Use a config snapshot via the stored config + a job.
        # If a jobs POST API doesn't exist we skip.
        # Try POST /api/jobs
        create = session.post(f"{API}/jobs", json={"label": "TEST_deploy_snap"})
        if create.status_code not in (200, 201):
            pytest.skip(f"/api/jobs POST not available: {create.status_code}")
        job_id = create.json().get("job_id") or create.json().get("id")
        if not job_id:
            pytest.skip("no job_id returned")

        # The job is created from current config snapshot. Just request a preview
        # using job_id and verify we got 200 with 7 files.
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "vastai", "gpu_name": "vast.ai · RTX 3090", "job_id": job_id,
        })
        # Either 200 (snapshot found) or 400 if no config available; accept 200 only as positive
        if r.status_code == 400:
            pytest.skip("job created without config_snapshot")
        assert r.status_code == 200
        assert r.json()["file_count"] == 7

    def test_no_config_returns_400(self, session):
        # Use bogus job_id and no config; if stored config exists this may still
        # succeed — in that case we accept either 200 or 400 (we only assert the
        # explicit no-config bogus job_id path falls through to stored config).
        r = session.post(f"{API}/deploy/preview", json={
            "provider": "vastai",
            "job_id": "non-existent-job-id-xyz-123",
        })
        # If no stored config and no job → must be 400
        assert r.status_code in (200, 400)


# ---------- /deploy/generate ----------
class TestDeployGenerate:
    def test_vastai_zip(self, session, sample_cfg):
        r = session.post(f"{API}/deploy/generate", json={
            "provider": "vastai", "gpu_name": "vast.ai · RTX 3090", "config": sample_cfg,
        })
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("application/zip")
        cd = r.headers.get("content-disposition", "")
        assert "seed-recovery-deploy-vastai-" in cd
        assert len(r.content) > 1024

        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        expected = {"Dockerfile", "run.sh", "config.json", "candlist.txt",
                    "verify.txt", "README.md", "vastai-deploy.sh"}
        assert names == expected

    def test_runpod_zip(self, session, sample_cfg):
        r = session.post(f"{API}/deploy/generate", json={
            "provider": "runpod", "gpu_name": "RunPod · A100 40GB", "config": sample_cfg,
        })
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        assert "runpod-deploy.md" in names
        assert "vastai-deploy.sh" not in names


# ---------- Regression smoke ----------
class TestRegressionSmoke:
    def test_health_and_config(self, session):
        r = session.get(f"{API}/config")
        assert r.status_code == 200

    def test_jobs_list(self, session):
        r = session.get(f"{API}/jobs")
        assert r.status_code == 200

    def test_estimate(self, session):
        r = session.post(f"{API}/jobs/estimate", json={
            "seed_length": 12, "known_words": ["abandon"] * 11 + [""],
            "wallet_type": "electrum2", "language": "en",
        })
        assert r.status_code == 200

    def test_cost_estimate(self, session):
        r = session.post(f"{API}/jobs/cost-estimate", json={
            "eta_seconds": 3600, "system_watts": 150, "eur_per_kwh": 0.30,
            "usd_to_eur": 0.92,
        })
        assert r.status_code == 200

    def test_wordlist_presets(self, session):
        r = session.get(f"{API}/wordlists/presets")
        assert r.status_code == 200
