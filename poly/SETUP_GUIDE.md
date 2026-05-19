# ============================================================================
# POLYMARKET COPYTRADE BOT - SETUP GUIDE
# ============================================================================

## PREREQUISITI
- Python 3.9+
- pip (package manager)
- Un wallet Polymarket con $10 USDC/pUSD

## STEP 1: INSTALLA DIPENDENZE

```bash
pip install -r requirements.txt
```

## STEP 2: OTTIENI LE CREDENZIALI

### A) Ottieni Wallet Address e Private Key:

1. Vai su https://polymarket.com
2. Connetti il tuo wallet (MetaMask, WalletConnect, ecc.)
3. Clicca su "Settings" → "Security"
4. Copia il tuo wallet address (formato: 0x...)
5. Per la private key:
   - MetaMask: Settings → Security & Privacy → "Reveal Secret Recovery Phrase"
   - IMPORTANTE: NON condividere mai la private key!

### B) (Opzionale) Ottieni API Key:

Se vuoi rate limiting più alto:
1. Vai su https://docs.polymarket.com
2. Registrati come developer
3. Crea una nuova API key nella dashboard

## STEP 3: CONFIGURA VARIABILI AMBIENTE

### Opzione A: File .env (CONSIGLIATO)

Crea un file `.env` nella stessa directory dello script:

```
POLYMARKET_WALLET_ADDRESS=0x1234567890abcdef...
POLYMARKET_PRIVATE_KEY=0x1234567890abcdef...
POLYMARKET_API_KEY=your_api_key_here
```

### Opzione B: Variabili shell

```bash
export POLYMARKET_WALLET_ADDRESS="0x..."
export POLYMARKET_PRIVATE_KEY="0x..."
export POLYMARKET_API_KEY="..."
```

## STEP 4: CONFIGURA PARAMETRI

Modifica questi valori in `polymarket_copytrade.py` classe `Config`:

```python
class Config:
    INITIAL_WALLET = 10.0           # Capitale iniziale ($)
    MAX_RISK_PER_TRADE = 0.05       # 5% rischio massimo per trade
    MIN_WALLET_BALANCE = 1.0        # Protezione minima wallet
    MAX_DRAWDOWN = 0.50             # Max perdita consentita (50%)
    TOP_TRADERS = 10                # Quanti trader copiare
    MIN_TRADER_ROI = 0.10           # ROI minimo trader (10%)
    COPY_MULTIPLIER = 0.80          # Copia 80% posizione originale
```

## STEP 5: ESEGUI IL BOT

```bash
python polymarket_copytrade.py
```

Output:
- Logs console in tempo reale
- `copytrade_stats.json` - Statistiche portfolio
- `copytrade_log.json` - Storico trade

## ============================================================================
# STRATEGIA DI MONEY MANAGEMENT
# ============================================================================

### Kelly Criterion (Frazionato 0.25x per sicurezza)

Formula: f = (p*b - q) / b * 0.25

Dove:
- f = frazione del bankroll per trade
- p = probabilità di vittoria
- q = probabilità di perdita
- b = rapporto payoff/rischio

### Protezioni Built-in:

1. **Max 5% rischio per singolo trade**
   - Impossibile perdere più di 5% del wallet in un trade

2. **Diversificazione su 10 trader**
   - Non dipendi da 1 solo trader
   - Risk spread = min(wallet/10, allocation)

3. **Stop Loss**
   - Chiudi posizioni a -20% di perdita
   - Chiudi portfolio a drawdown -50%

4. **Minimum Balance**
   - Mantieni sempre min $1 nel wallet
   - Protezione contro bankruptcy

## ============================================================================
# COME FUNZIONA
# ============================================================================

### Iteration Loop (ogni 5 minuti):

1. FETCH TOP TRADERS
   └─ Ottieni i 10 trader migliori per ROI %
   └─ Filtra: ROI ≥ 10%, trades ≥ 5

2. RANK TRADERS
   └─ Score = ROI * (win_rate²) * √(Sharpe) * log(trades)
   └─ Top performer in alto

3. ALLOCATE CAPITAL
   └─ Distribuisci ${WALLET} proporzionale al score
   └─ Trader 1: $3.00 | Trader 2: $2.50 | ecc.

4. COPY TRADES
   └─ Per ogni posizione aperta del trader
   └─ Copia 80% della size
   └─ Alla stessa probabilità

5. UPDATE POSITIONS
   └─ Aggiorna valore positions
   └─ Calcola P&L unrealized

6. RISK MANAGEMENT
   └─ Chiudi posizioni "bad" (>-20% loss)
   └─ Chiudi portfolio se drawdown > 50%

7. PRINT STATS
   └─ Mostra wallet, equity, positions
   └─ Mostra drawdown %

## ============================================================================
# ESEMPI SCENARIO
# ============================================================================

### Scenario 1: Buon Performante

```
Iteration 1:
- Top Trader "ProTrader" con ROI +250%
- Alloca $3.00 a lui
- Copia posizione WTI >$105 (size 10 tokens)
- Copia 8 tokens al nostro wallet

Iteration 5:
- Posizione up a +12%
- Value: $3.00 * 1.12 = $3.36
- Portfolio equity: $10 + $0.36 = $10.36 ✅

Iteration 20:
- Total equity: $11.50
- Realized P&L: +$1.50
- Drawdown: -0% (siamo in profitto!)
```

### Scenario 2: Protezione da Perdita

```
Iteration 1:
- Alloca $10 su diversi trader

Iteration 8:
- Uno dei trader inizia a perdere
- Posizione down a -22%
- TRIGGER: Stop loss -20%
- Close posizione → Realized loss -$0.20

Portfolio rimane:
- Wallet: $9.80 (protetto!)
- Drawdown: -2% (contenuto)
```

### Scenario 3: Max Drawdown

```
Iterazione 1-50:
- Trading sfavorevole
- Equity scende a $5.00
- Drawdown = (10 - 5) / 10 * 100 = -50%

TRIGGER: Max drawdown raggiunto!
- Close TUTTI le posizioni aperte
- Stop trading
- Proteggi i $5 rimasti
```

## ============================================================================
# MONITORING & TROUBLESHOOTING
# ============================================================================

### Problema: API errors frequenti

```
Soluzione 1: Aumenta timeout
- Modifica in PolymarketDataFetcher: timeout=20 (invece 10)

Soluzione 2: Aggiungi retry logic
- Aggiungi decorator @retry(max_attempts=3)

Soluzione 3: Usa API Key
- Registrati come developer su docs.polymarket.com
- Inserisci API key in .env
```

### Problema: Positions non si chiudono

```
Controlla:
1. Wallet ha saldo > 0.01 USDC per fee?
2. Private key è corretta?
3. Posizioni sono realmente "ACTIVE"?

Debug:
- Aggiungi logger.info() nel codice
- Stampa position data: print(pos.__dict__)
```

### Problema: Money not flowing

```
Verifiche:
1. Wallet è sulla rete Polygon?
2. Hai pUSD o USDC nel wallet?
3. Smart contract è stato approvato? (April 28 upgrade)

Soluzione:
- Vai su Polymarket.com
- Approve il nuovo exchange contract v2
- Converti USDC a pUSD
```

## ============================================================================
# BEST PRACTICES
# ============================================================================

### DO ✅

- Inizia con small amount ($10-50)
- Monitora il bot per prima settimana
- Usa diversificazione (10+ trader)
- Riceverai email alerts da Polymarket
- Tieni aggiornate le posizioni

### DON'T ❌

- NON condividere private key con nessuno
- NON usare denaro che non puoi permetterti di perdere
- NON avere bot su account con crypto significativa
- NON disabilitare protezioni di rischio
- NON operare durante volatilità massima (USA-Iran news)

## ============================================================================
# ADVANCED: MODIFICHE CUSTOM
# ============================================================================

### Aumentare Aggressività (Rischio Maggiore):

```python
# In Config class:
COPY_MULTIPLIER = 1.2          # Copia 120% invece 80%
MAX_RISK_PER_TRADE = 0.10      # 10% rischio invece 5%
MAX_DRAWDOWN = 0.75            # 75% drawdown max invece 50%
```

### Usare Traders Specifici:

```python
# Nel metodo _execute_copytrades():
allowed_traders = ["0xtrader1", "0xtrader2"]
if trader.address not in allowed_traders:
    continue
```

### Aggiungere Custom Indicators:

```python
# In MoneyManagementEngine:
def calculate_trader_confidence(trader: TraderMetrics) -> float:
    # Aggiungi logica custom
    vix_level = fetch_vix()  # Volatilità di mercato
    macro_score = analyze_macro()  # Fattori macro
    return (trader.score * 0.7 + macro_score * 0.3)
```

## ============================================================================
# DISCLAIMER
# ============================================================================

QUESTO BOT È A SCOPO EDUCATIVO.

I MERCATI PREDITTIVI COMPORTANO RISCHI:
- Puoi perdere tutto il denaro investito
- Correlazioni impreviste tra mercati
- Smart contract risk (approx 0.1%)
- Slippage su ordini
- Liquidità insufficiente

USARE A TUO RISCHIO.
L'autore NON è responsabile di perdite.

## ============================================================================
# CONTATTI & SUPPORTO
# ============================================================================

Problemi?
- Controlla logs in copytrade_log.json
- Visita docs.polymarket.com
- Join Polymarket Discord per help
