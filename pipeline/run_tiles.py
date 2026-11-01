"""Pasul 1 (în paralel, pe grupe de plăci): detectorul, imaginile înainte/după și părerea AI-ului.

python -m pipeline.run_tiles --group 0 --groups 8 --days 30 [--end 2026-10-30] [--judge]
"""
import argparse
import datetime as dt
import json
import subprocess
from collections import defaultdict

import numpy as np
from PIL import Image

from . import config as C
from .detect import detect_tile
from .rules import split
from .judge import backend, judge
from .sat import client, item_date, log, search
from .thumbs import thumbs_for

HANSEN = ["GFC-2025-v1.13", "GFC-2024-v1.12"]


def hansen_lossyear():
    d = C.DATA / "hansen"
    d.mkdir(parents=True, exist_ok=True)
    for ver in HANSEN:
        f = d / f"Hansen_{ver}_lossyear_50N_020E.tif"
        if f.exists() and f.stat().st_size > 1e6:
            return f
        url = f"https://storage.googleapis.com/earthenginepartners-hansen/{ver}/Hansen_{ver}_lossyear_50N_020E.tif"
        if subprocess.run(["curl", "-sfL", "--retry", "3", "-o", str(f), url]).returncode == 0 and f.stat().st_size > 1e6:
            log("Hansen:", ver)
            return f
        f.unlink(missing_ok=True)
    log("Hansen indisponibil, merg doar cu WorldCover")
    return None


def ro_checker():
    meta = json.load(open(C.DATA / "counties.json", encoding="utf-8"))
    cg = np.array(Image.open(C.DATA / "counties_grid.png"))

    def inside(lon0, lat0, lon1, lat1):
        for lo in np.linspace(lon0, lon1, 16):
            for la in np.linspace(lat0, lat1, 16):
                gy, gx = int((meta["north"] - la) / meta["cell"]), int((lo - meta["west"]) / meta["cell"])
                if 0 <= gy < cg.shape[0] and 0 <= gx < cg.shape[1] and cg[gy, gx] > 0:
                    return True
        return False
    return inside


def reuse_history(patches, days=60):
    """Zonele găsite iar în fiecare zi (fereastra e de 30 de zile) nu mai trec prin AI și nu mai primesc poze noi:
    luăm ce avem deja de la zona din istoric peste care cad (cel puțin jumătate din ele, văzute prima dată la cel
    mult `days` zile). Întoarce (câte au primit părerea AI, câte au deja poze)."""
    import os
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    if os.environ.get("PADUREA_AI_REUSE", "1") == "0":
        return 0, 0
    hist = []
    for f in (C.DOCS / "data" / "alerts.json", C.PENDING):
        if f.exists():
            hist += [h for h in json.loads(f.read_text(encoding="utf-8")).get("alerts", [])
                     if h.get("ai") or (h.get("img_before") and h.get("img_after"))]
    if not hist:
        return 0, 0
    geoms = [shape(h["geometry"]) for h in hist]
    tree = STRtree(geoms)
    n_ai = n_img = 0
    for p in patches:
        g = shape(p["geometry"])
        if g.area == 0:
            continue
        for i in tree.query(g):
            h = hist[int(i)]
            near = abs((dt.date.fromisoformat(h["first_seen"]) - dt.date.fromisoformat(p["first_seen"])).days) <= days
            if not near or g.intersection(geoms[int(i)]).area < 0.5 * g.area:
                continue
            if h.get("ai") and not p.get("ai"):
                p["ai"] = dict(h["ai"], refolosit=True)
                n_ai += 1
            if h.get("img_before") and h.get("img_after"):
                p["_known_img"] = True
                n_img += 1
            break
    return n_ai, n_img


def plan(cat, d0, d1):
    """Toate imaginile Sentinel-2 de care avem nevoie, pe plăci: fereastra, lunile dinainte, aceeași perioadă de acum
    un an (pentru referința de sezon a fiecărei imagini) și ultima vară (unde era pădure deasă)."""
    from .detect import summer_range
    r0 = d0 - dt.timedelta(days=C.RECENT_DAYS)
    ranges = {
        "window": (d0, d1),
        "recent": (r0, d0 - dt.timedelta(days=1)),
        "lastyear": (r0 - dt.timedelta(days=365 + C.SEASON_PAD + C.ANCHOR_DAYS),
                     d1 - dt.timedelta(days=365 - C.SEASON_PAD - C.ANCHOR_DAYS)),
        "summer": summer_range(d0),
    }
    by_tile = defaultdict(lambda: {"window": [], "recent": [], "lastyear": [], "summer": []})
    for key, (a, b) in ranges.items():
        items = search(cat, "sentinel-2-l2a", C.RO_BBOX, a.isoformat(), b.isoformat(), cloud=C.MAX_SCENE_CLOUD)
        log(f"  {key}: {a} – {b}: {len(items)} imagini")
        for it in items:
            by_tile[it.properties.get("s2:mgrs_tile")][key].append(it)
    return by_tile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", type=int, default=0)
    ap.add_argument("--groups", type=int, default=1)
    ap.add_argument("--days", type=int, default=C.WINDOW_DAYS)
    ap.add_argument("--end", default="")
    ap.add_argument("--tiles", default="", help="doar aceste plăci, separate prin virgulă (pentru teste)")
    ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()

    d1 = dt.date.fromisoformat(a.end) if a.end else dt.date.today()
    d0 = d1 - dt.timedelta(days=a.days - 1)
    log(f"Grupa {a.group}/{a.groups}: schimbări apărute între {d0} și {d1}")
    cat = client()
    by_tile = plan(cat, d0, d1)
    tiles = sorted((t for t, v in by_tile.items() if v["window"]), key=lambda t: (-len(by_tile[t]["window"]), t))
    if a.tiles:
        tiles = [t for t in tiles if t in a.tiles.split(",")]
    mine = [t for i, t in enumerate(tiles) if i % a.groups == a.group]
    log(f"Plăci cu imagini noi: {len(tiles)}; în grupa asta: {len(mine)} {mine}")

    lossyear = hansen_lossyear()
    inside = ro_checker()
    out_img = C.OUT / "img"
    infos, patches, rejected = [], [], []
    for n, tile in enumerate(mine, 1):
        log(f"Placa {tile} ({n}/{len(mine)}): {len(by_tile[tile]['window'])} imagini noi, "
            f"{len(by_tile[tile]['recent'])} recente, {len(by_tile[tile]['lastyear'])} de anul trecut, "
            f"{len(by_tile[tile]['summer'])} din vară")
        try:
            info, ps, rj = detect_tile(cat, tile, by_tile[tile], d0, d1, lossyear, inside)
        except Exception as exc:
            info, ps, rj = {"tile": tile, "status": f"eroare: {repr(exc)[:200]}"}, [], []
            log("  eroare:", repr(exc)[:300])
        for i, p in enumerate(ps):
            p["key"] = f"{tile}-{i}"
        for i, p in enumerate(rj):
            p["key"] = f"{tile}-r{i}"
        ps, rr = split(ps)
        rj += rr
        log(f"  {info.get('status')}: {len(ps)} zone păstrate, {len(rj)} respinse; "
            f"imagini folosite: {info.get('window_scenes')}")
        infos.append(info)
        patches += ps
        rejected += rj

    patches.sort(key=lambda p: -p["ha"])
    rejected.sort(key=lambda p: -p["ha"])
    every = list(by_tile.values())
    # pozele „înainte” pot veni și din vară, dacă iarna n-a fost nicio zi senină peste zonă
    items_by_tile = {t: v["window"] + v["recent"] + v["summer"] for t, v in by_tile.items()}
    conf = [p for p in patches if p.get("confirmed")]
    n_ai, n_img = reuse_history(patches)
    # pozele: întâi zonele confirmate care n-au încă poze în istoric, apoi (dacă mai e loc) celelalte
    fresh = [p for p in conf if not p.get("_known_img")]
    known = [p for p in conf if p.get("_known_img")]
    shots = (fresh + known)[:C.THUMB_MAX_CONFIRMED]
    singles = [p for p in patches if not p.get("confirmed") and not p.get("_known_img")][:C.THUMB_SINGLES]
    rconf = [p for p in rejected if p.get("confirmed")][:40]   # și câteva respinse, ca să verificăm regulile
    log(f"Imagini înainte/după: {len(shots)} din {len(conf)} zone confirmate ({n_img} au deja poze din rulările trecute), "
        f"{len(singles)} neconfirmate, {len(rconf)} respinse (control)")
    thumbs_for(shots + singles + rconf, items_by_tile, out_img)

    which = backend() if a.judge else None
    if which and conf:
        todo = [p for p in conf if not p.get("ai")][:C.JUDGE_MAX_PER_GROUP]
        log(f"Judecătorul AI ({which}): {n_ai} zone aveau deja părerea lui din rulările trecute; "
            f"acum cel mult {C.JUDGE_MAX_PER_GROUP} din celelalte {sum(1 for p in conf if not p.get('ai'))}")
        for p in todo + rejected[:3]:
            b, af = p.get("img_before"), p.get("img_after")
            if not af:
                continue
            try:
                p["ai"] = judge(out_img / b["file"] if b else None, out_img / af["file"],
                                b["date"] if b else "?", af["date"], which)
                log(f"  {p['key']}: {p['ai']['categorie']} ({p['ai']['incredere']}) {p['ai']['secunde']}s – {p['ai']['motiv'][:80]}")
            except Exception as exc:
                log("  AI sărit pentru", p["key"], repr(exc)[:150])

    C.OUT.mkdir(parents=True, exist_ok=True)
    res = {"group": a.group, "groups": a.groups, "d0": d0.isoformat(), "d1": d1.isoformat(),
           "tiles": infos, "patches": patches, "rejected": rejected,
           "n_tiles_total": len(tiles), "n_items": sum(len(v["window"]) for v in every)}
    (C.OUT / f"group_{a.group}.json").write_text(json.dumps(res, ensure_ascii=False))
    log(f"Gata grupa {a.group}: {len(conf)} zone confirmate, {len(patches) - len(conf)} neconfirmate, {len(rejected)} respinse.")


if __name__ == "__main__":
    main()
