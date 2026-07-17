/**
 * Scanner Bybit "pump detector" — SOLO OSSERVAZIONE, nessun ordine.
 *
 * Monitora tutti i perpetual USDT su Bybit, rileva movimenti % anomali
 * in finestre brevi (1min/5min) e registra sistematicamente cosa succede
 * al prezzo nell'ora successiva: continua a salire? crolla subito? di
 * quanto? Serve a costruire dati reali (il "denominatore" mancante)
 * prima di considerare qualunque automazione con leva.
 */

const fs = require('fs');
const axios = require('axios');
const cfg = require('./config.js');

const logStream = fs.createWriteStream(cfg.LOG_FILE, { flags: 'a' });
function logEvent(obj) {
  logStream.write(JSON.stringify({ ...obj, loggedAtMs: Date.now() }) + '\n');
}

// symbol -> [{ t: ms, price }]
const priceHistory = new Map();
// symbol -> stato evento in osservazione
const activeEvents = new Map();

function pruneHistory(symbol, nowMs) {
  const arr = priceHistory.get(symbol);
  if (!arr) return;
  const cutoff = nowMs - cfg.MAX_HISTORY_SEC * 1000;
  let i = 0;
  while (i < arr.length && arr[i].t < cutoff) i++;
  if (i > 0) arr.splice(0, i);
}

// Trova il prezzo più vicino a `targetMs` (il punto della history più
// vecchio disponibile che copra almeno `windowSec`).
function priceAtOrBefore(arr, targetMs) {
  let candidate = null;
  for (const p of arr) {
    if (p.t <= targetMs) candidate = p;
    else break;
  }
  return candidate;
}

function checkForPump(symbol, nowMs, lastPrice) {
  const arr = priceHistory.get(symbol);
  if (!arr || arr.length < 2) return null;

  for (const { sec, thresholdPct } of cfg.DETECT_WINDOWS) {
    const targetMs = nowMs - sec * 1000;
    const oldest = arr[0];
    if (oldest.t > targetMs) continue; // non abbiamo ancora abbastanza storico per questa finestra
    const ref = priceAtOrBefore(arr, targetMs);
    if (!ref || ref.price <= 0) continue;
    const pct = ((lastPrice - ref.price) / ref.price) * 100;
    if (Math.abs(pct) >= thresholdPct) {
      return { windowSec: sec, thresholdPct, pct, refPrice: ref.price };
    }
  }
  return null;
}

function startTrackingEvent(symbol, nowMs, price, trigger) {
  const ev = {
    symbol,
    detectedAt: new Date(nowMs).toISOString(),
    detectedAtMs: nowMs,
    triggerWindowSec: trigger.windowSec,
    triggerThresholdPct: trigger.thresholdPct,
    priceAtDetection: price,
    pctChangeAtDetection: trigger.pct,
    refPriceAtDetection: trigger.refPrice,
    checkpoints: {},
    pendingCheckpoints: [...cfg.FOLLOW_CHECKPOINTS_SEC],
    maxPrice: price,
    maxPriceAtSec: 0,
    postPeakMin: price,
    maxDrawdownFromPeakPct: 0,
    minPrice: price,
    minPriceAtSec: 0,
  };
  activeEvents.set(symbol, ev);

  console.log(
    `\n[PUMP] ${symbol} | ${trigger.pct >= 0 ? '+' : ''}${trigger.pct.toFixed(1)}% in ${trigger.windowSec}s | ` +
    `prezzo=${price} (rif=${trigger.refPrice}) | osservo per ${cfg.FOLLOW_DURATION_SEC / 60} min...`
  );
}

function updateTrackedEvent(ev, nowMs, price) {
  const elapsedSec = Math.floor((nowMs - ev.detectedAtMs) / 1000);

  if (price > ev.maxPrice) {
    ev.maxPrice = price;
    ev.maxPriceAtSec = elapsedSec;
    ev.postPeakMin = price; // riparte il tracking del minimo post-picco
  } else if (price < ev.postPeakMin) {
    ev.postPeakMin = price;
    const dd = ((ev.maxPrice - ev.postPeakMin) / ev.maxPrice) * 100;
    if (dd > ev.maxDrawdownFromPeakPct) ev.maxDrawdownFromPeakPct = dd;
  }

  if (price < ev.minPrice) {
    ev.minPrice = price;
    ev.minPriceAtSec = elapsedSec;
  }

  // Registra i checkpoint fissi (60/300/900/1800/3600s) appena superati
  ev.pendingCheckpoints = ev.pendingCheckpoints.filter((cpSec) => {
    if (elapsedSec < cpSec) return true;
    const pct = ((price - ev.priceAtDetection) / ev.priceAtDetection) * 100;
    ev.checkpoints[cpSec] = { price, pct };
    return false;
  });

  if (elapsedSec >= cfg.FOLLOW_DURATION_SEC) {
    finalizeEvent(ev);
    activeEvents.delete(ev.symbol);
  }
}

function finalizeEvent(ev) {
  const maxPricePct = ((ev.maxPrice - ev.priceAtDetection) / ev.priceAtDetection) * 100;
  const minPricePct = ((ev.minPrice - ev.priceAtDetection) / ev.priceAtDetection) * 100;

  console.log(
    `[PUMP DONE] ${ev.symbol} | entry=${ev.priceAtDetection} | ` +
    `max=${maxPricePct >= 0 ? '+' : ''}${maxPricePct.toFixed(1)}% @${ev.maxPriceAtSec}s | ` +
    `min=${minPricePct >= 0 ? '+' : ''}${minPricePct.toFixed(1)}% @${ev.minPriceAtSec}s | ` +
    `max drawdown da picco=${ev.maxDrawdownFromPeakPct.toFixed(1)}%`
  );

  logEvent({
    type: 'pump_event',
    symbol: ev.symbol,
    detectedAt: ev.detectedAt,
    triggerWindowSec: ev.triggerWindowSec,
    triggerThresholdPct: ev.triggerThresholdPct,
    priceAtDetection: ev.priceAtDetection,
    pctChangeAtDetection: ev.pctChangeAtDetection,
    checkpoints: ev.checkpoints,
    maxPrice: ev.maxPrice,
    maxPricePct,
    maxPriceAtSec: ev.maxPriceAtSec,
    minPrice: ev.minPrice,
    minPricePct,
    minPriceAtSec: ev.minPriceAtSec,
    maxDrawdownFromPeakPct: ev.maxDrawdownFromPeakPct,
  });
}

async function poll() {
  const nowMs = Date.now();
  let list;
  try {
    const { data } = await axios.get(cfg.BYBIT_TICKERS_URL, {
      params: { category: cfg.CATEGORY },
      timeout: 8000,
    });
    if (data.retCode !== 0) {
      console.warn(`[BYBIT] retCode=${data.retCode} ${data.retMsg}`);
      return;
    }
    list = data.result.list;
  } catch (err) {
    console.warn(`[BYBIT] richiesta fallita: ${err.message}`);
    return;
  }

  for (const t of list) {
    const symbol = t.symbol;
    const price = parseFloat(t.lastPrice);
    if (!price || price <= 0) continue;

    if (!priceHistory.has(symbol)) priceHistory.set(symbol, []);
    priceHistory.get(symbol).push({ t: nowMs, price });
    pruneHistory(symbol, nowMs);

    const activeEv = activeEvents.get(symbol);
    if (activeEv) {
      updateTrackedEvent(activeEv, nowMs, price);
    } else {
      const trigger = checkForPump(symbol, nowMs, price);
      if (trigger) startTrackingEvent(symbol, nowMs, price, trigger);
    }
  }
}

let pollCount = 0;
async function mainLoop() {
  console.log('=== Bybit Pump Scanner (solo osservazione, nessun ordine) ===');
  console.log(`Categoria: ${cfg.CATEGORY} | poll ogni ${cfg.POLL_INTERVAL_SEC}s`);
  console.log(
    `Soglie: ${cfg.DETECT_WINDOWS.map((w) => `${w.thresholdPct}% in ${w.sec}s`).join(', ')}`
  );
  console.log(`Follow-up: ${cfg.FOLLOW_DURATION_SEC / 60} min, checkpoint a ${cfg.FOLLOW_CHECKPOINTS_SEC.join(',')}s`);
  console.log(`Log: ${cfg.LOG_FILE}\n`);

  while (true) {
    await poll();
    pollCount++;
    if (pollCount % Math.round(300 / cfg.POLL_INTERVAL_SEC) === 0) {
      console.log(
        `[STATUS] ${new Date().toISOString()} | simboli monitorati=${priceHistory.size} | eventi in osservazione=${activeEvents.size}`
      );
    }
    await new Promise((r) => setTimeout(r, cfg.POLL_INTERVAL_SEC * 1000));
  }
}

process.on('SIGINT', () => {
  console.log('\nInterrotto. Chiudo log...');
  logStream.end(() => process.exit(0));
});

mainLoop().catch((err) => {
  console.error('Errore fatale:', err);
  process.exit(1);
});
