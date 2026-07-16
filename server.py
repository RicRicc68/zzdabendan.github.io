"""
Wrapper per Render (piano Free): espone una porta HTTP fittizia che
risponde ai ping di keep-alive, mentre il bot vero gira in un thread.
Il piano Free di Render mette in sleep il servizio dopo 15 minuti senza
traffico HTTP: serve un ping esterno periodico (es. cron-job.org) su "/".
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from live_trading import run_live


class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(("0.0.0.0", port), PingHandler).serve_forever()


if __name__ == "__main__":
    threading.Thread(target=start_http_server, daemon=True).start()
    run_live()
