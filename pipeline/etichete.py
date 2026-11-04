"""Etichetarea de mână: pagina pe care omul spune, pentru 100 de zone, ce vede. Din ea iese precizia reală.

Pagina (docs/eticheteaza.html, nelistată) ia un eșantion fix de zone, le amestecă și ascunde ce zice harta
despre ele (etichetare oarbă). Pentru fiecare arată: poza Esri de dinainte (live), înainte/după Sentinel, fișa de
context și locul pe hartă, apoi 8 butoane. Etichetele se țin în browser și se descarcă ca JSON.

    python -m pipeline.etichete                       scrie docs/eticheteaza.html cu eșantionul (sămânță fixă)
    python -m pipeline.etichete --raport etichete.json   precizia pe stare, pe categoria AI, pe felul de loc
    python -m pipeline.etichete --din-cheie evaluare/<data>/cheie.json   pagina pe un eșantion de evaluare deja ales
                                                     (aceleași zone pe care le-a etichetat și Claude, ca să comparăm)

Eșantionul: 45 roșii (fără/neacoperit), 15 nejudecate, 15 probabile, 25 verzi (acoperit, martor).
"""
import argparse
import datetime as dt
import json
import math
import random
from collections import Counter, defaultdict

from . import config as C
from .permise import zone_site, OUT as PERMISE

OUT_HTML = C.DOCS / "eticheteaza.html"
ETICHETE = [("taiere_rasa", "Tăiere rasă în pădure", "era pădure închisă, acum e sol gol / bușteni"),
            ("rarire", "Rărire", "pădurea e tot acolo, dar mai rară"),
            ("pasune", "Pășune curățată", "copaci răzleți pe pășune, scoși sau pășunea arată / curățată"),
            ("santier", "Drum / șantier", "fâșie lungă sau lucrare: drum, cale ferată, conductă, carieră, construcție"),
            ("camp", "Câmp", "teren agricol: arat, cosit, recoltat, livadă"),
            ("foc", "Foc", "urmă de ardere"),
            ("nimic", "Nimic real", "sezon, nori, umbre, zăpadă; pădurea e la fel"),
            ("neclar", "Nu-mi dau seama", "")]
COMPOZITIE = (("fara", 45), ("neacoperit", 0), ("nejudecat", 15), ("probabil", 15), ("acoperit", 25))


def esantion(zone, verd, seed=2026):
    rnd = random.Random(seed)
    ids = []
    rosii = [k for k, v in verd.items() if v.get("stare") in ("fara", "neacoperit") and k in zone and zone[k].get("img_after")]
    ids += rnd.sample(rosii, min(45, len(rosii)))
    for st, n in COMPOZITIE[2:]:
        c = [k for k, v in verd.items() if v.get("stare") == st and k in zone and zone[k].get("img_after")]
        ids += rnd.sample(c, min(n, len(c)))
    rnd.shuffle(ids)
    return ids


def scrie_html(ids, zone, cheie_ls="etichete"):
    """Pagina, cu eșantionul în ea; datele (poze, context) le ia din docs/data la deschidere."""
    date = {k: {kk: zone[k].get(kk) for kk in ("id", "lat", "lon", "bbox", "chip_bbox", "ha", "first_seen", "county", "localitate", "img_before", "img_after", "n_dates", "arii")} for k in ids}
    html = """<!doctype html>
<html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Etichetare — Pădurea RO</title><meta name="robots" content="noindex">
<link rel="stylesheet" href="style.css">
<style>
body{background:var(--color-paper);color:var(--color-ink);font-family:var(--font-body,system-ui);margin:0}
.et{max-width:1100px;margin:0 auto;padding:16px}
.et h1{font-size:1.2rem;margin:0 0 4px}.et .prog{font-family:var(--font-outlier,monospace);color:var(--color-ink-2)}
.poze{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:12px 0}
.poze figure{margin:0;position:relative}.poze img{width:100%;aspect-ratio:1/1;object-fit:cover;background:#222;display:block;border-radius:6px}
.poze figcaption{font-size:.8rem;color:var(--color-ink-2);margin-top:4px}
.poze svg{position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none}
.ctx{font-size:.85rem;color:var(--color-ink-2);line-height:1.45;margin:8px 0;columns:2;column-gap:24px}
.ctx b{color:var(--color-ink)}
.bt{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:12px 0}
.bt button{padding:12px 8px;border:1px solid var(--color-muted-2);background:var(--color-paper-2);color:var(--color-ink);border-radius:8px;cursor:pointer;text-align:left}
.bt button small{display:block;color:var(--color-ink-2);font-size:.75rem;margin-top:2px}
.bt button[aria-pressed=true]{outline:3px solid var(--color-accent,#f97c3d)}
.bt button:hover{border-color:var(--color-ink)}
.nav{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:12px 0}
.nav button,.nav a{padding:8px 12px;border:1px solid var(--color-muted-2);background:transparent;color:var(--color-ink);border-radius:6px;cursor:pointer;text-decoration:none}
textarea{width:100%;min-height:60px;background:var(--color-paper-2);color:var(--color-ink);border:1px solid var(--color-muted-2);border-radius:6px;padding:8px;font:inherit}
@media(max-width:700px){.poze{grid-template-columns:1fr 1fr}.bt{grid-template-columns:1fr 1fr}.ctx{columns:1}}
</style></head><body><div class="et">
<h1>Etichetare oarbă: ce vezi în zona marcată?</h1>
<p class="hint">Nu ți se spune ce zice harta despre zonă. Uită-te la poza detaliată (ce era înainte), la înainte/după și la context, și apasă un buton. Etichetele rămân în browserul ăsta; la final apasă „Descarcă etichetele”.</p>
<p class="prog" id="prog"></p>
<div id="card"></div>
<div class="nav"><button id="prev">← Înapoi</button><button id="next">Următoarea →</button><button id="skip">Sar peste</button><a id="lnkmap" target="_blank">Pe hartă</a><a id="esri" target="_blank">Esri mare</a><button id="dl">Descarcă etichetele</button><span id="cnt"></span></div>
<textarea id="nota" placeholder="Notă (opțional): ce ai văzut, dubii"></textarea>
</div>
<script>
var IDS = __IDS__;
var Z = __ZONE__;
var ET = __ET__;
var ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bboxSR=4326&imageSR=3857&size=700,700&format=jpg&f=image&bbox=";
var i = 0, lab = {}, peis = {}, dataDone = false;
var KEY = "__KEY__";
try { lab = JSON.parse(localStorage.getItem(KEY) || "{}"); i = +localStorage.getItem(KEY + "_i") || 0; } catch (e) {}
fetch("data/peisaj.json").then(function (r) { return r.json(); }).then(function (j) { peis = j.zone || {}; render(); }).catch(function () { render(); });
function outline(a, bb) {
  if (!bb) return "";
  var x0 = bb[0], y0 = bb[1], x1 = bb[2], y1 = bb[3], b = a.bbox;
  var l = (b[0] - x0) / (x1 - x0) * 100, t = (y1 - b[3]) / (y1 - y0) * 100, w = (b[2] - b[0]) / (x1 - x0) * 100, h = (b[3] - b[1]) / (y1 - y0) * 100;
  return '<svg viewBox="0 0 100 100" preserveAspectRatio="none"><rect x="' + l + '" y="' + t + '" width="' + w + '" height="' + h + '" fill="none" stroke="#f97c3d" stroke-width="0.8"/></svg>';
}
function ctx(a) {
  var p = peis[a.id] || {}, o = p.osm || {}, r = [];
  r.push("<b>" + a.ha + " ha</b>, " + (a.localitate || "") + ", " + (a.county || "") + ", văzută schimbată în " + a.n_dates + " imagini, prima dată " + a.first_seen);
  if (p.relief) r.push("relief: <b>" + p.relief + "</b>, " + p.alt_m + " m, pantă " + p.panta_grade + "°");
  if (p.wc_zona) r.push("în zonă (WorldCover 2021): " + Object.keys(p.wc_zona).map(function (k) { return k + " " + p.wc_zona[k] + "%"; }).join(", "));
  if (p.wc_jur) r.push("pe 500 m în jur: " + Object.keys(p.wc_jur).map(function (k) { return k + " " + p.wc_jur[k] + "%"; }).join(", "));
  if (p.coronament2000 != null) r.push("coronament în 2000 (Hansen): <b>" + p.coronament2000 + "%</b> în zonă, " + p.coronament2000_jur + "% în jur");
  var nume = { drum_mare: "drum mare", drum: "drum/potecă", drum_in_lucru: "drum în lucru (OSM)", cale_ferata: "cale ferată", cale_ferata_in_lucru: "cale ferată în lucru", apa: "apă", intravilan: "zonă locuită", cariera: "carieră", linie_electrica: "linie electrică", conducta: "conductă", agricol_osm: "teren agricol (OSM)" };
  Object.keys(nume).forEach(function (k) { if (o[k]) r.push(nume[k] + ": " + o[k].m + " m (" + o[k].ce + ")"); });
  if (p.alungire) r.push("formă: " + p.lungime_m + " × " + p.latime_m + " m (alungire " + p.alungire + ")");
  if (a.arii && a.arii.length) r.push("în arie protejată");
  return "<p>" + r.join("</p><p>") + "</p>";
}
function render() {
  if (i < 0) i = 0; if (i >= IDS.length) i = IDS.length - 1;
  var id = IDS[i], a = Z[id], bb = a.chip_bbox;
  document.getElementById("prog").textContent = (i + 1) + " / " + IDS.length + "   " + id;
  var h = '<div class="poze">';
  h += '<figure><img src="' + ESRI + bb.join(",") + '" alt="">' + outline(a, bb) + '<figcaption>Detaliat, înainte (Esri, 0,5 m, cu 1–4 ani în urmă)</figcaption></figure>';
  h += '<figure>' + (a.img_before ? '<img src="img/' + a.img_before.file + '" alt="">' + outline(a, bb) : '<div class="hint">fără poză de dinainte</div>') + '<figcaption>Înainte, Sentinel 10 m, ' + (a.img_before ? a.img_before.date : "") + '</figcaption></figure>';
  h += '<figure><img src="img/' + a.img_after.file + '" alt="">' + outline(a, bb) + '<figcaption>După, Sentinel 10 m, ' + a.img_after.date + '</figcaption></figure>';
  h += '</div><div class="ctx">' + ctx(a) + '</div><div class="bt">';
  ET.forEach(function (e) { h += '<button data-k="' + e[0] + '" aria-pressed="' + String((lab[id] || {}).et === e[0]) + '">' + e[1] + '<small>' + e[2] + '</small></button>'; });
  h += '</div>';
  document.getElementById("card").innerHTML = h;
  document.getElementById("nota").value = (lab[id] || {}).nota || "";
  document.getElementById("lnkmap").href = "./#a=" + id;
  var cx = (bb[0] + bb[2]) / 2, cy = (bb[1] + bb[3]) / 2;
  document.getElementById("esri").href = "https://www.arcgis.com/home/webmap/viewer.html?center=" + cx + "," + cy + "&level=17&basemapUrl=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer";
  document.getElementById("cnt").textContent = Object.keys(lab).length + " etichetate";
  document.querySelectorAll(".bt button").forEach(function (b) { b.addEventListener("click", function () { lab[id] = { et: b.dataset.k, nota: document.getElementById("nota").value, cand: new Date().toISOString().slice(0, 10) }; save(); i++; render(); window.scrollTo(0, 0); }); });
  try { localStorage.setItem(KEY + "_i", i); } catch (e) {}
}
function save() { try { localStorage.setItem(KEY, JSON.stringify(lab)); } catch (e) {} }
document.getElementById("prev").onclick = function () { i--; render(); };
document.getElementById("next").onclick = function () { i++; render(); };
document.getElementById("skip").onclick = function () { i++; render(); };
document.getElementById("nota").addEventListener("change", function () { var id = IDS[i]; if (lab[id]) { lab[id].nota = this.value; save(); } });
document.getElementById("dl").onclick = function () {
  var blob = new Blob([JSON.stringify({ cine: "om", esantion: KEY, cand: new Date().toISOString(), etichete: lab }, null, 1)], { type: "application/json" });
  var u = URL.createObjectURL(blob), x = document.createElement("a"); x.href = u; x.download = "etichete.json"; x.click();
};
</script></body></html>"""
    html = html.replace("__KEY__", cheie_ls).replace("__IDS__", json.dumps(ids)).replace("__ZONE__", json.dumps(date, ensure_ascii=False)).replace("__ET__", json.dumps(ETICHETE, ensure_ascii=False))
    OUT_HTML.write_text(html, encoding="utf-8")


def wilson(k, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def raport(path):
    et = json.loads(open(path, encoding="utf-8").read())
    et = et.get("etichete", et)
    zone = zone_site()
    verd = json.loads(PERMISE.read_text(encoding="utf-8")).get("zone", {})
    jud = {}
    jp = C.DOCS / "data" / "judecata.json"
    if jp.exists():
        jud = json.loads(jp.read_text(encoding="utf-8")).get("zone", {})
    peis = {}
    pp = C.DOCS / "data" / "peisaj.json"
    if pp.exists():
        peis = json.loads(pp.read_text(encoding="utf-8")).get("zone", {})

    def pct(k, n):
        lo, hi = wilson(k, n)
        return f"{k}/{n} = {100 * k / n:.0f}% (95%: {100 * lo:.0f}–{100 * hi:.0f}%)" if n else "-"

    print(f"{len(et)} zone etichetate de om\n")
    # 1. pe starea de pe hartă: câte roșii sunt tăieri de pădure?
    print("1. Starea de pe hartă -> ce a văzut omul")
    grup = defaultdict(Counter)
    for zid, e in et.items():
        grup[verd.get(zid, {}).get("stare", "?")][e["et"]] += 1
    for st, c in sorted(grup.items()):
        n = sum(c.values()); k = c["taiere_rasa"] + c["rarire"]
        print(f"  {st:12s} tăiere de pădure (rasă+rărire): {pct(k, n)}; " + ", ".join(f"{a} {b}" for a, b in c.most_common()))
    # 2. judecata AI cu context vs om
    if jud:
        print("\n2. Judecata AI cu context -> om (acord pe categorie)")
        ok = n = 0; conf = Counter()
        for zid, e in et.items():
            j = jud.get(zid)
            if not j:
                continue
            n += 1
            ai = j["categorie"]; om = e["et"]
            egal = (ai == om) or (ai == "sezon_nori" and om == "nimic")
            ok += egal
            conf[(ai, om)] += 1
        print(f"  acord: {pct(ok, n)}")
        print("  perechi (AI -> om): " + ", ".join(f"{a}->{b} {c}" for (a, b), c in conf.most_common(14)))
        # precizia AI-ului pe „tăiere”
        k = sum(1 for zid, e in et.items() if zid in jud and jud[zid]["categorie"] in ("taiere_rasa", "rarire") and e["et"] in ("taiere_rasa", "rarire"))
        n2 = sum(1 for zid in et if zid in jud and jud[zid]["categorie"] in ("taiere_rasa", "rarire"))
        print(f"  când AI-ul zice tăiere, omul confirmă: {pct(k, n2)}")
        k = sum(1 for zid, e in et.items() if zid in jud and e["et"] in ("taiere_rasa", "rarire") and jud[zid]["categorie"] in ("taiere_rasa", "rarire"))
        n3 = sum(1 for zid, e in et.items() if zid in jud and e["et"] in ("taiere_rasa", "rarire"))
        print(f"  din tăierile văzute de om, AI-ul le prinde: {pct(k, n3)}")
    # 3. felul de loc (peisaj) vs om
    if peis:
        print("\n3. Felul de loc (peisaj) -> om")
        grup = defaultdict(Counter)
        for zid, e in et.items():
            grup[peis.get(zid, {}).get("fel", "?")][e["et"]] += 1
        for f, c in sorted(grup.items()):
            n = sum(c.values()); k = c["taiere_rasa"] + c["rarire"]
            print(f"  {f:18s} tăiere de pădure: {pct(k, n)}; " + ", ".join(f"{a} {b}" for a, b in c.most_common()))
    # 4. ce ar da regula nouă: roșu doar dacă AI(context) zice tăiere și peisaj nu e câmp/coridor
    if jud:
        print("\n4. Regula propusă: roșu = fără autorizație ȘI AI cu context zice tăiere ȘI peisajul nu e câmp/coridor/carieră")
        k = n = 0
        for zid, e in et.items():
            st = verd.get(zid, {}).get("stare")
            j = jud.get(zid, {})
            f = peis.get(zid, {}).get("fel")
            if st in ("fara", "neacoperit", "nejudecat") and j.get("categorie") in ("taiere_rasa", "rarire") and f not in ("camp", "coridor", "cariera"):
                n += 1; k += e["et"] in ("taiere_rasa", "rarire")
        print(f"  precizia roșului cu regula nouă: {pct(k, n)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raport")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--din-cheie", help="ia zonele, în ordine, dintr-un cheie.json de evaluare (evaluare/*/cheie.json)")
    a = ap.parse_args(argv)
    if a.raport:
        return raport(a.raport)
    zone = zone_site()
    verd = json.loads(PERMISE.read_text(encoding="utf-8")).get("zone", {})
    if a.din_cheie:
        import pathlib
        ch = json.loads(pathlib.Path(a.din_cheie).read_text(encoding="utf-8"))
        ids = [ch[k]["id"] for k in sorted(ch) if ch[k]["id"] in zone]
        scrie_html(ids, zone, "etichete_" + pathlib.Path(a.din_cheie).parent.name)
    else:
        ids = esantion(zone, verd, a.seed)
        scrie_html(ids, zone)
    c = Counter(verd.get(k, {}).get("stare") for k in ids)
    print(f"{len(ids)} zone în eșantion -> {OUT_HTML}; compoziție (ascunsă în pagină): {dict(c)}")


if __name__ == "__main__":
    main()
