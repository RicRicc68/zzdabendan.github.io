import requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from config import DATA_API, MIN_TRADER_ROI, MIN_TRADER_TRADES


@dataclass
class SimTrade:
    market: str
    outcome: str
    entry_price: float
    entry_time: float
    size_usd: float
    exit_price: float = None
    exit_time: float = None
    resolved: bool = False

    @property
    def pnl(self):
        if self.exit_price is None:
            return 0.0
        shares = self.size_usd / self.entry_price
        return shares * (self.exit_price - self.entry_price)

    @property
    def roi(self):
        return self.pnl / self.size_usd if self.size_usd else 0.0


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    starting_bankroll: float = 1000.0

    def summary(self):
        if not self.trades:
            return {"error": "nessun trade simulato"}

        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in self.trades)

        gross_win = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses)) or 1e-9

        return {
            "trade_totali": len(self.trades),
            "winrate": round(len(wins) / len(self.trades), 3),
            "pnl_totale": round(total_pnl, 2),
            "roi_medio": round(
                sum(t.roi for t in self.trades) / len(self.trades), 4
            ),
            "profit_factor": round(gross_win / gross_loss, 2),
            "bankroll_finale": round(self.starting_bankroll + total_pnl, 2),
            "rendimento_pct": round(
                total_pnl / self.starting_bankroll * 100, 2
            ),
            "miglior_trade": round(max(t.pnl for t in self.trades), 2),
            "peggior_trade": round(min(t.pnl for t in self.trades), 2),
        }