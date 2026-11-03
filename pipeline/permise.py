"""Autorizațiile de tăiere (APV) din Inspectorul Pădurii, potrivite cu zonele găsite din satelit.

Întrebarea la care răspunde: pentru zona asta, exista o autorizație care să acopere tăierea?

Cum potrivim, pe scurt:
  1. Luăm din Inspectorul Pădurii toate APV-urile (un singur request, ~1 milion de puncte).
  2. Pentru zonele care n-au încă verdict, cerem detaliile APV-urilor din jur (ocol, u.a., volum, perioadă)
     și poligoanele parcelelor din amenajament, pe pătrate de 0,05°.
  3. Legăm fiecare APV de parcela lui (aceeași UP și u.a., sau punctul APV cade în poligon). Unde parcela
     nu e publicată, desenăm un cerc în jurul punctului, cu raza dedusă din volum — și spunem asta.
  4. Comparăm, pentru fiecare zonă, parcela autorizată cu zona tăiată și **intervalul în care s-a tăiat**
     cu perioada autorizației.

Intervalul contează, și e partea pe care e ușor să o greșești: satelitul nu vede tăierea când se întâmplă,
ci când revine frunza. O tăiere din ianuarie, cu autorizație valabilă până în decembrie, apare ca schimbare
abia în aprilie. Dacă am compara perioada autorizației cu data detectării, am declara „expirat" o tăiere
perfect legală. Așa că folosim intervalul [ultima imagine cu pădurea intactă → prima imagine cu schimbarea].
Când nu avem o imagine intactă recentă (iarnă, nori), zona are doar „intactă în vara lui X" și intervalul e
larg, de aproape un an: atunci spunem mai puțin, dar tot putem exclude o autorizație închisă înainte de vara aia.

Stări:
  acoperit   autorizație pe zona tăiată, valabilă în intervalul în care s-a tăiat
  expirat    autorizație pe zona tăiată, dar se terminase înainte ca zona să fie încă intactă
  neinceput  autorizație pe zona tăiată, dar începe după ce schimbarea se vedea deja
  langa      autorizație în apropiere, dar nu peste zona tăiată
  fara       nicio autorizație în raza căutată

Nicăieri nu scriem „ilegal": harta parcelelor e publicată doar în parte, autorizațiile se pot prelungi,
iar o zonă fără autorizație găsită e un motiv de verificat, nu o dovadă.

    python -m pipeline.permise                 adaugă verdicte pentru zonele care n-au
    python -m pipeline.permise --full          reface tot
    python -m pipeline.permise --retime        doar recalculează stările din ce avem (fără rețea)
    python -m pipeline.permise --judet Brașov  doar un județ
"""
import argparse
import datetime as dt
import json
import math
import sqlite3
import sys
import time
import unicodedata
import re
from concurrent.futures import ThreadPoolExecutor

from . import config as C

BASE = "https://inspectorulpadurii.ro"
UA = "padurea-ro/1.0 (+https://github.com/iliemihai/padurea-ro)"
CACHE = C.DATA / "sumal_cache.sqlite"
OUT = C.DOCS / "data" / "permise.json"
PARCELE = C.DOCS / "data" / "parcele.json"

RAZA_M = 500          # cât de departe de zonă mai căutăm o autorizație
TOLERANTA_ZILE = 30   # perioada autorizației, lărgită puțin la ambele capete
M3_PER_HA = 250.0     # volum tipic pe hectar, doar ca să dăm o mărime cercului când parcela lipsește
MAX_WORKERS = 4       # cerem puțin și rar: portalul e public, dar nu e al nostru
TILE = 0.05           # pătratul pe care cerem poligoanele de amenajament
CELL = 0.02           # pătratul pe care căutăm APV-uri în jurul zonelor

# stările APV din portal; ne interesează toate, și cele închise (o tăiere din primăvară are azi APV-ul reprimit)
STARE = {0: "istoric", 3: "aprobat", 4: "autorizat", 5: "predat", 6: "reprimit",
         8: "pregătit pentru predare", 9: "pregătit pentru reprimire", 10: "retras"}


# ---------------------------------------------------------------- text
def _fara_diacritice(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_ua(s):
    """'293 A' -> '293A'"""
    return re.sub(r"[^A-Z0-9]+", "", _fara_diacritice(str(s or "")).upper())


def split_ua(s):
    """Câmpul 'ua' al unui APV e 'ua1; ua2; ua1'."""
    out, seen = [], set()
    for part in str(s or "").split(";"):
        u = norm_ua(part)
        if u and u not in seen:
            seen.add(u); out.append(u)
    return out


_PER = re.compile(r"(\d{4}-\d{2}-\d{2}).*?(\d{4}-\d{2}-\d{2})")


def perioade(d):
    """'de la 2026-03-03 pana la 2026-06-03' (+ prelungiri) -> [(start, end)]"""
    out = []
    for s in (d.get("exploatari") or []) + (d.get("prelungiri") or []):
        m = _PER.search(str(s))
        if m:
            out.append((m.group(1), m.group(2)))
    return out


# ---------------------------------------------------------------- distanțe reale
# Un grad de longitudine are 111.320 m doar la ecuator; în România are ~75-78 km.
M_PER_DEG_LAT = 110_574.0


def m_per_deg_lon(lat):
    return 111_320.0 * math.cos(math.radians(lat))


def in_metri(geom, lat0):
    from shapely.affinity import scale
    return scale(geom, xfact=m_per_deg_lon(lat0), yfact=M_PER_DEG_LAT, origin=(0, 0, 0))


def cerc_m(lng, lat, raza_m):
    from shapely.affinity import scale
    from shapely.geometry import Point
    return scale(Point(lng, lat).buffer(1, quad_segs=20),
                 xfact=raza_m / m_per_deg_lon(lat), yfact=raza_m / M_PER_DEG_LAT, origin=(lng, lat))


def grade_acoperitoare(lat, raza_m):
    """Buffer în grade care sigur acoperă raza în orice direcție; filtrăm exact după."""
    return raza_m / min(m_per_deg_lon(lat), M_PER_DEG_LAT)


# ---------------------------------------------------------------- portal
def _get(url, params=None, incercari=4):
    import requests
    for i in range(incercari):
        try:
            r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=180)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 ** i)
    print("  nu răspunde:", url, file=sys.stderr)
    return None


def cache():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CACHE)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS apv(nr TEXT PRIMARY KEY, adus TEXT, json TEXT);
    CREATE TABLE IF NOT EXISTS parcela(fid TEXT PRIMARY KEY, strat TEXT, up TEXT, ua TEXT, json TEXT);
    CREATE INDEX IF NOT EXISTS parcela_key ON parcela(up, ua);
    CREATE TABLE IF NOT EXISTS tile(cheie TEXT PRIMARY KEY, adus TEXT);
    """)
    return con


def puncte_apv():
    """Toate APV-urile, cu coordonate și stare: un singur request, JSON pe coloane."""
    j = _get(f"{BASE}/api/apv/web/locations", {"numar": ""})
    if not j:
        raise SystemExit("nu am putut lua lista de APV")
    return j


def celule(geoms, raza_m, pas):
    """Pătratele de latură `pas` care ating zonele, lărgite cu raza."""
    out = set()
    for g in geoms:
        minx, miny, maxx, maxy = g.bounds
        r = grade_acoperitoare((miny + maxy) / 2, raza_m)
        for i in range(math.floor((miny - r) / pas), math.floor((maxy + r) / pas) + 1):
            for j in range(math.floor((minx - r) / pas), math.floor((maxx + r) / pas) + 1):
                out.add((i, j))
    return sorted(out)


def adu_apv(con, nrs):
    nrs = [n for n in nrs if not con.execute("SELECT 1 FROM apv WHERE nr=?", (n,)).fetchone()]
    if not nrs:
        return 0
    print(f"  cer detalii pentru {len(nrs)} autorizații")
    acum = dt.datetime.now(dt.timezone.utc).isoformat()
    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        for k, d in enumerate(ex.map(lambda n: _get(f"{BASE}/api/apv/{n}"), nrs)):
            if d:
                con.execute("INSERT OR REPLACE INTO apv VALUES (?,?,?)",
                            (d["numar"], acum, json.dumps(d, ensure_ascii=False)))
            if k % 200 == 0:
                con.commit()
    con.commit()
    return len(nrs)


def adu_parcele(con, cls):
    noi = 0
    acum = dt.datetime.now(dt.timezone.utc).isoformat()
    for k, (i, j) in enumerate(cls):
        cheie = f"{i}_{j}"
        if con.execute("SELECT 1 FROM tile WHERE cheie=?", (cheie,)).fetchone():
            continue
        s, w = i * TILE, j * TILE
        bbox = f"{s},{w},{s+TILE},{w+TILE},urn:ogc:def:crs:EPSG:4326"
        for strat in ("harti-amenajistice-stat", "harti-amenajistice-privat"):
            jj = _get(f"{BASE}/api/layer/{strat}", {"bbox": bbox})
            for f in (jj or {}).get("features", []):
                p = f["properties"]
                con.execute("INSERT OR REPLACE INTO parcela VALUES (?,?,?,?,?)",
                            (f["id"], strat, str(p.get("UP", p.get("up", ""))), norm_ua(p.get("UA", p.get("ua"))),
                             json.dumps(f, ensure_ascii=False)))
                noi += 1
        con.execute("INSERT OR REPLACE INTO tile VALUES (?,?)", (cheie, acum))
        if k % 25 == 0:
            con.commit(); print(f"  {k}/{len(cls)} pătrate, {noi} parcele", flush=True)
    con.commit()
    return noi


# ---------------------------------------------------------------- zonele de pe site
def zone_site(judet=None):
    d = C.DOCS / "data"
    out = {}
    fisiere = [d / "alerts.json"] + sorted((d / "arhiva").glob("2*.json"))
    for f in fisiere:
        if not f.exists():
            continue
        for a in json.loads(f.read_text(encoding="utf-8")).get("alerts", []):
            if judet and (a.get("county") or "") != judet:
                continue
            if a.get("geometry"):
                out[a["id"]] = a
    return out


def interval_taiere(a):
    """Când s-a tăiat, cât de bine știm: (început, sfârșit, cât de strâns)."""
    fs = dt.date.fromisoformat(a["first_seen"])
    if a.get("before_date"):
        return dt.date.fromisoformat(a["before_date"]), fs, "strânsă"
    if a.get("vara"):
        return dt.date(int(a["vara"]), 6, 1), fs, "largă"
    return fs - dt.timedelta(days=365), fs, "largă"


def stare_din_timp(cut, permis, toleranta=TOLERANTA_ZILE):
    """Perioada autorizației față de intervalul în care s-a tăiat."""
    cs, ce = cut
    g = dt.timedelta(days=toleranta)
    if not (permis.get("start") and permis.get("end")):
        return "acoperit"   # autorizație fără perioadă citibilă: nu inventăm o problemă
    ps, pe = dt.date.fromisoformat(permis["start"]), dt.date.fromisoformat(permis["end"])
    if pe < cs - g:
        return "expirat"
    if ps > ce + g:
        return "neinceput"
    return "acoperit"


PARCELA_REALA = ("exact", "cheie", "spațial")
SUPRA_MIN = 0.2    # cât din zonă trebuie să acopere parcela ca să vorbim despre perioada ei


def clasifica(a, permis):
    """Starea finală a unei zone, din potrivirea în spațiu și în timp.

    Ca să spunem că o autorizație NU acoperă tăierea, trebuie întâi să știm unde e parcela ei.
    Când parcela nu e publicată și am pus un cerc estimat, sau când abia atinge zona, nu afirmăm
    nimic despre perioadă: rămâne „autorizație, dar nu se potrivește clar".
    """
    if not permis or not permis.get("apv"):
        return "fara"
    supra = permis.get("suprapunere") or 0
    if supra <= 0:
        return "langa"
    cs, ce, _ = interval_taiere(a)
    stare = stare_din_timp((cs, ce), permis)
    if stare == "acoperit":
        return stare
    sigur = permis.get("potrivire") in PARCELA_REALA and supra > SUPRA_MIN
    return stare if sigur else "langa"


# ---------------------------------------------------------------- potrivirea
def parcele_apv(con):
    """Fiecare APV -> poligonul parcelei lui (sau un cerc, când parcela nu e publicată)."""
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    pol, bykey = [], {}
    for fid, strat, up, ua, gj in con.execute("SELECT fid,strat,up,ua,json FROM parcela"):
        g = shape(json.loads(gj)["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        bykey.setdefault((str(up), ua), []).append(len(pol))
        pol.append(g)
    tree = STRtree(pol) if pol else None

    out = {}
    for nr, _, js in con.execute("SELECT nr,adus,json FROM apv"):
        d = json.loads(js)
        r = (d.get("rampePrimare") or [])
        lat = d.get("_lat"); lng = d.get("_lng")
        if lat is None and r:
            lat, lng = r[0]["lat"], r[0]["lng"]
        if lat is None:
            continue
        pts = [Point(lng, lat)] + [Point(x["lng"], x["lat"]) for x in r]
        cand = [i for u in split_ua(d.get("ua")) for i in bykey.get((str(d.get("up", "")), u), [])]
        metoda, alese = None, []
        if cand:
            inside = [i for i in cand if any(pol[i].contains(p) for p in pts)]
            if inside:
                metoda, alese = "exact", inside
            else:
                aproape = [i for i in cand if in_metri(pol[i], lat).distance(in_metri(pts[0], lat)) < 3000]
                if aproape:
                    metoda, alese = "cheie", aproape
        if not alese and tree is not None:
            hit = [int(i) for i in tree.query(pts[0], predicate="contains")]
            if hit:
                metoda, alese = "spațial", hit[:1]
        if alese:
            geom = unary_union([pol[i] for i in alese])
        else:
            vol = float(d.get("volumInitial") or d.get("volum") or 0)
            ha = max(0.5, vol / M3_PER_HA)
            geom = cerc_m(lng, lat, math.sqrt(ha * 1e4 / math.pi)); metoda = "estimat"
        per = perioade(d)
        out[nr] = {"geom": geom, "metoda": metoda, "lat": lat, "lng": lng, "d": d,
                   "start": min((p[0] for p in per), default=None),
                   "end": max((p[1] for p in per), default=None)}
    return out


def potriveste(zone, apv, raza_m=RAZA_M):
    """Pentru fiecare zonă, autorizația care o explică cel mai bine."""
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    nrs = list(apv)
    tree = STRtree([apv[n]["geom"] for n in nrs])
    rezultat, parcele = {}, {}
    for zid, a in zone.items():
        g = shape(a["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        lat = g.centroid.y
        gm = in_metri(g, lat)
        cands = []
        for i in tree.query(g.buffer(grade_acoperitoare(lat, raza_m))):
            p = apv[nrs[int(i)]]
            supra = g.intersection(p["geom"]).area / max(g.area, 1e-12)
            dist = gm.distance(in_metri(p["geom"], lat))
            if supra <= 0 and dist > raza_m:
                continue   # intrase doar prin colțul pătratului
            cands.append((nrs[int(i)], p, round(supra, 4), round(dist)))
        if not cands:
            rezultat[zid] = {"stare": "fara", "n_apv": 0}
            continue
        cut = interval_taiere(a)[:2]
        rang = {"acoperit": 0, "expirat": 1, "neinceput": 2}

        def cheie(c):
            _, p, supra, dist = c
            t = stare_din_timp(cut, {"start": p["start"], "end": p["end"]})
            return (0 if supra > 0 else 1, rang[t], -supra, dist)
        cands.sort(key=cheie)
        nr, p, supra, dist = cands[0]
        d = p["d"]
        rec = {"apv": nr, "ocol": d.get("ocol"), "ua": split_ua(d.get("ua")), "ua_text": d.get("ua"), "up": d.get("up"),
               "stare_apv": STARE.get(d.get("codStare"), d.get("stare")), "titular": (d.get("autorizatie") or {}).get("titular"),
               "start": p["start"], "end": p["end"], "volum_m3": d.get("volumInitial") or d.get("volum"),
               "tratament": d.get("tratament"), "natura": d.get("naturaProdus"),
               "potrivire": p["metoda"], "suprapunere": supra, "dist_m": dist, "n_apv": len(cands)}
        rec["stare"] = clasifica(a, rec)
        rec["fereastra"] = interval_taiere(a)[2]
        ha_zona = a.get("ha") or 0
        if rec["volum_m3"] and supra > 0 and ha_zona * M3_PER_HA > 3 * float(rec["volum_m3"]):
            rec["volum_suspect"] = True
        rezultat[zid] = rec
        if p["metoda"] != "estimat":
            parcele[zid] = p["geom"]
    return rezultat, parcele


# ---------------------------------------------------------------- scriere
def scrie(zone_verdict, parcele, meta_extra=None):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    import collections
    numar = collections.Counter(z["stare"] for z in zone_verdict.values())
    meta = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "sursa": "SUMAL 2.0 / Inspectorul Pădurii",
            "raza_m": RAZA_M, "toleranta_zile": TOLERANTA_ZILE,
            "acoperire": {"zone_verificate": len(zone_verdict), **dict(numar)},
            "zone": zone_verdict}
    if meta_extra:
        meta.update(meta_extra)
    OUT.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(zone_verdict)} zone -> {OUT}  {dict(numar)}")
    if parcele:
        from shapely.geometry import mapping
        fc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": mapping(g.simplify(1e-5, preserve_topology=True)),
             "properties": {"zid": zid}} for zid, g in parcele.items()]}
        PARCELE.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{len(fc['features'])} parcele -> {PARCELE}")


def citeste_existent():
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8")).get("zone", {})
    return {}


# ---------------------------------------------------------------- comenzi
def cmd_retime(args):
    """Recalculează doar stările, din ce avem deja. Fără rețea."""
    zone, vechi = zone_site(args.judet), citeste_existent()
    import collections
    mutari = collections.Counter(); nou = {}
    for zid, rec in vechi.items():
        a = zone.get(zid)
        if not a:
            nou[zid] = rec; continue
        r = dict(rec)
        r["stare"] = clasifica(a, r)
        r["fereastra"] = interval_taiere(a)[2]
        mutari[(rec["stare"], r["stare"])] += 1
        nou[zid] = r
    for (v, n), k in sorted(mutari.items(), key=lambda x: -x[1]):
        if v != n:
            print(f"  {v} -> {n}: {k}")
    scrie(nou, {})


def cmd_run(args):
    from shapely.geometry import shape
    zone = zone_site(args.judet)
    vechi = {} if args.full else citeste_existent()
    tinta = {k: v for k, v in zone.items() if k not in vechi}
    if args.limit:
        tinta = dict(list(tinta.items())[: args.limit])
    print(f"{len(zone)} zone pe site, {len(vechi)} cu verdict, {len(tinta)} de verificat")
    if not tinta:
        print("nimic nou"); return

    con = cache()
    geoms = [shape(a["geometry"]) for a in tinta.values()]

    print("iau lista de autorizații...")
    L = puncte_apv()
    cls = set(celule(geoms, RAZA_M, CELL))
    nrs = []
    for k in range(len(L["nr"])):
        lat, lng = L["lat"][k], L["lng"][k]
        if lat is None:
            continue
        if (math.floor(lat / CELL), math.floor(lng / CELL)) in cls:
            nrs.append((L["nr"][k], lat, lng))
    print(f"  {len(nrs)} autorizații în jurul zonelor")
    adu_apv(con, [n for n, _, _ in nrs])
    # punem coordonatele din listă în detaliile salvate (detaliul nu le are)
    for nr, lat, lng in nrs:
        row = con.execute("SELECT json FROM apv WHERE nr=?", (nr,)).fetchone()
        if row:
            d = json.loads(row[0])
            if d.get("_lat") is None:
                d["_lat"], d["_lng"] = lat, lng
                con.execute("UPDATE apv SET json=? WHERE nr=?", (json.dumps(d, ensure_ascii=False), nr))
    con.commit()

    print("iau poligoanele parcelelor...")
    adu_parcele(con, celule(geoms, RAZA_M, TILE))

    print("potrivesc...")
    apv = parcele_apv(con)
    rez, parcele = potriveste(tinta, apv)
    vechi.update(rez)
    scrie(vechi, parcele)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true", help="reface verdictele pentru toate zonele")
    ap.add_argument("--retime", action="store_true", help="doar recalculează stările, fără rețea")
    ap.add_argument("--judet", help="doar zonele dintr-un județ")
    ap.add_argument("--limit", type=int, help="cel mult N zone (pentru probe)")
    a = ap.parse_args(argv)
    (cmd_retime if a.retime else cmd_run)(a)


if __name__ == "__main__":
    main()
