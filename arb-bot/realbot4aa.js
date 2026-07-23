const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '.env') });

// Proxy HTTP/HTTPS opzionale (stesso PROXY_URL del bot Python, vedi
// ../config.py e ../deploy/aws_spain_proxy/): axios onora HTTPS_PROXY/HTTP_PROXY
// in automatico, quindi qui basta valorizzare le env prima di ogni richiesta.
// Non serve per i WebSocket (RTDS/CLOB market feed): sono solo dati pubblici
// in lettura, mai soggetti al geoblock (che scatta solo su POST /order).
if (process.env.PROXY_URL) {
  process.env.HTTPS_PROXY = process.env.HTTPS_PROXY || process.env.PROXY_URL;
  process.env.HTTP_PROXY = process.env.HTTP_PROXY || process.env.PROXY_URL;
}

// ---------- Rete / contratti (Polygon mainnet) ----------
const CHAIN_ID = 137;

// ---------- Endpoint Polymarket ----------
const CLOB_HOST = 'https://clob.polymarket.com';
const CLOB_WS_URL = 'wss://ws-subscriptions-clob.polymarket.com/ws/market';
const GAMMA_BASE = 'https://gamma-api.polymarket.com';
const RTDS_URL = 'wss://ws-live-data.polymarket.com';

// ---------- Finestra di mercato ----------
// Verificato via Gamma API: i mercati "BTC Up/Down" reali hanno slug
// btc-updown-5m-<epoch> con finestre da 5 minuti.
const INTERVAL_MIN = 5;
const INTERVAL_SEC = INTERVAL_MIN * 60;

// ---------- Order-flow imbalance (filtro di conferma) ----------
// Banda di prezzo (in probabilità, es. 0.05 = 5 centesimi) attorno al
// best bid/ask entro cui sommare le size per il calcolo dell'imbalance.
const ORDER_FLOW_BAND = 0.05;
// Rapporto minimo bid/(bid+ask) richiesto per confermare il segnale:
// serve più pressione in acquisto che in vendita vicino al prezzo corrente.
const ORDER_FLOW_MIN_RATIO = 0.55;

// ---------- Guardrail di rischio (wallet indipendente dal bot Python —
// funder diverso, vedi render.yaml) ----------
// Riportato da 15$ a 5$ il 2026-07-23: a 15$/trade il book non ha abbastanza
// liquidità al prezzo migliore, lo slippage reale è salito a +5.95 centesimi
// medi (18/23 ordini riempiti peggio del segnale, alcuni fino a +31c) — a
// 5$ lo slippage misurato era di 1-2 centesimi. Vedi anche il fix in
// index.js che ora traccia il prezzo di riempimento reale, non l'ask
// del segnale, per il P&L.
const MAX_TRADE_SIZE_USDC = 5;
const MAX_TRADES_PER_HOUR = 999; // nessun cap orario esplicito, come richiesto
const MAX_DAILY_LOSS_USDC = 30;
const KILL_SWITCH_FILE = 'STOP_ARB';

// Capitale committed in posizioni non ancora risolte: prima mancava del
// tutto (bug trovato il 2026-07-20 in sessione live: 9 posizioni da 5$
// aperte quasi in parallelo con solo 21.67$ disponibili).
const MAX_OPEN_POSITIONS = 6;
const MAX_TOTAL_COMMITTED_USDC = 30;

function getWalletConfig() {
  const rawKey = process.env.POLY_PRIVATE_KEY;
  if (!rawKey) {
    throw new Error('POLY_PRIVATE_KEY mancante nel .env: impossibile andare live');
  }
  const privateKey = rawKey.startsWith('0x') ? rawKey : `0x${rawKey}`;

  const signatureType = Number(process.env.POLY_SIGNATURE_TYPE ?? 0);
  if (![0, 1, 2, 3].includes(signatureType)) {
    throw new Error(`POLY_SIGNATURE_TYPE=${signatureType} non valido: usa 0, 1, 2 o 3`);
  }

  const funderAddress = process.env.POLY_FUNDER;
  if ([1, 2, 3].includes(signatureType) && !funderAddress) {
    throw new Error(
      `POLY_SIGNATURE_TYPE=${signatureType} richiede POLY_FUNDER: l'indirizzo del proxy/deposit wallet Polymarket`
    );
  }

  return { privateKey, funderAddress, signatureType };
}

module.exports = {
  CHAIN_ID,
  CLOB_HOST,
  CLOB_WS_URL,
  GAMMA_BASE,
  RTDS_URL,
  INTERVAL_MIN,
  INTERVAL_SEC,
  ORDER_FLOW_BAND,
  ORDER_FLOW_MIN_RATIO,
  MAX_TRADE_SIZE_USDC,
  MAX_TRADES_PER_HOUR,
  MAX_DAILY_LOSS_USDC,
  MAX_OPEN_POSITIONS,
  MAX_TOTAL_COMMITTED_USDC,
  KILL_SWITCH_FILE,
  getWalletConfig,
};
