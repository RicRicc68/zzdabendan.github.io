import requests
from config import DATA_API

# Mappa i vecchi valori di periodo sul nuovo formato /v1/leaderboard
_PERIOD_MAP = {
    "1d": "DAY", "day": "DAY",
    "7d": "WEEK", "week": "WEEK",
    "30d": "MONTH", "month": "MONTH",
    "all": "ALL",
}


def fetch_leaderboard(period="30d", limit=50, order_by="PNL", category="OVERALL"):
    """
    Recupera la leaderboard trader (nuovo endpoint /v1/leaderboard).
    period: '1d', '7d', '30d', 'all'
    order_by: 'PNL' o 'VOL'
    NB: l'API accetta limit massimo 50.
    """
    url = f"{DATA_API}/v1/leaderboard"
    params = {
        "category": category,
        "timePeriod": _PERIOD_MAP.get(str(period).lower(), "MONTH"),
        "orderBy": order_by,
        "limit": min(int(limit), 50),
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[leaderboard] errore: {e}")
        return []


def fetch_markets_traded(proxy_wallet):
    """
    Numero totale di mercati tradati da un utente (endpoint /traded).
    Usato come proxy del vecchio campo tradeCount, rimosso dalla leaderboard.
    """
    url = f"{DATA_API}/traded"
    try:
        r = requests.get(url, params={"user": proxy_wallet}, timeout=10)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            # possibili chiavi: "traded", "count", "total"
            for k in ("traded", "count", "total"):
                if k in data:
                    return int(data[k])
            return 0
        return int(data)
    except (requests.RequestException, ValueError, TypeError) as e:
        print(f"[traded] errore per {proxy_wallet[:10]}: {e}")
        return 0


def fetch_trader_positions(proxy_wallet):
    """Posizioni aperte di un trader specifico."""
    url = f"{DATA_API}/positions"
    params = {"user": proxy_wallet, "sizeThreshold": 1}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[positions] errore: {e}")
        return []


def fetch_trader_activity(proxy_wallet, limit=100):
    """Storico trade recenti (per copiare le entry)."""
    url = f"{DATA_API}/activity"
    params = {"user": proxy_wallet, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"[activity] errore: {e}")
        return []
