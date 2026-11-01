"""Ariile protejate în care cade o zonă: situri Natura 2000, parcuri, rezervații (din data/arii_ro.geojson, făcut de static_arii).

Doar informație pentru cine citește: culoarea și nivelul de încredere nu se schimbă după asta.

python -m pipeline.arii    pune ariile la toate zonele din docs/data/alerts.json și reface textele
"""
import json
import time

from . import config as C

# de la regimul cel mai strict la cel mai larg; ordinea în care le arătăm
ORDER = ["rezervație științifică", "parc național", "rezervația biosferei", "rezervație naturală", "monument al naturii",
         "parc natural", "geoparc", "sit Natura 2000", "sit Natura 2000 pentru păsări", "arie protejată națională"]


class Arii:
    def __init__(self, path=None):
        self.items, self.tree = [], None
        path = path or (C.DATA / "arii_ro.geojson")
        if not path.exists():
            return
        from shapely.geometry import shape
        from shapely.strtree import STRtree
        for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
            try:
                self.items.append((shape(f["geometry"]), f["properties"]))
            except Exception:
                continue
        self.tree = STRtree([g for g, _ in self.items])

    def find(self, geom):
        """Ariile atinse de zonă; „parte” = cât din zonă e în arie (0–1)."""
        if self.tree is None:
            return []
        out = []
        for i in self.tree.query(geom):
            g, p = self.items[int(i)]
            try:
                if not g.intersects(geom):
                    continue
                share = g.intersection(geom).area / geom.area if geom.area else 1.0
            except Exception:
                share = 1.0
            out.append(dict(p, parte=round(min(share, 1.0), 2)))
        out.sort(key=lambda p: (ORDER.index(p.get("tip")) if p.get("tip") in ORDER else 99, p.get("nume", "")))
        return out


def apply(alerts, path=None):
    """Scrie a["arii"] la fiecare zonă (sau îl scoate). Întoarce câte zone sunt în cel puțin o arie."""
    A = Arii(path)
    if A.tree is None:
        return 0
    from shapely.geometry import Point, shape
    n = 0
    for a in alerts:
        try:
            g = shape(a["geometry"]) if a.get("geometry") else Point(a["lon"], a["lat"])
        except Exception:
            g = Point(a["lon"], a["lat"])
        found = [{k: p[k] for k in ("cod", "nume", "tip", "parte") if p.get(k) not in (None, "")} for p in A.find(g)]
        if found:
            a["arii"] = found
            n += 1
        else:
            a.pop("arii", None)
    return n


def main():
    from . import writer
    p = C.DOCS / "data" / "alerts.json"
    D = json.loads(p.read_text(encoding="utf-8"))
    n = apply(D["alerts"])
    writer.apply(D["alerts"])
    p.write_text(json.dumps(D, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(time.strftime("%H:%M:%S"), f"Arii protejate: {n} din {len(D['alerts'])} zone", flush=True)


if __name__ == "__main__":
    main()
