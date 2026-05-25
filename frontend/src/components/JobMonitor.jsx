import React from "react";
import { fmtDuration, STATUS_COLOR } from "../lib/api";
import { Activity, Square, Loader2 } from "lucide-react";

export default function JobMonitor({ job, onStop, stopping }) {
  if (!job) {
    return (
      <div className="card p-5 flex flex-col gap-2 min-h-[180px] justify-center items-center text-center" data-testid="job-monitor-empty">
        <div className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">No active job</div>
        <div className="text-sm text-slate-400">Start a recovery from the right panel to see live progress.</div>
      </div>
    );
  }
  const s = job.stats || {};
  const color = STATUS_COLOR[job.status] || "#94A3B8";
  const isRunning = job.status === "running";

  return (
    <div className="card p-5 flex flex-col gap-4" data-testid="job-monitor">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full shadow-[0_0_8px_currentColor] ${isRunning ? "led-blink" : ""}`}
              style={{ color, background: color }}
            />
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-400">{job.status}</span>
          </div>
          <div className="text-sm text-slate-300 font-mono" data-testid="job-id">
            {job.job_id?.slice(0, 8)}…
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onStop}
            disabled={!isRunning || stopping}
            className="btn-danger"
            data-testid="stop-job-btn"
          >
            {stopping ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
            Stop
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="progress" value={`${(s.progress_pct ?? 0).toFixed(2)}%`} testid="metric-progress" />
        <Metric
          label="candidates"
          value={s.candidates_tested?.toLocaleString?.() ?? "0"}
          sub={s.total_candidates ? `of ${s.total_candidates.toLocaleString()}` : null}
          testid="metric-tested"
        />
        <Metric
          label="rate"
          value={`${(s.candidates_per_sec ?? 0).toFixed(0)}`}
          sub="candidates/sec"
          testid="metric-rate"
        />
        <Metric label="ETA" value={fmtDuration(s.eta_seconds)} testid="metric-eta" />
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-widest text-slate-500 font-mono mb-1">progress</div>
        <div className="h-2 bg-slate-800 rounded-sm overflow-hidden" data-testid="progress-bar">
          <div
            className="h-full transition-all"
            style={{
              width: `${Math.min(100, s.progress_pct ?? 0)}%`,
              background: `linear-gradient(90deg, ${color}, ${color}cc)`,
              boxShadow: `0 0 12px ${color}55`,
            }}
          />
        </div>
      </div>

      {s.current_candidate && (
        <div className="text-xs font-mono text-slate-300">
          <span className="text-slate-500">testing → </span>
          <span className="text-green-300" data-testid="current-candidate">{s.current_candidate}</span>
        </div>
      )}
      {job.error && (
        <div className="text-xs font-mono text-red-300 bg-red-950/30 border border-red-900/40 rounded-sm p-2" data-testid="job-error">
          {job.error}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, sub, testid }) {
  return (
    <div className="flex flex-col gap-0.5" data-testid={testid}>
      <span className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">{label}</span>
      <span className="text-2xl font-mono tracking-tight text-slate-100">{value}</span>
      {sub && <span className="text-[10px] text-slate-500 font-mono">{sub}</span>}
    </div>
  );
}
