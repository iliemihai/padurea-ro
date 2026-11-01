"""Detectorul pe o placă inventată: pădure de foioase (verde vara, desfrunzită iarna) și o tăiere făcută iarna.

Verifică ce a ratat testul pe 2025: o tăiere din ianuarie trebuie găsită în ianuarie–martie, cu data ei; căderea
frunzelor singură, fără tăiere, nu trebuie să dea nicio zonă.
"""
import datetime as dt
import types

import numpy as np

H = W = 160
CUT = (slice(40, 60), slice(40, 60))      # 400 de pixeli de 40 m = 64 ha
CUT_DAY = dt.date(2025, 1, 20)


def leafy(day):
    """Cât de „cu frunze” e pădurea în ziua asta: 0 iarna, 1 vara, cu tranziții primăvara și toamna."""
    doy = day.timetuple().tm_yday
    if doy < 100 or doy > 320:
        return 0.0
    if doy < 140:
        return (doy - 100) / 40
    if doy > 280:
        return (320 - doy) / 40
    return 1.0


def fake_scene(day, cut_day):
    rng = np.random.default_rng(day.toordinal())
    f = leafy(day)
    ndvi = np.full((H, W), 0.42 + 0.43 * f, np.float32) + rng.normal(0, 0.02, (H, W)).astype(np.float32)
    nbr = np.full((H, W), 0.22 + 0.38 * f, np.float32) + rng.normal(0, 0.02, (H, W)).astype(np.float32)
    if cut_day and day >= cut_day:
        ndvi[CUT] = 0.22 + 0.2 * f
        nbr[CUT] = -0.02 + 0.08 * f
    clear = np.ones((H, W), bool)
    return clear, ndvi, nbr


def item(day, cloud=10):
    return types.SimpleNamespace(id=f"S2_{day.isoformat()}", datetime=dt.datetime(day.year, day.month, day.day, 9),
                                 properties={"eo:cloud_cover": cloud})


def run(d0, d1, cut_day):
    from affine import Affine
    from pipeline import config as C
    from pipeline import detect as D

    def read_scene(it, grid, pool=None, full=False):
        clear, ndvi, nbr = fake_scene(it.datetime.date(), cut_day)
        if full:
            return clear, ndvi, nbr, np.full((H, W), 0.03, np.float32), np.full((H, W), 0.04, np.float32)
        return clear, ndvi, nbr

    D.read_scene = read_scene
    D.tile_grid = lambda it: ("EPSG:32635", Affine(40, 0, 400000, 0, -40, 5100000), W, H)
    D.county_raster = lambda grid: (np.ones((H, W), np.uint8), ["Brașov"])
    forest = np.zeros((H, W), bool)
    forest[5:-5, 5:-5] = True
    D.forest_mask = lambda *a, **k: forest

    def days(a, b, step=5):
        return [a + dt.timedelta(days=i) for i in range(0, (b - a).days + 1, step)]
    r0 = d0 - dt.timedelta(days=C.RECENT_DAYS)
    s0, s1 = D.summer_range(d0)
    items = {
        "window": [item(d) for d in days(d0, d1)],
        "recent": [item(d) for d in days(r0, d0 - dt.timedelta(days=1))],
        "lastyear": [item(d) for d in days(r0 - dt.timedelta(days=400), d1 - dt.timedelta(days=320))],
        "summer": [item(d) for d in days(s0, s1)],
    }
    return D.detect_tile(None, "35TLM", items, d0, d1, None, lambda *a: True)


def test_winter_cut_found():
    info, patches, rejected = run(dt.date(2025, 1, 1), dt.date(2025, 3, 31), CUT_DAY)
    assert info["status"] == "ok", info
    assert len(patches) == 1, (info, [(p["ha"], p.get("motiv")) for p in patches + rejected])
    p = patches[0]
    assert 55 <= p["ha"] <= 70 and p["confirmed"], p
    assert dt.date.fromisoformat(p["first_seen"]) - CUT_DAY < dt.timedelta(days=6), p
    assert p["before_date"] and p["before_date"] < p["first_seen"], p
    print("Tăierea din iarnă: găsită", p["first_seen"], p["ha"], "ha")


def test_autumn_alone_is_quiet():
    info, patches, rejected = run(dt.date(2025, 10, 3), dt.date(2025, 12, 31), None)
    assert info["status"] == "ok", info
    assert not patches and not rejected, [(p["ha"], p["first_seen"], p.get("motiv")) for p in patches + rejected]
    assert len(info["window_scenes"]) >= 15, info
    print("Toamna fără tăieri: liniște,", len(info["window_scenes"]), "imagini folosite")


def test_spring_after_winter_cut_is_old():
    """În aprilie–iunie, o tăiere din ianuarie nu e nouă: se vedea deja în imaginile dinaintea ferestrei."""
    info, patches, rejected = run(dt.date(2025, 4, 2), dt.date(2025, 6, 30), CUT_DAY)
    assert not patches, [(p["ha"], p["first_seen"]) for p in patches]
    assert rejected and "deja" in rejected[0]["motiv"], rejected
    print("Primăvara: tăierea din iarnă e recunoscută ca veche")


if __name__ == "__main__":
    test_winter_cut_found()
    test_autumn_alone_is_quiet()
    test_spring_after_winter_cut_is_old()
