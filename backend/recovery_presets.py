"""
Recovery presets — curated scenarios that pre-fill the seed configuration so
non-technical users can start a recovery in one click. Each preset is a
declarative spec; the frontend applies it to the current config.

Designed to cover the most common real-world cases:
- Owner of a hardware wallet (Trezor/Ledger) with 1-2 forgotten words
- Electrum desktop wallet with partial recall
- Recovery against a clear typo or transcription mistake
"""
from __future__ import annotations

from typing import Any, Dict, List

PRESETS: List[Dict[str, Any]] = [
    {
        "id": "bip39_12_one_unknown",
        "name": "BIP39 · 12-word · 1 unknown",
        "tagline": "Trezor / Ledger / most BIP39 wallets — I remember 11 of 12 words.",
        "use_case": "You recall 11 out of 12 seed words at their correct positions, and one slot is completely blank.",
        "difficulty": "fast",
        "icon": "shield",
        "config": {
            "seed_length": 12,
            "wallet_type": "bip39",
            "language": "en",
            "typos": 0,
            "threads": 4,
            "addr_limit": 20,
        },
        "wordlist_preset": "bip39-en",
        "hint": "Leave the unknown slot empty and paste your BTC address in the verification target.",
    },
    {
        "id": "bip39_12_two_unknown",
        "name": "BIP39 · 12-word · 2 unknown",
        "tagline": "BIP39 with two missing words at known positions.",
        "use_case": "You remember 10 of 12 words at the correct positions, with two specific gaps. Best with a full BIP39 wordlist (2048 candidates).",
        "difficulty": "moderate",
        "icon": "key",
        "config": {
            "seed_length": 12,
            "wallet_type": "bip39",
            "language": "en",
            "typos": 0,
            "threads": 4,
            "addr_limit": 20,
        },
        "wordlist_preset": "bip39-en",
        "hint": "Expect minutes to a few hours on CPU; consider a GPU rental from the Energy panel.",
    },
    {
        "id": "bip39_24_two_unknown",
        "name": "BIP39 · 24-word · 2 unknown",
        "tagline": "Hardware-wallet 24-word seed, two known gaps.",
        "use_case": "Trezor Model T / Ledger Nano X / Coldcard 24-word seed with two blank positions.",
        "difficulty": "moderate",
        "icon": "shield",
        "config": {
            "seed_length": 24,
            "wallet_type": "bip39",
            "language": "en",
            "typos": 0,
            "threads": 4,
            "addr_limit": 50,
        },
        "wordlist_preset": "bip39-en",
        "hint": "24-word seeds have much wider entropy — use the same flow but expect proportionally longer ETA.",
    },
    {
        "id": "electrum2_12_one_unknown",
        "name": "Electrum 2 · 12-word · 1 unknown",
        "tagline": "Electrum desktop wallet (post-2.0) — single missing word.",
        "use_case": "Electrum-format 12-word seed (uses BIP39 dictionary but a different checksum). One missing slot.",
        "difficulty": "fast",
        "icon": "wallet",
        "config": {
            "seed_length": 12,
            "wallet_type": "electrum2",
            "language": "en",
            "typos": 0,
            "threads": 4,
            "addr_limit": 10,
        },
        "wordlist_preset": "bip39-en",
        "hint": "Make sure 'Electrum v2' is selected in wallet type — Electrum's checksum filters out most wrong combos quickly.",
    },
    {
        "id": "electrum1_12",
        "name": "Electrum 1 · 12-word seed",
        "tagline": "Legacy Electrum (pre-2.0) — uses its own 1626-word dictionary.",
        "use_case": "Wallets created with Electrum 1.x. The wordlist is different from BIP39, so make sure to load the electrum1-en preset.",
        "difficulty": "fast",
        "icon": "wallet",
        "config": {
            "seed_length": 12,
            "wallet_type": "electrum1",
            "language": "en",
            "typos": 0,
            "threads": 4,
            "addr_limit": 10,
        },
        "wordlist_preset": "electrum1-en",
        "hint": "Electrum 1 wordlist is loaded automatically; don't mix with BIP39 words.",
    },
    {
        "id": "bip39_12_typo",
        "name": "BIP39 · 12-word · 1 typo",
        "tagline": "All 12 words known but one is misspelled.",
        "use_case": "You wrote down all 12 words but one of them has a typo (single-letter substitution). seedrecover will try BIP39-near variants for every word.",
        "difficulty": "slow",
        "icon": "alert-triangle",
        "config": {
            "seed_length": 12,
            "wallet_type": "bip39",
            "language": "en",
            "typos": 1,
            "threads": 4,
            "addr_limit": 20,
        },
        "wordlist_preset": "bip39-en",
        "hint": "Typo tolerance expands the search 2048× — definitely worth checking the GPU cost projection first.",
    },
    {
        "id": "bip39_24_three_unknown_unpositioned",
        "name": "BIP39 · 24-word · 3 known but unpositioned",
        "tagline": "Three words I remember but not where they go.",
        "use_case": "You have 24 words in total, of which 3 you know but cannot place. Combine with the Mask Preview 'unpositioned words' field.",
        "difficulty": "very_slow",
        "icon": "puzzle",
        "config": {
            "seed_length": 24,
            "wallet_type": "bip39",
            "language": "en",
            "typos": 0,
            "threads": 4,
            "addr_limit": 50,
        },
        "wordlist_preset": "bip39-en",
        "hint": "Use the Mask Preview panel to enter the 3 unpositioned words; combinations grow quickly so the GPU panel is recommended.",
    },
    {
        "id": "blank",
        "name": "Custom · blank slate",
        "tagline": "Start from scratch — I'll configure everything myself.",
        "use_case": "Power-user flow. Clears the form to defaults.",
        "difficulty": "fast",
        "icon": "settings",
        "config": {
            "seed_length": 12,
            "wallet_type": "bip39",
            "language": "en",
            "typos": 0,
            "threads": 2,
            "addr_limit": 10,
        },
        "wordlist_preset": None,
        "hint": "All fields blank; fill in the words you remember and pick the wallet type that matches.",
    },
]


PRESETS_INDEX: Dict[str, Dict[str, Any]] = {p["id"]: p for p in PRESETS}


def list_presets() -> List[Dict[str, Any]]:
    """Return the public catalog (excluding any internal fields)."""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "tagline": p["tagline"],
            "use_case": p["use_case"],
            "difficulty": p["difficulty"],
            "icon": p["icon"],
            "seed_length": p["config"]["seed_length"],
            "wallet_type": p["config"]["wallet_type"],
            "typos": p["config"]["typos"],
            "wordlist_preset": p.get("wordlist_preset"),
            "hint": p["hint"],
        }
        for p in PRESETS
    ]


def get_preset(preset_id: str) -> Dict[str, Any]:
    return PRESETS_INDEX[preset_id]
