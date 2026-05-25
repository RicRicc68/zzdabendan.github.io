import React, { useEffect, useRef, useState } from "react";
import { Terminal, Trash2, Pause, Play } from "lucide-react";

const STREAM_COLOR = {
  stdout: "text-slate-200",
  stderr: "text-red-300",
  system: "text-blue-300",
  archived: "text-slate-400",
};

export default function TerminalPanel({ lines, autoScroll, onToggleAutoScroll, onClear, title = "LIVE OUTPUT" }) {
  const ref = useRef(null);
  const [follow, setFollow] = useState(autoScroll);

  useEffect(() => setFollow(autoScroll), [autoScroll]);

  useEffect(() => {
    if (follow && ref.current) {
      ref.current.scrollTop = ref.current.scrollHeight;
    }
  }, [lines, follow]);

  return (
    <div className="bg-[#050505] border border-slate-800 rounded-sm overflow-hidden flex flex-col" data-testid="terminal-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800 bg-[#0a0a0a]">
        <div className="flex items-center gap-2 text-xs text-slate-400 font-mono uppercase tracking-wider">
          <Terminal className="h-3.5 w-3.5 text-green-400" />
          <span>{title}</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-500">{lines.length} lines</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onToggleAutoScroll(!autoScroll)}
            className="text-[10px] font-mono uppercase text-slate-400 hover:text-slate-200 transition-colors flex items-center gap-1"
            data-testid="terminal-follow-toggle"
          >
            {autoScroll ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
            {autoScroll ? "follow" : "paused"}
          </button>
          <button
            onClick={onClear}
            className="text-[10px] font-mono uppercase text-slate-400 hover:text-red-300 transition-colors flex items-center gap-1"
            data-testid="terminal-clear-btn"
          >
            <Trash2 className="h-3 w-3" /> clear
          </button>
        </div>
      </div>
      <div
        ref={ref}
        className="flex-1 overflow-y-auto px-3 py-2 text-xs font-mono leading-relaxed min-h-[280px] max-h-[440px]"
        data-testid="terminal-output"
      >
        {lines.length === 0 && (
          <div className="text-slate-600 italic">// awaiting job output —</div>
        )}
        {lines.map((l, idx) => (
          <div key={idx} className={`${STREAM_COLOR[l.stream] || "text-slate-300"} whitespace-pre-wrap break-all`}>
            <span className="text-slate-700 mr-2">{String(idx + 1).padStart(4, "0")}</span>
            {l.line}
          </div>
        ))}
      </div>
    </div>
  );
}
