import { useEffect, useRef, useState } from "react";

/**
 * useJobStream — open a WebSocket to /api/jobs/{id}/stream and receive
 * snapshot + incremental log entries. Returns { logs, status, stats, foundSeed }.
 * Falls back gracefully if the WebSocket cannot be opened.
 */
export default function useJobStream(jobId, backendUrl) {
  const [logs, setLogs] = useState([]);
  const [status, setStatus] = useState(null);
  const [stats, setStats] = useState({});
  const [foundSeed, setFoundSeed] = useState(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef(null);

  useEffect(() => {
    setLogs([]); setStatus(null); setStats({}); setFoundSeed(null);
    if (!jobId || !backendUrl) return;
    const wsUrl = backendUrl.replace(/^http/, "ws") + `/api/jobs/${jobId}/stream`;
    let ws;
    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      return;
    }
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "snapshot") {
          setLogs(msg.logs || []);
          setStatus(msg.status);
          setStats(msg.stats || {});
          setFoundSeed(msg.found_seed || null);
        } else if (msg.type === "log") {
          setLogs((cur) => cur.concat([msg.entry]));
          setStats(msg.stats || {});
          setStatus(msg.status);
        } else if (msg.type === "end") {
          setStatus(msg.status);
          setStats(msg.stats || {});
          if (msg.found_seed) setFoundSeed(msg.found_seed);
        }
      } catch (_) {}
    };
    return () => {
      try { ws.close(); } catch (_) {}
    };
  }, [jobId, backendUrl]);

  return { logs, status, stats, foundSeed, connected };
}
