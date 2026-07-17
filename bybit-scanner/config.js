// Nessuna chiave API: solo endpoint pubblici di mercato (read-only).
const BYBIT_TICKERS_URL = 'https://api.bybit.com/v5/market/tickers';

// Bybit risponde 403 dall'IP di Render (blocca i range datacenter/hosting
// noti, non necessariamente per paese): stesso PROXY_URL già usato per
// Polymarket (vedi ../deploy/aws_spain_proxy/), axios lo rispetta in
// automatico tramite le env HTTP_PROXY/HTTPS_PROXY.
if (process.env.PROXY_URL) {
  process.env.HTTPS_PROXY = process.env.HTTPS_PROXY || process.env.PROXY_URL;
  process.env.HTTP_PROXY = process.env.HTTP_PROXY || process.env.PROXY_URL;
}

// 'linear' = perpetual USDT-margined (i future retail con leva 25-50x
// di cui parlavamo). Bybit supporta anche 'inverse' (coin-margined) e
// 'spot', non inclusi qui.
const CATEGORY = 'linear';

const POLL_INTERVAL_SEC = 5;

// Finestre su cui valutare la variazione % e soglia di "movimento anomalo"
// per ciascuna. Valori di partenza da calibrare guardando i primi log:
// se troppi eventi banali, alza le soglie; se non ne arriva nessuno in
// ore, abbassale.
const DETECT_WINDOWS = [
  { sec: 60, thresholdPct: 8 },   // >8% in 1 minuto
  { sec: 300, thresholdPct: 15 }, // >15% in 5 minuti
];

// Quanto tenere sotto osservazione un simbolo dopo averlo rilevato, e a
// quali istanti registrare un checkpoint di prezzo (in secondi dal
// momento del rilevamento).
const FOLLOW_DURATION_SEC = 3600; // 60 minuti
const FOLLOW_CHECKPOINTS_SEC = [60, 300, 900, 1800, 3600];

// Storico prezzi per simbolo: basta coprire la finestra di rilevamento
// più ampia, con un margine.
const MAX_HISTORY_SEC = Math.max(...DETECT_WINDOWS.map((w) => w.sec)) + 60;

const LOG_FILE = 'pump_events.jsonl';

module.exports = {
  BYBIT_TICKERS_URL,
  CATEGORY,
  POLL_INTERVAL_SEC,
  DETECT_WINDOWS,
  FOLLOW_DURATION_SEC,
  FOLLOW_CHECKPOINTS_SEC,
  MAX_HISTORY_SEC,
  LOG_FILE,
};
