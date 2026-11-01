"""Agentul 2, contextul: unelte care adaugă fapte verificabile despre fiecare zonă.

  - cea mai apropiată localitate (GeoNames) și comuna, orașul sau municipiul în care cade zona (limitele UAT)
  - vântul cel mai puternic din intervalul în care a apărut schimbarea (Open-Meteo)
  - dacă s-a mai pierdut pădure în jur în anii trecuți (Hansen 2001–2025)
"""
import datetime as dt
import io
import json
import math
import os
import subprocess
import time
import urllib.error
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


WIND_CELL = 0.1   # grade (~10 km): rafalele sunt la fel pe toată celula, deci o singură întrebare pe celulă


def winds(alerts):
    """Rafala maximă (km/h) între data „înainte" și data „după", pentru zonele confirmate (celelalte nu apar pe site).
    Zonele apropiate împart aceeași întrebare; la „prea multe cereri" (HTTP 429) ne oprim, vântul e doar un indiciu."""
    out = {}
    if os.environ.get("PADUREA_NO_WIND"):   # testul pe trecut: Open-Meteo dă doar ultimele 92 de zile, deci nu ajută
        log("Vântul: sărit")
        return out
    cells = {}
    for a in alerts:
        if a.get("confirmed") or a.get("n_dates", 0) >= 2:
            k = (round(a["lat"] / WIND_CELL) * WIND_CELL, round(a["lon"] / WIND_CELL) * WIND_CELL)
            cells.setdefault(k, []).append(a)
    keys = sorted(cells)
    series, stop, failed = {}, False, 0
    for i in range(0, len(keys), 50):
        if stop or failed >= 2:     # serviciul nu răspunde: nu țin rularea pe loc pentru un indiciu
            break
        chunk = keys[i:i + 50]
        q = {
            "latitude": ",".join(f"{la:.2f}" for la, _ in chunk),
            "longitude": ",".join(f"{lo:.2f}" for _, lo in chunk),
            "daily": "wind_gusts_10m_max", "past_days": 92, "forecast_days": 1, "timezone": "Europe/Bucharest",
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(q)
        data = None
        for attempt in range(3):     # Open-Meteo mai pică din când în când la conectare: încă două încercări, cu pauză
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as exc:
                log(f"  vântul n-a mers (încercarea {attempt + 1}): HTTP {exc.code}")
                if exc.code == 429 and attempt >= 1:
                    stop = True
                    break
                time.sleep(10 * (attempt + 1))
            except Exception as exc:
                log(f"  vântul n-a mers (încercarea {attempt + 1}):", repr(exc)[:120])
                time.sleep(5 * (attempt + 1))
        if data is None:
            failed += 1
            continue
        failed = 0
        if isinstance(data, dict):
            data = [data]
        for k, d in zip(chunk, data):
            series[k] = (d.get("daily", {}).get("time", []), d.get("daily", {}).get("wind_gusts_10m_max", []))
        time.sleep(1)
    for k, zone in cells.items():
        if k not in series:
            continue
        days, gust = series[k]
        for a in zone:
            lo = a.get("before_date") or a["first_seen"]
            hi = a["after_date"]
            vals = [g for t, g in zip(days, gust) if g is not None and lo <= t <= hi]
            if vals:
                out[a["id"]] = round(max(vals))
    log(f"Vântul: {len(out)} zone, din {len(series)} celule de {len(cells)}" + (" (oprit la HTTP 429)" if stop else "")
        + (" (oprit: serviciul nu răspunde)" if failed >= 2 else ""))
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
