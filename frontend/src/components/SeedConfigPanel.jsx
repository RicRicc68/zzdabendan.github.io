import React, { useState } from "react";
import { api } from "../lib/api";
import { ShieldCheck, ShieldAlert, Loader2, Search } from "lucide-react";

export default function SeedConfigPanel({ config, setConfig, onSave, saving }) {
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState(null);

  const verifyAddress = async () => {
    if (!config.address) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      const r = await api.post("/address/verify", { address: config.address });
      setVerifyResult(r.data);
    } catch (e) {
      setVerifyResult({ recommendation: "error", message: e.response?.data?.detail || e.message });
    } finally { setVerifying(false); }
  };

  const seedLength = config.seed_length || 12;

  const setWord = (i, val) => {
    const next = [...(config.known_words || [])];
    while (next.length < seedLength) next.push("");
    next[i] = val.toLowerCase().trim();
    setConfig({ ...config, known_words: next });
  };

  const setLength = (l) => {
    const next = [...(config.known_words || [])];
    while (next.length < l) next.push("");
    next.length = l;
    setConfig({ ...config, seed_length: l, known_words: next });
  };

  const knownCount = (config.known_words || []).filter((w) => w && w.trim()).length;
  const unknownCount = seedLength - knownCount;

  return (
    <div className="card p-5 flex flex-col gap-4" data-testid="seed-config-panel">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100">Seed Configuration</h3>
        <div className="text-[10px] font-mono uppercase tracking-widest text-slate-500">
          {knownCount}/{seedLength} known · {unknownCount} unknown
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Seed length">
          <select
            value={seedLength}
            onChange={(e) => setLength(parseInt(e.target.value))}
            className="input-base w-full px-2 py-1.5"
            data-testid="seed-length-select"
          >
            {[12, 15, 18, 21, 24].map((n) => (
              <option key={n} value={n}>{n} words</option>
            ))}
          </select>
        </Field>
        <Field label="Wallet type">
          <select
            value={config.wallet_type || "electrum2"}
            onChange={(e) => setConfig({ ...config, wallet_type: e.target.value })}
            className="input-base w-full px-2 py-1.5"
            data-testid="wallet-type-select"
          >
            <option value="electrum2">Electrum v2</option>
            <option value="electrum1">Electrum v1 (legacy)</option>
            <option value="bip39">BIP39</option>
            <option value="bip32">BIP32</option>
            <option value="ethereum">Ethereum</option>
          </select>
        </Field>
        <Field label="Language">
          <select
            value={config.language || "en"}
            onChange={(e) => setConfig({ ...config, language: e.target.value })}
            className="input-base w-full px-2 py-1.5"
            data-testid="language-select"
          >
            <option value="en">English</option>
            <option value="es">Spanish</option>
            <option value="fr">French</option>
            <option value="it">Italian</option>
            <option value="ja">Japanese</option>
            <option value="zh-hans">Chinese (Simplified)</option>
          </select>
        </Field>
        <Field label="Threads">
          <input
            type="number" min={1} max={16}
            value={config.threads ?? 2}
            onChange={(e) => setConfig({ ...config, threads: parseInt(e.target.value || "1") })}
            className="input-base w-full px-2 py-1.5"
            data-testid="threads-input"
          />
        </Field>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-widest text-slate-500 font-mono mb-2">
          Known words by position — leave empty for unknown (?)
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2" data-testid="seed-words-grid">
          {Array.from({ length: seedLength }).map((_, i) => {
            const w = (config.known_words || [])[i] || "";
            return (
              <div key={i} className="relative">
                <span className="absolute left-2 top-1.5 text-[10px] font-mono text-slate-600">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <input
                  type="text"
                  value={w}
                  placeholder="?"
                  onChange={(e) => setWord(i, e.target.value)}
                  className="input-base w-full pl-7 pr-2 py-1.5 text-sm"
                  data-testid={`seed-word-input-${i + 1}`}
                />
              </div>
            );
          })}
        </div>
      </div>

      <div className="border-t border-slate-800 pt-4 flex flex-col gap-3">
        <Field label="Verification target — at least one (address, mpk, or wallet file)">
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="BTC address (e.g. bc1q...)"
              value={config.address || ""}
              onChange={(e) => { setConfig({ ...config, address: e.target.value }); setVerifyResult(null); }}
              className="input-base flex-1 px-2 py-1.5"
              data-testid="verify-address-input"
            />
            <button
              type="button"
              onClick={verifyAddress}
              disabled={!config.address || verifying}
              className="btn-ghost"
              title="Check address format + on-chain history"
              data-testid="verify-address-btn"
            >
              {verifying ? <Loader2 className="h-3 w-3 animate-spin" /> : <Search className="h-3 w-3" />}
              check
            </button>
          </div>
          {verifyResult && <AddressVerdict result={verifyResult} />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Master pub key (xpub)">
            <input
              type="text"
              placeholder="xpub..."
              value={config.mpk || ""}
              onChange={(e) => setConfig({ ...config, mpk: e.target.value })}
              className="input-base w-full px-2 py-1.5"
              data-testid="verify-mpk-input"
            />
          </Field>
          <Field label="Address-derive limit">
            <input
              type="number" min={1} max={10000}
              value={config.addr_limit ?? 10}
              onChange={(e) => setConfig({ ...config, addr_limit: parseInt(e.target.value || "10") })}
              className="input-base w-full px-2 py-1.5"
              data-testid="addr-limit-input"
            />
          </Field>
        </div>
        <Field label="Wallet file path (optional)">
          <input
            type="text"
            placeholder="/path/to/wallet"
            value={config.wallet_file_path || ""}
            onChange={(e) => setConfig({ ...config, wallet_file_path: e.target.value })}
            className="input-base w-full px-2 py-1.5"
            data-testid="verify-walletfile-input"
          />
        </Field>
      </div>

      <div className="border-t border-slate-800 pt-4 flex flex-col gap-3">
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={!!config.passphrase_enabled}
            onChange={(e) => setConfig({ ...config, passphrase_enabled: e.target.checked })}
            data-testid="passphrase-enabled-checkbox"
          />
          Use seed-extension passphrase
        </label>
        {config.passphrase_enabled && (
          <Field label="Passphrase">
            <input
              type="password"
              value={config.passphrase || ""}
              onChange={(e) => setConfig({ ...config, passphrase: e.target.value })}
              className="input-base w-full px-2 py-1.5"
              data-testid="passphrase-input"
            />
          </Field>
        )}
        <Field label="Typo tolerance (big-typos)">
          <input
            type="number" min={0} max={4}
            value={config.typos ?? 0}
            onChange={(e) => setConfig({ ...config, typos: parseInt(e.target.value || "0") })}
            className="input-base w-full px-2 py-1.5"
            data-testid="typos-input"
          />
        </Field>
      </div>

      <button
        onClick={onSave}
        disabled={saving}
        className="btn-primary self-start"
        data-testid="save-config-btn"
      >
        {saving ? "Saving…" : "Save Configuration"}
      </button>
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


const VERDICT_COLOR = {
  ok: { c: "#22C55E", icon: <ShieldCheck className="h-3 w-3" />, label: "VALID · ON-CHAIN" },
  unused: { c: "#F59E0B", icon: <ShieldAlert className="h-3 w-3" />, label: "VALID · UNUSED" },
  invalid: { c: "#EF4444", icon: <ShieldAlert className="h-3 w-3" />, label: "INVALID" },
  unknown: { c: "#94A3B8", icon: <ShieldAlert className="h-3 w-3" />, label: "EXPLORER OFFLINE" },
  error: { c: "#EF4444", icon: <ShieldAlert className="h-3 w-3" />, label: "ERROR" },
};

function AddressVerdict({ result }) {
  const v = VERDICT_COLOR[result.recommendation] || VERDICT_COLOR.error;
  return (
    <div
      className="mt-2 border rounded-sm px-3 py-2 flex flex-col gap-1"
      style={{ borderColor: v.c + "55", background: v.c + "10" }}
      data-testid="address-verdict"
    >
      <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-widest" style={{ color: v.c }}>
        {v.icon} {v.label}
        {result.format?.type && (
          <span className="text-slate-500 normal-case tracking-normal">· {result.format.type}</span>
        )}
      </div>
      <div className="text-[11px] font-mono text-slate-300 leading-relaxed" data-testid="address-verdict-message">
        {result.message}
      </div>
      {result.onchain?.balance_sats != null && (
        <div className="text-[10px] font-mono text-slate-500 flex gap-4">
          <span>tx: {result.onchain.tx_count?.toLocaleString?.()}</span>
          <span>bal: {(result.onchain.balance_sats / 1e8).toFixed(8)} BTC</span>
          {result.onchain.explorer && <span>via {result.onchain.explorer.replace("https://", "")}</span>}
        </div>
      )}
    </div>
  );
}
