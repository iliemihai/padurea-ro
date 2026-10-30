"""Citirea imaginilor Sentinel-2 din Microsoft Planetary Computer, direct din cloud, doar bucățile de care avem nevoie."""
import datetime as dt
import time

import numpy as np

from . import config as C


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def client():
    import planetary_computer as pc
    from pystac_client import Client
    return Client.open(C.PC_URL, modifier=pc.sign_inplace)


def search(cat, collection, bbox, start, end, cloud=None, query=None):
    q = dict(query or {})
    if cloud is not None:
        q["eo:cloud_cover"] = {"lt": cloud}
    kw = {"collections": [collection], "bbox": bbox, "datetime": f"{start}/{end}"}
    if q:
        kw["query"] = q
    for attempt in range(4):
        try:
            return list(cat.search(**kw).items())
        except Exception as exc:  # serviciul mai dă erori trecătoare
            log("  căutare reîncercată:", repr(exc)[:120])
            time.sleep(5 * (attempt + 1))
    return list(cat.search(**kw).items())


def item_date(it):
    return it.datetime.date()


def s2_offset(it):
    """Din 2022 (baseline 04.00), valorile Sentinel-2 au un decalaj de 1000."""
    return 1000.0 if str(it.properties.get("s2:processing_baseline", "00.00")) >= "04.00" else 0.0


def open_at_res(href, target_res):
    """Deschide fișierul la nivelul de prezentare cel mai apropiat de rezoluția dorită (citim mult mai puțin)."""
    import rasterio
    src = rasterio.open(href)
    native = abs(src.transform.a)
    target = target_res / 111320.0 if src.crs and src.crs.is_geographic else target_res  # metri -> grade
    level = None
    for i, fac in enumerate(src.overviews(1) or []):
        if native * fac <= target * 1.01:
            level = i
    if level is not None:
        src.close()
        src = rasterio.open(href, overview_level=level)
    return src


def fresh(href):
    """Linkurile Planetary Computer expiră după un timp: le semnăm din nou chiar înainte de citire."""
    if href.startswith("https://") and ".blob.core.windows.net" in href:
        import planetary_computer as pc
        return pc.sign(href.split("?")[0])
    return href


def read_grid(href, grid, resampling, target_res=C.RES, nodata=None, dtype="float32"):
    """Citește un fișier din cloud direct pe grila noastră (proiecție, mărime, rezoluție)."""
    from rasterio.vrt import WarpedVRT
    crs, transform, width, height = grid
    for attempt in range(3):
        try:
            with open_at_res(fresh(href), target_res) as src:
                kw = dict(crs=crs, transform=transform, width=width, height=height, resampling=resampling)
                if nodata is not None:
                    kw["src_nodata"] = nodata
                    kw["nodata"] = nodata
                with WarpedVRT(src, **kw) as vrt:
                    return vrt.read(1).astype(dtype)
        except Exception as exc:
            if attempt == 2:
                raise
            log("    citire reîncercată:", repr(exc)[:100])
            time.sleep(3 * (attempt + 1))


def read_scene(it, grid, pool=None):
    """Citește SCL, roșu, infraroșu și SWIR pentru o imagine. Întoarce (clar, ndvi, nbr)."""
    from rasterio.enums import Resampling
    from scipy import ndimage

    jobs = {
        "scl": (it.assets["SCL"].href, Resampling.nearest, None),
        "b04": (it.assets["B04"].href, Resampling.average, 0),
        "b08": (it.assets["B08"].href, Resampling.average, 0),
        "b12": (it.assets["B12"].href, Resampling.average, 0),
    }
    if pool is not None:
        futs = {k: pool.submit(read_grid, h, grid, r, C.RES, nd) for k, (h, r, nd) in jobs.items()}
        arr = {k: f.result() for k, f in futs.items()}
    else:
        arr = {k: read_grid(h, grid, r, C.RES, nd) for k, (h, r, nd) in jobs.items()}
    scl = arr["scl"]
    bad = np.isin(scl, C.SCL_BAD)
    if bad.any():
        bad = ndimage.binary_dilation(bad, iterations=C.BAD_DILATE_PX)
    off = s2_offset(it)
    b04, b08, b12 = arr["b04"], arr["b08"], arr["b12"]
    clear = np.isin(scl, C.SCL_OK) & ~bad & (b04 > off) & (b08 > off) & (b12 > off)
    red, nir, swir = (b04 - off) / 1e4, (b08 - off) / 1e4, (b12 - off) / 1e4
    with np.errstate(all="ignore"):
        ndvi = np.clip((nir - red) / np.maximum(nir + red, 1e-6), -1, 1)
        nbr = np.clip((nir - swir) / np.maximum(nir + swir, 1e-6), -1, 1)
    ndvi[~clear] = np.nan
    nbr[~clear] = np.nan
    return clear, ndvi.astype("float32"), nbr.astype("float32")


def chip_size(bbox, lat):
    """Pixeli pătrați pe teren (~10 m), cel mult C.THUMB_MAX_PX pe latură."""
    import math
    x0, y0, x1, y1 = bbox
    res_lat = 0.00009
    res_lon = res_lat / max(math.cos(math.radians(lat)), 0.2)
    w, h = (x1 - x0) / res_lon, (y1 - y0) / res_lat
    k = max(1.0, max(w, h) / C.THUMB_MAX_PX)
    return max(32, round(w / k)), max(32, round(h / k))


def read_chip(it, bbox, size_wh):
    """Imagine color (10 m) pentru o zonă mică, în grade. Întoarce (RGB uint8, fracția clară)."""
    from affine import Affine
    from rasterio.enums import Resampling
    x0, y0, x1, y1 = bbox
    w, h = size_wh
    g = ("EPSG:4326", Affine((x1 - x0) / w, 0, x0, 0, -(y1 - y0) / h, y1), w, h)
    scl = read_grid(it.assets["SCL"].href, g, Resampling.nearest, 20)
    clear_frac = float(np.isin(scl, (4, 5, 6)).mean())
    off = s2_offset(it)
    bands = [read_grid(it.assets[b].href, g, Resampling.bilinear, 10, 0) for b in ("B04", "B03", "B02")]
    rgb = np.dstack([(b - off) / 1e4 for b in bands])
    v = np.clip(rgb / 0.18, 0, 1) ** (1 / 1.6)
    return (v * 255).astype(np.uint8), clear_frac


def days_between(a, b):
    return (b - a).days


def iso(d):
    return d.isoformat() if isinstance(d, (dt.date, dt.datetime)) else str(d)
