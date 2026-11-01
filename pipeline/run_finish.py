"""Pasul 2: unește grupele, scoate dublurile, ține minte istoricul, adaugă contextul, criticul și textul, publică.

Istoricul stă în docs/data/alerts.json (ultimele 90 de zile), în arhiva pe luni și în data/neconfirmate.json
(zonele încă neconfirmate, care nu apar pe site; vezi pipeline/arhiva.py).
O zonă găsită azi se potrivește cu cele vechi așa:
  - peste jumătate din ea e peste o zonă veche: e aceeași tăiere, văzută iar; actualizăm zona veche
  - atinge o zonă veche care s-a schimbat în ultimele EXT_DAYS zile: tăierea se lărgește; unim zonele
  - atinge o zonă veche în care nu s-a mai schimbat nimic de atunci: e o zonă nouă, cu legătură spre cea veche
    (altfel o tăiere nouă lângă una veche ar primi data veche și n-ar apărea la „ultimele 30 de zile”)

python -m pipeline.run_finish
"""
import datetime as dt
import json
import shutil

from . import arhiva, arii, critic, firms, uat, vischeck, writer
from . import config as C
from .context import add_context
from .sat import log

ALERTS = C.DOCS / "data" / "alerts.json"
RUNS = C.DOCS / "data" / "runs.json"
SAME = 0.5          # cât din zona nouă trebuie să fie peste una veche ca să fie aceeași tăiere
EXT_DAYS = 14       # cât timp după ultima schimbare o lărgire mai ține de aceeași zonă
BUF = 0.0002        # ~20 m: zonele care se ating


def shp(g):
    from shapely.geometry import shape
    return shape(g)


def geojson(g, digits=6):
    from shapely.geometry import mapping
    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], digits), round(c[1], digits)]
    m = json.loads(json.dumps(mapping(g)))
    m["coordinates"] = rnd(m["coordinates"])
    return m


def load_groups():
    groups = [json.loads(f.read_text()) for f in sorted(C.OUT.glob("group_*.json"))]
    if not groups:
        raise SystemExit("Nu am găsit rezultatele grupelor în out/")
    return groups


def dedup(patches):
    """Același loc văzut din două plăci vecine: păstrăm zona cea mai mare și unim datele."""
    kept = []
    for p in sorted(patches, key=lambda p: -p["ha"]):
        g = shp(p["geometry"])
        twin = next((k for k in kept if k["tile"] != p["tile"] and k["_g"].intersects(g)), None)
        if twin is None:
            p["_g"] = g
            kept.append(p)
            continue
        twin["first_seen"] = min(twin["first_seen"], p["first_seen"])
        twin["n_dates"] = max(twin["n_dates"], p["n_dates"])
        twin["confirmed"] = bool(twin.get("confirmed") or p.get("confirmed"))
        if not twin.get("ai") and p.get("ai"):
            twin["ai"] = p["ai"]
    return kept


def new_id(p):
    return f"{p['first_seen'].replace('-', '')}_{round(p['lat'] * 1000)}_{round(p['lon'] * 1000)}"


def _seen_again(m, p, same=True):
    """Aceeași zonă (same=True) sau una care o lărgește, văzută iar: date, număr de imagini, perechea de poze
    cea mai nouă."""
    m["first_seen"] = min(m["first_seen"], p["first_seen"])
    m["n_dates"] = max(m.get("n_dates", 0), p.get("n_dates", 0))
    # același loc, văzut schimbat și într-o imagine mai nouă decât data trecută: e confirmat
    again = same and p["after_date"] > m.get("after_date", "")
    m["confirmed"] = bool(m.get("confirmed") or p.get("confirmed") or again or m["n_dates"] >= C.CONFIRM_DATES)
    if p["after_date"] > m["after_date"]:
        m["after_date"] = p["after_date"]
        if p.get("img_after") and p.get("key"):
            for k in ("img_before", "img_after", "chip_bbox"):   # pozele și conturul lor merg împreună
                if p.get(k):
                    m[k] = p[k]
            m["_new_imgs"] = p["key"]
    if p.get("ai") and not m.get("ai"):
        m["ai"] = p["ai"]


def merge_history(found, hist):
    """Potrivește zonele găsite acum cu istoricul (recente + arhivă). Adaugă la hist zonele noi (cu _src="n").
    Întoarce (numărători, id-urile zonelor vechi atinse)."""
    from shapely.strtree import STRtree
    for h in hist:
        h["_g"] = shp(h["geometry"])
    tree = STRtree([h["_g"] for h in hist]) if hist else None
    n = {"noi": 0, "actualizate": 0, "largite": 0, "langa_altele": 0}
    touched, new = set(), []
    for p in found:
        g, best, frac = p["_g"], None, 0.0
        if tree is not None:
            for i in tree.query(g.buffer(BUF)):
                h = hist[int(i)]
                hb = h["_g"].buffer(BUF)
                if not hb.intersects(g):
                    continue
                try:
                    f = g.intersection(hb).area / g.area if g.area else 1.0
                except Exception:
                    f = 1.0
                if best is None or f > frac:
                    best, frac = h, f
        if best is not None and frac >= SAME:
            _seen_again(best, p)
            if p["ha"] > best["ha"]:
                for k in ("ha", "geometry", "bbox", "lat", "lon"):
                    best[k] = p[k]
                best["_g"] = g
            touched.add(best["id"])
            n["actualizate"] += 1
            continue
        if best is not None:
            gap = (dt.date.fromisoformat(p["first_seen"]) - dt.date.fromisoformat(best["after_date"])).days
            if gap <= EXT_DAYS:
                _seen_again(best, p, same=False)
                u = best["_g"].union(g)
                best["geometry"], best["_g"] = geojson(u), u
                best["ha"] = round(best["ha"] + p["ha"] * (1 - frac), 1)
                best["bbox"] = [round(x, 5) for x in u.bounds]
                best["extinsa"] = max(best.get("extinsa") or "", p["first_seen"])
                touched.add(best["id"])
                n["largite"] += 1
                continue
            p["langa"] = {"id": best["id"], "first_seen": best["first_seen"]}
            n["langa_altele"] += 1
        p["id"] = new_id(p)
        p["created"] = dt.date.today().isoformat()
        p["_src"] = "n"
        new.append(p)
        n["noi"] += 1
    hist.extend(new)
    return n, touched


def publish_images(alerts):
    """Pozele zonelor noi și ale celor vechi care au primit o pereche mai nouă: img/<id>_b.webp și img/<id>_a.webp."""
    dst = C.DOCS / "img"
    dst.mkdir(parents=True, exist_ok=True)
    src = C.OUT / "img"
    for a in alerts:
        key = a.pop("key", None)
        source_key = a.pop("_new_imgs", None) or key
        if not source_key:
            continue
        for side, k in (("img_before", "b"), ("img_after", "a")):
            info = a.get(side)
            if not info:
                continue
            fname = f"{a['id']}_{k}.webp"
            if (src / f"{source_key}_{k}.webp").exists():
                shutil.copy(src / f"{source_key}_{k}.webp", dst / fname)
            info["file"] = fname


def main():
    groups = load_groups()
    d0 = min(g["d0"] for g in groups)
    d1 = max(g["d1"] for g in groups)
    tiles = [t for g in groups for t in g["tiles"]]
    patches = [p for g in groups for p in g["patches"]]
    rejected = [p for g in groups for p in g["rejected"]]
    log(f"Fereastra {d0} – {d1}: {len(patches)} zone din {len(tiles)} plăci, {len(rejected)} respinse")
    found = dedup(patches)
    log(f"După dubluri: {len(found)}")

    doc = json.loads(ALERTS.read_text()) if ALERTS.exists() else {"alerts": []}
    months = arhiva.load()
    hist = ([dict(a, _src="r") for a in doc.get("alerts", [])] + [dict(a, _src="r") for a in arhiva.load_pending()]
            + [dict(a, _src="m") for zone in months.values() for a in zone])
    n, touched = merge_history(found, hist)
    log(f"Istoric: {n['noi']} noi ({n['langa_altele']} lângă zone mai vechi), {n['actualizate']} văzute iar, "
        f"{n['largite']} lărgite; {len(hist)} în total")

    # lucrăm doar pe zonele recente și pe cele atinse azi; restul arhivei rămâne neatins
    live = [a for a in hist if a["_src"] in ("r", "n") or a["id"] in touched]
    rest = {m: [a for a in zone if a["id"] not in touched] for m, zone in months.items()}
    publish_images([a for a in live if "key" in a or "_new_imgs" in a])

    todo = [a for a in live if a["first_seen"] >= d0 or (a.get("extinsa") or "") >= d0]  # contextul: doar fereastra curentă
    lossyear = next(iter(sorted((C.DATA / "hansen").glob("*lossyear*.tif"))), None) if (C.DATA / "hansen").exists() else None
    add_context(todo, lossyear)
    firms.apply(todo, C.DOCS / "data" / "firms.geojson")
    log(f"Verificarea pe poze: {vischeck.apply(live, C.DOCS / 'img')} zone cu ambele poze")
    critic.apply(live)
    uat.apply(live)  # numele comunelor, în ortografia de azi, și pentru zonele vechi atinse
    log(f"Arii protejate: {arii.apply(live)} din {len(live)} zone")
    writer.apply(live)

    clean = []
    for a in live:
        a.pop("_g", None)
        clean.append({k: v for k, v in a.items() if not k.startswith("_") and k not in ("key", "motiv")})
    recent, old, pending, expired = arhiva.split(clean, d1)
    for a in old:
        rest.setdefault(arhiva.month(a), []).append(a)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")
    index = arhiva.save(rest, now)
    n_img = arhiva.save_pending(pending, expired, now)
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    arhiva.write_recent(ALERTS, doc, recent, d1, [d0, d1], now)
    log(f"Pe site din start: {len(recent)} zone; în arhivă: {sum(i['n'] for i in index)}; "
        f"neconfirmate (nu apar pe site): {len(pending)} în așteptare, {len(expired)} uitate, {n_img} poze scoase")

    runs = json.loads(RUNS.read_text()) if RUNS.exists() else []
    seen_ha = sum(t.get("forest_ha", 0) for t in tiles if t.get("status") == "ok")
    runs.append({
        "time": now, "window": [d0, d1], "tiles": len(tiles),
        "tiles_ok": sum(1 for t in tiles if t.get("status") == "ok"),
        "forest_ha_checked": seen_ha, "found": len(found), "new": n["noi"], "updated": n["actualizate"],
        "extended": n["largite"], "near_older": n["langa_altele"], "pending": len(pending), "expired": len(expired),
        "rejected_neighbors": len(rejected), "judge": next((p["ai"]["model"] for p in patches if p.get("ai")), None),
        "tile_status": [{k: t.get(k) for k in ("tile", "status", "bbox", "window_scenes", "skipped", "patches", "rejected")} for t in tiles],
    })
    RUNS.write_text(json.dumps(runs[-60:], ensure_ascii=False, separators=(",", ":")))
    lv = {}
    for a in recent:
        lv[a["incredere"]] = lv.get(a["incredere"], 0) + 1
    log(f"Publicat: {len(recent)} alerte recente {lv}")


if __name__ == "__main__":
    main()
