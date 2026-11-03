/* Pădurea RO: harta schimbărilor din pădure. Datele vin din data/alerts.json, refăcut zilnic de GitHub Actions. */
(function () {
  "use strict";

  var REPO = "https://github.com/iliemihai/padurea-ro";
  /* zonele „de confirmat” (văzute într-o singură imagine) nu ajung pe site: testul pe 2025 a arătat că sunt aproape toate alarme false */
  var CONF = [["ridicată", "hi"], ["medie", "mid"], ["scăzută", "lo"]];
  var ICONS = CONF.concat([["de confirmat", "un"]]);
  var CONF_TOKEN = { "ridicată": "--color-data-hi", "medie": "--color-data-mid", "scăzută": "--color-data-lo", "de confirmat": "--color-data-un" };
  var LUNI = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."];
  var LUNI_L = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"];

  var state = { days: 30, conf: { "ridicată": true, "medie": true, "scăzută": false }, shown: 40, sel: null, years: [21, 25], cty: {}, arii: false, ariiMode: false, faraAut: false, culoare: "aut" };
  var DATA = { alerts: [], data_until: null, generated: null }, RUNS = [], VERIF = {}, FIRMS_FC = null, map, hansen = null;
  var AUT = {}, AUT_META = null; /* autorizațiile de tăiere (APV) din Inspectorul Pădurii, potrivite cu zonele */
  var ARH = null, ARH_LOADED = {}; /* arhiva pe luni: indexul și lunile deja aduse */
  var COUNTY_BB = {}, RO_FC = null, PLACE_LAYERS = ["pl-5", "pl-4", "pl-3", "pl-2", "pl-01"];
  /* literele pentru numele de pe hartă (Noto Sans) stau lângă pagină, în fonts/; harta nu iese din jurul României */
  var GLYPHS = document.baseURI.replace(/[#?].*$/, "").replace(/[^/]*$/, "") + "fonts/{fontstack}/{range}.pbf";
  var MAXB = [[15.5, 39.5], [34.5, 52.5]];
  var NARROW = window.matchMedia("(max-width: 60rem)");
  var LOADERR = false; /* alerts.json n-a venit din alt motiv decât că nu există încă */
  document.getElementById("period-hint").hidden = state.days > 3; /* vizibil fără JavaScript, ascuns de la început la perioadele lungi */

  /* ---------- unelte ---------- */
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function fmt(n, d) { return Number(n).toLocaleString("ro-RO", { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }); }
  function de(n) { var r = Math.round(n) % 100; return (n !== 0 && (r === 0 || r >= 20)) ? "de " : ""; }
  function pd(s) { var p = s.split("-"); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
  function iso(d) { return d.toISOString().slice(0, 10); }
  function addDays(s, k) { var d = pd(s); d.setUTCDate(d.getUTCDate() + k); return iso(d); }
  function zi(s, lung) { if (!s) return "necunoscută"; var d = pd(s); return d.getUTCDate() + " " + (lung ? LUNI_L : LUNI)[d.getUTCMonth()] + " " + d.getUTCFullYear(); }
  function ziScurt(s) { var d = pd(s); return d.getUTCDate() + " " + LUNI[d.getUTCMonth()]; }
  function confCls(c) { return c === "ridicată" ? "hi" : c === "medie" ? "mid" : c === "scăzută" ? "lo" : "un"; }
  function upFirst(s) { return s.charAt(0).toUpperCase() + s.slice(1); }
  function coord(v, pos, neg) { return fmt(Math.abs(v), 5) + "° " + (v >= 0 ? pos : neg); }
  function hhmm(t) { var s = ("000" + String(t)).slice(-4); return s.slice(0, 2) + ":" + s.slice(2); }
  /* numele din GeoNames vin cu sedilă (ş, ţ); în română corect e virgula de dedesubt */
  function ro(s) { return s ? String(s).replace(/ş/g, "ș").replace(/Ş/g, "Ș").replace(/ţ/g, "ț").replace(/Ţ/g, "Ț") : s; }
  var GEN = { comuna: "comunei", "orașul": "orașului", municipiul: "municipiului", sectorul: "sectorului" };
  /* locul unei zone: comuna, orașul sau municipiul din limitele oficiale (UAT), cu județul */
  function placeName(a) {
    var u = a.uat;
    if (u) return upFirst(u.tip) + " " + u.nume + (u.judet && u.tip !== "sectorul" ? ", " + u.judet : "");
    var p = (a.localitate ? ro(a.localitate) + ", " : "") + (a.county || "");
    return p || coord(a.lat, "N", "S") + ", " + coord(a.lon, "E", "V");
  }
  function placeInline(a) {
    var u = a.uat;
    return u ? u.tip + " " + u.nume + (u.judet && u.tip !== "sectorul" ? ", județul " + u.judet : "") : placeName(a);
  }
  function whereText(a) {
    var u = a.uat, sat = ro(a.localitate), near = (a.localitate_km || 99) <= 8;
    if (!u) return (sat ? (near ? " lângă " + sat : " la " + fmt(a.localitate_km) + " km de " + sat) : "") + (a.county ? ", județul " + a.county : "");
    var s = u.aproape ? " la marginea " + (GEN[u.tip] || u.tip) + " " + u.nume : " în " + u.tip + " " + u.nume;
    if (sat && near && sat !== u.nume) s += ", lângă " + sat;
    return s + (u.judet && u.tip !== "sectorul" ? ", județul " + u.judet : "");
  }

  /* culorile vin din foaia de stil, ca harta și pagina să folosească aceleași nuanțe */
  var TOK = {};
  function tok(name) {
    if (TOK[name]) return TOK[name];
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    var c = document.createElement("canvas"); c.width = c.height = 1;
    var x = c.getContext("2d", { willReadFrequently: true });
    x.fillStyle = v; x.fillRect(0, 0, 1, 1);
    var d = x.getImageData(0, 0, 1, 1).data;
    TOK[name] = { rgb: [d[0], d[1], d[2]], css: "rgb(" + d[0] + "," + d[1] + "," + d[2] + ")" };
    return TOK[name];
  }
  function confColor(c) { return tok(CONF_TOKEN[c] || "--color-data-lo").css; }
  function colorMatch() { return ["match", ["get", "c"], "ridicată", confColor("ridicată"), "medie", confColor("medie"), "scăzută", confColor("scăzută"), confColor("de confirmat")]; }
  function colorAutMatch() {
    var m = ["match", ["get", "au"]];
    AUT_ORD.forEach(function (k) { if (k !== "nev") { m.push(k, autColor(k)); } });
    m.push(autColor("nev")); return m;
  }
  function culoareZone() { return peAut() ? colorAutMatch() : colorMatch(); }
  function key(c, prot) { var k = el("i", "key " + confCls(c) + (prot ? " p" : "")); k.setAttribute("aria-hidden", "true"); return k; }
  /* pătratul din listă: după autorizație când asta e culoarea aleasă, altfel după încredere */
  function keyFor(a, prot) {
    if (!peAut()) return key(a.incredere, prot);
    var k = el("i", "key " + AUT_T[autStare(a)].cls + (prot ? " p" : "")); k.setAttribute("aria-hidden", "true"); return k;
  }
  function isProt(a) { return !!(a.arii && a.arii.length); }

  /* ---------- datele ---------- */
  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }

  Promise.all([
    getJSON("data/alerts.json").catch(function (e) { LOADERR = !/ 404$/.test(String(e && e.message)); return null; }),
    getJSON("data/runs.json").catch(function () { return []; }),
    getJSON("data/static/hansen.json").catch(function () { return null; }),
    getJSON("data/static/counties.geojson").catch(function () { return null; }),
    getJSON("data/verificari.json").catch(function () { return null; }),
    getJSON("data/firms.geojson").catch(function () { return null; }),
    getJSON("data/arhiva/index.json").catch(function () { return null; }),
    getJSON("data/permise.json").catch(function () { return null; })
  ]).then(function (res) {
    AUT = (res[7] && res[7].zone) || {}; AUT_META = res[7] || null;
    ARH = res[6] && res[6].luni && res[6].luni.length ? res[6] : null;
    FIRMS_FC = res[5] || { type: "FeatureCollection", features: [] };
    if (res[0]) { DATA = res[0]; DATA.alerts = (DATA.alerts || []).filter(isPublic); }
    VERIF = (res[4] && res[4].zone) || {};
    RUNS = res[1] || [];
    try { initMap(res[2], res[3]); } catch (e) { mapMissing(); }
    initControls();
    initCounties(res[3]);
    document.getElementById("lg-conf").hidden = peAut();
    document.getElementById("lg-aut").hidden = !peAut();
    renderAll();
    var m = location.hash.match(/a=([\w-]+)/);
    if (m) selectById(m[1], true);
    window.addEventListener("hashchange", function () {
      var h = location.hash.match(/a=([\w-]+)/);
      if (h && (!state.sel || state.sel.id !== h[1])) selectById(h[1], true);
    });
  });

  /* dacă biblioteca hărții nu se încarcă, lista și fișele merg mai departe */
  function mapMissing() {
    map = null;
    var w = document.querySelector(".mapwrap");
    w.querySelector(".maptools").hidden = true; document.getElementById("legend").hidden = true;
    w.appendChild(el("p", "map-missing", "Harta nu s-a putut încărca. Lista și fișele zonelor merg în continuare."));
  }

  /* ---------- perioada și filtrele ---------- */
  function periodStart() { return DATA.data_until ? addDays(DATA.data_until, -(state.days - 1)) : null; }
  function inPeriod(a) {
    var s = periodStart(), u = DATA.data_until;
    return !!s && ((a.first_seen >= s && a.first_seen <= u) || (!!a.extinsa && a.extinsa >= s && a.extinsa <= u));
  }
  /* datele mai vechi pot avea încă zone neconfirmate: nu le arătăm */
  function isPublic(a) { return !!CONF_TOKEN[a.incredere] && a.incredere !== "de confirmat" && !a.expirata; }
  function shownArh(a) { return isPublic(a); }
  function visible() { return DATA.alerts.filter(function (a) { return inPeriod(a) && state.conf[a.incredere] && inCounty(a) && inArii(a) && inAut(a) && shownArh(a); }); }
  function inArii(a) { return !state.arii || !!(a.arii && a.arii.length); }

  /* ---------- autorizațiile de tăiere (APV) ----------
     Pentru fiecare zonă căutăm în Inspectorul Pădurii autorizațiile din jur și le comparăm cu data schimbării.
     Zonele neverificate nu primesc nimic: lipsa unei autorizații în datele noastre nu dovedește o tăiere ilegală. */
  /* ordinea e de la cel mai îngrijorător la cel mai liniștitor; culorile vin din foaia de stil */
  var AUT_ORD = ["fara", "neacoperit", "probabil", "acoperit", "nu_taiere", "nev"];
  var AUT_T = {
    fara: { cls: "a-fara", scurt: "fără autorizație", badge: "fără autorizație", grija: true,
            lung: "Nu am găsit nicio autorizație de tăiere în jurul zonei." },
    neacoperit: { cls: "a-neacoperit", scurt: "autorizația nu acoperă tăierea", badge: "autorizația nu acoperă tăierea", grija: true,
                  lung: "Există o autorizație cu parcela publicată în amenajament, dar nu acoperă tăierea asta.",
                  motiv: { afara: "Schimbarea cade în afara parcelei autorizate.",
                           expirat: "Autorizația se terminase înainte ca pădurea să fie încă întreagă aici.",
                           neinceput: "Autorizația începe după ce schimbarea se vedea deja." } },
    probabil: { cls: "a-probabil", scurt: "probabil cu autorizație", badge: "probabil cu autorizație",
                lung: "Există o autorizație în zonă, dar amenajamentul nu publică harta parcelei ei, deci nu putem confirma că o acoperă. De cele mai multe ori o acoperă." },
    acoperit: { cls: "a-acoperit", scurt: "cu autorizație", badge: "cu autorizație", ok: true,
                lung: "Parcela autorizată acoperă zona, iar autorizația era valabilă când s-a tăiat." },
    nu_taiere: { cls: "a-nu_taiere", scurt: "nu e tăiere de pădure", badge: "nu e tăiere de pădure",
                 lung: "Schimbarea nu pare tăiere de lemn, așa că autorizațiile de tăiere nu se aplică.",
                 motiv: { drum: "Forma e o linie lungă și îngustă, ca un drum, o autostradă sau o linie electrică. Un drum prin pădure se aprobă altfel, prin scoatere din fondul forestier, nu cu APV.",
                          agricol: "Analistul AI vede teren agricol: arătură sau recoltă, nu pădure tăiată.",
                          incendiu: "Analistul AI vede urme de foc, nu de tăiere.",
                          nori: "Analistul AI crede că schimbarea vine din nori, nu de pe teren.",
                          "toamnă": "Analistul AI crede că e doar frunza care se îngălbenește toamna." } },
    nev: { cls: "a-nev", scurt: "autorizația neverificată", badge: "neverificată",
           lung: "Zona asta încă n-a fost comparată cu autorizațiile din Inspectorul Pădurii." }
  };
  /* numele vechi, ca o hartă deschisă cu datele de ieri să nu arate goluri */
  var AUT_VECHI = { in_perioada: "acoperit", in_apropiere: "probabil", langa: "probabil", neclar: "probabil", afara: "neacoperit", expirat: "neacoperit", neinceput: "neacoperit" };
  function aut(a) { return AUT[a.id] || null; }
  function autStare(a) { var v = aut(a); if (!v) return "nev"; return AUT_VECHI[v.stare] || v.stare; }
  function autT(a) { return AUT_T[autStare(a)]; }
  function autGrija(a) { return !!autT(a).grija; }
  function inAut(a) { return !state.faraAut || autGrija(a); }
  function autColor(s) { return tok("--color-aut-" + (s === "nev" ? "nev" : s)).css; }
  function autCount(list) { var n = {}; AUT_ORD.forEach(function (k) { n[k] = 0; }); list.forEach(function (a) { n[autStare(a)]++; }); return n; }
  /* colorăm după autorizație doar dacă avem ce arăta */
  function areAut() { for (var k in AUT) return true; return false; }
  function peAut() { return state.culoare === "aut" && areAut(); }

  /* județele alese, pe hartă sau din listă; niciunul = toată țara */
  function countyOf(a) { return (a.uat && a.uat.judet) || a.county || ""; }
  function ctyList() { return Object.keys(state.cty).sort(function (x, y) { return x.localeCompare(y, "ro"); }); }
  function inCounty(a) { return !ctyList().length || !!state.cty[countyOf(a)]; }
  function ctyText() {
    var k = ctyList();
    if (!k.length) return "";
    if (k.length === 1) return k[0] === "București" ? " în București" : " în județul " + k[0];
    return " în județele " + k.slice(0, -1).join(", ") + " și " + k[k.length - 1];
  }
  /* ce filtre de loc sunt puse, pentru mesajele cu „nicio zonă” */
  function ctxText() { return (state.arii ? " din arii protejate" : "") + ctyText(); }

  function daysLabel(n) { return n === 1 ? "ultima zi" : "ultimele " + n + " " + de(n) + "zile"; }
  /* de când avem date: cea mai veche fereastră analizată (istoricul crește cu fiecare rulare) */
  function coverageStart() {
    if (DATA.istoric_de_la) return DATA.istoric_de_la;
    var s = null;
    (RUNS || []).forEach(function (r) { if (r && r.window && (!s || r.window[0] < s)) s = r.window[0]; });
    if (!s && DATA.window) s = DATA.window[0];
    return s;
  }
  function coverageDays() { var s = coverageStart(); return s && DATA.data_until ? Math.round((pd(DATA.data_until) - pd(s)) / 864e5) + 1 : 0; }

  /* perioada de la început: 30 de zile, sau mai mult dacă în ultimele 30 nu e nicio zonă cu nivelurile arătate din start
     (iarna nu căutăm, iar toamna zonele rămân „scăzută”: fără asta harta ar porni goală) */
  function defaultDays() {
    var u = DATA.data_until; if (!u) return state.days;
    var lv = Object.keys(state.conf).filter(function (k) { return state.conf[k]; }), last = null;
    DATA.alerts.forEach(function (a) { if (lv.indexOf(a.incredere) >= 0 && (!last || a.first_seen > last)) last = a.first_seen; });
    if (!last && ARH) ARH.luni.forEach(function (m) { if (lv.some(function (l) { return (m.niveluri || {})[l]; }) && (!last || m.pana_la > last)) last = m.pana_la; });
    if (!last) return state.days;
    var need = Math.round((pd(u) - pd(last)) / 864e5) + 1;
    return need <= state.days ? state.days : need <= 90 ? 90 : Math.min(3650, need);
  }

  /* perioada: butoanele și glisorul arată mereu același număr de zile */
  function setPeriod(n, silent) {
    state.days = Math.max(1, Math.min(3650, n | 0));
    Array.prototype.forEach.call(document.querySelectorAll("#periods button"), function (b) { b.setAttribute("aria-pressed", String(+b.dataset.days === state.days)); });
    var nd = document.getElementById("ndays");
    nd.value = Math.min(+nd.max, state.days);
    document.getElementById("ndays-v").textContent = daysLabel(state.days);
    document.getElementById("period-hint").hidden = state.days > 3;
    state.shown = 40;
    if (!silent) { renderAll(); ensureArchive(); }
  }

  /* ---------- arhiva: lunile vechi se aduc doar când perioada le cere ---------- */
  function loadMonth(m) {
    if (ARH_LOADED[m]) return ARH_LOADED[m];
    ARH_LOADED[m] = getJSON("data/arhiva/" + m + ".json").then(function (d) {
      var have = {};
      DATA.alerts.forEach(function (a) { have[a.id] = 1; });
      (d.alerts || []).forEach(function (a) { if (!have[a.id] && isPublic(a)) { a._arh = true; DATA.alerts.push(a); } });
    }).catch(function () { ARH_LOADED[m] = null; });
    return ARH_LOADED[m];
  }
  function ensureArchive() {
    if (!ARH || !DATA.data_until) return Promise.resolve();
    var s = periodStart(), rec = DATA.recent_de_la || s;
    var need = ARH.luni.filter(function (m) {
      if (ARH_LOADED[m.luna]) return false;
      if (m.pana_la < s || m.de_la > DATA.data_until) return false;
      return m.de_la < rec;
    });
    if (!need.length) return Promise.resolve();
    var note = document.getElementById("arh-note"); if (note) note.hidden = false;
    return Promise.all(need.map(function (m) { return loadMonth(m.luna); })).then(function () {
      if (note) note.hidden = true;
      renderAll();
    });
  }

  function initControls() {
    var per = document.getElementById("periods"), nd = document.getElementById("ndays");
    per.addEventListener("click", function (e) { var b = e.target.closest("button"); if (b) setPeriod(+b.dataset.days); });
    nd.addEventListener("input", function () { setPeriod(+nd.value); });
    var cov = coverageDays();
    if (cov) nd.max = String(Math.max(7, cov));
    setPeriod(defaultDays(), true);

    var cb = document.getElementById("conf");
    CONF.forEach(function (c) {
      var b = el("button", "chip"); b.type = "button"; b.setAttribute("aria-pressed", String(state.conf[c[0]]));
      b.appendChild(key(c[0])); b.appendChild(el("span", null, c[0])); b.appendChild(el("span", "n"));
      b.addEventListener("click", function () { state.conf[c[0]] = !state.conf[c[0]]; b.setAttribute("aria-pressed", String(state.conf[c[0]])); state.shown = 40; renderAll(); });
      b.dataset.conf = c[0];
      cb.appendChild(b);
    });

    var yb = document.getElementById("years");
    [[1, 25, "din 2001"], [16, 25, "din 2016"], [21, 25, "din 2021"], [25, 25, "doar 2025"]].forEach(function (p) {
      var b = el("button", null, p[2]); b.type = "button"; b.setAttribute("aria-pressed", String(p[0] === state.years[0] && p[1] === state.years[1]));
      b.addEventListener("click", function () {
        state.years = [p[0], p[1]];
        Array.prototype.forEach.call(yb.children, function (c) { c.setAttribute("aria-pressed", String(c === b)); });
        document.getElementById("lyr-loss").checked = true;
        setVis("hansen", true);
        paintHansen();
      });
      yb.appendChild(b);
    });
    document.getElementById("lyr-loss").addEventListener("change", function (e) { setVis("hansen", e.target.checked); });
    document.getElementById("lyr-counties").addEventListener("change", function (e) { setVis("counties", e.target.checked); });
    document.getElementById("lyr-arii").addEventListener("change", function (e) { setAriiMode(e.target.checked); });
    var anyProt = DATA.alerts.some(isProt);
    document.getElementById("ariibtn").hidden = !anyProt;
    document.getElementById("lg-p").hidden = !anyProt;
    document.getElementById("ariibtn").addEventListener("click", function () { setAriiMode(!state.ariiMode); });
    var oa = document.getElementById("only-arii");
    if (DATA.alerts.some(function (a) { return a.arii && a.arii.length; })) document.getElementById("tg-only-arii").hidden = false;
    oa.addEventListener("change", function () { setOnlyArii(oa.checked); });
    var fa = document.getElementById("only-fara-aut");
    if (DATA.alerts.some(autGrija)) document.getElementById("tg-fara-aut").hidden = false;
    fa.addEventListener("change", function () { state.faraAut = fa.checked; state.shown = 40; renderAll(); });
    if (areAut()) {
      document.getElementById("culoare").hidden = false;
      document.getElementById("culoare").addEventListener("click", function (e) {
        var b = e.target.closest("button"); if (b) setCuloare(b.dataset.culoare);
      });
    } else {
      state.culoare = "incredere";
    }
    document.getElementById("base").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (b && !b.disabled) setBase(b.dataset.base);
    });
    document.getElementById("splitbtn").addEventListener("click", function () { toggleSplit(this.getAttribute("aria-pressed") !== "true"); });
    document.getElementById("lyr-split").addEventListener("change", function (e) { toggleSplit(e.target.checked); });
  }

  function setVis(id, on) { if (map && map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none"); }

  /* fundalul hărții: satelit, satelit detaliat, harta obișnuită sau doar pădurile (fără imagini din afară) */
  var BASE = "sat";
  function setBase(base) {
    BASE = base;
    Array.prototype.forEach.call(document.querySelectorAll("#base button"), function (c) { c.setAttribute("aria-pressed", String(c.dataset.base === base)); });
    setVis("sat", base === "sat"); setVis("hd", base === "hd"); setVis("osm", base === "osm");
    PLACE_LAYERS.forEach(function (id) { setVis(id, base !== "osm"); });
    paintForBase();
  }
  /* pe harta obișnuită (deschisă la culoare) liniile devin închise, ca să se vadă */
  function paintForBase() {
    if (!map || !map.getLayer) return;
    var light = BASE === "osm", fg = tok(light ? "--color-paper-3" : "--color-ink").css, bg = tok(light ? "--color-ink" : "--color-paper-3").css;
    [["ro-line", "line-color", fg], ["ro-halo", "line-color", bg], ["counties", "line-color", fg], ["cty-hover", "line-color", fg],
     ["cty-sel-line", "line-color", fg], ["cty-sel-halo", "line-color", bg], ["cty-sel-fill", "fill-color", fg]].forEach(function (x) {
      if (map.getLayer(x[0])) map.setPaintProperty(x[0], x[1], x[2]);
    });
  }
  /* unele servere de hărți pot lipsi (blocate sau căzute): încercăm câte o bucată și ascundem ce nu merge */
  function probe(url) {
    return new Promise(function (res) {
      var i = new Image(), t = setTimeout(function () { res(false); }, 8000);
      i.onload = function () { clearTimeout(t); res(true); };
      i.onerror = function () { clearTimeout(t); res(false); };
      i.src = url;
    });
  }
  function unavailable(kind) {
    var b = document.querySelector('#base button[data-base="' + kind + '"]');
    if (b) b.disabled = true;
    if (kind === "sat") { document.getElementById("base-note").hidden = false; if (BASE === "sat") setBase("forest"); }
    if (kind === "osm") {
      document.getElementById("tg-split").hidden = true; document.getElementById("splitbtn").hidden = true;
      if (BASE === "osm") setBase("forest");
    }
    if (kind === "hd" && BASE === "hd") setBase("forest");
  }

  /* ---------- randare ---------- */
  function renderAll() {
    renderHeader();
    renderStats();
    renderList();
    updateMapData();
  }

  function stamp(k, v, z) {
    var c = el("span", "cell"), vv = el("span", "v num", v);
    c.appendChild(el("span", "k", k));
    if (z) { vv.appendChild(document.createTextNode(" ")); vv.appendChild(el("span", "z", z)); }
    c.appendChild(vv);
    return c;
  }
  function renderHeader() {
    var u = document.getElementById("updated"), r = document.getElementById("range");
    if (!DATA.data_until) {
      u.textContent = LOADERR ? "Datele nu s-au putut încărca. Reîncarcă pagina peste câteva minute." : "Prima rulare pe toată țara e în curs. Revino în câteva ore.";
      r.textContent = "";
      return;
    }
    u.replaceChildren(stamp("Imagini până pe", zi(DATA.data_until)));
    if (DATA.generated) {
      var g = new Date(DATA.generated), tz = { timeZone: "Europe/Bucharest" };
      var day = g.toLocaleDateString("ro-RO", { timeZone: tz.timeZone, day: "numeric", month: "short" });
      var hour = g.toLocaleTimeString("ro-RO", { timeZone: tz.timeZone, hour: "2-digit", minute: "2-digit" });
      u.appendChild(stamp("Actualizat", day + ", " + hour, "ora României"));
    }
    var s = periodStart();
    var c0 = coverageStart(), cov = coverageDays();
    if (c0 && s < c0) s = c0;
    var sameYear = s && s.slice(0, 4) === DATA.data_until.slice(0, 4);
    r.textContent = state.days === 1 ? "Schimbări văzute prima dată pe " + zi(DATA.data_until) : "Schimbări văzute prima dată între " + (sameYear ? ziScurt(s) : zi(s)) + " și " + zi(DATA.data_until);
    var cv = document.getElementById("coverage");
    if (cv) cv.textContent = c0 ? (state.days > cov ? "Avem date doar din " + zi(c0, true) + ", așa că vezi tot ce avem. " : "") + "Istoricul începe pe " + zi(c0, true) + " și crește în fiecare zi." : "";
    var wn = document.getElementById("winter-note");
    if (wn) wn.hidden = !touchesWinter(s, DATA.data_until);
  }
  /* iarna (1 noiembrie – 15 martie) detectorul nu caută: perioada aleasă cade, măcar în parte, atunci? */
  function isWinterDay(t) { var md = t.slice(5, 10); return md >= "11-01" || md <= "03-15"; }
  function touchesWinter(s, u) {
    if (!s || !u) return false;
    for (var t = pd(s).getTime(), end = pd(u).getTime(); t <= end; t += 5 * 864e5) if (isWinterDay(new Date(t).toISOString())) return true;
    return isWinterDay(u);
  }

  function renderStats() {
    var v = visible(), ha = v.reduce(function (t, a) { return t + a.ha; }, 0);
    var cty = {}; v.forEach(function (a) { var c = countyOf(a); if (c) cty[c] = 1; });
    var st = document.getElementById("stats");
    st.replaceChildren();
    if (!DATA.data_until) { document.getElementById("spark").replaceChildren(); return; }
    [[fmt(v.length), "zone"], [fmt(ha, ha < 100 ? 1 : 0), "hectare"], [fmt(Object.keys(cty).length), "județe"]].forEach(function (x) {
      var d = el("div"); d.appendChild(el("b", null, x[0])); d.appendChild(el("span", null, x[1])); st.appendChild(d);
    });
    renderSpark(v);
    /* cât din ce se vede a fost comparat cu autorizațiile */
    var la = document.getElementById("lg-acop");
    if (la) {
      var nv = v.filter(function (a) { return !!aut(a); }).length;
      la.textContent = v.length && areAut() ? fmt(nv) + " din " + fmt(v.length) + " verificate" : "";
    }
    var np = v.filter(isProt).length, bn = document.getElementById("ariibtn-n"), ab = document.getElementById("ariibtn");
    if (bn) bn.replaceChildren(el("b", null, fmt(np)), document.createTextNode(" " + (np === 1 ? "zonă" : de(np) + "zone")));
    if (ab) ab.title = np === 1 ? "O zonă din cele afișate e într-o arie protejată" : fmt(np) + " " + de(np) + "zone din cele afișate sunt în arii protejate";
    var all = DATA.alerts.filter(function (a) { return inPeriod(a) && inCounty(a) && inArii(a) && shownArh(a); });
    Array.prototype.forEach.call(document.querySelectorAll("#conf .chip"), function (b) {
      var n = all.filter(function (a) { return a.incredere === b.dataset.conf; }).length;
      b.querySelector(".n").textContent = fmt(n);
    });
  }

  function renderSpark(v) {
    /* câte zone noi pe zi (sau pe săptămână, dacă perioada e lungă) */
    var sp = document.getElementById("spark");
    sp.replaceChildren();
    if (!DATA.data_until || state.days < 3) return;
    var step = state.days > 70 ? 7 : 1, n = Math.ceil(state.days / step), start = periodStart(), counts = [];
    for (var i = 0; i < n; i++) counts.push(0);
    v.forEach(function (a) { var k = Math.floor((pd(a.first_seen) - pd(start)) / 864e5 / step); if (k >= 0 && k < n) counts[k]++; });
    var mx = Math.max.apply(null, counts) || 1, bars = el("div", "bars");
    counts.forEach(function (c, i) {
      var b = el("i", c ? null : "z");
      if (c) b.style.height = Math.max(8, 100 * c / mx) + "%";
      b.title = (step === 1 ? zi(addDays(start, i)) : "săptămâna din " + zi(addDays(start, i * step))) + ": " + c + " " + (c === 1 ? "zonă" : de(c) + "zone");
      bars.appendChild(b);
    });
    sp.appendChild(bars);
    var ax = el("div", "ax");
    ax.appendChild(el("span", null, ziScurt(start)));
    ax.appendChild(el("span", null, "cel mult " + mx + (step === 1 ? " pe zi" : " pe săptămână")));
    ax.appendChild(el("span", null, ziScurt(DATA.data_until)));
    sp.appendChild(ax);
    sp.setAttribute("aria-label", "Zone noi " + (step === 1 ? "pe zi" : "pe săptămână") + ", cel mult " + mx);
  }

  function renderList() {
    var ol = document.getElementById("list"), box = document.getElementById("listbox");
    ol.replaceChildren();
    var old = box.querySelector(".empty, .more"); if (old) old.remove();
    var v = visible().sort(function (a, b) { return (b.first_seen > a.first_seen) - (b.first_seen < a.first_seen) || b.ha - a.ha; });
    if (!DATA.data_until) return;
    if (!v.length) {
      var s0 = periodStart(), older = DATA.alerts.filter(function (a) { return state.conf[a.incredere] && inCounty(a) && inArii(a) && a.first_seen < s0; })
        .sort(function (a, b) { return (b.first_seen > a.first_seen) - (b.first_seen < a.first_seen); })[0];
      if (older) {
        var need = Math.round((pd(DATA.data_until) - pd(older.first_seen)) / 864e5) + 1;
        var em = el("div", "empty");
        em.appendChild(el("p", null, "Nicio zonă cu nivelurile alese" + ctxText() + " în " + daysLabel(state.days) + ". Cea mai recentă e din " + zi(older.first_seen, true) + ", în " + placeInline(older) + "."));
        var go = el("button", "more", "Arată din " + ziScurt(older.first_seen)); go.type = "button";
        go.addEventListener("click", function () { setPeriod(need); });
        em.appendChild(go); box.appendChild(em);
        return;
      }
      var hidden = DATA.alerts.filter(function (a) { return inPeriod(a) && inCounty(a) && inArii(a) && shownArh(a); }).length;
      var msg = hidden ? "Nicio schimbare cu acest nivel de încredere" + ctxText() + " în perioada aleasă. Bifează și „scăzută” ca să le vezi pe toate." :
        "Nicio schimbare nouă" + ctxText() + " în perioada aleasă. Poate fi și din cauza norilor: pădurea acoperită de nori nu se vede. Încearcă o perioadă mai lungă.";
      if (!ctyList().length && !state.arii) { box.appendChild(el("p", "empty", msg)); return; }
      var ec = el("div", "empty"); ec.appendChild(el("p", null, msg));
      if (ctyList().length) { var wide = el("button", "more", "Arată toată țara"); wide.type = "button"; wide.addEventListener("click", clearCounties); ec.appendChild(wide); }
      if (state.arii) { var out = el("button", "more", "Arată și zonele din afara ariilor protejate"); out.type = "button"; out.addEventListener("click", function () { setOnlyArii(false); }); ec.appendChild(out); }
      box.appendChild(ec);
      return;
    }
    v.slice(0, state.shown).forEach(function (a) {
      var li = el("li"), b = el("button", "row"), meta = [];
      b.type = "button";
      b.appendChild(el("span", "visually-hidden", (peAut() ? AUT_T[autStare(a)].badge + ". Încredere " + a.incredere : "Încredere " + a.incredere) + ". "));
      b.appendChild(keyFor(a, isProt(a)));
      b.appendChild(el("span", "t", placeName(a)));
      b.appendChild(el("span", "d", ziScurt(a.first_seen)));
      b.appendChild(el("span", "p", headline(a).t));
      b.appendChild(el("span", "a", fmt(a.ha, 1) + " ha"));
      if (isVerified(a)) meta.push("verificat și din alte surse");
      if (aut(a)) meta.push(autT(a).scurt);
      if (a.arii && a.arii.length) meta.push("în arie protejată");
      if (a.extinsa) meta.push("s-a lărgit pe " + ziScurt(a.extinsa));
      if (a.langa) meta.push("lângă o zonă din " + ziScurt(a.langa.first_seen));
      meta.push(a.n_dates >= 2 ? "văzută în " + a.n_dates + " imagini" : "o singură imagine");
      b.appendChild(el("span", "s", upFirst(meta.join(", "))));
      b.addEventListener("click", function () { select(a, true); });
      li.appendChild(b); ol.appendChild(li);
    });
    if (v.length > state.shown) {
      var m = el("button", "more", "Arată încă " + Math.min(40, v.length - state.shown) + " din " + v.length);
      m.type = "button"; m.addEventListener("click", function () { state.shown += 40; renderList(); });
      box.appendChild(m);
    }
  }

  /* ---------- fișa unei alerte ---------- */
  function selectById(id, fly, retried) {
    var a = DATA.alerts.find(function (x) { return x.id === id; });
    if (!a) {
      /* zona poate fi în arhivă: id-ul începe cu data primei observații (AAAALLZZ) */
      var m = String(id).slice(0, 4) + "-" + String(id).slice(4, 6);
      if (!retried && ARH && ARH.luni.some(function (x) { return x.luna === m; })) loadMonth(m).then(function () { selectById(id, fly, true); });
      return;
    }
    if (!inPeriod(a)) setPeriod(Math.max(1, Math.round((pd(DATA.data_until) - pd(a.first_seen)) / 864e5) + 1), true);
    if (!state.conf[a.incredere]) { state.conf[a.incredere] = true; var c = document.querySelector('#conf .chip[data-conf="' + a.incredere + '"]'); if (c) c.setAttribute("aria-pressed", "true"); }
    if (!inCounty(a)) { state.cty = {}; renderCounties(); updateCountyLayers(); }
    if (!inArii(a)) setOnlyArii(false, true);
    renderAll();
    select(a, fly);
  }

  /* fly: mută harta pe zonă și derulează la fișă; scroll: doar derulează (pe telefon, după un clic pe hartă) */
  function select(a, fly, scroll) {
    state.sel = a;
    try { history.replaceState(null, "", "#a=" + a.id); } catch (e) { /* unele ferestre nu permit */ }
    var d = document.getElementById("detail");
    document.getElementById("listbox").hidden = true;
    d.hidden = false;
    d.replaceChildren();
    var back = el("button", "back", "Înapoi la listă"); back.type = "button";
    back.addEventListener("click", unselect);
    d.appendChild(back);
    d.appendChild(kindBlock(a));
    d.appendChild(el("p", "where", fmt(a.ha, 1) + " ha" + whereText(a)));
    var bd = el("div", "badges");
    var c1 = el("span", "badge"); c1.appendChild(key(a.incredere)); c1.appendChild(document.createTextNode("încredere " + a.incredere)); bd.appendChild(c1);
    if (isVerified(a)) bd.appendChild(el("span", "badge ok", "verificat și din alte surse"));
    if (aut(a)) {
      var t = autT(a), ba = el("span", "badge aut" + (t.ok ? " ok" : ""));
      ba.appendChild(el("i", "key " + t.cls)); ba.appendChild(document.createTextNode(t.badge));
      bd.appendChild(ba);
    }
    if (a.vant) bd.appendChild(el("span", "badge", "vânt puternic"));
    if (a.arii && a.arii.length) bd.appendChild(el("span", "badge arie", "în arie protejată"));
    if (a.extinsa) bd.appendChild(el("span", "badge", "s-a lărgit pe " + ziScurt(a.extinsa)));
    d.appendChild(bd);
    d.appendChild(compare(a, false));
    if (a.img_after) d.appendChild(chipControl(a));
    if (a.text) d.appendChild(el("p", "sum", a.text));
    if (a.langa) {
      var nb = el("p", "near"), go = el("button", "mini", "Vezi zona de atunci"); go.type = "button";
      nb.appendChild(document.createTextNode("Chiar lângă, o altă schimbare fusese văzută pe " + zi(a.langa.first_seen, true) + ". "));
      go.addEventListener("click", function () { selectById(a.langa.id, true); });
      nb.appendChild(go); d.appendChild(nb);
    }
    var act = el("div", "actions");
    function link(t, h) { var x = el("a", null, t); x.href = h; x.target = "_blank"; x.rel = "noopener"; act.appendChild(x); }
    link("Google Maps (satelit)", "https://www.google.com/maps/@?api=1&map_action=map&center=" + a.lat + "," + a.lon + "&zoom=16&basemap=satellite");
    link("OpenStreetMap", "https://www.openstreetmap.org/?mlat=" + a.lat + "&mlon=" + a.lon + "#map=15/" + a.lat + "/" + a.lon);
    link("Raportează o greșeală", REPO + "/issues/new?title=" + encodeURIComponent("Alerta " + a.id) + "&body=" + encodeURIComponent("Ce e greșit la alerta " + a.id + "?\n\n" + location.href));
    d.appendChild(act);
    if (a.arii && a.arii.length) d.appendChild(ariiBlock(a));
    var vi = verifItems(a); if (vi.length) d.appendChild(verifBlock(vi));
    var ab2 = autBlock(a); if (ab2) d.appendChild(ab2);
    d.appendChild(ownerBlock(a));
    var ev = el("ul", "ev"); (a.dovezi || []).forEach(function (x) { ev.appendChild(el("li", null, x)); });
    d.appendChild(el("p", "lbl", "De ce acest nivel de încredere"));
    d.appendChild(ev);
    var kv = el("dl", "kv");
    function row(k, v, num) { kv.appendChild(el("dt", null, k)); var dd = el("dd", num ? "num" : null); if (v instanceof Node) dd.appendChild(v); else dd.textContent = v; kv.appendChild(dd); }
    if (a.before_date || !a.vara) row("Intactă pe", zi(a.before_date, true), true);
    else row("Intactă", "în vara lui " + a.vara + " (de atunci, nori, zăpadă sau iarnă)");
    row("Schimbată pe", zi(a.first_seen, true), true);
    row("Ultima imagine", zi(a.after_date, true), true);
    if (a.rafala_kmh != null) { var w = el("span"); w.appendChild(el("span", "num", fmt(a.rafala_kmh) + " km/h")); w.appendChild(document.createTextNode(" în acel interval")); row("Vânt maxim", w); }
    if (a.hansen_jur && a.hansen_jur.ani && a.hansen_jur.ani.length) row("Pierderi în jur", a.hansen_jur.ani.join(", ") + " (Hansen)");
    row("Coordonate", coord(a.lat, "N", "S") + ", " + coord(a.lon, "E", "V"), true);
    d.appendChild(kv);
    d.appendChild(el("p", "mono", a.id));
    if (fly || scroll) d.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
    if (fly && map) {
      var b = a.bbox;
      map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 120, maxZoom: 14.5, duration: REDUCED ? 0 : 900 });
    }
    updateSelection();
  }

  var CHIP = "a";
  function showChip(a) {
    if (!map || !map.getLayer || !map.getStyle()) return;
    var info = a && (CHIP === "b" ? a.img_before : CHIP === "a" ? a.img_after : null);
    if (!info || !a.chip_bbox) { if (map.getLayer("chip")) map.setLayoutProperty("chip", "visibility", "none"); return; }
    var cb = a.chip_bbox, coords = [[cb[0], cb[3]], [cb[2], cb[3]], [cb[2], cb[1]], [cb[0], cb[1]]], url = "img/" + info.file;
    if (map.getSource("chip")) map.getSource("chip").updateImage({ url: url, coordinates: coords });
    else {
      map.addSource("chip", { type: "image", url: url, coordinates: coords });
      map.addLayer({ id: "chip", type: "raster", source: "chip", paint: { "raster-fade-duration": 0, "raster-saturation": -0.2, "raster-contrast": 0.1 } }, map.getLayer("firms") ? "firms" : "a-fill");
    }
    map.setLayoutProperty("chip", "visibility", "visible");
  }
  function chipControl(a) {
    var row = el("div", "maprow"), seg = el("div", "seg small");
    row.appendChild(el("span", null, "Pe hartă, sub zonă:"));
    seg.setAttribute("role", "group"); seg.setAttribute("aria-label", "Ce poză arată harta sub zonă");
    [["b", "poza de înainte"], ["a", "poza de după"], ["x", "nicio poză"]].forEach(function (m) {
      if ((m[0] === "b" && !a.img_before) || (m[0] === "a" && !a.img_after)) return;
      var x = el("button", null, m[1]); x.type = "button"; x.dataset.k = m[0]; x.setAttribute("aria-pressed", String(m[0] === CHIP)); seg.appendChild(x);
    });
    seg.addEventListener("click", function (e) {
      var x = e.target.closest("button"); if (!x) return;
      CHIP = x.dataset.k;
      Array.prototype.forEach.call(seg.children, function (c) { c.setAttribute("aria-pressed", String(c === x)); });
      showChip(a);
    });
    row.appendChild(seg);
    return row;
  }

  function unselect() {
    state.sel = null;
    try { history.replaceState(null, "", location.pathname); } catch (e) { /* unele ferestre nu permit */ }
    showChip(null);
    document.getElementById("detail").hidden = true;
    document.getElementById("listbox").hidden = false;
    updateSelection();
  }

  /* ---------- ce pare, în cuvinte simple ---------- */
  var KIND = {
    incendiu: ["Pare o zonă arsă", "fire"],
    taiere: ["Pare pădure tăiată sau sol gol nou", "cut"],
    toamna: ["Pare doar culoarea de toamnă", "leaf"],
    nori: ["Pare nori sau ceață", "cloud"],
    agricol: ["Pare teren agricol", "field"],
    neclar: ["Schimbare neclară", "q"]
  };
  var ICON = {
    fire: '<path d="M12 3c1 3 4.5 4.8 4.5 9.5a4.5 4.5 0 0 1-9 0c0-2.3 1.2-3.6 2.2-4.6 0 2 .9 3.1 2 3.1.3-2.6-.8-4.8.3-8z"/>',
    cut: '<path d="M4.5 19.5 14 10"/><path d="M12.5 4.5 19.5 11.5 16.5 12.5 11.5 7.5z"/>',
    leaf: '<path d="M5 19c0-8 6-14 14-14 0 8-6 14-14 14z"/><path d="M5 19l8-8"/>',
    cloud: '<path d="M7 18h10a4 4 0 0 0 0-8 6 6 0 0 0-11.5 1.5A3.5 3.5 0 0 0 7 18z"/>',
    field: '<path d="M3 18h18M5 14h14M7 10h10"/>',
    q: '<path d="M4 4h16v16H4z"/><path d="M12 16.5v.5M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8"/>'
  };
  function headline(a) {
    var v = a.vis && a.vis.verdict;
    if (a.firms && a.firms.n) return { t: "Incendiu văzut de sateliții NASA", k: "fire", src: "NASA FIRMS" + (v === "deschisa" ? ", dar zona era deja deschisă înainte, nu pădure" : "") };
    var fire = (VERIF[a.id] || []).filter(function (x) { return x.tip === "incendiu"; });
    var sure = fire.filter(function (x) { return x.potrivire === "sigură"; });
    if (sure.length) return { t: "Incendiu confirmat", k: "fire", src: sure.map(function (x) { return x.sursa; }).join("; ") };
    if (fire.length) return { t: "Probabil incendiu", k: "fire", src: fire[0].sursa + ", potrivire probabilă" };
    if (v === "deschisa") return { t: "Zona era deja deschisă înainte", k: "q", src: "verificarea pe poze" };
    if (v === "nevazut") return { t: "În poze nu se vede o schimbare clară", k: "q", src: "verificarea pe poze" };
    var c = a.ai && KIND[a.ai.categorie];
    if (c) return { t: c[0], k: c[1], src: "părerea analistului AI" };
    return { t: "Schimbare de verificat", k: "q", src: "" };
  }
  function kindBlock(a) {
    var h = headline(a), box = el("div", "kind k-" + h.k);
    var ic = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    ic.setAttribute("viewBox", "0 0 24 24"); ic.setAttribute("aria-hidden", "true"); ic.innerHTML = ICON[h.k];
    box.appendChild(ic);
    var t = el("div"); t.appendChild(el("h3", null, h.t)); if (h.src) t.appendChild(el("span", null, h.src));
    box.appendChild(t);
    return box;
  }

  /* ---------- verificări din alte surse: NASA FIRMS (automat) și data/verificari.json (oameni) ---------- */
  function rangeTxt(x, y) { return x === y ? "pe " + zi(x, true) : "între " + zi(x, true) + " și " + zi(y, true); }
  function verifItems(a) {
    var out = [], fi = a.firms;
    if (fi && fi.n) out.push({ sursa: "NASA FIRMS, senzori în infraroșu", potrivire: "sigură", url: "https://firms.modaps.eosdis.nasa.gov/map/",
      text: "Sateliții NASA au văzut " + fi.n + (fi.n === 1 ? " punct" : " " + de(fi.n) + "puncte") + " de foc la cel mult " + fmt(fi.dist_m) + " m de zonă, " + rangeTxt(fi.prima, fi.ultima) + (fi.surse ? " (" + fi.surse.join(", ") + ")" : "") + "." });
    else if (fi) out.push({ sursa: "NASA FIRMS, senzori în infraroșu", potrivire: "nimic",
      text: "Sateliții NASA n-au văzut foc la sub 750 m de zonă " + rangeTxt(fi.de_la, fi.pana_la) + ". Focurile mici sau ascunse de nori pot scăpa." });
    return out.concat(VERIF[a.id] || []);
  }
  function isVerified(a) { return verifItems(a).some(function (v) { return v.potrivire !== "nimic"; }); }
  function verifBlock(items) {
    var box = el("div", "verif");
    box.appendChild(el("p", "lbl", "Verificat și din alte surse"));
    items.forEach(function (v) {
      var it = el("div", "vitem");
      var head = el("p"); head.appendChild(el("b", null, v.sursa));
      head.appendChild(el("span", "vfit " + (v.potrivire === "sigură" ? "sure" : v.potrivire === "nimic" ? "none" : "maybe"),
        v.potrivire === "sigură" ? "se potrivește" : v.potrivire === "nimic" ? "n-a văzut foc" : "se potrivește probabil"));
      it.appendChild(head);
      it.appendChild(el("p", null, v.text));
      if (v.url) { var a = el("a", null, "Vezi sursa"); a.href = v.url; a.target = "_blank"; a.rel = "noopener"; it.appendChild(a); }
      if (v.potrivire === "nimic") it.classList.add("quiet");
      box.appendChild(it);
    });
    return box;
  }

  /* ---------- ariile protejate în care cade zona: doar informație, nivelul de încredere nu se schimbă ---------- */
  var ARIE = { "parc național": "Parcul Național", "parc natural": "Parcul Natural", "rezervație științifică": "rezervația științifică",
    "rezervație naturală": "rezervația naturală", "monument al naturii": "monumentul naturii", "rezervația biosferei": "Rezervația Biosferei",
    "geoparc": "Geoparcul", "arie protejată națională": "aria protejată" };
  var ARIE_REG = {
    "rezervație științifică": "Rezervațiile științifice au regim de protecție strictă.",
    "parc național": "În parcurile naționale legea interzice exploatarea în zonele de protecție strictă și integrală; în restul parcului tăierile sunt permise, cu restricții. Harta acestor zone nu e publică într-o formă pe care s-o putem folosi.",
    "rezervația biosferei": "În Delta Dunării regulile depind de zonă: protecție strictă, tampon sau tranziție.",
    "rezervație naturală": "Rezervațiile naturale și monumentele naturii au reguli proprii de protecție, scrise în regulamentul fiecăreia.",
    "parc natural": "În parcurile naturale tăierile sunt permise cu restricțiile din planul de management, mai puțin în zonele de protecție integrală.",
    "geoparc": "Geoparcurile au reguli proprii de protecție, scrise în regulamentul fiecăruia.",
    "sit Natura 2000": "În siturile Natura 2000 tăierile sunt permise după amenajamentul silvic, dacă nu afectează speciile și habitatele pentru care a fost declarat situl."
  };
  function arieName(p) {
    var t = p.tip || "", n = p.nume || "";
    if (t.indexOf("sit Natura 2000") === 0) return ("situl Natura 2000 " + (p.cod || "") + " " + n).replace(/\s+/g, " ").trim();
    var art = ARIE[t] || "aria protejată";
    return /^((geo)?parcul|rezerva|monumentul|aria )/.test(n.toLowerCase()) ? n : (art + " " + n).trim();
  }
  function ariiBlock(a) {
    var box = el("div", "owner arii"), ul = el("ul");
    box.appendChild(el("p", "lbl", "Arie protejată"));
    a.arii.forEach(function (p) {
      var li = el("li", null, upFirst(arieName(p)) + (p.parte != null && p.parte < 0.9 ? ", doar o parte din zonă" : "") + " ");
      if (p.cod && /^RO(SCI|SAC|SPA)\d/.test(p.cod)) {
        var x = el("a", null, "fișa sitului"); x.href = "https://natura2000.eea.europa.eu/Natura2000/SDF.aspx?site=" + encodeURIComponent(p.cod);
        x.target = "_blank"; x.rel = "noopener"; li.appendChild(x);
      }
      ul.appendChild(li);
    });
    box.appendChild(ul);
    var seen = {}, notes = [];
    a.arii.forEach(function (p) {
      var k = p.tip === "monument al naturii" ? "rezervație naturală" : (p.tip || "").indexOf("sit Natura 2000") === 0 ? "sit Natura 2000" :
        /^geoparc/i.test(p.nume || "") ? "geoparc" : p.tip;
      if (ARIE_REG[k] && !seen[k]) { seen[k] = 1; notes.push(ARIE_REG[k]); }
    });
    notes.slice(0, 2).forEach(function (t) { box.appendChild(el("p", null, t)); });
    box.appendChild(el("p", null, "Dacă tăierea era permisă aici pot spune administrația ariei protejate, ocolul silvic sau Garda Forestieră."));
    return box;
  }
  function setOnlyArii(on, silent) {
    state.arii = on; state.shown = 40;
    var c = document.getElementById("only-arii"); if (c) c.checked = on;
    if (!silent) renderAll();
  }

  /* ---------- „Arii protejate” pe hartă: arată limitele ariilor și lasă în față doar zonele din ele ---------- */
  function setAriiMode(on) {
    state.ariiMode = on;
    var b = document.getElementById("ariibtn"); if (b) b.setAttribute("aria-pressed", String(on));
    var c = document.getElementById("lyr-arii"); if (c) c.checked = on;
    toggleArii(on);
    paintArii();
  }
  function paintArii() {
    [map].forEach(function (m) {
      if (!m || !m.getLayer || !m.getLayer("a-pt")) return;
      var on = state.ariiMode;
      m.setPaintProperty("a-pt", "icon-opacity", on ? ["case", ["get", "p"], 1, 0.25] : 1);
      m.setPaintProperty("a-fill", "fill-opacity", on ? ["case", ["get", "p"], 0.32, 0.06] : 0.28);
      m.setPaintProperty("a-line", "line-opacity", on ? ["case", ["get", "p"], 1, 0.25] : 1);
    });
  }
  function toggleArii(on) {
    document.getElementById("lg-arii").hidden = !on;
    if (!map || !map.getStyle) return;
    if (map.getLayer("arii-fill")) { setVis("arii-fill", on); setVis("arii-line", on); return; }
    if (!on) return;
    getJSON("data/static/arii.geojson").then(function (fc) {
      if (map.getSource("arii")) return;
      map.addSource("arii", { type: "geojson", data: fc, attribution: 'Arii protejate: <a href="https://www.eea.europa.eu" target="_blank">EEA</a>' });
      var col = tok("--color-protected").css, before = map.getLayer("cty-hit") ? "cty-hit" : map.getLayer("firms") ? "firms" : undefined;
      map.addLayer({ id: "arii-fill", type: "fill", source: "arii", paint: { "fill-color": col, "fill-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.16, 11, 0.1] } }, before);
      map.addLayer({ id: "arii-line", type: "line", source: "arii", paint: { "line-color": col, "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.6, 11, 1.4], "line-opacity": 0.7 } }, before);
    }).catch(function () { document.getElementById("tg-arii").hidden = true; document.getElementById("lg-arii").hidden = true; document.getElementById("ariibtn").hidden = true; });
  }

  /* ---------- autorizația de tăiere: ce scrie în Inspectorul Pădurii pentru zona asta ----------
     Spunem ce am găsit și ce n-am găsit, cu limitele la vedere: harta parcelelor e publicată doar în parte. */
  function autBlock(a) {
    var v = aut(a); if (!v) return null;
    var t = autT(a), box = el("div", "verif aut");
    box.appendChild(el("p", "lbl", "Autorizația de tăiere (APV)"));

    /* verdictul, în cuvinte, înaintea cifrelor */
    var head = el("p", "aut-head");
    head.appendChild(el("i", "key " + t.cls));
    head.appendChild(el("b", null, t.badge));
    box.appendChild(head);
    box.appendChild(el("p", null, t.lung));
    if (t.motiv && v.motiv && t.motiv[v.motiv]) box.appendChild(el("p", null, t.motiv[v.motiv]));

    /* când s-a tăiat: intervalul, nu data la care am văzut noi */
    var cs = a.before_date ? zi(a.before_date, true) : (a.vara ? "vara lui " + a.vara : null);
    if (cs) {
      var p1 = el("p", "vfit", "Tăierea s-a întâmplat între " + cs + " (ultima dată când pădurea era întreagă aici) și "
        + zi(a.first_seen, true) + " (prima imagine cu schimbarea).");
      if (!a.before_date) p1.textContent += " E un interval larg, deci despre perioada autorizației putem spune puține.";
      box.appendChild(p1);
    }

    if (v.apv && v.stare !== "nu_taiere") {
      var it = el("div", "vitem");
      var h2 = el("p"); h2.appendChild(el("b", null, "APV " + v.apv));
      if (v.stare_apv) h2.appendChild(el("span", "vfit", v.stare_apv));
      it.appendChild(h2);
      var uaTxt = v.ua_text || (v.ua && v.ua.length ? v.ua.join(", ") : null);
      var det = [v.ocol, uaTxt ? "u.a. " + uaTxt : null,
                 v.volum_m3 != null ? fmt(v.volum_m3) + " m³" : null, v.tratament].filter(Boolean).join(" · ");
      if (det) it.appendChild(el("p", null, det));
      if (v.start && v.end) it.appendChild(el("p", null, "Tăiere permisă între " + zi(v.start, true) + " și " + zi(v.end, true) + "."));
      it.appendChild(el("p", "vfit", v.suprapunere > 0
        ? "Parcela autorizată acoperă " + Math.round(v.suprapunere * 100) + "% din zona schimbată."
        : "Parcela autorizată nu atinge zona schimbată; e la " + fmt(v.dist_m) + " m."));
      if (v.potrivire === "estimat" || v.potrivire === "buffer")
        it.appendChild(el("p", "vfit", "Parcela nu e publicată în amenajament; în locul ei am folosit un cerc în jurul punctului autorizației, pe măsura volumului. Poziția e aproximativă."));
      if (v.volum_suspect) it.appendChild(el("p", "vfit", "Suprafața schimbată pare mult mai mare decât ar explica volumul autorizat."));
      if (v.n_apv > 1) it.appendChild(el("p", "vfit", v.n_apv + " autorizații în jur; o arătăm pe cea care se potrivește cel mai bine."));
      if (t.grija) it.classList.add("quiet");
      box.appendChild(it);
    }

    box.appendChild(el("p", "vfit", "Harta parcelelor e publicată doar în parte, mai ales pentru pădurile private, iar autorizațiile se pot prelungi. O zonă fără autorizație găsită nu e o dovadă de tăiere ilegală — e un motiv de verificat."));
    var lk = el("a", null, "Caută în Inspectorul Pădurii"); lk.href = "https://inspectorulpadurii.ro"; lk.target = "_blank"; lk.rel = "noopener";
    box.appendChild(lk);
    return box;
  }

  /* ---------- cine deține terenul: nu publicăm nume; arătăm drumul legal, pas cu pas ---------- */
  function ownerBlock(a) {
    var box = el("div", "owner");
    box.appendChild(el("p", "lbl", "Cine deține terenul"));
    box.appendChild(el("p", null, "Nu publicăm proprietari: cartea funciară se cere parcelă cu parcelă, iar proprietarul nu e neapărat cel care a tăiat. Oricine poate afla, așa:"));
    var ol = el("ol");
    [["Caută parcela după coordonate pe geoportalul ANCPI și notează numărul cadastral.", "https://geoportal.ancpi.ro", "Geoportal ANCPI"],
     ["Cere un extras de carte funciară pentru informare pe ePay ANCPI; îl poate cere oricine.", "https://epay.ancpi.ro", "ePay ANCPI"],
     ["Caută autorizațiile de exploatare și transporturile de lemn din zonă în Inspectorul Pădurii.", "https://inspectorulpadurii.ro", "Inspectorul Pădurii"],
     ["Întreabă ocolul silvic sau Garda Forestieră din " + (a.uat ? "județul " + a.uat.judet : "județ") + ".", null, null]].forEach(function (s) {
      var li = el("li", null, s[0] + " ");
      if (s[1]) { var x = el("a", null, s[2]); x.href = s[1]; x.target = "_blank"; x.rel = "noopener"; li.appendChild(x); }
      ol.appendChild(li);
    });
    box.appendChild(ol);
    return box;
  }

  /* ---------- înainte și după: clipește, glisează sau una lângă alta ---------- */
  var REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function outline(a) {
    if (!a.chip_bbox || !a.geometry) return null;
    var NS = "http://www.w3.org/2000/svg", cb = a.chip_bbox, w = cb[2] - cb[0], h = cb[3] - cb[1], d = "";
    var polys = a.geometry.type === "MultiPolygon" ? a.geometry.coordinates : [a.geometry.coordinates];
    polys.forEach(function (poly) {
      poly.forEach(function (ring) {
        ring.forEach(function (c, i) { d += (i ? "L" : "M") + (1000 * (c[0] - cb[0]) / w).toFixed(1) + " " + (1000 * (cb[3] - c[1]) / h).toFixed(1); });
        d += "Z";
      });
    });
    var svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 1000 1000"); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("class", "outline"); svg.setAttribute("aria-hidden", "true");
    ["halo", "line"].forEach(function (c) { var p = document.createElementNS(NS, "path"); p.setAttribute("d", d); p.setAttribute("class", c); svg.appendChild(p); });
    return svg;
  }
  function compare(a, big) {
    var wrap = el("div", "cmp" + (big ? " big" : "")), b = a.img_before, f = a.img_after;
    if (!f) { wrap.appendChild(el("p", "hint", "Nu avem încă o imagine curată a zonei.")); return wrap; }
    var mode = b ? (REDUCED ? "swipe" : "blink") : "after", showLine = true;
    var top = el("div", "cmp-top"), seg = el("div", "seg small"), stage = el("div", "cmp-stage"), hint = el("p", "hint");
    seg.setAttribute("role", "group"); seg.setAttribute("aria-label", "Cum compari pozele");
    if (b) {
      [["blink", "Clipește"], ["swipe", "Glisează"], ["side", "Una lângă alta"]].forEach(function (m) {
        var x = el("button", null, m[1]); x.type = "button"; x.dataset.mode = m[0]; seg.appendChild(x);
      });
      top.appendChild(seg);
    }
    var ln = el("button", "mini", "Contur"); ln.type = "button"; ln.setAttribute("aria-pressed", "true"); top.appendChild(ln);
    var pz = el("button", "mini", "Pauză"), paused = false, onPause = null; pz.type = "button"; pz.setAttribute("aria-pressed", "false"); pz.hidden = true; top.appendChild(pz);
    pz.addEventListener("click", function () { if (onPause) onPause(!paused); });
    if (!big) { var zm = el("button", "mini", "Mărește"); zm.type = "button"; zm.addEventListener("click", function () { openModal(a); }); top.appendChild(zm); }
    wrap.appendChild(top); wrap.appendChild(stage); wrap.appendChild(hint);

    function pic(info, cls, alt) { var i = el("img", cls); i.src = "img/" + info.file; i.alt = alt; return i; }
    function frame(main) {
      var box = el("div", "compare");
      main.addEventListener("load", function () { box.style.aspectRatio = main.naturalWidth + " / " + main.naturalHeight; });
      return box;
    }
    function addLine(box) { var o = showLine && outline(a); if (o) box.appendChild(o); }
    function cell(k, date) { var c = el("span", "cell"); c.appendChild(el("span", "k", k)); c.appendChild(el("span", "v", zi(date))); return c; }
    function render() {
      stage.replaceChildren();
      onPause = null; pz.hidden = mode !== "blink";
      Array.prototype.forEach.call(seg.children, function (x) { x.setAttribute("aria-pressed", String(x.dataset.mode === mode)); });
      if (mode === "side") {
        var g = el("div", "side");
        [[b, "Înainte"], [f, "După"]].forEach(function (p) {
          var fig = el("figure"), i = pic(p[0], null, p[1] + ", " + zi(p[0].date)), box = frame(i), cap = el("figcaption");
          box.appendChild(i); addLine(box); fig.appendChild(box);
          cap.appendChild(el("span", "k", p[1])); cap.appendChild(el("span", "v", zi(p[0].date, true)));
          fig.appendChild(cap); g.appendChild(fig);
        });
        stage.appendChild(g);
        hint.textContent = "Stânga: înainte. Dreapta: după. Conturul portocaliu e zona găsită.";
        return;
      }
      var i2 = pic(f, "after", "După, " + zi(f.date)), box = frame(i2), strip = el("div", "strip");
      if (mode === "after") {
        var only = cell("După", f.date);
        i2.style.clipPath = "none"; box.appendChild(i2); addLine(box);
        only.classList.add("on"); strip.appendChild(only); box.appendChild(strip);
        hint.textContent = "Nu avem o imagine curată de dinainte.";
        stage.appendChild(box);
        return;
      }
      var cBefore = cell("Înainte", b.date), cAfter = cell("După", f.date);
      box.appendChild(pic(b, null, "Înainte, " + zi(b.date))); box.appendChild(i2); addLine(box);
      strip.appendChild(cBefore); strip.appendChild(cAfter); box.appendChild(strip);
      if (mode === "swipe") {
        var bar = el("div", "bar"); box.appendChild(bar);
        var rg = el("input"); rg.type = "range"; rg.min = 0; rg.max = 100; rg.value = 50; rg.setAttribute("aria-label", "Compară înainte și după");
        rg.addEventListener("input", function () { i2.style.clipPath = "inset(0 0 0 " + rg.value + "%)"; bar.style.left = rg.value + "%"; });
        box.appendChild(rg);
        hint.textContent = "Trage peste imagine: stânga e înainte, dreapta e după. Conturul portocaliu e zona găsită.";
      } else {
        i2.style.clipPath = "none";
        var st = el("span", "cell state"), on = false, seen = true, io = null;
        strip.appendChild(st);
        var show = function () {
          i2.style.opacity = on ? "1" : "0";
          cAfter.classList.toggle("on", on); cBefore.classList.toggle("on", !on);
        };
        var setPaused = function (p) {
          paused = p;
          st.textContent = paused ? "oprită" : "";
          box.setAttribute("aria-pressed", String(paused));
          pz.setAttribute("aria-pressed", String(paused));
        };
        onPause = setPaused;
        on = true; show(); setPaused(paused);
        if ("IntersectionObserver" in window) { io = new IntersectionObserver(function (es) { seen = es[0].isIntersecting; }); io.observe(box); }
        var t = setInterval(function () {
          if (!document.body.contains(box)) { clearInterval(t); if (io) io.disconnect(); return; }
          if (!paused && seen) { on = !on; show(); }
        }, 1000);
        box.classList.add("clickable");
        box.tabIndex = 0; box.setAttribute("role", "button");
        box.setAttribute("aria-label", "Pozele înainte și după, care clipesc. Apasă ca să oprești sau să pornești clipirea.");
        box.addEventListener("click", function () { setPaused(!paused); });
        box.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPaused(!paused); } });
        hint.textContent = "Poza trece singură de la înainte la după, o dată pe secundă. Apasă pe ea sau pe „Pauză” ca s-o oprești. Conturul portocaliu e zona găsită.";
      }
      stage.appendChild(box);
    }
    seg.addEventListener("click", function (e) { var x = e.target.closest("button"); if (x) { mode = x.dataset.mode; render(); } });
    ln.addEventListener("click", function () { showLine = !showLine; ln.setAttribute("aria-pressed", String(showLine)); render(); });
    render();
    return wrap;
  }

  /* ---------- poza mare ---------- */
  var lastFocus = null;
  function openModal(a) {
    var m = document.getElementById("modal");
    if (!m) {
      m = el("div", "modal"); m.id = "modal"; m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true"); m.setAttribute("aria-label", "Poza mare, înainte și după");
      document.body.appendChild(m);
      m.addEventListener("click", function (e) { if (e.target === m) closeModal(); });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !m.hidden) closeModal(); });
    }
    lastFocus = document.activeElement;
    m.replaceChildren();
    var card = el("div", "modal-card"), top = el("div", "modal-top"), h = headline(a);
    top.appendChild(el("h3", null, h.t + ", " + fmt(a.ha, 1) + " ha" + whereText(a)));
    var x = el("button", "mini", "Închide"); x.type = "button"; x.addEventListener("click", closeModal); top.appendChild(x);
    card.appendChild(top); card.appendChild(compare(a, true)); m.appendChild(card);
    m.hidden = false; document.body.classList.add("noscroll"); x.focus();
  }
  function closeModal() {
    var m = document.getElementById("modal");
    if (m) { m.hidden = true; m.replaceChildren(); }
    document.body.classList.remove("noscroll");
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  /* ---------- harta ---------- */
  /* semnele de pe hartă sunt pătrate, desenate o dată, în culorile din foaia de stil */
  function addIcons(m) {
    var S = 40, edge = tok("--color-paper-3").css, prot = tok("--color-protected").css;
    function img(draw) { var c = document.createElement("canvas"); c.width = c.height = S; var x = c.getContext("2d"); draw(x); return x.getImageData(0, 0, S, S); }
    ICONS.forEach(function (c) {
      var fill = confColor(c[0]);
      if (c[1] === "un") {
        m.addImage("k-un", img(function (x) {
          x.strokeStyle = edge; x.lineWidth = 7; x.strokeRect(9, 9, S - 18, S - 18);
          x.setLineDash([5, 4]); x.strokeStyle = fill; x.lineWidth = 3; x.strokeRect(9, 9, S - 18, S - 18);
        }), { pixelRatio: 2 });
        return;
      }
      m.addImage("k-" + c[1], img(function (x) { x.fillStyle = edge; x.fillRect(4, 4, S - 8, S - 8); x.fillStyle = fill; x.fillRect(8, 8, S - 16, S - 16); }), { pixelRatio: 2 });
    });
    /* în arie protejată: chenar albastru, gros, în jurul aceluiași pătrat */
    var P = 52;
    function imgP(draw) { var c = document.createElement("canvas"); c.width = c.height = P; var x = c.getContext("2d"); draw(x); return x.getImageData(0, 0, P, P); }
    /* stil: "plin", "gol" (contur) sau "punctat" */
    function prot_(nume, fill, stil) {
      m.addImage(nume, imgP(function (x) {
        x.fillStyle = edge; x.fillRect(0, 0, P, P);
        x.fillStyle = prot; x.fillRect(3, 3, P - 6, P - 6);
        x.fillStyle = edge; x.fillRect(10, 10, P - 20, P - 20);
        if (stil === "punctat") { x.setLineDash([5, 4]); x.strokeStyle = fill; x.lineWidth = 3; x.strokeRect(15, 15, P - 30, P - 30); }
        else if (stil === "gol") { x.strokeStyle = fill; x.lineWidth = 4; x.strokeRect(16, 16, P - 32, P - 32); }
        else { x.fillStyle = fill; x.fillRect(14, 14, P - 28, P - 28); }
      }), { pixelRatio: 2 });
    }
    ICONS.forEach(function (c) { prot_("k-" + c[1] + "-p", confColor(c[0]), c[1] === "un" ? "punctat" : "plin"); });
    AUT_ORD.forEach(function (k) { prot_("ka-" + k + "-p", autColor(k), k === "nev" ? "punctat" : k === "probabil" ? "gol" : "plin"); });
    /* aceleași pătrate, dar în culorile stărilor de autorizație */
    AUT_ORD.forEach(function (k) {
      var fill = autColor(k);
      if (k === "probabil") {
        m.addImage("ka-probabil", img(function (x) {
          x.fillStyle = edge; x.fillRect(4, 4, S - 8, S - 8);
          x.strokeStyle = fill; x.lineWidth = 5; x.strokeRect(10.5, 10.5, S - 21, S - 21);
        }), { pixelRatio: 2 });
        return;
      }
      if (k === "nev") {
        m.addImage("ka-nev", img(function (x) {
          x.strokeStyle = edge; x.lineWidth = 7; x.strokeRect(9, 9, S - 18, S - 18);
          x.setLineDash([5, 4]); x.strokeStyle = fill; x.lineWidth = 3; x.strokeRect(9, 9, S - 18, S - 18);
        }), { pixelRatio: 2 });
      } else {
        m.addImage("ka-" + k, img(function (x) { x.fillStyle = edge; x.fillRect(4, 4, S - 8, S - 8); x.fillStyle = fill; x.fillRect(8, 8, S - 16, S - 16); }), { pixelRatio: 2 });
      }
    });
    m.addImage("k-sel", img(function (x) {
      x.strokeStyle = edge; x.lineWidth = 8; x.strokeRect(6, 6, S - 12, S - 12);
      x.strokeStyle = tok("--color-ink").css; x.lineWidth = 3; x.strokeRect(6, 6, S - 12, S - 12);
    }), { pixelRatio: 2 });
    m.addImage("k-fire", img(function (x) {
      x.lineCap = "square";
      [[edge, 9], [tok("--color-fire").css, 4]].forEach(function (p) {
        x.strokeStyle = p[0]; x.lineWidth = p[1]; x.beginPath();
        x.moveTo(12, 12); x.lineTo(S - 12, S - 12); x.moveTo(S - 12, 12); x.lineTo(12, S - 12); x.stroke();
      });
    }), { pixelRatio: 2 });
  }
  var PT_IMAGE = ["case", ["get", "p"],
    ["match", ["get", "c"], "ridicată", "k-hi-p", "medie", "k-mid-p", "scăzută", "k-lo-p", "k-un-p"],
    ["match", ["get", "c"], "ridicată", "k-hi", "medie", "k-mid", "scăzută", "k-lo", "k-un"]];
  function ptImageAut() {
    function m(suf) {
      var e = ["match", ["get", "au"]];
      AUT_ORD.forEach(function (k) { if (k !== "nev") { e.push(k, "ka-" + k + suf); } });
      e.push("ka-nev" + suf); return e;
    }
    return ["case", ["get", "p"], m("-p"), m("")];
  }
  function ptImage() { return peAut() ? ptImageAut() : PT_IMAGE; }
  function zoneText(p) { return [fmt(p.ha, 1) + " ha", p.loc || p.county || "", ziScurt(p.d), p.p ? "în arie protejată" : ""].filter(Boolean).join(", "); }

  function initMap(hj, counties) {
    var ink = tok("--color-ink").css;
    map = new maplibregl.Map({
      container: "map",
      bounds: [[20.2, 43.55], [29.8, 48.3]],
      fitBoundsOptions: { padding: 20 },
      maxZoom: 16, minZoom: 5, maxBounds: MAXB,
      cooperativeGestures: false, /* un deget mișcă harta; pagina se derulează din afara ei */
      attributionControl: { compact: true },
      style: {
        version: 8,
        glyphs: GLYPHS,
        sources: {
          sat: { type: "raster", tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg"], tileSize: 256, maxzoom: 15,
                 attribution: '<a href="https://s2maps.eu" target="_blank">Sentinel-2 cloudless</a> de EOX IT Services GmbH (date Copernicus Sentinel modificate)' },
          osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
                 attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>' },
          hd: { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 18,
                attribution: 'Imagini: Esri, Maxar, Earthstar Geographics (pot fi mai vechi)' }
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": tok("--color-map").css } },
          { id: "sat", type: "raster", source: "sat", paint: { "raster-saturation": -0.2, "raster-contrast": 0.1 } },
          { id: "hd", type: "raster", source: "hd", layout: { visibility: "none" }, paint: { "raster-saturation": -0.2, "raster-contrast": 0.1 } },
          { id: "osm", type: "raster", source: "osm", layout: { visibility: "none" } }
        ]
      }
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    pickSatellite();
    map.on("load", function () {
      addIcons(map);
      if (hj) {
        hansen = { meta: hj };
        map.addSource("hansen", { type: "image", url: "data/static/hansen.webp", coordinates: [[hj.west, hj.north], [hj.east, hj.north], [hj.east, hj.south], [hj.west, hj.south]] });
        /* pierderile Hansen pornesc ascunse: le arată doar cine bifează stratul sau alege anii */
        map.addLayer({ id: "hansen", type: "raster", source: "hansen", maxzoom: 12, layout: { visibility: document.getElementById("lyr-loss").checked ? "visible" : "none" }, paint: { "raster-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.85, 10, 0.7, 12, 0.35], "raster-resampling": "nearest", "raster-fade-duration": 0 } });
        loadHansen();
      }
      if (counties) {
        var none = ["in", ["get", "n"], ["literal", ctyList()]];
        map.addSource("counties", { type: "geojson", data: counties });
        map.addLayer({ id: "cty-hit", type: "fill", source: "counties", paint: { "fill-color": ink, "fill-opacity": 0 } });
        map.addLayer({ id: "cty-sel-fill", type: "fill", source: "counties", filter: none, paint: { "fill-color": ink, "fill-opacity": 0.07 } });
        map.addLayer({ id: "counties", type: "line", source: "counties", paint: { "line-color": ink, "line-opacity": 0.35, "line-width": 0.8 } });
        map.addLayer({ id: "cty-hover", type: "line", source: "counties", filter: ["==", ["get", "n"], ""], paint: { "line-color": ink, "line-opacity": 0.7, "line-width": 1.4 } });
        map.addLayer({ id: "cty-sel-halo", type: "line", source: "counties", filter: none, paint: { "line-color": tok("--color-paper-3").css, "line-width": 5, "line-opacity": 0.6 } });
        map.addLayer({ id: "cty-sel-line", type: "line", source: "counties", filter: none, paint: { "line-color": ink, "line-width": 2.2 } });
      }
      map.addSource("firms", { type: "geojson", data: FIRMS_FC || { type: "FeatureCollection", features: [] } });
      map.addLayer({ id: "firms", type: "symbol", source: "firms", layout: {
        "icon-image": "k-fire", "icon-allow-overlap": true, "icon-ignore-placement": true,
        "icon-size": ["interpolate", ["linear"], ["zoom"], 5, 0.55, 9, 0.8, 13, 1.15] } });
      map.addSource("alerts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("points", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("sel", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      var color = culoareZone();
      map.addLayer({ id: "a-fill", type: "fill", source: "alerts", minzoom: 9, paint: { "fill-color": color, "fill-opacity": 0.28 } });
      map.addLayer({ id: "a-line-p", type: "line", source: "alerts", minzoom: 9, filter: ["==", ["get", "p"], true],
        paint: { "line-color": tok("--color-protected").css, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 4, 14, 7] } });
      map.addLayer({ id: "a-line", type: "line", source: "alerts", minzoom: 9, paint: { "line-color": color, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.2, 14, 2.6] } });
      map.addLayer({ id: "a-pt", type: "symbol", source: "points", maxzoom: 12.5, layout: {
        "icon-image": ptImage(), "icon-allow-overlap": true, "icon-ignore-placement": true,
        "icon-size": ["interpolate", ["linear"], ["sqrt", ["get", "ha"]], 1, 0.7, 4, 1.1, 12, 2],
        /* cele din arii protejate deasupra; între ele, cele mici peste cele mari */
        "symbol-sort-key": ["+", ["-", ["get", "ha"]], ["case", ["get", "p"], 100000, 0]] } });
      map.addLayer({ id: "sel-halo", type: "line", source: "sel", paint: { "line-color": tok("--color-paper-3").css, "line-width": 6 } });
      map.addLayer({ id: "sel-line", type: "line", source: "sel", paint: { "line-color": ink, "line-width": 2.4 } });
      map.addLayer({ id: "sel-pt", type: "symbol", source: "sel", filter: ["==", ["geometry-type"], "Point"], maxzoom: 12.5, layout: {
        "icon-image": "k-sel", "icon-size": 1.5, "icon-allow-overlap": true, "icon-ignore-placement": true } });

      var pop = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
      ["a-pt", "a-fill"].forEach(function (id) {
        map.on("mouseenter", id, function () { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", id, function () { map.getCanvas().style.cursor = ""; pop.remove(); });
        map.on("mousemove", id, function (e) { pop.setLngLat(e.lngLat).setText(zoneText(e.features[0].properties)).addTo(map); });
        map.on("click", id, function (e) { var a = DATA.alerts.find(function (x) { return x.id === e.features[0].properties.id; }); if (a) select(a, false, NARROW.matches); });
      });
      map.on("mouseenter", "firms", function () { map.getCanvas().style.cursor = "help"; });
      map.on("mouseleave", "firms", function () { map.getCanvas().style.cursor = ""; pop.remove(); });
      map.on("mousemove", "firms", function (e) {
        var p = e.features[0].properties;
        pop.setLngLat(e.lngLat).setText("Foc văzut de sateliții NASA, " + zi(p.d) + (p.t != null && p.t !== "" ? ", ora " + hhmm(p.t) + " UTC" : "") + (p.s ? " (" + p.s + ")" : "")).addTo(map);
      });
      document.getElementById("lyr-firms").addEventListener("change", function (e) { setVis("firms", e.target.checked); });
      if (!FIRMS_FC || !FIRMS_FC.features || !FIRMS_FC.features.length) { document.getElementById("tg-firms").hidden = true; document.getElementById("lg-firms").hidden = true; }
      setCuloare(state.culoare, true);
      if (counties) countyEvents();
      /* conturul țării și numele localităților vin după, ca lista să nu aștepte după ele */
      Promise.all([getJSON("data/static/romania.geojson").catch(function () { return null; }),
                   getJSON("data/static/places.json").catch(function () { return null; })]).then(function (r) {
        RO_FC = r[0];
        addContour(map);
        if (map2 && map2.loaded()) addContour(map2);
        if (r[1] && r[1].p) addPlaces(map, r[1].p);
        paintForBase();
      });
      probe("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/7/45/72").then(function (ok) { if (!ok) unavailable("hd"); });
      probe("https://tile.openstreetmap.org/7/72/45.png").then(function (ok) { if (!ok) unavailable("osm"); });
      updateMapData();
      updateSelection();
    });
  }

  /* ---------- județele pe hartă: trecut cu mouse-ul arată numele și câte zone are, clic îl alege sau îl scoate ---------- */
  function countyEvents() {
    var cpop = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 14 }), hov = "", txt = "";
    function onAlert(pt) {
      var ls = ["a-pt", "a-fill", "firms"].filter(function (l) { return map.getLayer(l); });
      return map.queryRenderedFeatures(pt, { layers: ls }).length > 0;
    }
    function clear() { if (hov) { hov = ""; map.setFilter("cty-hover", ["==", ["get", "n"], ""]); } cpop.remove(); }
    map.on("mousemove", "cty-hit", function (e) {
      if (onAlert(e.point)) { clear(); return; }
      var n = e.features[0].properties.n;
      map.getCanvas().style.cursor = "pointer";
      if (n !== hov) {
        hov = n; map.setFilter("cty-hover", ["==", ["get", "n"], n]);
        var c = DATA.alerts.filter(function (a) { return inPeriod(a) && state.conf[a.incredere] && inArii(a) && countyOf(a) === n; }).length;
        txt = n + ": " + (c ? fmt(c) + " " + (c === 1 ? "zonă" : de(c) + "zone") : "nicio zonă") + (state.cty[n] ? " (ales)" : "");
      }
      var extra = "";
      if (map.getLayer("arii-fill") && map.getLayoutProperty("arii-fill", "visibility") !== "none") {
        var seen = {}, nm = map.queryRenderedFeatures(e.point, { layers: ["arii-fill"] }).map(function (f) { return upFirst(arieName(f.properties)); })
          .filter(function (x) { if (seen[x]) return false; seen[x] = 1; return true; });
        if (nm.length) extra = " · " + nm.slice(0, 2).join("; ") + (nm.length > 2 ? " și încă " + (nm.length - 2) : "");
      }
      cpop.setLngLat(e.lngLat).setText(txt + extra).addTo(map);
    });
    map.on("mouseleave", "cty-hit", function () { map.getCanvas().style.cursor = ""; clear(); });
    map.on("click", function (e) {
      if (onAlert(e.point) || !map.getLayer("cty-hit")) return;
      var f = map.queryRenderedFeatures(e.point, { layers: ["cty-hit"] })[0];
      if (f) { hov = ""; toggleCounty(f.properties.n, true); }
    });
  }
  function bboxOf(g) {
    var b = [180, 90, -180, -90];
    (function walk(c) { if (typeof c[0] === "number") { b[0] = Math.min(b[0], c[0]); b[1] = Math.min(b[1], c[1]); b[2] = Math.max(b[2], c[0]); b[3] = Math.max(b[3], c[1]); } else c.forEach(walk); })(g.coordinates);
    return b;
  }
  function initCounties(fc) {
    var pick = document.getElementById("cty-pick");
    if (!pick) return;
    if (!fc || !fc.features) { document.getElementById("cty-block").hidden = true; return; }
    fc.features.forEach(function (f) { COUNTY_BB[f.properties.n] = bboxOf(f.geometry); });
    Object.keys(COUNTY_BB).sort(function (x, y) { return x.localeCompare(y, "ro"); }).forEach(function (n) { var o = el("option", null, n); o.value = n; pick.appendChild(o); });
    pick.addEventListener("change", function () { if (pick.value) toggleCounty(pick.value, true); });
    renderCounties();
  }
  function renderCounties() {
    var box = document.getElementById("ctys"), pick = document.getElementById("cty-pick"), k = ctyList();
    if (!box || !pick) return;
    box.replaceChildren();
    k.forEach(function (n) {
      var b = el("button", "chip cty"); b.type = "button"; b.setAttribute("aria-pressed", "true"); b.setAttribute("aria-label", "Scoate " + n);
      b.appendChild(el("span", null, n)); b.appendChild(el("span", "x", "×"));
      b.addEventListener("click", function () { toggleCounty(n, false); });
      box.appendChild(b);
    });
    if (k.length) { var all = el("button", "more", "Toată țara"); all.type = "button"; all.addEventListener("click", clearCounties); box.appendChild(all); }
    box.hidden = !k.length;
    pick.options[0].textContent = k.length ? "Adaugă alt județ" : "Toată țara";
    Array.prototype.forEach.call(pick.options, function (o) { if (o.value) o.disabled = !!state.cty[o.value]; });
    pick.value = "";
    document.getElementById("cty-hint").hidden = !!k.length;
  }
  function toggleCounty(n, fly) {
    if (state.cty[n]) delete state.cty[n]; else state.cty[n] = true;
    state.shown = 40;
    if (state.sel) unselect();
    renderCounties(); renderAll(); updateCountyLayers();
    if (fly && state.cty[n]) fitCounties();
  }
  function clearCounties() { state.cty = {}; state.shown = 40; renderCounties(); renderAll(); updateCountyLayers(); }
  function updateCountyLayers() {
    if (!map || !map.getLayer) return;
    var f = ["in", ["get", "n"], ["literal", ctyList()]];
    ["cty-sel-fill", "cty-sel-halo", "cty-sel-line"].forEach(function (id) { if (map.getLayer(id)) map.setFilter(id, f); });
  }
  function fitCounties() {
    var k = ctyList(), b = [180, 90, -180, -90];
    if (!map || !k.length) return;
    k.forEach(function (n) { var c = COUNTY_BB[n]; if (c) b = [Math.min(b[0], c[0]), Math.min(b[1], c[1]), Math.max(b[2], c[2]), Math.max(b[3], c[3])]; });
    if (b[0] > b[2]) return;
    map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: NARROW.matches ? 24 : 60, maxZoom: 10, duration: REDUCED ? 0 : 800 });
  }

  /* ---------- conturul României și numele localităților (GeoNames), fără servicii din afară ---------- */
  function addContour(m, light) {
    if (!RO_FC || !m || !m.getStyle || m.getSource("ro")) return;
    var before = m.getLayer("firms") ? "firms" : m.getLayer("a-fill") ? "a-fill" : undefined;
    m.addSource("ro", { type: "geojson", data: RO_FC });
    m.addLayer({ id: "ro-halo", type: "line", source: "ro", paint: { "line-color": tok(light ? "--color-ink" : "--color-paper-3").css, "line-width": 4.5, "line-opacity": 0.5 } }, before);
    m.addLayer({ id: "ro-line", type: "line", source: "ro", paint: { "line-color": tok(light ? "--color-paper-3" : "--color-ink").css, "line-width": 1.6, "line-opacity": 0.9 } }, before);
  }
  function addPlaces(m, pts) {
    if (m.getSource("places")) return;
    m.addSource("places", { type: "geojson", attribution: 'Nume: <a href="https://www.geonames.org" target="_blank">GeoNames</a>',
      data: { type: "FeatureCollection", features: pts.map(function (p) { return { type: "Feature", geometry: { type: "Point", coordinates: [p[0], p[1]] }, properties: { n: p[2], r: p[3] } }; }) } });
    var ink = tok("--color-ink").css, ink2 = tok("--color-ink-2").css, mut = tok("--color-muted").css, halo = tok("--color-paper-3").css;
    function z(a, b, c, d) { return ["interpolate", ["linear"], ["zoom"], a, b, c, d]; }
    [/* id, de la zoom, ce ranguri, literă, mărime, culoare */
      ["pl-5", 11, ["==", ["get", "r"], 5], "noto-regular", z(11, 10.5, 14, 12), mut],
      ["pl-4", 9.5, ["==", ["get", "r"], 4], "noto-regular", z(9.5, 11, 13, 12.5), ink2],
      ["pl-3", 8, ["==", ["get", "r"], 3], "noto-regular", z(8, 11, 11, 13), ink2],
      ["pl-2", 7, ["==", ["get", "r"], 2], "noto-medium", z(7, 11.5, 10, 13.5), ink],
      ["pl-01", 0, ["<=", ["get", "r"], 1], "noto-medium", ["interpolate", ["linear"], ["zoom"], 5, ["match", ["get", "r"], 0, 13, 11.5], 9, ["match", ["get", "r"], 0, 16, 14]], ink]
    ].forEach(function (s) {
      m.addLayer({ id: s[0], type: "symbol", source: "places", minzoom: s[1], filter: s[2],
        layout: { "text-field": ["get", "n"], "text-font": [s[3]], "text-size": s[4], "text-max-width": 12, "text-padding": 3,
                  "symbol-sort-key": ["get", "r"], visibility: BASE === "osm" ? "none" : "visible" },
        paint: { "text-color": s[5], "text-halo-color": halo, "text-halo-width": 1.4, "text-halo-blur": 0.4 } }, m.getLayer("firms") ? "firms" : undefined);
    });
  }

  function pickSatellite() {
    /* cea mai nouă hartă Sentinel-2 cloudless care răspunde */
    var years = ["2024", "2023", "2022", "2021"], i = 0;
    function tryNext() {
      if (i >= years.length) { unavailable("sat"); return; }
      var y = years[i++], img = new Image();
      img.onload = function () {
        if (y === "2023") return;
        var src = map.getSource("sat");
        if (src && src.setTiles) src.setTiles(["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-" + y + "_3857/default/g/{z}/{y}/{x}.jpg"]);
      };
      img.onerror = tryNext;
      img.src = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-" + y + "_3857/default/g/7/45/72.jpg";
    }
    tryNext();
  }

  function alertsFC(v) {
    return { type: "FeatureCollection", features: v.map(function (a) {
      return { type: "Feature", geometry: a.geometry, properties: { id: a.id, c: a.incredere, au: autStare(a), ha: a.ha, d: a.first_seen, county: a.county, loc: placeName(a), p: isProt(a) } };
    }) };
  }
  function pointsFC(v) {
    return { type: "FeatureCollection", features: v.map(function (a) {
      return { type: "Feature", geometry: { type: "Point", coordinates: [a.lon, a.lat] }, properties: { id: a.id, c: a.incredere, au: autStare(a), ha: a.ha, d: a.first_seen, county: a.county, loc: placeName(a), p: isProt(a) } };
    }).sort(function (x, y) { return y.properties.ha - x.properties.ha; }) };
  }
  /* ---------- după ce colorăm zonele: autorizație sau încredere ---------- */
  function setCuloare(mod, silent) {
    state.culoare = mod;
    Array.prototype.forEach.call(document.querySelectorAll("#culoare button"), function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.culoare === mod));
    });
    [map, map2].forEach(function (m) {
      if (!m || !m.getLayer || !m.getLayer("a-fill")) return;
      var c = culoareZone();
      m.setPaintProperty("a-fill", "fill-color", c);
      if (m.getLayer("a-line")) m.setPaintProperty("a-line", "line-color", c);
      if (m.getLayer("a-line-p")) m.setPaintProperty("a-line-p", "line-color", c);
      if (m.getLayer("a-pt")) m.setLayoutProperty("a-pt", "icon-image", ptImage());
    });
    document.getElementById("lg-conf").hidden = peAut();
    document.getElementById("lg-aut").hidden = !peAut();
    if (!silent) renderAll();
  }

  function updateMapData() {
    var v = visible(), s = periodStart();
    if (map && map.getLayer && map.getLayer("firms") && s) map.setFilter("firms", ["all", [">=", ["get", "d"], s], ["<=", ["get", "d"], DATA.data_until]]);
    [map, map2].forEach(function (m) {
      if (!m || !m.getSource || !m.getSource("alerts")) return;
      m.getSource("alerts").setData(alertsFC(v));
      m.getSource("points").setData(pointsFC(v));
    });
  }

  /* ---------- harta normală alături, mișcată odată cu prima ---------- */
  var map2 = null, syncing = false;
  function sync(a, b) { b.jumpTo({ center: a.getCenter(), zoom: a.getZoom(), bearing: a.getBearing(), pitch: a.getPitch() }); }
  function toggleSplit(on) {
    document.querySelector(".mapwrap").classList.toggle("split", on);
    document.getElementById("map2").hidden = !on;
    document.getElementById("splitbtn").setAttribute("aria-pressed", String(on));
    document.getElementById("lyr-split").checked = on;
    if (on && !map2) initMap2();
    setTimeout(function () { if (!map) return; map.resize(); if (map2) { map2.resize(); sync(map, map2); } }, 60);
  }
  function initMap2() {
    map2 = new maplibregl.Map({
      container: "map2", center: map.getCenter(), zoom: map.getZoom(), maxZoom: 18, minZoom: 5, maxBounds: MAXB,
      attributionControl: { compact: true },
      style: { version: 8, sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>' } },
        layers: [{ id: "osm", type: "raster", source: "osm" }] }
    });
    map2.on("load", function () {
      var color = culoareZone(), dark = tok("--color-paper-3").css;
      addIcons(map2);
      map2.addSource("alerts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addSource("points", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addSource("sel", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addLayer({ id: "a-fill", type: "fill", source: "alerts", minzoom: 9, paint: { "fill-color": color, "fill-opacity": 0.18 } });
      map2.addLayer({ id: "a-line", type: "line", source: "alerts", minzoom: 9, paint: { "line-color": color, "line-width": 2.4 } });
      map2.addLayer({ id: "a-pt", type: "symbol", source: "points", maxzoom: 12.5, layout: { "icon-image": ptImage(), "icon-size": 0.9, "icon-allow-overlap": true, "icon-ignore-placement": true } });
      map2.addLayer({ id: "sel-line", type: "line", source: "sel", paint: { "line-color": dark, "line-width": 3 } });
      addContour(map2, true);
      ["a-pt", "a-fill"].forEach(function (id) {
        map2.on("mouseenter", id, function () { map2.getCanvas().style.cursor = "pointer"; });
        map2.on("mouseleave", id, function () { map2.getCanvas().style.cursor = ""; });
        map2.on("click", id, function (e) { var a = DATA.alerts.find(function (x) { return x.id === e.features[0].properties.id; }); if (a) select(a, false, NARROW.matches); });
      });
      updateMapData();
      updateSelection();
    });
    map.on("move", function () { if (!syncing && map2) { syncing = true; sync(map, map2); syncing = false; } });
    map2.on("move", function () { if (!syncing) { syncing = true; sync(map2, map); syncing = false; } });
  }

  function updateSelection() {
    var a = state.sel;
    var fc = { type: "FeatureCollection", features: a ? [
      { type: "Feature", geometry: a.geometry, properties: {} },
      { type: "Feature", geometry: { type: "Point", coordinates: [a.lon, a.lat] }, properties: {} }
    ] : [] };
    [map, map2].forEach(function (m) { if (m && m.getSource && m.getSource("sel")) m.getSource("sel").setData(fc); });
    if (map && map.getSource && map.getSource("sel")) showChip(a);
  }

  /* ---------- stratul Hansen: decodăm imaginea și o colorăm după anii aleși ---------- */
  var HSRC = null, HW = 0, HH = 0, lastURL = null;
  function loadHansen() {
    var img = new Image();
    img.onload = function () {
      var c = document.createElement("canvas"); c.width = HW = img.width; c.height = HH = img.height;
      var x = c.getContext("2d", { willReadFrequently: true });
      x.drawImage(img, 0, 0);
      HSRC = x.getImageData(0, 0, HW, HH).data;
      paintForest();
      paintHansen();
    };
    img.src = "data/static/hansen.webp";
  }
  function paintForest() {
    if (!HSRC || !hansen) return;
    var lo = tok("--color-forest-lo").rgb, hi = tok("--color-forest-hi").rgb;
    var cv = document.createElement("canvas"); cv.width = HW; cv.height = HH;
    var ctx = cv.getContext("2d"), im = ctx.createImageData(HW, HH), D = im.data;
    for (var i = 0; i < HSRC.length; i += 4) {
      var g = HSRC[i + 1];
      if (g > 0) {
        var t = g / 255;
        D[i] = lo[0] + (hi[0] - lo[0]) * t; D[i + 1] = lo[1] + (hi[1] - lo[1]) * t; D[i + 2] = lo[2] + (hi[2] - lo[2]) * t; D[i + 3] = 120 + 135 * t;
      }
    }
    ctx.putImageData(im, 0, 0);
    cv.toBlob(function (blob) {
      if (!blob) return;
      var hj = hansen.meta, coords = [[hj.west, hj.north], [hj.east, hj.north], [hj.east, hj.south], [hj.west, hj.south]];
      map.addSource("forest", { type: "image", url: URL.createObjectURL(blob), coordinates: coords });
      map.addLayer({ id: "forest", type: "raster", source: "forest", paint: { "raster-opacity": ["interpolate", ["linear"], ["zoom"], 8, 0.95, 12, 0.55, 14, 0.3], "raster-resampling": "linear", "raster-fade-duration": 0 } }, "sat");
    }, "image/png");
  }
  function paintHansen() {
    if (!HSRC || !map.getSource("hansen")) return;
    var a0 = tok("--color-loss-old").rgb, a1 = tok("--color-loss-new").rgb, col = [];
    for (var y = 0; y <= 25; y++) {
      var t = Math.max(0, (y - 1) / 24);
      col[y] = [a0[0] + (a1[0] - a0[0]) * t, a0[1] + (a1[1] - a0[1]) * t, a0[2] + (a1[2] - a0[2]) * t];
    }
    var cv = document.createElement("canvas"); cv.width = HW; cv.height = HH;
    var ctx = cv.getContext("2d"), im = ctx.createImageData(HW, HH), D = im.data, y0 = state.years[0], y1 = state.years[1];
    for (var i = 0; i < HSRC.length; i += 4) {
      var ry = HSRC[i], bl = HSRC[i + 2];
      if (bl > 0 && ry >= y0 && ry <= y1) {
        var c = col[ry];
        D[i] = c[0]; D[i + 1] = c[1]; D[i + 2] = c[2]; D[i + 3] = 255 * (0.45 + 0.55 * bl / 255);
      }
    }
    ctx.putImageData(im, 0, 0);
    cv.toBlob(function (blob) {
      if (!blob) return;
      var url = URL.createObjectURL(blob), hj = hansen.meta;
      map.getSource("hansen").updateImage({ url: url, coordinates: [[hj.west, hj.north], [hj.east, hj.north], [hj.east, hj.south], [hj.west, hj.south]] });
      if (lastURL) setTimeout(function (u) { URL.revokeObjectURL(u); }.bind(null, lastURL), 2000);
      lastURL = url;
    }, "image/png");
  }
})();
