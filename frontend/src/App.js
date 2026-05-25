import React, { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import SystemStatus from "./components/SystemStatus";
import SeedConfigPanel from "./components/SeedConfigPanel";
import MaskPreview from "./components/MaskPreview";
import WordlistManager from "./components/WordlistManager";
import SearchSpaceEstimate from "./components/SearchSpaceEstimate";
import JobMonitor from "./components/JobMonitor";
import JobHistory from "./components/JobHistory";
import TerminalPanel from "./components/TerminalPanel";
import FoundSeedModal from "./components/FoundSeedModal";
import useJobStream from "./hooks/useJobStream";
import { Play, ShieldCheck, Zap } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

export default function App() {
  const [systemStatus, setSystemStatus] = useState(null);
  const [config, setConfig] = useState({
    seed_length: 12,
    known_words: Array(12).fill(""),
    wallet_type: "electrum2",
    language: "en",
    threads: 2,
    typos: 0,
    addr_limit: 10,
  });
  const [savingConfig, setSavingConfig] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState(null);
  const [archivedJob, setArchivedJob] = useState(null);
  const [archivedLogs, setArchivedLogs] = useState([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [stopping, setStopping] = useState(false);
  const [starting, setStarting] = useState(false);
  const [foundSeedModal, setFoundSeedModal] = useState(null);
  const [error, setError] = useState(null);

  const stream = useJobStream(selectedJobId, BACKEND_URL);

  // Decide if selected job is live (in-memory & has WS data) or archived
  const liveJob = stream.status
    ? {
        job_id: selectedJobId,
        status: stream.status,
        stats: stream.stats,
        found_seed: stream.foundSeed,
      }
    : null;
  const activeJob = liveJob || archivedJob;
  const logs = liveJob ? stream.logs : archivedLogs;

  // Show seed modal when found
  useEffect(() => {
    if (stream.foundSeed) setFoundSeedModal(stream.foundSeed);
  }, [stream.foundSeed]);

  // Initial load
  useEffect(() => {
    (async () => {
      try {
        const [cfg, st, j] = await Promise.all([
          api.get("/config"),
          api.get("/system/status"),
          api.get("/jobs"),
        ]);
        setConfig({ ...cfg.data });
        setSystemStatus(st.data);
        setJobs(j.data);
        if (j.data?.length > 0 && !selectedJobId) {
          setSelectedJobId(j.data[0].job_id);
        }
      } catch (e) {
        setError("Failed to load initial state: " + e.message);
      }
    })();
    const statusInt = setInterval(async () => {
      try {
        const st = await api.get("/system/status");
        setSystemStatus(st.data);
      } catch (e) {
        console.debug("[App] status poll failed", e?.message);
      }
    }, 5000);
    return () => clearInterval(statusInt);
    // eslint-disable-next-line
  }, []);

  // Fetch archived job snapshot (when WS can't connect)
  useEffect(() => {
    if (!selectedJobId) {
      setArchivedJob(null); setArchivedLogs([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [jr, lr] = await Promise.all([
          api.get(`/jobs/${selectedJobId}`),
          api.get(`/jobs/${selectedJobId}/logs`, { params: { since: 0 } }),
        ]);
        if (cancelled) return;
        setArchivedJob(jr.data);
        setArchivedLogs(lr.data?.lines || []);
        if (lr.data?.found_seed) setFoundSeedModal(lr.data.found_seed);
      } catch (e) {
        console.debug("[App] archived job fetch failed", e?.message);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedJobId]);

  // Refresh job list periodically
  useEffect(() => {
    const i = setInterval(async () => {
      try {
        const j = await api.get("/jobs");
        setJobs(j.data);
      } catch (e) {
        console.debug("[App] jobs poll failed", e?.message);
      }
    }, 3000);
    return () => clearInterval(i);
  }, []);

  const saveConfig = useCallback(async () => {
    setSavingConfig(true);
    try {
      const r = await api.put("/config", config);
      setConfig({ ...r.data });
    } catch (e) {
      setError("Save failed: " + e.message);
    } finally { setSavingConfig(false); }
  }, [config]);

  const startJob = async () => {
    setStarting(true);
    setError(null);
    try {
      await api.put("/config", config);
      const r = await api.post("/jobs", { label: `${config.wallet_type}-${config.seed_length}w` });
      setSelectedJobId(r.data.job_id);
      const j = await api.get("/jobs");
      setJobs(j.data);
    } catch (e) {
      setError("Start failed: " + (e.response?.data?.detail || e.message));
    } finally { setStarting(false); }
  };

  const stopJob = async () => {
    if (!selectedJobId) return;
    setStopping(true);
    try {
      await api.post(`/jobs/${selectedJobId}/stop`);
    } catch (e) {
      setError("Stop failed: " + (e.response?.data?.detail || e.message));
    } finally { setStopping(false); }
  };

  const deleteJob = async (jid) => {
    try {
      await api.delete(`/jobs/${jid}`);
      const j = await api.get("/jobs");
      setJobs(j.data);
      if (selectedJobId === jid) setSelectedJobId(j.data?.[0]?.job_id || null);
    } catch (e) {
      setError("Delete failed: " + (e.response?.data?.detail || e.message));
    }
  };

  const canStart = systemStatus?.btcrecover?.available && !starting;

  return (
    <div className="min-h-screen text-slate-200 font-sans" data-testid="app-root">
      <header className="border-b border-slate-800 bg-[#0D0E12]/80 backdrop-blur-xl sticky top-0 z-30">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600/20 border border-blue-500/40 rounded-sm flex items-center justify-center">
              <ShieldCheck className="h-4 w-4 text-blue-400" />
            </div>
            <div>
              <div className="font-mono text-sm tracking-widest text-slate-200">SEED-RECOVERY</div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500">control room v1.1</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span
              className="w-2 h-2 rounded-full shadow-[0_0_8px_currentColor] led-blink"
              style={{ color: systemStatus?.btcrecover?.available ? "#22C55E" : "#EF4444", background: systemStatus?.btcrecover?.available ? "#22C55E" : "#EF4444" }}
            />
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400" data-testid="header-status">
              {systemStatus?.btcrecover?.available ? "system ready" : "system offline"}
            </span>
            {stream.connected && (
              <span className="text-[10px] font-mono uppercase tracking-widest text-blue-300 border border-blue-500/30 rounded-sm px-1.5 py-0.5" data-testid="ws-indicator">
                ws · live
              </span>
            )}
            <button
              onClick={startJob}
              disabled={!canStart}
              className="btn-primary"
              data-testid="start-job-btn"
            >
              <Play className="h-4 w-4" /> {starting ? "Launching…" : "Start Recovery"}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] mx-auto px-6 py-6 flex flex-col gap-6">
        <SystemStatus status={systemStatus} />

        {error && (
          <div className="bg-red-950/40 border border-red-900/50 text-red-300 text-xs font-mono px-4 py-2 rounded-sm" data-testid="error-banner">
            {error}
            <button onClick={() => setError(null)} className="float-right text-red-400 hover:text-red-200">✕</button>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-5 flex flex-col gap-6" data-testid="config-column">
            <SeedConfigPanel
              config={config}
              setConfig={setConfig}
              onSave={saveConfig}
              saving={savingConfig}
            />
            <SearchSpaceEstimate config={config} />
            <MaskPreview config={config} />
            <WordlistManager />
          </div>

          <div className="lg:col-span-7 flex flex-col gap-6" data-testid="monitor-column">
            <JobMonitor job={activeJob} onStop={stopJob} stopping={stopping} />
            <TerminalPanel
              lines={logs}
              autoScroll={autoScroll}
              onToggleAutoScroll={setAutoScroll}
              onClear={() => { setArchivedLogs([]); }}
              title={selectedJobId ? `JOB ${selectedJobId.slice(0, 8)} · ${stream.connected ? "WS LIVE" : "ARCHIVED"}` : "LIVE OUTPUT"}
            />
            <JobHistory
              jobs={jobs}
              selectedId={selectedJobId}
              onSelect={setSelectedJobId}
              onDelete={deleteJob}
            />
          </div>
        </div>

        <footer className="pt-4 pb-8 text-center text-[10px] font-mono uppercase tracking-widest text-slate-600 flex items-center justify-center gap-3">
          <Zap className="h-3 w-3" />
          Offline-recommended · Run sensitive recovery on an air-gapped machine.
        </footer>
      </main>

      <FoundSeedModal seed={foundSeedModal} onClose={() => setFoundSeedModal(null)} />
    </div>
  );
}
