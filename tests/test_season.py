"""Detectorul pe o placă inventată: pădure de foioase (verde vara, desfrunzită iarna) și o tăiere făcută iarna.

Verifică ce a ratat testul pe 2025: o tăiere din ianuarie trebuie găsită primăvara, când pădurea din jur
înverzește, cu intervalul în care s-a putut întâmpla; iarna nu căutăm (zăpada și solul ud dau alarme false);
căderea frunzelor singură, fără tăiere, nu trebuie să dea nicio zonă.
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


LATE = {"days": 0, "partial": False}     # primăvara întârziată anul ăsta; tăiere parțială (rămân arbori)


def fake_scene(day, cut_day):
    rng = np.random.default_rng(day.toordinal())
    f = leafy(day - dt.timedelta(days=LATE["days"]) if day.year == 2025 else day)
    ndvi = np.full((H, W), 0.42 + 0.43 * f, np.float32) + rng.normal(0, 0.02, (H, W)).astype(np.float32)
    nbr = np.full((H, W), 0.22 + 0.38 * f, np.float32) + rng.normal(0, 0.02, (H, W)).astype(np.float32)
    if cut_day and day >= cut_day:
        if LATE["partial"]:   # rărire puternică: verdele scade puțin, NBR mai mult (ca în diagnostic)
            ndvi[CUT] -= 0.18 * f + 0.05
            nbr[CUT] -= 0.27 * f + 0.05
        else:
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


def test_winter_is_quiet():
    """Iarna nu căutăm: nicio zonă, nicio imagine folosită."""
    info, patches, rejected = run(dt.date(2025, 1, 1), dt.date(2025, 3, 1), CUT_DAY)
    assert info["status"] == "ok", info
    assert not patches and not rejected and not info["window_scenes"], info
    print("Iarna: nu căutăm")


def test_winter_cut_found_in_spring():
    """Tăierea din ianuarie apare primăvara, la prima imagine în care pădurea din jur are frunze."""
    info, patches, rejected = run(dt.date(2025, 4, 2), dt.date(2025, 6, 30), CUT_DAY)
    assert info["status"] == "ok", info
    assert len(patches) == 1, (info, [(p["ha"], p.get("motiv")) for p in patches + rejected])
    p = patches[0]
    assert 55 <= p["ha"] <= 70 and p["confirmed"], p
    assert "2025-05-01" <= p["first_seen"] <= "2025-05-20", p
    # n-am văzut-o intactă de curând (iarna nu ne uităm): intervalul pornește din vara trecută
    assert p["before_date"] is None and p["vara"] == 2024, p
    print("Tăierea din iarnă: găsită primăvara,", p["first_seen"], p["ha"], "ha")


def test_autumn_alone_is_quiet():
    info, patches, rejected = run(dt.date(2025, 9, 1), dt.date(2025, 11, 30), None)
    assert info["status"] == "ok", info
    assert not patches and not rejected, [(p["ha"], p["first_seen"], p.get("motiv")) for p in patches + rejected]
    assert len(info["window_scenes"]) >= 10, info
    print("Toamna fără tăieri: liniște,", len(info["window_scenes"]), "imagini folosite")


def test_summer_after_spring_is_old():
    """În iulie–septembrie, tăierea din iarnă nu mai e nouă: se vedea deja în imaginile din mai–iunie."""
    info, patches, rejected = run(dt.date(2025, 7, 2), dt.date(2025, 9, 30), CUT_DAY)
    assert not patches, [(p["ha"], p["first_seen"]) for p in patches]
    assert rejected and "deja" in rejected[0]["motiv"], rejected
    print("Vara: tăierea din iarnă e recunoscută ca veche")


def test_summer_cut_dated():
    """O tăiere din iulie: găsită la prima imagine de după, cu ultima zi intactă dinainte."""
    cut = dt.date(2025, 7, 20)
    info, patches, rejected = run(dt.date(2025, 7, 2), dt.date(2025, 9, 30), cut)
    assert len(patches) == 1, (info, [(p["ha"], p.get("motiv")) for p in patches + rejected])
    p = patches[0]
    assert dt.date.fromisoformat(p["first_seen"]) - cut < dt.timedelta(days=6) and p["before_date"] < p["first_seen"], p
    print("Tăierea din vară: găsită", p["first_seen"], "după", p["before_date"])


def test_partial_cut_found():
    """O rărire puternică vara (rămân arbori, crește iarbă): verdele scade cu ~0,2, NBR cu ~0,3. Trebuie găsită."""
    LATE["partial"] = True
    try:
        info, patches, rejected = run(dt.date(2025, 7, 2), dt.date(2025, 9, 30), dt.date(2025, 7, 20))
    finally:
        LATE["partial"] = False
    assert len(patches) == 1 and patches[0]["confirmed"], (info, [(p["ha"], p.get("motiv")) for p in patches + rejected])
    print("Rărirea din vară: găsită", patches[0]["first_seen"], patches[0]["ha"], "ha")


def test_late_spring_is_quiet():
    """Anul ăsta frunzele vin cu 12 zile mai târziu, peste tot: nu e nicio tăiere."""
    LATE["days"] = 12
    try:
        info, patches, rejected = run(dt.date(2025, 3, 20), dt.date(2025, 6, 17), None)
    finally:
        LATE["days"] = 0
    assert not patches, [(p["ha"], p["first_seen"]) for p in patches]
    print("Primăvara întârziată: liniște")


if __name__ == "__main__":
    test_winter_is_quiet()
    test_winter_cut_found_in_spring()
    test_autumn_alone_is_quiet()
    test_summer_after_spring_is_old()
    test_summer_cut_dated()
    test_partial_cut_found()
    test_late_spring_is_quiet()
