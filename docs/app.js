/* Pădurea RO: harta schimbărilor din pădure. Datele vin din data/alerts.json, refăcut zilnic de GitHub Actions. */
(function () {
  "use strict";

  var REPO = "https://github.com/iliemihai/padurea-ro";
  var CONF = [["ridicată", "hi"], ["medie", "mid"], ["scăzută", "lo"], ["de confirmat", "un"]];
  var CONF_COLOR = { "ridicată": "#ff4d4f", "medie": "#ffb020", "scăzută": "#9fb1ba", "de confirmat": "#a99cf0" };
  var LUNI = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."];
  var LUNI_L = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"];

  var state = { days: 30, conf: { "ridicată": true, "medie": false, "scăzută": false, "de confirmat": false }, shown: 40, sel: null, years: [21, 25] };
  var DATA = { alerts: [], data_until: null, generated: null }, RUNS = [], VERIF = {}, map, hansen = null;

  /* ---------- unelte ---------- */
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function fmt(n, d) { return Number(n).toLocaleString("ro-RO", { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }); }
  function de(n) { var r = Math.round(n) % 100; return (n !== 0 && (r === 0 || r >= 20)) ? "de " : ""; }
  function pd(s) { var p = s.split("-"); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
  function iso(d) { return d.toISOString().slice(0, 10); }
  function addDays(s, k) { var d = pd(s); d.setUTCDate(d.getUTCDate() + k); return iso(d); }
  function zi(s, lung) { if (!s) return "—"; var d = pd(s); return d.getUTCDate() + " " + (lung ? LUNI_L : LUNI)[d.getUTCMonth()] + " " + d.getUTCFullYear(); }
  function ziScurt(s) { var d = pd(s); return d.getUTCDate() + " " + LUNI[d.getUTCMonth()]; }
  function confCls(c) { return c === "ridicată" ? "hi" : c === "medie" ? "mid" : c === "scăzută" ? "lo" : "un"; }

  /* ---------- datele ---------- */
  function getJSON(u) { return fetch(u, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(u + " " + r.status); return r.json(); }); }

  Promise.all([
    getJSON("data/alerts.json").catch(function () { return null; }),
    getJSON("data/runs.json").catch(function () { return []; }),
    getJSON("data/static/hansen.json").catch(function () { return null; }),
    getJSON("data/static/counties.geojson").catch(function () { return null; }),
    getJSON("data/verificari.json").catch(function () { return null; })
  ]).then(function (res) {
    if (res[0]) DATA = res[0];
    VERIF = (res[4] && res[4].zone) || {};
    RUNS = res[1] || [];
    initMap(res[2], res[3]);
    initControls();
    renderAll();
    var m = location.hash.match(/a=([\w-]+)/);
    if (m) selectById(m[1], true);
  });

  /* ---------- perioada și filtrele ---------- */
  function periodStart() { return DATA.data_until ? addDays(DATA.data_until, -(state.days - 1)) : null; }
  function inPeriod(a) { var s = periodStart(); return s && a.first_seen >= s && a.first_seen <= DATA.data_until; }
  function visible() { return DATA.alerts.filter(function (a) { return inPeriod(a) && state.conf[a.incredere]; }); }

  function daysLabel(n) { return n === 1 ? "ultima zi" : "ultimele " + n + " " + de(n) + "zile"; }

  /* perioada: butoanele și glisorul arată mereu același număr de zile */
  function setPeriod(n, silent) {
    state.days = Math.max(1, Math.min(3650, n | 0));
    Array.prototype.forEach.call(document.querySelectorAll("#periods button"), function (b) { b.setAttribute("aria-pressed", String(+b.dataset.days === state.days)); });
    var nd = document.getElementById("ndays");
    nd.value = Math.min(+nd.max, state.days);
    document.getElementById("ndays-v").textContent = daysLabel(state.days);
    state.shown = 40;
    if (!silent) renderAll();
  }

  function initControls() {
    var per = document.getElementById("periods"), nd = document.getElementById("ndays");
    per.addEventListener("click", function (e) { var b = e.target.closest("button"); if (b) setPeriod(+b.dataset.days); });
    nd.addEventListener("input", function () { setPeriod(+nd.value); });
    setPeriod(state.days, true);

    var cb = document.getElementById("conf");
    CONF.forEach(function (c) {
      var b = el("button", "chip"); b.type = "button"; b.setAttribute("aria-pressed", String(state.conf[c[0]]));
      b.appendChild(el("i", c[1])); b.appendChild(el("span", null, c[0])); b.appendChild(el("span", "n"));
      b.addEventListener("click", function () { state.conf[c[0]] = !state.conf[c[0]]; b.setAttribute("aria-pressed", String(state.conf[c[0]])); state.shown = 40; renderAll(); });
      b.dataset.conf = c[0];
      cb.appendChild(b);
    });

    var yb = document.getElementById("years");
    [[1, 25, "2001–2025"], [16, 25, "2016–2025"], [21, 25, "2021–2025"], [25, 25, "2025"]].forEach(function (p) {
      var b = el("button", null, p[2]); b.type = "button"; b.setAttribute("aria-pressed", String(p[0] === state.years[0] && p[1] === state.years[1]));
      b.addEventListener("click", function () {
        state.years = [p[0], p[1]];
        Array.prototype.forEach.call(yb.children, function (c) { c.setAttribute("aria-pressed", String(c === b)); });
        document.getElementById("lyr-loss").checked = true;
        paintHansen();
      });
      yb.appendChild(b);
    });
    document.getElementById("lyr-loss").addEventListener("change", function (e) { setVis("hansen", e.target.checked); });
    document.getElementById("lyr-counties").addEventListener("change", function (e) { setVis("counties", e.target.checked); });
    document.getElementById("base").addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b) return;
      Array.prototype.forEach.call(this.children, function (c) { c.setAttribute("aria-pressed", String(c === b)); });
      var base = b.dataset.base;
      setVis("sat", base === "sat"); setVis("hd", base === "hd"); setVis("osm", base === "osm"); setVis("labels", base !== "osm");
    });
    document.getElementById("splitbtn").addEventListener("click", function () { toggleSplit(this.getAttribute("aria-pressed") !== "true"); });
    document.getElementById("lyr-split").addEventListener("change", function (e) { toggleSplit(e.target.checked); });
  }

  function setVis(id, on) { if (map && map.getLayer(id)) map.setLayoutProperty(id, "visibility", on ? "visible" : "none"); }

  /* ---------- randare ---------- */
  function renderAll() {
    renderHeader();
    renderStats();
    renderList();
    updateMapData();
  }

  function renderHeader() {
    var u = document.getElementById("updated"), r = document.getElementById("range");
    if (!DATA.data_until) {
      u.textContent = "Prima rulare pe toată țara e în curs. Revino în câteva ore.";
      r.textContent = "";
      return;
    }
    var g = DATA.generated ? new Date(DATA.generated) : null;
    var when = g ? g.toLocaleString("ro-RO", { timeZone: "Europe/Bucharest", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" }) : "";
    u.textContent = "Actualizat " + when + " · imagini până pe " + zi(DATA.data_until, true);
    var s = periodStart();
    r.textContent = state.days === 1 ? "Schimbări văzute prima dată pe " + zi(DATA.data_until, true) : "Schimbări văzute prima dată între " + zi(s, true) + " și " + zi(DATA.data_until, true);
  }

  function renderStats() {
    var v = visible(), ha = v.reduce(function (t, a) { return t + a.ha; }, 0);
    var cty = {}; v.forEach(function (a) { if (a.county) cty[a.county] = 1; });
    var st = document.getElementById("stats");
    st.replaceChildren();
    [[fmt(v.length), "zone"], [fmt(ha, ha < 100 ? 1 : 0), "hectare"], [fmt(Object.keys(cty).length), "județe"]].forEach(function (x) {
      var d = el("div"); d.appendChild(el("b", null, x[0])); d.appendChild(el("span", null, x[1])); st.appendChild(d);
    });
    renderSpark(v);
    var all = DATA.alerts.filter(inPeriod);
    Array.prototype.forEach.call(document.querySelectorAll("#conf .chip"), function (b) {
      var n = all.filter(function (a) { return a.incredere === b.dataset.conf; }).length;
      b.querySelector(".n").textContent = "· " + fmt(n);
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
      var hidden = DATA.alerts.filter(inPeriod).length;
      box.appendChild(el("p", "empty", hidden ? "Nicio schimbare cu acest nivel de încredere în perioada aleasă. Bifează și „scăzută” ca să le vezi pe toate." :
        "Nicio schimbare nouă în perioada aleasă. Poate fi și din cauza norilor: pădurea acoperită de nori nu se vede. Încearcă o perioadă mai lungă."));
      return;
    }
    v.slice(0, state.shown).forEach(function (a) {
      var li = el("li"), b = el("button"); b.type = "button";
      b.appendChild(el("i", "dot " + confCls(a.incredere)));
      b.appendChild(el("span", "t", fmt(a.ha, 1) + " ha · " + (a.localitate ? a.localitate + ", " : "") + (a.county || "")));
      b.appendChild(el("span", "d", ziScurt(a.first_seen)));
      b.appendChild(el("span", "s", headline(a).t + (VERIF[a.id] ? " · verificat și din alte surse" : "") + (a.n_dates >= 2 ? " · văzută în " + a.n_dates + " imagini" : " · o singură imagine")));
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
    renderAll();
    select(a, fly);
  }

  function select(a, fly) {
    state.sel = a;
    history.replaceState(null, "", "#a=" + a.id);
    var d = document.getElementById("detail");
    document.getElementById("listbox").hidden = true;
    d.hidden = false;
    d.replaceChildren();
    var back = el("button", "back", "← Înapoi la listă"); back.type = "button";
    back.addEventListener("click", unselect);
    d.appendChild(back);
    var bd = el("div", "badges");
    var c1 = el("span", "badge"); c1.appendChild(el("i", "dot " + confCls(a.incredere))); c1.appendChild(document.createTextNode(a.incredere === "de confirmat" ? "de confirmat" : "încredere " + a.incredere)); bd.appendChild(c1);
    if (VERIF[a.id]) bd.appendChild(el("span", "badge ok", "verificat și din alte surse"));
    if (a.vant) bd.appendChild(el("span", "badge", "vânt puternic"));
    d.appendChild(bd);
    d.appendChild(kindBlock(a));
    d.appendChild(el("h3", null, fmt(a.ha, 1) + " ha" + (a.localitate ? " lângă " + a.localitate : "") + (a.county ? ", județul " + a.county : "")));
    d.appendChild(compare(a, false));
    if (VERIF[a.id]) d.appendChild(verifBlock(VERIF[a.id]));
    d.appendChild(el("p", null, a.text || ""));
    var ev = el("ul", "ev"); (a.dovezi || []).forEach(function (x) { ev.appendChild(el("li", null, x)); });
    d.appendChild(el("p", "lbl", "De ce acest nivel de încredere"));
    d.appendChild(ev);
    var kv = el("dl", "kv");
    function row(k, v) { kv.appendChild(el("dt", null, k)); var dd = el("dd"); if (v instanceof Node) dd.appendChild(v); else dd.textContent = v; kv.appendChild(dd); }
    row("Intactă pe", zi(a.before_date, true));
    row("Schimbată pe", zi(a.first_seen, true));
    row("Ultima imagine", zi(a.after_date, true));
    if (a.rafala_kmh != null) row("Vânt maxim", fmt(a.rafala_kmh) + " km/h în acel interval");
    if (a.hansen_jur && a.hansen_jur.ani && a.hansen_jur.ani.length) row("Pierderi în jur", a.hansen_jur.ani.join(", ") + " (Hansen)");
    if (a.ai) row("Model AI", a.ai.model || "");
    row("Coordonate", fmt(a.lat, 5) + ", " + fmt(a.lon, 5));
    d.appendChild(kv);
    d.appendChild(copyButton(a));
    var act = el("div", "actions");
    function link(t, h) { var x = el("a", null, t); x.href = h; x.target = "_blank"; x.rel = "noopener"; act.appendChild(x); }
    link("Google Maps (satelit)", "https://www.google.com/maps/@?api=1&map_action=map&center=" + a.lat + "," + a.lon + "&zoom=16&basemap=satellite");
    link("OpenStreetMap", "https://www.openstreetmap.org/?mlat=" + a.lat + "&mlon=" + a.lon + "#map=15/" + a.lat + "/" + a.lon);
    link("Raportează o greșeală", REPO + "/issues/new?title=" + encodeURIComponent("Alerta " + a.id) + "&body=" + encodeURIComponent("Ce e greșit la alerta " + a.id + "?\n\n" + location.href));
    d.appendChild(act);
    d.appendChild(el("p", "mono", a.id));
    if (fly) d.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });
    if (fly && map) {
      var b = a.bbox;
      map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 120, maxZoom: 14.5, duration: 900 });
    }
    updateSelection();
  }

  function unselect() {
    state.sel = null;
    history.replaceState(null, "", location.pathname);
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
    q: '<circle cx="12" cy="12" r="9"/><path d="M12 16.5v.5M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.1.9-1.1 1.8"/>'
  };
  function headline(a) {
    var v = a.vis && a.vis.verdict;
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
    var t = el("div"); t.appendChild(el("b", null, h.t)); if (h.src) t.appendChild(el("span", null, h.src));
    box.appendChild(t);
    return box;
  }

  /* ---------- verificări din alte surse (data/verificari.json) ---------- */
  function verifBlock(items) {
    var box = el("div", "verif");
    box.appendChild(el("p", "lbl", "Verificat și din alte surse"));
    items.forEach(function (v) {
      var it = el("div", "vitem");
      var head = el("p"); head.appendChild(el("b", null, v.sursa));
      head.appendChild(el("span", "vfit " + (v.potrivire === "sigură" ? "sure" : "maybe"), v.potrivire === "sigură" ? "se potrivește" : "se potrivește probabil"));
      it.appendChild(head);
      it.appendChild(el("p", null, v.text));
      if (v.url) { var a = el("a", null, "Vezi sursa"); a.href = v.url; a.target = "_blank"; a.rel = "noopener"; it.appendChild(a); }
      box.appendChild(it);
    });
    return box;
  }

  /* ---------- fișa pentru jurnaliști ---------- */
  function sheet(a) {
    var h = headline(a), abs = function (f) { return new URL("img/" + f, location.href).href; }, L = [];
    L.push("Pădurea RO: schimbare în pădure, de verificat");
    L.push("Loc: " + (a.localitate ? "lângă " + a.localitate + ", " : "") + (a.county ? "județul " + a.county : "") + " (" + a.lat + ", " + a.lon + ")");
    L.push("Suprafață: aproximativ " + fmt(a.ha, 1) + " ha");
    L.push("Când: intactă pe " + zi(a.before_date, true) + ", văzută schimbată pe " + zi(a.first_seen, true) + ", ultima imagine pe " + zi(a.after_date, true));
    L.push("Ce pare: " + h.t + (h.src ? " (" + h.src + ")" : ""));
    if (a.ai && a.ai.motiv) L.push("Analistul AI: " + a.ai.motiv);
    L.push("Încredere: " + a.incredere + (a.dovezi && a.dovezi.length ? " (" + a.dovezi.join("; ") + ")" : ""));
    if (a.img_before) L.push("Imagine înainte, " + zi(a.img_before.date, true) + ": " + abs(a.img_before.file));
    if (a.img_after) L.push("Imagine după, " + zi(a.img_after.date, true) + ": " + abs(a.img_after.file));
    L.push("Google Maps, satelit: https://www.google.com/maps/@?api=1&map_action=map&center=" + a.lat + "," + a.lon + "&zoom=16&basemap=satellite");
    (VERIF[a.id] || []).forEach(function (v) { L.push("Verificat și în: " + v.sursa + " (" + v.potrivire + "): " + v.text + (v.url ? " " + v.url : "")); });
    L.push("Fișa pe hartă: " + location.href.split("#")[0] + "#a=" + a.id);
    L.push("Autorizații și transporturi de lemn: se pot căuta în aplicația Inspectorul Pădurii.");
    L.push("Notă: imagini Copernicus Sentinel-2. Nu spunem că e ilegal. E o schimbare văzută din satelit care merită verificată.");
    return L.join("\n");
  }
  function copyButton(a) {
    var wrap = el("div", "copywrap"), cp = el("button", "copy", "Copiază fișa pentru jurnaliști"); cp.type = "button";
    wrap.appendChild(cp);
    cp.addEventListener("click", function () {
      var txt = sheet(a);
      function ok() { cp.textContent = "Copiată. Lipește-o într-un e-mail."; setTimeout(function () { cp.textContent = "Copiază fișa pentru jurnaliști"; }, 2500); }
      function fallback() { var old = wrap.querySelector("textarea"); if (old) old.remove(); var ta = el("textarea", "copybox"); ta.value = txt; ta.readOnly = true; ta.rows = 8; wrap.appendChild(ta); ta.select(); }
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(ok, fallback); else fallback();
    });
    return wrap;
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
    if (b) [["blink", "Clipește"], ["swipe", "Glisează"], ["side", "Una lângă alta"]].forEach(function (m) {
      var x = el("button", null, m[1]); x.type = "button"; x.dataset.mode = m[0]; seg.appendChild(x);
    });
    top.appendChild(seg);
    var ln = el("button", "mini", "Contur"); ln.type = "button"; ln.setAttribute("aria-pressed", "true"); top.appendChild(ln);
    if (!big) { var zm = el("button", "mini", "Mărește"); zm.type = "button"; zm.addEventListener("click", function () { openModal(a); }); top.appendChild(zm); }
    wrap.appendChild(top); wrap.appendChild(stage); wrap.appendChild(hint);

    function pic(info, cls, alt) { var i = el("img", cls); i.src = "img/" + info.file; i.alt = alt; return i; }
    function frame(main) {
      var box = el("div", "compare");
      main.addEventListener("load", function () { box.style.aspectRatio = main.naturalWidth + " / " + main.naturalHeight; });
      return box;
    }
    function addLine(box) { var o = showLine && outline(a); if (o) box.appendChild(o); }
    function render() {
      stage.replaceChildren();
      Array.prototype.forEach.call(seg.children, function (x) { x.setAttribute("aria-pressed", String(x.dataset.mode === mode)); });
      if (mode === "side") {
        var g = el("div", "side");
        [[b, "înainte"], [f, "după"]].forEach(function (p) {
          var fig = el("figure"), i = pic(p[0], null, p[1] + ", " + zi(p[0].date)), box = frame(i);
          box.appendChild(i); addLine(box); fig.appendChild(box);
          fig.appendChild(el("figcaption", null, p[1] + " · " + zi(p[0].date, true))); g.appendChild(fig);
        });
        stage.appendChild(g);
        hint.textContent = "Stânga: înainte. Dreapta: după. Conturul galben e zona găsită.";
        return;
      }
      var i2 = pic(f, "after", "După, " + zi(f.date)), box = frame(i2);
      if (mode === "after") {
        i2.style.clipPath = "none"; box.appendChild(i2); addLine(box);
        box.appendChild(el("span", "cap r", "după · " + ziScurt(f.date)));
        hint.textContent = "Nu avem o imagine curată de dinainte.";
        stage.appendChild(box);
        return;
      }
      box.appendChild(pic(b, null, "Înainte, " + zi(b.date))); box.appendChild(i2); addLine(box);
      if (mode === "swipe") {
        var bar = el("div", "bar"); box.appendChild(bar);
        box.appendChild(el("span", "cap l", "înainte · " + ziScurt(b.date)));
        box.appendChild(el("span", "cap r", "după · " + ziScurt(f.date)));
        var rg = el("input"); rg.type = "range"; rg.min = 0; rg.max = 100; rg.value = 50; rg.setAttribute("aria-label", "Compară înainte și după");
        rg.addEventListener("input", function () { i2.style.clipPath = "inset(0 0 0 " + rg.value + "%)"; bar.style.left = rg.value + "%"; });
        box.appendChild(rg);
        hint.textContent = "Trage peste imagine: stânga e înainte, dreapta e după. Conturul galben e zona găsită.";
      } else {
        i2.style.clipPath = "none";
        var cap = el("span", "cap blink"), on = true, paused = false;
        box.appendChild(cap);
        var tick = function () {
          on = !on; i2.style.opacity = on ? "1" : "0";
          cap.textContent = (on ? "DUPĂ · " + ziScurt(f.date) : "ÎNAINTE · " + ziScurt(b.date)) + (paused ? " · oprit" : "");
          cap.classList.toggle("on", on);
        };
        tick();
        var t = setInterval(function () { if (!document.body.contains(box)) { clearInterval(t); return; } if (!paused) tick(); }, 1000);
        box.classList.add("clickable");
        box.addEventListener("click", function () { paused = !paused; on = !on; tick(); });
        hint.textContent = "Poza trece singură de la înainte la după, o dată pe secundă. Apasă pe ea ca s-o oprești. Conturul galben e zona găsită.";
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
    top.appendChild(el("h3", null, h.t + " · " + fmt(a.ha, 1) + " ha" + (a.localitate ? " lângă " + a.localitate : "") + (a.county ? ", " + a.county : "")));
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
  function initMap(hj, counties) {
    var mobile = window.matchMedia("(max-width: 900px)").matches;
    map = new maplibregl.Map({
      container: "map",
      bounds: [[20.2, 43.55], [29.8, 48.3]],
      fitBoundsOptions: { padding: 20 },
      maxZoom: 16, minZoom: 5,
      cooperativeGestures: mobile,
      attributionControl: { compact: true },
      style: {
        version: 8,
        sources: {
          sat: { type: "raster", tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg"], tileSize: 256, maxzoom: 15,
                 attribution: '<a href="https://s2maps.eu" target="_blank">Sentinel-2 cloudless</a> de EOX IT Services GmbH (date Copernicus Sentinel modificate)' },
          osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
                 attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>' },
          hd: { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, maxzoom: 18,
                attribution: 'Imagini: Esri, Maxar, Earthstar Geographics (pot fi mai vechi)' },
          labels: { type: "raster", tiles: ["https://a.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png", "https://b.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png"], tileSize: 256,
                    attribution: '© <a href="https://carto.com/attributions" target="_blank">CARTO</a>' }
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#0f1411" } },
          { id: "sat", type: "raster", source: "sat" },
          { id: "hd", type: "raster", source: "hd", layout: { visibility: "none" } },
          { id: "osm", type: "raster", source: "osm", layout: { visibility: "none" } }
        ]
      }
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    pickSatellite();
    map.on("load", function () {
      if (hj) {
        hansen = { meta: hj };
        map.addSource("hansen", { type: "image", url: "data/static/hansen.webp", coordinates: [[hj.west, hj.north], [hj.east, hj.north], [hj.east, hj.south], [hj.west, hj.south]] });
        map.addLayer({ id: "hansen", type: "raster", source: "hansen", maxzoom: 12, paint: { "raster-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.85, 10, 0.7, 12, 0.35], "raster-resampling": "nearest", "raster-fade-duration": 0 } });
        loadHansen();
      }
      if (counties) {
        map.addSource("counties", { type: "geojson", data: counties });
        map.addLayer({ id: "counties", type: "line", source: "counties", paint: { "line-color": "#ffffff", "line-opacity": 0.45, "line-width": 0.8 } });
      }
      map.addLayer({ id: "labels", type: "raster", source: "labels", paint: { "raster-opacity": 0.9 } });
      map.addSource("alerts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("points", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("sel", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      var color = ["match", ["get", "c"], "ridicată", CONF_COLOR["ridicată"], "medie", CONF_COLOR["medie"], "scăzută", CONF_COLOR["scăzută"], CONF_COLOR["de confirmat"]];
      map.addLayer({ id: "a-fill", type: "fill", source: "alerts", minzoom: 9, paint: { "fill-color": color, "fill-opacity": 0.32 } });
      map.addLayer({ id: "a-line", type: "line", source: "alerts", minzoom: 9, paint: { "line-color": color, "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.2, 14, 2.6] } });
      map.addLayer({ id: "a-pt", type: "circle", source: "points", maxzoom: 12.5, paint: {
        "circle-color": color,
        "circle-radius": ["interpolate", ["linear"], ["sqrt", ["get", "ha"]], 1, 4.5, 4, 8, 12, 15],
        "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.6, "circle-opacity": 0.95,
        "circle-pitch-alignment": "map" } });
      map.addLayer({ id: "sel-line", type: "line", source: "sel", paint: { "line-color": "#ffffff", "line-width": 3.2 } });
      map.addLayer({ id: "sel-pt", type: "circle", source: "sel", filter: ["==", ["geometry-type"], "Point"], maxzoom: 12.5, paint: { "circle-radius": 18, "circle-color": "rgba(0,0,0,0)", "circle-stroke-color": "#ffffff", "circle-stroke-width": 3 } });

      var pop = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
      ["a-pt", "a-fill"].forEach(function (id) {
        map.on("mouseenter", id, function () { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", id, function () { map.getCanvas().style.cursor = ""; pop.remove(); });
        map.on("mousemove", id, function (e) {
          var p = e.features[0].properties;
          pop.setLngLat(e.lngLat).setText(fmt(p.ha, 1) + " ha · " + (p.loc || p.county || "") + " · " + ziScurt(p.d)).addTo(map);
        });
        map.on("click", id, function (e) { var a = DATA.alerts.find(function (x) { return x.id === e.features[0].properties.id; }); if (a) select(a, false); });
      });
      updateMapData();
      updateSelection();
    });
  }

  function pickSatellite() {
    /* cea mai nouă hartă Sentinel-2 cloudless care răspunde */
    var years = ["2024", "2023", "2022", "2021"], i = 0;
    function tryNext() {
      if (i >= years.length) return;
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
      return { type: "Feature", geometry: a.geometry, properties: { id: a.id, c: a.incredere, ha: a.ha, d: a.first_seen, county: a.county, loc: a.localitate } };
    }) };
  }
  function pointsFC(v) {
    return { type: "FeatureCollection", features: v.map(function (a) {
      return { type: "Feature", geometry: { type: "Point", coordinates: [a.lon, a.lat] }, properties: { id: a.id, c: a.incredere, ha: a.ha, d: a.first_seen, county: a.county, loc: a.localitate } };
    }).sort(function (x, y) { return y.properties.ha - x.properties.ha; }) };
  }
  function updateMapData() {
    var v = visible();
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
    setTimeout(function () { map.resize(); if (map2) { map2.resize(); sync(map, map2); } }, 60);
  }
  function initMap2() {
    map2 = new maplibregl.Map({
      container: "map2", center: map.getCenter(), zoom: map.getZoom(), maxZoom: 18, minZoom: 5,
      attributionControl: { compact: true },
      style: { version: 8, sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>' } },
        layers: [{ id: "osm", type: "raster", source: "osm" }] }
    });
    map2.on("load", function () {
      var color = ["match", ["get", "c"], "ridicată", CONF_COLOR["ridicată"], "medie", CONF_COLOR["medie"], "scăzută", CONF_COLOR["scăzută"], CONF_COLOR["de confirmat"]];
      map2.addSource("alerts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addSource("points", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addSource("sel", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map2.addLayer({ id: "a-fill", type: "fill", source: "alerts", minzoom: 9, paint: { "fill-color": color, "fill-opacity": 0.18 } });
      map2.addLayer({ id: "a-line", type: "line", source: "alerts", minzoom: 9, paint: { "line-color": color, "line-width": 2.4 } });
      map2.addLayer({ id: "a-pt", type: "circle", source: "points", maxzoom: 12.5, paint: { "circle-color": color, "circle-radius": 6, "circle-stroke-color": "#14201a", "circle-stroke-width": 1.4 } });
      map2.addLayer({ id: "sel-line", type: "line", source: "sel", paint: { "line-color": "#14201a", "line-width": 3 } });
      ["a-pt", "a-fill"].forEach(function (id) {
        map2.on("mouseenter", id, function () { map2.getCanvas().style.cursor = "pointer"; });
        map2.on("mouseleave", id, function () { map2.getCanvas().style.cursor = ""; });
        map2.on("click", id, function (e) { var a = DATA.alerts.find(function (x) { return x.id === e.features[0].properties.id; }); if (a) select(a, false); });
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
      paintHansen();
    };
    img.src = "data/static/hansen.webp";
  }
  function paintHansen() {
    if (!HSRC || !map.getSource("hansen")) return;
    var a = [243, 184, 211], b = [214, 68, 142], cc = [125, 11, 76], col = [];
    for (var y = 0; y <= 25; y++) {
      var t = Math.max(0, (y - 1) / 24), p, q, u;
      if (t < 0.5) { p = a; q = b; u = t / 0.5; } else { p = b; q = cc; u = (t - 0.5) / 0.5; }
      col[y] = [p[0] + (q[0] - p[0]) * u, p[1] + (q[1] - p[1]) * u, p[2] + (q[2] - p[2]) * u];
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
