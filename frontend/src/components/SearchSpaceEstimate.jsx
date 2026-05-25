import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Gauge, RefreshCw } from "lucide-react";

const FEAS_COLOR = {
  fast: "#22C55E",
  moderate: "#3B82F6",
  slow: "#F59E0B",
  very_slow: "#F97316",
  impractical: "#EF4444",
};
const FEAS_LABEL = {
  fast: "FAST",
  moderate: "MODERATE",
  slow: "SLOW",
  very_slow: "VERY SLOW",
  impractical: "IMPRACTICAL",
};

export default function SearchSpaceEstimate({ config }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [wordlistSize, setWordlistSize] = useState(2048);
  const [rate, setRate] = useState(50000);

  useEffect(() => {
    // Load wordlist size on mount
    api.get("/wordlist").then((r) => {
      if (r.data?.count > 0) setWordlistSize(r.data.count);
    }).catch(() => {});
  }, []);

  const run = async () => {
    setLoading(true);
    try {
      const r = await api.post("/jobs/estimate", {
        seed_length: config.seed_length,
        known_words: config.known_words,
        typos: config.typos || 0,
        threads: config.threads || 2,
        wordlist_size: wordlistSize,
        rate_per_thread: rate,
      });
      setData(r.data);
    } finally { setLoading(false); }
  };

  // Auto-run when config changes meaningfully
  useEffect(() => { run(); /* eslint-disable-next-line */ }, [config.seed_length, JSON.stringify(config.known_words), config.typos, config.threads, wordlistSize, rate]);

  const color = data ? (FEAS_COLOR[data.feasibility] || "#94A3B8") : "#94A3B8";

  return (
    <div className="card p-5 flex flex-col gap-3" data-testid="search-space-estimate">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center gap-2">
          <Gauge className="h-4 w-4 text-blue-400" />
          Pre-flight Estimate
        </h3>
        <button onClick={run} disabled={loading} className="btn-ghost" data-testid="estimate-recalc-btn">
          <RefreshCw className={`h-3 w-3 mr-1 inline ${loading ? "animate-spin" : ""}`} /> recalc
        </button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">wordlist size</span>
          <input
            type="number" min={10} max={500000}
            value={wordlistSize}
            onChange={(e) => setWordlistSize(parseInt(e.target.value || "1"))}
            className="input-base w-full px-2 py-1.5"
            data-testid="estimate-wordlist-size"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">rate/thread (c/s)</span>
          <input
            type="number" min={1000} max={10000000}
            value={rate}
            onChange={(e) => setRate(parseInt(e.target.value || "1"))}
            className="input-base w-full px-2 py-1.5"
            data-testid="estimate-rate"
          />
        </label>
      </div>

      {data && (
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="unknown ?" value={data.unknown_positions} testid="est-unknown" />
            <Stat label="search space" value={data.search_space_approx} testid="est-space" />
            <Stat label="ETA" value={data.eta_human} color={color} testid="est-eta" />
          </div>
          <div
            className="flex items-center justify-between border rounded-sm px-3 py-2 mt-1"
            style={{ borderColor: color + "55", background: color + "10" }}
            data-testid="est-feasibility"
          >
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full shadow-[0_0_8px_currentColor]" style={{ color, background: color }} />
              <span className="text-xs font-mono uppercase tracking-widest" style={{ color }}>
                {FEAS_LABEL[data.feasibility] || data.feasibility}
              </span>
            </div>
            <span className="text-[10px] font-mono text-slate-500">
              {data.effective_rate?.toLocaleString()} c/s · {data.threads} thread(s)
            </span>
          </div>
          {data.feasibility === "impractical" && (
            <div className="text-[10px] font-mono text-red-300 leading-relaxed">
              ⚠ Search space too large with current configuration. Reduce unknown positions, lower typo tolerance, or shrink the wordlist before launching.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color, testid }) {
  return (
    <div className="flex flex-col gap-0.5" data-testid={testid}>
      <span className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">{label}</span>
      <span className="text-xl font-mono tracking-tight" style={{ color: color || "#E2E8F0" }}>{value}</span>
    </div>
  );
}
