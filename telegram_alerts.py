"""
Alert Telegram per il bot di paper trading.

Setup (una tantum):
1. Su Telegram cerca @BotFather -> /newbot -> segui le istruzioni,
   ottieni il TOKEN del bot.
2. Scrivi un messaggio qualsiasi al tuo nuovo bot (serve per aprire la chat).
3. Recupera il tuo chat_id: apri nel browser
      https://api.telegram.org/bot<TOKEN>/getUpdates
   e leggi "chat":{"id": 123456789, ...}
4. Aggiungi al file .env:
      TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
      TELEGRAM_CHAT_ID=123456789

Se le variabili mancano, il modulo si disattiva da solo senza rompere il bot.
"""

from __future__ import annotations

import time
import logging
import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("telegram_alerts")

_API = "https://api.telegram.org/bot{token}/sendMessage"

# Deduplica: non rinotificare lo stesso segnale entro questa finestra
DEDUP_TTL_SEC = 3600
_sent: dict[str, float] = {}   # chiave alert -> timestamp ultimo invio


def enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _cleanup_sent() -> None:
    now = time.time()
    stale = [k for k, ts in _sent.items() if now - ts > DEDUP_TTL_SEC]
    for k in stale:
        del _sent[k]


def send(text: str, dedup_key: str | None = None) -> bool:
    """
    Invia un messaggio Telegram. Ritorna True se inviato.
    dedup_key: se fornita, il messaggio non viene reinviato
    finché la chiave resta nella finestra DEDUP_TTL_SEC.
    Non solleva mai eccezioni: un alert fallito non deve
    fermare il loop di trading.
    """
    if not enabled():
        return False

    _cleanup_sent()
    if dedup_key is not None:
        if dedup_key in _sent:
            return False
        _sent[dedup_key] = time.time()

    try:
        r = requests.post(
            _API.format(token=TELEGRAM_BOT_TOKEN),
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning("Telegram HTTP %d: %s", r.status_code, r.text[:200])
            return False
        return True
    except requests.RequestException as e:
        logger.warning("Telegram non raggiungibile: %s", e)
        return False


# ---------- messaggi preformattati ----------

def alert_signal(sig) -> None:
    """Nuovo segnale generato (BUY o SELL)."""
    emoji = "🟢" if sig.action == "BUY" else "🔴"
    key = f"SIG|{sig.market_id}|{sig.outcome}|{sig.action}"
    send(
        f"{emoji} <b>SEGNALE {sig.action}</b>\n"
        f"Mercato: <code>{sig.market_id[:16]}…</code>\n"
        f"Outcome: <b>{sig.outcome}</b>\n"
        f"Prezzo osservato: {sig.price:.3f}\n"
        f"Peso trader: {sig.weight:.2f}\n"
        f"Copiato da: <code>{sig.trader_addr[:10]}…</code>",
        dedup_key=key,
    )


def alert_open(pos) -> None:
    """Posizione paper aperta."""
    send(
        f"📈 <b>POSIZIONE APERTA</b>\n"
        f"Mercato: <code>{pos.market_id[:16]}…</code>\n"
        f"Outcome: <b>{pos.outcome}</b> @ {pos.entry_price:.3f}\n"
        f"Size: {pos.size_usd:.2f}$ ({pos.shares:.1f} shares)\n"
        f"Fonte: <code>{pos.source_trader[:10]}…</code>"
    )


def alert_close(pos, reason: str) -> None:
    """Posizione paper chiusa."""
    emoji = "✅" if pos.pnl_usd >= 0 else "❌"
    send(
        f"{emoji} <b>POSIZIONE CHIUSA</b>\n"
        f"Mercato: <code>{pos.market_id[:16]}…</code>\n"
        f"Outcome: <b>{pos.outcome}</b>\n"
        f"Entry {pos.entry_price:.3f} → Exit {pos.exit_price:.3f}\n"
        f"PnL: <b>{pos.pnl_usd:+.2f}$</b>\n"
        f"Motivo: {reason}"
    )


def alert_loop_summary(loop: int, equity: float, bankroll: float,
                       open_count: int, realized_pnl: float) -> None:
    """Riepilogo di fine ciclo (inviato solo se cambia qualcosa)."""
    key = f"SUM|{bankroll:.2f}|{open_count}|{realized_pnl:.2f}"
    send(
        f"📊 <b>Riepilogo loop {loop}</b>\n"
        f"Equity: {equity:.2f}$\n"
        f"Bankroll: {bankroll:.2f}$\n"
        f"Posizioni aperte: {open_count}\n"
        f"PnL realizzato: {realized_pnl:+.2f}$",
        dedup_key=key,
    )
