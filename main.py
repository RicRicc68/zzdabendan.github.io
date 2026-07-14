import time
from leaderboard import fetch_leaderboard
from trader_analysis import rank_traders
from signals import extract_fresh_signals
from executor import Executor
from config import POLL_INTERVAL_SEC

def run(bankroll=1000, dry_run=True):
    executor = None if dry_run else Executor(bankroll)
    seen = set()

    while True:
        board = fetch_leaderboard(period="30d", limit=100)
        top = rank_traders(board)
        print(f"[main] {len(top)} trader qualificati")

        signals = extract_fresh_signals(top)
        for sig in signals[:5]:
            sig_id = (sig["market"], sig["outcome"])
            if sig_id in seen:
                continue
            seen.add(sig_id)

            print(f"[SEGNALE] {sig['market']} | {sig['outcome']} "
                  f"| peso {sig['weight']:.2f} | "
                  f"{len(sig['traders'])} trader d'accordo")

            if not dry_run:
                # recupera token_id + prezzo dal mercato, poi:
                # executor.place_order(token_id, price, sig["weight"])
                pass

        time.sleep(POLL_INTERVAL_SEC)

if __name__ == "__main__":
    run(dry_run=True)   # inizia SEMPRE in dry_run