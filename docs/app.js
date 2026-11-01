/* Pădurea RO: harta schimbărilor din pădure. Datele vin din data/alerts.json, refăcut zilnic de GitHub Actions. */
(function () {
  "use strict";

  var REPO = "https://github.com/iliemihai/padurea-ro";
  var CONF = [["ridicată", "hi"], ["medie", "mid"], ["scăzută", "lo"], ["de confirmat", "un"]];
  var CONF_TOKEN = { "ridicată": "--color-data-hi", "medie": "--color-data-mid", "scăzută": "--color-data-lo", "de confirmat": "--color-data-un" };
  var LUNI = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."];
  var LUNI_L = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"];

  var state = { days: 30, conf: { "ridicată": true, "medie": false, "scăzută": false, "de confirmat": false }, shown: 40, sel: null, years: [21, 25], cty: {} };
  var DATA = { alerts: [], data_until: null, generated: null }, RUNS = [], VERIF = {}, FIRMS_FC = null, map, hansen = null;
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
  function key(c) { var k = el("i", "key " + confCls(c)); k.setAttribute("aria-hidden", "true"); return k; }

  /* ---------- datele ---------- */
  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }

  Promise.all([
    getJSON("data/alerts.json").catch(function (e) { LOADERR = !/ 404$/.test(String(e && e.message)); return null; }),
    getJSON("data/runs.json").catch(function () { return []; }),
    getJSON("data/static/hansen.json").catch(function () { return null; }),
    getJSON("data/static/counties.geojson").catch(function () { return null; }),
    getJSON("data/verificari.json").catch(function () { return null; }),
    getJSON("data/firms.geojson").catch(function () { return null; })
  ]).then(function (res) {
    FIRMS_FC = res[5] || { type: "FeatureCollection", features: [] };
    if (res[0]) DATA = res[0];
    VERIF = (res[4] && res[4].zone) || {};
    RUNS = res[1] || [];
    try { initMap(res[2], res[3]); } catch (e) { mapMissing(); }
    initControls();
    initCounties(res[3]);
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
  function inPeriod(a) { var s = periodStart(); return s && a.first_seen >= s && a.first_seen <= DATA.data_until; }
  function visible() { return DATA.alerts.filter(function (a) { return inPeriod(a) && state.conf[a.incredere] && inCounty(a); }); }

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

  function daysLabel(n) { return n === 1 ? "ultima zi" : "ultimele " + n + " " + de(n) + "zile"; }
  /* de când avem date: cea mai veche fereastră analizată (istoricul crește cu fiecare rulare) */
  function coverageStart() {
    var s = null;
    (RUNS || []).forEach(function (r) { if (r && r.window && (!s || r.window[0] < s)) s = r.window[0]; });
    if (!s && DATA.window) s = DATA.window[0];
    return s;
  }
  function coverageDays() { var s = coverageStart(); return s && DATA.data_until ? Math.round((pd(DATA.data_until) - pd(s)) / 864e5) + 1 : 0; }

  /* perioada: butoanele și glisorul arată mereu același număr de zile */
  function setPeriod(n, silent) {
    state.days = Math.max(1, Math.min(3650, n | 0));
    Array.prototype.forEach.call(document.querySelectorAll("#periods button"), function (b) { b.setAttribute("aria-pressed", String(+b.dataset.days === state.days)); });
    var nd = document.getElementById("ndays");
    nd.value = Math.min(+nd.max, state.days);
    document.getElementById("ndays-v").textContent = daysLabel(state.days);
    document.getElementById("period-hint").hidden = state.days > 3;
    state.shown = 40;
    if (!silent) renderAll();
  }

  function initControls() {
    var per = document.getElementById("periods"), nd = document.getElementById("ndays");
    per.addEventListener("click", function (e) { var b = e.target.closest("button"); if (b) setPeriod(+b.dataset.days); });
    nd.addEventListener("input", function () { setPeriod(+nd.value); });
    var cov = coverageDays();
    if (cov) nd.max = String(Math.max(7, cov));
    setPeriod(state.days, true);

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
    var all = DATA.alerts.filter(function (a) { return inPeriod(a) && inCounty(a); });
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
      var s0 = periodStart(), older = DATA.alerts.filter(function (a) { return state.conf[a.incredere] && inCounty(a) && a.first_seen < s0; })
        .sort(function (a, b) { return (b.first_seen > a.first_seen) - (b.first_seen < a.first_seen); })[0];
      if (older) {
        var need = Math.round((pd(DATA.data_until) - pd(older.first_seen)) / 864e5) + 1;
        var em = el("div", "empty");
        em.appendChild(el("p", null, "Nicio zonă cu nivelurile alese" + ctyText() + " în " + daysLabel(state.days) + ". Cea mai recentă e din " + zi(older.first_seen, true) + ", în " + placeInline(older) + "."));
        var go = el("button", "more", "Arată din " + ziScurt(older.first_seen)); go.type = "button";
        go.addEventListener("click", function () { setPeriod(need); });
        em.appendChild(go); box.appendChild(em);
        return;
      }
      var hidden = DATA.alerts.filter(function (a) { return inPeriod(a) && inCounty(a); }).length;
      var msg = hidden ? "Nicio schimbare cu acest nivel de încredere" + ctyText() + " în perioada aleasă. Bifează și „scăzută” ca să le vezi pe toate." :
        "Nicio schimbare nouă" + ctyText() + " în perioada aleasă. Poate fi și din cauza norilor: pădurea acoperită de nori nu se vede. Încearcă o perioadă mai lungă.";
      if (!ctyList().length) { box.appendChild(el("p", "empty", msg)); return; }
      var ec = el("div", "empty"); ec.appendChild(el("p", null, msg));
      var wide = el("button", "more", "Arată toată țara"); wide.type = "button"; wide.addEventListener("click", clearCounties);
      ec.appendChild(wide); box.appendChild(ec);
      return;
    }
    v.slice(0, state.shown).forEach(function (a) {
      var li = el("li"), b = el("button", "row"), meta = [];
      b.type = "button";
      b.appendChild(el("span", "visually-hidden", (a.incredere === "de confirmat" ? "De confirmat" : "Încredere " + a.incredere) + ". "));
      b.appendChild(key(a.incredere));
      b.appendChild(el("span", "t", placeName(a)));
      b.appendChild(el("span", "d", ziScurt(a.first_seen)));
      b.appendChild(el("span", "p", headline(a).t));
      b.appendChild(el("span", "a", fmt(a.ha, 1) + " ha"));
      if (isVerified(a)) meta.push("verificat și din alte surse");
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
  function selectById(id, fly) {
    var a = DATA.alerts.find(function (x) { return x.id === id; });
    if (!a) return;
    if (!inPeriod(a)) setPeriod(Math.max(1, Math.round((pd(DATA.data_until) - pd(a.first_seen)) / 864e5) + 1), true);
    if (!state.conf[a.incredere]) { state.conf[a.incredere] = true; var c = document.querySelector('#conf .chip[data-conf="' + a.incredere + '"]'); if (c) c.setAttribute("aria-pressed", "true"); }
    if (!inCounty(a)) { state.cty = {}; renderCounties(); updateCountyLayers(); }
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
    var c1 = el("span", "badge"); c1.appendChild(key(a.incredere)); c1.appendChild(document.createTextNode(a.incredere === "de confirmat" ? "de confirmat" : "încredere " + a.incredere)); bd.appendChild(c1);
    if (isVerified(a)) bd.appendChild(el("span", "badge ok", "verificat și din alte surse"));
    if (a.vant) bd.appendChild(el("span", "badge", "vânt puternic"));
    d.appendChild(bd);
    d.appendChild(compare(a, false));
    if (a.img_after) d.appendChild(chipControl(a));
    if (a.text) d.appendChild(el("p", "sum", a.text));
    var act = el("div", "actions");
    function link(t, h) { var x = el("a", null, t); x.href = h; x.target = "_blank"; x.rel = "noopener"; act.appendChild(x); }
    link("Google Maps (satelit)", "https://www.google.com/maps/@?api=1&map_action=map&center=" + a.lat + "," + a.lon + "&zoom=16&basemap=satellite");
    link("OpenStreetMap", "https://www.openstreetmap.org/?mlat=" + a.lat + "&mlon=" + a.lon + "#map=15/" + a.lat + "/" + a.lon);
    link("Raportează o greșeală", REPO + "/issues/new?title=" + encodeURIComponent("Alerta " + a.id) + "&body=" + encodeURIComponent("Ce e greșit la alerta " + a.id + "?\n\n" + location.href));
    d.appendChild(act);
    var vi = verifItems(a); if (vi.length) d.appendChild(verifBlock(vi));
    d.appendChild(ownerBlock(a));
    var ev = el("ul", "ev"); (a.dovezi || []).forEach(function (x) { ev.appendChild(el("li", null, x)); });
    d.appendChild(el("p", "lbl", "De ce acest nivel de încredere"));
    d.appendChild(ev);
    var kv = el("dl", "kv");
    function row(k, v, num) { kv.appendChild(el("dt", null, k)); var dd = el("dd", num ? "num" : null); if (v instanceof Node) dd.appendChild(v); else dd.textContent = v; kv.appendChild(dd); }
    row("Intactă pe", zi(a.before_date, true), true);
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
    var S = 40, edge = tok("--color-paper-3").css;
    function img(draw) { var c = document.createElement("canvas"); c.width = c.height = S; var x = c.getContext("2d"); draw(x); return x.getImageData(0, 0, S, S); }
    CONF.forEach(function (c) {
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
  var PT_IMAGE = ["match", ["get", "c"], "ridicată", "k-hi", "medie", "k-mid", "scăzută", "k-lo", "k-un"];
  function zoneText(p) { return [fmt(p.ha, 1) + " ha", p.loc || p.county || "", ziScurt(p.d)].filter(Boolean).join(", "); }

  function initMap(hj, counties) {
    var ink = tok("--color-ink").css;
    map = new maplibregl.Map({
      container: "map",
      bounds: [[20.2, 43.55], [29.8, 48.3]],
      fitBoundsOptions: { padding: 20 },
      maxZoom: 16, minZoom: 5, maxBounds: MAXB,
      cooperativeGestures: NARROW.matches,
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
      var color = colorMatch();
      map.addLayer({ id: "a-fill", type: "fill", source: "alerts", minzoom: 9, paint: { "fill-color": color, "fill-opacity": 0.28 } });
      map.addLayer({ id: "a-line", type: "line", source: "alerts", minzoom: 9, paint: { "line-color": color, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.2, 14, 2.6] } });
      map.addLayer({ id: "a-pt", type: "symbol", source: "points", maxzoom: 12.5, layout: {
        "icon-image": PT_IMAGE, "icon-allow-overlap": true, "icon-ignore-placement": true,
        "icon-size": ["interpolate", ["linear"], ["sqrt", ["get", "ha"]], 1, 0.7, 4, 1.1, 12, 2],
        "symbol-sort-key": ["-", ["get", "ha"]] } });
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
        var c = DATA.alerts.filter(function (a) { return inPeriod(a) && state.conf[a.incredere] && countyOf(a) === n; }).length;
        txt = n + ": " + (c ? fmt(c) + " " + (c === 1 ? "zonă" : de(c) + "zone") : "nicio zonă") + (state.cty[n] ? " (ales)" : "");
      }
      cpop.setLngLat(e.lngLat).setText(txt).addTo(map);
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
      return { type: "Feature", geometry: a.geometry, properties: { id: a.id, c: a.incredere, ha: a.ha, d: a.first_seen, county: a.county, loc: placeName(a) } };
    }) };
  }
  function pointsFC(v) {
    return { type: "FeatureCollection", features: v.map(function (a) {
      return { type: "Feature", geometry: { type: "Point", coordinates: [a.lon, a.lat] }, properties: { id: a.id, c: a.incredere, ha: a.ha, d: a.first_seen, county: a.county, loc: placeName(a) } };
    }).sort(function (x, y) { return y.properties.ha - x.properties.ha; }) };
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
      var color = colorMatch(), dark = tok("--color-paper-3").css;
      addIcons(map2);
      map2.addSource("alerts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addSource("points", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addSource("sel", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addLayer({ id: "a-fill", type: "fill", source: "alerts", minzoom: 9, paint: { "fill-color": color, "fill-opacity": 0.18 } });
      map2.addLayer({ id: "a-line", type: "line", source: "alerts", minzoom: 9, paint: { "line-color": color, "line-width": 2.4 } });
      map2.addLayer({ id: "a-pt", type: "symbol", source: "points", maxzoom: 12.5, layout: { "icon-image": PT_IMAGE, "icon-size": 0.9, "icon-allow-overlap": true, "icon-ignore-placement": true } });
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
