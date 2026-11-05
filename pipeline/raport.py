"""Raportul lunar: docs/raport/<AAAA-LL>/ (index.html, zone.csv, zone.geojson), docs/raport/index.html și index.json.

Un instantaneu: zonele văzute prima dată în luna aceea, cu starea lor din ziua raportului. Odată făcut, raportul nu se mai
rescrie (decât cu --refa): paginile zonelor arată starea de azi și istoricul ei, raportul rămâne ce am spus atunci,
ca să poată fi citat. Workflow-ul „Raportul lunar” îl face pe 5 ale lunii și pune datele lunii într-un Release pe GitHub.

    python -m pipeline.raport                    # luna trecută
    python -m pipeline.raport --luna 2026-10     # o lună anume
    python -m pipeline.raport --luna 2026-10 --refa
"""
import argparse
import csv
import datetime as dt
import io
import json
from collections import Counter, defaultdict

from . import config as C
from .judete import (CAP, COADA, COLS, GRUP, card_zona, e, fmt, ha_t, incarca, judet_de, kpi, luna_t, nav, nr, og_meta, rand, slug,
                     tabel, zi)

DOCS = C.DOCS
OUT = DOCS / "raport"
REPO = "https://github.com/iliemihai/padurea-ro"


def luna_trecuta(azi=None):
    azi = azi or dt.date.today()
    return (azi.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")


def luna_dinainte(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"


def statistici(zs, verd):
    grp = {a["id"]: GRUP.get((verd.get(a["id"]) or {}).get("stare", "nev"), "confirmat") for a in zs}
    cnt, ha = Counter(grp.values()), defaultdict(float)
    for a in zs:
        ha[grp[a["id"]]] += a.get("ha") or 0
    return grp, cnt, ha


def pagina(luna, zs, prev, verd, jud, ver, generat):
    rel = "../../"
    grp, cnt, ha = statistici(zs, verd)
    tot = sum(ha.values())
    L = luna_t(luna, True)
    lead = (f"În {L}, satelitul a văzut schimbări în pădure sau la marginea ei în {nr(len(zs), 'loc', 'locuri')} ({ha_t(tot)}). "
            + (f"În {nr(cnt['rosu'], 'loc', 'locuri')} ({ha_t(ha['rosu'])}) pozele arată pădure tăiată și n-am găsit o autorizație "
               "de tăiere care să acopere locul." if cnt["rosu"] else "N-am găsit nicio tăiere de pădure fără o autorizație care s-o acopere."))
    if prev is not None:
        _, cp, hp = statistici(prev, verd)
        lead += f" Luna dinainte: {nr(cp['rosu'], 'loc', 'locuri')} fără autorizație ({ha_t(hp['rosu'])})."
    titlu = f"{L[0].upper()}{L[1:]} în pădurile României"
    o = [CAP.format(title=e(f"{titlu} · Pădurea RO"), desc=e(lead), rel=rel, ver=ver, nav=nav(rel), extra=og_meta(f"raport/{luna}/"))]
    o.append(f'<p class="crumbs"><a href="../">Rapoarte lunare</a></p><h1>{e(titlu)}</h1><p class="lead">{e(lead)}</p>'
             f'<p class="caveat">Starea zonelor e cea din {e(zi(generat, True))}, ziua raportului. Pe pagina fiecărei zone vezi starea de azi '
             'și cum s-a schimbat. Roșu nu înseamnă automat ilegal: e un loc de întrebat ocolul silvic și Garda Forestieră.</p>')
    mo = int(luna[5:7])
    if mo in (12, 1, 2, 3):
        o.append('<p class="caveat">Între 15 decembrie și 15 martie nu căutăm tăieri noi; ce se taie iarna apare primăvara.</p>')
    o.append('<section class="kpis" aria-label="Pe scurt">' +
             kpi("rosu", fmt(cnt["rosu"]), "Fără autorizație care s-o acopere", ha_t(ha["rosu"])) +
             kpi("verde", fmt(cnt["verde"]), "Cu autorizație", ha_t(ha["verde"])) +
             kpi("", fmt(cnt["nu"] + cnt["pasune"]), "Nu e tăiere de pădure", "drum, câmp, foc, sezon, pășune") +
             kpi("", fmt(cnt["confirmat"]), "De confirmat", "analistul nu e sigur") + "</section>")
    # județele
    pj = defaultdict(lambda: [0, 0.0, 0])
    for a in zs:
        j = judet_de(a)
        pj[j][2] += 1
        if grp[a["id"]] == "rosu":
            pj[j][0] += 1
            pj[j][1] += a.get("ha") or 0
    top = sorted(((j, n_r, h_r, n) for j, (n_r, h_r, n) in pj.items() if j and n_r), key=lambda t: (-t[2], -t[1]))[:10]
    if top:
        rows = [(f'<a href="../../judet/{e(slug(j))}/">{e(j)}</a>', fmt(n_r), fmt(h_r, 1), fmt(n)) for j, n_r, h_r, n in top]
        o.append('<section class="sec"><h2>Județele cu cele mai multe hectare fără autorizație</h2>' +
                 tabel(["județul", "locuri fără autorizație", "ha fără autorizație", "toate locurile"], rows, {1, 2, 3}) + "</section>")
    # zonele roșii
    rosii = sorted((a for a in zs if grp[a["id"]] == "rosu"), key=lambda a: -(a.get("ha") or 0))
    if rosii:
        o.append(f'<section class="sec"><h2>Locurile fără autorizație</h2><p class="sub">Toate cele {fmt(len(rosii))}, de la cea mai mare. '
                 'Fiecare are pagina ei, cu coordonatele, pozele și textul de citare.</p><div class="zgrid">' +
                 "".join(card_zona(a, verd.get(a["id"]) or {}, jud.get(a["id"]) or {}) for a in rosii) + "</div></section>")
    url = f"{C.SITE_URL}raport/{luna}/"
    o.append('<section class="sec"><h2>Datele lunii și citarea</h2>'
             '<p>Instantaneul de mai sus, de descărcat: <a href="zone.csv">zone.csv</a> · <a href="zone.geojson">zone.geojson</a> '
             f'(toate zonele din {e(L)}, cu starea din ziua raportului). Licență CC BY 4.0.</p>'
             f'<pre class="cite">Pădurea RO, raportul lunar: {e(L)}. {e(url)} (publicat pe {e(zi(generat, True))}).</pre></section>')
    o.append(COADA.format(rel=rel, ver=ver, upd=e(zi(generat, True))).replace("Actualizat ", "Raport făcut pe "))
    return "".join(o), {"luna": luna, "url": url, "zone": len(zs), "ha": round(tot, 1), "rosii": cnt["rosu"],
                        "ha_rosii": round(ha["rosu"], 1), "generat": generat}


def date_luna(d, zs, verd, jud):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLS)
    feats = []
    for a in sorted(zs, key=lambda a: (a.get("first_seen") or "", a["id"]), reverse=True):
        row = rand(a, verd.get(a["id"]) or {}, jud.get(a["id"]) or {})
        w.writerow([row[c] for c in COLS])
        feats.append({"type": "Feature", "id": a["id"], "geometry": a.get("geometry"), "properties": row})
    (d / "zone.csv").write_text("﻿" + buf.getvalue(), encoding="utf-8")
    (d / "zone.geojson").write_text(json.dumps({"type": "FeatureCollection", "licenta": "CC BY 4.0", "sursa": "Pădurea RO",
                                                "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def note_release(r):
    """Textul Release-ului de pe GitHub (Markdown), scris în out/, nu pe site."""
    L = luna_t(r["luna"], True)
    return (f"Raportul lunar Pădurea RO: {L}.\n\n"
            f"- {fmt(r['zone'])} locuri cu schimbări în pădure ({fmt(r['ha'], 1)} ha)\n"
            f"- {fmt(r['rosii'])} fără o autorizație de tăiere care să le acopere ({fmt(r['ha_rosii'], 1)} ha)\n\n"
            f"Raportul: {r['url']}\n\nFișierele atașate sunt instantaneul zonelor din {L}, cu starea din ziua raportului "
            f"({r['generat']}). Licență CC BY 4.0, cu sursa „Pădurea RO”.\n")


def index(rapoarte, ver):
    rel = "../"
    lead = ("Un raport pe lună: ce s-a văzut în pădurile României, unde n-am găsit autorizații și datele lunii, de descărcat. "
            "Odată publicat, un raport nu se mai schimbă, ca să poată fi citat.")
    o = [CAP.format(title="Rapoarte lunare · Pădurea RO", desc=e(lead), rel=rel, ver=ver, nav=nav(rel), extra=og_meta("raport/"))]
    o.append(f'<h1>Rapoarte lunare</h1><p class="lead">{e(lead)}</p>')
    rows = [(f'<a href="{e(r["luna"])}/">{e(luna_t(r["luna"], True))}</a>', fmt(r["rosii"]), fmt(r["ha_rosii"], 1), fmt(r["zone"]), e(zi(r["generat"])))
            for r in sorted(rapoarte, key=lambda r: r["luna"], reverse=True)]
    o.append('<section class="sec">' + tabel(["luna", "fără autorizație", "ha fără autorizație", "toate locurile", "publicat"], rows, {1, 2, 3}) +
             f'<p class="sub">Fiecare lună e și un <a href="{REPO}/releases" rel="noopener">Release pe GitHub</a>, cu datele atașate. '
             'Ca să primești anunțul, apasă „Watch → Custom → Releases” pe pagina proiectului, sau adaugă '
             '<a href="../feed.xml">fluxul</a> într-un cititor RSS.</p></section>')
    o.append(COADA.format(rel=rel, ver=ver, upd=e(zi(max((r["generat"] for r in rapoarte), default=""), True)) if rapoarte else ""))
    return "".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--luna", default="", help="AAAA-LL; gol = luna trecută")
    ap.add_argument("--refa", action="store_true", help="rescrie raportul, dacă există deja")
    args = ap.parse_args()
    luna = args.luna or luna_trecuta()
    d = OUT / luna
    idx_p = OUT / "index.json"
    rapoarte = json.loads(idx_p.read_text(encoding="utf-8")).get("rapoarte", []) if idx_p.exists() else []
    from .deschis import ver_css
    ver = ver_css()
    if (d / "index.html").exists() and not args.refa:
        print(f"Raportul pentru {luna} există deja (cu --refa îl rescrii).")
    else:
        zone, verd, jud, _, _ = incarca()
        zs = [a for a in zone.values() if (a.get("first_seen") or "")[:7] == luna]
        prev_m = luna_dinainte(luna)
        prev = [a for a in zone.values() if (a.get("first_seen") or "")[:7] == prev_m] or None
        generat = dt.datetime.now(dt.timezone.utc).date().isoformat()
        html, rez = pagina(luna, zs, prev, verd, jud, ver, generat)
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(html, encoding="utf-8")
        date_luna(d, zs, verd, jud)
        rapoarte = [r for r in rapoarte if r["luna"] != luna] + [rez]
        print(f"Raport {luna}: {rez['zone']} zone, {rez['rosii']} fără autorizație ({rez['ha_rosii']} ha) -> {d}")
    rez = next((r for r in rapoarte if r["luna"] == luna), None)
    if rez:   # textul Release-ului, și când raportul exista deja
        C.OUT.mkdir(parents=True, exist_ok=True)
        (C.OUT / f"raport_{luna}.md").write_text(note_release(rez), encoding="utf-8")
    idx_p.parent.mkdir(parents=True, exist_ok=True)
    idx_p.write_text(json.dumps({"rapoarte": sorted(rapoarte, key=lambda r: r["luna"])}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "index.html").write_text(index(rapoarte, ver), encoding="utf-8")


if __name__ == "__main__":
    main()
