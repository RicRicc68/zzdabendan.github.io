/**
 * Wrapper per Render (piano Free): stesso pattern di ../arb-bot/server.js
 * e ../server.py — espone una porta HTTP fittizia per il keep-alive,
 * mentre lo scanner vero gira nello stesso processo.
 */
const http = require('http');

const port = process.env.PORT || 10000;
http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  if (req.method === 'HEAD') return res.end();
  res.end('OK');
}).listen(port);

require('./index.js');
