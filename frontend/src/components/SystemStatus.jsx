import React from "react";
import { Activity, Cpu, HardDrive, Shield, ShieldAlert } from "lucide-react";

export default function SystemStatus({ status }) {
  if (!status) return null;
  const ok = status.btcrecover?.available;
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="system-status">
      <StatCard
        label="btcrecover"
        value={ok ? "READY" : "MISSING"}
        sub={status.btcrecover?.version || status.btcrecover?.path}
        color={ok ? "#22C55E" : "#EF4444"}
        icon={ok ? <Shield className="h-4 w-4" /> : <ShieldAlert className="h-4 w-4" />}
        testid="stat-btcrecover"
      />
      <StatCard
        label="active jobs"
        value={String(status.active_jobs ?? 0)}
        sub="running now"
        color={status.active_jobs ? "#3B82F6" : "#94A3B8"}
        icon={<Activity className="h-4 w-4" />}
        testid="stat-active-jobs"
      />
      <StatCard
        label="cpu"
        value={`${status.cpu_percent?.toFixed?.(0) ?? 0}%`}
        sub={`${status.cpu_count || "?"} cores`}
        color="#94A3B8"
        icon={<Cpu className="h-4 w-4" />}
        testid="stat-cpu"
      />
      <StatCard
        label="memory"
        value={`${status.memory_percent?.toFixed?.(0) ?? 0}%`}
        sub={`${status.memory_total_gb || "?"} GB total`}
        color="#94A3B8"
        icon={<HardDrive className="h-4 w-4" />}
        testid="stat-mem"
      />
      <StatCard
        label="disk"
        value={`${status.disk_percent?.toFixed?.(0) ?? 0}%`}
        sub={`${status.disk_total_gb || "?"} GB`}
        color="#94A3B8"
        icon={<HardDrive className="h-4 w-4" />}
        testid="stat-disk"
      />
    </div>
  );
}

function StatCard({ label, value, sub, color, icon, testid }) {
  return (
    <div className="card p-4 flex flex-col gap-2" data-testid={testid}>
      <div className="flex items-center justify-between text-[10px] uppercase tracking-widest text-slate-500 font-mono">
        <span className="flex items-center gap-1">{icon} {label}</span>
        <span className="w-2 h-2 rounded-full shadow-[0_0_8px_currentColor]" style={{ color, background: color }} />
      </div>
      <div className="text-2xl font-mono tracking-tight text-slate-100">{value}</div>
      <div className="text-[10px] text-slate-500 font-mono truncate">{sub}</div>
    </div>
  );
}
