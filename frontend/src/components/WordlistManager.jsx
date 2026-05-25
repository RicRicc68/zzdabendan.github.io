import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { devError } from "../lib/logger";
import { BookText, Save, Library } from "lucide-react";

export default function WordlistManager({ version = 0 }) {
  const [raw, setRaw] = useState("");
  const [count, setCount] = useState(0);
  const [saving, setSaving] = useState(false);
  const [presets, setPresets] = useState([]);
  const [selectedPreset, setSelectedPreset] = useState("");
  const [loadingPreset, setLoadingPreset] = useState(false);

  const load = async () => {
    const r = await api.get("/wordlist");
    setRaw(r.data.raw || "");
    setCount(r.data.count || 0);
  };

  const loadPresets = async () => {
    try {
      const r = await api.get("/wordlists/presets");
      setPresets(r.data.presets || []);
    } catch (e) {
      devError("[WordlistManager] presets load failed", e);
    }
  };

  useEffect(() => { load(); loadPresets(); }, []);
  useEffect(() => { if (version > 0) load(); }, [version]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/wordlist", { raw });
      setCount(r.data.count);
    } finally { setSaving(false); }
  };

  const applyPreset = async () => {
    if (!selectedPreset) return;
    setLoadingPreset(true);
    try {
      await api.post("/wordlist/load-preset", { name: selectedPreset });
      await load();
    } finally { setLoadingPreset(false); }
  };

  return (
    <div className="card p-5 flex flex-col gap-3" data-testid="wordlist-manager">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center gap-2">
          <BookText className="h-4 w-4 text-amber-400" />
          Candidate Wordlist (candlist.txt)
        </h3>
        <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500" data-testid="wordlist-count">
          {count} words
        </span>
      </div>

      <div className="flex gap-2">
        <select
          value={selectedPreset}
          onChange={(e) => setSelectedPreset(e.target.value)}
          className="input-base flex-1 px-2 py-1.5"
          data-testid="wordlist-preset-select"
        >
          <option value="">— preset (BIP39 / Electrum) —</option>
          {presets.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name} ({p.size} words)
            </option>
          ))}
        </select>
        <button
          onClick={applyPreset}
          disabled={!selectedPreset || loadingPreset}
          className="btn-ghost flex items-center gap-1"
          data-testid="wordlist-load-preset-btn"
        >
          <Library className="h-3 w-3" /> {loadingPreset ? "…" : "load"}
        </button>
      </div>

      <textarea
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder={"one word per line\nor whitespace separated"}
        className="input-base w-full px-2 py-2 min-h-[120px]"
        data-testid="wordlist-textarea"
      />
      <button onClick={save} disabled={saving} className="btn-primary self-start" data-testid="wordlist-save-btn">
        <Save className="h-4 w-4" /> {saving ? "Saving…" : "Save Wordlist"}
      </button>
    </div>
  );
}
