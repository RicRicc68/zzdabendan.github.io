"""Tests for POST /api/jobs/cost-estimate (Energy & GPU rental calculator)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://a1957061-8377-4647-b8b6-08939cffaadc.preview.emergentagent.com").rstrip("/")
ENDPOINT = f"{BASE_URL}/api/jobs/cost-estimate"

EXPECTED_GPUS = [
    "vast.ai · RTX 3060",
    "vast.ai · RTX 3090",
    "vast.ai · RTX 4090",
    "RunPod · RTX A4000",
    "RunPod · RTX A6000",
    "RunPod · A100 40GB",
    "RunPod · H100 80GB",
]


def _post(payload):
    r = requests.post(ENDPOINT, json=payload, timeout=15)
    return r


# --- Core schema & local energy math ---
class TestCostEstimateCore:
    def test_baseline_24h_returns_full_schema(self):
        r = _post({"eta_seconds": 86400, "system_watts": 150, "eur_per_kwh": 0.30})
        assert r.status_code == 200
        d = r.json()
        # schema
        for key in ("local", "gpu_options", "recommendation", "message", "assumptions"):
            assert key in d, f"missing key {key}"
        # local math
        assert d["local"]["energy_kwh"] == pytest.approx(3.6, rel=0.01)
        assert d["local"]["energy_cost_eur"] == pytest.approx(1.08, rel=0.02)
        assert d["local"]["classification"] in ("trivial", "low", "moderate", "high", "extreme")
        # gpu list
        assert isinstance(d["gpu_options"], list)
        assert len(d["gpu_options"]) == 7
        names = [g["name"] for g in d["gpu_options"]]
        for expected in EXPECTED_GPUS:
            assert expected in names, f"missing GPU option: {expected}"
        # per-GPU schema
        for g in d["gpu_options"]:
            for k in ("name", "provider", "speedup_x", "usd_per_hour", "eur_per_hour",
                      "eta_seconds", "eta_human", "rental_cost_eur", "savings_vs_local_eur",
                      "classification"):
                assert k in g, f"GPU {g.get('name')} missing key {k}"

    def test_baseline_24h_recommends_cheapest_gpu(self):
        r = _post({"eta_seconds": 86400, "system_watts": 150, "eur_per_kwh": 0.30})
        d = r.json()
        reco = d["recommendation"]
        # local energy €1.08 ; cheapest GPU is RTX 3090 at €0.24 (well below 60%)
        assert reco.startswith("gpu:"), f"expected gpu reco, got {reco}"
        # find cheapest gpu in returned list
        cheapest = min(d["gpu_options"], key=lambda o: o["rental_cost_eur"])
        assert reco == f"gpu:{cheapest['name']}"


# --- Recommendation branches ---
class TestRecommendation:
    def test_short_eta_recommends_local(self):
        r = _post({"eta_seconds": 1800, "system_watts": 150, "eur_per_kwh": 0.30})
        d = r.json()
        assert d["recommendation"] == "local", f"got {d['recommendation']}"

    def test_impossible_eta_recommends_do_not_run(self):
        r = _post({"eta_seconds": 1e10, "system_watts": 150, "eur_per_kwh": 0.30})
        d = r.json()
        assert d["recommendation"] == "do_not_run", f"got {d['recommendation']}"

    def test_zero_eta_returns_na(self):
        r = _post({"eta_seconds": 0, "system_watts": 150, "eur_per_kwh": 0.30})
        d = r.json()
        assert d["recommendation"] == "n/a"
        assert d["local"]["energy_cost_eur"] == 0


# --- Scaling parameters ---
class TestParameterScaling:
    def test_watts_and_kwh_scale_local_cost(self):
        base = _post({"eta_seconds": 86400, "system_watts": 150, "eur_per_kwh": 0.30}).json()
        scaled = _post({"eta_seconds": 86400, "system_watts": 300, "eur_per_kwh": 0.50}).json()
        # 300/150 * 0.50/0.30 = 2 * 1.6667 = 3.333x
        expected_ratio = (300 / 150) * (0.50 / 0.30)
        actual_ratio = scaled["local"]["energy_cost_eur"] / base["local"]["energy_cost_eur"]
        assert actual_ratio == pytest.approx(expected_ratio, rel=0.02)

    def test_usd_to_eur_affects_gpu_eur_per_hour(self):
        d_default = _post({"eta_seconds": 86400, "system_watts": 150, "eur_per_kwh": 0.30,
                           "usd_to_eur": 0.92}).json()
        d_higher = _post({"eta_seconds": 86400, "system_watts": 150, "eur_per_kwh": 0.30,
                          "usd_to_eur": 1.10}).json()
        for g_def, g_hi in zip(d_default["gpu_options"], d_higher["gpu_options"]):
            assert g_hi["eur_per_hour"] > g_def["eur_per_hour"], f"{g_def['name']} eur_per_hour not scaled"
            # ratio should equal 1.10/0.92
            ratio = g_hi["eur_per_hour"] / g_def["eur_per_hour"]
            assert ratio == pytest.approx(1.10 / 0.92, rel=0.02)


# --- Provisioning overhead ---
class TestProvisioningOverhead:
    def test_default_overhead_10min_added_to_each_gpu_eta(self):
        # eta_seconds = 0 -> gpu_eta should equal overhead alone (600s)
        r = _post({"eta_seconds": 0.001, "system_watts": 150, "eur_per_kwh": 0.30})
        d = r.json()
        for g in d["gpu_options"]:
            # raw work = 0.001 / speedup ≈ 0 ; eta should be ~600s (10 min overhead)
            assert g["eta_seconds"] == pytest.approx(600.0, abs=1.0), \
                f"{g['name']} eta_seconds={g['eta_seconds']}, expected ~600s"

    def test_custom_overhead_changes_gpu_eta(self):
        # Use overhead=30 minutes (1800s) to verify overhead value is honoured.
        # Note: overhead=0 gets silently replaced by default 10 due to `payload.get(...) or 10`
        # idiom in server.py — see backend_issues.minor in test report.
        r = _post({"eta_seconds": 86400, "system_watts": 150, "eur_per_kwh": 0.30,
                   "provisioning_overhead_min": 30})
        d = r.json()
        gpu_3090 = next(g for g in d["gpu_options"] if "3090" in g["name"])
        # speedup 35 -> 86400/35 + 30*60 = 2468.57 + 1800 = 4268.57
        assert gpu_3090["eta_seconds"] == pytest.approx(86400 / 35 + 1800, abs=1.0)


# --- Regression smoke ---
class TestRegressionSmoke:
    def test_config_get(self):
        r = requests.get(f"{BASE_URL}/api/config", timeout=10)
        assert r.status_code == 200

    def test_estimate(self):
        r = requests.post(f"{BASE_URL}/api/jobs/estimate", json={
            "seed_length": 12, "known_words": ["abandon"] * 9, "typos": 0, "threads": 2,
            "wordlist_size": 2048, "rate_per_thread": 50000
        }, timeout=10)
        assert r.status_code == 200
        assert "eta_seconds" in r.json()

    def test_wordlist(self):
        r = requests.get(f"{BASE_URL}/api/wordlist", timeout=10)
        assert r.status_code == 200

    def test_jobs_list(self):
        r = requests.get(f"{BASE_URL}/api/jobs", timeout=10)
        assert r.status_code == 200

    def test_address_verify(self):
        r = requests.post(f"{BASE_URL}/api/address/verify",
                          json={"address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"}, timeout=15)
        assert r.status_code == 200
