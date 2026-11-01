"""Imaginile înainte/după (10 m, culori naturale) pentru fiecare zonă găsită."""
import datetime as dt
import math
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from . import config as C
from .sat import chip_size, item_date, log, read_chip


def chip_bbox(p):
    lat = p["lat"]
    dlat = C.THUMB_PAD_M / 111320.0
    dlon = dlat / max(math.cos(math.radians(lat)), 0.2)
    x0, y0, x1, y1 = p["bbox"]
    # cel puțin ~900 m pe latură, ca să se vadă și pădurea din jur
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half_lat = max((y1 - y0) / 2 + dlat, 450 / 111320.0)
    half_lon = max((x1 - x0) / 2 + dlon, half_lat / max(math.cos(math.radians(lat)), 0.2))
    return [cx - half_lon, cy - half_lat, cx + half_lon, cy + half_lat]


def best_chip(candidates, bbox, size, min_clear=0.8):
    """Prima imagine din listă care e destul de curată peste zonă."""
    for it in candidates:
        try:
            rgb, clear = read_chip(it, bbox, size)
        except Exception as exc:
            log("    imagine mică sărită:", it.id, repr(exc)[:80])
            continue
        if clear >= min_clear:
            return rgb, item_date(it)
    return None, None


def make_thumbs(p, items, out_dir, name):
    """p = zona; items = toate imaginile plăcii. Scrie {name}_b.webp și {name}_a.webp."""
    bbox = chip_bbox(p)
    size = chip_size(bbox, p["lat"])
    first_seen = dt.date.fromisoformat(p["first_seen"])
    before_d = dt.date.fromisoformat(p["before_date"]) if p.get("before_date") else None
    after_d = dt.date.fromisoformat(p["after_date"])
    pool = sorted(items, key=item_date)
    # înainte: imaginea din ziua „ultima dată intactă", apoi cele mai vechi, de la cea mai nouă.
    # Niciodată una dintre „ultima dată intactă" și „prima dată schimbată": acolo zona poate fi deja tăiată.
    # n-am văzut-o intactă de curând (iarna nu ne uităm): poza „înainte” vine din vara în care era pădure deasă
    last_ok = before_d or (dt.date(p["vara"], 9, 1) if p.get("vara") else first_seen - dt.timedelta(days=1))
    before_c = sorted([i for i in pool if item_date(i) <= last_ok],
                      key=lambda i: (item_date(i) != before_d, -item_date(i).toordinal()))
    # după: imaginea în care se vede schimbarea, apoi celelalte de după, de la cea mai nouă
    after_c = sorted([i for i in pool if item_date(i) >= first_seen],
                     key=lambda i: (item_date(i) != after_d, -item_date(i).toordinal()))
    # dacă cele mai noi sunt toate cu nori sau zăpadă, încercăm și cele mai senine dintre cele mai vechi (vara)
    before_c = before_c[:6] + sorted(before_c[6:], key=lambda i: i.properties.get("eo:cloud_cover", 100))[:3]
    res = {}
    for key, cands in (("b", before_c), ("a", after_c[:8])):
        rgb, d = best_chip(cands, bbox, size)
        if rgb is None and cands:
            rgb, d = best_chip(cands[:3], bbox, size, min_clear=0.4)
        if rgb is None:
            res[key] = None
            continue
        f = f"{name}_{key}.webp"
        Image.fromarray(rgb, "RGB").save(out_dir / f, "WEBP", quality=86, method=6)
        res[key] = {"file": f, "date": d.isoformat()}
    res["bbox"] = [round(x, 5) for x in bbox]
    return res


def thumbs_for(patches, items_by_tile, out_dir, workers=6):
    out_dir.mkdir(parents=True, exist_ok=True)

    def one(p):
        try:
            return make_thumbs(p, items_by_tile[p["tile"]], out_dir, p["key"])
        except Exception as exc:
            log("    imagini sărite pentru", p["key"], repr(exc)[:100])
            return {"b": None, "a": None}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for p, r in zip(patches, ex.map(one, patches)):
            p["img_before"], p["img_after"], p["chip_bbox"] = r.get("b"), r.get("a"), r.get("bbox")
