"""Fișierele fixe ale hărții, refăcute doar când se schimbă sursele:

  docs/data/static/places.json     numele localităților din România (GeoNames), cu rangul care decide de la ce zoom apar
  docs/data/static/romania.geojson conturul țării, din limitele județelor

python -m pipeline.static_map    (GeoNames se descarcă singur în data/, ca la context)

Rangul: 0 București, 1 reședințe de județ, 2 municipii, 3 orașe, 4 sate-reședință de comună, 5 alte sate mari.
"""
import json
import unicodedata

from . import config as C
from . import romania, uat
from .context import localities

SEATS = {"Deva", "Buftea"}          # reședințe de județ pe care GeoNames nu le marchează ca atare
VILLAGE_MIN_POP = 500
RANK_BY_TIP = {"municipiul": 2, "orașul": 3, "comuna": 4}


def key(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace("-", " ").strip()


def rows():
    localities()                     # descarcă GeoNames dacă lipsește
    out = []
    for line in (C.DATA / "geonames_RO.txt").read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) > 14 and p[6] == "P" and p[7] in ("PPLC", "PPLA", "PPLA2", "PPL"):
            out.append({"name": uat.modern(p[1]), "lat": float(p[4]), "lon": float(p[5]), "code": p[7], "pop": int(p[14] or 0)})
    return out


def places():
    U = uat.UAT()
    pts, seen_uat = [], set()
    for r in rows():
        if not romania.contains(r["lon"], r["lat"], margin=0.03):
            continue
        rank = None
        if r["code"] == "PPLC":
            r["name"], rank = "București", 0
        elif r["code"] == "PPLA" or (r["name"] in SEATS and r["pop"] > 5000):
            rank = 1
        elif r["code"] == "PPLA2":
            u = U.find(r["lon"], r["lat"])
            same = u and key(u["nume"]) == key(r["name"])
            rank = RANK_BY_TIP.get(u["tip"], 4) if same else 4
            if same:
                seen_uat.add(u["siruta"])
        elif r["pop"] >= VILLAGE_MIN_POP:
            rank = 5
        if rank is not None:
            pts.append([round(r["lon"], 4), round(r["lat"], 4), r["name"], rank])
    # același loc de două ori (o dată ca reședință, o dată ca sat): păstrăm rangul cel mai mare
    best = {}
    for p in sorted(pts, key=lambda p: p[3]):
        k = (key(p[2]), round(p[0], 1), round(p[1], 1))
        best.setdefault(k, p)
    return sorted(best.values(), key=lambda p: (p[3], p[2])), seen_uat


def main():
    pts, _ = places()
    out = C.DOCS / "data" / "static"
    (out / "places.json").write_text(json.dumps({"sursa": "GeoNames (CC BY 4.0)", "p": pts}, ensure_ascii=False, separators=(",", ":")),
                                     encoding="utf-8")
    from shapely.geometry import mapping
    geom = json.loads(json.dumps(mapping(romania.outline())))

    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 4), round(c[1], 4)]
    geom["coordinates"] = rnd(geom["coordinates"])
    (out / "romania.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"n": "România"}, "geometry": geom}]}, separators=(",", ":")), encoding="utf-8")
    by = {}
    for p in pts:
        by[p[3]] = by.get(p[3], 0) + 1
    print(f"Localități: {len(pts)} {dict(sorted(by.items()))}; contur: {geom['type']}")


if __name__ == "__main__":
    main()
