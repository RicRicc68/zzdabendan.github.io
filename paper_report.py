"""
Report giornaliero automatico sul ledger del paper trading.
Riusa le metriche di backtest.py per un confronto omogeneo
tra simulazione storica e paper live.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, date
from dataclasses import dataclass
from collections import defaultdict
from typing import Optional

import matplotlib
matplotlib.use("Agg")  # backend headless, nessuna finestra
import matplotlib.pyplot as plt

from config import PAPER_BANKROLL_START

logger = logging.getLogger("paper_report")


@dataclass
class DailyReport:
    day: str
    trades_closed: int
    winrate: float
    pnl_day: float
    bankroll_end: float
    equity_end: float
    open_positions: int
    committed_capital: float
    # metriche cumulative dall'inizio
    cum_trades: int
    cum_winrate: float
    cum_pnl: float
    profit_factor: float
    max_drawdown_pct: float
    calmar_ratio: float
    rendimento_pct: float

    def to_console(self) -> str:
        return (
            f"\n╔══════════════════════════════════════════════╗\n"
            f"║  REPORT PAPER TRADING — {self.day:<20}║\n"
            f"╠══════════════════════════════════════════════╣\n"
            f"║  Oggi                                        ║\n"
            f"║    trade chiusi ........ {self.trades_closed:>18} ║\n"
            f"║    winrate ............. {self.winrate:>16.1f}% ║\n"
            f"║    PnL giorno .......... {self.pnl_day:>+16.2f}$ ║\n"
            f"║    posizioni aperte .... {self.open_positions:>18} ║\n"
            f"║    capitale impegnato .. {self.committed_capital:>16.2f}$ ║\n"
            f"╠══════════════════════════════════════════════╣\n"
            f"║  Cumulativo                                  ║\n"
            f"║    trade totali ........ {self.cum_trades:>18} ║\n"
            f"║    winrate cum ......... {self.cum_winrate:>16.1f}% ║\n"
            f"║    PnL cumulativo ...... {self.cum_pnl:>+16.2f}$ ║\n"
            f"║    profit factor ....... {self.profit_factor:>18.2f} ║\n"
            f"║    max drawdown ........ {self.max_drawdown_pct:>16.1f}% ║\n"
            f"║    calmar ratio ........ {self.calmar_ratio:>18.2f} ║\n"
            f"║    bankroll finale ..... {self.bankroll_end:>16.2f}$ ║\n"
            f"║    rendimento .......... {self.rendimento_pct:>+16.1f}% ║\n"
            f"╚══════════════════════════════════════════════╝\n"
        )


def _load_ledger(ledger_path: str) -> dict:
    p = Path(ledger_path)
    if not p.exists():
        raise FileNotFoundError(f"Ledger non trovato: {ledger_path}")
    return json.loads(p.read_text())


def _closed_trades(ledger: dict) -> list[dict]:
    """Estrae gli eventi CLOSE dallo storico, ordinati per timestamp."""
    closes = [h for h in ledger.get("history", []) if h.get("event") == "CLOSE"]
    closes.sort(key=lambda h: h["ts"])
    return closes


def _day_of(ts_iso: str) -> str:
    return datetime.fromisoformat(ts_iso).astimezone(timezone.utc).date().isoformat()


# ---------- metriche riusate dalla logica di backtest.py ----------

def _profit_factor(pnls: list[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def _equity_curve(closes: list[dict], start: float) -> list[float]:
    """Ricostruisce la equity realizzata trade-by-trade."""
    curve = [start]
    running = start
    for c in closes:
        running += c["pnl_usd"]
        curve.append(running)
    return curve


def _max_drawdown_pct(curve: list[float]) -> float:
    peak = curve[0]
    max_dd = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
    return max_dd * 100.0


def _calmar_ratio(rendimento_pct: float, max_dd_pct: float) -> float:
    if max_dd_pct == 0:
        return float("inf") if rendimento_pct > 0 else 0.0
    return rendimento_pct / max_dd_pct


# ---------- generazione report ----------

def build_daily_report(
    ledger_path: str = "paper_ledger.json",
    target_day: Optional[str] = None,
) -> DailyReport:
    """
    Costruisce il report per un giorno specifico (default: oggi UTC).
    """
    ledger = _load_ledger(ledger_path)
    closes = _closed_trades(ledger)

    if target_day is None:
        target_day = datetime.now(timezone.utc).date().isoformat()

    # trade chiusi solo nel giorno target
    day_closes = [c for c in closes if _day_of(c["ts"]) == target_day]
    day_pnls = [c["pnl_usd"] for c in day_closes]
    day_wins = sum(1 for p in day_pnls if p > 0)

    # metriche cumulative su TUTTO lo storico
    all_pnls = [c["pnl_usd"] for c in closes]
    cum_wins = sum(1 for p in all_pnls if p > 0)

    curve = _equity_curve(closes, PAPER_BANKROLL_START)
    bankroll_end = ledger["bankroll"]
    committed = sum(
        p["size_usd"] for p in ledger.get("positions", []) if not p["closed"]
    )
    open_count = sum(1 for p in ledger.get("positions", []) if not p["closed"])

    rendimento = (
        (bankroll_end - PAPER_BANKROLL_START) / PAPER_BANKROLL_START * 100.0
    )
    max_dd = _max_drawdown_pct(curve)

    return DailyReport(
        day=target_day,
        trades_closed=len(day_closes),
        winrate=(day_wins / len(day_closes) * 100.0) if day_closes else 0.0,
        pnl_day=sum(day_pnls),
        bankroll_end=bankroll_end,
        equity_end=bankroll_end,  # equity live richiede prezzi correnti; qui usiamo realizzato
        open_positions=open_count,
        committed_capital=committed,
        cum_trades=len(closes),
        cum_winrate=(cum_wins / len(closes) * 100.0) if closes else 0.0,
        cum_pnl=sum(all_pnls),
        profit_factor=_profit_factor(all_pnls),
        max_drawdown_pct=max_dd,
        calmar_ratio=_calmar_ratio(rendimento, max_dd),
        rendimento_pct=rendimento,
    )


def plot_daily_equity(
    ledger_path: str = "paper_ledger.json",
    out_path: str = "paper_equity.png",
) -> None:
    """Salva equity curve realizzata + drawdown del paper trading."""
    ledger = _load_ledger(ledger_path)
    closes = _closed_trades(ledger)
    if not closes:
        logger.warning("Nessun trade chiuso, niente da plottare")
        return

    curve = _equity_curve(closes, PAPER_BANKROLL_START)
    # timestamp per asse x: partenza + ogni chiusura
    xs = [datetime.fromisoformat(closes[0]["ts"])] + [
        datetime.fromisoformat(c["ts"]) for c in closes
    ]

    # drawdown a ogni punto
    peak = curve[0]
    dd = []
    for v in curve:
        peak = max(peak, v)
        dd.append((v - peak) / peak * 100.0 if peak > 0 else 0.0)

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )

    ax1.plot(xs, curve, color="#2e86de", linewidth=1.8, label="Equity (realizzato)")
    ax1.axhline(PAPER_BANKROLL_START, color="gray", linestyle="--", linewidth=0.8)
    ax1.fill_between(xs, curve, PAPER_BANKROLL_START, alpha=0.12, color="#2e86de")
    ax1.set_ylabel("Bankroll ($)")
    ax1.set_title("Paper Trading — Equity Curve & Drawdown")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)

    ax2.fill_between(xs, dd, 0, color="#e74c3c", alpha=0.4)
    ax2.plot(xs, dd, color="#c0392b", linewidth=1.0)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Data")
    ax2.grid(alpha=0.3)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    logger.info("Grafico salvato in %s", out_path)


def append_report_log(report: DailyReport, log_path: str = "paper_reports.jsonl") -> None:
    """Accoda il report in formato JSONL per storicizzare i giorni."""
    from dataclasses import asdict
    with open(log_path, "a") as f:
        f.write(json.dumps(asdict(report)) + "\n")


def run_daily_report(
    ledger_path: str = "paper_ledger.json",
    target_day: Optional[str] = None,
) -> DailyReport:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    report = build_daily_report(ledger_path, target_day)
    print(report.to_console())
    plot_daily_equity(ledger_path)
    append_report_log(report)
    return report


if __name__ == "__main__":
    run_daily_report()