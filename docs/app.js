/* Pădurea RO: harta schimbărilor din pădure. Datele vin din data/alerts.json, refăcut zilnic de GitHub Actions. */
(function () {
  "use strict";

  var REPO = "https://github.com/iliemihai/padurea-ro";
  var CONF = [["ridicată", "hi"], ["medie", "mid"], ["scăzută", "lo"], ["de confirmat", "un"]];
  var CONF_COLOR = { "ridicată": "#ff4d4f", "medie": "#ffb020", "scăzută": "#9fb1ba", "de confirmat": "#a99cf0" };
  var LUNI = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."];
  var LUNI_L = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie"];
  var AI_TXT = { taiere: "AI: pădure dispărută", incendiu: "AI: zonă arsă", toamna: "AI: frunze de toamnă", nori: "AI: nori sau ceață", agricol: "AI: teren agricol", neclar: "AI: neclar" };

  var state = { days: 30, conf: { "ridicată": true, "medie": false, "scăzută": false, "de confirmat": false }, shown: 40, sel: null, years: [21, 25] };
  var DATA = { alerts: [], data_until: null, generated: null }, RUNS = [], map, hansen = null;

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
    getJSON("data/static/counties.geojson").catch(function () { return null; })
  ]).then(function (res) {
    if (res[0]) DATA = res[0];
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

  function initControls() {
    var per = document.getElementById("periods"), nd = document.getElementById("ndays"), custom = nd.parentNode;
    function setDays(n, fromInput) {
      state.days = Math.max(1, Math.min(3650, n | 0));
      Array.prototype.forEach.call(per.querySelectorAll("button"), function (b) { b.setAttribute("aria-pressed", String(+b.dataset.days === state.days && !fromInput)); });
      custom.classList.toggle("on", !!fromInput);
      state.shown = 40;
      renderAll();
    }
    per.addEventListener("click", function (e) { var b = e.target.closest("button"); if (b) setDays(+b.dataset.days, false); });
    nd.addEventListener("input", function () { if (+nd.value > 0) setDays(+nd.value, true); });
    nd.addEventListener("focus", function () { if (+nd.value > 0) setDays(+nd.value, true); });

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
      b.appendChild(el("span", "s", (a.ai ? AI_TXT[a.ai.categorie] || "" : "fără părerea AI") + (a.n_dates >= 2 ? " · văzută în " + a.n_dates + " imagini" : " · o singură imagine")));
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
    if (!inPeriod(a)) {
      state.days = Math.max(1, Math.round((pd(DATA.data_until) - pd(a.first_seen)) / 864e5) + 1);
      document.getElementById("ndays").value = state.days;
      document.getElementById("ndays").parentNode.classList.add("on");
      Array.prototype.forEach.call(document.querySelectorAll("#periods button"), function (b) { b.setAttribute("aria-pressed", "false"); });
    }
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
    if (a.ai) bd.appendChild(el("span", "badge", (AI_TXT[a.ai.categorie] || "AI") + " (" + fmt(a.ai.incredere * 100) + "%)"));
    if (a.vant) bd.appendChild(el("span", "badge", "vânt puternic"));
    d.appendChild(bd);
    d.appendChild(el("h3", null, fmt(a.ha, 1) + " ha" + (a.localitate ? " lângă " + a.localitate : "") + (a.county ? ", județul " + a.county : "")));
    d.appendChild(compare(a));
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
    var act = el("div", "actions");
    function link(t, h) { var x = el("a", null, t); x.href = h; x.target = "_blank"; x.rel = "noopener"; act.appendChild(x); }
    link("Google Maps (satelit)", "https://www.google.com/maps/@?api=1&map_action=map&center=" + a.lat + "," + a.lon + "&zoom=16&basemap=satellite");
    link("OpenStreetMap", "https://www.openstreetmap.org/?mlat=" + a.lat + "&mlon=" + a.lon + "#map=15/" + a.lat + "/" + a.lon);
    link("Raportează o greșeală", REPO + "/issues/new?title=" + encodeURIComponent("Alerta " + a.id) + "&body=" + encodeURIComponent("Ce e greșit la alerta " + a.id + "?\n\n" + location.href));
    d.appendChild(act);
    d.appendChild(el("p", "mono", a.id));
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

  function compare(a) {
    var wrap = el("div");
    var b = a.img_before, f = a.img_after;
    if (!f) { wrap.appendChild(el("p", "hint", "Nu avem încă o imagine curată a zonei.")); return wrap; }
    var box = el("div", "compare");
    var i1 = el("img"), i2 = el("img", "after");
    i2.src = "img/" + f.file; i2.alt = "După, " + zi(f.date);
    if (b) { i1.src = "img/" + b.file; i1.alt = "Înainte, " + zi(b.date); box.appendChild(i1); }
    box.appendChild(i2);
    if (!b) i2.style.clipPath = "none";
    i2.addEventListener("load", function () { box.style.aspectRatio = i2.naturalWidth + " / " + i2.naturalHeight; });
    if (a.chip_bbox && a.bbox) {
      var cb = a.chip_bbox, ab = a.bbox, w = cb[2] - cb[0], h = cb[3] - cb[1];
      var r = el("div", "box");
      r.style.left = (100 * (ab[0] - cb[0]) / w) + "%"; r.style.width = (100 * (ab[2] - ab[0]) / w) + "%";
      r.style.top = (100 * (cb[3] - ab[3]) / h) + "%"; r.style.height = (100 * (ab[3] - ab[1]) / h) + "%";
      box.appendChild(r);
    }
    if (b) {
      var bar = el("div", "bar"); box.appendChild(bar);
      box.appendChild(el("span", "cap l", "înainte · " + ziScurt(b.date)));
      box.appendChild(el("span", "cap r", "după · " + ziScurt(f.date)));
      var rg = el("input"); rg.type = "range"; rg.min = 0; rg.max = 100; rg.value = 50; rg.setAttribute("aria-label", "Compară înainte și după");
      rg.addEventListener("input", function () { i2.style.clipPath = "inset(0 0 0 " + rg.value + "%)"; bar.style.left = rg.value + "%"; });
      box.appendChild(rg);
    } else {
      box.appendChild(el("span", "cap r", "după · " + ziScurt(f.date)));
    }
    wrap.appendChild(box);
    wrap.appendChild(el("p", "hint", b ? "Trage peste imagine ca să compari. Conturul punctat e zona găsită." : "Nu avem o imagine curată de dinainte."));
    return wrap;
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
