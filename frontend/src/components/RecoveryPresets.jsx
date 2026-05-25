import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { devError } from "../lib/logger";
import { Sparkles, Shield, Key, Wallet, AlertTriangle, Puzzle, Settings, ChevronRight } from "lucide-react";

const ICON_MAP = {
  shield: Shield,
  key: Key,
  wallet: Wallet,
  "alert-triangle": AlertTriangle,
  puzzle: Puzzle,
  settings: Settings,
};

const DIFFICULTY_STYLE = {
  fast:       { c: "#22C55E", label: "FAST" },
  moderate:   { c: "#3B82F6", label: "MODERATE" },
  slow:       { c: "#F59E0B", label: "SLOW" },
  very_slow:  { c: "#F97316", label: "VERY SLOW" },
  impractical:{ c: "#EF4444", label: "IMPRACTICAL" },
};

export default function RecoveryPresets({ onApplied }) {
  const [presets, setPresets] = useState([]);
  const [applyingId, setApplyingId] = useState(null);
  const [appliedId, setAppliedId] = useState(null);
  const [appliedHint, setAppliedHint] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.get("/presets")
      .then((r) => setPresets(r.data.presets || []))
      .catch((e) => devError("[RecoveryPresets] list failed", e));
  }, []);

  const apply = async (id) => {
    setApplyingId(id);
    setError(null);
    try {
      const r = await api.post(`/presets/${id}/apply`);
      setAppliedId(id);
      setAppliedHint(r.data.hint);
      if (onApplied) onApplied(r.data.config);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setApplyingId(null); }
  };

  return (
    <div className="card p-5 flex flex-col gap-3" data-testid="recovery-presets">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-purple-300" />
          Quick Start · Recovery Presets
        </h3>
        <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
          {presets.length} scenarios
        </span>
      </div>

      <p className="text-xs text-slate-400 leading-relaxed">
        Pick a scenario that matches your situation — it will pre-fill the seed
        configuration and load the right wordlist. You can still tweak anything
        after applying.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="presets-grid">
        {presets.map((p) => {
          const Icon = ICON_MAP[p.icon] || Sparkles;
          const diff = DIFFICULTY_STYLE[p.difficulty] || DIFFICULTY_STYLE.moderate;
          const isApplied = appliedId === p.id;
          const isApplying = applyingId === p.id;
          return (
            <button
              key={p.id}
              onClick={() => apply(p.id)}
              disabled={isApplying}
              className={`text-left bg-[#0D0E12] border rounded-sm p-3 flex flex-col gap-2 transition-all hover:border-purple-500/40 hover:bg-purple-500/5 ${isApplied ? "border-purple-500/60 bg-purple-500/10" : "border-slate-800"}`}
              data-testid={`preset-card-${p.id}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <Icon className="h-4 w-4 text-purple-300 shrink-0" />
                  <span className="text-sm font-medium text-slate-100 truncate">{p.name}</span>
                </div>
                <span
                  className="text-[9px] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded-sm shrink-0"
                  style={{ color: diff.c, background: diff.c + "15", border: `1px solid ${diff.c}40` }}
                >
                  {diff.label}
                </span>
              </div>
              <div className="text-[11px] text-slate-400 leading-snug">{p.tagline}</div>
              <div className="flex items-center justify-between text-[10px] font-mono text-slate-500">
                <span>
                  {p.seed_length}w · {p.wallet_type} · typos={p.typos}
                  {p.wordlist_preset && <span className="text-slate-600"> · {p.wordlist_preset}</span>}
                </span>
                <ChevronRight className="h-3 w-3" />
              </div>
              {isApplied && (
                <div className="text-[10px] font-mono text-purple-300 uppercase tracking-widest" data-testid={`preset-applied-${p.id}`}>
                  ✓ applied
                </div>
              )}
            </button>
          );
        })}
      </div>

      {appliedHint && (
        <div className="border border-purple-500/30 bg-purple-500/5 rounded-sm px-3 py-2 text-xs text-slate-300 font-mono leading-relaxed" data-testid="preset-hint">
          <span className="text-purple-300 uppercase tracking-widest text-[10px] mr-2">hint:</span>
          {appliedHint}
        </div>
      )}

      {error && (
        <div className="text-xs font-mono text-red-300 bg-red-950/30 border border-red-900/40 rounded-sm p-2" data-testid="preset-error">
          {error}
        </div>
      )}
    </div>
  );
}
