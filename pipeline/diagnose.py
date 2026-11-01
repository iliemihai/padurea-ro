"""Diagnosticul testului pe trecut: de ce ratăm petele Hansen și ce sunt zonele care nu se potrivesc cu ele.

python -m pipeline.diagnose --year 2025 --docs ev/score/docs --raw ev/raw --out diag

1. plăcile: pe fiecare fereastră, câte imagini s-au folosit și de ce s-au sărit celelalte
2. pâlnia: fiecare pată Hansen de cel puțin 0,5 ha e găsită, respinsă de un filtru (care) sau nevăzută deloc
3. un eșantion de locuri (pete ratate și găsite, zone care se potrivesc și care nu): seria de timp Sentinel-2,
   zona și pădurea din jur, de la START la END, plus o poză înainte și una după, puse pe planșe
Nu atinge site-ul; scrie doar în --out.
"""
import argparse
import datetime as dt
import json
import math
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import config as C
from . import evaluate as E
from . import romania
from .sat import log, read_chip, read_grid, search, s2_offset

START, END = "2024-06-01", "2026-01-31"
REASONS = [("vecini", "pădurea din jur"), ("veche", "se vedea deja"), ("ir", "în infraroșu"),
           ("contrast", "nu iese în evidență"), ("margine", "fâșie pe marginea")]


def reason_code(m):
    return next((k for k, s in REASONS if s in (m or "")), "altul")


# ---------- 1. plăcile ----------
def tiles_summary(raw):
    out = []
    for f in sorted(Path(raw).glob("*/group_*.json")):
        g = json.loads(f.read_text())
        for t in g["tiles"]:
            sk = {}
            for _, why in t.get("skipped") or []:
                k = "nori" if why == "nori" else "schimbare_mare"
                sk[k] = sk.get(k, 0) + 1
            out.append({"d1": g["d1"], "tile": t["tile"], "status": t.get("status"), "forest_ha": t.get("forest_ha"),
                        "used": len(t.get("window_scenes") or []), "skipped": sk,
                        "ref_recent": len(t.get("ref_recent") or []), "ref_lastyear": len(t.get("ref_lastyear") or []),
                        "patches": t.get("patches"), "rejected": t.get("rejected")})
    return out


def rejected_candidates(raw):
    out = []
    for f in sorted(Path(raw).glob("*/group_*.json")):
        g = json.loads(f.read_text())
        for p in g["rejected"]:
            out.append({"d1": g["d1"], "motiv": reason_code(p.get("motiv")), "geometry": p["geometry"], "ha": p["ha"],
                        "first_seen": p["first_seen"], "n_dates": p.get("n_dates"), "f": p.get("f"),
                        "neigh_drop": p.get("neigh_drop"), "edge_frac": p.get("edge_frac")})
    return out


# ---------- 2. pâlnia ----------
def hansen_patches(zones, rej, src, year, band=0.5):
    """Petele de pierdere Hansen din anul testat (≥0,5 ha): mărime, contur, cel mai bun nivel care le atinge
    și ce filtre au respins candidați peste ele."""
    from rasterio.features import geometry_mask, rasterize, shapes
    from scipy import ndimage
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    ro = romania.outline()
    W, S, Ee, N = ro.bounds
    yv = year - 2000
    zs = [(shape(a["geometry"]).buffer(E.PX * 1.2), E.CODE.get(a.get("incredere"), 4)) for a in zones]
    zs.sort(key=lambda t: -t[1])
    rs = {k: [shape(r["geometry"]).buffer(E.PX * 1.2) for r in rej if r["motiv"] == k] for k, _ in REASONS}
    out = []
    lat = S
    while lat < N:
        top = min(lat + band, N)
        w = E.window(src, W, lat, Ee, top)
        arr = src.read(1, window=w, boundless=True, fill_value=0)
        tr = src.window_transform(w)
        loss = (arr == yv) & ~geometry_mask([mapping(ro)], out_shape=arr.shape, transform=tr)
        if loss.any():
            lab, nlab = ndimage.label(loss, structure=np.ones((3, 3), bool))
            idx = np.arange(1, nlab + 1)
            px_ha = (E.PX * 111320 * math.cos(math.radians((lat + top) / 2))) * (E.PX * 110574) / 1e4
            sizes = ndimage.sum(loss, lab, index=idx) * px_ha

            def burn(pairs):
                here = [(mapping(g), v) for g, v in pairs if g.bounds[3] >= lat and g.bounds[1] <= top]
                return rasterize(here, out_shape=arr.shape, transform=tr, fill=0, dtype="uint8") if here else None

            ours = burn(zs)
            best = (ndimage.minimum(np.where(ours == 0, 99, ours).astype(np.uint8), lab, index=idx)
                    if ours is not None else np.full(nlab, 99))
            flags = {}
            for k, _ in REASONS:
                r = burn([(g, 1) for g in rs[k]])
                flags[k] = ndimage.maximum(r, lab, index=idx) if r is not None else np.zeros(nlab)
            slices = ndimage.find_objects(lab)
            for i in np.where(sizes >= 0.5)[0]:
                s = slices[i]
                m = lab[s] == i + 1
                t2 = tr * tr.translation(s[1].start, s[0].start)
                poly = unary_union([shape(g) for g, v in shapes(m.astype("uint8"), mask=m, transform=t2) if v == 1])
                c = poly.centroid
                out.append({"ha": round(float(sizes[i]), 2), "lat": round(c.y, 5), "lon": round(c.x, 5),
                            "best": int(best[i]), "rej": [k for k, _ in REASONS if flags[k][i] > 0],
                            "geometry": mapping(poly.simplify(E.PX / 2))})
            del lab
        lat = top
    return out


def funnel(patches):
    res = {}
    for name, lo, hi in E.SIZES:
        ps = [p for p in patches if lo <= p["ha"] < hi]
        d = {"pete": len(ps)}
        for lv in E.LEVELS:
            d[f"gasite_pana_la_{lv}"] = sum(p["best"] <= E.CODE[lv] for p in ps)
        miss = [p for p in ps if p["best"] > 4]
        d["ratate"] = len(miss)
        d["ratate_dar_respinse_de"] = {k: sum(k in p["rej"] for p in miss) for k, _ in REASONS}
        d["ratate_nevazute_deloc"] = sum(not p["rej"] for p in miss)
        res[name] = d
    return res


# ---------- 3. seriile de timp ----------
def s2_items(cat):
    """Toate imaginile Sentinel-2 peste România din perioadă, lună cu lună."""
    items, d = [], dt.date.fromisoformat(START)
    end = dt.date.fromisoformat(END)
    while d <= end:
        nxt = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
        b = min(nxt - dt.timedelta(days=1), end)
        got = search(cat, "sentinel-2-l2a", C.RO_BBOX, d.isoformat(), b.isoformat(), cloud=90)
        log(f"  imagini {d} – {b}: {len(got)}")
        items += got
        d = nxt
    return items


def utm_grid(crs, geom_ll, pad_m=600, res=20.0):
    from affine import Affine
    from pyproj import Transformer
    from shapely.ops import transform as stf
    to = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    g = stf(lambda x, y, z=None: to.transform(x, y), geom_ll)
    x0, y0, x1, y1 = g.bounds
    x0, y0 = math.floor((x0 - pad_m) / res) * res, math.floor((y0 - pad_m) / res) * res
    x1, y1 = math.ceil((x1 + pad_m) / res) * res, math.ceil((y1 + pad_m) / res) * res
    w, h = int((x1 - x0) / res), int((y1 - y0) / res)
    return (crs, Affine(res, 0, x0, 0, -res, y1), w, h), g


def masks(grid, g_utm, wc_items):
    from rasterio.enums import Resampling
    from rasterio.features import rasterize
    from scipy import ndimage
    from shapely.geometry import mapping
    crs, tr, w, h = grid
    patch = rasterize([(mapping(g_utm), 1)], out_shape=(h, w), transform=tr, fill=0, dtype="uint8").astype(bool)
    if not patch.any():
        patch = rasterize([(mapping(g_utm), 1)], out_shape=(h, w), transform=tr, fill=0, dtype="uint8",
                          all_touched=True).astype(bool)
    wc = np.zeros((h, w), np.uint8)
    for it in wc_items:
        try:
            arr = read_grid(it.assets["map"].href, grid, Resampling.mode, 20, 0, "uint8")
            wc = np.where(wc == 0, arr, wc)
        except Exception as exc:
            log("    WorldCover:", repr(exc)[:100])
    forest = wc == 10
    near = ndimage.binary_dilation(patch, iterations=3)
    far = ndimage.binary_dilation(patch, iterations=20)
    ring = forest & far & ~near
    return patch, ring, float(forest[patch].mean()) if patch.any() else 0.0


def scene_stats(it, grid, patch, ring):
    from rasterio.enums import Resampling
    from scipy import ndimage
    b = {}
    for k, r in (("SCL", Resampling.nearest), ("B02", Resampling.average), ("B04", Resampling.average),
                 ("B08", Resampling.average), ("B11", Resampling.average), ("B12", Resampling.average)):
        b[k] = read_grid(it.assets[k].href, grid, r, 20, None if k == "SCL" else 0)
    scl = b["SCL"]
    bad = np.isin(scl, C.SCL_BAD)
    if bad.any():
        bad = ndimage.binary_dilation(bad, iterations=2)
    off = s2_offset(it)
    blue, red, nir, sw1, sw2 = [(b[k] - off) / 1e4 for k in ("B02", "B04", "B08", "B11", "B12")]
    valid = (b["B04"] > off) & (b["B08"] > off) & (b["B12"] > off)
    clear = np.isin(scl, C.SCL_OK) & ~bad & valid
    snow = scl == 11
    with np.errstate(all="ignore"):
        idx = {"ndvi": (nir - red) / (nir + red), "nbr": (nir - sw2) / (nir + sw2), "ndmi": (nir - sw1) / (nir + sw1),
               "red": red, "sw1": sw1, "sw2": sw2, "blue": blue}

    def stats(m):
        n = int(m.sum())
        if not n:
            return None
        c = clear & m
        row = {"clear": round(float(c.sum()) / n, 2), "snow": round(float((snow & m).sum()) / n, 2)}
        if c.sum() >= max(3, 0.3 * n):
            row.update({k: round(float(np.nanmedian(v[c])), 3) for k, v in idx.items()})
        return row
    return {"date": it.datetime.date().isoformat(), "tile": it.properties.get("s2:mgrs_tile"),
            "cloud": round(float(it.properties.get("eo:cloud_cover", -1)), 1), "p": stats(patch), "r": stats(ring)}


def series_for(loc, items, wc_items, pool):
    import rasterio
    from shapely.geometry import box, shape
    g = shape(loc["geometry"])
    here = [it for it in items if shape(it.geometry).contains(g.buffer(0.004))]
    if not here:
        here = [it for it in items if shape(it.geometry).intersects(g)]
    if not here:
        return None
    tiles = {}
    for it in here:
        tiles[it.properties.get("s2:mgrs_tile")] = tiles.get(it.properties.get("s2:mgrs_tile"), 0) + 1
    tile = max(tiles, key=tiles.get)
    here = sorted([it for it in here if it.properties.get("s2:mgrs_tile") == tile], key=lambda it: it.datetime)
    from .sat import fresh
    with rasterio.open(fresh(here[0].assets["B12"].href)) as src:
        crs = src.crs
    grid, g_utm = utm_grid(crs, g)
    gb = g.bounds
    wc_here = [it for it in wc_items if box(*it.bbox).intersects(box(*gb))]
    patch, ring, forest_frac = masks(grid, g_utm, wc_here)
    rows = list(pool.map(lambda it: _safe(scene_stats, it, grid, patch, ring), here))
    rows = [r for r in rows if r]
    loc = dict(loc, tile=tile, forest_frac=round(forest_frac, 2), series=rows)
    loc["_items"] = {it.datetime.date().isoformat(): it for it in here}
    return loc


def _safe(f, *a):
    try:
        return f(*a)
    except Exception as exc:
        log("    sărit:", repr(exc)[:120])
        return None


# ---------- 4. pozele ----------
def pick_pair(loc):
    """Cea mai curată imagine de dinainte și cea mai curată de după (fără nori și fără zăpadă pe zonă)."""
    ok = [r for r in loc["series"] if r["p"] and r["p"]["clear"] >= 0.97 and r["p"]["snow"] == 0
          and r["r"] and r["r"]["clear"] >= 0.8]
    if loc["kind"].startswith("hansen"):
        before = [r for r in ok if "2024-06-01" <= r["date"] <= "2024-09-30"]
        after = [r for r in ok if "2025-06-01" <= r["date"] <= "2025-09-30"] or [r for r in ok if r["date"] >= "2025-10-01"]
        later = [r for r in ok if r["date"] >= "2025-11-01"]
    else:
        fs = loc["first_seen"]
        lo = (dt.date.fromisoformat(fs) - dt.timedelta(days=150)).isoformat()
        hi = (dt.date.fromisoformat(fs) + dt.timedelta(days=100)).isoformat()
        before = [r for r in ok if lo <= r["date"] < (loc.get("before_date") or fs)]
        after = [r for r in ok if fs <= r["date"] <= hi]
        later = [r for r in ok if r["date"] > hi]
    def best(rs):
        return min(rs, key=lambda r: (r["cloud"], r["date"])) if rs else None
    b = best(before[-6:]) if before else None
    a = best(after[:6]) if after else None
    lt = best(later[:6]) if later else None
    return b, a, lt


def thumbs(loc, size=150):
    from PIL import Image
    from shapely.geometry import shape
    g = shape(loc["geometry"])
    x0, y0, x1, y1 = g.bounds
    lat = (y0 + y1) / 2
    pad = 300 / 111320.0
    cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, (y1 - y0) / math.cos(math.radians(lat))) / 2 + pad
    bb = (cx - r, cy - r * math.cos(math.radians(lat)), cx + r, cy + r * math.cos(math.radians(lat)))
    out = []
    for row in pick_pair(loc):
        if row is None:
            out.append((None, None))
            continue
        it = loc["_items"][row["date"]]
        try:
            rgb, _ = read_chip(it, bb, (size, size))
            out.append((Image.fromarray(rgb), row["date"]))
        except Exception as exc:
            log("    poză sărită:", repr(exc)[:100])
            out.append((None, row["date"]))
    return out, bb


def sheet(locs, path, size=150):
    from PIL import Image, ImageDraw
    rows = []
    for loc in locs:
        try:
            ims, bb = thumbs(loc, size)
        except Exception as exc:
            log("  planșă sărită:", repr(exc)[:100])
            continue
        rows.append((loc, ims, bb))
    if not rows:
        return
    W, Hr = 230 + 3 * (size + 6), size + 8
    canvas = Image.new("RGB", (W, Hr * len(rows)), (250, 250, 248))
    d = ImageDraw.Draw(canvas)
    for i, (loc, ims, bb) in enumerate(rows):
        y = i * Hr + 4
        lines = [f"#{loc['n']} {loc['kind']}", f"{loc['ha']} ha {loc.get('nivel') or ''}".strip(),
                 f"{loc['lat']:.4f}, {loc['lon']:.4f}", f"padure WC: {loc.get('forest_frac')}"]
        if loc.get("first_seen"):
            lines.append(f"vazuta {loc['first_seen']}")
        if loc.get("ai"):
            lines.append(f"AI: {loc['ai']}")
        if loc.get("frac") is not None:
            lines.append(f"Hansen: {loc['frac']}")
        if loc.get("rej"):
            lines.append("respinsa: " + ",".join(loc["rej"]))
        for j, t in enumerate(lines):
            d.text((6, y + 2 + 13 * j), t, fill=(30, 30, 30))
        for j, (im, date) in enumerate(ims):
            x = 230 + j * (size + 6)
            if im is not None:
                canvas.paste(im, (x, y))
                # conturul zonei
                from shapely.geometry import shape
                g = shape(loc["geometry"])
                gx0, gy0, gx1, gy1 = bb
                for poly in getattr(g, "geoms", [g]):
                    pts = [((px - gx0) / (gx1 - gx0) * size + x, (gy1 - py) / (gy1 - gy0) * size + y)
                           for px, py in poly.exterior.coords]
                    d.line(pts, fill=(255, 220, 0), width=1)
            d.text((x + 3, y + size - 14), date or "-", fill=(255, 255, 255) if im is not None else (120, 120, 120))
    canvas.save(path, quality=85)
    log(f"  planșa {path}: {len(rows)} rânduri")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--docs", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", default="diag")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    import rasterio
    from .run_tiles import hansen_lossyear
    from .sat import client

    tiles = tiles_summary(a.raw)
    rej = rejected_candidates(a.raw)
    zones = E.load_zones(Path(a.docs), a.year)
    log(f"{len(tiles)} plăci-ferestre, {len(rej)} candidați respinși, {len(zones)} zone publicate")
    src = rasterio.open(hansen_lossyear())
    prec = {r["id"]: r for r in E.precision(zones, src, a.year)}
    patches = hansen_patches(zones, rej, src, a.year)
    fun = funnel(patches)
    log(json.dumps(fun, ensure_ascii=False))

    # eșantionul
    rnd = random.Random(a.seed)
    def take(xs, k):
        xs = list(xs)
        return rnd.sample(xs, min(k, len(xs)))
    miss = [p for p in patches if p["best"] > 4]
    hit = [p for p in patches if p["best"] <= 2]
    sample = []
    for kind, ps in (("hansen ratata >15ha", take([p for p in miss if p["ha"] >= 15], 20)),
                     ("hansen ratata 5-15ha", take([p for p in miss if 5 <= p["ha"] < 15], 20)),
                     ("hansen ratata 1-5ha", take([p for p in miss if 1 <= p["ha"] < 5], 15)),
                     ("hansen gasita", take([p for p in hit if p["ha"] >= 3], 12))):
        sample += [dict(p, kind=kind) for p in ps]
    zinfo = {z["id"]: z for z in zones}
    conf = [prec[z["id"]] for z in zones if z["id"] in prec and z.get("incredere") in ("ridicată", "medie")]
    fp = sorted([r for r in conf if r["frac"] < E.TRUE_FRAC], key=lambda r: -(r["ha"] or 0))
    tp = [r for r in conf if r["frac"] >= 0.5 and r["nivel"] == "ridicată"]
    dc = [prec[z["id"]] for z in zones if z["id"] in prec and z.get("incredere") == "de confirmat"]
    lo = [prec[z["id"]] for z in zones if z["id"] in prec and z.get("incredere") == "scăzută"]
    for kind, rs in (("fals pozitiv mare", fp[:12]), ("fals pozitiv", take(fp[12:], 18)), ("adevarat", take(tp, 10)),
                     ("de confirmat", take(dc, 12)), ("scazuta", take(lo, 8))):
        for r in rs:
            z = zinfo[r["id"]]
            sample.append({"kind": kind, "id": z["id"], "ha": z["ha"], "lat": z["lat"], "lon": z["lon"],
                           "nivel": z.get("incredere"), "ai": (z.get("ai") or {}).get("categorie"), "frac": r["frac"],
                           "first_seen": z["first_seen"], "before_date": z.get("before_date"),
                           "after_date": z.get("after_date"), "n_dates": z.get("n_dates"), "tile": z.get("tile"),
                           "dovezi": z.get("dovezi"), "geometry": z["geometry"]})
    for i, s in enumerate(sample, 1):
        s["n"] = i
    log(f"Eșantion: {len(sample)} locuri")

    cat = client()
    items = s2_items(cat)
    wc_items = search(cat, "esa-worldcover", C.RO_BBOX, "2021-01-01", "2021-12-31")
    done = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        for s in sample:
            r = _safe(series_for, s, items, wc_items, pool)
            if r:
                done.append(r)
                log(f"  #{s['n']} {s['kind']}: {len(r['series'])} imagini, pădure {r['forest_frac']}")
    for kind_prefix, name in (("hansen ratata", "ratate"), ("hansen gasita", "gasite"), ("fals pozitiv", "fals_pozitive"),
                              ("adevarat", "adevarate"), ("de confirmat", "de_confirmat"), ("scazuta", "scazute")):
        sheet([d for d in done if d["kind"].startswith(kind_prefix)], out / f"plansa_{name}.jpg")
    for d in done:
        d.pop("_items", None)
    report = {"an": a.year, "placi": tiles, "palnie": fun, "esantion": done,
              "pete_hansen": [{k: p[k] for k in ("ha", "lat", "lon", "best", "rej")} for p in patches]}
    (out / f"diag_{a.year}.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    log("Gata")


if __name__ == "__main__":
    main()
