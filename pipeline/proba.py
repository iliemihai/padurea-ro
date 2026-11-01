"""Verificarea unui loc anume: ce a găsit detectorul în jurul unui punct, cu pozele înainte/după.

python -m pipeline.proba --lat 45.59 --lon 22.40 --km 6 --out proba

Citește zonele din PADUREA_DOCS (alerts.json, arhiva) și din PADUREA_PENDING (neconfirmate), după o rulare
run_tiles + run_finish făcută într-un folder separat (vezi .github/workflows/proba.yml). Scrie proba.json și
copiază pozele zonelor găsite.
"""
import argparse
import json
import math
import shutil
from pathlib import Path

from . import config as C


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--km", type=float, default=5)
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default="proba")
    a = ap.parse_args()
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    zones = []
    files = [C.DOCS / "data" / "alerts.json", C.PENDING] + sorted((C.DOCS / "data" / "arhiva").glob("????-??.json"))
    for f in files:
        if f.exists():
            zones += json.loads(f.read_text(encoding="utf-8")).get("alerts", [])
    near = []
    for z in zones:
        dy = (z["lat"] - a.lat) * 111.32
        dx = (z["lon"] - a.lon) * 111.32 * math.cos(math.radians(a.lat))
        d = math.hypot(dx, dy)
        if d <= a.km:
            near.append(dict(z, dist_km=round(d, 2)))
    near.sort(key=lambda z: (z["incredere"] == "de confirmat", -z["ha"]))
    keep = ("id", "incredere", "ha", "lat", "lon", "dist_km", "first_seen", "before_date", "after_date", "vara", "n_dates",
            "uat", "localitate", "arii", "ai", "dovezi", "text", "img_before", "img_after", "geometry")
    rows = []
    for z in near:
        for k in ("img_before", "img_after"):
            info = z.get(k)
            if info and info.get("file") and (C.DOCS / "img" / info["file"]).exists():
                shutil.copy(C.DOCS / "img" / info["file"], out / "img" / info["file"])
        rows.append({k: z.get(k) for k in keep})
    (out / "proba.json").write_text(json.dumps({"label": a.label, "lat": a.lat, "lon": a.lon, "km": a.km,
                                                 "zone": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{a.label}: {len(rows)} zone la cel mult {a.km} km")
    for z in rows[:15]:
        print(f"  {z['id']} {z['incredere']:12s} {z['ha']:6.1f} ha  {z['dist_km']:4.1f} km  văzută {z['first_seen']}"
              f"  înainte {z.get('before_date') or ('vara ' + str(z.get('vara')) if z.get('vara') else '-')}")


if __name__ == "__main__":
    main()
