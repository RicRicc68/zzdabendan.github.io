import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const api = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  timeout: 30000,
});

export const fmtDuration = (sec) => {
  if (sec == null || isNaN(sec)) return "—";
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (d) return `${d}d ${h}h ${m}m`;
  if (h) return `${h}h ${m}m ${s}s`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
};

export const STATUS_COLOR = {
  pending: "#94A3B8",
  running: "#3B82F6",
  found: "#22C55E",
  not_found: "#F59E0B",
  stopped: "#94A3B8",
  failed: "#EF4444",
};
