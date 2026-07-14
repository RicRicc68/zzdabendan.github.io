"""
Generazione segnali dai trade recenti dei top trader.
Espone sia la vecchia extract_fresh_signals (usata da main.py)
sia generate_signals + Signal (usati da paper_trading.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

from config import GAMMA_API
from leaderboard import fetch_trader_activity


@dataclass
class Signal:
    market_id: str          # conditionId del mercato
    outcome: str            # es. "Yes" / "No"
    action: str             # "BUY" o "SELL"
    trader_addr: str        # wallet del trader copiato
    weight: float = 0.0     # score del trader sorgente
    price: float = 0.0      # prezzo del trade osservato
    token_id: Optional[str] = None


def generate_signals(top_traders: list[dict], max_age_min: int = 10):
    """
    Analizza l'attività recente dei trader qualificati.
    Ritorna (signals, market_prices):
      - signals: lista di Signal (BUY/SELL)
      - market_prices: {market_id: {outcome: ultimo prezzo osservato}}
    top_traders: output di rank_traders() -> dict con chiave "wallet".
    """
    now = datetime.now(timezone.utc).timestamp()
    signals: list[Signal] = []
    market_prices: dict[str, dict[str, float]] = {}

    for trader in top_traders[:20]:
        wallet = trader.get("wallet") or trader.get("proxyWallet")
        if not wallet:
            continue
        activity = fetch_trader_activity(wallet, limit=20)
        for trade in activity:
            if trade.get("type") != "TRADE":
                continue
            ts = trade.get("timestamp", 0) or 0
            if (now - ts) / 60 > max_age_min:
                continue

            market_id = trade.get("conditionId") or trade.get("market")
            outcome = trade.get("outcome")
            if not market_id or not outcome:
                continue

            side = str(trade.get("side", "BUY")).upper()
            try:
                price = float(trade.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0

            signals.append(
                Signal(
                    market_id=market_id,
                    outcome=outcome,
                    action="SELL" if side == "SELL" else "BUY",
                    trader_addr=wallet,
                    weight=trader.get("score", 0.0),
                    price=price,
                    token_id=trade.get("asset"),
                )
            )
            if 0.0 < price < 1.0:
                market_prices.setdefault(market_id, {})[outcome] = price

    # Ordina per peso decrescente (consenso dei trader migliori prima)
    signals.sort(key=lambda s: s.weight, reverse=True)
    return signals, market_prices


def fetch_market_prices(market_ids) -> dict[str, dict[str, float]]:
    """
    Recupera i prezzi correnti da Gamma API per una lista di conditionId.
    Serve per il mark-to-market delle posizioni aperte su mercati
    senza attività recente dei trader copiati.
    """
    prices: dict[str, dict[str, float]] = {}
    market_ids = [m for m in market_ids if m]
    if not market_ids:
        return prices

    # Gamma accetta condition_ids multipli come parametri ripetuti
    for i in range(0, len(market_ids), 20):
        batch = market_ids[i : i + 20]
        try:
            r = requests.get(
                f"{GAMMA_API}/markets",
                params=[("condition_ids", m) for m in batch],
                timeout=10,
            )
            r.raise_for_status()
            for mkt in r.json():
                cid = mkt.get("conditionId")
                outcomes = mkt.get("outcomes")
                out_prices = mkt.get("outcomePrices")
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)
                if isinstance(out_prices, str):
                    out_prices = json.loads(out_prices)
                if not cid or not outcomes or not out_prices:
                    continue
                prices[cid] = {
                    o: float(p) for o, p in zip(outcomes, out_prices)
                }
        except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
            print(f"[prices] errore batch {i}: {e}")
    return prices



def fetch_markets_info(market_ids) -> dict[str, dict]:
    """
    Info complete da Gamma per una lista di conditionId:
      {cid: {"closed": bool, "prices": {outcome: prezzo}}}
    A mercato risolto Gamma imposta closed=True e outcomePrices a 1/0:
    serve per chiudere posizioni su mercati spariti dal book.
    """
    info: dict[str, dict] = {}
    market_ids = [m for m in market_ids if m]
    if not market_ids:
        return info

    for i in range(0, len(market_ids), 20):
        batch = market_ids[i : i + 20]
        try:
            r = requests.get(
                f"{GAMMA_API}/markets",
                params=[("condition_ids", m) for m in batch],
                timeout=10,
            )
            r.raise_for_status()
            for mkt in r.json():
                cid = mkt.get("conditionId")
                outcomes = mkt.get("outcomes")
                out_prices = mkt.get("outcomePrices")
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)
                if isinstance(out_prices, str):
                    out_prices = json.loads(out_prices)
                if not cid or not outcomes or not out_prices:
                    continue
                info[cid] = {
                    "closed": bool(mkt.get("closed", False)),
                    "prices": {o: float(p) for o, p in zip(outcomes, out_prices)},
                }
        except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
            print(f"[markets_info] errore batch {i}: {e}")
    return info

def extract_fresh_signals(top_traders, max_age_min=10):
    """
    (Legacy, usata da main.py)
    Se più trader entrano sullo stesso mercato/lato -> segnale forte.
    """
    now = datetime.now(timezone.utc).timestamp()
    market_votes = {}

    for trader in top_traders[:20]:
        activity = fetch_trader_activity(trader["wallet"], limit=20)
        for trade in activity:
            if trade.get("type") != "TRADE":
                continue
            ts = trade.get("timestamp", 0)
            if (now - ts) / 60 > max_age_min:
                continue

            key = (trade.get("conditionId") or trade.get("market"), trade.get("outcome"))
            market_votes.setdefault(key, {"weight": 0, "traders": []})
            market_votes[key]["weight"] += trader["score"]
            market_votes[key]["traders"].append(trader["wallet"])

    signals = [
        {"market": k[0], "outcome": k[1], **v}
        for k, v in market_votes.items()
    ]
    return sorted(signals, key=lambda x: x["weight"], reverse=True)
