from datetime import datetime, timezone, timedelta
from leaderboard import fetch_leaderboard
from trader_analysis import rank_traders
from backtest import Backtester


def main():
    # Finestra: ultimi 90 giorni
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=90)
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())

    board = fetch_leaderboard(period="all", limit=100)
    top = rank_traders(board)[:20]
    print(f"Testo la strategia su {len(top)} trader qualificati...\n")

    bt = Backtester(
        bankroll=1000,
        slippage=0.02,        # regola questi valori sui costi reali
        latency_penalty=0.01,
        max_position_pct=0.02,
    )
    result = bt.run(top, start_ts, end_ts)

    print("=" * 45)
    print("RISULTATI BACKTEST")
    print("=" * 45)
    for k, v in result.summary().items():
        print(f"{k:.<25} {v}")
    print("=" * 45)


if __name__ == "__main__":
    main()