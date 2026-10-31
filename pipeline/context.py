"""Agentul 2, contextul: unelte care adaugă fapte verificabile despre fiecare zonă.

  - cea mai apropiată localitate (GeoNames) și comuna, orașul sau municipiul în care cade zona (limitele UAT)
  - vântul cel mai puternic din intervalul în care a apărut schimbarea (Open-Meteo)
  - dacă s-a mai pierdut pădure în jur în anii trecuți (Hansen 2001–2025)
"""
import datetime as dt
import io
import json
import math
import subprocess
import urllib.parse
import urllib.request
import zipfile

import numpy as np

from . import config as C
from . import uat
from .sat import log


def localities_fallback():
    """Rezervă fără internet: localitățile de peste 1.000 de locuitori din pachetul reverse_geocoder (tot GeoNames)."""
    try:
        import csv, os
        import reverse_geocoder
        path = os.path.join(os.path.dirname(reverse_geocoder.__file__), "rg_cities1000.csv")
        return [(r["name"], float(r["lat"]), float(r["lon"]), 1000) for r in csv.DictReader(open(path, encoding="utf-8")) if r["cc"] == "RO"]
    except Exception:
        return None


def localities():
    """Localitățile din România (GeoNames): nume, lat, lon, populație."""
    f = C.DATA / "geonames_RO.txt"
    if not f.exists():
        z = C.DATA / "RO.zip"
        if subprocess.run(["curl", "-sfL", "--retry", "3", "--max-time", "120", "-o", str(z), "https://download.geonames.org/export/dump/RO.zip"]).returncode != 0:
            return localities_fallback()
        with zipfile.ZipFile(z) as zf:
            f.write_bytes(zf.read("RO.txt"))
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if len(p) > 14 and p[6] == "P" and p[7].startswith("PPL") and p[7] not in ("PPLQ", "PPLH", "PPLW"):
            rows.append((p[1], float(p[4]), float(p[5]), int(p[14] or 0)))
    return rows


class Places:
    def __init__(self):
        from scipy.spatial import cKDTree
        self.rows = localities() or []
        if self.rows:
            lat = np.array([r[1] for r in self.rows]); lon = np.array([r[2] for r in self.rows])
            self.tree = cKDTree(np.c_[lat, lon * math.cos(math.radians(46))])

    def nearest(self, lat, lon):
        if not self.rows:
            return None, None
        d, i = self.tree.query([lat, lon * math.cos(math.radians(46))])
        return self.rows[i][0], round(d * 111.32, 1)


def winds(alerts):
    """Rafala maximă (km/h) între data „înainte" și data „după", pentru fiecare alertă."""
    out = {}
    for i in range(0, len(alerts), 40):
        chunk = alerts[i:i + 40]
        q = {
            "latitude": ",".join(f"{a['lat']:.3f}" for a in chunk),
            "longitude": ",".join(f"{a['lon']:.3f}" for a in chunk),
            "daily": "wind_gusts_10m_max", "past_days": 92, "forecast_days": 1, "timezone": "Europe/Bucharest",
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q)
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = json.load(r)
        except Exception as exc:
            log("  vântul n-a mers:", repr(exc)[:120])
            continue
        if isinstance(data, dict):
            data = [data]
        for a, d in zip(chunk, data):
            days = d.get("daily", {}).get("time", [])
            gust = d.get("daily", {}).get("wind_gusts_10m_max", [])
            lo = a.get("before_date") or a["first_seen"]
            hi = a["after_date"]
            vals = [g for t, g in zip(days, gust) if g is not None and lo <= t <= hi]
            if vals:
                out[a["id"]] = round(max(vals))
    return out


class PastLoss:
    """Pierderile Hansen din jurul unui punct (fereastră de ~600 m)."""
    def __init__(self, path):
        self.src = None
        if path and path.exists():
            import rasterio
            self.src = rasterio.open(path)

    def near(self, lat, lon, half_m=300):
        if self.src is None:
            return None
        from rasterio.windows import from_bounds
        dlat = half_m / 111320.0
        dlon = dlat / math.cos(math.radians(lat))
        w = from_bounds(lon - dlon, lat - dlat, lon + dlon, lat + dlat, self.src.transform)
        arr = self.src.read(1, window=w, boundless=True, fill_value=0)
        years = sorted({2000 + int(y) for y in np.unique(arr) if 0 < y <= 30})
        frac = float((arr > 0).mean()) if arr.size else 0.0
        return {"ani": years[-5:], "procent": round(100 * frac, 1)}


def add_context(alerts, lossyear_path):
    places = Places()
    past = PastLoss(lossyear_path)
    for a in alerts:
        name, km = places.nearest(a["lat"], a["lon"])
        a["localitate"] = name
        a["localitate_km"] = km
        a["hansen_jur"] = past.near(a["lat"], a["lon"])
    log(f"Comuna sau orașul: {uat.apply(alerts)} din {len(alerts)} zone")
    w = winds(alerts)
    for a in alerts:
        a["rafala_kmh"] = w.get(a["id"])
