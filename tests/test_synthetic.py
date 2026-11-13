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
    if day >= -25:                    # o tăiere mai veche: se vede deja în ultima imagine de referință
        ndvi[150:170, 200:230] = 0.20
        nbr[150:170, 200:230] = 0.00
    if full:
        blue = np.full((N, N), 0.03, np.float32)
        red = np.where(ndvi < 0.5, 0.09, 0.03).astype(np.float32)
        return clear, ndvi, nbr, blue, red
    return clear, ndvi, nbr


def main():
    detect.read_scene = fake_scene
    detect.tile_grid = lambda it: (CRS.from_epsg(32634), Affine(40, 0, 600000, 0, -40, 5200000), N, N)
    detect.county_raster = lambda grid: (np.ones((N, N), np.uint8), ["Test"])
    detect.forest_mask = lambda cat, grid, bb, ly, **kw: np.ones((N, N), bool)
    items = {"window": [item(d) for d in (5, 12, 20, 27)], "recent": [item(-40), item(-30), item(-20)], "lastyear": [item(-365)]}
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
    old = [p for p in rejected if p.get("early")]
    assert len(old) == 1 and old[0]["early"] == "2026-09-11" and abs(old[0]["ha"] - 20 * 30 * 0.16) < 1, "tăierea veche trebuia respinsă ca veche"
    assert not any(p.get("early") for p in patches), "o zonă veche a scăpat printre cele noi"
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
    patches[0]["img_before"] = {"file": "34TXX-0_b.webp", "date": "2026-09-11"}
    patches[0]["img_after"] = {"file": "34TXX-0_a.webp", "date": "2026-10-28"}
    twin = json.loads(json.dumps(patches[0]))
    twin["tile"], twin["key"], twin["ha"] = "34TYY", "34TYY-0", 9.0
    (tmp / "group_0.json").write_text(json.dumps({"d0": "2026-10-01", "d1": "2026-10-30", "tiles": [info, {"tile": "34TYY", "status": "ok"}],
                                                   "patches": [patches[0], twin], "rejected": rejected}))
    run_finish.main()
    out = json.loads(run_finish.ALERTS.read_text())
    assert len(out["alerts"]) == 1, "dublura trebuia unită"
    a = out["alerts"][0]
    print("ALERTĂ:", a["id"], a["incredere"], a["dovezi"])
    assert a["incredere"] == "ridicată", a["dovezi"]
    print("TEXT:", a["text"])
    run_finish.main()  # a doua rulare: aceeași zonă trebuie recunoscută, nu dublată
    assert len(json.loads(run_finish.ALERTS.read_text())["alerts"]) == 1
    print("pasul 2: OK")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(docs, ignore_errors=True)


def test_critic():
    """Criticul: fără poză de dinainte nu dăm încredere; o poză veche sau un AI nehotărât scad scorul."""
    from pipeline.critic import score
    base = {"confirmed": True, "n_dates": 4, "ha": 4.0, "neigh_drop": 0.01, "first_seen": "2026-07-04",
            "before_date": "2026-06-17", "img_before": {"date": "2026-06-17"},
            "ai": {"categorie": "taiere", "incredere": 0.8}}
    assert score(base)[0] == "ridicată"
    assert score({**base, "img_before": None})[0] == "de confirmat"
    assert score({**base, "before_date": "2026-05-13"})[1] == score(base)[1] - 1
    assert score({**base, "ai": {"categorie": "neclar", "incredere": 0.3}})[0] == "medie"
    assert score({**base, "ai": {"categorie": "toamna", "incredere": 0.8}})[0] == "scăzută"
    print("criticul: OK")


def test_vischeck():
    """Verificarea pe poze: tăiere nouă = vizibil; luminiș care era deja acolo = deschisa; nimic schimbat = nevazut."""
    import tempfile
    from pathlib import Path
    from PIL import Image
    from pipeline import vischeck
    from pipeline.critic import score
    tmp = Path(tempfile.mkdtemp())
    n = 100                                            # 100 px pe ~1 km: ~10 m pe pixel
    bbox = [22.0, 46.0, 22.013, 46.009]
    zone_px = (40, 40, 60, 60)
    x0, y0, x1, y1 = bbox
    lon = lambda c: x0 + c / n * (x1 - x0)
    lat = lambda r: y1 - r / n * (y1 - y0)
    c0, r0, c1, r1 = zone_px
    geom = {"type": "Polygon", "coordinates": [[[lon(c0), lat(r0)], [lon(c1), lat(r0)], [lon(c1), lat(r1)], [lon(c0), lat(r1)], [lon(c0), lat(r0)]]]}
    forest, autumn, soil = (40, 90, 40), (90, 80, 40), (190, 170, 140)

    def pic(name, ring, zone):
        im = Image.new("RGB", (n, n), ring)
        im.paste(Image.new("RGB", (c1 - c0, r1 - r0), zone), (c0, r0))
        im.save(tmp / name)
        return {"file": name, "date": "2026-10-01"}

    def alert(b, a):
        return {"chip_bbox": bbox, "geometry": geom, "img_before": b, "img_after": a}
    cases = {
        "vizibil": alert(pic("cut_b.png", forest, forest), pic("cut_a.png", autumn, soil)),
        "deschisa": alert(pic("old_b.png", forest, soil), pic("old_a.png", autumn, soil)),
        "nevazut": alert(pic("same_b.png", forest, forest), pic("same_a.png", forest, forest)),
    }
    for want, a in cases.items():
        v = vischeck.measure(a, tmp)
        assert vischeck.verdict(v) == want, (want, v)
    base = {"confirmed": True, "n_dates": 4, "ha": 4.0, "neigh_drop": 0.01, "first_seen": "2026-07-04",
            "before_date": "2026-06-17", "img_before": {"date": "2026-06-17"}, "ai": {"categorie": "taiere", "incredere": 0.8}}
    assert score({**base, "vis": {"verdict": "vizibil"}})[0] == "ridicată"
    assert score({**base, "vis": {"verdict": "deschisa"}})[0] == "scăzută"
    assert score({**base, "vis": {"verdict": "nevazut"}})[0] == "scăzută"
    print("verificarea pe poze: OK")


def test_firms():
    """NASA FIRMS fără rețea: citim CSV-ul, potrivim punctele cu o zonă reală (Siseștii de Sus) și scriem stratul."""
    import os
    import tempfile
    from pathlib import Path
    from pipeline import firms
    from pipeline.critic import score
    csv_text = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight\n"
                "44.7872,22.8418,330.1,0.4,0.4,2026-10-07,1105,N,VIIRS,n,2.0NRT,290.2,12.5,D\n"   # pe zonă, în perioada ei
                "44.8300,22.9000,331.0,0.4,0.4,2026-10-07,1105,N,VIIRS,n,2.0NRT,291.0,9.0,D\n"    # la ~6 km: nu se potrivește
                "44.7860,22.8420,329.0,0.4,0.4,2026-09-01,1050,N,VIIRS,n,2.0NRT,289.0,7.0,D\n")   # pe zonă, dar înainte să fie intactă
    pts = firms.parse(csv_text, "VIIRS_NOAA20_NRT")
    assert len(pts) == 3 and pts[0]["src"] == "VIIRS NOAA20" and pts[0]["time"] == "1105"
    assert firms.parse("Invalid MAP_KEY.", "MODIS_NRT") == []
    zone = {"id": "20261012_44786_22842", "bbox": [22.84101, 44.78502, 22.84355, 44.78648],
            "before_date": "2026-10-04", "first_seen": "2026-10-12"}
    m = firms.match(zone, pts)
    assert m["n"] == 1 and m["prima"] == "2026-10-07" and m["dist_m"] < 200, m
    far = {**zone, "bbox": [23.5, 45.5, 23.51, 45.51]}
    assert firms.match(far, pts)["n"] == 0
    # apply(), cu descărcarea înlocuită: fără cheie nu face nimic, cu cheie scrie rezultatul și stratul hărții
    old_fetch, old_key = firms.fetch, os.environ.pop("FIRMS_MAP_KEY", None)
    try:
        firms.fetch = lambda key, start, end, bbox=None, sources=None: pts
        z1 = dict(zone)
        assert firms.apply([z1]) == 0 and "firms" not in z1
        os.environ["FIRMS_MAP_KEY"] = "test"
        out = Path(tempfile.mkdtemp()) / "firms.geojson"
        assert firms.apply([z1], out) == 1 and z1["firms"]["n"] == 1
        fc = json.loads(out.read_text())
        assert len(fc["features"]) == 3 and fc["features"][0]["properties"]["d"] == "2026-10-07"
    finally:
        firms.fetch = old_fetch
        os.environ.pop("FIRMS_MAP_KEY", None)
        if old_key is not None:
            os.environ["FIRMS_MAP_KEY"] = old_key
    base = {"confirmed": True, "n_dates": 4, "ha": 1.4, "neigh_drop": 0.1, "first_seen": "2026-10-12",
            "before_date": "2026-10-04", "img_before": {"date": "2026-10-04"}, "ai": {"categorie": "neclar", "incredere": 0.3}}
    s0, s1 = score(base), score({**base, "firms": z1["firms"]})
    assert s1[1] == s0[1] + 2 and any("NASA" in x for x in s1[2]), s1
    print("NASA FIRMS: OK")


def test_uat():
    """Comuna se găsește după coordonate, iar textul fișei o spune."""
    from pipeline import uat, writer
    u = uat.UAT()
    assert u.find(22.772, 44.517)["nume"] == "Hinova"
    assert u.find(22.599, 44.523)["nume"] == "Burila Mare"
    a = {"lat": 44.523, "lon": 22.599, "localitate": "Vrancea", "localitate_km": 1.2, "county": "Mehedinți", "ha": 1.8,
         "first_seen": "2026-10-02", "before_date": "2026-09-09", "n_dates": 7}
    assert uat.apply([a]) == 1
    assert "din comuna Burila Mare, lângă Vrancea, județul Mehedinți" in writer.text(a), writer.text(a)
    assert uat.ro("Şişeşti") == "Șișești"
    assert uat.modern("Vînjuleț") == "Vânjuleț" and uat.modern("Întorsura Buzăului") == "Întorsura Buzăului"
    assert u.find(22.79, 44.44)["nume"] == "Vânjuleț"
    print("Comuna: OK")


def _sq(x, y, d=0.002, **kw):
    from shapely.geometry import box, mapping
    g = box(x, y, x + d, y + d)
    p = {"tile": "T", "ha": 4.0, "lat": y + d / 2, "lon": x + d / 2, "first_seen": "2026-08-01", "after_date": "2026-08-10",
         "n_dates": 2, "geometry": json.loads(json.dumps(mapping(g))), "bbox": list(g.bounds), "_g": g}
    p.update(kw)
    return p


def test_merge_rules():
    """Aceeași tăiere văzută iar se actualizează; o lărgire la scurt timp se unește; o tăiere nouă lângă una veche e zonă nouă."""
    from pipeline import run_finish as R
    old = _sq(25.0, 46.0, id="A")
    old.pop("_g")
    hist = [old]
    again = _sq(25.0003, 46.0, first_seen="2026-08-05", after_date="2026-08-12", n_dates=4)
    grow = _sq(25.002, 46.0, d=0.001, first_seen="2026-08-20", after_date="2026-08-22", ha=1.0)
    later = _sq(25.0, 46.002, d=0.001, first_seen="2026-10-20", after_date="2026-10-25", ha=1.0)
    n, touched = R.merge_history([again, grow, later], hist)
    assert n == {"noi": 1, "actualizate": 1, "largite": 1, "langa_altele": 1}, n
    a = next(h for h in hist if h["id"] == "A")
    assert a["n_dates"] == 4 and a["extinsa"] == "2026-08-20" and a["ha"] > 4.0, a
    new = next(h for h in hist if h.get("_src") == "n")
    assert new["langa"]["id"] == "A" and new["first_seen"] == "2026-10-20"
    print("Potrivirea cu istoricul: OK")


def test_arhiva_split():
    """Pe site din start: ultimele 90 de zile, doar zonele confirmate; „de confirmat” stau deoparte 30 de zile, apoi se uită."""
    from pipeline import arhiva
    z = [{"id": "a", "incredere": "de confirmat", "first_seen": "2026-10-20"},
         {"id": "b", "incredere": "de confirmat", "first_seen": "2026-09-15"},
         {"id": "c", "incredere": "ridicată", "first_seen": "2026-09-15"},
         {"id": "d", "incredere": "ridicată", "first_seen": "2026-07-01"},
         {"id": "e", "incredere": "ridicată", "first_seen": "2026-07-01", "extinsa": "2026-10-25"}]
    recent, old, pending, expired = arhiva.split(z, "2026-11-01")
    assert sorted(a["id"] for a in recent) == ["c", "e"] and [a["id"] for a in old] == ["d"]
    assert [a["id"] for a in pending] == ["a"] and [a["id"] for a in expired] == ["b"]
    print("Arhiva: OK")


def test_confirm_across_runs():
    """O zonă văzută într-o singură imagine devine confirmată când o vedem schimbată în încă trei imagini mai noi,
    chiar dacă fiecare rulare (fereastra alunecă) vede doar una."""
    from pipeline import run_finish as R
    old = _sq(25.0, 46.0, id="P", n_dates=1, confirmed=False, after_date="2026-10-01", first_seen="2026-10-01")
    old.pop("_g")
    same_day = _sq(25.0, 46.0, n_dates=1, confirmed=False, first_seen="2026-10-01", after_date="2026-10-01")
    R.merge_history([same_day], [old])
    assert not old["confirmed"] and old["n_dates"] == 1, old
    later = _sq(25.0, 46.0, n_dates=1, confirmed=False, first_seen="2026-10-01", after_date="2026-10-09")
    R.merge_history([later], [old])
    assert not old["confirmed"] and old["n_dates"] == 2, old
    third = _sq(25.0, 46.0, n_dates=1, confirmed=False, first_seen="2026-10-01", after_date="2026-10-14")
    R.merge_history([third], [old])
    assert not old["confirmed"] and old["n_dates"] == 3, old
    last = _sq(25.0, 46.0, n_dates=1, confirmed=False, first_seen="2026-10-01", after_date="2026-10-19")
    R.merge_history([last], [old])
    assert old["confirmed"] and old["n_dates"] == 4 and old["after_date"] == "2026-10-19", old
    print("Confirmarea între rulări: OK")


def test_autumn_cap():
    """Văzută schimbată doar toamna: cel mult „scăzută”; văzută și după toamnă: nivelul obișnuit."""
    from pipeline import critic
    a = {"confirmed": True, "n_dates": 4, "img_before": {"file": "x"}, "ha": 5, "neigh_drop": 0.01,
         "first_seen": "2025-10-05", "after_date": "2025-10-20", "before_date": "2025-09-30",
         "ai": {"categorie": "taiere", "incredere": 0.9}}
    assert critic.score(a)[0] == "scăzută", critic.score(a)
    a["after_date"] = "2026-04-20"
    assert critic.score(a)[0] == "ridicată", critic.score(a)
    print("Toamna: OK")


def test_romania():
    """Conturul țării: punctele din țară da, cele de peste graniță nu (pentru focuri și nume pe hartă)."""
    from pipeline import romania
    assert romania.contains(24.0, 46.0) and romania.contains(29.3, 45.1)
    assert not romania.contains(21.3, 47.6) and not romania.contains(25.0, 43.3)
    print("Contur: OK")


if __name__ == "__main__":
    test_critic()
    test_vischeck()
    test_firms()
    test_uat()
    test_romania()
    test_merge_rules()
    test_arhiva_split()
    test_confirm_across_runs()
    test_autumn_cap()
    main()
