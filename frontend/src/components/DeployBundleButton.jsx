import React, { useState } from "react";
import { api } from "../lib/api";
import { Rocket, Download, Eye, X, FileCode } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;

export default function DeployBundleButton({ recommendedGpu, etaHuman, localEtaHuman, costLocalEur, costRentalEur }) {
  const [provider, setProvider] = useState("vastai");
  const [preview, setPreview] = useState(null);
  const [previewFile, setPreviewFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const body = () => ({
    provider,
    gpu_name: recommendedGpu || null,
    eta_human: etaHuman,
    local_eta_human: localEtaHuman,
    cost_local_eur: costLocalEur,
    cost_rental_eur: costRentalEur,
  });

  const doPreview = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.post("/deploy/preview", body());
      setPreview(r.data);
      setPreviewFile(Object.keys(r.data.files)[0]);
    } catch (e) {
      setError(e.response?.data?.detail || e.message);
    } finally { setBusy(false); }
  };

  const doDownload = async () => {
    setBusy(true);
    setError(null);
    try {
      const resp = await fetch(`${BACKEND_URL}/api/deploy/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body()),
      });
      if (!resp.ok) {
        const j = await resp.json().catch(() => ({}));
        throw new Error(j.detail || `HTTP ${resp.status}`);
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ts = new Date().toISOString().replace(/[:.]/g, "-");
      a.href = url;
      a.download = `seed-recovery-deploy-${provider}-${ts}.zip`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally { setBusy(false); }
  };

  return (
    <div className="card p-5 flex flex-col gap-3" data-testid="deploy-bundle">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center gap-2">
          <Rocket className="h-4 w-4 text-purple-400" />
          GPU Deploy Bundle
        </h3>
        {recommendedGpu && (
          <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500" data-testid="deploy-gpu-name">
            target: {recommendedGpu}
          </span>
        )}
      </div>

      <p className="text-xs text-slate-400 leading-relaxed">
        Generates a ZIP with <span className="font-mono text-slate-300">Dockerfile</span>, <span className="font-mono text-slate-300">run.sh</span>, your config, the candidate wordlist and provider-specific deploy commands — ready to ship to a rented GPU box.
      </p>

      <div className="flex gap-2">
        <select
          value={provider}
          onChange={(e) => { setProvider(e.target.value); setPreview(null); }}
          className="input-base flex-1 px-2 py-1.5"
          data-testid="deploy-provider-select"
        >
          <option value="vastai">vast.ai (CLI)</option>
          <option value="runpod">RunPod (web)</option>
        </select>
        <button onClick={doPreview} disabled={busy} className="btn-ghost" data-testid="deploy-preview-btn">
          <Eye className="h-3 w-3 mr-1 inline" /> preview
        </button>
        <button onClick={doDownload} disabled={busy} className="btn-primary" data-testid="deploy-download-btn">
          <Download className="h-4 w-4" /> {busy ? "…" : "download .zip"}
        </button>
      </div>

      {error && (
        <div className="text-xs font-mono text-red-300 bg-red-950/30 border border-red-900/40 rounded-sm p-2" data-testid="deploy-error">
          {error}
        </div>
      )}

      {preview && (
        <div className="border border-slate-800 rounded-sm overflow-hidden" data-testid="deploy-preview">
          <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 bg-[#0a0a0a]">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">files</span>
              {Object.keys(preview.files).map((name) => (
                <button
                  key={name}
                  onClick={() => setPreviewFile(name)}
                  className={`text-[10px] font-mono px-2 py-0.5 rounded-sm transition-colors flex items-center gap-1 ${name === previewFile ? "bg-purple-500/20 text-purple-200 border border-purple-500/40" : "text-slate-400 hover:text-slate-200 border border-transparent"}`}
                  data-testid={`deploy-file-tab-${name.replace(/[^a-z0-9]/gi, '-').toLowerCase()}`}
                >
                  <FileCode className="h-3 w-3" /> {name}
                </button>
              ))}
            </div>
            <button onClick={() => setPreview(null)} className="text-slate-500 hover:text-slate-200" data-testid="deploy-preview-close">
              <X className="h-3 w-3" />
            </button>
          </div>
          <pre
            className="bg-[#050505] text-xs font-mono text-slate-200 p-3 max-h-[340px] overflow-auto whitespace-pre-wrap break-all"
            data-testid="deploy-preview-content"
          >
            {previewFile ? preview.files[previewFile] : ""}
          </pre>
        </div>
      )}

      <div className="text-[10px] font-mono text-slate-600 leading-relaxed">
        ⓘ The bundle contains your target address + known seed positions + the wordlist. Any passphrase is redacted. Treat the rented box as untrusted: destroy it the moment the recovery completes.
      </div>
    </div>
  );
}
