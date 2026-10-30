#!/bin/bash
# Test pe imagini reale: 4 plăci Sentinel-2, ultimele 30 de zile, cu analistul AI pe Mac.
#   bash ~/Projects/padurea-ro/github/ruleaza_test.sh
# Plăcile: 34TFT (Sălaj, tăierea reală), 35TLN (Suceava), 34TES (Arad, toamna), 34TFQ (Caraș-Severin, norii)
cd "$(dirname "$0")" || exit 1
PY=../.venv/bin/python
TILES=34TFT,35TLN,34TES,34TFQ
MODEL=qwen3-vl:4b
T0=$(date +%s)

echo "Pregătesc mediul (o dată)…"
$PY -m pip install -q pyproj || exit 1
mkdir -p data/hansen out
[ -e data/hansen/Hansen_GFC-2025-v1.13_lossyear_50N_020E.tif ] || ln -s "$(cd .. && pwd)/data/GFC-2025-v1.13_lossyear.tif" data/hansen/Hansen_GFC-2025-v1.13_lossyear_50N_020E.tif
rm -f out/group_*.json out/log_*.txt

echo "1/4 Pornesc modelul AI în fundal ($MODEL; îl descarc dacă lipsește)"
(
  curl -s localhost:11434/api/tags >/dev/null 2>&1 || (ollama serve >/dev/null 2>&1 &)
  sleep 4
  ollama pull "$MODEL" > out/model.log 2>&1
) &
PULL=$!

echo "2/4 Detectorul pe 4 plăci, în paralel (10–20 de minute)…"
PIDS=()
for g in 0 1 2 3; do
  $PY -m pipeline.run_tiles --group "$g" --groups 4 --days 30 --tiles "$TILES" > "out/log_$g.txt" 2>&1 &
  PIDS+=($!)
done
for p in "${PIDS[@]}"; do wait "$p" || echo "   o grupă a avut o eroare (vezi out/log_*.txt)"; done
grep -h -E "Placa|zone păstrate|Gata grupa|eroare" out/log_*.txt

echo "3/4 Analistul AI"
wait "$PULL"
if curl -s localhost:11434/api/tags | grep -q "$MODEL"; then
  LOCAL_MODEL="$MODEL" $PY -m pipeline.eval_judge "$MODEL" | tail -4
  LOCAL_MODEL="$MODEL" $PY -m pipeline.judge_groups | tail -3
else
  echo "   modelul n-a pornit (vezi out/model.log), merg mai departe fără AI"
fi

echo "4/4 Contextul, criticul și redactorul"
$PY -m pipeline.run_finish

echo "GATA în $(( ($(date +%s) - T0) / 60 )) minute. Scrie-i lui Claude."
