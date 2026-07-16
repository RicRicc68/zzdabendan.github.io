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

// ===== PARAMETRI V2 — TUNING CONSERVATIVO =====

// V2: Entrambi solo se c'è DISCONNESSIONE DIREZIONALE chiara
// Compra UP solo se ask > 0.52 (il mercato dice UP con >52% prob)
// Compra DOWN solo se ask < 0.48 (il mercato dice DOWN con >52% prob)
const UP_ENTRY_MIN_ASK = 0.52;   // buy UP solo se il mercato già pensa sia probabile
const DOWN_ENTRY_MAX_ASK = 0.48; // buy DOWN solo se il mercato già pensa sia probabile

// Discount reale: ask deve essere ALMENO 3 centesimi sotto il fair value implicito
// (non chiedere "quanto è scontato da 0.5" — chiedi "quanto è scontato dal prezzo indicato")
const MIN_EDGE_BPS = 30; // 30 basis points = 0.03 di edge minimo

// Size: proporzionale all'edge. Max $5 (mantenuto da guardrail).
// Se edge > 5% → size pieno. Se edge 0.3% → size ridotta.
const SIZE_FRACTION = 0.3; // frazione di MAX_TRADE_SIZE_USDC da usare

// Entry: SOLO negli ultimi 45 secondi della finestra
// (non 120s, non 180s — 45 secondi. Il prezzo deve ESSERE vicino a convergenza)
const ENTRY_WINDOW_LAST_SECONDS = 45;

// Volatilità minima per entrare: deviazione standard 5min di BTC
// deve essere > 0.3% (altrimenti il mercato è sideways e il prezzo è random)
const MIN_VOLAT_BPS = 30; // 30 bps = 0.3%

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
let signalFiredThisWindow = false;
let activeClobWs = null;
let activeClobPingInterval = null;

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
    let msg;
    try { msg = JSON.parse(text); } catch { return; }

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
      if (msg.asset_id === tokenIdUp && msg.asks?.length > 0) {
        currentBestAskUp = Math.min(...msg.asks.map((a) => parseFloat(a.price)));
      }
      if (msg.asset_id === tokenIdDown && msg.asks?.length > 0) {
        currentBestAskDown = Math.min(...msg.asks.map((a) => parseFloat(a.price)));
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

// ========== LOGICA V2: valuta segnale ==========
function evaluateSignal() {
  if (signalFiredThisWindow) return;
  if (chainlinkPrice === null || currentWindowStart === null) return;

  const { windowStart } = computeCurrentWindow();
  if (windowStart !== currentWindowStart) return;

  // 1. GATE TEMPORALE: solo ultimi 45 secondi
  const secondsIntoWindow = Math.floor(Date.now() / 1000) - currentWindowStart;
  if (secondsIntoWindow < INTERVAL_SEC - ENTRY_WINDOW_LAST_SECONDS) return;
  if (secondsIntoWindow >= INTERVAL_SEC) return;

  // 2. GATE VOLATILITÀ: deviazione std 5min > 0.3%
  const volBps = getRecentVolBps();
  if (volBps < MIN_VOLAT_BPS) return;

  // 3. Calcolo fair value basato su prezzo di window start
  // Se BTC è salito > 0.2% → fair value UP > 0.52
  // Se BTC è sceso > 0.2% → fair value DOWN > 0.52
  const priceChangePct = ((chainlinkPrice - priceAtWindowStart) / priceAtWindowStart) * 100;
  const fairValueUp = 0.5 + (priceChangePct * 0.5); // amplifico per essere conservativo
  const fairValueDown = 1 - fairValueUp;

  // 4. Valuta UP
  let upSignal = null;
  if (currentBestAskUp !== null) {
    // Solo se ask > 0.52 (il mercato dice UP probabile)
    if (currentBestAskUp >= UP_ENTRY_MIN_ASK) {
      const discount = fairValueUp - currentBestAskUp;
      if (discount >= MIN_EDGE_BPS / 100) {
        upSignal = {
          tokenName: 'UP',
          tokenId: currentTokenIdUp,
          bestAsk: currentBestAskUp,
          fairValue: fairValueUp,
          discount,
          edgeBps: discount * 10000,
        };
      }
    }
  }

  // 5. Valuta DOWN
  let downSignal = null;
  if (currentBestAskDown !== null) {
    // Solo se ask < 0.48 (il mercato dice DOWN probabile)
    if (currentBestAskDown <= DOWN_ENTRY_MAX_ASK) {
      const discount = fairValueDown - currentBestAskDown;
      if (discount >= MIN_EDGE_BPS / 100) {
        downSignal = {
          tokenName: 'DOWN',
          tokenId: currentTokenIdDown,
          bestAsk: currentBestAskDown,
          fairValue: fairValueDown,
          discount,
          edgeBps: discount * 10000,
        };
      }
    }
  }

  // 6. Scegli il migliore (edge più alto)
  const bestSignal = upSignal && downSignal
    ? (upSignal.edgeBps > downSignal.edgeBps ? upSignal : downSignal)
    : (upSignal || downSignal);

  if (!bestSignal) return;

  signalFiredThisWindow = true;

  const size = Math.min(
    MAX_TRADE_SIZE_USDC,
    (bestSignal.edgeBps / (MIN_EDGE_BPS * 2)) * MAX_TRADE_SIZE_USDC * SIZE_FRACTION + MAX_TRADE_SIZE_USDC * 0.5
  );

  console.log(
    `\n[SEGNALE V2] ${bestSignal.tokenName} | t=${secondsIntoWindow}s | ask=${bestSignal.bestAsk.toFixed(3)} | ` +
    `fair=${bestSignal.fairValue.toFixed(3)} | edge=${bestSignal.edgeBps.toFixed(0)}bps | vol=${volBps.toFixed(0)}bps | size=$${size.toFixed(2)}`
  );

  logEvent({
    type: 'signal_v2',
    ...bestSignal,
    secondsIntoWindow,
    volBps,
    size,
    priceAtEntry: chainlinkPrice,
    slug: currentMarketSlug,
  });

  executeTrade(bestSignal, size);
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
      const realPnl = won ? (settlePrice - pending.bestAsk) * pending.size : -pending.bestAsk * pending.size;

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
  console.log('=== Bot Arbitraggio BTC Up/Down V2 ===');
  console.log(`Modalità: ${IS_LIVE ? 'LIVE ⚠️' : 'DRY-RUN'}`);
  console.log(`Threshold: UP > ${UP_ENTRY_MIN_ASK}, DOWN < ${DOWN_ENTRY_MAX_ASK}, edge min ${MIN_EDGE_BPS}bps`);
  console.log(`Entry window: ultimi ${ENTRY_WINDOW_LAST_SECONDS}s`);
  console.log(`Vol min: ${MIN_VOLAT_BPS}bps`);
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
