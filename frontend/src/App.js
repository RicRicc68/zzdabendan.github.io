import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./lib/api";
import SystemStatus from "./components/SystemStatus";
import SeedConfigPanel from "./components/SeedConfigPanel";
import MaskPreview from "./components/MaskPreview";
import WordlistManager from "./components/WordlistManager";
import JobMonitor from "./components/JobMonitor";
import JobHistory from "./components/JobHistory";
import TerminalPanel from "./components/TerminalPanel";
import FoundSeedModal from "./components/FoundSeedModal";
import { Play, ShieldCheck, Zap } from "lucide-react";

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
  const [activeJob, setActiveJob] = useState(null);
  const [logs, setLogs] = useState([]);
  const [logCursor, setLogCursor] = useState(0);
  const [autoScroll, setAutoScroll] = useState(true);
  const [stopping, setStopping] = useState(false);
  const [starting, setStarting] = useState(false);
  const [foundSeedModal, setFoundSeedModal] = useState(null);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  // Load initial config + system status + jobs
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
        // Auto-select most recent
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
      } catch (_) {}
    }, 5000);
    return () => clearInterval(statusInt);
    // eslint-disable-next-line
  }, []);

  // Poll selected job
  useEffect(() => {
    if (!selectedJobId) {
      setActiveJob(null); setLogs([]); setLogCursor(0);
      return;
    }
    setLogs([]); setLogCursor(0);
    let stopped = false;
    let cursor = 0;
    const tick = async () => {
      try {
        const [jr, lr] = await Promise.all([
          api.get(`/jobs/${selectedJobId}`),
          api.get(`/jobs/${selectedJobId}/logs`, { params: { since: cursor } }),
        ]);
        if (stopped) return;
        setActiveJob(jr.data);
        if (lr.data?.lines?.length) {
          setLogs((cur) => cur.concat(lr.data.lines));
          cursor = lr.data.next;
          setLogCursor(cursor);
        }
        if (lr.data?.found_seed && jr.data.status === "found") {
          setFoundSeedModal(lr.data.found_seed);
        }
        const stillRunning = jr.data.status === "running" || jr.data.status === "pending";
        const interval = stillRunning ? 1000 : 4000;
        pollRef.current = setTimeout(tick, interval);
      } catch (e) {
        if (!stopped) pollRef.current = setTimeout(tick, 3000);
      }
    };
    tick();
    return () => {
      stopped = true;
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [selectedJobId]);

  // Refresh job list periodically
  useEffect(() => {
    const i = setInterval(async () => {
      try {
        const j = await api.get("/jobs");
        setJobs(j.data);
      } catch (_) {}
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
      {/* Header */}
      <header className="border-b border-slate-800 bg-[#0D0E12]/80 backdrop-blur-xl sticky top-0 z-30">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600/20 border border-blue-500/40 rounded-sm flex items-center justify-center">
              <ShieldCheck className="h-4 w-4 text-blue-400" />
            </div>
            <div>
              <div className="font-mono text-sm tracking-widest text-slate-200">SEED-RECOVERY</div>
              <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500">control room v1.0</div>
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
        {/* Top stats */}
        <SystemStatus status={systemStatus} />

        {error && (
          <div className="bg-red-950/40 border border-red-900/50 text-red-300 text-xs font-mono px-4 py-2 rounded-sm" data-testid="error-banner">
            {error}
            <button onClick={() => setError(null)} className="float-right text-red-400 hover:text-red-200">✕</button>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left column — configuration */}
          <div className="lg:col-span-5 flex flex-col gap-6" data-testid="config-column">
            <SeedConfigPanel
              config={config}
              setConfig={setConfig}
              onSave={saveConfig}
              saving={savingConfig}
            />
            <MaskPreview config={config} />
            <WordlistManager />
          </div>

          {/* Right column — monitor */}
          <div className="lg:col-span-7 flex flex-col gap-6" data-testid="monitor-column">
            <JobMonitor job={activeJob} onStop={stopJob} stopping={stopping} />
            <TerminalPanel
              lines={logs}
              autoScroll={autoScroll}
              onToggleAutoScroll={setAutoScroll}
              onClear={() => setLogs([])}
              title={selectedJobId ? `JOB ${selectedJobId.slice(0,8)} · LIVE OUTPUT` : "LIVE OUTPUT"}
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
