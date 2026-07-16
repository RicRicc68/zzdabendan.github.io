import os
from pathlib import Path
from dotenv import load_dotenv

# Carica il file .env dalla directory del progetto
# (senza questa chiamata os.getenv non vede le variabili del .env!)
load_dotenv(Path(__file__).resolve().parent / ".env")

# Polymarket usa Polygon + CLOB API
CLOB_API = "https://clob.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

# Chiave privata wallet (usa .env, MAI hardcoded)
PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")
WALLET_ADDR = os.getenv("POLY_WALLET")

# Proxy HTTP/HTTPS opzionale per le chiamate al CLOB (es. VPS con uscita in
# Spagna, per far coincidere l'IP del bot con la propria reale residenza,
# dato che Render non offre region in Spagna). Formato:
# http://user:pass@host:porta oppure socks5://user:pass@host:porta
# Deve essere impostata PRIMA di importare py_clob_client_v2 (in executor.py),
# perché il suo httpx.Client legge le env HTTP_PROXY/HTTPS_PROXY solo alla
# creazione del client, quindi lo facciamo qui che viene importato per primo.
PROXY_URL = os.getenv("PROXY_URL")
if PROXY_URL:
    os.environ.setdefault("HTTPS_PROXY", PROXY_URL)
    os.environ.setdefault("HTTP_PROXY", PROXY_URL)

# Alert Telegram (opzionali: se mancano, gli alert sono disattivati)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Parametri risk management (fondamentali)
MAX_POSITION_PCT = 0.02      # max 2% capitale per trade
MIN_TRADER_ROI = 0.15        # segui solo trader con ROI storico >15%
MIN_TRADER_TRADES = 50       # almeno 50 trade per validità statistica
POLL_INTERVAL_SEC = 300      # secondi
PAPER_BANKROLL_START = 1000

# ---------- LIVE TRADING (capitale reale!) ----------
# Tipo firma: 0 = EOA diretto (chiave con USDC sull'address stesso)
#             1 = account Polymarket via email/Magic (proxy wallet)
#             2 = account Polymarket via browser wallet (proxy wallet)
POLY_SIGNATURE_TYPE = int(os.getenv("POLY_SIGNATURE_TYPE", "0"))
# Se signature type 1 o 2: indirizzo del proxy che detiene i fondi
POLY_FUNDER = os.getenv("POLY_FUNDER")

# Guard-rail di sicurezza per la sessione di test
LIVE_MAX_USD_PER_TRADE = 5.0    # tetto per singolo ordine
LIVE_MAX_OPEN_POSITIONS = 6     # massimo posizioni contemporanee
LIVE_MAX_TOTAL_USD = 30.0       # capitale totale massimo impegnabile
LIVE_MIN_SHARES = 5.0           # minimo del CLOB Polymarket
