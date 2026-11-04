"""Paginile pe județe: docs/judet/<slug>/ (index.html, zone.csv, zone.geojson) și docs/judet/index.html.

Pagini statice, din aceleași date ca harta (docs/data): ce s-a văzut în județ, unde, cu ce autorizații, cine răspunde,
plus datele de descărcat. Se citesc, se distribuie și se citează fără JavaScript; JS-ul (judet.js) doar adaugă
etichetele la trecerea cu mouse-ul peste grafice.

    python -m pipeline.judete
"""
import csv
import datetime as dt
import html
import io
import json
import math
import unicodedata
from collections import Counter, defaultdict

from . import config as C
from .permise import zone_site, OUT as PERMISE

DOCS = C.DOCS
OUT = DOCS / "judet"
VER = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M")

LUNI = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."]
LUNI_L = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie",
          "noiembrie", "decembrie"]

# aceleași texte ca pe hartă (docs/app.js, AUT_T)
STARE_T = {"fara": "fără autorizație", "neacoperit": "autorizația nu acoperă tăierea", "vegetatie": "pășune, nu pădure",
           "probabil": "probabil cu autorizație", "acoperit": "cu autorizație", "nu_taiere": "nu e tăiere de pădure",
           "nejudecat": "de confirmat pe poze", "nev": "încă necomparată"}
MOTIV_NEACOPERIT = {"afara": "schimbarea cade în afara parcelei autorizate",
                    "expirat": "autorizația expirase înainte de tăiere",
                    "neinceput": "autorizația începe după ce schimbarea se vedea deja"}
GRUP = {"fara": "rosu", "neacoperit": "rosu", "acoperit": "verde", "probabil": "verde", "vegetatie": "pasune",
        "nu_taiere": "nu", "nejudecat": "confirmat", "nev": "confirmat"}

# Garda Forestieră de care ține fiecare județ (HG 743/2015, anexa 1); aceeași listă ca în docs/app.js
GARZI = {
    "Brașov": ["Brașov", "Covasna", "Harghita", "Mureș", "Sibiu"],
    "București": ["București", "Călărași", "Constanța", "Ilfov", "Giurgiu", "Ialomița", "Teleorman"],
    "Cluj": ["Alba", "Bistrița-Năsăud", "Cluj", "Maramureș"],
    "Focșani": ["Brăila", "Buzău", "Galați", "Tulcea", "Vrancea", "Vaslui"],
    "Oradea": ["Arad", "Bihor", "Satu Mare", "Sălaj"],
    "Ploiești": ["Argeș", "Dâmbovița", "Prahova"],
    "Râmnicu Vâlcea": ["Dolj", "Gorj", "Mehedinți", "Olt", "Vâlcea"],
    "Suceava": ["Bacău", "Botoșani", "Iași", "Neamț", "Suceava"],
    "Timișoara": ["Caraș-Severin", "Hunedoara", "Timiș"],
}


# ---------------------------------------------------------------- mărunțișuri
def slug(n):
    s = "".join(c for c in unicodedata.normalize("NFKD", n) if not unicodedata.combining(c)).lower()
    return "-".join("".join(c if c.isalnum() else " " for c in s).split())


def fmt(n, d=0):
    s = f"{abs(n):,.{d}f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return ("-" if n < 0 else "") + s


def de(n):
    r = round(n) % 100
    return "de " if n != 0 and (r == 0 or r >= 20) else ""


def ha_t(x):
    return f"{fmt(x, 1 if x < 100 else 0)} ha"


def nr(n, unu, multe):
    """«1 zonă», «3 zone», «20 de zone»."""
    return f"{fmt(n)} {unu}" if n == 1 else f"{fmt(n)} {de(n)}{multe}"


def zi(s, lung=False):
    if not s:
        return "necunoscută"
    d = dt.date.fromisoformat(s[:10])
    return f"{d.day} {(LUNI_L if lung else LUNI)[d.month - 1]} {d.year}"


def luna_t(m, lung=False):
    y, mo = int(m[:4]), int(m[5:7])
    return f"{(LUNI_L if lung else LUNI)[mo - 1]} {y}"


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def judet_de(a):
    return (a.get("uat") or {}).get("judet") or a.get("county") or ""


def loc_t(a):
    u = a.get("uat") or {}
    loc = a.get("localitate")
    parti = []
    if loc:
        parti.append(loc)
    if u.get("nume") and u.get("nume") != loc:
        tip = {"comuna": "com.", "orașul": "oraș", "municipiul": "mun.", "sectorul": "sector"}.get(u.get("tip"), "")
        parti.append(f"{tip} {u['nume']}".strip())
    return ", ".join(parti) or "loc fără nume"


def nice_step(vmax, n=4):
    if vmax <= 0:
        return 1
    raw = vmax / n
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * p >= raw:
            return m * p
    return 10 * p


# ---------------------------------------------------------------- date
def incarca():
    zone = zone_site()
    verd = json.loads(PERMISE.read_text(encoding="utf-8")).get("zone", {})
    jud = {}
    p = DOCS / "data" / "judecata.json"
    if p.exists():
        jud = json.loads(p.read_text(encoding="utf-8")).get("zone", {})
    meta = json.loads((DOCS / "data" / "alerts.json").read_text(encoding="utf-8"))
    cty = json.loads((DOCS / "data" / "static" / "counties.geojson").read_text(encoding="utf-8"))
    return zone, verd, jud, meta, cty


def luni_intre(m0, m1):
    y, m = int(m0[:4]), int(m0[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= m1:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------- grafice (SVG static; judet.js adaugă eticheta la hover)
def svg_luni(luni, val, cnt, titlu_aria):
    """Coloane pe luni, o singură serie: hectarele fără autorizație care să le acopere."""
    W, H, L, R, T, B = 720, 220, 46, 8, 14, 40
    pw, ph = W - L - R, H - T - B
    step = nice_step(max(list(val.values()) + [1]))
    ymax = step * max(1, math.ceil(max(list(val.values()) + [0.0001]) / step))
    band = pw / len(luni)
    bw = min(24, band * 0.62)
    y = lambda v: T + ph - v / ymax * ph
    o = [f'<div class="chartwrap"><svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{e(titlu_aria)}">']
    k = 0
    while k * step <= ymax + 1e-9:
        v = k * step
        o.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        o.append(f'<text class="tick" x="{L - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{fmt(v, 0 if step >= 1 else 1)}</text>')
        k += 1
    for i, m in enumerate(luni):
        cx = L + band * i + band / 2
        x0 = cx - bw / 2
        o.append(f'<text class="tick" x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle">{LUNI[int(m[5:7]) - 1].rstrip(".")}</text>')
        if i == 0 or m[5:7] == "01":
            o.append(f'<text class="tick an" x="{cx:.1f}" y="{H - B + 31}" text-anchor="middle">{m[:4]}</text>')
        v = val[m]
        if v <= 0:
            continue
        h = max(1.5, v / ymax * ph)
        yt = T + ph - h
        r = min(4, h, bw / 2)
        d = (f"M{x0:.1f},{T + ph:.1f} L{x0:.1f},{yt + r:.1f} Q{x0:.1f},{yt:.1f} {x0 + r:.1f},{yt:.1f} "
             f"L{x0 + bw - r:.1f},{yt:.1f} Q{x0 + bw:.1f},{yt:.1f} {x0 + bw:.1f},{yt + r:.1f} L{x0 + bw:.1f},{T + ph:.1f} Z")
        lab = f"{luna_t(m, True)} · {nr(cnt[m], 'loc', 'locuri')}"
        o.append(f'<path class="m s-rosu" d="{d}" tabindex="0" data-v="{e(ha_t(v))}" data-l="{e(lab)}">'
                 f'<title>{e(ha_t(v) + " — " + lab)}</title></path>')
    o.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{T + ph:.1f}" y2="{T + ph:.1f}"/>')
    o.append("</svg></div>")
    return "".join(o)


def svg_hansen(ani, loss, titlu_aria):
    W, H, L, R, T, B = 720, 190, 46, 8, 14, 26
    pw, ph = W - L - R, H - T - B
    step = nice_step(max(loss + [1]))
    ymax = step * max(1, math.ceil(max(loss + [0.0001]) / step))
    band = pw / len(ani)
    bw = min(16, band * 0.62)
    y = lambda v: T + ph - v / ymax * ph
    o = [f'<div class="chartwrap"><svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{e(titlu_aria)}">']
    k = 0
    while k * step <= ymax + 1e-9:
        v = k * step
        o.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        o.append(f'<text class="tick" x="{L - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{fmt(v)}</text>')
        k += 1
    for i, (an, v) in enumerate(zip(ani, loss)):
        cx = L + band * i + band / 2
        x0 = cx - bw / 2
        if an % 5 == 0 or i == 0 or i == len(ani) - 1:
            o.append(f'<text class="tick" x="{cx:.1f}" y="{H - B + 16}" text-anchor="middle">{an}</text>')
        if v <= 0:
            continue
        h = v / ymax * ph
        yt = T + ph - h
        r = min(3, h, bw / 2)
        d = (f"M{x0:.1f},{T + ph:.1f} L{x0:.1f},{yt + r:.1f} Q{x0:.1f},{yt:.1f} {x0 + r:.1f},{yt:.1f} "
             f"L{x0 + bw - r:.1f},{yt:.1f} Q{x0 + bw:.1f},{yt:.1f} {x0 + bw:.1f},{yt + r:.1f} L{x0 + bw:.1f},{T + ph:.1f} Z")
        lab = f"pădure pierdută în {an}"
        tit = f"{an}: {ha_t(v)}"
        o.append(f'<path class="m s-hansen" d="{d}" tabindex="0" data-v="{e(ha_t(v))}" data-l="{e(lab)}">'
                 f'<title>{e(tit)}</title></path>')
    o.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{T + ph:.1f}" y2="{T + ph:.1f}"/>')
    o.append("</svg></div>")
    return "".join(o)


def svg_harta(geom, puncte, titlu_aria):
    """Conturul județului și zonele: roșii și verzi; fiecare punct deschide zona pe hartă."""
    from shapely.geometry import shape
    g = shape(geom).simplify(0.003, preserve_topology=True)
    x0, y0, x1, y1 = g.bounds
    lat0 = (y0 + y1) / 2
    kx = math.cos(math.radians(lat0))
    W = 720
    sx = (W - 16) / ((x1 - x0) * kx)
    Hh = (y1 - y0) * sx + 16
    if Hh > 520:  # județele înalte: limităm înălțimea
        sx = (520 - 16) / (y1 - y0)
        Hh = 520
    px = lambda lon: 8 + (lon - x0) * kx * sx
    py = lambda lat: 8 + (y1 - lat) * sx
    polys = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
    d = ""
    for p in polys:
        for ring in [p.exterior] + list(p.interiors):
            cs = list(ring.coords)
            d += "M" + " L".join(f"{px(c[0]):.1f},{py(c[1]):.1f}" for c in cs) + " Z "
    o = [f'<svg class="minimap" viewBox="0 0 {W} {Hh:.0f}" role="img" aria-label="{e(titlu_aria)}">',
         f'<path class="cty" d="{d.strip()}"/>']
    # verzile întâi, roșiile deasupra
    for cls, a, lab in sorted(puncte, key=lambda t: t[0] == "rosu"):
        x, yy = px(a["lon"]), py(a["lat"])
        r = 5 if cls == "rosu" else 3.5
        o.append(f'<a href="../../#a={e(a["id"])}" class="pt" data-v="{e(ha_t(a.get("ha") or 0))}" data-l="{e(lab)}">'
                 f'<title>{e(lab)}</title><circle class="hit" cx="{x:.1f}" cy="{yy:.1f}" r="12"/>'
                 f'<circle class="dot s-{cls}" cx="{x:.1f}" cy="{yy:.1f}" r="{r}"/></a>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------- bucăți de pagină
CAP = """<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%23030201'/%3E%3Crect x='11' y='11' width='10' height='10' fill='%23f97c3d'/%3E%3C/svg%3E">
<link rel="stylesheet" href="{rel}judet/judet.css?v={ver}">
</head>
<body>
<header class="top"><div class="wrap">
  <a class="home" href="{rel}">Pădurea RO</a>
  <nav aria-label="Navigare"><a href="{rel}">Harta</a><a href="{rel}judet/"{cur_j}>Județe</a></nav>
</div></header>
<main class="wrap">
"""

COADA = """</main>
<footer class="wrap foot">
  <p>Pădurea RO arată ce se vede din satelit și ce scrie în registrul public de autorizații; nu e o dovadă în sine.
  Imagini: Copernicus Sentinel-2 (ESA), Esri World Imagery; autorizații: Inspectorul Pădurii; pierderi istorice: Hansen/UMD/Google/USGS/NASA (GFC-2025-v1.13).
  Actualizat {upd}.</p>
</footer>
<script src="{rel}judet/judet.js?v={ver}" defer></script>
</body>
</html>
"""


def kpi(cls, val, lab, sub):
    key = f'<i class="key s-{cls}" aria-hidden="true"></i>' if cls else ""
    return f'<div class="kpi"><p class="lbl">{key}{e(lab)}</p><p class="val">{val}</p><p class="sub">{sub}</p></div>'


ESRI = ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
        "?bboxSR=4326&imageSR=3857&size=400,400&format=jpg&f=image&bbox=")


def contur(a):
    """Conturul zonei peste o poză care acoperă chip_bbox (același calcul ca pe hartă)."""
    cb, g = a.get("chip_bbox"), a.get("geometry")
    if not cb or not g:
        return ""
    w, h = cb[2] - cb[0], cb[3] - cb[1]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    d = ""
    for poly in polys:
        for ring in poly:
            d += "M" + " L".join(f"{1000 * (c[0] - cb[0]) / w:.0f} {1000 * (cb[3] - c[1]) / h:.0f}" for c in ring) + "Z"
    return f'<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true"><path d="{d}"/></svg>'


def teren(v):
    """Al cui e terenul, după amenajamentele silvice publicate în Inspectorul Pădurii (None = încă necalculat)."""
    pr, am = v.get("proprietate"), v.get("amenajament")
    if pr is None or am is None:
        return None
    if am < 0.2:
        return "afara"
    if (pr.get("stat") or 0) >= 0.5:
        return "stat"
    if (pr.get("privat") or 0) >= 0.5:
        return "privat"
    return "mixt"


TEREN_T = {"stat": "pădure de stat", "privat": "pădure privată", "mixt": "parțial de stat, parțial privată sau fără amenajament",
           "afara": "în afara amenajamentelor silvice publicate"}
TEREN_LUNG = {"stat": "Terenul: pădure de stat, după amenajamentul silvic publicat.",
              "privat": "Terenul: pădure privată, după amenajamentul silvic publicat.",
              "mixt": "Terenul: o parte în pădure de stat, o parte privată sau fără amenajament publicat.",
              "afara": "Terenul: în afara amenajamentelor silvice publicate (pășune, mal de apă sau pădure privată fără amenajament în registru)."}


def card_zona(a, v, j):
    st = v.get("stare")
    ib, ia = a.get("img_before") or {}, a.get("img_after") or {}
    cb = a.get("chip_bbox")
    ct = contur(a)
    poze = ""
    if ib.get("file") and ia.get("file") and cb:
        src = ESRI + ",".join(f"{x:.6f}" for x in cb)
        ascunde = "this.style.display='none'"
        poze = ('<div class="pair">'
                f'<figure><div class="ph"><img src="{src}" alt="poza detaliată de dinainte" loading="lazy" width="400" height="400" onerror="{ascunde}">{ct}</div>'
                f'<figcaption>detaliat · Esri</figcaption></figure>'
                f'<figure><div class="ph"><img src="../../img/{e(ib["file"])}" alt="înainte" loading="lazy" width="90" height="90">{ct}</div>'
                f'<figcaption>înainte · {e(zi(ib.get("date")))}</figcaption></figure>'
                f'<figure><div class="ph"><img src="../../img/{e(ia["file"])}" alt="după" loading="lazy" width="90" height="90">{ct}</div>'
                f'<figcaption>după · {e(zi(ia.get("date")))}</figcaption></figure></div>')
    rows = []
    if st == "fara":
        rows.append("Nu am găsit nicio autorizație de tăiere în jur.")
    elif st == "neacoperit":
        m = MOTIV_NEACOPERIT.get(v.get("motiv"), "autorizația din apropiere nu acoperă zona")
        rows.append(f"Autorizația cea mai apropiată nu acoperă tăierea: {e(m)}.")
        if v.get("apv"):
            per = f", valabilă {zi(v.get('start'))} – {zi(v.get('end'))}" if v.get("start") else ""
            dist = f", la {fmt(v.get('dist_m') or 0)} m" if v.get("dist_m") is not None else ""
            rows.append(f'<span class="mono">APV {e(v["apv"])}</span> · {e((v.get("ocol") or "").title())}{e(per)}{e(dist)}')
    t = teren(v)
    if t:
        rows.append(e(TEREN_LUNG[t]))
    ce = (j or {}).get("motiv")
    if ce:
        rows.append(f'<b>Ce se vede în poze:</b> {e(ce)}')
    arii = [x.get("nume") for x in (a.get("arii") or []) if isinstance(x, dict) and x.get("nume")]
    arii = list(dict.fromkeys(arii))
    tag = f'<p class="tag">în arie protejată: {e(", ".join(arii))}</p>' if arii else ""
    return (f'<article class="zcard"><div class="zhead"><p class="zt"><b>{e(ha_t(a.get("ha") or 0))}</b> · {e(loc_t(a))}</p>'
            f'<p class="zd">văzută schimbată prima dată pe {e(zi(a.get("first_seen")))}</p></div>'
            f'{poze}<div class="zbody">' + "".join(f"<p>{r}</p>" for r in rows) + tag +
            f'<p><a class="go" href="../../#a={e(a["id"])}">Vezi zona pe hartă</a></p></div></article>')


def tabel(cap, rows, num_cols, cls="tbl"):
    cth, ctd = ' class="r"', ' class="r num"'
    th = "".join(f'<th scope="col"{cth if i in num_cols else ""}>{e(c)}</th>' for i, c in enumerate(cap))
    tr = "".join("<tr>" + "".join(f'<td{ctd if i in num_cols else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tblwrap"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


# ---------------------------------------------------------------- pagina unui județ
def pagina_judet(nume, zs, verd, jud, meta, feat, luni, upd):
    s = slug(nume)
    g = next((k for k, v in GARZI.items() if nume in v), None)
    st = {a["id"]: (verd.get(a["id"]) or {}).get("stare", "nev") for a in zs}
    grp = {k: GRUP.get(v, "confirmat") for k, v in st.items()}
    cnt = Counter(grp.values())
    ha = defaultdict(float)
    for a in zs:
        ha[grp[a["id"]]] += a.get("ha") or 0
    tot_ha = sum(ha.values())
    rosii = sorted([a for a in zs if grp[a["id"]] == "rosu"], key=lambda a: (a.get("first_seen") or "", a.get("ha") or 0), reverse=True)
    verzi = [a for a in zs if grp[a["id"]] == "verde"]
    de_la, pana = meta.get("istoric_de_la"), meta.get("data_until")
    in_jud = "în municipiul București" if nume == "București" else f"în județul {nume}"

    # textul de sus
    if zs:
        lead = (f"Din {zi(de_la, True)} până pe {zi(pana, True)}, satelitul a văzut schimbări în pădure sau la marginea ei {in_jud}, "
                f"în {nr(len(zs), 'loc', 'locuri')} ({ha_t(tot_ha)}). ")
        if cnt["rosu"]:
            lead += (f"În {nr(cnt['rosu'], 'loc', 'locuri')} ({ha_t(ha['rosu'])}) pozele arată pădure tăiată și nu am găsit "
                     f"o autorizație de tăiere care să acopere locul.")
        else:
            lead += "În niciunul nu am găsit o tăiere de pădure fără o autorizație care s-o acopere."
    else:
        lead = f"Din {zi(de_la, True)} până pe {zi(pana, True)}, satelitul nu a văzut schimbări în pădure {in_jud}."
    desc = lead

    o = [CAP.format(title=e(f"{nume} · Pădurea RO"), desc=e(desc), rel="../../", ver=VER, cur_j="")]
    o.append(f'<p class="crumbs"><a href="../">Județe</a></p><h1>{e(nume)}</h1><p class="lead">{e(lead)}</p>')
    if zs:
        o.append('<p class="caveat">Roșu nu înseamnă automat ilegal: autorizația poate exista fără să fie publicată, '
                 'sau tăierea poate fi aprobată altfel (de exemplu, pentru un drum). E un loc de întrebat ocolul silvic și Garda Forestieră.</p>')

    # cifrele
    o.append('<section class="kpis" aria-label="Pe scurt">')
    o.append(kpi("rosu", fmt(cnt["rosu"]), "Fără autorizație care s-o acopere", ha_t(ha["rosu"])))
    o.append(kpi("verde", fmt(cnt["verde"]), "Cu autorizație", ha_t(ha["verde"])))
    o.append(kpi("", fmt(cnt["nu"] + cnt["pasune"]), "Nu e tăiere de pădure", "drum, câmp, foc, sezon, pășune"))
    o.append(kpi("", fmt(cnt["confirmat"]), "De confirmat pe poze", "analistul nu e sigur"))
    o.append("</section>")

    if zs:
        # pe luni
        val = {m: {"rosu": 0.0, "verde": 0.0, "n_rosu": 0, "n_verde": 0} for m in luni}
        for a in zs:
            m = (a.get("first_seen") or "")[:7]
            gg = grp[a["id"]]
            if m in val and gg in ("rosu", "verde"):
                val[m][gg] += a.get("ha") or 0
                val[m]["n_" + gg] += 1
        o.append('<section class="sec"><h2>Pe luni</h2><p class="sub">Hectarele fără autorizație care să le acopere, după luna în care '
                 'am văzut prima dată schimbarea. Între 15 decembrie și 15 martie nu căutăm tăieri noi. Zonele cu autorizație sunt în tabel.</p>')
        if cnt["rosu"]:
            o.append(svg_luni(luni, {m: val[m]["rosu"] for m in luni}, {m: val[m]["n_rosu"] for m in luni},
                              f"Hectare fără autorizație care să le acopere, pe luni, {in_jud}"))
        else:
            o.append('<p class="none">Nicio zonă fără autorizație care s-o acopere în această perioadă.</p>')
        rows = [[e(luna_t(m, True)), f'{fmt(val[m]["rosu"], 1)}', fmt(val[m]["n_rosu"]), f'{fmt(val[m]["verde"], 1)}', fmt(val[m]["n_verde"])]
                for m in luni if val[m]["n_rosu"] or val[m]["n_verde"]]
        o.append('<details class="tview"><summary>Vezi cifrele în tabel, cu zonele cu autorizație</summary>' +
                 tabel(["Luna", "ha fără autorizație", "locuri", "ha cu autorizație", "locuri"], rows, {1, 2, 3, 4}) + "</details></section>")

        # harta
        pct = [("rosu", a, f"{ha_t(a.get('ha') or 0)} · {loc_t(a)} · {zi(a.get('first_seen'))} · fără autorizație care s-o acopere") for a in rosii]
        pct += [("verde", a, f"{ha_t(a.get('ha') or 0)} · {loc_t(a)} · {zi(a.get('first_seen'))} · cu autorizație") for a in verzi]
        if feat and pct:
            o.append('<section class="sec"><h2>Unde</h2><p class="sub">Fiecare punct deschide zona pe hartă, cu pozele înainte și după.</p>'
                     '<div class="legend"><span><i class="key dotk s-rosu"></i>fără autorizație care s-o acopere</span>'
                     '<span><i class="key dotk s-verde"></i>cu autorizație</span></div>')
            o.append(svg_harta(feat["geometry"], pct, f"Harta zonelor {in_jud}"))
            o.append("</section>")

        # lista roșiilor
        if rosii:
            o.append(f'<section class="sec"><h2>Locurile fără autorizație care să le acopere</h2>'
                     f'<p class="sub">{nr(len(rosii), "loc", "locuri")}, cele mai noi întâi. Pentru fiecare: pozele din satelit, '
                     f'ce am găsit în registrul de autorizații și ce vede analistul în poza detaliată.</p><div class="zgrid">')
            for a in rosii:
                o.append(card_zona(a, verd.get(a["id"]) or {}, jud.get(a["id"])))
            o.append("</div></section>")

        # al cui e terenul, pentru locurile fără autorizație
        per_t = defaultdict(lambda: [0, 0.0])
        for a in rosii:
            t = teren(verd.get(a["id"]) or {}) or "necunoscut"
            per_t[t][0] += 1
            per_t[t][1] += a.get("ha") or 0
        if rosii and any(k != "necunoscut" for k in per_t):
            ordine = ["stat", "privat", "mixt", "afara", "necunoscut"]
            nume_t = dict(TEREN_T, necunoscut="încă necalculat")
            rows = [[e(nume_t[k]), fmt(per_t[k][0]), fmt(per_t[k][1], 1)] for k in ordine if k in per_t]
            o.append('<section class="sec"><h2>Al cui e terenul</h2><p class="sub">Pentru locurile fără autorizație care să le acopere, '
                     'după hărțile amenajamentelor silvice publicate în Inspectorul Pădurii: pădurile statului sunt administrate de '
                     'ocoalele Romsilva, cele private de ocoale private sau de regim.</p>')
            o.append(tabel(["Terenul", "locuri", "ha"], rows, {1, 2}))
            o.append("</section>")

        # pe comune
        per_uat = defaultdict(lambda: {"n": 0, "ha": 0.0, "r": 0, "rha": 0.0, "v": 0})
        for a in zs:
            u = a.get("uat") or {}
            k = (u.get("tip") or "", u.get("nume") or a.get("localitate") or "—")
            per_uat[k]["n"] += 1
            per_uat[k]["ha"] += a.get("ha") or 0
            if grp[a["id"]] == "rosu":
                per_uat[k]["r"] += 1
                per_uat[k]["rha"] += a.get("ha") or 0
            if grp[a["id"]] == "verde":
                per_uat[k]["v"] += 1
        lst = sorted(per_uat.items(), key=lambda kv: (-kv[1]["rha"], -kv[1]["ha"]))
        tipn = {"comuna": "comuna", "orașul": "orașul", "municipiul": "municipiul", "sectorul": "sectorul"}
        rows = [[e(f"{tipn.get(k[0], '')} {k[1]}".strip()), fmt(v["n"]), fmt(v["ha"], 1), fmt(v["r"]), fmt(v["rha"], 1), fmt(v["v"])] for k, v in lst]
        cap = ["Comuna sau orașul", "zone", "ha", "fără autorizație", "ha", "cu autorizație"]
        o.append('<section class="sec"><h2>Pe comune și orașe</h2><p class="sub">Ordonate după hectarele fără autorizație care să le acopere.</p>')
        if len(rows) > 15:
            o.append(tabel(cap, rows[:15], {1, 2, 3, 4, 5}) +
                     f'<details class="tview"><summary>Toate cele {fmt(len(rows))}</summary>' + tabel(cap, rows[15:], {1, 2, 3, 4, 5}) + "</details>")
        else:
            o.append(tabel(cap, rows, {1, 2, 3, 4, 5}))
        o.append("</section>")

        # ocoalele
        per_ocol = defaultdict(lambda: {"acop": 0, "neacop": 0})
        for a in zs:
            v = verd.get(a["id"]) or {}
            oc = (v.get("ocol") or "").strip()
            if not oc:
                continue
            if v.get("stare") in ("acoperit", "probabil"):
                per_ocol[oc]["acop"] += 1
            elif v.get("stare") == "neacoperit":
                per_ocol[oc]["neacop"] += 1
        if per_ocol:
            lst = sorted(per_ocol.items(), key=lambda kv: (-kv[1]["neacop"], -kv[1]["acop"]))
            rows = [[e(k.title()), fmt(v["acop"]), fmt(v["neacop"])] for k, v in lst if v["acop"] or v["neacop"]]
            o.append('<section class="sec"><h2>Ocoalele silvice</h2><p class="sub">Ocolul care a emis autorizația cea mai apropiată de fiecare zonă. '
                     'A doua coloană: zone unde autorizația ocolului acoperă tăierea; a treia: zone tăiate lângă o autorizație a ocolului, '
                     'dar în afara ei sau în afara perioadei ei.</p>')
            o.append(tabel(["Ocolul silvic", "acoperite de autorizație", "neacoperite"], rows, {1, 2}))
            o.append("</section>")

        # ariile protejate
        per_arie = defaultdict(lambda: {"n": 0, "r": 0, "tip": ""})
        for a in zs:
            for x in a.get("arii") or []:
                if isinstance(x, dict) and x.get("nume"):
                    per_arie[x["nume"]]["n"] += 1
                    per_arie[x["nume"]]["tip"] = x.get("tip") or ""
                    if grp[a["id"]] == "rosu":
                        per_arie[x["nume"]]["r"] += 1
        if per_arie:
            lst = sorted(per_arie.items(), key=lambda kv: (-kv[1]["r"], -kv[1]["n"]))
            rows = [[e(k), e(v["tip"]), fmt(v["n"]), fmt(v["r"])] for k, v in lst]
            o.append('<section class="sec"><h2>În arii protejate</h2>')
            o.append(tabel(["Aria", "tip", "zone", "fără autorizație"], rows, {2, 3}))
            o.append("</section>")

    # istoric lung
    if feat and feat["properties"].get("loss"):
        loss = feat["properties"]["loss"]
        ani = list(range(2001, 2001 + len(loss)))
        f2000 = feat["properties"].get("f2000") or 0
        o.append(f'<section class="sec"><h2>Din 2001 încoace</h2><p class="sub">Pădure pierdută pe an {e(in_jud)}, după harta Hansen '
                 f'(University of Maryland). Numără orice copaci dispăruți: tăieri legale sau nu, furtuni, incendii. '
                 f'Pădure în 2000: {e(ha_t(f2000))}; pierdută de atunci: {e(ha_t(sum(loss)))}.</p>')
        o.append(svg_hansen(ani, loss, f"Pădure pierdută pe an {in_jud}, 2001–{ani[-1]}"))
        o.append('<details class="tview"><summary>Vezi cifrele în tabel</summary>' +
                 tabel(["Anul", "ha pierdute"], [[str(a), fmt(v)] for a, v in zip(ani, loss)], {1}) + "</details></section>")

    # cine răspunde
    o.append('<section class="sec"><h2>Cine răspunde și unde sesizezi</h2>')
    if g:
        o.append(f'<p>Pădurile {e(in_jud.replace("în ", "din ", 1))} sunt în grija <b>Gărzii Forestiere {e(g)}</b>, '
                 f'instituția care controlează tăierile și aplică amenzile. Pădurea e administrată de ocoalele silvice; '
                 f'cele din tabelul de mai sus au emis autorizații lângă zonele găsite.</p>')
    o.append('<p>Sesizări: <a href="https://gfn.gov.ro/taieri-ilegale/" rel="noopener" target="_blank">formularul Gărzii Forestiere Naționale</a> '
             'primește sesizări și fără nume, cu locul și poze. Dacă tăierea e în desfășurare, sună la <b>112</b>. '
             'Trimite coordonatele și pozele înainte/după din fișa zonei de pe hartă.</p></section>')

    # cum citești
    o.append('<section class="sec how"><h2>Cum citești pagina</h2><ul>'
             '<li><b>Ce vedem.</b> Sateliții Sentinel-2 trec peste fiecare loc cam la trei zile. Căutăm locuri unde pădurea s-a schimbat față de imaginile de dinainte.</li>'
             '<li><b>Ce verificăm.</b> Pentru fiecare loc căutăm autorizațiile de tăiere (APV) publicate în Inspectorul Pădurii și verificăm dacă parcela și perioada lor acoperă locul.</li>'
             '<li><b>Cine se uită.</b> Un analist AI (Claude) se uită la poza detaliată de dinainte și la pozele din satelit și spune ce s-a întâmplat. Când nu e sigur, locul rămâne „de confirmat”, nu roșu.</li>'
             '<li><b>Ce nu putem ști.</b> Din satelit nu se vede cine a tăiat și nici dacă există o hârtie nepublicată. Roșu înseamnă „de întrebat”, nu „vinovat”.</li>'
             '</ul></section>')

    # date
    if zs:
        o.append('<section class="sec"><h2>Datele județului</h2><p>Toate zonele văzute în județ, cu starea, autorizația cea mai apropiată și ce vede analistul: '
                 '<a href="zone.csv" download>zone.csv</a> (pentru Excel) · <a href="zone.geojson" download>zone.geojson</a> (pentru hărți, QGIS).</p></section>')

    o.append(COADA.format(rel="../../", ver=VER, upd=e(upd)))
    d = OUT / s
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text("".join(o), encoding="utf-8")
    scrie_date(d, zs, verd, jud)
    return {"nume": nume, "slug": s, "n": len(zs), "ha": tot_ha, "rosu": cnt["rosu"], "rosu_ha": ha["rosu"],
            "verde": cnt["verde"], "garda": g}


def scrie_date(d, zs, verd, jud):
    cols = ["id", "judet", "uat", "localitate", "lat", "lon", "ha", "prima_data", "poza_inainte", "poza_dupa", "stare", "stare_text",
            "motiv", "apv", "ocol", "apv_de_la", "apv_pana_la", "apv_distanta_m", "arie_protejata", "analist_categorie",
            "analist_incredere", "ce_se_vede", "teren", "parte_stat", "parte_privat", "parte_amenajament", "link"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    feats = []
    for a in sorted(zs, key=lambda a: a.get("first_seen") or "", reverse=True):
        v = verd.get(a["id"]) or {}
        j = jud.get(a["id"]) or {}
        u = a.get("uat") or {}
        arii = "; ".join(x.get("nume") for x in (a.get("arii") or []) if isinstance(x, dict) and x.get("nume"))
        row = {"id": a["id"], "judet": judet_de(a), "uat": f"{u.get('tip') or ''} {u.get('nume') or ''}".strip(),
               "localitate": a.get("localitate") or "", "lat": a.get("lat"), "lon": a.get("lon"), "ha": a.get("ha"),
               "prima_data": a.get("first_seen"), "poza_inainte": a.get("before_date"), "poza_dupa": a.get("after_date"),
               "stare": v.get("stare") or "nev", "stare_text": STARE_T.get(v.get("stare") or "nev", ""), "motiv": v.get("motiv") or "",
               "apv": v.get("apv") or "", "ocol": v.get("ocol") or "", "apv_de_la": v.get("start") or "", "apv_pana_la": v.get("end") or "",
               "apv_distanta_m": v.get("dist_m") if v.get("apv") else "", "arie_protejata": arii,
               "analist_categorie": j.get("categorie") or "", "analist_incredere": j.get("incredere") if j else "",
               "ce_se_vede": j.get("motiv") or "", "teren": TEREN_T.get(teren(v) or "", ""),
               "parte_stat": (v.get("proprietate") or {}).get("stat", ""), "parte_privat": (v.get("proprietate") or {}).get("privat", ""),
               "parte_amenajament": v.get("amenajament") if v.get("amenajament") is not None else "",
               "link": f"https://iliemihai.github.io/padurea-ro/#a={a['id']}"}
        w.writerow([row[c] for c in cols])
        feats.append({"type": "Feature", "geometry": a.get("geometry"), "properties": row})
    (d / "zone.csv").write_text("﻿" + buf.getvalue(), encoding="utf-8")
    (d / "zone.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# ---------------------------------------------------------------- indexul
def pagina_index(rez, meta, upd):
    rez = sorted(rez, key=lambda r: (-r["rosu_ha"], -r["ha"]))
    tot = {k: sum(r[k] for r in rez) for k in ("n", "ha", "rosu", "rosu_ha", "verde")}
    mx = max([r["rosu_ha"] for r in rez] + [0.0001])
    lead = (f"Din {zi(meta.get('istoric_de_la'), True)} până pe {zi(meta.get('data_until'), True)}, satelitul a văzut schimbări în pădure "
            f"sau la marginea ei în {nr(tot['n'], 'loc', 'locuri')} ({ha_t(tot['ha'])}). În {nr(tot['rosu'], 'loc', 'locuri')} "
            f"({ha_t(tot['rosu_ha'])}) pozele arată pădure tăiată și nu am găsit o autorizație care să acopere locul.")
    o = [CAP.format(title="Județele · Pădurea RO", desc=e(lead), rel="../", ver=VER, cur_j=' aria-current="page"')]
    o.append(f'<h1>Județele</h1><p class="lead">{e(lead)}</p>')
    o.append('<section class="sec"><p class="sub">Ordonate după hectarele fără autorizație care să le acopere. Dă clic pe un județ pentru pagina lui.</p>'
             '<div class="tblwrap"><table class="tbl idx"><thead><tr><th scope="col">Județul</th>'
             '<th scope="col" class="barcol"><i class="key s-rosu" aria-hidden="true"></i>ha fără autorizație</th>'
             '<th scope="col" class="r">locuri fără autorizație</th><th scope="col" class="r">toate locurile</th><th scope="col" class="r">ha, toate</th>'
             '<th scope="col" class="r">cu autorizație</th><th scope="col">Garda Forestieră</th></tr></thead><tbody>')
    for r in rez:
        w = 100 * r["rosu_ha"] / mx
        o.append(f'<tr><td><a href="{e(r["slug"])}/">{e(r["nume"])}</a></td>'
                 f'<td class="barcol"><span class="hbar"><span class="fill s-rosu" style="width:{w:.1f}%"></span></span><span class="num">{fmt(r["rosu_ha"], 1)}</span></td>'
                 f'<td class="r num">{fmt(r["rosu"])}</td><td class="r num">{fmt(r["n"])}</td><td class="r num">{fmt(r["ha"], 1)}</td>'
                 f'<td class="r num">{fmt(r["verde"])}</td><td>{e(r["garda"] or "")}</td></tr>')
    o.append("</tbody></table></div></section>")
    o.append(COADA.format(rel="../", ver=VER, upd=e(upd)))
    (OUT / "index.html").write_text("".join(o), encoding="utf-8")


def main():
    zone, verd, jud, meta, cty = incarca()
    upd = zi(dt.date.today().isoformat(), True)
    pe_judet = defaultdict(list)
    for a in zone.values():
        pe_judet[judet_de(a)].append(a)
    feats = {f["properties"]["n"]: f for f in cty["features"]}
    m0 = (meta.get("istoric_de_la") or min(a["first_seen"] for a in zone.values()))[:7]
    m1 = (meta.get("data_until") or max(a["first_seen"] for a in zone.values()))[:7]
    luni = luni_intre(m0, m1)
    OUT.mkdir(parents=True, exist_ok=True)
    rez = []
    for nume in sorted(feats, key=lambda x: slug(x)):
        rez.append(pagina_judet(nume, pe_judet.get(nume, []), verd, jud, meta, feats[nume], luni, upd))
    fara = [k for k in pe_judet if k not in feats]
    if fara:
        print("zone fără județ cunoscut în contururi:", {k: len(pe_judet[k]) for k in fara})
    pagina_index(rez, meta, upd)
    # zonele roșii din tot istoricul, întregi: harta pornește cu ele fără să aducă toată arhiva
    rosii = sorted((a for a in zone.values() if (verd.get(a["id"]) or {}).get("stare") in ("fara", "neacoperit")),
                   key=lambda a: a.get("first_seen") or "", reverse=True)
    (DOCS / "data" / "rosii.json").write_text(json.dumps({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                                                          "alerts": rosii}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rez)} pagini de județ -> {OUT}; roșii: {sum(r['rosu'] for r in rez)}")


if __name__ == "__main__":
    main()
