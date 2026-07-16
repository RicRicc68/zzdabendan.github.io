/**
 * Wrapper per Render (piano Free): espone una porta HTTP fittizia che
 * risponde ai ping di keep-alive, mentre il bot vero gira nello stesso
 * processo. Il piano Free di Render mette in sleep il servizio dopo 15
 * minuti senza traffico HTTP: serve un ping esterno periodico (es.
 * cron-job.org) su "/". Stesso pattern di ../server.py per il bot Python.
 */
const http = require('http');

const port = process.env.PORT || 10000;
http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/plain' });
  if (req.method === 'HEAD') return res.end();
  res.end('OK');
}).listen(port);

require('./index.js');
