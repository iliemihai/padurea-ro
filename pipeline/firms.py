"""Sursa independentă pentru incendii: NASA FIRMS (senzorii în infraroșu VIIRS și MODIS).

Sateliții NASA văd căldura focurilor de câteva ori pe zi. Dacă au văzut foc lângă o zonă în perioada în care
s-a schimbat, avem o dovadă independentă de AI și de detectorul nostru că a fost incendiu.

Cheie gratuită, pe e-mail: https://firms.modaps.eosdis.nasa.gov/api/map_key  (variabila FIRMS_MAP_KEY).
Fără cheie, pasul e sărit și restul merge la fel.

API: /api/area/csv/{cheie}/{sursă}/{vest,sud,est,nord}/{zile 1–10}/{data de început}
     întoarce punctele de foc din [data, data + zile - 1]. Limita: 5000 de cereri la 10 minute pe cheie.
"""
import csv
import datetime as dt
import io
import json
import math
import os
import time
import urllib.error
import urllib.request

from . import config as C
from .sat import log

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{bbox}/{days}/{date}"
# NRT = date din ultimele luni; SP = aceleași date, reprocesate, pentru perioade mai vechi. Dublurile le scoatem.
SOURCES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT",
           "VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "MODIS_SP"]


def _get(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "padurea-ro"}), timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return None
        except Exception:
            pass
        time.sleep(2 * (k + 1))
    return None


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse(text, src):
    """Rândurile CSV ale FIRMS → puncte {lat, lon, date, time, src, conf, frp}."""
    if not text or not text.lstrip().lower().startswith("latitude"):
        return []
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        lat, lon = _num(r.get("latitude")), _num(r.get("longitude"))
        if lat is None or lon is None or not r.get("acq_date"):
            continue
        out.append({"lat": lat, "lon": lon, "date": r["acq_date"], "time": (r.get("acq_time") or "").zfill(4),
                    "src": src.rsplit("_", 1)[0].replace("_", " "), "conf": r.get("confidence"), "frp": _num(r.get("frp"))})
    return out


def fetch(key, start, end, bbox=None, sources=SOURCES):
    """Toate punctele de foc din dreptunghi, între start și end inclusiv, din toate sursele, fără dubluri."""
    bbox = bbox or C.RO_BBOX
    box = ",".join(f"{x:.3f}" for x in bbox)
    pts, seen = [], set()
    d = start
    while d <= end:
        days = min(10, (end - d).days + 1)
        for src in sources:
            for p in parse(_get(API.format(key=key, src=src, bbox=box, days=days, date=d.isoformat())), src):
                k = (round(p["lat"], 3), round(p["lon"], 3), p["date"], p["time"][:3])
                if k not in seen:
                    seen.add(k)
                    pts.append(p)
        d += dt.timedelta(days=days)
    return pts


def _window(a):
    """Perioada în care căutăm foc: de când zona era intactă până la câteva zile după ce s-a văzut schimbată."""
    first = dt.date.fromisoformat(a["first_seen"])
    start = dt.date.fromisoformat(a["before_date"]) if a.get("before_date") else first - dt.timedelta(days=30)
    return start, first + dt.timedelta(days=C.FIRMS_AFTER_DAYS)


def match(a, pts):
    """Punctele de foc la cel mult C.FIRMS_BUFFER_M de zonă, în perioada ei. Întoarce un rezumat."""
    start, end = _window(a)
    x0, y0, x1, y1 = a["bbox"]
    s0, s1 = start.isoformat(), end.isoformat()
    hits = []
    for p in pts:
        if not (s0 <= p["date"] <= s1):
            continue
        dx = max(x0 - p["lon"], 0.0, p["lon"] - x1) * 111320.0 * math.cos(math.radians(p["lat"]))
        dy = max(y0 - p["lat"], 0.0, p["lat"] - y1) * 110540.0
        dist = math.hypot(dx, dy)
        if dist <= C.FIRMS_BUFFER_M:
            hits.append((dist, p))
    res = {"n": len(hits), "de_la": s0, "pana_la": s1}
    if hits:
        dates = sorted(p["date"] for _, p in hits)
        frp = [p["frp"] for _, p in hits if p["frp"] is not None]
        res.update({"prima": dates[0], "ultima": dates[-1], "dist_m": int(round(min(d for d, _ in hits))),
                    "frp_max": round(max(frp), 1) if frp else None, "surse": sorted({p["src"] for _, p in hits})})
    return res


def save_points(pts, path, until):
    """Punctele pentru stratul de pe hartă: cele noi plus cele vechi, din ultimele C.FIRMS_KEEP_DAYS zile."""
    old = []
    if path.exists():
        try:
            old = [{"lat": f["geometry"]["coordinates"][1], "lon": f["geometry"]["coordinates"][0], **f["properties"]}
                   for f in json.loads(path.read_text())["features"]]
        except Exception:
            old = []
    keep_from = (until - dt.timedelta(days=C.FIRMS_KEEP_DAYS)).isoformat()
    from . import romania
    seen, feats = set(), []
    for p in pts + old:
        d = p.get("date") or p.get("d")
        if not d or d < keep_from:
            continue
        if not romania.contains(p["lon"], p["lat"]):
            continue      # pe hartă arătăm doar focurile din țară; cele de lângă graniță contează totuși la potrivirea zonelor
        k = (round(p["lat"], 3), round(p["lon"], 3), d, str(p.get("time") or p.get("t") or "")[:3])
        if k in seen:
            continue
        seen.add(k)
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(p["lon"], 4), round(p["lat"], 4)]},
                      "properties": {"d": d, "t": p.get("time") or p.get("t") or "", "s": p.get("src") or p.get("s") or "",
                                     "frp": p.get("frp")}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    return len(feats)


def apply(alerts, points_path=None):
    """Caută foc NASA lângă fiecare zonă. Scrie a["firms"]; întoarce câte zone au foc văzut."""
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        log("FIRMS: fără cheie (FIRMS_MAP_KEY), sar peste")
        return 0
    todo = [a for a in alerts if a.get("bbox") and a.get("first_seen")]
    if not todo:
        return 0
    wins = [_window(a) for a in todo]
    today = dt.date.today()
    start, end = min(w[0] for w in wins), min(today, max(w[1] for w in wins))
    pts = fetch(key, start, end)
    log(f"FIRMS: {len(pts)} puncte de foc în România, {start} – {end}")
    if not pts:
        return 0       # fără date (cheie greșită sau serviciu căzut): nu scriem „n-a văzut foc”
    for a in todo:
        a["firms"] = match(a, pts)
    if points_path is not None:
        log(f"FIRMS: {save_points(pts, points_path, end)} puncte pe hartă")
    n = sum(1 for a in todo if a["firms"]["n"])
    log(f"FIRMS: foc văzut lângă {n} din {len(todo)} zone")
    return n
