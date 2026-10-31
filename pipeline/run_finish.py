"""Pasul 2: unește grupele, scoate dublurile, ține minte istoricul, adaugă contextul, criticul și textul, publică.

python -m pipeline.run_finish
"""
import datetime as dt
import json
import shutil

from . import config as C
from . import critic, vischeck, writer
from .context import add_context
from .sat import log

ALERTS = C.DOCS / "data" / "alerts.json"
RUNS = C.DOCS / "data" / "runs.json"
KEEP = ("tile", "ha", "lat", "lon", "county", "first_seen", "before_date", "after_date", "n_dates",
        "ndvi_ref", "nbr_ref", "neigh_drop", "persist", "geometry", "bbox", "chip_bbox", "ai")


def shp(g):
    from shapely.geometry import shape
    return shape(g)


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
        if not twin.get("ai") and p.get("ai"):
            twin["ai"] = p["ai"]
    return kept


def new_id(p):
    return f"{p['first_seen'].replace('-', '')}_{round(p['lat'] * 1000)}_{round(p['lon'] * 1000)}"


def merge_history(found, history, window_start):
    """Zonele găsite acum se potrivesc cu cele din istoric după suprafață comună."""
    hist = history.get("alerts", [])
    for h in hist:
        h["_g"] = shp(h["geometry"])
    added, updated = 0, 0
    for p in found:
        g = p["_g"]
        match = next((h for h in hist if h["_g"].buffer(0.0002).intersects(g)), None)
        if match is None:
            p["id"] = new_id(p)
            p["created"] = dt.date.today().isoformat()
            hist.append(p)
            added += 1
            continue
        updated += 1
        match["first_seen"] = min(match["first_seen"], p["first_seen"])
        match["n_dates"] = max(match.get("n_dates", 0), p["n_dates"])
        if p["after_date"] > match["after_date"]:
            match["after_date"] = p["after_date"]
            if p.get("img_after"):
                match["img_after"] = p["img_after"]
                match["_new_after"] = p["key"]
        if p["ha"] > match["ha"]:
            for k in ("ha", "geometry", "bbox", "lat", "lon"):
                match[k] = p[k]
        if p.get("ai") and not match.get("ai"):
            match["ai"] = p["ai"]
        match["_g"] = shp(match["geometry"])
    return hist, added, updated


def publish_images(alerts):
    dst = C.DOCS / "img"
    dst.mkdir(parents=True, exist_ok=True)
    src = C.OUT / "img"
    for a in alerts:
        key = a.pop("key", None)
        new_after = a.pop("_new_after", None)
        for side, k in (("img_before", "b"), ("img_after", "a")):
            info = a.get(side)
            if not info:
                continue
            fname = f"{a['id']}_{k}.webp"
            source_key = new_after if (side == "img_after" and new_after) else key
            if source_key and (src / f"{source_key}_{k}.webp").exists():
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

    history = json.loads(ALERTS.read_text()) if ALERTS.exists() else {"alerts": []}
    alerts, added, updated = merge_history(found, history, d0)
    log(f"Istoric: {added} noi, {updated} actualizate, {len(alerts)} în total")
    publish_images([a for a in alerts if "key" in a or "_new_after" in a])

    todo = [a for a in alerts if a["first_seen"] >= d0]  # contextul se recalculează doar pentru fereastra curentă
    lossyear = next(iter(sorted((C.DATA / "hansen").glob("*lossyear*.tif"))), None) if (C.DATA / "hansen").exists() else None
    add_context(todo, lossyear)
    log(f"Verificarea pe poze: {vischeck.apply(alerts, C.DOCS / 'img')} zone cu ambele poze")
    critic.apply(alerts)
    writer.apply(alerts)

    clean = []
    for a in alerts:
        a.pop("_g", None)
        clean.append({k: v for k, v in a.items() if not k.startswith("_") and k not in ("key", "motiv")})
    clean.sort(key=lambda a: (a["first_seen"], a["ha"]), reverse=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    ALERTS.write_text(json.dumps({"generated": now, "data_until": d1, "window": [d0, d1], "alerts": clean},
                                 ensure_ascii=False, separators=(",", ":")))
    runs = json.loads(RUNS.read_text()) if RUNS.exists() else []
    seen_ha = sum(t.get("forest_ha", 0) for t in tiles if t.get("status") == "ok")
    runs.append({
        "time": now, "window": [d0, d1], "tiles": len(tiles),
        "tiles_ok": sum(1 for t in tiles if t.get("status") == "ok"),
        "forest_ha_checked": seen_ha, "found": len(found), "new": added, "updated": updated,
        "rejected_neighbors": len(rejected), "judge": next((p["ai"]["model"] for p in patches if p.get("ai")), None),
        "tile_status": [{k: t.get(k) for k in ("tile", "status", "bbox", "window_scenes", "skipped", "patches", "rejected")} for t in tiles],
    })
    RUNS.write_text(json.dumps(runs[-60:], ensure_ascii=False, separators=(",", ":")))
    lv = {}
    for a in clean:
        lv[a["incredere"]] = lv.get(a["incredere"], 0) + 1
    log(f"Publicat: {len(clean)} alerte {lv}")


if __name__ == "__main__":
    main()
