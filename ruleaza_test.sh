#!/bin/bash
# Test pe imagini reale: 4 plăci Sentinel-2, ultimele 30 de zile.
#   bash ~/Projects/padurea-ro/github/ruleaza_test.sh
# Cu analistul AI (Claude Haiku 5.5), înainte de comandă:  export ANTHROPIC_API_KEY=cheia_ta
# Plăcile: 34TFT (Sălaj–Cluj), 35TLN (Suceava), 34TES (Arad, toamna), 34TFQ (Caraș-Severin, norii)
cd "$(dirname "$0")" || exit 1
PY=../.venv/bin/python
TILES=34TFT,35TLN,34TES,34TFQ
T0=$(date +%s)

# rezultatele rulării de dinainte le mutăm deoparte, nu le ștergem
if [ -d out ]; then mv out "out_$(date +%H%M%S)"; fi
mkdir -p out data/hansen
for f in docs/data/alerts.json docs/data/runs.json; do [ -f "$f" ] && mv "$f" "out/prev_$(basename "$f")"; done
[ -d docs/img ] && mv docs/img out/prev_img
[ -e data/hansen/Hansen_GFC-2025-v1.13_lossyear_50N_020E.tif ] || ln -s "$(cd .. && pwd)/data/GFC-2025-v1.13_lossyear.tif" data/hansen/Hansen_GFC-2025-v1.13_lossyear_50N_020E.tif
[ -e data/hansen/Hansen_GFC-2025-v1.13_treecover2000_50N_020E.tif ] || ln -s "$(cd .. && pwd)/data/GFC-2025-v1.13_treecover2000.tif" data/hansen/Hansen_GFC-2025-v1.13_treecover2000_50N_020E.tif
$PY -m pip install -q pyproj >/dev/null 2>&1

# cheia Claude: din mediu sau din ~/Projects/padurea-ro/.env (fișier privat, nu intră în git)
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f ../.env ]; then . ../.env; export ANTHROPIC_API_KEY; fi
AI=0
if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "0/3 Verific analistul AI (Claude) pe 2 imagini…"
  if EVAL_N=2 $PY -m pipeline.eval_judge claude 2>&1 | tee out/ai_check.txt | grep -q '"corecte"'; then
    grep -q "eroare" out/ai_check.txt && echo "   AI-ul răspunde cu erori (vezi out/ai_check.txt), merg fără el" || { AI=1; echo "   merge"; }
  else
    echo "   AI-ul nu merge (vezi out/ai_check.txt), merg fără el"
  fi
else
  echo "0/3 Fără ANTHROPIC_API_KEY: rulez fără analistul AI"
fi

echo "1/3 Detectorul pe 4 plăci, în paralel (5–10 minute)…"
for g in 0 1 2 3; do
  $PY -m pipeline.run_tiles --group "$g" --groups 4 --days 30 --tiles "$TILES" > "out/log_$g.txt" 2>&1 &
done
wait
grep -h -E "Placa|  ok:|Gata grupa|eroare" out/log_*.txt

echo "2/3 Analistul AI"
if [ "$AI" = 1 ]; then
  $PY -m pipeline.eval_judge claude | tail -3
  $PY -m pipeline.judge_groups | tail -2
else
  echo "   sar peste"
fi

echo "3/3 Contextul, criticul și redactorul"
$PY -m pipeline.run_finish

tar czf out/run.tgz out/group_*.json out/img out/log_*.txt out/eval_*.json out/ai_raw.jsonl out/ai_check.txt docs/data/alerts.json docs/data/runs.json docs/img 2>/dev/null
echo "GATA în $(( ($(date +%s) - T0) / 60 )) minute. Scrie-i lui Claude."
