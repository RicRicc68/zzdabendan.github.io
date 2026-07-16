# Bot momentum BTC Up/Down (Node.js, CLOB v2 + RTDS)

Secondo bot, indipendente dal bot Python in `../`, ma **stesso wallet**
(stesse env `POLY_PRIVATE_KEY`/`POLY_FUNDER`/`POLY_SIGNATURE_TYPE`). I
guardrail dei due bot sono indipendenti: l'esposizione reale è la somma
di entrambi.

## Strategia (in breve)

Guarda il prezzo Chainlink di BTC/USD via RTDS e lo confronta con l'ask
del mercato "Up/Down" a 5 minuti su Polymarket, negli ultimi 45 secondi
della finestra. Entra solo se c'è un edge diretto (`ask` gia' spostato
nella direzione del movimento di prezzo) sopra una soglia minima e con
volatilita' recente sufficiente. Vedi i commenti in `index.js` per i
dettagli dei parametri (`UP_ENTRY_MIN_ASK`, `MIN_EDGE_BPS`, ecc.).

## Setup locale

```bash
cd arb-bot
npm install
cp .env.example .env   # compila le tue chiavi
node index.js          # dry-run: logga i segnali, nessun ordine reale
node index.js --live   # LIVE: ordini reali con capitale vero
```

## Guardrail

- `MAX_TRADE_SIZE_USDC = 5` — tetto per singolo ordine
- `MAX_TRADES_PER_HOUR = 999` — nessun cap orario esplicito (per scelta)
- `MAX_DAILY_LOSS_USDC = 30` — stop giornaliero sul P&L realizzato
- Kill switch: crea un file `STOP_ARB` nella working dir per fermare il bot

Valori in `realbot4aa.js`.

## Proxy (geoblock Polymarket)

Stesso discorso del bot Python (vedi `../deploy/aws_spain_proxy/`): se
l'host non e' in una regione autorizzata, `POST /order` torna 403.
Basta impostare `PROXY_URL` nell'env — sia le chiamate REST del client
CLOB Node sia `axios` la rispettano automaticamente (verificato). I due
WebSocket (RTDS e CLOB market feed) restano diretti: sono solo dati
pubblici in lettura, non soggetti al geoblock.

## Deploy su Render

Vedi il secondo servizio (`polymarket-arb-bot`) in `../render.yaml`.
Parte in **dry-run** (`node server.js`, senza `--live`): logga solo i
segnali. Passa a live cambiando lo startCommand in
`node server.js --live` dalla dashboard Render solo dopo aver
verificato che i segnali abbiano senso nei log.
