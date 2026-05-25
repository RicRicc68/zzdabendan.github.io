"""Backend tests for the Recovery Presets feature (GET /api/presets, POST /apply)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL"):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass

API = f"{BASE_URL}/api"

EXPECTED_IDS = {
    "bip39_12_one_unknown",
    "bip39_12_two_unknown",
    "bip39_24_two_unknown",
    "electrum2_12_one_unknown",
    "electrum1_12",
    "bip39_12_typo",
    "bip39_24_three_unknown_unpositioned",
    "blank",
}

VALID_DIFFICULTY = {"fast", "moderate", "slow", "very_slow", "impractical"}
VALID_WALLET = {"bip39", "electrum1", "electrum2"}


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# -------- List presets --------
class TestListPresets:
    def test_list_returns_eight(self, session):
        r = session.get(f"{API}/presets")
        assert r.status_code == 200
        data = r.json()
        assert "presets" in data
        assert isinstance(data["presets"], list)
        assert len(data["presets"]) == 8

    def test_list_ids_match_expected(self, session):
        r = session.get(f"{API}/presets")
        ids = {p["id"] for p in r.json()["presets"]}
        assert ids == EXPECTED_IDS

    def test_entry_shape(self, session):
        r = session.get(f"{API}/presets")
        for p in r.json()["presets"]:
            for field in ("id", "name", "tagline", "use_case", "difficulty",
                          "icon", "seed_length", "wallet_type", "typos",
                          "wordlist_preset", "hint"):
                assert field in p, f"missing {field} in {p['id']}"
            assert p["difficulty"] in VALID_DIFFICULTY
            assert p["seed_length"] in (12, 24)
            assert p["wallet_type"] in VALID_WALLET
            assert isinstance(p["typos"], int)
            # wordlist_preset is str or None
            assert p["wordlist_preset"] is None or isinstance(p["wordlist_preset"], str)
            assert isinstance(p["hint"], str) and len(p["hint"]) > 0


# -------- Apply presets --------
class TestApplyPresets:
    def test_apply_bip39_12_one_unknown(self, session):
        r = session.post(f"{API}/presets/bip39_12_one_unknown/apply")
        assert r.status_code == 200
        data = r.json()
        assert data["applied_preset"] == "bip39_12_one_unknown"
        c = data["config"]
        assert c["seed_length"] == 12
        assert c["wallet_type"] == "bip39"
        assert c["typos"] == 0
        assert c["addr_limit"] == 20
        assert c["threads"] == 4
        assert isinstance(c["known_words"], list) and len(c["known_words"]) == 12
        assert all(w == "" for w in c["known_words"])
        assert data["wordlist"]["loaded"] == "bip39-en"
        assert data["wordlist"]["count"] == 2048
        assert isinstance(data["hint"], str) and len(data["hint"]) > 0

    def test_apply_electrum1_12_loads_wordlist(self, session):
        r = session.post(f"{API}/presets/electrum1_12/apply")
        assert r.status_code == 200
        data = r.json()
        assert data["config"]["wallet_type"] == "electrum1"
        assert data["wordlist"]["loaded"] == "electrum1-en"
        # Electrum1 dictionary is exactly 1626 words.
        assert data["wordlist"]["count"] == 1626

    def test_apply_bip39_24_two_unknown(self, session):
        r = session.post(f"{API}/presets/bip39_24_two_unknown/apply")
        assert r.status_code == 200
        c = r.json()["config"]
        assert c["seed_length"] == 24
        assert len(c["known_words"]) == 24
        assert all(w == "" for w in c["known_words"])

    def test_apply_bip39_12_typo(self, session):
        r = session.post(f"{API}/presets/bip39_12_typo/apply")
        assert r.status_code == 200
        c = r.json()["config"]
        assert c["seed_length"] == 12
        assert c["typos"] == 1

    def test_apply_blank_no_wordlist(self, session):
        r = session.post(f"{API}/presets/blank/apply")
        assert r.status_code == 200
        data = r.json()
        c = data["config"]
        assert all(w == "" for w in c["known_words"])
        assert c["address"] == ""
        assert data["wordlist"] is None

    def test_apply_invalid_returns_404(self, session):
        r = session.post(f"{API}/presets/invalid_id/apply")
        assert r.status_code == 404
        # FastAPI error envelope
        body = r.json()
        detail = body.get("detail") or body.get("message") or ""
        assert "invalid_id" in detail.lower() or "not found" in detail.lower()


# -------- Persistence to /api/config --------
class TestApplyPersistence:
    def test_config_reflects_applied_preset(self, session):
        # Apply an electrum1 preset then read config
        r = session.post(f"{API}/presets/electrum1_12/apply")
        assert r.status_code == 200
        r2 = session.get(f"{API}/config")
        assert r2.status_code == 200
        cfg = r2.json()
        assert cfg["wallet_type"] == "electrum1"
        assert cfg["seed_length"] == 12

    def test_wordlist_count_after_electrum1(self, session):
        session.post(f"{API}/presets/electrum1_12/apply")
        r = session.get(f"{API}/wordlist")
        assert r.status_code == 200
        d = r.json()
        # field name may be "count" — fall back gracefully
        count = d.get("count") or d.get("word_count") or len(d.get("words", []))
        assert count == 1626, f"expected 1626 electrum1 words, got {count}"

    def test_apply_24_then_get_config(self, session):
        session.post(f"{API}/presets/bip39_24_two_unknown/apply")
        r = session.get(f"{API}/config")
        cfg = r.json()
        assert cfg["seed_length"] == 24
        assert len(cfg["known_words"]) == 24
