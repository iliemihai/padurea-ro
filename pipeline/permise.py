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

Stări, de la cel mai îngrijorător la cel mai liniștitor:
  fara        nicio autorizație în jur
  neacoperit  autorizație pe parcelă, dar nu acoperă tăierea (motiv: afara / expirat / neinceput)
  probabil    autorizație în zonă, dar amenajamentul nu publică parcela ei: nu putem confirma
  acoperit    parcela autorizată acoperă zona, în intervalul tăierii
  nu_taiere   nu e tăiere de lemn (drum, agricol, incendiu): autorizațiile de tăiere nu se aplică
  nejudecat   ar fi roșu, dar analistul AI n-a confirmat „tăiere": nu acuzăm fără ochi pe poze

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


# ---------------------------------------------------------------- ce fel de schimbare e
# Autorizațiile de tăiere (APV) au sens doar pentru tăieri de lemn. Un drum prin pădure, un teren arat,
# un incendiu nu au APV și nu trebuie judecate după el. Întrebăm asta înaintea oricărui permis.
CORIDOR_ALUNGIRE = 5.0    # de câte ori mai lung decât lat
CORIDOR_LATIME_M = 120.0  # o autostradă cu taluzuri are ~100 m; un parchet e mult mai lat
NU_TAIERE_AI = {"drum": "drum", "agricol": "agricol", "incendiu": "incendiu", "nori": "nori", "toamna": "toamnă", "altceva": "altceva"}
# zonele judecate înainte să existe categoria „drum": dacă analistul a descris chiar el un drum nou prin zonă, îl credem
DRUM_IN_MOTIV = re.compile(r"(drum\w*|cale\w*|coridor\w*|linie\w*)[^.]{0,40}\bno[iu]\b[^.]{0,60}(prin|peste|traverseaz|trece)|\bno[iu]\b[^.]{0,30}drum[^.]{0,60}(prin|peste|traverseaz|trece)", re.I)


def forma(a):
    """(alungire, lățime m, lungime m) din dreptunghiul minim rotit, în metri."""
    from shapely.geometry import shape
    g = shape(a["geometry"])
    lat = g.centroid.y
    gm = in_metri(g, lat)
    r = gm.minimum_rotated_rectangle
    xs, ys = r.exterior.coords.xy
    pts = list(zip(xs, ys))
    l = sorted(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(2))
    return (l[1] / max(l[0], 1.0), l[0], l[1])


def fel_schimbare(a):
    """'taiere' sau de ce nu e tăiere de lemn: 'drum', 'agricol', 'incendiu', 'nori', 'toamnă'."""
    ai = a.get("ai") or {}
    cat = ai.get("categorie")
    if cat in NU_TAIERE_AI:
        return NU_TAIERE_AI[cat]
    if cat == "taiere" and DRUM_IN_MOTIV.search(ai.get("motiv") or ""):
        # drum nou descris de analist: îl credem doar dacă și forma e alungită (regulă de tranziție; judecătorul are acum categoria „drum")
        try:
            alungire, _, _ = forma(a)
        except Exception:
            alungire = 1.0
        if alungire >= 2.5:
            return "drum"
    try:
        alungire, latime, _ = forma(a)
    except Exception:
        return "taiere"
    if alungire >= CORIDOR_ALUNGIRE and latime <= CORIDOR_LATIME_M:
        return "drum"
    return "taiere"


PARCELA_REALA = ("exact", "cheie", "spațial")
SUPRA_MIN = 0.2    # cât din zonă trebuie să acopere parcela ca să vorbim despre perioada ei


# judecata cu context (rejudeca.py) și peisajul (peisaj.py), când există: le încărcăm o dată, la pornire
JUDECATA, PEISAJ = {}, {}
# încrederea minimă a judecătorului cu context ca să punem roșu, pe model, calibrată pe eșantioane etichetate orb (evaluare/):
#   Sonnet + promptul cu capcane, holdout de 120: 0.5 -> precizie 88% (100% fără neclare), recall 64%; 0.6 -> 100%, recall 55%
#   Haiku, promptul vechi: 0.6 -> 62% pe holdout (judecățile vechi, până le înlocuiește Sonnet)
PRAG_ROSU = {"claude-sonnet": 0.5, "": 0.7}


def _prag(j):
    m = j.get("model") or ""
    return next((v for k, v in sorted(PRAG_ROSU.items(), key=lambda x: -len(x[0])) if m.startswith(k)), 0.7)


# încrederea minimă ca să spunem public „nu e tăiere de pădure" / „pășune, nu pădure" (doar pentru judecătorul Sonnet;
# judecățile vechi Haiku rămân cum erau până le înlocuiește rejudecarea)
PRAG_NU = {"claude-sonnet": 0.5, "": 0.0}


def _prag_nu(j):
    m = j.get("model") or ""
    return next((v for k, v in sorted(PRAG_NU.items(), key=lambda x: -len(x[0])) if m.startswith(k)), 0.0)
JUD_NU_TAIERE = {"pasune": "pasune", "santier": "santier", "camp": "camp", "foc": "incendiu", "sezon_nori": "sezon", "altceva": "altceva"}
PEISAJ_NU_TAIERE = {"camp": "camp", "coridor": "santier", "cariera": "santier"}


def incarca_context():
    global JUDECATA, PEISAJ
    for nume, cale in (("JUDECATA", C.DOCS / "data" / "judecata.json"), ("PEISAJ", C.DOCS / "data" / "peisaj.json")):
        try:
            globals()[nume] = json.loads(cale.read_text(encoding="utf-8")).get("zone", {}) if cale.exists() else {}
        except Exception:
            globals()[nume] = {}
    print(f"context: {len(JUDECATA)} judecăți cu context, {len(PEISAJ)} peisaje")


def clasifica(a, permis):
    """Starea unei zone, de la cel mai îngrijorător la cel mai liniștitor.

      nu_taiere   nu e tăiere de lemn (drum/șantier, câmp, incendiu, sezon...): autorizațiile de tăiere nu se aplică
      vegetatie   copaci răzleți scoși de pe pășune: cere autorizație de la ocol (art. 60), dar nu o putem verifica în registru
      fara        nicio autorizație în jur
      neacoperit  există autorizație pe parcelă, dar nu acoperă tăierea; `motiv` spune de ce:
                    afara (parcela nu cuprinde zona), expirat, neinceput
      probabil    există autorizație în zonă, dar amenajamentul nu publică parcela ei: nu putem confirma
      acoperit    parcela autorizată acoperă zona, în intervalul tăierii
      nejudecat   ar fi roșie, dar nimeni (AI cu context) n-a confirmat încă pe poze că e pădure tăiată

    Ordinea: întâi „e tăiere de pădure?” (judecata cu context > peisaj > AI-ul simplu > forma), apoi „are autorizație?”.
    Ca să afirmăm că o autorizație NU acoperă tăierea, trebuie întâi să știm unde e parcela ei.
    Întoarce (stare, motiv).
    """
    j = JUDECATA.get(a["id"]) or {}
    p = PEISAJ.get(a["id"]) or {}
    jc = j.get("categorie")
    if jc in JUD_NU_TAIERE:
        if (j.get("incredere") or 0) < _prag_nu(j):
            # judecătorul înclină spre „nu e tăiere", dar nu e sigur: pe eșantionul holdout, aici erau
            # 13 din cele 17 tăieri reale scăpate. Nu afirmăm nimic: dacă un permis acoperă zona, starea
            # permisului; altfel „de confirmat".
            st0, m0 = _stare_permis(a, permis)
            if st0 in ("acoperit", "probabil"):
                return st0, m0
            return "nejudecat", "nesigur_nu"
        if jc == "pasune":
            return "vegetatie", "pasune"
        return "nu_taiere", JUD_NU_TAIERE[jc]
    if jc in ("taiere_rasa", "rarire"):
        # judecata cu context spune tăiere; peisajul o contrazice doar dacă AI-ul nu e sigur
        if p.get("fel") in PEISAJ_NU_TAIERE and (j.get("incredere") or 0) < 0.8:
            st0, m0 = _stare_permis(a, permis)
            if st0 in ("acoperit", "probabil"):
                return st0, m0
            return "nejudecat", "contrazis"
        fel = "taiere"
    else:
        if p.get("fel") in PEISAJ_NU_TAIERE:
            # forma de coridor/câmp/carieră spune „nu e tăiere" doar când nu există un permis care să explice
            # schimbarea; o tăiere autorizată de-a lungul unui drum e tot o tăiere cu permis
            st0, m0 = _stare_permis(a, permis)
            if st0 not in ("acoperit", "probabil"):
                return "nu_taiere", PEISAJ_NU_TAIERE[p["fel"]]
            return st0, m0
        fel = fel_schimbare(a)
        if fel != "taiere":
            return "nu_taiere", fel
    stare, motiv = _stare_permis(a, permis)
    # ca să spunem „fără autorizație", trebuie ca cineva să fi văzut pozele și să fi zis „tăiere";
    # în eșantionul verificat, zonele roșii fără părerea AI erau câmp sau sat, nu pădure tăiată.
    # pentru verde (există autorizație) nu cerem asta: a spune că există hârtie nu acuză pe nimeni.
    # judecata cu context trebuie să fie și destul de sigură (>= 0.6) ca să punem roșu
    confirmat = (jc in ("taiere_rasa", "rarire") and (j.get("incredere") or 0) >= _prag(j)) \
        or (not j and (a.get("ai") or {}).get("categorie") == "taiere")
    if stare in ("fara", "neacoperit") and not confirmat:
        return "nejudecat", ("nesigur" if jc in ("taiere_rasa", "rarire") else ("neclar" if jc == "neclar" else None))
    if stare in ("fara", "neacoperit") and p.get("fel") == "pasune_cu_copaci" and jc != "taiere_rasa":
        # copaci răzleți, fără judecată clară de tăiere rasă: nu acuzăm
        return "vegetatie", "pasune"
    return stare, motiv


def _stare_permis(a, permis):
    if not permis or not permis.get("apv"):
        return "fara", None
    reala = permis.get("potrivire") in PARCELA_REALA
    supra = permis.get("suprapunere") or 0
    if supra <= 0:
        return ("neacoperit", "afara") if reala else ("probabil", None)
    cs, ce, _ = interval_taiere(a)
    t = stare_din_timp((cs, ce), permis)
    if t == "acoperit":
        return "acoperit", None
    if reala and supra > SUPRA_MIN:
        return "neacoperit", t
    return "probabil", None


# ---------------------------------------------------------------- potrivirea
def parcele_apv(con):
    """Fiecare APV -> poligonul parcelei lui (sau un cerc, când parcela nu e publicată)."""
    from shapely.geometry import shape, Point
    from shapely.ops import unary_union
    from shapely.strtree import STRtree

    pol, bykey, strat_pol = [], {}, []
    for fid, strat, up, ua, gj in con.execute("SELECT fid,strat,up,ua,json FROM parcela"):
        g = shape(json.loads(gj)["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        bykey.setdefault((str(up), ua), []).append(len(pol))
        pol.append(g)
        strat_pol.append(strat)
    tree = STRtree(pol) if pol else None

    out, pe_parcela = {}, {}
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
        for i in alese:
            pe_parcela.setdefault(i, []).append(nr)
    return out, pol, pe_parcela, strat_pol


def potriveste(zone, apv, parcele_pol=None, apv_pe_parcela=None, raza_m=RAZA_M, parcele_strat=None):
    """Pentru fiecare zonă, autorizația care o explică cel mai bine.

    Căutăm pe două căi, pentru că raza singură nu e de ajuns. Punctul unei autorizații e de multe ori
    rampa primară, nu locul tăierii: la o parcelă mare, rampa poate fi la un kilometru de unde s-a tăiat.
    Așa că ne uităm și la parcela din amenajament în care cade zona, și luăm toate autorizațiile emise
    pe acea parcelă, oricât de departe ar fi punctul lor.
    """
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    nrs = list(apv)
    tree = STRtree([apv[n]["geom"] for n in nrs])
    ptree = STRtree(parcele_pol) if parcele_pol else None
    rezultat, parcele = {}, {}
    for zid, a in zone.items():
        g = shape(a["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        lat = g.centroid.y
        gm = in_metri(g, lat)
        vazut, cands = set(), []
        # cât din zonă cade în parcelele de amenajament publicate (stat + privat): 1.0 = pădure cu amenajament;
        # 0 = în afara lor: pășune împădurită, zăvoi, aliniament sau pădure privată fără amenajament în registru
        # și din ce strat vin parcelele: amenajamentele publicate pentru pădurile statului sau pentru cele private
        amenaj, prop = None, None
        if ptree is not None:
            idx = [int(i) for i in ptree.query(g, predicate="intersects")]
            amenaj = 0.0
            if idx:
                from shapely.ops import unary_union
                amenaj = round(min(1.0, unary_union([parcele_pol[i] for i in idx]).intersection(g).area / max(g.area, 1e-12)), 2)
            if parcele_strat:
                prop = {}
                for strat, nume in (("harti-amenajistice-stat", "stat"), ("harti-amenajistice-privat", "privat")):
                    sel = [parcele_pol[i] for i in idx if parcele_strat[i] == strat]
                    prop[nume] = round(min(1.0, unary_union(sel).intersection(g).area / max(g.area, 1e-12)), 2) if sel else 0.0

        def pune(nr):
            if nr in vazut:
                return
            vazut.add(nr)
            p = apv[nr]
            supra = g.intersection(p["geom"]).area / max(g.area, 1e-12)
            dist = gm.distance(in_metri(p["geom"], lat))
            if supra <= 0 and dist > raza_m and nr not in prin_parcela:
                return   # intrase doar prin colțul pătratului de căutare
            cands.append((nr, p, round(supra, 4), round(dist)))

        # (a) autorizațiile emise pe parcela în care cade zona — fără limită de distanță
        prin_parcela = set()
        if ptree is not None and apv_pe_parcela:
            for i in ptree.query(g, predicate="intersects"):
                for nr in apv_pe_parcela.get(int(i), []):
                    prin_parcela.add(nr)
        for nr in prin_parcela:
            pune(nr)
        # (b) autorizațiile din raza din jurul zonei
        for i in tree.query(g.buffer(grade_acoperitoare(lat, raza_m))):
            pune(nrs[int(i)])
        if not cands:
            st, mo = clasifica(a, None)
            rezultat[zid] = {"stare": st, "motiv": mo, "fel": fel_schimbare(a), "n_apv": 0, "amenajament": amenaj, "proprietate": prop}
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
               "potrivire": p["metoda"], "suprapunere": supra, "dist_m": dist, "n_apv": len(cands),
               "parcela_ha": None if p["metoda"] == "estimat" else round(in_metri(p["geom"], lat).area / 1e4, 1)}
        rec["stare"], rec["motiv"] = clasifica(a, rec)
        rec["fel"] = fel_schimbare(a)
        rec["fereastra"] = interval_taiere(a)[2]
        rec["amenajament"] = amenaj
        rec["proprietate"] = prop
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


def vecini_apv(L, geoms, k=15, raza_max_m=5000, an_minim="24"):
    """Cele mai apropiate k autorizații de fiecare zonă, nu toate dintr-o rază fixă.

    Punctul unei autorizații e de obicei rampa primară, nu locul tăierii: la o parcelă mare poate fi
    la un kilometru și mai bine. O rază fixă de câteva sute de metri le pierde pe acelea, iar una
    largă ar însemna zeci de mii de cereri. Luăm, pentru fiecare zonă, cele mai apropiate k puncte
    de până la `raza_max_m` — același cost, dar ajungem mult mai departe.
    """
    pas = 0.02
    grid = {}
    for i in range(len(L["nr"])):
        lat, lng = L["lat"][i], L["lng"][i]
        if lat is None or L["nr"][i][:2] < an_minim:
            continue
        grid.setdefault((math.floor(lat / pas), math.floor(lng / pas)), []).append(i)

    ales = {}
    for g in geoms:
        c = g.centroid
        lat, lng = c.y, c.x
        inele = max(1, math.ceil(grid_raze(lat, raza_max_m, pas)))
        gasit = []
        for r in range(0, inele + 1):
            if len(gasit) >= k and r > 1:
                break
            ci, cj = math.floor(lat / pas), math.floor(lng / pas)
            for i in range(ci - r, ci + r + 1):
                for j in range(cj - r, cj + r + 1):
                    if r and max(abs(i - ci), abs(j - cj)) != r:
                        continue   # doar inelul nou
                    for idx in grid.get((i, j), []):
                        dx = (L["lng"][idx] - lng) * m_per_deg_lon(lat)
                        dy = (L["lat"][idx] - lat) * M_PER_DEG_LAT
                        d = math.hypot(dx, dy)
                        if d <= raza_max_m:
                            gasit.append((d, idx))
        gasit.sort()
        for _, idx in gasit[:k]:
            ales[L["nr"][idx]] = (L["lat"][idx], L["lng"][idx])
    return [(nr, la, lo) for nr, (la, lo) in ales.items()]


def grid_raze(lat, raza_m, pas):
    """Câte inele de pătrate acoperă raza dată."""
    return raza_m / (min(m_per_deg_lon(lat), M_PER_DEG_LAT) * pas)


# ---------------------------------------------------------------- comenzi
def cmd_retime(args):
    incarca_context()
    """Recalculează doar stările, din ce avem deja. Fără rețea."""
    zone, vechi = zone_site(args.judet), citeste_existent()
    import collections
    mutari = collections.Counter(); nou = {}
    for zid, rec in vechi.items():
        a = zone.get(zid)
        if not a:
            nou[zid] = rec; continue
        r = dict(rec)
        r["stare"], r["motiv"] = clasifica(a, r)
        r["fel"] = fel_schimbare(a)
        r["fereastra"] = interval_taiere(a)[2]
        mutari[(rec["stare"], r["stare"])] += 1
        nou[zid] = r
    for (v, n), k in sorted(mutari.items(), key=lambda x: -x[1]):
        if v != n:
            print(f"  {v} -> {n}: {k}")
    scrie(nou, {})


def cmd_run(args):
    incarca_context()
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
    nrs = vecini_apv(L, geoms, args.vecini, args.raza_cautare, args.an_minim)
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
    apv, parcele_pol, apv_pe_parcela, parcele_strat = parcele_apv(con)
    rez, parcele = potriveste(tinta, apv, parcele_pol, apv_pe_parcela, raza_m=args.raza, parcele_strat=parcele_strat)
    vechi.update(rez)
    scrie(vechi, parcele)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true", help="reface verdictele pentru toate zonele")
    ap.add_argument("--retime", action="store_true", help="doar recalculează stările, fără rețea")
    ap.add_argument("--judet", help="doar zonele dintr-un județ")
    ap.add_argument("--limit", type=int, help="cel mult N zone (pentru probe)")
    ap.add_argument("--raza", type=float, default=RAZA_M, help="cât de departe de zonă poate fi o autorizație ca să o legăm de ea, în metri")
    ap.add_argument("--vecini", type=int, default=15, help="câte autorizații apropiate aducem pentru fiecare zonă")
    ap.add_argument("--raza-cautare", type=float, default=5000, help="cât de departe căutăm autorizații apropiate, în metri")
    ap.add_argument("--an-minim", default="24", help="numărul APV începe cu anul: 24 = din 2024 încoace")
    a = ap.parse_args(argv)
    (cmd_retime if a.retime else cmd_run)(a)


if __name__ == "__main__":
    main()
