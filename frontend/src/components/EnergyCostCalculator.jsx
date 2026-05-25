import React, { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { Zap, Cpu, Cloud, Check } from "lucide-react";

const CLASS_COLOR = {
  trivial: "#22C55E",
  low: "#22C55E",
  moderate: "#3B82F6",
  high: "#F59E0B",
  extreme: "#EF4444",
};

export default function EnergyCostCalculator({ etaSeconds }) {
  const [systemWatts, setSystemWatts] = useState(150);
  const [eurPerKwh, setEurPerKwh] = useState(0.30);
  const [usdToEur, setUsdToEur] = useState(0.92);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const eta = useMemo(() => (etaSeconds && isFinite(etaSeconds) ? etaSeconds : 0), [etaSeconds]);

  const run = async () => {
    setLoading(true);
    try {
      const r = await api.post("/jobs/cost-estimate", {
        eta_seconds: eta,
        system_watts: systemWatts,
        eur_per_kwh: eurPerKwh,
        usd_to_eur: usdToEur,
      });
      setData(r.data);
    } catch (e) {
      console.error("[EnergyCostCalculator] failed", e);
    } finally { setLoading(false); }
  };

  useEffect(() => { run(); /* eslint-disable-next-line */ }, [eta, systemWatts, eurPerKwh, usdToEur]);

  if (!eta) {
    return (
      <div className="card p-5 flex flex-col gap-2 text-center" data-testid="energy-cost-empty">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center justify-center gap-2">
          <Zap className="h-4 w-4 text-amber-400" /> Energy &amp; GPU Cost
        </h3>
        <p className="text-xs text-slate-500 font-mono">
          Compute Pre-flight Estimate first to see cost projections.
        </p>
      </div>
    );
  }

  const local = data?.local;
  const reco = data?.recommendation || "";
  const isLocal = reco === "local";
  const recoGpu = reco.startsWith("gpu:") ? reco.slice(4) : null;
  const isImpractical = reco === "do_not_run";

  let recoColor;
  if (isImpractical) recoColor = "#EF4444";
  else if (isLocal) recoColor = "#22C55E";
  else recoColor = "#3B82F6";

  let recoLabel;
  if (isLocal) recoLabel = "RUN LOCAL";
  else if (isImpractical) recoLabel = "DO NOT RUN";
  else if (recoGpu) recoLabel = `RENT GPU · ${recoGpu}`;
  else recoLabel = "—";

  return (
    <div className="card p-5 flex flex-col gap-4" data-testid="energy-cost-calculator">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center gap-2">
          <Zap className="h-4 w-4 text-amber-400" />
          Energy &amp; GPU Cost
        </h3>
        {loading && <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">computing…</span>}
      </div>

      {/* Recommendation banner */}
      {data && (
        <div
          className="border rounded-sm px-3 py-2 flex items-start gap-2"
          style={{ borderColor: recoColor + "55", background: recoColor + "10" }}
          data-testid="cost-recommendation"
        >
          <span className="w-2.5 h-2.5 rounded-full mt-1 shadow-[0_0_8px_currentColor]" style={{ color: recoColor, background: recoColor }} />
          <div className="flex-1">
            <div className="text-[10px] font-mono uppercase tracking-widest" style={{ color: recoColor }}>
              {recoLabel}
            </div>
            <div className="text-xs text-slate-300 font-mono leading-relaxed mt-1" data-testid="cost-message">
              {data.message}
            </div>
          </div>
        </div>
      )}

      {/* Inputs */}
      <div className="grid grid-cols-3 gap-3">
        <Field label="system watts">
          <input type="number" min={20} max={2000} value={systemWatts}
            onChange={(e) => setSystemWatts(parseFloat(e.target.value || "0"))}
            className="input-base w-full px-2 py-1.5" data-testid="cost-watts-input" />
        </Field>
        <Field label="€ / kWh">
          <input type="number" min={0.01} max={2} step={0.01} value={eurPerKwh}
            onChange={(e) => setEurPerKwh(parseFloat(e.target.value || "0"))}
            className="input-base w-full px-2 py-1.5" data-testid="cost-kwh-input" />
        </Field>
        <Field label="USD → EUR">
          <input type="number" min={0.5} max={1.5} step={0.01} value={usdToEur}
            onChange={(e) => setUsdToEur(parseFloat(e.target.value || "0"))}
            className="input-base w-full px-2 py-1.5" data-testid="cost-usd-eur-input" />
        </Field>
      </div>

      {/* Local row */}
      {local && (
        <div className="border border-slate-800 rounded-sm p-3 flex items-center justify-between" data-testid="cost-local-row">
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-slate-400" />
            <div>
              <div className="text-sm font-mono text-slate-200">Local CPU ({systemWatts}W)</div>
              <div className="text-[10px] font-mono text-slate-500">
                {local.energy_kwh} kWh · {local.eta_human}
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-lg font-mono tracking-tight" style={{ color: CLASS_COLOR[local.classification] }}>
              €{local.energy_cost_eur.toFixed(2)}
            </div>
            <div className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">{local.classification}</div>
          </div>
        </div>
      )}

      {/* GPU options table */}
      {data?.gpu_options && (
        <div className="flex flex-col gap-1 max-h-[260px] overflow-y-auto pr-1" data-testid="cost-gpu-options">
          <div className="grid grid-cols-12 gap-2 px-2 text-[10px] font-mono uppercase tracking-widest text-slate-500 pb-1 border-b border-slate-800">
            <div className="col-span-4 flex items-center gap-1"><Cloud className="h-3 w-3" /> GPU</div>
            <div className="col-span-2 text-right">€/h</div>
            <div className="col-span-3 text-right">ETA</div>
            <div className="col-span-3 text-right">cost · save</div>
          </div>
          {data.gpu_options.map((g) => {
            const isReco = recoGpu === g.name;
            return (
              <div
                key={g.name}
                className={`grid grid-cols-12 gap-2 px-2 py-1.5 text-xs font-mono rounded-sm transition-colors ${isReco ? "bg-blue-500/10 border border-blue-500/40" : "hover:bg-slate-900/40"}`}
                data-testid={`cost-gpu-${g.name.replace(/[^a-z0-9]/gi, '-').toLowerCase()}`}
              >
                <div className="col-span-4 flex items-center gap-1 text-slate-300 truncate">
                  {isReco && <Check className="h-3 w-3 text-blue-300 shrink-0" />}
                  <span className="truncate">{g.name}</span>
                </div>
                <div className="col-span-2 text-right text-slate-400">€{g.eur_per_hour.toFixed(2)}</div>
                <div className="col-span-3 text-right text-slate-300">{g.eta_human}</div>
                <div className="col-span-3 text-right">
                  <span style={{ color: CLASS_COLOR[g.classification] }}>€{g.rental_cost_eur.toFixed(2)}</span>
                  {g.savings_vs_local_eur > 0 && (
                    <span className="text-green-400 ml-1">−€{g.savings_vs_local_eur.toFixed(2)}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="text-[10px] font-mono text-slate-600 leading-relaxed">
        ⓘ GPU speedups are conservative estimates for seedrecover (BIP39/Electrum). Run with{" "}
        <span className="text-slate-400">--enable-opencl</span> on the rented box. Prices are typical spot rates.
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">{label}</span>
      {children}
    </label>
  );
}
