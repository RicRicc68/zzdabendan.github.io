import React, { useState } from "react";
import { ShieldCheck, Copy, X } from "lucide-react";

export default function FoundSeedModal({ seed, onClose }) {
  const [copied, setCopied] = useState(false);
  if (!seed) return null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(seed);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (_) {}
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md" data-testid="found-seed-modal">
      <div className="w-full max-w-2xl mx-4 backdrop-blur-xl bg-[#0D0E12]/95 border border-green-500/40 shadow-2xl rounded-sm p-6 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-green-400">
            <ShieldCheck className="h-5 w-5" />
            <span className="font-mono uppercase tracking-widest text-sm">SEED RECOVERED</span>
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300" data-testid="found-close-btn">
            <X className="h-5 w-5" />
          </button>
        </div>
        <p className="text-xs font-mono text-slate-400 leading-relaxed">
          Your seed phrase has been recovered. Copy it to a SECURE offline location and clear from this screen.
          Never paste it into any web form, never share it.
        </p>
        <div
          className="font-mono text-lg leading-relaxed text-green-300 bg-[#050505] border border-green-500/30 rounded-sm p-5 break-words shadow-[0_0_24px_rgba(34,197,94,0.18)]"
          data-testid="found-seed-text"
        >
          {seed}
        </div>
        <div className="flex items-center justify-end gap-3">
          <button onClick={copy} className="btn-ghost" data-testid="copy-seed-btn">
            <Copy className="h-3 w-3 mr-1 inline" /> {copied ? "Copied ✓" : "Copy to clipboard"}
          </button>
          <button onClick={onClose} className="btn-danger" data-testid="clear-close-btn">
            Clear & close
          </button>
        </div>
      </div>
    </div>
  );
}
