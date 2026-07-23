#!/bin/bash
# Watchdog: tiene live_trading.py in esecuzione, riavviandolo se crasha.
# Si ferma da solo se trova un file STOP nella working dir.
cd /workspaces/zzdabendan.github.io || exit 1
LOG="live_trading.log"

while true; do
    if [ -f STOP ]; then
        echo "$(date -Is) [watchdog] file STOP trovato, watchdog terminato" >> "$LOG"
        break
    fi
    echo "$(date -Is) [watchdog] avvio bot" >> "$LOG"
    echo "LIVE" | python3 live_trading.py >> "$LOG" 2>&1
    code=$?
    echo "$(date -Is) [watchdog] bot terminato (exit=$code), riavvio tra 10s" >> "$LOG"
    sleep 10
done
