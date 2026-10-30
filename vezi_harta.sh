#!/bin/bash
# Deschide harta pe Mac-ul tău, cu fundalul din satelit:  bash ~/Projects/padurea-ro/github/vezi_harta.sh
cd "$(dirname "$0")/docs" || exit 1
PORT=8765
python3 -m http.server "$PORT" >/dev/null 2>&1 &
SRV=$!
sleep 1
open "http://localhost:$PORT/"
echo "Harta e deschisă în browser la http://localhost:$PORT/  (Ctrl+C ca s-o închizi)"
trap 'kill $SRV' INT TERM
wait $SRV
