"""
Tests for the BTC address verification preflight check (POST /api/address/verify).

Covers:
- Empty/missing address → HTTP 400
- Garbage → recommendation='invalid', format.valid=false
- Mainnet P2PKH (Genesis) → format.valid + on-chain history + recommendation='ok'
- Mainnet P2SH (Satoshi Dice) → valid + recommendation ∈ {ok, unused}
- BIP173 reference P2WPKH bech32 → valid p2wpkh + recommendation ∈ {ok, unused}
- BIP350 reference Taproot bech32m → valid p2tr
- Testnet bech32 (tb1...) → invalid for mainnet endpoint
- Acceptable "unknown" path if explorers unreachable from sandbox
- Smoke regression: system/status, config, wordlists/presets, jobs (list)
"""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

VERIFY_URL = f"{BASE_URL}/api/address/verify"

OK_RECOS = {"ok", "unused", "unknown"}  # unknown allowed if outbound HTTPS restricted


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- /api/address/verify ----------
class TestAddressVerify:
    def test_missing_address_returns_400(self, session):
        r = session.post(VERIFY_URL, json={})
        assert r.status_code == 400, r.text

    def test_empty_address_returns_400(self, session):
        r = session.post(VERIFY_URL, json={"address": "   "})
        assert r.status_code == 400, r.text

    def test_garbage_returns_invalid(self, session):
        r = session.post(VERIFY_URL, json={"address": "garbage"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["recommendation"] == "invalid"
        assert data["format"]["valid"] is False
        assert data["onchain"] is None
        assert isinstance(data.get("message"), str)
        assert data["message"].lower().startswith("invalid address")

    def test_genesis_p2pkh_ok_with_history(self, session):
        addr = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        r = session.post(VERIFY_URL, json={"address": addr}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["format"]["valid"] is True
        assert data["format"]["type"] == "p2pkh"
        if data["recommendation"] == "unknown":
            pytest.skip("Explorers unreachable from sandbox; format validated OK")
        assert data["recommendation"] == "ok"
        oc = data["onchain"]
        assert oc["reachable"] is True
        assert oc["has_history"] is True
        assert oc["tx_count"] > 0
        assert oc["balance_sats"] > 0
        assert "p2pkh" in data["message"]

    def test_p2sh_satoshi_dice(self, session):
        addr = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
        r = session.post(VERIFY_URL, json={"address": addr}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["format"]["valid"] is True
        assert data["format"]["type"] == "p2sh"
        assert data["recommendation"] in OK_RECOS

    def test_p2wpkh_bech32_reference(self, session):
        # BIP173 reference mainnet P2WPKH
        addr = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
        r = session.post(VERIFY_URL, json={"address": addr}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["format"]["valid"] is True
        assert data["format"]["type"] == "p2wpkh"
        assert data["recommendation"] in OK_RECOS

    def test_p2tr_bech32m_reference(self, session):
        # BIP350 reference Taproot
        addr = "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"
        r = session.post(VERIFY_URL, json={"address": addr}, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["format"]["valid"] is True
        assert data["format"]["type"] == "p2tr"
        assert data["recommendation"] in OK_RECOS

    def test_testnet_address_rejected_as_invalid(self, session):
        # tb1... is testnet bech32 — must be rejected by mainnet-only validator
        addr = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
        r = session.post(VERIFY_URL, json={"address": addr})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["format"]["valid"] is False
        assert data["recommendation"] == "invalid"

    def test_response_schema_keys(self, session):
        r = session.post(VERIFY_URL, json={"address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"}, timeout=20)
        assert r.status_code == 200
        data = r.json()
        for k in ("address", "format", "onchain", "recommendation", "message"):
            assert k in data, f"missing key {k}"
        assert "valid" in data["format"]
        assert "type" in data["format"]


# ---------- Regression smoke ----------
class TestRegressionSmoke:
    def test_system_status(self, session):
        r = session.get(f"{BASE_URL}/api/system/status", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, dict)

    def test_get_config(self, session):
        r = session.get(f"{BASE_URL}/api/config", timeout=10)
        assert r.status_code == 200, r.text

    def test_wordlists_presets(self, session):
        r = session.get(f"{BASE_URL}/api/wordlists/presets", timeout=10)
        assert r.status_code == 200, r.text
        assert "presets" in r.json()

    def test_jobs_list(self, session):
        r = session.get(f"{BASE_URL}/api/jobs", timeout=10)
        assert r.status_code == 200, r.text

    def test_masks_preview(self, session):
        # POST endpoint for preview — best-effort smoke
        r = session.post(f"{BASE_URL}/api/masks/preview", json={"mask": "?l?l?l?l", "limit": 5}, timeout=10)
        # endpoint may not accept exactly this; accept any non-5xx as smoke OK
        assert r.status_code < 500, r.text
