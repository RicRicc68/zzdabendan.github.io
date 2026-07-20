/**
 * trade_btc_arb_v2.js
 *
 * ARBITRAGGIO CLOB-GAMMA — VERSIONE CORRETTA
 *
 * I PROBLEMI DELLA V1 (che ti hanno azzerato):
 *   1. Fair value sempre 0.5 → "discount" era rumore, non edge
 *   2. Entry a 120s → troppo presto, nessuna convergenza
 *   3. Nessun filtro sulla volatilità → entra in tutte le finestre
 *   4. Size fissa $10 → non scala col rischio
 *
 * LA V2:
 *   - Usa solo ask > 0.52 come ENTRY LONG (buy UP quando ask è alto = alta probabilità)
 *   - Oppure ask < 0.48 come SHORT (buy DOWN quando DOWN è cheap = bassa prob)
 *   - Il "sweet spot" 0.35-0.65 era il problema: quel prezzo è il fair value
 *   - Size proporzionale al discount reale
 *   - Solo nelle finestre con volatilità sufficiente
 */

const WebSocket = require('ws');
const axios = require('axios');
const fs = require('fs');
const { ClobClient, Side, OrderType } = require('@polymarket/clob-client-v2');
const { http, createPublicClient, formatUnits } = require('viem');
const { polygon } = require('viem/chains');
const { privateKeyToAccount } = require('viem/accounts');

const cfg = require('./realbot4aa.js');
const {
  USDC_ADDRESS, COLLATERAL_SYMBOL, COLLATERAL_DECIMALS,
  CLOB_SPENDERS, ERC20_ABI, MAX_TRADE_SIZE_USDC, MAX_TRADES_PER_HOUR,
  MAX_DAILY_LOSS_USDC, KILL_SWITCH_FILE, INTERVAL_MIN, INTERVAL_SEC,
  RTDS_URL, CLOB_WS_URL, CLOB_HOST, GAMMA_BASE, CHAIN_ID,
} = cfg;

// ===== PARAMETRI V3 — MOMENTUM, NON CONTRARIAN =====
//
// V2 calcolava un "fair value" ipersemplificato (0.5 + variazione%*0.5) e
// comprava quando l'ask era "sotto" quel fair value. Verificato coi log
// diagnostici reali: il mercato riprezza molto più aggressivamente di
// quanto quella formula preveda, quindi il lato che sembrava "scontato"
// era quasi sempre il lato PERDENTE (es. DOWN a 0.09 mentre BTC saliva
// deciso) — la formula finiva per far scommettere contro il trend, non
// con il trend. Probabile causa dell'azzeramento della "V1" citato nei
// commenti storici.
//
// V3: compra il lato che il mercato GIÀ favorisce (come l'entry originale
// ask>=0.52), ma solo se il movimento BTC conferma la direzione, l'ask
// non è già agli estremi (troppo tardi, nessun edge residuo) e
// l'order-flow (bid/ask depth reale) conferma pressione ancora a favore.

// Il mercato deve aver già mostrato una preferenza chiara per un lato...
const MOMENTUM_MIN_ASK = 0.55;
// ...ma non deve essere già agli estremi: oltre questo livello il book è
// verificato "esaurito" (visto ask 1.000/0.010 già a metà finestra), size
// minima e rischio di slippage/no-fill senza edge residuo.
const MOMENTUM_MAX_ASK = 0.90;

// Movimento BTC minimo (dal prezzo di inizio finestra) per considerare la
// direzione "confermata" e non rumore. In basis points (5bps = 0.05%).
const MIN_MOVE_BPS = 5;

// Entry: su (quasi) tutta la finestra, non solo gli ultimi 45s.
// Verificato coi log diagnostici: già a t=257s/300s il book è ESAURITO
// (ask a 1.000/0.010, mercato già convergo) — non resta più nessun edge
// da sfruttare così tardi. Il vero disallineamento, se c'è, va cercato
// prima; lasciamo che i gate su edge/volatilità/order-flow decidano DOVE
// nella finestra scatta davvero l'ingresso, invece di forzare un istante
// fisso a ridosso della scadenza.
const ENTRY_WINDOW_START_SEC = 15;  // salta i primi secondi (book non ancora popolato)
const ENTRY_WINDOW_END_SEC = 285;   // stop 15s prima della fine (già convergo, vedi sopra)

// getRecentVolBps() (deviazione standard tick-a-tick) resta calcolata e
// loggata a scopo informativo, ma NON è più un gate: nei test è rimasta
// vicino a 0bps anche con BTC in movimento reale (misura il rumore fra
// un tick e l'altro, non lo spostamento netto di finestra) — il vero
// gate sul movimento è MIN_MOVE_BPS su priceChangePct, sopra.

const IS_LIVE = process.argv.includes('--live');
const LOG_FILE = 'trade_arb_log_v2.jsonl';
const logStream = fs.createWriteStream(LOG_FILE, { flags: 'a' });

function logEvent(obj) {
  logStream.write(JSON.stringify({ ...obj, loggedAtMs: Date.now() }) + '\n');
}

// ========== Guardrail ==========
let tradesThisHour = [];
let lastDayReset = new Date().toDateString();
let realizedPnL = 0;
let reconciledCount = 0;

function checkKillSwitch() {
  if (fs.existsSync(KILL_SWITCH_FILE)) {
    console.error(`\n[KILL SWITCH] File ${KILL_SWITCH_FILE} presente.`);
    return true;
  }
  return false;
}

function checkRateLimit() {
  const oneHourAgo = Date.now() - 3600000;
  tradesThisHour = tradesThisHour.filter((t) => t > oneHourAgo);
  if (tradesThisHour.length >= MAX_TRADES_PER_HOUR) {
    console.warn(`[RATE LIMIT] ${tradesThisHour.length}/${MAX_TRADES_PER_HOUR} nell'ultima ora.`);
    return false;
  }
  return true;
}

function checkDailyLoss() {
  const today = new Date().toDateString();
  if (today !== lastDayReset) {
    realizedPnL = 0;
    lastDayReset = today;
  }
  if (realizedPnL <= -MAX_DAILY_LOSS_USDC) {
    console.error(`[STOP] P&L ${realizedPnL.toFixed(2)} <= -${MAX_DAILY_LOSS_USDC}`);
    return false;
  }
  return true;
}

// ========== Calcolo volatilità (deviazione standard 5min) ==========
let priceHistory = [];

function getRecentVolBps() {
  if (priceHistory.length < 5) return 0;
  const recent = priceHistory.slice(-20); // ultimi ~20 tick
  const prices = recent.map((p) => p.price);
  const mean = prices.reduce((a, b) => a + b, 0) / prices.length;
  const variance = prices.reduce((sum, p) => sum + Math.pow(p - mean, 2), 0) / prices.length;
  const stdDev = Math.sqrt(variance);
  return (stdDev / mean) * 10000; // in basis points
}

// ========== CLOB Client ==========
let clobClient = null;

async function initClobClient() {
  if (!IS_LIVE) return;

  let privateKey, funderAddress, signatureType;
  try {
    ({ privateKey, funderAddress, signatureType } = cfg.getWalletConfig());
  } catch (err) {
    console.error(`[ERRORE] ${err.message}`);
    process.exit(1);
  }

  const account = privateKeyToAccount(privateKey);
  const signer = {
    getAddress: async () => account.address,
    signTypedData: async (typedData) => account.signTypedData(typedData),
  };

  const bootstrapClient = new ClobClient({ host: CLOB_HOST, chain: CHAIN_ID, signer });
  const creds = await bootstrapClient.createOrDeriveApiKey();
  if (!creds || typeof creds !== 'object' || !creds.key) {
    console.error('[CLOB] Impossibile ottenere API key. Interrompo.');
    process.exit(1);
  }

  clobClient = new ClobClient({
    host: CLOB_HOST,
    chain: CHAIN_ID,
    signer,
    creds,
    signatureType,
    funderAddress,
  });

  console.log('[CLOB] Client pronto.');

  // Check saldo
  try {
    const publicClient = createPublicClient({ chain: polygon, transport: http(cfg.RPC_URL) });
    const balance = await publicClient.readContract({
      address: USDC_ADDRESS, abi: ERC20_ABI, functionName: 'balanceOf', args: [funderAddress],
    });
    const balanceUsd = Number(formatUnits(balance, COLLATERAL_DECIMALS));
    console.log(`[CHECK] Saldo ${COLLATERAL_SYMBOL}: $${balanceUsd.toFixed(2)}`);
    if (balanceUsd < MAX_TRADE_SIZE_USDC) {
      console.warn(`[CHECK] Saldo insufficiente per un trade da $${MAX_TRADE_SIZE_USDC}`);
    }
  } catch (err) {
    console.warn(`[CHECK] Impossibile verificare saldo: ${err.message}`);
  }
}

// ========== Stato di mercato ==========
let chainlinkPrice = null;
let priceAtWindowStart = null;
let currentWindowStart = null;
let currentMarketSlug = null;
let currentTokenIdUp = null;
let currentTokenIdDown = null;
let currentBestBidUp = null, currentBestAskUp = null;
let currentBestBidDown = null, currentBestAskDown = null;
let currentBookUp = null, currentBookDown = null;
let signalFiredThisWindow = false;
let activeClobWs = null;
let activeClobPingInterval = null;
let lastDiagLogMs = 0;

// ========== Order-flow imbalance ==========
// Rapporto tra size in bid e size totale (bid+ask), limitato ai livelli
// entro ORDER_FLOW_BAND dal best bid/ask (non l'intero book profondo).
// > 0.5 = più pressione in acquisto che in vendita vicino al prezzo corrente.
function getOrderFlowRatio(book, bestBid, bestAsk) {
  if (!book || bestBid === null || bestAsk === null) return null;
  const band = cfg.ORDER_FLOW_BAND;

  const bidDepth = (book.bids || [])
    .filter((b) => parseFloat(b.price) >= bestBid - band)
    .reduce((sum, b) => sum + parseFloat(b.size), 0);

  const askDepth = (book.asks || [])
    .filter((a) => parseFloat(a.price) <= bestAsk + band)
    .reduce((sum, a) => sum + parseFloat(a.size), 0);

  const total = bidDepth + askDepth;
  if (total <= 0) return null;
  return bidDepth / total;
}

// ========== RTDS WebSocket ==========
function connectRTDS() {
  const ws = new WebSocket(RTDS_URL);

  ws.on('open', () => {
    console.log('[RTDS] Connesso.');
    ws.send(JSON.stringify({
      action: 'subscribe',
      subscriptions: [{ topic: 'crypto_prices_chainlink', type: 'update', filters: '{"symbol":"btc/usd"}' }],
    }));
    setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.send('PING'); }, 5000);
  });

  ws.on('message', (raw) => {
    const text = raw.toString();
    if (text === 'PONG') return;
    let msg;
    try { msg = JSON.parse(text); } catch { return; }

    if (msg.topic === 'crypto_prices_chainlink' && msg.payload?.symbol === 'btc/usd') {
      chainlinkPrice = msg.payload.value;

      const { windowStart } = computeCurrentWindow();
      if (windowStart !== currentWindowStart) {
        priceAtWindowStart = chainlinkPrice;
        currentWindowStart = windowStart;
        signalFiredThisWindow = false;
      }

      priceHistory.push({ ts: Date.now(), price: chainlinkPrice });
      const cutoff = Date.now() - 10 * 60 * 1000;
      priceHistory = priceHistory.filter((p) => p.ts > cutoff);

      evaluateSignal();
    }
  });

  ws.on('close', () => {
    console.warn('[RTDS] Chiuso. Riconnetto in 3s...');
    setTimeout(connectRTDS, 3000);
  });

  ws.on('error', (err) => console.error(`[RTDS] Errore: ${err.message}`));
}

// ========== CLOB WebSocket ==========
function connectClobMarket(tokenIdUp, tokenIdDown) {
  if (activeClobWs?.readyState === WebSocket.OPEN) {
    activeClobWs.close();
  }
  if (activeClobPingInterval) {
    clearInterval(activeClobPingInterval);
  }

  const ws = new WebSocket(CLOB_WS_URL);
  const slugAtOpen = currentMarketSlug;

  ws.on('open', () => {
    console.log(`[CLOB] Connesso per ${slugAtOpen}`);
    ws.send(JSON.stringify({
      type: 'market',
      assets_ids: [tokenIdUp, tokenIdDown],
      custom_feature_enabled: true,
    }));
    activeClobPingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('PING');
    }, 10000);
  });

  ws.on('message', (raw) => {
    if (slugAtOpen !== currentMarketSlug) return;
    const text = raw.toString();
    if (text === 'PONG') return;
    let parsed;
    try { parsed = JSON.parse(text); } catch { return; }

    // Il primo messaggio dopo la sottoscrizione (snapshot iniziale) arriva
    // come ARRAY di più eventi (uno per asset); gli aggiornamenti
    // incrementali arrivano come oggetto singolo. Normalizziamo sempre
    // a un array per gestire entrambi i casi allo stesso modo.
    const msgs = Array.isArray(parsed) ? parsed : [parsed];

    for (const msg of msgs) {
      if (msg.event_type === 'best_bid_ask') {
        if (msg.asset_id === tokenIdUp) {
          currentBestBidUp = msg.best_bid ? parseFloat(msg.best_bid) : null;
          currentBestAskUp = msg.best_ask ? parseFloat(msg.best_ask) : null;
        }
        if (msg.asset_id === tokenIdDown) {
          currentBestBidDown = msg.best_bid ? parseFloat(msg.best_bid) : null;
          currentBestAskDown = msg.best_ask ? parseFloat(msg.best_ask) : null;
        }
        evaluateSignal();
      } else if (msg.event_type === 'book') {
        // NB: non usiamo più 'book' per il prezzo (i livelli coprono
        // l'intero range 0.01-0.99, Math.min(asks) prendeva il livello
        // più profondo del book, non il best ask reale). 'best_bid_ask'
        // resta l'unica fonte del prezzo. Il book serve solo per
        // l'order-flow imbalance (vedi getOrderFlowRatio).
        if (msg.asset_id === tokenIdUp) currentBookUp = msg;
        if (msg.asset_id === tokenIdDown) currentBookDown = msg;
      }
    }
  });

  ws.on('close', () => {
    if (activeClobPingInterval) clearInterval(activeClobPingInterval);
  });

  ws.on('error', (err) => console.error(`[CLOB] Errore: ${err.message}`));

  activeClobWs = ws;
}

// ========== Utility ==========
function computeCurrentWindow() {
  const nowSec = Math.floor(Date.now() / 1000);
  const windowStart = nowSec - (nowSec % INTERVAL_SEC);
  return { windowStart, windowEnd: windowStart + INTERVAL_SEC };
}

// ========== LOGICA V3: momentum, non contrarian ==========
function evaluateSignal() {
  if (signalFiredThisWindow) return;
  if (chainlinkPrice === null || currentWindowStart === null) return;

  const { windowStart } = computeCurrentWindow();
  if (windowStart !== currentWindowStart) return;

  // 1. GATE TEMPORALE: (quasi) tutta la finestra, vedi commento sopra
  const secondsIntoWindow = Math.floor(Date.now() / 1000) - currentWindowStart;
  if (secondsIntoWindow < ENTRY_WINDOW_START_SEC) return;
  if (secondsIntoWindow >= ENTRY_WINDOW_END_SEC) return;

  // volBps resta solo informativo (vedi commento sopra sulla sua inaffidabilità)
  const volBps = getRecentVolBps();
  const priceChangePct = ((chainlinkPrice - priceAtWindowStart) / priceAtWindowStart) * 100;
  const moveBps = Math.abs(priceChangePct) * 100;

  // 2. Direzione favorita dal movimento BTC reale (non da una formula di
  // "fair value" — vedi commento in cima al file sul perché era invertita)
  const favorsUp = priceChangePct > 0;
  const tokenName = favorsUp ? 'UP' : 'DOWN';
  const tokenId = favorsUp ? currentTokenIdUp : currentTokenIdDown;
  const ask = favorsUp ? currentBestAskUp : currentBestAskDown;
  const bid = favorsUp ? currentBestBidUp : currentBestBidDown;
  const book = favorsUp ? currentBookUp : currentBookDown;

  let signal = null;
  let rejectReason = null;

  if (moveBps < MIN_MOVE_BPS) {
    rejectReason = `movimento ${moveBps.toFixed(1)}bps < ${MIN_MOVE_BPS}bps`;
  } else if (ask === null) {
    rejectReason = 'ask n/d';
  } else if (ask < MOMENTUM_MIN_ASK) {
    rejectReason = `ask ${ask.toFixed(3)} < ${MOMENTUM_MIN_ASK} (mercato non ancora convinto)`;
  } else if (ask > MOMENTUM_MAX_ASK) {
    rejectReason = `ask ${ask.toFixed(3)} > ${MOMENTUM_MAX_ASK} (già convergo, nessun edge residuo)`;
  } else {
    const flowRatio = getOrderFlowRatio(book, bid, ask);
    if (flowRatio === null || flowRatio < cfg.ORDER_FLOW_MIN_RATIO) {
      rejectReason = `order-flow ${flowRatio === null ? 'n/d' : flowRatio.toFixed(2)} < ${cfg.ORDER_FLOW_MIN_RATIO}`;
    } else {
      signal = { tokenName, tokenId, bestAsk: ask, priceChangePct, flowRatio };
    }
  }

  // Log diagnostico (throttled, ~1 ogni 10s) per capire perché non si entra,
  // anche quando nessun gate viene superato.
  if (Date.now() - lastDiagLogMs > 10000) {
    lastDiagLogMs = Date.now();
    console.log(
      `[DIAG] t=${secondsIntoWindow}s | BTC ${priceChangePct >= 0 ? '+' : ''}${priceChangePct.toFixed(3)}% (${moveBps.toFixed(1)}bps) | ` +
      `vol=${volBps.toFixed(0)}bps(info) | favorito=${tokenName} ask=${ask?.toFixed(3) ?? 'n/d'} ` +
      `[${signal ? 'OK' : rejectReason}]`
    );
  }

  if (!signal) return;

  signalFiredThisWindow = true;

  const size = MAX_TRADE_SIZE_USDC;

  console.log(
    `\n[SEGNALE V3] ${signal.tokenName} | t=${secondsIntoWindow}s | ask=${signal.bestAsk.toFixed(3)} | ` +
    `BTC ${signal.priceChangePct >= 0 ? '+' : ''}${signal.priceChangePct.toFixed(3)}% | ` +
    `flow=${signal.flowRatio.toFixed(2)} | size=$${size.toFixed(2)}`
  );

  logEvent({
    type: 'signal_v3',
    ...signal,
    secondsIntoWindow,
    volBps,
    size,
    priceAtEntry: chainlinkPrice,
    slug: currentMarketSlug,
  });

  executeTrade(signal, size);
}

// ========== Esecuzione trade ==========
async function executeTrade(signal, size) {
  if (checkKillSwitch()) {
    logEvent({ type: 'blocked_kill_switch', tokenName: signal.tokenName, slug: currentMarketSlug });
    return;
  }
  if (!checkRateLimit()) {
    logEvent({ type: 'blocked_rate_limit', tokenName: signal.tokenName, slug: currentMarketSlug });
    return;
  }
  if (!checkDailyLoss()) {
    logEvent({ type: 'blocked_daily_loss', tokenName: signal.tokenName, slug: currentMarketSlug });
    return;
  }

  if (!IS_LIVE) {
    console.log(`[DRY-RUN] Comprerei $${size.toFixed(2)} di ${signal.tokenName} a ${signal.bestAsk.toFixed(3)}`);
    logEvent({
      type: 'dry_run_trade',
      tokenName: signal.tokenName,
      tokenId: signal.tokenId,
      size,
      bestAsk: signal.bestAsk,
      fairValue: signal.fairValue,
      slug: currentMarketSlug,
    });
    pendingReconciliation.push({
      slug: currentMarketSlug,
      tokenName: signal.tokenName,
      size,
      bestAsk: signal.bestAsk,
      fairValue: signal.fairValue,
      signaledAtMs: Date.now(),
      live: false,
    });
    return;
  }

  try {
    console.log(`[LIVE] BUY $${size.toFixed(2)} ${signal.tokenName} @ ${signal.bestAsk.toFixed(3)}`);
    const marketOrder = { tokenID: signal.tokenId, amount: size, side: Side.BUY };
    const signedOrder = await clobClient.createMarketOrder(marketOrder);
    const resp = await clobClient.postOrder(signedOrder, OrderType.FOK);

    if (resp && typeof resp === 'object' && resp.error) {
      throw new Error(`CLOB error: ${resp.error}`);
    }

    console.log('[LIVE] Ordine piazzato:', resp);
    logEvent({
      type: 'live_trade_submitted',
      tokenName: signal.tokenName,
      tokenId: signal.tokenId,
      size,
      bestAsk: signal.bestAsk,
      fairValue: signal.fairValue,
      slug: currentMarketSlug,
      response: resp,
    });

    tradesThisHour.push(Date.now());
    pendingReconciliation.push({
      slug: currentMarketSlug,
      tokenName: signal.tokenName,
      size,
      bestAsk: signal.bestAsk,
      fairValue: signal.fairValue,
      signaledAtMs: Date.now(),
      live: true,
    });
  } catch (err) {
    console.error(`[LIVE] Errore: ${err.message}`);
    logEvent({
      type: 'live_trade_failed',
      tokenName: signal.tokenName,
      tokenId: signal.tokenId,
      size,
      error: err.message,
      slug: currentMarketSlug,
    });
  }
}

// ========== Reconciliation ==========
let pendingReconciliation = [];

async function reconcileClosedWindows() {
  if (pendingReconciliation.length === 0) return;

  const now = Date.now();
  const stillPending = [];

  for (const pending of pendingReconciliation) {
    if (now - pending.signaledAtMs < 6 * 60 * 1000) {
      stillPending.push(pending);
      continue;
    }

    try {
      const { data } = await axios.get(`${GAMMA_BASE}/markets/slug/${pending.slug}`, { timeout: 8000 });
      const market = Array.isArray(data) ? data[0] : data;

      if (!market?.closed) {
        if (now - pending.signaledAtMs < 20 * 60 * 1000) {
          stillPending.push(pending);
        } else {
          console.warn(`[RECONCILE] ${pending.slug}: timeout`);
        }
        continue;
      }

      const outcomes = typeof market.outcomes === 'string' ? JSON.parse(market.outcomes) : market.outcomes;
      const outcomePrices = typeof market.outcomePrices === 'string' ? JSON.parse(market.outcomePrices) : market.outcomePrices;

      const upIdx = outcomes?.indexOf('Up') ?? 0;
      const upWon = parseFloat(outcomePrices[upIdx]) === 1;
      const actualOutcome = upWon ? 'UP' : 'DOWN';

      const won = actualOutcome === pending.tokenName;
      const settlePrice = won ? 1.0 : 0.0;
      // pending.size è in dollari, non in shares: va prima convertito
      // (shares = size/ask) prima di applicare il payoff. La versione
      // precedente moltiplicava direttamente size per (settle-ask),
      // sottostimando sia vincite che perdite di un fattore ~1/ask.
      const shares = pending.size / pending.bestAsk;
      const realPnl = shares * (settlePrice - pending.bestAsk);

      realizedPnL += realPnl;
      reconciledCount++;

      console.log(
        `[RECONCILE] ${pending.slug}: ${pending.tokenName} @ ${pending.bestAsk.toFixed(3)} → ${actualOutcome} ` +
        `(${won ? 'WIN' : 'LOSS'}) | P&L: $${realPnl.toFixed(3)} | Cum: $${realizedPnL.toFixed(3)}`
      );

      logEvent({
        type: 'reconciled',
        slug: pending.slug,
        tokenName: pending.tokenName,
        actualOutcome,
        won,
        realPnl,
        bestAsk: pending.bestAsk,
        settlePrice,
        fairValue: pending.fairValue,
        live: pending.live,
        cumulativeRealizedPnL: realizedPnL,
      });
    } catch (err) {
      console.warn(`[RECONCILE] Errore ${pending.slug}: ${err.message}`);
      stillPending.push(pending);
    }
  }

  pendingReconciliation = stillPending;
}

// ========== Refresh mercato ==========
async function fetchCurrentMarket() {
  const { windowStart } = computeCurrentWindow();
  const slug = `btc-updown-${INTERVAL_MIN}m-${windowStart}`;

  try {
    const { data } = await axios.get(`${GAMMA_BASE}/markets/slug/${slug}`, { timeout: 8000 });
    const market = Array.isArray(data) ? data[0] : data;
    if (!market) return null;

    const clobTokenIds = typeof market.clobTokenIds === 'string' ? JSON.parse(market.clobTokenIds) : market.clobTokenIds;
    const outcomes = typeof market.outcomes === 'string' ? JSON.parse(market.outcomes) : market.outcomes;
    const upIdx = outcomes?.indexOf('Up') ?? 0;
    const downIdx = upIdx === 0 ? 1 : 0;

    return {
      slug,
      conditionId: market.conditionId,
      tokenIdUp: clobTokenIds?.[upIdx],
      tokenIdDown: clobTokenIds?.[downIdx],
      windowStart,
    };
  } catch (err) {
    return null;
  }
}

async function refreshMarketLoop() {
  let loopCount = 0;
  while (true) {
    const market = await fetchCurrentMarket();
    if (market && market.slug !== currentMarketSlug) {
      console.log(`\n[MERCATO] Nuova finestra: ${market.slug}`);

      currentMarketSlug = market.slug;
      currentTokenIdUp = market.tokenIdUp;
      currentTokenIdDown = market.tokenIdDown;
      currentBestBidUp = null;
      currentBestAskUp = null;
      currentBestBidDown = null;
      currentBestAskDown = null;
      signalFiredThisWindow = false;

      if (currentTokenIdUp && currentTokenIdDown) {
        connectClobMarket(currentTokenIdUp, currentTokenIdDown);
      }
    }

    await reconcileClosedWindows();

    loopCount++;
    if (loopCount % 8 === 0 && reconciledCount > 0) {
      console.log(
        `\n[RIEPILOGO] ${reconciledCount} trades | P&L: $${realizedPnL.toFixed(3)} | ` +
        `${pendingReconciliation.length} pending\n`
      );
    }

    await new Promise((r) => setTimeout(r, 15000));
  }
}

// ========== Main ==========
async function main() {
  console.log('=== Bot Momentum BTC Up/Down V3 ===');
  console.log(`Modalità: ${IS_LIVE ? 'LIVE ⚠️' : 'DRY-RUN'}`);
  console.log(`Momentum: ask tra ${MOMENTUM_MIN_ASK} e ${MOMENTUM_MAX_ASK}, movimento min ${MIN_MOVE_BPS}bps, order-flow min ${cfg.ORDER_FLOW_MIN_RATIO}`);
  console.log(`Entry window: t=${ENTRY_WINDOW_START_SEC}s..${ENTRY_WINDOW_END_SEC}s (finestra ${INTERVAL_SEC}s)`);
  console.log(`Kill switch: ${KILL_SWITCH_FILE}\n`);

  if (IS_LIVE) {
    await initClobClient();
  }

  connectRTDS();
  await refreshMarketLoop();
}

process.on('SIGINT', () => {
  console.log('\nInterrotto. Chiudo log...');
  logStream.end(() => process.exit(0));
});

main().catch((err) => {
  console.error('Errore fatale:', err);
  process.exit(1);
});
