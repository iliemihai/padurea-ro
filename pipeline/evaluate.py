"""Testul pe trecut: cât de bine se potrivesc zonele noastre cu pierderile de pădure din Hansen (Universitatea Maryland).

python -m pipeline.evaluate --year 2025 --docs ev/docs [--out ev/evaluare_2025.json]

Precizia: din zonele noastre văzute prima dată în anul testat, câte au cel puțin 20% din suprafață pierdere Hansen în
anul testat sau în cel dinainte (o tăiere din iarnă o vedem uneori abia primăvara). Pe niveluri de încredere și pe ce
a crezut AI-ul.
Recall: din petele de pierdere Hansen din anul testat (cel puțin 0,5 ha, în România), câte ating o zonă de-a noastră,
pe mărimi; și cât din suprafața lor e acoperită. „Până la nivelul X” = găsite de zone cu încrederea X sau mai mare.

Hansen e o referință independentă (Landsat, 30 m, un an întreg), dar nu perfectă: are și doborâturi de vânt și incendii,
ratează tăierile parțiale, iar anul lui nu se potrivește la zi cu ferestrele noastre. Cifrele sunt aproximative.
"""
import argparse
import json
import math
import os
from pathlib import Path

import numpy as np

from . import config as C
from . import romania

LEVELS = ["ridicată", "medie", "scăzută", "de confirmat"]
CODE = {lv: i + 1 for i, lv in enumerate(LEVELS)}
SIZES = [("0,5–1 ha", 0.5, 1), ("1–5 ha", 1, 5), ("peste 5 ha", 5, 1e9)]
PX = 0.00025          # pixelul Hansen, în grade
TRUE_FRAC = 0.2       # o zonă „se potrivește” dacă măcar atât din ea e pierdere Hansen


def load_zones(docs, year):
    zs = []
    p = docs / "data" / "alerts.json"
    if p.exists():
        zs += json.loads(p.read_text(encoding="utf-8")).get("alerts", [])
    for f in sorted((docs / "data" / "arhiva").glob("????-??.json")):
        zs += json.loads(f.read_text(encoding="utf-8")).get("alerts", [])
    seen, out = set(), []
    for a in zs:
        if a["id"] in seen or not a["first_seen"].startswith(str(year)):
            continue
        seen.add(a["id"])
        out.append(a)
    return out


def window(src, x0, y0, x1, y1):
    from rasterio.windows import from_bounds
    return from_bounds(x0, y0, x1, y1, src.transform).round_offsets().round_lengths()


def precision(zones, src, year):
    from rasterio.features import geometry_mask
    from shapely.geometry import mapping, shape
    good = [year - 2000, year - 2001]
    rows = []
    for a in zones:
        g = shape(a["geometry"])
        x0, y0, x1, y1 = g.bounds
        w = window(src, x0 - PX, y0 - PX, x1 + PX, y1 + PX)
        arr = src.read(1, window=w, boundless=True, fill_value=0)
        if arr.size == 0:
            continue
        inside = ~geometry_mask([mapping(g)], out_shape=arr.shape, transform=src.window_transform(w), all_touched=True)
        n = int(inside.sum())
        if not n:
            continue
        frac = float((np.isin(arr, good) & inside).sum()) / n
        rows.append({"id": a["id"], "nivel": a.get("incredere"), "ha": a.get("ha"), "ai": (a.get("ai") or {}).get("categorie"),
                     "arie_protejata": bool(a.get("arii")), "frac": round(frac, 3)})
    return rows


def recall(zones, src, year, band=0.5):
    from rasterio.features import geometry_mask, rasterize
    from scipy import ndimage
    from shapely.geometry import mapping, shape
    ro = romania.outline()
    W, S, E, N = ro.bounds
    yv = year - 2000
    shapes = sorted(((shape(a["geometry"]).buffer(PX * 1.2), CODE.get(a.get("incredere"), 4)) for a in zones), key=lambda t: -t[1])
    counts = {name: {"total": 0, **{lv: 0 for lv in LEVELS}} for name, _, _ in SIZES}
    area_tot, area_hit = 0.0, {lv: 0.0 for lv in LEVELS}
    lat = S
    while lat < N:
        top = min(lat + band, N)
        w = window(src, W, lat, E, top)
        arr = src.read(1, window=w, boundless=True, fill_value=0)
        tr = src.window_transform(w)
        loss = (arr == yv) & ~geometry_mask([mapping(ro)], out_shape=arr.shape, transform=tr)
        if loss.any():
            lab, nlab = ndimage.label(loss, structure=np.ones((3, 3), bool))
            idx = np.arange(1, nlab + 1)
            here = [(mapping(g), c) for g, c in shapes if g.bounds[3] >= lat and g.bounds[1] <= top]
            ours = rasterize(here, out_shape=arr.shape, transform=tr, fill=0, dtype="uint8") if here else np.zeros(arr.shape, np.uint8)
            px_ha = (PX * 111320 * math.cos(math.radians((lat + top) / 2))) * (PX * 110574) / 1e4
            sizes = ndimage.sum(loss, lab, index=idx) * px_ha
            best = ndimage.minimum(np.where(ours == 0, 99, ours).astype(np.uint8), lab, index=idx)
            for s_ha, b in zip(sizes, best):
                if s_ha < 0.5:
                    continue
                name = next(n for n, lo, hi in SIZES if lo <= s_ha < hi)
                counts[name]["total"] += 1
                for lv in LEVELS:
                    if b <= CODE[lv]:
                        counts[name][lv] += 1
            big = np.isin(lab, idx[sizes >= 0.5])
            area_tot += float(big.sum()) * px_ha
            for lv in LEVELS:
                area_hit[lv] += float((big & (ours >= 1) & (ours <= CODE[lv])).sum()) * px_ha
            del lab, ours, big
        lat = top
    return counts, area_tot, area_hit


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--docs", default=str(C.DOCS))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    import rasterio
    from .run_tiles import hansen_lossyear
    src = rasterio.open(hansen_lossyear())
    zones = load_zones(Path(a.docs), a.year)
    rows = precision(zones, src, a.year)
    counts, area_tot, area_hit = recall(zones, src, a.year)

    prec = {}
    for lv in LEVELS:
        r = [x for x in rows if x["nivel"] == lv]
        prec[lv] = {"zone": len(r), "precizie_%": pct(sum(x["frac"] >= TRUE_FRAC for x in r), len(r)),
                    "jumatate_%": pct(sum(x["frac"] >= 0.5 for x in r), len(r))}
    conf = [x for x in rows if x["nivel"] in ("ridicată", "medie")]
    by_ai = {}
    for x in conf:
        k = x["ai"] or "fără AI"
        by_ai.setdefault(k, [0, 0])
        by_ai[k][0] += 1
        by_ai[k][1] += x["frac"] >= TRUE_FRAC
    rec = {name: {"pete": c["total"], **{f"pana_la_{lv}_%": pct(c[lv], c["total"]) for lv in LEVELS}} for name, c in counts.items()}
    tot = {lv: sum(c[lv] for c in counts.values()) for lv in LEVELS}
    n_all = sum(c["total"] for c in counts.values())
    report = {
        "an": a.year, "zone": len(rows), "prag_potrivire": TRUE_FRAC,
        "precizie": prec,
        "precizie_dupa_ai_(ridicata+medie)": {k: {"zone": v[0], "precizie_%": pct(v[1], v[0])} for k, v in by_ai.items()},
        "recall_pete": rec,
        "recall_pete_total": {"pete": n_all, **{f"pana_la_{lv}_%": pct(tot[lv], n_all) for lv in LEVELS}},
        "recall_suprafata": {"ha_hansen": round(area_tot), **{f"pana_la_{lv}_%": pct(area_hit[lv], area_tot) for lv in LEVELS}},
        "fals_pozitive_mari": sorted([x for x in conf if x["frac"] < TRUE_FRAC], key=lambda x: -(x["ha"] or 0))[:30],
    }
    out = Path(a.out) if a.out else C.OUT / f"evaluare_{a.year}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out.parent / f"evaluare_{a.year}_zone.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    md = [f"## Testul pe {a.year}: zonele noastre comparate cu pierderile Hansen", "",
          f"{len(rows)} zone văzute prima dată în {a.year}; o zonă se potrivește dacă cel puțin {int(TRUE_FRAC * 100)}% din ea e pierdere Hansen {a.year - 1}–{a.year}.", "",
          "| Încredere | Zone | Precizie | Măcar jumătate pierdere |", "|---|---|---|---|"]
    md += [f"| {lv} | {p['zone']} | {p['precizie_%']}% | {p['jumatate_%']}% |" for lv, p in prec.items()]
    md += ["", f"Recall: {n_all} pete de pierdere Hansen {a.year} de cel puțin 0,5 ha.", "",
           "| Mărime | Pete | ridicată | până la medie | până la scăzută | toate |", "|---|---|---|---|---|---|"]
    md += [f"| {n} | {r['pete']} | " + " | ".join(f"{r['pana_la_' + lv + '_%']}%" for lv in LEVELS) + " |" for n, r in rec.items()]
    md += ["", "Suprafața Hansen acoperită: " + ", ".join(f"{lv} {report['recall_suprafata']['pana_la_' + lv + '_%']}%" for lv in LEVELS)]
    text = "\n".join(md)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
