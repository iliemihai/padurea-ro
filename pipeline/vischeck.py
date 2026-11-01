"""Verificarea pe poze, fără AI: ce ar vedea un om în perechea înainte/după.

Pentru fiecare zonă comparăm culoarea ei cu un inel de 40–200 m în jur, pe aceleași poze pe care le arătăm pe hartă:
  - open_before: cu cât era zona mai luminoasă decât împrejurimile ÎNAINTE. Mult mai luminoasă = era deja
    luminiș, pajiște sau drum, deci nu e pădure tăiată acum (toamna, iarba de acolo doar s-a uscat).
  - excess: cât s-a schimbat culoarea zonei peste cât s-a schimbat inelul (toamna schimbă tot dealul la fel).
  - dgreen: cât verde a pierdut zona peste cât a pierdut inelul, în puncte procentuale.
Nu decide singură nimic: criticul folosește măsurătorile ca dovezi.
"""
import numpy as np
from PIL import Image, ImageDraw

from . import config as C


def _masks(a, w, h):
    from scipy import ndimage
    x0, y0, x1, y1 = a["chip_bbox"]
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    g = a["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    for poly in polys:
        ring = [((lon - x0) / (x1 - x0) * w, (y1 - lat) / (y1 - y0) * h) for lon, lat in poly[0]]
        if len(ring) >= 3:
            d.polygon(ring, fill=1)
    zone = np.array(m, bool)
    px_m = (y1 - y0) * 111320.0 / h
    near = ndimage.binary_dilation(zone, iterations=max(1, round(40 / px_m)))
    far = ndimage.binary_dilation(zone, iterations=max(2, round(200 / px_m)))
    return zone, far & ~near


SEASON_GAP = 100   # zile: poze din anotimpuri diferite (vară înainte, iarnă după) nu se pot compara pe culori


def measure(a, img_dir):
    """Măsurătorile pentru o zonă, sau None dacă nu avem ambele poze din același anotimp."""
    import datetime as dt
    b, af = a.get("img_before"), a.get("img_after")
    if not b or not af or not a.get("chip_bbox") or not a.get("geometry"):
        return None
    try:
        if (dt.date.fromisoformat(af["date"]) - dt.date.fromisoformat(b["date"])).days > SEASON_GAP:
            return None
    except (KeyError, TypeError, ValueError):
        pass
    fb, fa = img_dir / b["file"], img_dir / af["file"]
    if not fb.exists() or not fa.exists():
        return None
    B = np.asarray(Image.open(fb).convert("RGB"), np.float32)
    A = Image.open(fa).convert("RGB")
    if A.size != (B.shape[1], B.shape[0]):
        A = A.resize((B.shape[1], B.shape[0]))
    A = np.asarray(A, np.float32)
    zone, ring = _masks(a, B.shape[1], B.shape[0])
    if zone.sum() < 4 or ring.sum() < 10:
        return None
    zb, za, rb, ra = B[zone].mean(0), A[zone].mean(0), B[ring].mean(0), A[ring].mean(0)

    def green(v):
        return float(v[1] / max(float(v.sum()), 1e-6))
    return {
        "open_before": round(float(zb.mean() - rb.mean()), 1),
        "excess": round(float(np.linalg.norm((za - zb) - (ra - rb))), 1),
        "dgreen": round(100 * ((green(zb) - green(za)) - (green(rb) - green(ra))), 2),
    }


def verdict(v):
    """'deschisa' (era deja deschisă), 'nevazut' (nu se vede schimbarea), 'vizibil' sau None."""
    if not v:
        return None
    if v["open_before"] > C.VIS_OPEN_MAX:
        return "deschisa"
    if v["excess"] < C.VIS_EXCESS_MIN and v["dgreen"] < C.VIS_DGREEN_MIN:
        return "nevazut"
    return "vizibil"


def apply(alerts, img_dir):
    n = 0
    for a in alerts:
        try:
            v = measure(a, img_dir)
        except Exception:
            v = None
        if v:
            v["verdict"] = verdict(v)
            a["vis"] = v
            n += 1
        else:
            a.pop("vis", None)
    return n
