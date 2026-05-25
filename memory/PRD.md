# SEED-RECOVERY — Control Room Dashboard

## Original Problem
> "costruiscimi una dashboard per il bot da implementare nel file allegato"

The attached `README_recover.md` describes an OFFLINE recovery helper for an
Electrum 12-word seed (via `btcrecover` / `seedrecover.py` + `gen_masks.py`).
User confirmed it's HIS own BTC wallet of which he has lost the private key
and seed phrase. User choices:
- all features
- REAL subprocess execution of `btcrecover`
- no authentication
- (later) all suggested improvements + public-IP deploy

## Architecture
- **Backend**: FastAPI (`/app/backend/server.py`) + MongoDB
- **Frontend**: React 18 + Tailwind (Control Room dark theme)
- **External tool**: `/opt/btcrecover` (3rdIteration/btcrecover, cloned at setup)
- **Subprocess model**: `seedrecover.py` launched via `asyncio.create_subprocess_exec`
  using `sys.executable` so the venv (with pycryptodome) is reused

## Implemented v1.0 (2026-05-25)
- Seed configuration (12-24 words, wallet type, language, threads, typos, address/mpk/wallet file, optional passphrase)
- Mask generation (fixed + permutations, guarded against combinatorial explosion)
- Candidate wordlist editor (`candlist.txt`)
- Real subprocess execution with stdout/stderr streaming
- Live progress parsing (candidates, rate, ETA, %)
- Found-seed reveal modal (copy + clear)
- System vitals (cpu/mem/disk/btcrecover availability)
- Job history with stop/delete
- Dark "Control Room" UI

## Implemented v1.5 (2026-05-25 — GPU deploy bundle generator)
- POST `/api/deploy/preview` (JSON) and POST `/api/deploy/generate` (ZIP)
  produce a complete deploy bundle: Dockerfile (nvidia/cuda + btcrecover +
  pyopencl), run.sh (seedrecover --enable-opencl), config.json (passphrase
  redacted), candlist.txt, verify.txt, README.md, and provider-specific
  deploy script (vastai-deploy.sh or runpod-deploy.md).
- vastai-deploy.sh uses the correct CLI gpu filter — friendly labels are
  converted via `_gpu_cli_name` (e.g. "vast.ai · RTX 3090" → `RTX_3090`,
  "RunPod · A100 40GB" → `A100`, "RunPod · RTX A4000" → `RTX_A4000`).
- Frontend: `DeployBundleButton.jsx` with provider selector (vast.ai CLI /
  RunPod web), tabbed file preview, download .zip; header shows target GPU
  recommended by the Energy Cost panel (fallback "RTX 3090 (default)").
- Verified: 19/19 backend pytest + 100% frontend Playwright. Zero issues.


## Implemented v1.4 (2026-05-25 — Energy & GPU cost calculator)
- **POST `/api/jobs/cost-estimate`** — pure-math endpoint that takes
  `eta_seconds`, `system_watts`, `eur_per_kwh`, `usd_to_eur`, optional
  `provisioning_overhead_min` and returns:
  - `local.energy_kwh / energy_cost_eur / classification`
  - `gpu_options[]` for 7 typical configs (vast.ai 3060/3090/4090,
    RunPod A4000/A6000/A100/H100): hourly rate in €, GPU ETA, total
    rental cost, savings vs local, classification
  - `recommendation` ∈ {`local`, `gpu:<name>`, `do_not_run`, `n/a`} +
    human-readable message
- **Frontend `EnergyCostCalculator.jsx`** panel below Pre-flight Estimate:
  banner with color-coded recommendation, editable inputs (W, €/kWh,
  USD→EUR), Local CPU row + table of GPU options with the recommended
  one highlighted in blue. Footer reminder to use `--enable-opencl`.
- **Wiring**: `SearchSpaceEstimate` lifts `eta_seconds` to `App.js` via
  `onEtaChange`, which feeds `EnergyCostCalculator`.
- Verified by testing agent: 14/14 backend + 6/7 frontend tests (the 1 minor
  failure was a backend bug, see below).

### Bug fixes applied after iteration_5
- **MIN**: `/api/jobs/estimate` returned `2e-05s` (search_space=1/50000) when
  the seed was fully known. Now short-circuits to `eta_seconds=0` →
  energy panel correctly shows the empty state.
- **MIN**: `cost_estimate` used `payload.get(k) or default` idiom which
  silently replaced user-supplied `0` (e.g. `system_watts=0`,
  `provisioning_overhead_min=0`). Replaced with explicit `is None` check.

## Implemented v1.3 (2026-05-25 — BTC address preflight)
- **POST `/api/address/verify`** — local format check + on-chain stats from
  mempool.space (with Blockstream Esplora fallback). Returns one of four
  recommendations: `ok` (valid + has history), `unused` (valid format but no
  on-chain activity), `invalid` (format check failed), `unknown` (explorers
  unreachable).
- **`/app/backend/btc_address.py`** — zero-dependency mainnet validator
  supporting P2PKH, P2SH, P2WPKH/P2WSH (Bech32) and P2TR (Bech32m); rejects
  testnet/signet/regtest addresses.
- **Frontend**: `check` button next to the address input in SeedConfigPanel
  with color-coded verdict badge (green ON-CHAIN / amber UNUSED / red INVALID
  / slate EXPLORER OFFLINE), tx count, balance in BTC and explorer source.
- Verified: 14/14 pytest + 5/5 Playwright; Genesis address correctly shows
  62,952 tx and 57.2 BTC balance.

## Implemented v1.2 (2026-05-25 — signed JSON audit export)
- **GET `/api/jobs/{id}/export`** returns a canonical audit-trail JSON
  (`schema=seed-recovery-audit/v1`) containing job metadata, tool info, full
  command, redacted config snapshot, stats, result (found seed redacted by
  default), logs (count + SHA-256 hash, optional embedded lines).
- **HMAC-SHA256 signature** over canonical (sorted, separator-less) JSON,
  using a persistent key in `/app/backend/data/.sign_key`.
- **POST `/api/exports/verify`** re-signs and compares — detects any
  tampering of the payload or logs.
- **Query options**: `include_logs=true` to embed all log lines,
  `redact_seed=false` to include a recovered seed in clear.
- **Security**: passphrase always redacted in `config_snapshot`.
- **Frontend**: `export` button in JobMonitor (with reveal/redact toggle when
  a seed has been recovered) + per-row download icon in JobHistory. File
  saved as `seed-recovery-{job8}-{iso-timestamp}.json`.
- Verified: 16/16 pytest cases pass; clean payload `valid=true`, tampered
  payload `valid=false`.

## Implemented v1.1 (2026-05-25 — improvements)
- **Pre-flight Estimate panel** — computes search space (wordlist^unknowns × perms × typos^words), ETA at given rate, and feasibility badge (FAST/MODERATE/SLOW/VERY_SLOW/IMPRACTICAL). Auto-recalcs on config change.
- **Wordlist presets** — 16 BIP39/Electrum dictionaries (`bip39-en/es/fr/it/ja/...`, `electrum1-en`, etc.) selectable from a dropdown; one-click load into `candlist.txt`.
- **Incremental log persistence** — every log line written to `/app/backend/data/{job_id}/output.ndjson` (line-delimited JSON). `get_logs` reads from disk when the job is no longer in memory.
- **Orphan-job cleanup** — at backend startup, jobs persisted as `running`/`pending` with no in-memory runtime are marked `failed` with `error="Backend restarted while job was running (orphaned)"`.
- **WebSocket live log streaming** — `ws://…/api/jobs/{id}/stream` sends a `snapshot` (current state + logs), then `log` events line-by-line, then an `end` event with final status. Frontend uses it via `useJobStream` hook; HTTP polling kept as fallback for archived jobs. Header shows a "WS · LIVE" badge when connected.

## Bug fixes between iterations
- HIGH (iter 1): status was prematurely flipped to `not_found` because seedrecover prints "Seed not found" at the end of each of its 4 phases. Now status is finalized only after `proc.wait()` returns.
- Cached `seedrecover --version` at startup (no per-poll subprocess invocation).
- Guarded `generate_permutation_masks` against factorial explosion (>9 words).

## Verified flows (test reports)
- `/app/test_reports/iteration_1.json` — 14/14 backend tests, full E2E frontend OK
- `/app/test_reports/iteration_2.json` — 9/9 new tests + 12/14 regression (2 timeout-only, fixed); no critical issues

## Deployment (per user request)
- App is preview-running at `https://a1957061-8377-4647-b8b6-08939cffaadc.preview.emergentagent.com`
- For PUBLIC IP/domain access, use Emergent native deploy:
  1. Click "Deploy" in the chat sidebar → "Deploy Now"
  2. Wait 10-15 minutes → receive public URL
  3. (Optional) Link a custom domain
- Cost: 50 crediti/month; can be turned off any time
- Emergent provides a **public domain** (not a static IP); for true offline recovery, run the same stack on an air-gapped machine (recommended by `README_recover.md`).

## Backlog
- P1: Auto-refresh of wordlist count in Pre-flight Estimate when wordlist changes via preset
- P2: Cache `/api/wordlists/presets` results in memory at startup
- P2: Return numeric search_space alongside string format
- P2: Log dropped events when WebSocket queue is full
- P2: Wrap `load_logs_from_disk` in `asyncio.to_thread` for huge NDJSON files
- P2: Migrate `@app.on_event` to FastAPI lifespan API
- P3: SLIP39 / Substrate wallet support
- P3: Multi-job parallel orchestration with global resource pool

## Known limitations
- Pod is online; the README recommends air-gapped recovery. Disclaimer shown in footer.
- Recovery time is bounded by `seedrecover.py`; dashboard orchestrates, it does not accelerate.
- WebSocket queue caps at 1000 events; under extreme chatter some lines may drop (logged eventually).
