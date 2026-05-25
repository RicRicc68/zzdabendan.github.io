import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { BookText, Save } from "lucide-react";

export default function WordlistManager() {
  const [raw, setRaw] = useState("");
  const [count, setCount] = useState(0);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const r = await api.get("/wordlist");
    setRaw(r.data.raw || "");
    setCount(r.data.count || 0);
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/wordlist", { raw });
      setCount(r.data.count);
    } finally { setSaving(false); }
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
