"""Peisajul din jurul fiecărei zone: ce lipsea AI-ului și regulilor ca să deosebească o tăiere de pădure de restul.

O poză de 10 m nu spune unde ești. Aici punem, pentru fiecare zonă, fapte luate din surse publice, o singură dată:
  - relieful: altitudinea și panta (Copernicus DEM 30 m) -> câmpie / deal / munte
  - ce e în zonă și pe 500 m în jur (ESA WorldCover 2021, 10 m): copaci, pășune, arabil, construit, apă
  - cât de des era coronamentul înainte (Hansen treecover2000, 30 m): pădure închisă sau copaci răzleți
  - cât de aproape e drumul mare, calea ferată, apa și satul (OpenStreetMap, prin Overpass)
  - forma schimbării: alungire, lățime
și din ele un „fel de loc”: pădure închisă / pășune cu copaci / câmp / lângă drum sau cale ferată / mal de apă / la marginea
satului. Nu e un verdict, e context: judecătorul AI și regulile îl folosesc, iar fișa îl arată omului.

    python -m pipeline.peisaj                 zonele fără context (nou apărute)
    python -m pipeline.peisaj --full          toate
    python -m pipeline.peisaj --limit 50      pentru probe

Scrie docs/data/peisaj.json: {"zone": {id: {...}}, "generated": ...}. Rezultatele vechi rămân.
"""
import argparse
import datetime as dt
import json
import math
import sys
import time

import numpy as np

from . import config as C
from .permise import zone_site, forma, in_metri, m_per_deg_lon, M_PER_DEG_LAT

OUT = C.DOCS / "data" / "peisaj.json"
OVERPASS = "https://overpass-api.de/api/interpreter"
INEL_M = 500          # inelul din jurul zonei pentru „ce e în jur”
RAZA_OSM_M = 1500     # cât de departe căutăm drumuri, ape, sate

WC = {10: "copaci", 20: "tufe", 30: "pasune", 40: "arabil", 50: "construit", 60: "gol", 70: "zapada", 80: "apa", 90: "mlastina", 95: "mangrove", 100: "muschi"}
DRUM_MARE = {"motorway", "trunk", "primary", "secondary", "tertiary"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- rastere din Planetary Computer
def _client():
    import planetary_computer as pc
    from pystac_client import Client
    return Client.open(C.PC_URL, modifier=pc.sign_inplace)


def _bbox_pad(g, pad_m):
    lat = g.centroid.y
    dlat = pad_m / 111320.0
    dlon = dlat / max(math.cos(math.radians(lat)), 0.2)
    w, s, e, n = g.bounds
    return [w - dlon, s - dlat, e + dlon, n + dlat]


_ITEMS, _SRC = {}, {}
RO_BBOX = [20.2, 43.5, 30.0, 48.3]


def _items(cat, colectie, data):
    """Plăcile colecției peste toată România, căutate o singură dată."""
    if colectie not in _ITEMS:
        _ITEMS[colectie] = list(cat.search(collections=[colectie], bbox=RO_BBOX, datetime=f"{data[0]}/{data[1]}" if data else None, max_items=400).items())
        log(f"  {colectie}: {len(_ITEMS[colectie])} plăci")
    return _ITEMS[colectie]


def _src(it, asset_key):
    """Fișierul deschis (COG, citim doar ferestre), ținut deschis între zone."""
    import rasterio
    if it.id not in _SRC:
        asset = it.assets.get(asset_key) if asset_key else None
        if asset is None:
            asset = next(a for a in it.assets.values() if a.href.split("?")[0].endswith(".tif"))
        _SRC[it.id] = rasterio.open(asset.href)
    return _SRC[it.id]


def _citeste(cat, colectie, bbox, asset_key=None, data=("2021-01-01", "2021-12-31")):
    """Fereastra `bbox` (grade) dintr-o colecție în EPSG:4326: (array, transform). Lipește bucățile dacă bbox atinge două plăci."""
    from rasterio.merge import merge
    from rasterio.windows import from_bounds
    from rasterio.io import MemoryFile
    from shapely.geometry import box, shape
    cerut = box(*bbox)
    items = [it for it in _items(cat, colectie, data) if shape(it.geometry).intersects(cerut)]
    if not items:
        return None, None
    bucati = []
    for it in items[:4]:
        src = _src(it, asset_key)
        w = from_bounds(*bbox, transform=src.transform)
        arr = src.read(1, window=w, boundless=True, fill_value=src.nodata if src.nodata is not None else 0)
        tr = src.window_transform(w)
        bucati.append((arr, tr, src.crs, src.nodata))
    if len(bucati) == 1:
        return bucati[0][0], bucati[0][1]
    srcs = []
    for arr, tr, crs, nd in bucati:
        mem = MemoryFile()
        with mem.open(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype=arr.dtype, crs=crs, transform=tr, nodata=nd) as d:
            d.write(arr, 1)
        srcs.append(mem.open())
    a, tr = merge(srcs)
    for s_ in srcs:
        s_.close()
    return a[0], tr


def _masca(g, shape, tr):
    from rasterio.features import rasterize
    return rasterize([(g, 1)], out_shape=shape, transform=tr, fill=0, dtype="uint8").astype(bool)


def compozitie(arr, m):
    """Procentele claselor WorldCover pe masca m."""
    v = arr[m]
    v = v[v > 0]
    if v.size == 0:
        return None
    out = {}
    for k, nume in WC.items():
        p = float((v == k).mean() * 100)
        if p >= 0.5:
            out[nume] = round(p)
    return out


def relief(alt, panta):
    if alt is None:
        return None
    if alt < 300:
        return "câmpie"
    if alt < 800:
        return "deal"
    return "munte"


# ---------------------------------------------------------------- OpenStreetMap
def _q_osm(puncte, raza):
    """Elementele OSM din jurul mai multor puncte, într-o singură cerere (loturile fac Overpass de 20 de ori mai ieftin)."""
    import requests
    ar = lambda tag: "\n".join(f'  way(around:{raza},{lat},{lon}){tag};' for lat, lon in puncte)
    taguri = ['[highway~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|track|service|motorway_link|trunk_link|primary_link|construction|proposed)$"]',
              '[railway~"^(rail|construction|proposed|narrow_gauge)$"]', '[waterway~"^(river|stream|canal)$"]', '[natural=water]',
              '[landuse~"^(residential|industrial|quarry)$"]', '[power=line]', '[man_made=pipeline]']
    q = "[out:json][timeout:180];\n(\n" + "\n".join(ar(t) for t in taguri) + "\n);\nout tags geom;"
    for incercare in range(3):
        try:
            r = requests.post(OVERPASS, data={"data": q}, timeout=200, headers={"User-Agent": "padurea-ro/1.0 (+https://github.com/iliemihai/padurea-ro)"})
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(30 * (incercare + 1)); continue
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as e:
            log("  overpass:", repr(e)[:100]); time.sleep(15 * (incercare + 1))
    return None


_OSM_LOT = {}


def osm_lot(zone_lot, raza=RAZA_OSM_M):
    """Pregătește, pentru un lot de zone, elementele OSM; fiecare zonă își ia apoi doar ce e în raza ei."""
    from shapely.geometry import shape, LineString
    puncte = [(shape(a["geometry"]).centroid.y, shape(a["geometry"]).centroid.x) for a in zone_lot]
    el = _q_osm(puncte, raza)
    if el is None:
        return
    for a, (lat, lon) in zip(zone_lot, puncte):
        dlat = raza / 111320.0; dlon = dlat / max(math.cos(math.radians(lat)), 0.2)
        aproape = []
        for e in el:
            g = e.get("geometry") or []
            if any(abs(p["lat"] - lat) <= dlat and abs(p["lon"] - lon) <= dlon for p in g[:: max(1, len(g) // 40)]):
                aproape.append(e)
        _OSM_LOT[a["id"]] = aproape


def osm_in_jur(a):
    return _OSM_LOT.get(a["id"])


def distante_osm(g, elems):
    """Distanțe (m) de la zonă la cel mai apropiat element din fiecare fel."""
    from shapely.geometry import LineString, Polygon
    lat = g.centroid.y
    gm = in_metri(g, lat)
    best = {}

    def pune(fel, geom, eticheta=None):
        d = gm.distance(in_metri(geom, lat))
        if fel not in best or d < best[fel][0]:
            best[fel] = (d, eticheta)

    for e in elems or []:
        pts = [(p["lon"], p["lat"]) for p in e.get("geometry", [])]
        if len(pts) < 2:
            continue
        t = e.get("tags", {})
        inchis = pts[0] == pts[-1] and len(pts) >= 4
        geom = Polygon(pts) if inchis and (t.get("landuse") or t.get("natural")) else LineString(pts)
        if not geom.is_valid:
            geom = geom.buffer(0)
        hw = t.get("highway")
        if hw in DRUM_MARE or hw in ("motorway_link", "trunk_link", "primary_link"):
            pune("drum_mare", geom, hw)
        if hw in ("construction", "proposed"):
            pune("drum_in_lucru", geom, (t.get("construction") or t.get("proposed") or hw) + (" " + t["name"] if t.get("name") else ""))
        if hw:
            pune("drum", geom, hw)
        rw = t.get("railway")
        if rw in ("rail", "narrow_gauge"):
            pune("cale_ferata", geom, rw)
        if rw in ("construction", "proposed"):
            pune("cale_ferata_in_lucru", geom, rw)
        if t.get("waterway"):
            pune("apa", geom, (t.get("waterway") + (" " + t["name"] if t.get("name") else "")))
        if t.get("natural") == "water":
            pune("apa", geom, "lac")
        lu = t.get("landuse")
        if lu in ("residential", "industrial"):
            pune("intravilan", geom, lu)
        if lu == "quarry":
            pune("cariera", geom, lu)
        if lu in ("farmland", "farmyard", "meadow", "orchard", "vineyard"):
            pune("agricol_osm", geom, lu)
        if t.get("power") == "line":
            pune("linie_electrica", geom, "LEA")
        if t.get("man_made") == "pipeline":
            pune("conducta", geom, "conductă")
    return {k: {"m": int(round(v[0])), "ce": v[1]} for k, v in best.items()}


# ---------------------------------------------------------------- felul locului
def fel_loc(p):
    """Un cuvânt pentru om, din cifre. Ordinea contează: întâi ce exclude pădurea."""
    z, j = p.get("wc_zona") or {}, p.get("wc_jur") or {}
    copaci = z.get("copaci", 0)
    cor = p.get("coronament2000")
    o = p.get("osm") or {}
    alung, lat_m = p.get("alungire") or 1, p.get("latime_m") or 999
    motive = []
    if alung >= 5 and lat_m <= 120:
        motive.append("formă de coridor")
    for k, nume in (("drum_in_lucru", "drum în construcție în OSM"), ("cale_ferata_in_lucru", "cale ferată în lucru în OSM")):
        if k in o and o[k]["m"] <= 300:
            motive.append(nume + " la " + str(o[k]["m"]) + " m")
    if alung >= 2.5 and (("cale_ferata" in o and o["cale_ferata"]["m"] <= 80) or ("drum_mare" in o and o["drum_mare"]["m"] <= 60)
                         or ("linie_electrica" in o and o["linie_electrica"]["m"] <= 60) or ("conducta" in o and o["conducta"]["m"] <= 60)):
        motive.append("alungită, lipită de " + next(o[k]["ce"] for k in ("cale_ferata", "drum_mare", "linie_electrica", "conducta") if k in o and o[k]["m"] <= 80))
    if motive:
        return "coridor", "; ".join(motive)
    if "cariera" in o and o["cariera"]["m"] <= 150:
        return "cariera", "carieră în OSM la " + str(o["cariera"]["m"]) + " m"
    if copaci < 30 or (z.get("arabil", 0) >= 40):
        return "camp", f"în zonă erau {copaci}% copaci (WorldCover 2021)" + (f", {z.get('arabil')}% arabil" if z.get("arabil") else "")
    if "intravilan" in o and o["intravilan"]["m"] <= 50 and copaci < 60:
        return "sat", "la marginea zonei locuite, cu copaci răzleți"
    if "apa" in o and o["apa"]["m"] <= 40 and alung >= 2.5:
        return "mal", "fâșie de-a lungul apei (" + str(o["apa"]["ce"]) + ")"
    if copaci < 60 or (cor is not None and cor < 40 and copaci < 85 and j.get("pasune", 0) >= 20):
        return "pasune_cu_copaci", f"coronament rar: {copaci}% copaci în zonă" + (f", {cor}% coronament în 2000" if cor is not None else "") + (f", {j.get('pasune')}% pășune în jur" if j.get("pasune") else "")
    return "padure", f"{copaci}% copaci în zonă" + (f", {cor}% coronament în 2000" + (" (pădure tânără sau neînregistrată atunci)" if cor < 40 else "") if cor is not None else "") + (f", {j.get('copaci', 0)}% copaci în jur" if j else "")


FEL_T = {
    "padure": "pădure închisă",
    "pasune_cu_copaci": "copaci răzleți, probabil pășune împădurită",
    "camp": "câmp sau teren agricol, nu pădure",
    "coridor": "fâșie lungă: drum, cale ferată, linie electrică sau conductă",
    "mal": "mal de apă",
    "sat": "marginea satului",
    "cariera": "carieră sau balastieră",
}


# ---------------------------------------------------------------- pe o zonă
def peisaj(cat, a, hansen_tc):
    from shapely.geometry import shape
    g = shape(a["geometry"])
    if not g.is_valid:
        g = g.buffer(0)
    lat = g.centroid.y
    p = {"calculat": dt.date.today().isoformat()}
    try:
        al, lm, lg = forma(a)
        p["alungire"], p["latime_m"], p["lungime_m"] = round(al, 1), int(lm), int(lg)
    except Exception:
        pass
    # WorldCover: în zonă și pe inelul de 500 m
    try:
        bb = _bbox_pad(g, INEL_M + 50)
        try:
            arr, tr = _citeste(cat, "esa-worldcover", bb, "map")
        except Exception:
            _SRC.clear(); _ITEMS.pop("esa-worldcover", None)
            arr, tr = _citeste(cat, "esa-worldcover", bb, "map")
        if arr is not None:
            mz = _masca(g, arr.shape, tr)
            from shapely.affinity import scale
            inel_deg = scale(in_metri(g, lat).buffer(INEL_M), xfact=1 / m_per_deg_lon(lat), yfact=1 / M_PER_DEG_LAT, origin=(0, 0, 0))
            mj = _masca(inel_deg, arr.shape, tr) & ~mz
            p["wc_zona"], p["wc_jur"] = compozitie(arr, mz), compozitie(arr, mj)
    except Exception as e:
        log("  worldcover:", a["id"], repr(e)[:100])
    # DEM
    try:
        bb = _bbox_pad(g, 200)
        try:
            arr, tr = _citeste(cat, "cop-dem-glo-30", bb, "data", data=None)
        except Exception:
            _SRC.clear(); _ITEMS.pop("cop-dem-glo-30", None)
            arr, tr = _citeste(cat, "cop-dem-glo-30", bb, "data", data=None)
        if arr is not None and arr.size > 4:
            mz = _masca(g, arr.shape, tr)
            a_ = arr.astype("float32")
            p["alt_m"] = int(round(float(a_[mz].mean()))) if mz.any() else int(round(float(a_.mean())))
            dy = abs(tr.e) * 111320.0; dx = abs(tr.a) * 111320.0 * math.cos(math.radians(lat))
            gy, gx = np.gradient(a_, dy, dx)
            panta = np.degrees(np.arctan(np.hypot(gx, gy)))
            p["panta_grade"] = int(round(float(panta[mz].mean()))) if mz.any() else int(round(float(panta.mean())))
            p["relief"] = relief(p["alt_m"], p["panta_grade"])
    except Exception as e:
        log("  dem:", a["id"], repr(e)[:100])
    # Hansen treecover2000
    if hansen_tc is not None:
        try:
            from rasterio.windows import from_bounds
            bb = _bbox_pad(g, INEL_M)
            w = from_bounds(*bb, transform=hansen_tc.transform)
            arr = hansen_tc.read(1, window=w, boundless=True, fill_value=0)
            tr = hansen_tc.window_transform(w)
            mz = _masca(g, arr.shape, tr)
            if mz.any():
                p["coronament2000"] = int(round(float(arr[mz].mean())))
                p["coronament2000_jur"] = int(round(float(arr[~mz].mean())))
        except Exception as e:
            log("  hansen:", a["id"], repr(e)[:100])
    # OSM
    el = osm_in_jur(a)
    if el is not None:
        p["osm"] = distante_osm(g, el)
    p["fel"], p["fel_motiv"] = fel_loc(p)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--pauza", type=float, default=0.0, help="secunde între zone")
    args = ap.parse_args(argv)

    zone = zone_site()
    vechi = json.loads(OUT.read_text(encoding="utf-8")).get("zone", {}) if OUT.exists() else {}
    if args.ids:
        tinta = {k: zone[k] for k in args.ids if k in zone}
    else:
        tinta = {k: v for k, v in zone.items() if args.full or k not in vechi}
    tinta = dict(sorted(tinta.items(), key=lambda kv: kv[1]["first_seen"], reverse=True))
    if args.limit:
        tinta = dict(list(tinta.items())[: args.limit])
    log(f"{len(tinta)} zone de descris, {len(vechi)} deja făcute")

    cat = _client()
    hansen_tc = None
    try:
        import rasterio
        from .run_tiles import HANSEN
        d = C.DATA / "hansen"
        d.mkdir(parents=True, exist_ok=True)
        for ver in HANSEN:
            f = d / f"Hansen_{ver}_treecover2000_50N_020E.tif"
            if not (f.exists() and f.stat().st_size > 1e6):
                import subprocess
                subprocess.run(["curl", "-sfL", "--retry", "3", "-o", str(f),
                                f"https://storage.googleapis.com/earthenginepartners-hansen/{ver}/Hansen_{ver}_treecover2000_50N_020E.tif"])
            if f.exists() and f.stat().st_size > 1e6:
                hansen_tc = rasterio.open(f); log("Hansen treecover2000:", ver); break
    except Exception as e:
        log("fără Hansen treecover:", repr(e)[:100])

    rez, n = dict(vechi), 0
    lista = list(tinta.items())
    LOT = 25
    for zid, a in lista:
        if zid not in _OSM_LOT and n % LOT == 0:
            osm_lot([x for _, x in lista[n:n + LOT]])
        try:
            rez[zid] = peisaj(cat, a, hansen_tc)
            n += 1
            log(f"  {n}/{len(tinta)} {zid} {rez[zid].get('fel')}: {rez[zid].get('fel_motiv')}")
        except Exception as e:
            log("  eroare la", zid, repr(e)[:120])
        if n % 25 == 0:
            OUT.write_text(json.dumps({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "zone": rez}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        time.sleep(args.pauza)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "zone": rez}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    from collections import Counter
    c = Counter(v.get("fel") for v in rez.values())
    log(f"{n} zone descrise -> {OUT}; feluri: {dict(c)}")


if __name__ == "__main__":
    main()
