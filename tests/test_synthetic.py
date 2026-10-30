"""Test pe date inventate: o tăiere reală, un nor trecător și o zonă de toamnă.

Detectorul trebuie să păstreze tăierea, să ignore norul și să respingă toamna.
python -m tests.test_synthetic
"""
import datetime as dt
import json
import shutil
from types import SimpleNamespace

import numpy as np
from affine import Affine
from rasterio.crs import CRS

from pipeline import config as C
from pipeline import detect

N = 300
D0 = dt.date(2026, 10, 1)


def item(day, cloud=10):
    d = D0 + dt.timedelta(days=day)
    return SimpleNamespace(id=f"S2_{d}", datetime=dt.datetime(d.year, d.month, d.day, 9), properties={"eo:cloud_cover": cloud}, assets={})


def fake_scene(it, grid, pool=None, full=False):
    day = (it.datetime.date() - D0).days
    ndvi = np.full((N, N), 0.80, np.float32)
    nbr = np.full((N, N), 0.55, np.float32)
    clear = np.ones((N, N), bool)
    if day >= 5:                      # tăierea apare în ziua 5 și rămâne
        ndvi[100:120, 100:130] = 0.20
        nbr[100:120, 100:130] = 0.00
    if day == 12:                     # „nor" care apare o singură dată
        ndvi[200:220, 50:70] = 0.30
        nbr[200:220, 50:70] = 0.10
    if day >= 25:                     # toamnă: tot dealul se îngălbenește, o pată mai tare
        ndvi[230:300, 200:300] = 0.52
        nbr[230:300, 200:300] = 0.35
        ndvi[250:270, 250:280] = 0.40
        nbr[250:270, 250:280] = 0.25
    if day >= 27:                     # o tăiere văzută doar în ultima imagine: încă neconfirmată
        ndvi[30:45, 30:45] = 0.20
        nbr[30:45, 30:45] = 0.00
    if full:
        blue = np.full((N, N), 0.03, np.float32)
        red = np.where(ndvi < 0.5, 0.09, 0.03).astype(np.float32)
        return clear, ndvi, nbr, blue, red
    return clear, ndvi, nbr


def main():
    detect.read_scene = fake_scene
    detect.tile_grid = lambda it: (CRS.from_epsg(32634), Affine(40, 0, 600000, 0, -40, 5200000), N, N)
    detect.county_raster = lambda grid: (np.ones((N, N), np.uint8), ["Test"])
    detect.forest_mask = lambda cat, grid, bb, ly: np.ones((N, N), bool)
    items = {"window": [item(d) for d in (5, 12, 20, 27)], "recent": [item(-30), item(-20)], "lastyear": [item(-365)]}
    info, patches, rejected = detect.detect_tile(None, "34TXX", items, D0, D0 + dt.timedelta(days=29), None, lambda *a: True)
    print("info:", {k: info.get(k) for k in ("status", "patches", "rejected", "window_scenes")})
    from pipeline.rules import split
    patches, rr = split(patches)
    rejected += rr
    for p in patches:
        print("PĂSTRAT ", p["ha"], "ha", p["first_seen"], "înainte", p["before_date"], "după", p["after_date"], "n_dates", p["n_dates"], "vecini", p["neigh_drop"], p["geometry"]["type"])
    for p in rejected:
        print("RESPINS ", p["ha"], "ha", p["first_seen"], "vecini", p["neigh_drop"], p["motiv"])
    conf = [p for p in patches if p["confirmed"]]
    single = [p for p in patches if not p["confirmed"]]
    assert len(conf) == 1 and abs(conf[0]["ha"] - 20 * 30 * 0.16) < 1, "tăierea trebuia păstrată și confirmată"
    assert conf[0]["first_seen"] == "2026-10-06" and conf[0]["n_dates"] == 4 and conf[0]["before_date"] == "2026-09-11"
    assert len(single) == 1 and single[0]["n_dates"] == 1, "tăierea din ultima zi trebuia să fie neconfirmată"
    assert not any(p["lat"] < conf[0]["lat"] - 0.05 for p in patches + rejected), "toamna nu trebuia să apară"
    print("detectorul: OK")
    patches = conf

    # pasul 2 pe rezultatul de mai sus (fără rețea: contextul se dă bătut elegant)
    from pipeline import run_finish
    tmp = C.ROOT / "out_test"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "img").mkdir(parents=True)
    C.OUT = tmp
    run_finish.C.OUT = tmp
    docs = C.ROOT / "docs_test"
    shutil.rmtree(docs, ignore_errors=True)
    run_finish.ALERTS = docs / "data" / "alerts.json"
    run_finish.RUNS = docs / "data" / "runs.json"
    run_finish.C.DOCS = docs
    patches[0]["key"] = "34TXX-0"
    patches[0]["ai"] = {"categorie": "taiere", "incredere": 0.8, "motiv": "Sol gol cu margini drepte.", "model": "test"}
    twin = json.loads(json.dumps(patches[0]))
    twin["tile"], twin["key"], twin["ha"] = "34TYY", "34TYY-0", 9.0
    (tmp / "group_0.json").write_text(json.dumps({"d0": "2026-10-01", "d1": "2026-10-30", "tiles": [info, {"tile": "34TYY", "status": "ok"}],
                                                   "patches": [patches[0], twin], "rejected": rejected}))
    run_finish.main()
    out = json.loads(run_finish.ALERTS.read_text())
    assert len(out["alerts"]) == 1, "dublura trebuia unită"
    a = out["alerts"][0]
    print("ALERTĂ:", a["id"], a["incredere"], a["dovezi"])
    print("TEXT:", a["text"])
    run_finish.main()  # a doua rulare: aceeași zonă trebuie recunoscută, nu dublată
    assert len(json.loads(run_finish.ALERTS.read_text())["alerts"]) == 1
    print("pasul 2: OK")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(docs, ignore_errors=True)


if __name__ == "__main__":
    main()
