import React, { useState } from "react";
import { api } from "../lib/api";
import { Layers, Eye } from "lucide-react";

export default function MaskPreview({ config }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [unpositioned, setUnpositioned] = useState("");

  const preview = async () => {
    setLoading(true);
    try {
      const known_unpositioned = unpositioned.split(/\s+/).filter(Boolean);
      const r = await api.post("/masks/preview", {
        seed_length: config.seed_length,
        known_words: config.known_words,
        known_unpositioned,
      });
      setData(r.data);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card p-5 flex flex-col gap-3" data-testid="mask-preview">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium tracking-tight text-slate-100 flex items-center gap-2">
          <Layers className="h-4 w-4 text-blue-400" />
          Mask Preview
        </h3>
        <button onClick={preview} disabled={loading} className="btn-ghost" data-testid="mask-preview-btn">
          <Eye className="h-3 w-3 mr-1 inline" /> {loading ? "…" : "preview"}
        </button>
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">
          Known but UNPOSITIONED words (space separated, optional)
        </span>
        <input
          type="text"
          value={unpositioned}
          placeholder="e.g. lemon ocean ladder"
          onChange={(e) => setUnpositioned(e.target.value)}
          className="input-base w-full px-2 py-1.5"
          data-testid="unpositioned-input"
        />
      </label>
      {data && (
        <div className="flex flex-col gap-2 mt-1">
          <div className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">
            Fixed mask
          </div>
          <pre className="bg-[#050505] border border-slate-800 rounded-sm p-2 text-xs font-mono text-green-300 whitespace-pre-wrap break-all" data-testid="mask-fixed-output">
            {data.fixed_mask?.[0]}
          </pre>
          {data.permutation_masks_count > 0 && (
            <>
              <div className="text-[10px] uppercase tracking-widest text-slate-500 font-mono">
                Permutation masks ({data.permutation_masks_count}, first {data.permutation_masks_sample.length})
              </div>
              <pre className="bg-[#050505] border border-slate-800 rounded-sm p-2 text-[10px] font-mono text-slate-300 max-h-40 overflow-auto" data-testid="mask-perm-output">
                {data.permutation_masks_sample.join("\n")}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}
