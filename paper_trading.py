"""
Paper trading live: esegue la logica del bot in tempo reale
registrando ordini fittizi ai prezzi di mercato correnti.
Nessun capitale reale a rischio.
"""

from __future__ import annotations

import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

from config import (
    MAX_POSITION_PCT,
    POLL_INTERVAL_SEC,
    PAPER_BANKROLL_START,
)
from leaderboard import fetch_leaderboard
from trader_analysis import rank_traders
from signals import generate_signals, fetch_market_prices, Signal
import telegram_alerts as tg

logger = logging.getLogger("paper_trading")


@dataclass
class PaperPosition:
    market_id: str
    outcome: str          # "YES" / "NO"
    entry_price: float    # prezzo pagato per share (0-1)
    size_usd: float       # capitale impegnato
    shares: float         # size_usd / entry_price
    opened_at: str
    source_trader: str
    closed: bool = False
    exit_price: Optional[float] = None
    closed_at: Optional[str] = None
    pnl_usd: float = 0.0

    def mark_to_market(self, current_price: float) -> float:
        """PnL non realizzato al prezzo corrente."""
        if self.closed:
            return self.pnl_usd
        return self.shares * (current_price - self.entry_price)


@dataclass
class PaperLedger:
    bankroll: float = PAPER_BANKROLL_START
    positions: list[PaperPosition] = field(default_factory=list)
    realized_pnl: float = 0.0
    history: list[dict] = field(default_factory=list)

    @property
    def open_positions(self) -> list[PaperPosition]:
        return [p for p in self.positions if not p.closed]

    @property
    def committed_capital(self) -> float:
        return sum(p.size_usd for p in self.open_positions)

    @property
    def free_capital(self) -> float:
        return self.bankroll - self.committed_capital

    def equity(self, price_lookup) -> float:
        """Bankroll + PnL non realizzato di tutte le posizioni aperte."""
        unrealized = 0.0
        for p in self.open_positions:
            px = price_lookup(p.market_id, p.outcome)
            if px is not None:
                unrealized += p.mark_to_market(px)
        return self.bankroll + unrealized


class PaperTrader:
    def __init__(self, ledger_path: str = "paper_ledger.json"):
        self.ledger = PaperLedger()
        self.ledger_path = Path(ledger_path)
        self._load()

    # ---------- persistenza ----------

    def _load(self) -> None:
        if self.ledger_path.exists():
            raw = json.loads(self.ledger_path.read_text())
            self.ledger.bankroll = raw["bankroll"]
            self.ledger.realized_pnl = raw["realized_pnl"]
            self.ledger.history = raw.get("history", [])
            self.ledger.positions = [
                PaperPosition(**p) for p in raw.get("positions", [])
            ]
            logger.info(
                "Ledger caricato: bankroll=%.2f, posizioni aperte=%d",
                self.ledger.bankroll,
                len(self.ledger.open_positions),
            )

    def _save(self) -> None:
        payload = {
            "bankroll": self.ledger.bankroll,
            "realized_pnl": self.ledger.realized_pnl,
            "positions": [asdict(p) for p in self.ledger.positions],
            "history": self.ledger.history,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        self.ledger_path.write_text(json.dumps(payload, indent=2))

    # ---------- logica di trading ----------

    def _already_holds(self, market_id: str, outcome: str) -> bool:
        return any(
            p.market_id == market_id and p.outcome == outcome
            for p in self.ledger.open_positions
        )

    def open_position(self, sig: Signal, current_price: float) -> Optional[PaperPosition]:
        if self._already_holds(sig.market_id, sig.outcome):
            logger.debug("Posizione già aperta su %s/%s, skip", sig.market_id, sig.outcome)
            return None

        size = self.ledger.bankroll * MAX_POSITION_PCT
        if size > self.ledger.free_capital:
            logger.warning(
                "Capitale insufficiente: richiesto %.2f, libero %.2f",
                size,
                self.ledger.free_capital,
            )
            return None

        if current_price <= 0 or current_price >= 1:
            logger.warning("Prezzo fuori range (%.4f), skip", current_price)
            return None

        pos = PaperPosition(
            market_id=sig.market_id,
            outcome=sig.outcome,
            entry_price=current_price,
            size_usd=size,
            shares=size / current_price,
            opened_at=datetime.now(timezone.utc).isoformat(),
            source_trader=sig.trader_addr,
        )
        self.ledger.positions.append(pos)
        self.ledger.history.append(
            {"event": "OPEN", "ts": pos.opened_at, **asdict(pos)}
        )
        logger.info(
            "APERTA %s/%s @ %.3f | size=%.2f | copia da %s",
            pos.market_id,
            pos.outcome,
            current_price,
            size,
            sig.trader_addr[:8],
        )
        tg.alert_open(pos)
        return pos

    def close_position(self, pos: PaperPosition, exit_price: float, reason: str) -> None:
        pnl = pos.shares * (exit_price - pos.entry_price)
        pos.closed = True
        pos.exit_price = exit_price
        pos.closed_at = datetime.now(timezone.utc).isoformat()
        pos.pnl_usd = pnl

        self.ledger.bankroll += pnl
        self.ledger.realized_pnl += pnl
        self.ledger.history.append(
            {
                "event": "CLOSE",
                "ts": pos.closed_at,
                "reason": reason,
                "pnl_usd": pnl,
                **asdict(pos),
            }
        )
        logger.info(
            "CHIUSA %s/%s @ %.3f | PnL=%+.2f | motivo=%s",
            pos.market_id,
            pos.outcome,
            exit_price,
            pnl,
            reason,
        )
        tg.alert_close(pos, reason)


def price_lookup_factory(market_prices: dict):
    """Chiusura che restituisce il prezzo corrente di un outcome."""
    def _lookup(market_id: str, outcome: str) -> Optional[float]:
        m = market_prices.get(market_id)
        if not m:
            return None
        return m.get(outcome)
    return _lookup


def run_paper_live(iterations: Optional[int] = None):
    """
    Loop principale del paper trading.
    iterations=None -> gira all'infinito.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    trader = PaperTrader()
    if tg.enabled():
        logger.info("Alert Telegram: ATTIVI")
        tg.send("🤖 Paper trading bot avviato")
    else:
        logger.info(
            "Alert Telegram: disattivati "
            "(imposta TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nel .env)"
        )
    loop = 0

    while iterations is None or loop < iterations:
        loop += 1
        try:
            # 1. Prendi i top trader dalla leaderboard
            #    (rank_traders filtra già per MIN_TRADER_ROI e MIN_TRADER_TRADES)
            leaders = fetch_leaderboard(period="30d", limit=50)
            qualified = rank_traders(leaders)

            # 2. Genera segnali dalle loro attività recenti
            signals, market_prices = generate_signals(qualified)

            # 2b. Refresh prezzi correnti per le posizioni aperte
            #     su mercati senza attività recente (mark-to-market
            #     e rilevamento risoluzione)
            open_ids = {p.market_id for p in trader.ledger.open_positions}
            missing = open_ids - set(market_prices)
            if missing:
                market_prices.update(fetch_market_prices(missing))

            lookup = price_lookup_factory(market_prices)

            # 2c. Alert Telegram sui segnali nuovi (dedup automatica)
            for sig in signals:
                tg.alert_signal(sig)

            # 3. Apri nuove posizioni sui segnali BUY
            #    Anti-churn: salta se nello stesso loop c'è anche un SELL
            #    sullo stesso mercato/outcome, o se una posizione identica
            #    è stata chiusa da meno di 30 minuti.
            sell_keys = {
                (s.market_id, s.outcome) for s in signals if s.action == "SELL"
            }
            now = datetime.now(timezone.utc)
            recently_closed = set()
            for p in trader.ledger.positions:
                if p.closed and p.closed_at:
                    age_min = (now - datetime.fromisoformat(p.closed_at)).total_seconds() / 60
                    if age_min < 30:
                        recently_closed.add((p.market_id, p.outcome))

            for sig in signals:
                if sig.action != "BUY":
                    continue
                key = (sig.market_id, sig.outcome)
                if key in sell_keys:
                    logger.debug("Skip %s: BUY e SELL nello stesso loop", key)
                    continue
                if key in recently_closed:
                    logger.debug("Skip %s: chiusa da meno di 30 min", key)
                    continue
                px = market_prices.get(sig.market_id, {}).get(sig.outcome)
                if px is not None:
                    trader.open_position(sig, px)

            # 4. Chiudi posizioni su segnale SELL o risoluzione mercato
            for pos in list(trader.ledger.open_positions):
                px = lookup(pos.market_id, pos.outcome)
                if px is None:
                    continue
                # mercato risolto: prezzo a 1.0 (vinto) o 0.0 (perso)
                if px >= 0.999:
                    trader.close_position(pos, 1.0, "market_resolved_win")
                elif px <= 0.001:
                    trader.close_position(pos, 0.0, "market_resolved_loss")
                else:
                    # segnale di uscita dal trader sorgente
                    exit_sig = next(
                        (s for s in signals
                         if s.market_id == pos.market_id
                         and s.outcome == pos.outcome
                         and s.action == "SELL"),
                        None,
                    )
                    if exit_sig:
                        trader.close_position(pos, px, "source_sell")

            # 5. Snapshot equity e salvataggio
            equity = trader.ledger.equity(lookup)
            logger.info(
                "--- Loop %d | equity=%.2f | bankroll=%.2f | aperte=%d | PnL realizzato=%+.2f",
                loop,
                equity,
                trader.ledger.bankroll,
                len(trader.ledger.open_positions),
                trader.ledger.realized_pnl,
            )
            trader._save()

        except Exception as e:  # noqa: BLE001
            logger.exception("Errore nel loop %d: %s", loop, e)

        logger.info("In attesa %d secondi prima del prossimo ciclo...", POLL_INTERVAL_SEC)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    run_paper_live()
