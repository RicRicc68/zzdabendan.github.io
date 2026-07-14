"""
Riconciliazione del ledger live con lo stato reale dei mercati.
v2 — tre fonti in cascata:
  1. CLOB  /markets/{conditionId}      (flag closed + token winner)
  2. Gamma /markets?condition_ids=...  (outcomePrices)
  3. Data-API /positions?user=FUNDER   (le TUE posizioni reali on-chain)

Uso:  python3 sync_ledger.py --dry-run   (solo diagnosi, non scrive)
      python3 sync_ledger.py             (chiede conferma prima di scrivere)
"""

from __future__ import annotations

import sys
import json
import shutil
import requests
from pathlib import Path
from datetime import datetime, timezone

from config import CLOB_API, DATA_API, POLY_FUNDER
from signals import fetch_markets_info

LEDGER = Path("live_ledger.json")


def from_clob(cid: str) -> dict | None:
    """CLOB /markets/{cid}: closed + winner per token. Fonte più affidabile."""
    for path in (f"/markets/{cid}", f"/clob-markets/{cid}"):
        try:
            r = requests.get(f"{CLOB_API}{path}", timeout=10)
            if r.status_code != 200:
                continue
            m = r.json()
            if isinstance(m, dict) and "market" in m:
                m = m["market"]
            tokens = m.get("tokens") or []
            if not tokens:
                continue
            prices = {}
            for t in tokens:
                out = t.get("outcome")
                if out is None:
                    continue
                if t.get("winner") is True:
                    prices[out] = 1.0
                elif t.get("winner") is False and m.get("closed"):
                    prices[out] = 0.0
                elif t.get("price") is not None:
                    prices[out] = float(t["price"])
            return {"closed": bool(m.get("closed")), "prices": prices,
                    "source": f"CLOB {path}"}
        except (requests.RequestException, ValueError):
            continue
    return None


def from_positions() -> dict:
    """
    Data-API: posizioni reali del deposit wallet.
    Ritorna {(conditionId, outcome): {"cur_price", "redeemable", "size"}}
    """
    if not POLY_FUNDER:
        return {}
    try:
        r = requests.get(
            f"{DATA_API}/positions",
            params={"user": POLY_FUNDER, "sizeThreshold": 0.01},
            timeout=10,
        )
        r.raise_for_status()
        out = {}
        for p in r.json():
            key = (p.get("conditionId"), p.get("outcome"))
            out[key] = {
                "cur_price": p.get("curPrice"),
                "redeemable": p.get("redeemable"),
                "size": p.get("size"),
            }
        return out
    except (requests.RequestException, ValueError) as e:
        print(f"[positions] errore: {e}")
        return {}


def main(dry_run: bool = False):
    if not LEDGER.exists():
        print(f"Ledger non trovato: {LEDGER}")
        return

    lg = json.loads(LEDGER.read_text())
    open_pos = [p for p in lg.get("positions", []) if not p.get("closed")]
    if not open_pos:
        print("Nessuna posizione aperta nel ledger, niente da fare.")
        return

    print(f"Posizioni aperte nel ledger: {len(open_pos)}\n")

    gamma = fetch_markets_info({p["market_id"] for p in open_pos})
    real_positions = from_positions()
    if real_positions:
        print(f"Posizioni reali sul deposit wallet: {len(real_positions)}")
        for (cid, out), v in real_positions.items():
            print(f"   . {out:<12} {str(cid)[:14]}… size={v['size']} "
                  f"curPrice={v['cur_price']} redeemable={v['redeemable']}")
        print()

    to_close = []
    for p in open_pos:
        cid, outcome = p["market_id"], p["outcome"]
        final = None
        via = None

        # 1. CLOB
        m = from_clob(cid)
        if m and m["closed"]:
            px = m["prices"].get(outcome)
            if px is not None:
                final = 1.0 if px >= 0.5 else 0.0
                via = m["source"]

        # 2. Gamma
        if final is None:
            g = gamma.get(cid)
            if g and g["closed"]:
                px = g["prices"].get(outcome)
                if px is not None:
                    final = 1.0 if px >= 0.5 else 0.0
                    via = "Gamma"

        # 3. Posizioni reali del wallet
        if final is None:
            rp = real_positions.get((cid, outcome))
            if rp and rp["cur_price"] is not None and (
                rp["redeemable"] or rp["cur_price"] in (0, 1, 0.0, 1.0)
            ):
                final = 1.0 if float(rp["cur_price"]) >= 0.5 else 0.0
                via = "Data-API positions"

        if final is None:
            print(f"  ? {outcome:<12} {cid[:14]}… stato non determinabile "
                  f"da nessuna fonte (lo lascio aperto)")
            continue

        pnl = p["shares"] * (final - p["entry_price"])
        tag = "WIN " if final == 1.0 else "LOSS"
        print(f"  {tag} {outcome:<12} entry={p['entry_price']:.3f} -> {final:.1f} "
              f"PnL={pnl:+.2f}$   [fonte: {via}]")
        to_close.append((p, final))

    if not to_close:
        print("\nNessuna posizione riconciliabile.")
        return

    total = sum(p["shares"] * (f - p["entry_price"]) for p, f in to_close)
    print(f"\nDa chiudere: {len(to_close)} posizioni, PnL totale {total:+.2f}$")

    if dry_run:
        print("(dry-run: ledger NON modificato)")
        return

    if input("\nConfermi la scrittura sul ledger? [s/N] ").strip().lower() != "s":
        print("Annullato.")
        return

    backup = LEDGER.with_suffix(f".backup-{datetime.now():%Y%m%d-%H%M%S}.json")
    shutil.copy(LEDGER, backup)
    print(f"Backup creato: {backup}")

    now = datetime.now(timezone.utc).isoformat()
    for p, final in to_close:
        pnl = p["shares"] * (final - p["entry_price"])
        p["closed"] = True
        p["exit_price"] = final
        p["closed_at"] = now
        p["pnl_usd"] = pnl
        lg["realized_pnl"] = lg.get("realized_pnl", 0.0) + pnl
        lg.setdefault("history", []).append({
            "event": "CLOSE", "ts": now,
            "reason": "market_resolved_win" if final == 1.0 else "market_resolved_loss",
            "note": "riconciliato da sync_ledger.py", **p,
        })

    LEDGER.write_text(json.dumps(lg, indent=2))
    print(f"Ledger aggiornato: PnL realizzato ora {lg['realized_pnl']:+.2f}$")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
