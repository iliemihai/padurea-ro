"""Pagina „Cum lucrăm”: docs/metodologie/index.html. Ce face fiecare pas, ce înseamnă culorile, cât de des avem dreptate, limitele.

Textul urmează README-ul; cifrele vin din fișiere (testul pe 2025 din data/evaluare_2025.json, stările de azi din
docs/data/permise.json), ca pagina să nu rămână în urmă. Se rescrie doar când se schimbă ceva.

    python -m pipeline.metodologie
"""
import json
from collections import Counter

from . import config as C
from .judete import CAP, COADA, STARE_T, e, fmt, nav, og_meta, zi

DOCS = C.DOCS
OUT = DOCS / "metodologie" / "index.html"
REPO = "https://github.com/iliemihai/padurea-ro"

CULORI = [("fara", "fără autorizație", "Nicio autorizație de tăiere în jurul zonei, iar pozele arată pădure tăiată."),
          ("neacoperit", "autorizația nu acoperă tăierea",
           "Există o autorizație cu parcela publicată, dar nu cuprinde zona sau nu era valabilă când s-a tăiat. Pagina zonei spune care."),
          ("vegetatie", "pășune, nu pădure", "Înainte era pășune, fâneață sau copaci răzleți, nu pădure închisă."),
          ("probabil", "probabil cu autorizație",
           "Autorizație în zonă, dar amenajamentul nu publică parcela ei, deci nu putem confirma că acoperă exact locul."),
          ("acoperit", "cu autorizație", "Parcela autorizată acoperă zona, în intervalul în care s-a tăiat."),
          ("nu_taiere", "nu e tăiere de pădure", "Drum, șantier, câmp, incendiu, nori sau toamnă: autorizațiile de tăiere nu se aplică."),
          ("nejudecat", "de confirmat pe poze", "Fără autorizație care s-o acopere, dar analistul nu e sigur ce s-a întâmplat. Nu dăm roșu pe o bănuială.")]


def _ev():
    p = C.DATA / "evaluare_2025.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _tabel(cap, rows, num):
    cth, ctd = ' class="r"', ' class="r num"'
    th = "".join(f'<th scope="col"{cth if i in num else ""}>{e(c)}</th>' for i, c in enumerate(cap))
    tr = "".join("<tr>" + "".join(f'<td{ctd if i in num else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<div class="tblwrap"><table class="tbl"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def pct(x):
    return "—" if x is None else f"{fmt(x, 1)}%"


def pagina(ver):
    rel = "../"
    st, meta = Counter(), {}
    p = DOCS / "data" / "permise.json"
    if p.exists():
        st = Counter((v or {}).get("stare") for v in json.loads(p.read_text(encoding="utf-8")).get("zone", {}).values())
    a = DOCS / "data" / "alerts.json"
    if a.exists():
        meta = {k: v for k, v in json.loads(a.read_text(encoding="utf-8")).items() if k != "alerts"}
    lead = ("Pădurea RO caută, în imaginile gratuite ale sateliților Sentinel-2, locurile unde pădurea a dispărut sau s-a schimbat "
            "puternic, apoi le compară cu autorizațiile de tăiere publicate de stat. Aici scrie cum facem asta, cât de des avem "
            "dreptate și unde greșim.")
    o = [CAP.format(title="Cum lucrăm · Pădurea RO", desc=e(lead), rel=rel, ver=ver, nav=nav(rel, "metodologie/"), extra=og_meta("metodologie/"))]
    o.append(f'<h1>Cum lucrăm</h1><p class="lead">{e(lead)}</p>')

    o.append('<section class="sec how"><h2>Pe scurt</h2><ul>'
             "<li>O zonă pe hartă înseamnă: <b>aici s-a schimbat ceva în pădure și merită verificat</b>. Arătăm unde, când și cât, cu imaginile înainte și după.</li>"
             "<li>Roșu înseamnă că pozele arată pădure tăiată și n-am găsit în registrul public o autorizație care să acopere locul. "
             "<b>Nu scriem nicăieri „ilegal”</b>: autorizațiile se pot prelungi, unele parcele nu sunt publicate, iar o tăiere se poate aproba și altfel.</li>"
             "<li>Totul rulează singur, în fiecare dimineață, pe GitHub. Codul e public; oricine îl poate citi și verifica.</li>"
             "<li>Nu vedem zone sub 1 ha, tăierile de sub coronament și nici iarna (15 decembrie – 15 martie).</li></ul></section>")

    pasi = [
        ("Detectorul (cod, fără AI)",
         "Caută doar unde era pădure deasă și verde în ultima vară (ESA WorldCover). Fiecare imagine nouă se compară cu aceeași perioadă "
         "de acum un an, ca frunzele care vin sau cad la alte date să nu arate ca o tăiere. Păstrează locurile unde verdele (NDVI) și "
         "infraroșul de undă scurtă (NBR) au scăzut mult mai mult decât în pădurea din jur, și doar dacă schimbarea se vede în cel puțin patru imagini."),
        ("Analistul AI",
         "Un model de viziune (Claude) se uită la perechea înainte/după și spune ce vede: tăiere, nori, toamnă, câmp, foc sau neclar. "
         "Pentru zonele fără autorizație, un al doilea analist primește și o poză detaliată mai veche (Esri), o vedere largă și o fișă de teren, "
         "și e obligat să verifice pe rând capcanele cunoscute (culori de toamnă, umbre, arsuri, pășuni cu copaci, șantiere) înainte să spună „tăiere”."),
        ("Contextul",
         "Localitatea și comuna (limitele UAT), ariile protejate, vântul din acele zile (o doborâtură nu e o tăiere), focurile văzute de sateliții NASA (FIRMS) "
         "și pierderile de pădure Hansen din jur."),
        ("Verificarea pe poze și criticul",
         "Zona trebuie să fi arătat ca pădurea din jur înainte și să se schimbe vizibil după. Criticul pune dovezile cap la cap și dă nivelul: "
         "încredere ridicată, medie sau scăzută. Zonele văzute schimbate într-o singură imagine nu apar pe site până nu le vedem iar."),
        ("Autorizațiile",
         "Pentru fiecare zonă căutăm în Inspectorul Pădurii (SUMAL 2.0) autorizațiile de tăiere (APV) de la mai puțin de 500 m și verificăm două lucruri: "
         "parcela autorizată acoperă zona, iar perioada autorizației cuprinde intervalul în care s-a tăiat."),
    ]
    o.append('<section class="sec"><h2>Pașii, în fiecare zi</h2><ol class="steps">' +
             "".join(f"<li><b>{e(t)}.</b> {e(d)}</li>" for t, d in pasi) + "</ol></section>")

    o.append('<section class="sec"><h2>De ce contează intervalul</h2>'
             "<p>Satelitul nu vede tăierea când se întâmplă, ci când revine frunza. O tăiere din ianuarie, cu autorizație valabilă până în decembrie, "
             "apare ca schimbare abia în aprilie. Dacă am compara autorizația cu data la care am văzut-o noi, am declara expirată o tăiere legală "
             "(la prima încercare ne-a ieșit așa: 277 de zone în loc de 27). De aceea folosim intervalul dintre ultima imagine cu pădurea întreagă "
             "și prima imagine cu schimbarea, iar dacă parcela autorizată acoperă locul și autorizația s-a terminat cu cel mult un an înainte, "
             "zona e „probabil cu autorizație”, nu roșie.</p></section>")

    rows = [(f'<i class="key a-{k}" aria-hidden="true"></i>{e(t)}', e(d), fmt(st.get(k, 0))) for k, t, d in CULORI]
    o.append('<section class="sec" id="stari"><h2>Ce înseamnă culorile</h2>'
             '<p class="sub">O singură scară: cu cât mai cald, cu atât mai mult merită privit. Cifrele sunt zonele de azi, din tot istoricul.</p>'
             + _tabel(["stare", "ce înseamnă", "zone"], rows, {2}) + "</section>")

    ev = _ev()
    if ev:
        pr = ev.get("precizie", {})
        r1 = [(e(k), fmt(pr[k]["zone"]), pct(pr[k].get("precizie_%"))) for k in ("ridicată", "medie", "scăzută") if k in pr]
        rp = ev.get("recall_pete", {})
        r2 = [(e(k), fmt(v["pete"]), pct(v.get("pana_la_scăzută_%")), pct(v.get("pana_la_ridicată_%"))) for k, v in rp.items()]
        rs = ev.get("recall_suprafata", {})
        o.append('<section class="sec"><h2>Cât de des avem dreptate</h2>'
                 f"<p>Testul pe {e(ev.get('an'))}: am rulat detectorul pe tot anul, ca în rulările zilnice, și am comparat zonele cu harta de pierderi "
                 "de pădure Hansen (Universitatea Maryland, Landsat, 30 m), o referință independentă. O zonă „se potrivește” dacă măcar 20% din ea "
                 "e pierdere Hansen.</p>" + _tabel(["nivel", "zone", "se potrivesc cu Hansen"], r1, {1, 2}) +
                 "<p>Și invers: câte pete de pierdere Hansen atinge o zonă de pe site.</p>" +
                 _tabel(["mărimea", "pete", "găsite", "doar „ridicată”"], r2, {1, 2, 3}) +
                 (f"<p>Ca suprafață: {pct(rs.get('pana_la_scăzută_%'))} din cele {fmt(rs.get('ha_hansen') or 0)} ha pierdute în {e(ev.get('an'))}.</p>" if rs else "") +
                 "<p>Hansen ratează tăierile parțiale (rărituri, tăieri progresive) și trece uneori o tăiere de toamnă la anul următor, așa că "
                 "precizia adevărată e probabil mai mare. Când ne-am uitat pe poze la zonele care nu se potrivesc, multe erau tot schimbări reale.</p>"
                 "<p><b>Zonele roșii.</b> Precizia lor („roșu = chiar pădure tăiată”) o măsurăm pe un eșantion ales la întâmplare, verificat de om "
                 "pe poze, fără să vadă ce spune harta. Cifra apare aici când verificarea e gata.</p></section>")

    o.append('<section class="sec how"><h2>Limitele</h2><ul>'
             "<li>Norii ascund pădurea uneori zile întregi; satelitul trece peste fiecare loc cam la 3 zile.</li>"
             "<li>Iarna nu căutăm: o tăiere din decembrie–martie apare primăvara, cu intervalul în care s-a putut întâmpla. "
             "Ce găsim toamna rămâne „scăzută” până o vedem și primăvara.</li>"
             "<li>Nu vedem zone mai mici de 1 ha și nici tăierile de sub coronament (rărituri ușoare).</li>"
             "<li>Registrul public nu e complet: lipsesc parcelele multor păduri private, iar unele autorizații nu se pot lega de loc.</li>"
             "<li>Analistul AI greșește. Îl măsurăm și îl corectăm; când vezi o greșeală, spune-ne.</li></ul></section>")

    o.append('<section class="sec"><h2>Sursele</h2><ul class="src">'
             "<li>Copernicus Sentinel-2 L2A (ESA), prin Microsoft Planetary Computer</li><li>ESA WorldCover 2021</li>"
             "<li>Hansen et al., Global Forest Change 2000–2025, Universitatea Maryland</li><li>Inspectorul Pădurii (SUMAL 2.0, Ministerul Mediului)</li>"
             "<li>Agenția Europeană de Mediu: Natura 2000 și ariile protejate naționale</li><li>NASA FIRMS, GeoNames, Open-Meteo, limitele UAT de la geo-spatial.org</li>"
             "</ul></section>")
    o.append('<section class="sec"><h2>Cum ne corectezi, cum ne citezi</h2>'
             f'<p>Dacă o zonă e greșită, <a href="{REPO}/issues" rel="noopener">spune-ne pe GitHub</a> (fiecare pagină de zonă are un link gata făcut). '
             f'Codul e public, <a href="{REPO}" rel="noopener">aici</a>.</p>'
             '<p>Datele sunt sub licența CC BY 4.0: le poți folosi oricum, cu mențiunea „Pădurea RO” și linkul. '
             'Fiecare zonă are o pagină permanentă, cu textul de citare gata scris; toate zonele sunt la <a href="../date/">date deschise</a>.</p></section>')
    o.append(COADA.format(rel=rel, ver=ver, upd=e(zi(meta.get("data_until"), True)) if meta.get("data_until") else ""))
    return "".join(o)


def main(ver=None):
    if ver is None:
        from .deschis import ver_css
        ver = ver_css()
    text = pagina(ver)
    if OUT.exists() and OUT.read_text(encoding="utf-8") == text:
        return False
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    return True


if __name__ == "__main__":
    print("scrisă" if main() else "neschimbată")
