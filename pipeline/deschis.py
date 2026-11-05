"""Pădurea RO, ca să poată fi citată: un link permanent pentru fiecare zonă, datele de descărcat, un flux.

    docs/zona/<id>/index.html   pagina zonei: ce, unde, când, înainte/după, autorizația, cui te adresezi, cum o citezi
    docs/zona/<id>/zona.json    aceeași zonă, ca GeoJSON, pentru programe
    docs/zona/<id>/og.jpg       imaginea care apare când linkul e pus pe WhatsApp, Facebook, X (doar zonele care se
                                distribuie: roșii, cu știri sau verificări; restul folosesc docs/og.jpg)
    docs/date/                  toate zonele: zone.csv, zone.geojson, index.json (intrarea în API), licența, dicționarul
    docs/date/registru.json     fiecare zonă publicată vreodată: de când e pe site, cum i s-a schimbat starea, dacă a fost retrasă
    docs/feed.xml               zonele noi fără autorizație care s-o acopere (Atom), pentru cine vrea să le urmărească

Un link dat cuiva nu trebuie să moară: dacă o zonă iese de pe hartă (o regulă nouă o scoate), pagina ei rămâne,
cu ce știam despre ea și cu data la care a fost retrasă. Paginile nu poartă data rulării și se rescriu doar când se
schimbă ceva în ele, ca istoricul din git să crească puțin.

    python -m pipeline.deschis
"""
import csv
import datetime as dt
import hashlib
import io
import json
from collections import Counter
from urllib.parse import quote

from . import config as C
from . import og, writer
from .judete import (CAP, COADA, COLS, GARZI, MOTIV_NEACOPERIT, STARE_T, TEREN_LUNG, contur, e, fmt, ha_t, incarca, judet_de,
                     loc_t, nav, og_meta, rand, slug, teren, zi)

DOCS = C.DOCS
ZONA = DOCS / "zona"
DATE = DOCS / "date"
REGISTRU = DATE / "registru.json"
REPO = "https://github.com/iliemihai/padurea-ro"
LICENTA = "CC BY 4.0"
LICENTA_URL = "https://creativecommons.org/licenses/by/4.0/deed.ro"
ESRI = ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
        "?bboxSR=4326&imageSR=3857&size=600,600&format=jpg&f=image&bbox=")
ROSU = ("fara", "neacoperit")

# aceleași texte ca pe hartă (docs/app.js, AUT_T): ce înseamnă fiecare stare, pe larg
STARE_LUNG = {
    "fara": "Nu am găsit nicio autorizație de tăiere în jurul zonei.",
    "neacoperit": "Există o autorizație cu parcela publicată în amenajament, dar nu acoperă tăierea asta.",
    "vegetatie": "Analistul nu vede pădure tăiată: înainte era pășune, fâneață sau teren cu copaci răzleți și tufăriș, nu pădure "
                 "închisă. Dacă s-au scos copaci de pe pășune, și asta cere autorizație de la ocolul silvic (Codul silvic, art. 60), "
                 "dar aceste autorizații nu apar sigur în registrul public, așa că nu putem spune dacă există. Nu e dovadă de ilegalitate.",
    "probabil": "Am găsit o autorizație de tăiere pentru locul ăsta, dar registrul nu ne lasă să confirmăm că acoperă exact tăierea pe care o vedem.",
    "acoperit": "Parcela autorizată acoperă zona, iar autorizația era valabilă când s-a tăiat.",
    "nu_taiere": "Schimbarea nu pare tăiere de lemn, așa că autorizațiile de tăiere nu se aplică.",
    "nejudecat": "N-am găsit o autorizație care să acopere zona, dar nu putem spune ce s-a întâmplat aici: analistul AI fie n-a văzut "
                 "încă pozele, fie le-a văzut și nu e sigur. Nu dăm roșu pe o bănuială, și nici nu spunem că e în regulă.",
    "nev": "Zona n-a fost încă comparată cu autorizațiile din Inspectorul Pădurii. Nu e un semn, nici bun, nici rău.",
}
MOTIV_LUNG = {
    "probabil": {"fara_parcela": "Amenajamentul nu publică harta parcelei autorizației, deci nu știm exact unde e. De cele mai multe ori o acoperă.",
                 "dupa_termen": "Autorizația acoperă chiar locul, dar se terminase înainte să vedem schimbarea. Cel mai des e o tăiere făcută "
                                "toamna sau iarna, cât autorizația era valabilă, pe care satelitul o vede abia primăvara; sau scosul lemnului după tăiere."},
    "nu_taiere": {"drum": "E o linie lungă și îngustă, ca un drum, o autostradă sau o linie electrică. Un drum prin pădure se aprobă altfel, "
                          "prin scoatere din fondul forestier, nu cu autorizație de tăiere.",
                  "altceva": "Zona nu era pădure nici înainte: livadă, vie, tufăriș, construcții sau carieră.",
                  "agricol": "Analistul AI vede teren agricol: arătură sau recoltă, nu pădure tăiată.",
                  "incendiu": "Analistul AI vede urme de foc, nu de tăiere.",
                  "nori": "Analistul AI crede că schimbarea vine din nori, nu de pe teren.",
                  "toamnă": "Analistul AI crede că e doar frunza care se îngălbenește toamna.",
                  "santier": "E o lucrare, nu o exploatare de lemn: drum, cale ferată, linie electrică, conductă, carieră sau șantier.",
                  "camp": "E teren agricol: arat, cosit sau recoltat. Nu era pădure.",
                  "sezon": "Nu s-a schimbat nimic pe teren: e doar sezonul, norii sau lumina."},
    "nejudecat": {"contrazis": "Analistul vede tăiere, dar hărțile de teren spun câmp, coridor sau carieră. Până nu se lămurește, nu dăm roșu.",
                  "nesigur": "Analistul crede că e pădure tăiată, dar nu e sigur: pozele sunt neclare sau schimbarea e la limită.",
                  "nesigur_nu": "Analistul înclină spre altceva decât o tăiere, dar nu e sigur. Printre astfel de zone au fost și tăieri reale.",
                  "neclar": "Analistul n-a putut spune ce s-a întâmplat aici din poze. Rămâne de verificat cu o imagine mai bună."},
}
NU_VERIFICAT = "Nu am verificat dacă există o autorizație de exploatare (unele se pot căuta în aplicația Inspectorul Pădurii)."
MERITA = "E o schimbare care merită verificată."


# ---------------------------------------------------------------- mărunțișuri
def scrie(path, text):
    """Scrie doar dacă s-a schimbat. Întoarce True dacă a scris."""
    data = text.encode("utf-8")   # pe octeți: CSV-ul are \r\n, pe care read_text l-ar schimba
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def jdump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"), sort_keys=False)


def ver_css():
    """Versiunea foii de stil după conținut, nu după oră: paginile nu se rescriu degeaba la fiecare rulare."""
    return hashlib.sha1((DOCS / "judet" / "judet.css").read_bytes()).hexdigest()[:10]


def azi():
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def titlu_zona(a):
    sat = a.get("localitate")
    unde = f"lângă {sat}" if sat else (f"în {(a.get('uat') or {}).get('nume')}" if (a.get("uat") or {}).get("nume") else "")
    return f"{ha_t(a.get('ha') or 0)} de pădure schimbată {unde}".strip()


def cand_t(a):
    if a.get("before_date"):
        return f"între {zi(a['before_date'], True)} și {zi(a['first_seen'], True)}"
    if a.get("vara"):
        return f"între vara lui {a['vara']} și {zi(a['first_seen'], True)}"
    return f"până pe {zi(a['first_seen'], True)}"


def garda(a):
    j = judet_de(a)
    return next((g for g, js in GARZI.items() if j in js), None)


def motiv_t(stare, v):
    m = v.get("motiv")
    if stare == "neacoperit":
        return MOTIV_NEACOPERIT.get(m, "")
    return (MOTIV_LUNG.get(stare) or {}).get(m, "")


def lead(a, stare):
    """Prima frază a redactorului (writer.py: când, unde, cât), plus ce știm acum din registrul de autorizații.
    Restul textului lui (câte imagini, arii protejate, foc, vânt, Hansen) e în „Pe scurt”."""
    t = a.get("text") or writer.text(a)
    t = t.split("puternic.", 1)[0] + "puternic." if "puternic." in t else t.replace(NU_VERIFICAT, "").replace(MERITA, "").strip()
    if stare in ROSU:
        t += " Nu am găsit o autorizație de tăiere care să acopere locul. Nu înseamnă automat că e ilegal; e un loc de întrebat."
    elif stare in ("acoperit", "probabil"):
        t += " În registrul public există o autorizație de tăiere pentru acest loc."
    elif stare == "nu_taiere":
        t += " Nu pare o tăiere de lemn."
    else:
        t += " " + MERITA
    return t


def loc_lung(a):
    """„Zăvoi, municipiul Pitești, județul Argeș”; satul doar dacă nu e chiar comuna."""
    u = a.get("uat") or {}
    sat = a.get("localitate") if a.get("localitate") != u.get("nume") else None
    return ", ".join(x for x in [sat, f"{u.get('tip', '')} {u.get('nume', '')}".strip() if u.get("nume") else "",
                                 f"județul {judet_de(a)}" if judet_de(a) else ""] if x)


def citare(a, url):
    unde = loc_lung(a)
    return (f"Pădurea RO, zona {a['id']}: {ha_t(a.get('ha') or 0)}, {unde}; schimbare văzută din satelit {cand_t(a)}. "
            f"{url} (consultat la [data]). Date: {LICENTA}.")


# ---------------------------------------------------------------- registrul: ce a fost publicat vreodată
def registru(zone, verd):
    """Ține minte fiecare zonă publicată: de când e pe site, ce stări a avut, dacă a fost retrasă."""
    reg = json.loads(REGISTRU.read_text(encoding="utf-8")).get("zone", {}) if REGISTRU.exists() else {}
    zi_azi = azi()
    for i, a in zone.items():
        st = (verd.get(i) or {}).get("stare") or "nev"
        r = reg.get(i)
        snap = {"prima_data": a.get("first_seen"), "ha": a.get("ha"), "lat": a.get("lat"), "lon": a.get("lon"),
                "judet": judet_de(a), "loc": loc_t(a)}
        if r is None:
            reg[i] = {"pe_site_din": zi_azi, "stari": [[zi_azi, st]], "retrasa": None, "ultima": snap}
            continue
        if r.get("retrasa"):
            r["retrasa"] = None
            r["stari"].append([zi_azi, "reapărută"])
        if r["stari"][-1][1] != st:
            if r["stari"][-1][0] == zi_azi and r["stari"][-1][1] != "reapărută":
                r["stari"][-1][1] = st   # schimbată de două ori în aceeași zi: ține doar ultima
            else:
                r["stari"].append([zi_azi, st])
        r["ultima"] = snap
    for i, r in reg.items():
        if i not in zone and not r.get("retrasa"):
            r["retrasa"] = zi_azi
    return dict(sorted(reg.items()))


# ---------------------------------------------------------------- pagina zonei
def fapte(a, v, j, u):
    rows = [("Identificator", f'<span class="mono">{e(a["id"])}</span>'),
            ("Locul", e(loc_lung(a)) +
             (f' <span class="muted">(SIRUTA {e(u["siruta"])})</span>' if u.get("siruta") else "")),
            ("Coordonate (centru)", f'<span class="mono">{a["lat"]:.5f}, {a["lon"]:.5f}</span> · '
                                    f'<a href="https://www.google.com/maps/@?api=1&amp;map_action=map&amp;center={a["lat"]},{a["lon"]}&amp;zoom=16&amp;basemap=satellite" rel="noopener">Google Maps</a> · '
                                    f'<a href="https://www.openstreetmap.org/?mlat={a["lat"]}&amp;mlon={a["lon"]}#map=15/{a["lat"]}/{a["lon"]}" rel="noopener">OpenStreetMap</a>'),
            ("Suprafața", f'<span class="mono">{e(ha_t(a.get("ha") or 0))}</span> <span class="muted">(din pixeli de 10 m; ± câțiva pixeli pe margine)</span>')]
    if a.get("before_date"):
        rows.append(("Ultima imagine cu pădurea întreagă", f'<span class="mono">{e(zi(a["before_date"], True))}</span>'))
    elif a.get("vara"):
        rows.append(("Pădurea întreagă", f"în vara lui {e(a['vara'])} (de atunci, nori sau iarnă)"))
    rows.append(("Prima imagine cu schimbarea", f'<span class="mono">{e(zi(a["first_seen"], True))}</span>'))
    if a.get("extinsa"):
        rows.append(("S-a lărgit", f'<span class="mono">{e(zi(a["extinsa"], True))}</span>'))
    rows.append(("Imagini în care se vede schimbarea", f'<span class="mono">{e(a.get("n_dates") or "")}</span>'))
    rows.append(("Cât de sigur e semnalul din satelit", e(a.get("incredere") or "")))
    if v.get("apv"):
        per = f", valabilă {zi(v.get('start'), True)} – {zi(v.get('end'), True)}" if v.get("start") else ""
        dist = f", la {fmt(v.get('dist_m') or 0)} m de zonă" if v.get("dist_m") is not None else ""
        rows.append(("Autorizația cea mai apropiată", f'<span class="mono">APV {e(v["apv"])}</span> · {e((v.get("ocol") or "").title())}{e(per)}{e(dist)}'))
    t = teren(v)
    if t:
        rows.append(("Terenul", e(TEREN_LUNG[t].replace("Terenul: ", "").rstrip("."))))
    arii = list(dict.fromkeys(x.get("nume") for x in (a.get("arii") or []) if isinstance(x, dict) and x.get("nume")))
    if arii:
        rows.append(("Arie protejată", e(", ".join(arii))))
    fi = a.get("firms") or {}
    if fi.get("n"):
        rows.append(("Foc văzut de NASA (FIRMS)", f"la {fmt(fi.get('dist_m') or 0)} m, {e(zi(fi.get('prima'), True))}"))
    if a.get("vant"):
        rows.append(("Vânt puternic în interval", f'rafale de până la <span class="mono">{e(a.get("rafala_kmh"))} km/h</span>'))
    hj = a.get("hansen_jur") or {}
    if hj.get("ani"):
        rows.append(("Pădure pierdută în jur, alți ani", e(", ".join(str(y) for y in hj["ani"])) + ' <span class="muted">(Hansen)</span>'))
    if a.get("langa"):
        rows.append(("Chiar lângă", f'o altă schimbare, văzută pe {e(zi(a["langa"]["first_seen"], True))}: '
                                    f'<a href="../{e(a["langa"]["id"])}/">pagina ei</a>'))
    g = garda(a)
    if g:
        rows.append(("Garda Forestieră", e(g)))
    return '<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v_}</dd>" for k, v_ in rows) + "</dl>"


def poze(a, rel):
    ib, ia, cb = a.get("img_before") or {}, a.get("img_after") or {}, a.get("chip_bbox")
    if not (ib.get("file") and ia.get("file") and cb):
        return ""
    ct = contur(a)
    esri = ESRI + ",".join(f"{x:.6f}" for x in cb)
    return ('<div class="pair zpair">'
            f'<figure><div class="ph"><img src="{rel}img/{e(ib["file"])}" alt="înainte, imagine Sentinel-2" width="90" height="90">{ct}</div>'
            f'<figcaption>înainte · {e(zi(ib.get("date")))}</figcaption></figure>'
            f'<figure><div class="ph"><img src="{rel}img/{e(ia["file"])}" alt="după, imagine Sentinel-2" width="90" height="90">{ct}</div>'
            f'<figcaption>după · {e(zi(ia.get("date")))}</figcaption></figure>'
            f'<figure><div class="ph"><img src="{esri}" alt="poza detaliată de dinainte" loading="lazy" width="600" height="600" '
            f'onerror="this.style.display=\'none\'">{ct}</div><figcaption>detaliat, mai veche · Esri</figcaption></figure></div>'
            '<p class="caveat">Înainte și după: Copernicus Sentinel-2, 10 m pe pixel, conturul zonei cu portocaliu. '
            'Poza detaliată (Esri World Imagery) e de acum 1–4 ani: arată ce era acolo înainte, nu tăierea.</p>')


def istoric(r):
    if not r:
        return ""
    li = []
    st = r.get("stari") or []
    for k, (d, s) in enumerate(st):
        pana = f" – {zi(st[k + 1][0], True)}" if k + 1 < len(st) else " – azi"
        lab = "a reapărut pe hartă" if s == "reapărută" else STARE_T.get(s, s)
        li.append(f'<li><span class="mono">{e(zi(d, True))}{e(pana)}</span> · {e(lab)}</li>')
    return ('<section class="sec"><h2>Istoricul zonei pe hartă</h2><p class="sub">Starea se poate schimba când registrul publică o '
            'autorizație sau când analistul vede poze mai bune. O ținem aici, ca un link citat să arate și ce spuneam atunci.</p>'
            f'<p class="sub">Pe hartă cel târziu din {e(zi(r["pe_site_din"], True))}.</p><ul class="hist">{"".join(li)}</ul></section>')


def tehnic(a, j):
    f = a.get("f") or {}
    ai = a.get("ai") or {}
    rows = [("Placa Sentinel-2", a.get("tile")), ("NDVI de referință", a.get("ndvi_ref")), ("NBR de referință", a.get("nbr_ref")),
            ("Scăderea în pădurea din jur", a.get("neigh_drop")), ("Persistență", a.get("persist")),
            ("NDVI / NBR după", f"{f.get('nd')} / {f.get('nb')}" if f else None),
            ("Analistul de zi (model)", f"{ai.get('categorie')} · {ai.get('incredere')} · {ai.get('model')}" if ai else None),
            ("Analistul cu context (model)", f"{j.get('categorie')} · {j.get('incredere')}" if j else None)]
    dl = "".join(f'<dt>{e(k)}</dt><dd class="mono">{e(v)}</dd>' for k, v in rows if v not in (None, ""))
    dov = "".join(f"<li>{e(x)}</li>" for x in (a.get("dovezi") or []))
    det = f'<p><b>Ce a văzut analistul cu context:</b> {e(j.get("detalii"))}</p>' if j.get("detalii") else ""
    return ('<details class="sec tech"><summary>Detalii tehnice, pentru verificare</summary>'
            f'<p class="sub">De ce acest nivel de încredere:</p><ul>{dov}</ul>{det}<dl class="facts">{dl}</dl>'
            '<p class="sub">Cum se calculează fiecare: <a href="../../metodologie/">metodologia</a>.</p></details>')


def surse_extra(i, stiri, verif):
    items = (verif.get(i) or []) + (stiri.get(i) or [])
    if not items:
        return ""
    li = []
    for x in items:
        txt = e(x.get("text") or x.get("titlu") or x.get("sursa") or "")
        link = f' <a href="{e(x["url"])}" rel="noopener">sursa</a>' if x.get("url") else ""
        li.append(f'<li><b>{e(x.get("sursa") or "")}</b> ({e(x.get("potrivire") or "")}): {txt}{link}</li>')
    return f'<section class="sec"><h2>Din alte surse</h2><ul class="src">{"".join(li)}</ul></section>'


def pagina_zona(a, v, j, r, stiri, verif, ver, og_img):
    i = a["id"]
    rel = "../../"
    url = f"{C.SITE_URL}zona/{i}/"
    st = v.get("stare") or "nev"
    u = a.get("uat") or {}
    titlu = titlu_zona(a)
    desc = lead(a, st)
    jud = judet_de(a)
    o = [CAP.format(title=e(f"{titlu} · Pădurea RO"), desc=e(desc), rel=rel, ver=ver, nav=nav(rel),
                    extra=og_meta(f"zona/{i}/", og_img) + f'<link rel="alternate" type="application/geo+json" href="zona.json">\n')]
    crumbs = '<a href="../../judet/">Județe</a>' + (f' › <a href="../../judet/{e(slug(jud))}/">{e(jud)}</a>' if jud else "")
    o.append(f'<p class="crumbs">{crumbs}</p><h1>{e(titlu)}</h1><p class="lead">{e(desc)}</p>')
    # starea autorizației, cu explicația
    m = motiv_t(st, v)
    o.append(f'<section class="zstatus z-{e(st)}"><p class="lbl">Autorizația de tăiere</p>'
             f'<p class="st"><i class="key a-{e(st)}" aria-hidden="true"></i>{e(STARE_T.get(st, st))}</p>'
             f'<p>{e(STARE_LUNG.get(st, ""))}{(" " + e(m[0].upper() + m[1:]) + ("" if m.endswith(".") else ".")) if m else ""}</p>'
             + (f'<p><b>Ce se vede în poze:</b> {e(j["motiv"])}</p>' if j.get("motiv") else "") + "</section>")
    o.append(poze(a, rel))
    o.append(f'<section class="sec"><h2>Pe scurt</h2>{fapte(a, v, j, u)}</section>')
    # ce poți face
    g = garda(a)
    o.append('<section class="sec how"><h2>Dacă vrei să verifici sau să sesizezi</h2><ul>'
             + (f"<li>Pădurile din {'București' if jud == 'București' else 'județul ' + e(jud)} sunt în grija <b>Gărzii Forestiere {e(g)}</b>, "
                "care controlează tăierile și dă amenzile.</li>" if g else "")
             + (f"<li>Autorizația găsită în zonă e emisă de <b>{e((v.get('ocol') or '').title())}</b>.</li>" if v.get("ocol") else "")
             + '<li><a href="https://gfn.gov.ro/taieri-ilegale/" rel="noopener">Formularul Gărzii Forestiere Naționale</a> primește sesizări '
             'și fără nume. Trimite linkul acestei pagini, coordonatele și pozele. Dacă tăierea e în desfășurare, sună la <b>112</b>.</li>'
             '<li>Autorizațiile și transporturile de lemn se pot căuta în <a href="https://inspectorulpadurii.ro" rel="noopener">Inspectorul Pădurii</a>.</li>'
             '</ul><p class="caveat">Pagina arată ce se vede din satelit și ce scrie în registrul public; nu e o dovadă în sine.</p></section>')
    o.append(surse_extra(i, stiri, verif))
    # cum o citezi
    o.append('<section class="sec"><h2>Cum citezi zona</h2>'
             f'<p class="sub">Linkul acestei pagini nu se schimbă. Dacă zona iese vreodată de pe hartă, pagina rămâne, cu data și cu ce știam despre ea.</p>'
             f'<pre class="cite">{e(citare(a, url))}</pre>'
             f'<p class="sub">Datele zonei: <a href="zona.json">GeoJSON</a> · toate zonele: <a href="../../date/">date deschise</a> · '
             f'licența <a href="{LICENTA_URL}" rel="noopener">{LICENTA}</a>.</p></section>')
    o.append(istoric(r))
    o.append(tehnic(a, j))
    iframe = (f'<iframe src="{C.SITE_URL}embed/?a={i}" width="100%" height="420" style="border:0" loading="lazy" '
              f'title="Pădurea RO: {titlu.replace(chr(34), "")}"></iframe>')
    o.append('<details class="sec"><summary>Pune harta zonei într-un articol</summary>'
             '<p class="sub">Copiază codul în articol (merge în majoritatea site-urilor de știri). Sau pune doar linkul: '
             'WhatsApp, Facebook și X arată singure poza zonei.</p>'
             f'<textarea class="code" readonly rows="3" onclick="this.select()">{e(iframe)}</textarea></details>')
    issue = f"{REPO}/issues/new?title=" + quote(f"Zona {i}") + "&body=" + quote(f"Ce e greșit la zona {i}?\n\n{url}")
    o.append(f'<p class="links"><a class="go" href="../../#a={e(i)}">Vezi zona pe hartă</a> · '
             f'<a href="{issue}" rel="noopener">Raportează o greșeală</a></p>')
    o.append(COADA.format(rel=rel, ver=ver, upd=e(zi(r["stari"][-1][0], True) if r else "")).replace(
        "Actualizat ", f"Datele: {LICENTA}, cu sursa „Pădurea RO”. Starea de mai sus e valabilă din "))
    return "".join(o)


def pagina_retrasa(i, r, ver):
    rel = "../../"
    s = r.get("ultima") or {}
    titlu = f"Zona {i}, retrasă de pe hartă"
    desc = (f"Zona {i} ({ha_t(s.get('ha') or 0)}, {s.get('loc') or ''}, {s.get('judet') or ''}) a fost pe hartă cel târziu din "
            f"{zi(r.get('pe_site_din'), True)} până pe {zi(r.get('retrasa'), True)}.")
    stari = "".join(f"<li><span class=\"mono\">{e(zi(d, True))}</span> · {e(STARE_T.get(x, x))}</li>" for d, x in r.get("stari") or [])
    o = [CAP.format(title=e(f"{titlu} · Pădurea RO"), desc=e(desc), rel=rel, ver=ver, nav=nav(rel), extra=og_meta(f"zona/{i}/"))]
    o.append(f'<p class="crumbs"><a href="../../judet/">Județe</a></p><h1>{e(titlu)}</h1><p class="lead">{e(desc)}</p>'
             '<p class="caveat">O zonă iese de pe hartă când o verificare nouă arată că schimbarea nu se mai vede în imaginile următoare '
             '(nori, umbre, sezon) sau când o regulă nouă o reclasifică. Păstrăm pagina ca linkurile citate să nu moară.</p>'
             f'<section class="sec"><h2>Ce știam</h2><dl class="facts"><dt>Prima imagine cu schimbarea</dt><dd class="mono">{e(zi(s.get("prima_data"), True))}</dd>'
             f'<dt>Coordonate</dt><dd class="mono">{e(s.get("lat"))}, {e(s.get("lon"))}</dd><dt>Suprafața</dt><dd class="mono">{e(ha_t(s.get("ha") or 0))}</dd></dl></section>'
             f'<section class="sec"><h2>Stările pe care le-a avut</h2><ul class="hist">{stari}</ul></section>')
    o.append(COADA.format(rel=rel, ver=ver, upd=e(zi(r.get("retrasa"), True))).replace("Actualizat ", "Retrasă de pe hartă pe "))
    return "".join(o)


def zona_json(a, row, r):
    props = dict(row)
    props.update({"text": a.get("text"), "dovezi": a.get("dovezi") or [], "istoric_stari": (r or {}).get("stari") or [],
                  "pe_site_din": (r or {}).get("pe_site_din"), "licenta": LICENTA, "sursa": "Pădurea RO", "citare": citare(a, row["link"])})
    return jdump({"type": "Feature", "id": a["id"], "geometry": a.get("geometry"), "properties": props})


# ---------------------------------------------------------------- datele deschise
CAMPURI = {
    "id": "identificatorul zonei; nu se schimbă (data primei observații, latitudinea și longitudinea × 1000)",
    "judet": "județul", "uat": "comuna, orașul sau municipiul (limitele UAT)", "siruta": "codul SIRUTA al UAT-ului",
    "localitate": "satul cel mai apropiat (GeoNames)", "lat": "latitudinea centrului (WGS84)", "lon": "longitudinea centrului (WGS84)",
    "ha": "suprafața schimbată, în hectare", "prima_data": "prima imagine Sentinel-2 în care se vede schimbarea",
    "poza_inainte": "data imaginii „înainte” (ultima cu pădurea întreagă)", "poza_dupa": "data imaginii „după”",
    "incredere_semnal": "cât de sigur e semnalul din satelit: ridicată, medie, scăzută",
    "stare": "starea față de autorizațiile de tăiere (cod)", "stare_text": "starea, în cuvinte",
    "motiv": "de ce are starea asta (cod)", "apv": "numărul autorizației de tăiere (APV) cea mai apropiate",
    "ocol": "ocolul silvic care a emis autorizația", "apv_de_la": "autorizația, valabilă de la", "apv_pana_la": "autorizația, valabilă până la",
    "apv_distanta_m": "distanța de la zonă la autorizație, în metri", "arie_protejata": "ariile protejate în care cade zona",
    "analist_categorie": "ce vede analistul AI cu context", "analist_incredere": "cât de sigur e analistul (0–1)",
    "ce_se_vede": "ce vede analistul în poze, în cuvinte", "teren": "al cui e terenul, după amenajamentele publicate",
    "parte_stat": "partea din zonă în pădure de stat (0–1)", "parte_privat": "partea din zonă în pădure privată (0–1)",
    "parte_amenajament": "partea din zonă în amenajamente silvice publicate (0–1)",
    "link": "pagina permanentă a zonei", "link_harta": "zona, pe hartă",
}
TIPURI = {"lat": "number", "lon": "number", "ha": "number", "apv_distanta_m": "number", "analist_incredere": "number",
          "parte_stat": "number", "parte_privat": "number", "parte_amenajament": "number",
          "prima_data": "date", "poza_inainte": "date", "poza_dupa": "date", "apv_de_la": "date", "apv_pana_la": "date"}
SURSE = [
    ("Copernicus Sentinel-2 L2A (ESA), prin Microsoft Planetary Computer", "conține date Copernicus Sentinel modificate"),
    ("ESA WorldCover 2021", "CC BY 4.0"), ("Hansen et al., Global Forest Change 2000–2025 (Universitatea Maryland)", "CC BY 4.0"),
    ("Agenția Europeană de Mediu: Natura 2000 și CDDA", "CC BY 4.0"), ("GeoNames", "CC BY 4.0"),
    ("Inspectorul Pădurii (SUMAL 2.0, Ministerul Mediului)", "informații de interes public"),
    ("limitele UAT: geo-spatial.org", "vezi sursa"), ("NASA FIRMS", "date publice NASA"),
]


def date_deschise(zone, verd, jud, meta, reg, ver):
    DATE.mkdir(parents=True, exist_ok=True)
    rows, feats = [], []
    for a in sorted(zone.values(), key=lambda a: (a.get("first_seen") or "", a["id"]), reverse=True):
        row = rand(a, verd.get(a["id"]) or {}, jud.get(a["id"]) or {})
        rows.append(row)
        feats.append({"type": "Feature", "id": a["id"], "geometry": a.get("geometry"), "properties": row})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLS)
    for row in rows:
        w.writerow([row[c] for c in COLS])
    n = 0
    n += scrie(DATE / "zone.csv", "﻿" + buf.getvalue())
    n += scrie(DATE / "zone.geojson", jdump({"type": "FeatureCollection", "licenta": LICENTA, "sursa": "Pădurea RO", "features": feats}))
    n += scrie(REGISTRU, jdump({"despre": "Fiecare zonă publicată vreodată pe Pădurea RO: de când e pe site, stările pe care le-a avut "
                                          "și, dacă e cazul, data la care a ieșit de pe hartă.", "zone": reg}))
    st = Counter(r["stare"] for r in rows)
    judete = sorted({r["judet"] for r in rows if r["judet"]})
    api = {
        "nume": "Pădurea RO, date deschise", "versiune": 1, "date_pana_la": meta.get("data_until"),
        "istoric_de_la": meta.get("istoric_de_la"), "licenta": LICENTA, "licenta_url": LICENTA_URL,
        "citare": f"Pădurea RO, {C.SITE_URL}, date {LICENTA}.",
        "zone": len(rows), "stari": dict(st),
        "fisiere": {"toate_zonele_csv": f"{C.SITE_URL}date/zone.csv", "toate_zonele_geojson": f"{C.SITE_URL}date/zone.geojson",
                    "zonele_fara_autorizatie": f"{C.SITE_URL}data/rosii.json", "registru": f"{C.SITE_URL}date/registru.json",
                    "flux_atom": f"{C.SITE_URL}feed.xml", "descriere_campuri": f"{C.SITE_URL}date/datapackage.json"},
        "sabloane": {"zona_pagina": C.SITE_URL + "zona/{id}/", "zona_geojson": C.SITE_URL + "zona/{id}/zona.json",
                     "judet_csv": C.SITE_URL + "judet/{judet}/zone.csv", "judet_geojson": C.SITE_URL + "judet/{judet}/zone.geojson"},
        "judete": [{"nume": j, "judet": slug(j)} for j in judete],
        "stari_explicate": STARE_T,
    }
    n += scrie(DATE / "index.json", json.dumps(api, ensure_ascii=False, indent=1))
    pkg = {"name": "padurea-ro", "title": "Pădurea RO: schimbări în pădurile României văzute din satelit",
           "homepage": C.SITE_URL, "licenses": [{"name": "CC-BY-4.0", "path": LICENTA_URL, "title": "Creative Commons Attribution 4.0"}],
           "sources": [{"title": s} for s, _ in SURSE],
           "resources": [{"name": "zone", "path": "zone.csv", "format": "csv", "encoding": "utf-8-sig", "mediatype": "text/csv",
                          "schema": {"primaryKey": "id", "fields": [{"name": c, "type": TIPURI.get(c, "string"), "description": CAMPURI[c]} for c in COLS]}},
                         {"name": "zone-geojson", "path": "zone.geojson", "format": "geojson", "mediatype": "application/geo+json"}]}
    n += scrie(DATE / "datapackage.json", json.dumps(pkg, ensure_ascii=False, indent=1))
    n += scrie(DATE / "LICENTA.txt", licenta_txt())
    n += scrie(DATE / "index.html", pagina_date(api, meta, ver))
    return n


def licenta_txt():
    return (f"Datele Pădurea RO ({C.SITE_URL}) sunt publicate sub licența Creative Commons Atribuire 4.0 Internațional (CC BY 4.0):\n"
            f"{LICENTA_URL}\n\nPoți să le copiezi, să le redistribui, să le transformi și să le folosești în orice scop, inclusiv comercial,\n"
            "cu condiția să menționezi sursa: „Pădurea RO” și linkul zonei sau al site-ului.\n\n"
            "Sursele din care sunt făcute datele își păstrează propriile condiții:\n" + "".join(f"  - {s} ({l})\n" for s, l in SURSE) +
            "\nNu fac parte din date: fundalurile hărții (Sentinel-2 cloudless de EOX, CC BY-NC-SA 4.0; Esri World Imagery; OpenStreetMap)\n"
            "și poza detaliată Esri din paginile zonelor, care se încarcă direct de la Esri.\n"
            "\nDatele arată ce se vede din satelit și ce scrie în registrul public de autorizații. Nu sunt o dovadă de ilegalitate.\n")


def pagina_date(api, meta, ver):
    rel = "../"
    st = api["stari"]
    lead_t = (f"Toate cele {fmt(api['zone'])} de zone de pe hartă, de descărcat și de folosit, sub licența {LICENTA}: oricine le poate "
              f"folosi, și în scop comercial, cu mențiunea „Pădurea RO” și linkul. Datele merg până pe {zi(meta.get('data_until'), True)}.")
    o = [CAP.format(title="Date deschise · Pădurea RO", desc=e(lead_t), rel=rel, ver=ver, nav=nav(rel, "date/"), extra=og_meta("date/"))]
    o.append(f'<h1>Date deschise</h1><p class="lead">{e(lead_t)}</p>')
    fis = [("zone.csv", "toate zonele, un rând pe zonă (se deschide în Excel)"),
           ("zone.geojson", "toate zonele, cu conturul (QGIS, Python, harta ta)"),
           ("../data/rosii.json", "doar zonele fără autorizație care să le acopere"),
           ("registru.json", "fiecare zonă publicată vreodată: de când e pe site, ce stări a avut, dacă a fost retrasă"),
           ("../feed.xml", "flux Atom: zonele noi fără autorizație (îl adaugi în orice cititor de RSS)"),
           ("datapackage.json", "descrierea câmpurilor, în format Frictionless Data"),
           ("index.json", "intrarea în API: unde e fiecare fișier și cum se construiesc adresele"),
           ("LICENTA.txt", "licența și sursele")]
    o.append('<section class="sec"><h2>Fișierele</h2><div class="tblwrap"><table class="tbl"><tbody>' +
             "".join(f'<tr><td><a href="{f}">{e(f.split("/")[-1])}</a></td><td>{e(t)}</td></tr>' for f, t in fis) +
             "</tbody></table></div><p class=\"sub\">Pe fiecare județ: <a href=\"../judet/\">pagina județului</a> are zone.csv și zone.geojson doar "
             "cu zonele lui. Se actualizează zilnic, odată cu harta. Fiecare lună e păstrată și ca instantaneu, în "
             f'<a href="{REPO}/releases" rel="noopener">rapoartele lunare</a>.</p></section>')
    o.append('<section class="sec"><h2>API</h2><p>Nu e nevoie de cheie sau cont: fișierele sunt statice și pot fi citite și din browser (CORS deschis).</p>'
             f'<pre class="cite">curl {e(C.SITE_URL)}date/index.json\ncurl {e(C.SITE_URL)}zona/&lt;id&gt;/zona.json\n'
             f'curl {e(C.SITE_URL)}judet/arges/zone.geojson</pre>'
             '<p class="sub">Identificatorul unei zone nu se schimbă. Adresele din <code>index.json</code> → <code>sabloane</code> rămân la fel; '
             'dacă vreodată se schimbă formatul, crește <code>versiune</code> și vechiul format rămâne publicat o vreme.</p></section>')
    stari = "".join(f'<tr><td><i class="key a-{e(k)}" aria-hidden="true"></i>{e(STARE_T.get(k, k))}</td><td class="r num">{fmt(n)}</td>'
                    f'<td class="mono">{e(k)}</td></tr>' for k, n in sorted(st.items(), key=lambda kv: -kv[1]))
    o.append('<section class="sec"><h2>Stările</h2><div class="tblwrap"><table class="tbl"><thead><tr><th>stare</th><th class="r">zone</th>'
             f'<th>cod</th></tr></thead><tbody>{stari}</tbody></table></div><p class="sub">Ce înseamnă fiecare: <a href="../metodologie/#stari">metodologia</a>.</p></section>')
    campuri = "".join(f'<tr><td class="mono">{e(c)}</td><td>{e(CAMPURI[c])}</td></tr>' for c in COLS)
    o.append(f'<section class="sec"><h2>Câmpurile</h2><div class="tblwrap"><table class="tbl"><tbody>{campuri}</tbody></table></div></section>')
    o.append('<section class="sec"><h2>Cum ne citezi</h2>'
             f'<pre class="cite">Pădurea RO, {e(C.SITE_URL)} (date consultate la [data]). Licență {LICENTA}.</pre>'
             '<p class="sub">Pentru o zonă anume, folosește linkul paginii ei: are și textul de citare gata scris.</p></section>')
    o.append('<section class="sec"><h2>Sursele</h2><ul class="src">' + "".join(f"<li>{e(s)} ({e(l)})</li>" for s, l in SURSE) +
             '</ul><p class="sub">Fundalurile hărții și poza detaliată Esri nu fac parte din date și nu sunt sub CC BY.</p></section>')
    o.append(COADA.format(rel=rel, ver=ver, upd=e(zi(meta.get("data_until"), True))))
    return "".join(o)


# ---------------------------------------------------------------- fluxul
def flux(zone, verd, reg, meta):
    """Atom: zonele fără autorizație care să le acopere, cele mai noi pe site întâi."""
    rosii = [a for a in zone.values() if (verd.get(a["id"]) or {}).get("stare") in ROSU]

    def cand(a):  # data la care a devenit roșie (din registru), altfel prima observație
        r = reg.get(a["id"]) or {}
        d = next((d for d, s in reversed(r.get("stari") or []) if s in ROSU), None)
        return d or a.get("first_seen") or ""

    rosii.sort(key=lambda a: (cand(a), a.get("first_seen") or "", a["id"]), reverse=True)
    rosii = rosii[:50]
    upd = (max((cand(a) for a in rosii), default=meta.get("data_until")) or azi()) + "T00:00:00Z"
    o = ['<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="ro">',
         "<title>Pădurea RO: tăieri fără autorizație care să le acopere</title>",
         f'<link href="{C.SITE_URL}"/><link rel="self" href="{C.SITE_URL}feed.xml"/>',
         f"<id>{C.SITE_URL}feed.xml</id><updated>{upd}</updated><author><name>Pădurea RO</name></author>",
         f"<rights>Date {LICENTA}, cu sursa „Pădurea RO”.</rights>"]
    intrari = []
    for a in rosii:
        v = verd.get(a["id"]) or {}
        url = f"{C.SITE_URL}zona/{a['id']}/"
        intrari.append((cand(a), f"<entry><title>{e(titlu_zona(a))}, {e(judet_de(a))}</title><link href=\"{url}\"/><id>{url}</id>"
                        f"<updated>{cand(a)}T00:00:00Z</updated><summary>{e(STARE_T.get(v.get('stare'), ''))}. "
                        f"{e(lead(a, v.get('stare')))}</summary></entry>"))
    rp = DOCS / "raport" / "index.json"
    for r in (json.loads(rp.read_text(encoding="utf-8")).get("rapoarte", []) if rp.exists() else []):
        url = f"{C.SITE_URL}raport/{r['luna']}/"
        intrari.append((r["generat"], f"<entry><title>Raportul lunar: {e(r['luna'])}</title><link href=\"{url}\"/><id>{url}</id>"
                        f"<updated>{r['generat']}T00:00:00Z</updated><summary>{e(fmt(r['rosii']))} locuri fără autorizație care să le acopere "
                        f"({e(ha_t(r['ha_rosii']))}), din {e(fmt(r['zone']))} cu schimbări în pădure.</summary></entry>"))
        upd = max(upd, r["generat"] + "T00:00:00Z")
    o[3] = f"<id>{C.SITE_URL}feed.xml</id><updated>{upd}</updated><author><name>Pădurea RO</name></author>"
    o += [x for _, x in sorted(intrari, key=lambda t: t[0], reverse=True)]
    o.append("</feed>\n")
    return scrie(DOCS / "feed.xml", "\n".join(o))


# ---------------------------------------------------------------- harta: imaginea de previzualizare cu adresa de azi
def sincron_index():
    """docs/index.html e scris de mână; aici doar adresa imaginii de previzualizare urmează SITE_URL (domeniul propriu)."""
    import re
    p = DOCS / "index.html"
    if not p.exists():
        return False
    t = p.read_text(encoding="utf-8")
    n = re.sub(r'(<meta property="og:image" content=")[^"]*(")', r"\g<1>" + C.SITE_URL + r"og.jpg\g<2>", t)
    return scrie(p, n)


# ---------------------------------------------------------------- tot
def de_distribuit(a, st, stiri, verif):
    return st in ROSU or a["id"] in stiri or a["id"] in verif


def main():
    zone, verd, jud, meta, _ = incarca()
    stiri = (json.loads((DOCS / "data" / "stiri.json").read_text(encoding="utf-8")).get("zone", {})
             if (DOCS / "data" / "stiri.json").exists() else {})
    verif = (json.loads((DOCS / "data" / "verificari.json").read_text(encoding="utf-8")).get("zone", {})
             if (DOCS / "data" / "verificari.json").exists() else {})
    ver = ver_css()
    reg = registru(zone, verd)
    scrise = poze_og = 0
    for i, a in zone.items():
        v, j, r = verd.get(i) or {}, jud.get(i) or {}, reg.get(i)
        st = v.get("stare") or "nev"
        d = ZONA / i
        og_img = None
        if de_distribuit(a, st, stiri, verif) and a.get("img_after"):
            u = a.get("uat") or {}
            loc = ", ".join(x for x in [a.get("localitate"), u.get("nume") if u.get("nume") != a.get("localitate") else None,
                                        f"județul {judet_de(a)}" if judet_de(a) else None] if x)
            poze_og += og.zona(a, ha_t(a.get("ha") or 0), loc, st, STARE_T.get(st, st),
                               f"schimbare văzută {cand_t(a)}", f"{C.SITE_URL}zona/{i}/".replace("https://", ""), d / "og.jpg")
            og_img = f"{C.SITE_URL}zona/{i}/og.jpg"
        elif (d / "og.jpg").exists():
            (d / "og.jpg").unlink()
        scrise += scrie(d / "index.html", pagina_zona(a, v, j, r, stiri, verif, ver, og_img))
        scrise += scrie(d / "zona.json", zona_json(a, rand(a, v, j), r))
    retrase = 0
    for i, r in reg.items():
        if r.get("retrasa"):
            retrase += 1
            scrise += scrie(ZONA / i / "index.html", pagina_retrasa(i, r, ver))
            (ZONA / i / "zona.json").unlink(missing_ok=True)
            (ZONA / i / "og.jpg").unlink(missing_ok=True)
    # cardul site-ului: câteva zone roșii mari, înainte/după
    rosii = sorted((a for a in zone.values() if (verd.get(a["id"]) or {}).get("stare") in ROSU and a.get("img_after")),
                   key=lambda a: -(a.get("ha") or 0))
    og.generic("Pădurea RO", "Schimbări în pădurile României, văzute din satelit, cu imagini înainte și după și autorizațiile de tăiere.",
               DOCS / "og.jpg", rosii[:3])
    nd = date_deschise(zone, verd, jud, meta, reg, ver)
    nf = flux(zone, verd, reg, meta)
    from . import metodologie
    nm = metodologie.main(ver)
    sincron_index()
    print(f"Zone: {len(zone)} pagini ({scrise} fișiere rescrise), {poze_og} imagini noi de previzualizare, {retrase} retrase; "
          f"date deschise: {nd} fișiere rescrise; flux: {'nou' if nf else 'neschimbat'}; metodologie: {'nouă' if nm else 'neschimbată'}")


if __name__ == "__main__":
    main()
