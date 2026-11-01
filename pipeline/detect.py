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
    found, failed = 0, 0
    try:
        items = search(cat, "esa-worldcover", lonlat_bbox, "2021-01-01", "2021-12-31")
    except Exception as exc:
        log("    WorldCover n-a mers:", repr(exc)[:120])
        items = []
    for it in items:
        try:
            asset = it.assets.get("map") or next(a for a in it.assets.values() if a.href.split("?")[0].endswith(".tif"))
            arr = read_grid(asset.href, grid, Resampling.mode, C.RES, 0, "uint8")
            wc = np.where(wc == 0, arr, wc)
            found += 1
        except Exception as exc:
            failed += 1
            log("    WorldCover, o bucată n-a mers:", repr(exc)[:120])
    tc_path = lossyear_path and next(iter(sorted(lossyear_path.parent.glob("*treecover2000*.tif"))), None)
    # o placă de pe coastă e mai mult mare (fără date în WorldCover): e în regulă, cât timp s-au citit toate bucățile
    if found and (not failed or tc_path is None):
        trees = wc == 10
    else:  # rezervă: coronamentul Hansen din 2000 (cel puțin 30%)
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


class SceneCache:
    """Imaginile de acum un an (NDVI, NBR; NaN unde nu e clar), citite o singură dată și ținute cât mai sunt de folos."""

    def __init__(self, grid, pool, forest, n_forest):
        self.grid, self.pool, self.forest, self.n = grid, pool, forest, max(float(n_forest), 1.0)
        self.d = {}

    def get(self, it):
        if it.id not in self.d:
            try:
                clear, nd, nb = read_scene(it, self.grid, self.pool)
            except Exception as exc:
                log("    imagine sărită:", it.id, repr(exc)[:100])
                self.d[it.id] = None
                return None
            ok = float((clear & self.forest).sum()) / self.n >= C.MIN_SCENE_CLEAR
            self.d[it.id] = (item_date(it), nd.astype(np.float16), nb.astype(np.float16)) if ok else None
        return self.d[it.id]

    def drop_before(self, day):
        for k, v in list(self.d.items()):
            if v is not None and v[0] < day:
                self.d[k] = None


class SeasonRef:
    """Referința de sezon: pentru o dată t, mediana imaginilor clare de acum un an din jurul lui t − 365 de zile.
    Calculată pe „ancore” la ANCHOR_DAYS zile, în ordinea datelor; golurile (nori, zăpadă) se umplu din ancora dinainte."""

    def __init__(self, items, cache, start, gate):
        self.items = items
        self.cache, self.start, self.gate = cache, start, gate
        self.refs, self.dates = {}, set()

    def anchor(self, day):
        k = round((day - self.start).days / C.ANCHOR_DAYS)
        return self.start + dt.timedelta(days=k * C.ANCHOR_DAYS)

    def get(self, day):
        a = self.anchor(day)
        if a not in self.refs:
            self.refs[a] = self._build(a)
        return self.refs[a]

    def _build(self, a):
        target = a - dt.timedelta(days=365)
        # întâi cele mai senine, iar dintre ele cele mai apropiate de ziua-țintă (primăvara și toamna contează zilele)
        cands = sorted([it for it in self.items if abs((item_date(it) - target).days) <= C.SEASON_PAD],
                       key=lambda it: (round(it.properties.get("eo:cloud_cover", 100) / 20),
                                       abs((item_date(it) - target).days)))
        nd, nb = [], []
        seen = np.zeros(self.gate.shape, bool)
        n_gate = max(int(self.gate.sum()), 1)
        for it in cands:
            r = self.cache.get(it)
            if r is None:
                continue
            nd.append(r[1].astype(np.float32))
            nb.append(r[2].astype(np.float32))
            seen |= ~np.isnan(nd[-1])
            self.dates.add(r[0])
            # cel puțin MAX_REF_SCENES imagini; mai multe (până la dublu) doar dacă norii lasă goluri în pădure
            if len(nd) >= C.MAX_REF_SCENES and (float((self.gate & ~seen).sum()) / n_gate < 0.02 or len(nd) >= 2 * C.MAX_REF_SCENES):
                break
        # imaginile mai vechi decât ce trebuie ancorei următoare nu mai folosesc la nimic
        self.cache.drop_before(target + dt.timedelta(days=C.ANCHOR_DAYS) - dt.timedelta(days=C.SEASON_PAD))
        prev = self.refs.get(a - dt.timedelta(days=C.ANCHOR_DAYS))
        if not nd:
            return prev
        with np.errstate(all="ignore"):
            r_nd, r_nb = np.nanmedian(np.stack(nd), 0), np.nanmedian(np.stack(nb), 0)
        del nd, nb
        if prev is not None:
            m = np.isnan(r_nd)
            r_nd[m] = prev[0][m]
            r_nb[m] = prev[1][m]
        return r_nd.astype(np.float16), r_nb.astype(np.float16)


def winter(day):
    """Iarna (C.WINTER): nu căutăm schimbări în imaginile de atunci."""
    md = day.strftime("%m-%d")
    a, b = C.WINTER
    return (md >= a or md <= b) if a > b else (a <= md <= b)


def change(ndvi, nbr, ref, ok):
    """Unde a dispărut pădurea în imaginea asta, față de referința de sezon și față de pădurea din jur.
    Doar unde referința are frunze (sau e de rășinoase). Întoarce (unde ne-am uitat, schimbat, scăderea NDVI,
    scăderea NBR, scăderea din jur NDVI, scăderea din jur NBR)."""
    b_nd, b_nb = ref
    with np.errstate(invalid="ignore"):
        ok = ok & ~np.isnan(b_nd) & ~np.isnan(b_nb) & (b_nd >= C.LEAFON_NDVI)
        drop = b_nd - ndvi
        drop_nb = b_nb - nbr
        # 1. candidații: pixeli care arată ca sol gol, lemn tăiat sau ars, nu ca pădurea de acum un an din aceeași perioadă
        chg0 = (ok & (drop > C.NDVI_DROP) & (drop_nb > C.NBR_DROP)
                & (ndvi < C.NDVI_NOW_MAX) & (nbr < C.NBR_NOW_MAX))
        # 2. cât s-a schimbat restul pădurii din jur (anul ăsta frunzele cad mai devreme, ceață) se scade
        base = ok & ~chg0
        loc_nd = np.maximum(neighbor_drop(drop, base), 0)
        loc_nb = np.maximum(neighbor_drop(drop_nb, base), 0)
        chg = chg0 & ((drop - loc_nd) > C.NDVI_DROP) & ((drop_nb - loc_nb) > C.NBR_DROP)
    return ok, chg, drop, drop_nb, loc_nd, loc_nb


def summer_range(d0):
    """Ultima vară încheiată înainte de începutul ferestrei."""
    y = d0.year if (d0.month, d0.day) > tuple(int(x) for x in C.SUMMER[1].split("-")) else d0.year - 1
    return dt.date.fromisoformat(f"{y}-{C.SUMMER[0]}"), dt.date.fromisoformat(f"{y}-{C.SUMMER[1]}")


def detect_tile(cat, tile, items, d0, d1, lossyear_path, ro_check):
    """items = {"window", "recent", "lastyear", "summer"} pentru această placă."""
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
        # pădure deasă și verde în ultima vară: doar acolo căutăm (unde nu s-a văzut deloc vara, avem încredere în hartă)
        s_nd, s_nb, s_dates = composite(items.get("summer") or [], grid, pool, forest, "summer")
        info["ref_summer"] = [d.isoformat() for d in s_dates]
        with np.errstate(invalid="ignore"):
            gate = forest.copy() if s_nd is None else (forest & ~(s_nd <= C.NDVI_REF_MIN) & ~(s_nb <= C.NBR_REF_MIN))
        n_gate = int(gate.sum())
        if n_gate < 1000:
            info["status"] = "prea puțină pădure deasă vara trecută"
            return info, [], []
        cache = SceneCache(grid, pool, gate, n_gate)
        season = SeasonRef(items["lastyear"], cache, d0 - dt.timedelta(days=C.RECENT_DAYS), gate)
        # marginea pădurii (40 m) doar o notăm: acolo se amestecă des cu câmpuri, drumuri, pajiști
        edge = forest & ~ndimage.binary_erosion(forest, iterations=1)

        # imaginile clare dinaintea ferestrei, de la cea mai nouă: era zona deja schimbată? când a fost văzută intactă?
        recent = []
        for it in sorted([i for i in items["recent"] if i.properties.get("eo:cloud_cover", 100) < 80
                          and not winter(item_date(i))], key=item_date, reverse=True):
            if len(recent) >= C.MAX_RECENT_SCENES:
                break
            try:
                clear, ndvi, nbr = read_scene(it, grid, pool)
            except Exception as exc:
                log("    imagine sărită:", it.id, repr(exc)[:100])
                continue
            if (clear & gate).sum() < C.MIN_SCENE_CLEAR * n_gate:
                continue
            recent.append((item_date(it), clear, ndvi, nbr))
        ref_scenes, r_dates = [], []
        for day, clear, ndvi, nbr in sorted(recent, key=lambda t: t[0]):
            ref = season.get(day)
            if ref is None:
                continue
            s_ok, s_chg = change(ndvi, nbr, ref, clear & gate)[:2]
            ref_scenes.append((day, s_ok, s_chg))
            r_dates.append(day)
        del recent
        info["ref_recent"] = [d.isoformat() for d in r_dates]

        # urmărim fiecare pixel de la o imagine la alta
        first_day = np.full((H, W), -1, np.int16)     # ziua (față de d0) în care s-a văzut prima dată schimbat
        n_change = np.zeros((H, W), np.uint8)
        n_clear_after = np.zeros((H, W), np.uint8)
        neigh_first = np.zeros((H, W), np.float32)    # cât a scăzut pădurea din jur în acea zi
        feat = {k: np.full((H, W), np.nan, np.float32) for k in ("nd", "nb", "adj_nd", "adj_nb", "blue", "red", "b_nd", "b_nb")}
        scenes = []                                   # (data, clar, schimbat) pentru calculul datelor pe zonă
        used, skipped = [], []
        for it in sorted(items["window"], key=item_date):
            day = item_date(it)
            if winter(day):
                skipped.append((day.isoformat(), "iarnă"))
                continue
            try:
                clear, ndvi, nbr, blue, red = read_scene(it, grid, pool, full=True)
            except Exception as exc:
                log("    imagine sărită:", it.id, repr(exc)[:100])
                continue
            if (clear & gate).sum() < C.MIN_SCENE_CLEAR * n_gate:
                skipped.append((day.isoformat(), "nori"))
                continue
            ref = season.get(day)
            if ref is None:
                skipped.append((day.isoformat(), "fără imagine clară acum un an"))
                continue
            ok, chg, drop, drop_nb, loc_nd, loc_nb = change(ndvi, nbr, ref, clear & gate)
            frac = float(chg.sum()) / max(float(ok.sum()), 1.0)
            if frac > C.SCENE_MAX_CHANGED:
                skipped.append((day.isoformat(), f"schimbare pe {round(100 * frac, 1)}% din pădure (ceață sau toamnă)"))
                continue
            k = (day - d0).days
            new = chg & (first_day < 0)
            first_day[new] = k
            neigh_first[new] = loc_nd[new]
            for key, arr in (("nd", ndvi), ("nb", nbr), ("adj_nd", drop - loc_nd), ("adj_nb", drop_nb - loc_nb),
                             ("blue", blue), ("red", red), ("b_nd", ref[0]), ("b_nb", ref[1])):
                feat[key][new] = arr[new]
            seen_after = ok & (first_day >= 0)
            n_clear_after[seen_after] += 1
            n_change[chg & (first_day >= 0)] += 1
            scenes.append((day, ok, chg))
            used.append(day.isoformat())
        info["window_scenes"] = used
        info["skipped"] = skipped
        info["ref_lastyear"] = sorted(d.isoformat() for d in season.dates)
    finally:
        pool.shutdown(wait=True)
    ref_nd, ref_nb = (s_nd, s_nb) if s_nd is not None else (np.full((H, W), np.nan, np.float32),) * 2

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
        if before is None and s_dates:
            p["vara"] = max(s_dates).year      # n-am văzut-o intactă de curând, dar vara aceea era pădure deasă
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
