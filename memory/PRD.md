# SEED-RECOVERY — Control Room Dashboard

## Original Problem
> "costruiscimi una dashboard per il bot da implementare nel file allegato"

The attached `README_recover.md` describes an OFFLINE recovery helper for an
Electrum 12-word seed (via `btcrecover` / `seedrecover.py` + `gen_masks.py`).
User confirmed it's HIS own BTC wallet of which he has lost the private key
and seed phrase. User chose:
- all features
- REAL subprocess execution of `btcrecover`
- no authentication

## Architecture
- **Backend**: FastAPI (`/app/backend/server.py`) + MongoDB
  - Manages `seedrecover.py` as `asyncio.create_subprocess_exec`
  - Streams stdout/stderr line-by-line, parses progress
  - Persists configuration and job history in MongoDB
- **Frontend**: React 18 + Tailwind (Control Room dark theme)
  - Cards for system vitals, seed config, mask preview, wordlist
  - Live terminal panel (JetBrains Mono), live job monitor, job history
  - Found-seed reveal modal
- **External tool**: `/opt/btcrecover` (3rdIteration/btcrecover, cloned at setup)

## Implemented (2026-05-25)
- Seed configuration: seed length 12/15/18/21/24, wallet type
  (electrum2/bip39/bip32/ethereum), language, threads, typos, address/mpk/wallet-file
  verification target, optional seed-extension passphrase
- Mask generation: fixed position mask, permutation masks for unpositioned
  known words (capped at 9 unpositioned to avoid factorial explosion)
- Candidate wordlist (`candlist.txt`) editor and persistence
- Job lifecycle: create / poll status / stream logs (cursor-based polling) /
  stop / delete
- Real-time progress parsing: candidates tested, total, rate, ETA, %
- Found-seed detection with secure reveal modal (copy + clear)
- System vitals (CPU/MEM/DISK/active jobs/btcrecover availability)
- Robust subprocess management:
  - status finalization deferred until `proc.wait()` returns
  - `sys.executable` used so the venv with `pycryptodome` is reused
  - process killed via `os.killpg(SIGTERM)` for stop, supports child cleanup
- Seedrecover version cached at startup (no per-poll subprocess invocation)
- Dark "Control Room" UI with terminal panel, status LEDs, dense grid layout

## Verified flows (test report `/app/test_reports/iteration_1.json`)
- 14 backend pytest tests pass
- E2E frontend: configure → save → start → live terminal → status NOT_FOUND
- Mask preview produces `alpha ? ? ? ? ? ? ? ? ? ? ?`

## Bug fixes applied after iteration_1
- HIGH: status now stays `running` until subprocess truly exits (was flipping
  to `not_found` after each seedrecover phase). Stop + delete now consistent.
- Cached `seedrecover --version` at startup
- Guarded `generate_permutation_masks` against combinatorial explosion (>9 words)

## Backlog / Next
- P1: Persist log lines incrementally to MongoDB (currently only last 200
  lines saved after process exits)
- P1: Restart-resilience — if backend restarts mid-job, mark orphan jobs as
  `failed` on startup
- P2: WebSocket for log streaming (instead of polling)
- P2: Validate candidate wordlist against BIP39/Electrum dictionaries
- P2: Resource-aware throttling (auto threads = min(cores, 4))
- P2: Export job result as JSON (audit trail)
- P2: Optional dark/light theme toggle (currently dark-only by design)

## Known limitations
- The pod is online; the README explicitly recommends air-gapped recovery.
  The dashboard prominently shows this disclaimer in the footer.
- Recovery time is bounded by `seedrecover.py` — the dashboard does NOT
  accelerate the search, it only orchestrates and monitors it.
