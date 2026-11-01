"""Detectorul (cod, fără AI). Pentru o placă Sentinel-2:

  referință = cel mai mic dintre: verdele din lunile dinaintea ferestrei și verdele de acum un an
  pentru fiecare imagine nouă din fereastră: unde a dispărut verdele în pădure?
  păstrăm doar ce rămâne schimbat în imaginile următoare și nu e o schimbare a întregului deal
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import config as C
from .sat import item_date, log, read_grid, read_scene


def tile_grid(it):
    """Grila de 40 m a plăcii, în proiecția ei UTM."""
    from affine import Affine
    from .sat import open_at_res
    from .sat import fresh
    with open_at_res(fresh(it.assets["B04"].href), C.RES) as src:
        b, crs = src.bounds, src.crs
    w, h = round((b.right - b.left) / C.RES), round((b.top - b.bottom) / C.RES)
    return (crs, Affine(C.RES, 0, b.left, 0, -C.RES, b.top), w, h)


def county_raster(grid):
    """Indicele județului (1..42, 0 = în afara României) pentru fiecare pixel al grilei."""
    import json
    from affine import Affine
    from PIL import Image
    from rasterio.warp import Resampling, reproject
    meta = json.load(open(C.DATA / "counties.json", encoding="utf-8"))
    src = np.array(Image.open(C.DATA / "counties_grid.png"))
    crs, transform, w, h = grid
    dst = np.zeros((h, w), np.uint8)
    reproject(src.astype(np.uint8), dst,
              src_transform=Affine(meta["cell"], 0, meta["west"], 0, -meta["cell"], meta["north"]),
              src_crs="EPSG:4326", dst_transform=transform, dst_crs=crs, resampling=Resampling.nearest)
    return dst, meta["names"]


def forest_mask(cat, grid, lonlat_bbox, lossyear_path, year=None):
    """Pădure = copaci în ESA WorldCover 2021 (10 m) și fără pierdere Hansen în cei 5 ani dinaintea anului ferestrei
    (pentru 2026: 2021–2025). Anul contează la testul pe trecut: pierderile din anul testat nu se ascund."""
    from rasterio.enums import Resampling
    from .sat import search
    wc = np.zeros((grid[3], grid[2]), np.uint8)
    found = 0
    try:
        for it in search(cat, "esa-worldcover", lonlat_bbox, "2021-01-01", "2021-12-31"):
            asset = it.assets.get("map") or next(a for a in it.assets.values() if a.href.split("?")[0].endswith(".tif"))
            arr = read_grid(asset.href, grid, Resampling.mode, C.RES, 0, "uint8")
            wc = np.where(wc == 0, arr, wc)
            found += 1
    except Exception as exc:
        log("    WorldCover n-a mers:", repr(exc)[:120])
    if found and (wc > 0).mean() > 0.2:
        trees = wc == 10
    else:  # rezervă: coronamentul Hansen din 2000 (cel puțin 30%)
        tc_path = lossyear_path and next(iter(sorted(lossyear_path.parent.glob("*treecover2000*.tif"))), None)
        if tc_path is None:
            raise RuntimeError("nu am nici WorldCover, nici Hansen treecover pentru masca de pădure")
        log("    masca de pădure: Hansen treecover2000 (WorldCover lipsă)")
        trees = read_grid(str(tc_path), grid, Resampling.average, C.RES, None, "float32") >= 30
    if lossyear_path is not None:
        ly = read_grid(str(lossyear_path), grid, Resampling.max, C.RES, None, "uint8")
        y = (year or 2026) - 2000
        trees &= ~((ly >= y - 5) & (ly <= y - 1))
    return trees


def neighbor_drop(drop, ok, win=C.NEIGH_PX):
    """Cât a scăzut, în medie, verdele pădurii din jur (fereastră de win pixeli), doar pe pixelii `ok`."""
    from scipy import ndimage
    d = np.where(ok, drop, 0).astype("float32")
    n = ndimage.uniform_filter(ok.astype("float32"), win)
    return ndimage.uniform_filter(d, win) / np.maximum(n, 1e-6)


def composite(items, grid, pool, forest, label, keep=False):
    """Mediana NDVI și NBR din cele mai curate imagini (max C.MAX_REF_SCENES).

    keep=True: întoarce și imaginile una câte una (float16), ca să vedem pe fiecare zonă
    dacă schimbarea se vedea deja înainte de perioada analizată."""
    nd, nb, dates = [], [], []
    for it in sorted(items, key=lambda i: i.properties.get("eo:cloud_cover", 100)):
        if len(nd) >= C.MAX_REF_SCENES:
            break
        try:
            clear, ndvi, nbr = read_scene(it, grid, pool)
        except Exception as exc:
            log("    imagine sărită:", it.id, repr(exc)[:100])
            continue
        frac = float((clear & forest).sum()) / max(float(forest.sum()), 1.0)
        if frac < C.MIN_SCENE_CLEAR:
            continue
        nd.append(ndvi)
        nb.append(nbr)
        dates.append(item_date(it))
    if not nd:
        return (None, None, [], []) if keep else (None, None, [])
    with np.errstate(all="ignore"):
        med_nd, med_nb = np.nanmedian(np.stack(nd), 0), np.nanmedian(np.stack(nb), 0)
    if keep:
        scenes = sorted(zip(dates, [a.astype(np.float16) for a in nd], [b.astype(np.float16) for b in nb]), key=lambda t: t[0])
        return med_nd, med_nb, dates, scenes
    return med_nd, med_nb, dates


def detect_tile(cat, tile, items, d0, d1, lossyear_path, ro_check):
    """items = {"recent": [...], "lastyear": [...], "window": [...]} pentru această placă."""
    from scipy import ndimage

    if not items["window"]:
        return {"tile": tile, "status": "fără imagini noi în fereastră"}, [], []
    first = items["window"][0]
    grid = tile_grid(first)
    crs, transform, W, H = grid
    from rasterio.warp import transform_bounds
    lon0, lat0, lon1, lat1 = transform_bounds(crs, "EPSG:4326", transform.c, transform.f + H * transform.e,
                                              transform.c + W * transform.a, transform.f)
    info = {"tile": tile, "bbox": [round(lon0, 3), round(lat0, 3), round(lon1, 3), round(lat1, 3)]}
    if not ro_check(lon0, lat0, lon1, lat1):
        info["status"] = "în afara României"
        return info, [], []

    county, names = county_raster(grid)
    forest = forest_mask(cat, grid, [lon0, lat0, lon1, lat1], lossyear_path, year=int(str(d1)[:4])) & (county > 0)
    n_forest = int(forest.sum())
    info["forest_ha"] = round(n_forest * C.PX_HA)
    if n_forest < 2000:
        info["status"] = "prea puțină pădure"
        return info, [], []
    # citim din imagini doar dreptunghiul în care e pădure (mult mai puțini megabytes)
    from affine import Affine
    rr, cc = np.where(forest.any(axis=1))[0], np.where(forest.any(axis=0))[0]
    r0, r1 = max(0, rr[0] - C.NEIGH_PX), min(H, rr[-1] + 1 + C.NEIGH_PX)
    c0, c1 = max(0, cc[0] - C.NEIGH_PX), min(W, cc[-1] + 1 + C.NEIGH_PX)
    transform = transform * Affine.translation(c0, r0)
    W, H = c1 - c0, r1 - r0
    grid = (crs, transform, W, H)
    forest, county = forest[r0:r1, c0:c1], county[r0:r1, c0:c1]

    pool = ThreadPoolExecutor(max_workers=6)
    try:
        r_nd, r_nb, r_dates, r_scenes = composite(items["recent"], grid, pool, forest, "recent", keep=True)
        y_nd, y_nb, y_dates = composite(items["lastyear"], grid, pool, forest, "lastyear")
        info["ref_recent"] = [d.isoformat() for d in r_dates]
        info["ref_lastyear"] = [d.isoformat() for d in y_dates]
        if r_nd is None and y_nd is None:
            info["status"] = "fără imagine de referință curată"
            return info, [], []
        ref_nd = np.fmin(r_nd, y_nd) if (r_nd is not None and y_nd is not None) else (r_nd if r_nd is not None else y_nd)
        ref_nb = np.fmin(r_nb, y_nb) if (r_nb is not None and y_nb is not None) else (r_nb if r_nb is not None else y_nb)
        # marginea pădurii (40 m) doar o notăm: acolo se amestecă des cu câmpuri, drumuri, pajiști
        edge = forest & ~ndimage.binary_erosion(forest, iterations=1)
        with np.errstate(invalid="ignore"):
            ref_ok = forest & (ref_nd > C.NDVI_REF_MIN) & (ref_nb > C.NBR_REF_MIN)
        # imaginile de referință, una câte una: unde arăta zona deja schimbată, înainte de perioada analizată
        ref_scenes = []
        for day, s_nd, s_nb in r_scenes:
            s_nd, s_nb = s_nd.astype(np.float32), s_nb.astype(np.float32)
            with np.errstate(invalid="ignore"):
                s_ok = ref_ok & ~np.isnan(s_nd) & ~np.isnan(s_nb)
                s_chg = (s_ok & ((ref_nd - s_nd) > C.NDVI_DROP) & ((ref_nb - s_nb) > C.NBR_DROP)
                         & (s_nd < C.NDVI_NOW_MAX) & (s_nb < C.NBR_NOW_MAX))
            ref_scenes.append((day, s_ok, s_chg))
        del r_scenes

        # urmărim fiecare pixel de la o imagine la alta
        first_day = np.full((H, W), -1, np.int16)     # ziua (față de d0) în care s-a văzut prima dată schimbat
        n_change = np.zeros((H, W), np.uint8)
        n_clear_after = np.zeros((H, W), np.uint8)
        neigh_first = np.zeros((H, W), np.float32)    # cât a scăzut pădurea din jur în acea zi
        feat = {k: np.full((H, W), np.nan, np.float32) for k in ("nd", "nb", "adj_nd", "adj_nb", "blue", "red")}
        scenes = []                                   # (data, clar, schimbat) pentru calculul datelor pe zonă
        used, skipped = [], []
        for it in sorted(items["window"], key=item_date):
            day = item_date(it)
            try:
                clear, ndvi, nbr, blue, red = read_scene(it, grid, pool, full=True)
            except Exception as exc:
                log("    imagine sărită:", it.id, repr(exc)[:100])
                continue
            ok = clear & ref_ok
            if ok.sum() < C.MIN_SCENE_CLEAR * n_forest:
                skipped.append((day.isoformat(), "nori"))
                continue
            with np.errstate(invalid="ignore"):
                drop = ref_nd - ndvi
                drop_nb = ref_nb - nbr
                # 1. candidații: pixeli care arată ca sol gol sau ars, nu ca frunze de toamnă
                chg0 = (ok & (drop > C.NDVI_DROP) & (drop_nb > C.NBR_DROP)
                        & (ndvi < C.NDVI_NOW_MAX) & (nbr < C.NBR_NOW_MAX))
                # 2. cât s-a schimbat restul pădurii din jur (toamnă, ceață) se scade din schimbarea fiecărui candidat
                base = ok & ~chg0
                loc_nd = np.maximum(neighbor_drop(drop, base), 0)
                loc_nb = np.maximum(neighbor_drop(drop_nb, base), 0)
                chg = chg0 & ((drop - loc_nd) > C.NDVI_DROP) & ((drop_nb - loc_nb) > C.NBR_DROP)
            frac = float(chg.sum()) / max(float(ok.sum()), 1.0)
            if frac > C.SCENE_MAX_CHANGED:
                skipped.append((day.isoformat(), f"schimbare pe {round(100 * frac, 1)}% din pădure (ceață sau toamnă)"))
                continue
            nd_map = loc_nd
            k = (day - d0).days
            new = chg & (first_day < 0)
            first_day[new] = k
            neigh_first[new] = nd_map[new]
            for key, arr in (("nd", ndvi), ("nb", nbr), ("adj_nd", drop - loc_nd), ("adj_nb", drop_nb - loc_nb),
                             ("blue", blue), ("red", red)):
                feat[key][new] = arr[new]
            seen_after = ok & (first_day >= 0)
            n_clear_after[seen_after] += 1
            n_change[chg & (first_day >= 0)] += 1
            scenes.append((day, ok, chg))
            used.append(day.isoformat())
        info["window_scenes"] = used
        info["skipped"] = skipped
    finally:
        pool.shutdown(wait=True)

    with np.errstate(invalid="ignore", divide="ignore"):
        persist = n_change / np.maximum(n_clear_after, 1)
    cand = (first_day >= 0) & (persist >= C.PERSIST_MIN)
    lab, n = ndimage.label(cand, structure=np.ones((3, 3)))
    patches, rejected = [], []
    if n == 0:
        info["status"] = "ok"
        info["patches"] = 0
        return info, patches, rejected
    idx = np.arange(1, n + 1)
    sizes = ndimage.sum(cand, lab, idx) * C.PX_HA
    slices = ndimage.find_objects(lab)
    from pyproj import Transformer
    to_ll = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    for k in idx[sizes >= C.MIN_HA]:
        s = slices[k - 1]
        m = lab[s] == k
        fd = first_day[s][m]
        neigh = float(np.median(neigh_first[s][m]))
        # pentru fiecare imagine clară: ce parte din zonă apare schimbată
        obs = []
        for day, ok, chg in scenes:
            okm, chm = ok[s][m], chg[s][m]
            if okm.mean() >= 0.5:
                obs.append((day, float(chm[okm].mean())))
        # aceeași întrebare pe imaginile de referință (dinaintea perioadei), ca să știm de când e intactă zona
        obs_ref = []
        for day, ok, chg in ref_scenes:
            okm, chm = ok[s][m], chg[s][m]
            if okm.mean() >= 0.5:
                obs_ref.append((day, float(chm[okm].mean())))
        first_seen = next((d for d, f in obs if f >= 0.3), d0 + dt.timedelta(days=int(np.median(fd))))
        before = next((d for d, f in reversed(obs_ref + obs) if d < first_seen and f < 0.1), None)
        # schimbată deja în ultima imagine de referință curată și nevăzută intactă de atunci: e mai veche
        early = obs_ref[-1][0] if obs_ref and obs_ref[-1][1] >= 0.5 else None
        if early and before and before > early:
            early = None
        changed_days = {d for d, f in obs if f >= 0.5}
        after = max(changed_days) if changed_days else None
        n_dates = len(changed_days)
        if before is None and r_dates:
            before = max(r_dates)
        cy, cx = ndimage.center_of_mass(m)
        x, y = transform * (s[1].start + cx + 0.5, s[0].start + cy + 0.5)
        lon, lat = to_ll.transform(x, y)
        cnt = np.bincount(county[s][m].ravel(), minlength=len(names) + 1)
        cnt[0] = 0
        p = {
            "tile": tile,
            "ha": round(float(sizes[k - 1]), 1),
            "lat": round(lat, 5), "lon": round(lon, 5),
            "county": names[int(cnt.argmax()) - 1] if cnt.max() > 0 else None,
            "first_seen": first_seen.isoformat(),
            "before_date": before.isoformat() if before else None,
            "after_date": (after or first_seen).isoformat(),
            "n_dates": n_dates,
            "confirmed": n_dates >= C.CONFIRM_DATES,
            "ndvi_ref": round(float(np.nanmean(ref_nd[s][m])), 2),
            "nbr_ref": round(float(np.nanmean(ref_nb[s][m])), 2),
            "neigh_drop": round(neigh, 2),
            "persist": round(float(np.mean(persist[s][m])), 2),
            "f": {k: round(float(np.nanmean(v[s][m])), 3) for k, v in feat.items()},
            "edge_frac": round(float(edge[s][m].mean()), 2),
            "geometry": polygon(m, s, transform, to_ll),
        }
        p["bbox"] = bbox_of(p["geometry"])
        if early:
            p["early"] = early.isoformat()
        if neigh > C.NEIGH_MAX:
            p["motiv"] = "pădurea din jur a pierdut și ea verde (toamnă sau ceață)"
            rejected.append(p)
        elif early:
            p["motiv"] = f"se vedea deja schimbată pe {early.isoformat()}, înainte de perioada analizată"
            rejected.append(p)
        else:
            patches.append(p)
    info["status"] = "ok"
    info["patches"] = len(patches)
    info["rejected"] = len(rejected)
    return info, patches, rejected


def polygon(mask, s, transform, to_ll):
    """Conturul zonei, în grade, simplificat."""
    from rasterio.features import shapes
    from shapely.geometry import mapping, shape
    from shapely.ops import transform as shp_transform, unary_union
    t = transform * transform.translation(s[1].start, s[0].start)
    polys = [shape(g) for g, v in shapes(mask.astype("uint8"), mask=mask, transform=t) if v == 1]
    geom = unary_union(polys)
    geom = shp_transform(lambda x, y, z=None: to_ll.transform(x, y), geom)
    geom = geom.simplify(0.00015, preserve_topology=True)
    g = mapping(geom)
    return round_coords(g)


def round_coords(g, nd=5):
    def r(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def bbox_of(g):
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for x in c:
                walk(x)
    walk(g["coordinates"])
    return [min(xs), min(ys), max(xs), max(ys)]
