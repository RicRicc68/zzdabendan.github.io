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
const RPC_URL = process.env.POLYGON_RPC_URL || 'https://polygon-rpc.com';

// USDC.e (collaterale usato da Polymarket CTF), 6 decimali
const USDC_ADDRESS = '0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174';
const COLLATERAL_SYMBOL = 'USDC.e';
const COLLATERAL_DECIMALS = 6;

// Contratti che richiedono allowance sul collaterale
const CLOB_SPENDERS = [
  '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E', // CTF Exchange
  '0xC5d563A36AE78145C45a50134d48A1215220f80a', // Neg Risk CTF Exchange
];

const ERC20_ABI = [
  {
    constant: true,
    inputs: [{ name: 'owner', type: 'address' }],
    name: 'balanceOf',
    outputs: [{ name: '', type: 'uint256' }],
    type: 'function',
  },
];

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

// ---------- Guardrail di rischio (indipendenti da quelli del bot Python:
// usando lo stesso wallet, si sommano ai suoi 6 posizioni / 30$ totali) ----------
const MAX_TRADE_SIZE_USDC = 5;
const MAX_TRADES_PER_HOUR = 999; // nessun cap orario esplicito, come richiesto
const MAX_DAILY_LOSS_USDC = 30;
const KILL_SWITCH_FILE = 'STOP_ARB';

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
  RPC_URL,
  USDC_ADDRESS,
  COLLATERAL_SYMBOL,
  COLLATERAL_DECIMALS,
  CLOB_SPENDERS,
  ERC20_ABI,
  CLOB_HOST,
  CLOB_WS_URL,
  GAMMA_BASE,
  RTDS_URL,
  INTERVAL_MIN,
  INTERVAL_SEC,
  MAX_TRADE_SIZE_USDC,
  MAX_TRADES_PER_HOUR,
  MAX_DAILY_LOSS_USDC,
  KILL_SWITCH_FILE,
  getWalletConfig,
};
