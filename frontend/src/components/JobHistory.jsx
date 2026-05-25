import React from "react";
import { fmtDuration, STATUS_COLOR } from "../lib/api";
import { History, Trash2 } from "lucide-react";

export default function JobHistory({ jobs, onSelect, selectedId, onDelete }) {
  return (
    <div className="card p-5 flex flex-col gap-3" data-testid="job-history">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center gap-2">
          <History className="h-4 w-4 text-slate-400" />
          Job History
        </h3>
        <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
          {jobs.length} entries
        </span>
      </div>
      <div className="flex flex-col gap-1 max-h-[280px] overflow-y-auto pr-1">
        {jobs.length === 0 && (
          <div className="text-xs text-slate-600 italic font-mono py-4 text-center">// no jobs yet</div>
        )}
        {jobs.map((j) => {
          const color = STATUS_COLOR[j.status] || "#94A3B8";
          const isSel = j.job_id === selectedId;
          const dur = j.started_at && j.finished_at
            ? (new Date(j.finished_at) - new Date(j.started_at)) / 1000
            : null;
          return (
            <div
              key={j.job_id}
              className={`flex items-center gap-3 px-2 py-1.5 border border-transparent hover:border-slate-700 hover:bg-slate-900/60 rounded-sm cursor-pointer transition-colors ${isSel ? "bg-slate-900/80 border-blue-900" : ""}`}
              onClick={() => onSelect(j.job_id)}
              data-testid={`job-row-${j.job_id}`}
            >
              <span
                className="w-2 h-2 rounded-full shadow-[0_0_6px_currentColor]"
                style={{ color, background: color }}
              />
              <span className="text-xs font-mono text-slate-400 flex-1 truncate">
                {j.job_id.slice(0, 8)}… <span className="text-slate-600">·</span> <span className="text-slate-500">{j.label || j.config_snapshot?.wallet_type || "job"}</span>
              </span>
              <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color }}>
                {j.status}
              </span>
              <span className="text-[10px] font-mono text-slate-500 w-16 text-right">
                {dur != null ? fmtDuration(dur) : "—"}
              </span>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(j.job_id); }}
                className="text-slate-600 hover:text-red-400 transition-colors"
                title="Delete"
                data-testid={`delete-job-${j.job_id}`}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
