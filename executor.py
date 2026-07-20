"""
Executor per ordini REALI sul CLOB V2 di Polymarket.

IMPORTANTE: dal 28 aprile 2026 Polymarket usa CLOB V2.
Serve il pacchetto NUOVO:   pip install py_clob_client_v2
(il vecchio py-clob-client è morto: rifiuta ogni ordine
con "invalid order version" — disinstallalo pure.)

Capitale vero a rischio: usato solo da live_trading.py,
che applica i guard-rail definiti in config.py.
"""

from __future__ import annotations

import logging

from py_clob_client_v2 import (
    ClobClient,
    MarketOrderArgs,
    OrderType,
    PartialCreateOrderOptions,
    Side,
)

from config import (
    CLOB_API,
    PRIVATE_KEY,
    POLY_SIGNATURE_TYPE,
    POLY_FUNDER,
    LIVE_MIN_SHARES,
)

logger = logging.getLogger("executor")


class Executor:
    def __init__(self):
        if not PRIVATE_KEY:
            raise RuntimeError(
                "POLY_PRIVATE_KEY mancante nel .env: impossibile andare live"
            )
        if POLY_SIGNATURE_TYPE not in (0, 1, 2, 3):
            raise RuntimeError(
                f"POLY_SIGNATURE_TYPE={POLY_SIGNATURE_TYPE} non valido: "
                "usa 0 (EOA diretto), 1 (email/Magic), "
                "2 (browser wallet/Gnosis Safe) "
                "o 3 (deposit wallet flow, EIP-1271)"
            )

        kwargs = dict(host=CLOB_API, key=PRIVATE_KEY, chain_id=137)
        if POLY_SIGNATURE_TYPE in (1, 2, 3):
            if not POLY_FUNDER:
                raise RuntimeError(
                    f"POLY_SIGNATURE_TYPE={POLY_SIGNATURE_TYPE} richiede "
                    "POLY_FUNDER: l'indirizzo del proxy/deposit wallet "
                    "Polymarket che detiene i fondi"
                )
            kwargs["signature_type"] = POLY_SIGNATURE_TYPE
            kwargs["funder"] = POLY_FUNDER

        self.client = ClobClient(**kwargs)
        self.client.set_api_creds(self.client.create_or_derive_api_key())
        self.last_buy_error: str | None = None
        logger.info(
            "Executor V2 pronto (signature_type=%d, funder=%s)",
            POLY_SIGNATURE_TYPE,
            (POLY_FUNDER or "EOA diretto")[:12],
        )

    # ---------- prezzi ----------

    def best_price(self, token_id: str, side: str) -> float | None:
        """Miglior prezzo eseguibile: ask per comprare, bid per vendere."""
        try:
            resp = self.client.get_price(token_id, side.upper())
            if isinstance(resp, dict):
                return float(resp["price"])
            return float(resp)
        except Exception as e:  # noqa: BLE001
            logger.warning("get_price fallita per %s: %s", token_id[:12], e)
            return None

    def _tick_size(self, token_id: str) -> str:
        try:
            return self.client.get_tick_size(token_id)
        except Exception:  # noqa: BLE001
            return "0.01"

    @staticmethod
    def _round_to_tick(price: float, tick: str) -> float:
        t = float(tick)
        return round(round(price / t) * t, 6)

    # ---------- ordini ----------
    #
    # Il server valida gli ordini FAK come MARKET order:
    #   BUY : maker amount = USDC, max 2 decimali
    #   SELL: maker amount = shares, max 2 decimali
    # Usiamo quindi le API market-order del client, che applicano
    # gli arrotondamenti corretti per il tick size del mercato.

    def buy(self, token_id: str, size_usd: float) -> tuple[dict | None, float, float]:
        """
        Market buy per size_usd dollari (FAK).
        Ritorna (risposta, prezzo, shares stimate) — risposta None se fallito.
        """
        # Per COMPRARE serve il miglior ASK: nel CLOB è il lato "SELL" del book
        # (side=BUY restituirebbe il miglior BID, dove un buy non incrocia nulla)
        px = self.best_price(token_id, "SELL")
        if px is None or px <= 0 or px >= 1:
            return None, 0.0, 0.0

        amount_usd = round(size_usd, 2)
        est_shares = amount_usd / px
        if est_shares < LIVE_MIN_SHARES:
            logger.warning(
                "Ordine sotto il minimo CLOB (%.2f < %.1f shares), skip",
                est_shares, LIVE_MIN_SHARES,
            )
            return None, 0.0, 0.0

        tick = self._tick_size(token_id)
        try:
            resp = self.client.create_and_post_market_order(
                order_args=MarketOrderArgs(
                    token_id=token_id,
                    amount=amount_usd,        # USDC, 2 decimali
                    side=Side.BUY,
                    # prezzo limite: ask + 2% di margine (il fill avviene
                    # comunque al miglior prezzo disponibile sul book)
                    price=min(px * 1.02, 0.99),
                    order_type=OrderType.FAK,
                ),
                options=PartialCreateOrderOptions(tick_size=tick),
                order_type=OrderType.FAK,
            )
            logger.info(
                "[LIVE V2] BUY %.2f$ (~%.2f shares) @ %.4f -> %s",
                amount_usd, est_shares, px, resp,
            )
            self.last_buy_error = None
            return resp, px, est_shares
        except Exception as e:  # noqa: BLE001
            logger.error("Ordine BUY fallito: %s", e)
            self.last_buy_error = str(e)
            return None, 0.0, 0.0

    def sell(self, token_id: str, shares: float) -> tuple[dict | None, float]:
        """Market sell di `shares` (FAK). Ritorna (risposta, prezzo)."""
        # Per VENDERE serve il miglior BID: nel CLOB è il lato "BUY" del book
        px = self.best_price(token_id, "BUY")
        if px is None or px <= 0 or px >= 1:
            return None, 0.0

        amount_shares = float(int(shares * 100)) / 100  # round DOWN a 2 decimali
        if amount_shares < LIVE_MIN_SHARES:
            logger.warning(
                "Vendita sotto il minimo CLOB (%.2f < %.1f shares), skip",
                amount_shares, LIVE_MIN_SHARES,
            )
            return None, 0.0

        tick = self._tick_size(token_id)
        try:
            resp = self.client.create_and_post_market_order(
                order_args=MarketOrderArgs(
                    token_id=token_id,
                    amount=amount_shares,     # shares, 2 decimali
                    side=Side.SELL,
                    # prezzo limite: bid - 2% di margine
                    price=max(px * 0.98, 0.01),
                    order_type=OrderType.FAK,
                ),
                options=PartialCreateOrderOptions(tick_size=tick),
                order_type=OrderType.FAK,
            )
            logger.info(
                "[LIVE V2] SELL %.2f shares @ %.4f -> %s",
                amount_shares, px, resp,
            )
            return resp, px
        except Exception as e:  # noqa: BLE001
            logger.error("Ordine SELL fallito: %s", e)
            return None, 0.0
