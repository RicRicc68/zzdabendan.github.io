# Bybit Pump Scanner (solo osservazione)

Nessuna chiave API, nessun ordine: monitora tutti i perpetual USDT su
Bybit (`GET /v5/market/tickers?category=linear`, dato pubblico) e logga
sistematicamente cosa succede al prezzo DOPO un movimento anomalo, per
avere dati reali prima di considerare qualunque bot con leva.

## Come funziona

1. Ogni 5s scarica i prezzi di tutti i ~740 perpetual USDT.
2. Se un simbolo si muove oltre soglia in 1 o 5 minuti (default: 8% in
   60s o 15% in 300s, vedi `config.js`), lo mette "in osservazione".
3. Per i 60 minuti successivi registra checkpoint di prezzo a
   60/300/900/1800/3600s, il massimo raggiunto, il minimo, e soprattutto
   il **max drawdown dal picco** — cioè: se fosse continuato a salire e
   poi crollato, quanto sarebbe stato il tracollo dal massimo? Questo è
   il dato che serve per capire se una leva 25x/50x sarebbe sopravvissuta.
4. Ogni evento concluso viene scritto come riga JSON in `pump_events.jsonl`.

## Uso locale

```bash
cd bybit-scanner
npm install
node index.js
```

## Analizzare i dati raccolti

```bash
node -e "
const fs = require('fs');
const events = fs.readFileSync('pump_events.jsonl', 'utf8')
  .trim().split('\n').filter(Boolean).map(JSON.parse);
console.log('eventi totali:', events.length);
console.log('drawdown medio da picco:', 
  (events.reduce((s,e)=>s+e.maxDrawdownFromPeakPct,0)/events.length).toFixed(1) + '%');
// quanti avrebbero liquidato una leva 25x (drawdown >= 4%) o 50x (>= 2%)?
console.log('avrebbero liquidato una 25x:', events.filter(e=>e.maxDrawdownFromPeakPct>=4).length);
console.log('avrebbero liquidato una 50x:', events.filter(e=>e.maxDrawdownFromPeakPct>=2).length);
"
```

## Deploy su Render

Vedi il servizio `bybit-pump-scanner` in `../render.yaml`. Nessuna env
var necessaria.

**Attenzione alla persistenza**: il filesystem dei servizi Render free
è effimero — `pump_events.jsonl` si azzera ad ogni redeploy (non ad ogni
riavvio/sleep, solo quando pushi codice nuovo). Finché non tocchiamo il
codice i dati restano; ogni evento viene comunque stampato anche su
console (`[PUMP]` / `[PUMP DONE]`), visibile nei log di Render per la
finestra di retention del piano. Se vuoi raccolta dati garantita su
settimane a prescindere dai redeploy, conviene aggiungere in futuro
l'invio di ogni evento concluso altrove (es. Telegram, un piccolo DB
esterno) — dimmelo quando vuoi che lo implementiamo.

## Calibrazione soglie

`DETECT_WINDOWS` in `config.js` sono valori di partenza. Se i log si
riempiono di eventi banali, alza le soglie; se non arriva nulla per
ore, abbassale.
