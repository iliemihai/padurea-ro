"""Comuna, orașul sau municipiul în care cade o zonă, din limitele oficiale ale unităților administrativ-teritoriale (UAT).

Sursa: limitele UAT de la geo-spatial.org (versiunea 2019/12/19), simplificate în github.com/akaleeroy/romania-uat,
adunate într-un singur fișier: data/uat_ro.geojson. Pentru fiecare UAT păstrăm codul SIRUTA, numele, tipul și județul.
Limitele sunt simplificate, deci lângă o graniță între două comune răspunsul poate fi vecinul; atunci îl marcăm „aproape”.
"""
import json
import re

from . import config as C

RO_FIX = str.maketrans({"ş": "ș", "Ş": "Ș", "ţ": "ț", "Ţ": "Ț"})
INNER_I = re.compile(r"(?<=\w)î(?=\w)")
INNER_I_UP = re.compile(r"(?<=\w)Î(?=\w)")


def ro(s):
    """Numele din GeoNames vin cu sedilă (ş, ţ); în română corect e virgula de dedesubt (ș, ț)."""
    return s.translate(RO_FIX) if isinstance(s, str) else s


def modern(s):
    """Ortografia de azi: „â” în interiorul cuvintelor („Vînjuleț” → „Vânjuleț”); „î” rămâne la început și la sfârșit.
    Limitele UAT de la geo-spatial.org au numele scrise cu „î” peste tot; GeoNames și site-ul folosesc „â”."""
    if not isinstance(s, str):
        return s
    return INNER_I_UP.sub("Â", INNER_I.sub("â", ro(s)))


class UAT:
    def __init__(self, path=None):
        self.items, self.tree = [], None
        path = path or (C.DATA / "uat_ro.geojson")
        if not path.exists():
            return
        from shapely.geometry import shape
        from shapely.strtree import STRtree
        fc = json.loads(path.read_text(encoding="utf-8"))
        self.items = [(shape(f["geometry"]), dict(f["properties"], nume=modern(f["properties"]["nume"]),
                                                   judet=modern(f["properties"].get("judet"))))
                      for f in fc["features"]]
        self.tree = STRtree([g for g, _ in self.items])

    def find(self, lon, lat):
        """UAT-ul care conține punctul; dacă niciunul (graniță simplificată), cel mai apropiat sub ~1 km, marcat „aproape”."""
        if self.tree is None:
            return None
        from shapely.geometry import Point
        p = Point(lon, lat)
        for i in self.tree.query(p):
            g, props = self.items[int(i)]
            if g.covers(p):
                return dict(props)
        i = self.tree.nearest(p)
        g, props = self.items[int(i)]
        if g.distance(p) < 0.012:
            return dict(props, aproape=True)
        return None


def apply(alerts, path=None):
    """Pune la fiecare zonă câmpul „uat” (siruta, nume, tip, județ). Întoarce câte zone au primit unul."""
    u = UAT(path)
    n = 0
    for a in alerts:
        r = u.find(a["lon"], a["lat"])
        if r:
            a["uat"] = r
            n += 1
        if a.get("localitate"):
            a["localitate"] = ro(a["localitate"])
    return n
