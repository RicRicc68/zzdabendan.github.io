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
