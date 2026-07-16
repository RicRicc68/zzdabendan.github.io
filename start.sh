#!/bin/bash
# Invia "LIVE" allo stdin di server.py per superare la conferma
# interattiva di live_trading.py (stesso meccanismo usato in locale).
echo LIVE | python3 server.py
