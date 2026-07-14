import math
from config import MIN_TRADER_ROI, MIN_TRADER_TRADES
from leaderboard import fetch_markets_traded


def score_trader(trader):
    """
    Assegna uno score ponderato. La leaderboard grezza (solo PnL)
    è ingannevole: un trader può avere PnL alto ma winrate pessimo
    e sopravvivere per fortuna. Serve un punteggio composito.

    Nota (nuova API /v1/leaderboard): il volume è nel campo "vol"
    e tradeCount non esiste più — usiamo il numero di mercati
    tradati (/traded) come proxy di attività.
    """
    pnl = trader.get("pnl", 0) or 0
    volume = trader.get("vol") or trader.get("volume") or 0
    wallet = trader.get("proxyWallet") or trader.get("wallet")

    if not wallet or volume <= 0:
        return None

    roi = pnl / volume
    if roi < MIN_TRADER_ROI:
        return None  # scarta subito, evita la chiamata /traded

    # tradeCount non è più nella leaderboard: proxy con mercati tradati
    trades = trader.get("tradeCount") or fetch_markets_traded(wallet)
    if trades < MIN_TRADER_TRADES:
        return None

    # Sharpe-like: premia consistenza, penalizza pochi trade
    consistency_factor = math.log10(max(trades, 2))
    score = roi * consistency_factor

    return {
        "wallet": wallet,
        "roi": round(roi, 4),
        "pnl": pnl,
        "trades": trades,
        "score": round(score, 4),
    }


def rank_traders(leaderboard):
    scored = [s for t in leaderboard if (s := score_trader(t))]
    return sorted(scored, key=lambda x: x["score"], reverse=True)
