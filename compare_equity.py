"""
Confronto diretto tra equity curve del backtest e del paper trading.
Entrambe normalizzate a base 100 per un raffronto omogeneo,
indipendente dal bankroll di partenza.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import PAPER_BANKROLL_START

logger = logging.getLogger("compare_equity")


@dataclass
class NormalizedCurve:
    label: str
    timestamps: list[datetime]
    values: list[float]      # equity assoluta
    normalized: list[float]  # base 100
    final_return_pct: float
    max_dd_pct: float


def _max_dd_pct(values: list[float]) -> float:
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
    return max_dd * 100.0


def _normalize(values: list[float]) -> list[float]:
    """Riscala la serie in modo che il primo punto valga 100."""
    if not values or values[0] == 0:
        return values
    base = values[0]
    return [v / base * 100.0 for v in values]


# ---------- caricamento equity dal PAPER LEDGER ----------

def load_paper_curve(ledger_path: str = "paper_ledger.json") -> Optional[NormalizedCurve]:
    p = Path(ledger_path)
    if not p.exists():
        logger.warning("Ledger paper non trovato: %s", ledger_path)
        return None

    ledger = json.loads(p.read_text())
    closes = sorted(
        (h for h in ledger.get("history", []) if h.get("event") == "CLOSE"),
        key=lambda h: h["ts"],
    )
    if not closes:
        logger.warning("Nessun trade chiuso nel paper ledger")
        return None

    running = PAPER_BANKROLL_START
    values = [running]
    ts = [datetime.fromisoformat(closes[0]["ts"]).astimezone(timezone.utc)]
    for c in closes:
        running += c["pnl_usd"]
        values.append(running)
        ts.append(datetime.fromisoformat(c["ts"]).astimezone(timezone.utc))

    norm = _normalize(values)
    return NormalizedCurve(
        label="Paper Live",
        timestamps=ts,
        values=values,
        normalized=norm,
        final_return_pct=norm[-1] - 100.0,
        max_dd_pct=_max_dd_pct(values),
    )


# ---------- caricamento equity dal BACKTEST ----------
#
# Aspetta un JSON prodotto da run_backtest.py con struttura:
#   {"equity_curve": [[timestamp_iso, valore], ...]}
# Se il tuo backtest esporta diversamente, adatta _parse_backtest().

def _dump_backtest_curve(result, out_path: str = "backtest_equity.json") -> None:
    """
    Helper da chiamare in run_backtest.py DOPO aver ottenuto BacktestResult.
    Serializza la equity curve su disco così compare_equity può leggerla.
    Esempio d'uso in run_backtest.py:
        from compare_equity import _dump_backtest_curve
        _dump_backtest_curve(result)
    """
    curve = result.equity_curve()  # metodo già presente in backtest.py
    # curve atteso come lista di (timestamp, valore) o lista di valori
    serial = []
    for point in curve:
        if isinstance(point, (list, tuple)) and len(point) == 2:
            ts, val = point
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            serial.append([ts_str, float(val)])
        else:
            serial.append([None, float(point)])
    Path(out_path).write_text(json.dumps({"equity_curve": serial}, indent=2))
    logger.info("Equity backtest esportata in %s", out_path)


def load_backtest_curve(path: str = "backtest_equity.json") -> Optional[NormalizedCurve]:
    p = Path(path)
    if not p.exists():
        logger.warning(
            "Equity backtest non trovata: %s "
            "(chiama _dump_backtest_curve(result) in run_backtest.py)",
            path,
        )
        return None

    data = json.loads(p.read_text())
    raw = data.get("equity_curve", [])
    if not raw:
        logger.warning("equity_curve vuota in %s", path)
        return None

    ts, values = [], []
    for i, point in enumerate(raw):
        ts_str, val = point
        if ts_str:
            ts.append(datetime.fromisoformat(ts_str))
        else:
            # nessun timestamp: uso indice sequenziale fittizio
            ts.append(datetime.fromtimestamp(i, tz=timezone.utc))
        values.append(float(val))

    norm = _normalize(values)
    return NormalizedCurve(
        label="Backtest",
        timestamps=ts,
        values=values,
        normalized=norm,
        final_return_pct=norm[-1] - 100.0,
        max_dd_pct=_max_dd_pct(values),
    )


# ---------- grafico sovrapposto ----------

def plot_comparison(
    paper: Optional[NormalizedCurve],
    backtest: Optional[NormalizedCurve],
    out_path: str = "compare_equity.png",
) -> None:
    if paper is None and backtest is None:
        logger.error("Nessuna curva disponibile, impossibile confrontare")
        return

    fig, ax = plt.subplots(figsize=(13, 7))

    # asse x: usiamo l'indice trade-progression per allineare periodi diversi.
    # (Le due curve coprono finestre temporali diverse; il confronto è sulla
    #  FORMA e sul RENDIMENTO RELATIVO, non sulle date assolute.)
    if backtest:
        x_bt = range(len(backtest.normalized))
        ax.plot(
            x_bt, backtest.normalized,
            color="#8e44ad", linewidth=2.0, label=f"Backtest ({backtest.final_return_pct:+.1f}%)",
        )
        ax.fill_between(x_bt, backtest.normalized, 100, alpha=0.08, color="#8e44ad")

    if paper:
        x_pp = range(len(paper.normalized))
        ax.plot(
            x_pp, paper.normalized,
            color="#27ae60", linewidth=2.0, label=f"Paper Live ({paper.final_return_pct:+.1f}%)",
        )
        ax.fill_between(x_pp, paper.normalized, 100, alpha=0.08, color="#27ae60")

    ax.axhline(100, color="gray", linestyle="--", linewidth=0.9, label="Base 100")
    ax.set_xlabel("Progressione trade (n° operazioni chiuse)")
    ax.set_ylabel("Equity normalizzata (base 100)")
    ax.set_title("Confronto Equity — Backtest vs Paper Live")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    logger.info("Confronto salvato in %s", out_path)


def print_divergence(
    paper: Optional[NormalizedCurve],
    backtest: Optional[NormalizedCurve],
) -> None:
    if paper is None or backtest is None:
        logger.info("Confronto numerico saltato: manca una delle due curve")
        return

    ret_gap = paper.final_return_pct - backtest.final_return_pct
    dd_gap = paper.max_dd_pct - backtest.max_dd_pct

    print("\n─── DIVERGENZA BACKTEST ↔ PAPER ───")
    print(f"  Rendimento backtest ... {backtest.final_return_pct:+.1f}%")
    print(f"  Rendimento paper ...... {paper.final_return_pct:+.1f}%")
    print(f"  Gap rendimento ........ {ret_gap:+.1f} punti")
    print(f"  Max DD backtest ....... {backtest.max_dd_pct:.1f}%")
    print(f"  Max DD paper .......... {paper.max_dd_pct:.1f}%")
    print(f"  Gap drawdown .......... {dd_gap:+.1f} punti")

    # interpretazione automatica
    if ret_gap < -15:
        verdict = "⚠️  Il paper rende MOLTO meno del backtest: probabile look-ahead o survivorship bias nella simulazione."
    elif ret_gap < -5:
        verdict = "🟡  Gap moderato: normale un po' di degrado (slippage/timing). Tienilo d'occhio."
    elif ret_gap > 15:
        verdict = "🟢  Il paper supera il backtest: fortuna o regime di mercato favorevole. Non fidarti troppo, servono più dati."
    else:
        verdict = "✅  Le due curve sono allineate: il backtest sta reggendo alla prova del live."
    print(f"\n  {verdict}\n")


def run_comparison(
    paper_ledger: str = "paper_ledger.json",
    backtest_json: str = "backtest_equity.json",
    out_path: str = "compare_equity.png",
) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )
    paper = load_paper_curve(paper_ledger)
    backtest = load_backtest_curve(backtest_json)
    plot_comparison(paper, backtest, out_path)
    print_divergence(paper, backtest)


if __name__ == "__main__":
    run_comparison()