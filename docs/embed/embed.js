/* Harta de pus în articole: <iframe src=".../embed/?a=<id>"> (o zonă), ?judet=<slug> (un județ), fără nimic (zonele roșii din țară).
   ?stare=toate arată și zonele cu autorizație. Citește aceleași fișiere statice ca site-ul; nu are nevoie de server. */
(function () {
  "use strict";
  var q = new URLSearchParams(location.search);
  var ID = (q.get("a") || "").replace(/[^\w-]/g, "");
  var JUDET = (q.get("judet") || "").replace(/[^a-z-]/g, "");
  var TOATE = q.get("stare") === "toate";
  var SITE = new URL("../", location.href).href;
  var CUL = { fara: "#ee3533", neacoperit: "#ee3533", vegetatie: "#dc9e12", probabil: "#249c74", acoperit: "#249c74",
              nu_taiere: "#7e7a73", nejudecat: "#bbb7af", nev: "#bbb7af" };
  var TXT = { fara: "fără autorizație", neacoperit: "autorizația nu acoperă tăierea", vegetatie: "pășune, nu pădure",
              probabil: "probabil cu autorizație", acoperit: "cu autorizație", nu_taiere: "nu e tăiere de pădure",
              nejudecat: "de confirmat pe poze", nev: "încă necomparată" };
  var ROSU = { fara: 1, neacoperit: 1 };
  var LUNI = ["ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.", "nov.", "dec."];

  function zi(s) { if (!s) return ""; var p = s.split("-"); return +p[2] + " " + LUNI[+p[1] - 1] + " " + p[0]; }
  function ha(x) { return (Math.round((x || 0) * 10) / 10).toString().replace(".", ",") + " ha"; }
  function sub(t) { document.getElementById("sub").textContent = t; }
  function msg(t) { var m = document.createElement("p"); m.className = "msg"; m.textContent = t; document.body.appendChild(m); }
  function getJSON(u) { return fetch(u).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }

  /* fiecare sursă devine aceeași formă: Feature cu id, stare, ha, loc, data */
  function dinAlerta(a) {
    var u = a.uat || {};
    return { type: "Feature", geometry: a.geometry, properties: { id: a.id, stare: "fara", ha: a.ha,
             loc: [a.localitate, u.nume && u.nume !== a.localitate ? u.nume : null, a.county].filter(Boolean).join(", "),
             data: a.first_seen, txt: "fără autorizație care s-o acopere" } };
  }
  function dinRand(f) {
    var p = f.properties || {};
    return { type: "Feature", geometry: f.geometry, properties: { id: p.id || f.id, stare: p.stare || "nev", ha: p.ha,
             loc: [p.localitate, p.uat && (!p.localitate || p.uat.indexOf(p.localitate) < 0) ? p.uat : null, p.judet].filter(Boolean).join(", "),
             data: p.prima_data, txt: TXT[p.stare] || p.stare_text || "" } };
  }

  var src, titlu;
  if (ID) { src = getJSON(SITE + "zona/" + ID + "/zona.json").then(function (f) { return [dinRand(f)]; }); titlu = "o zonă"; }
  else if (JUDET) {
    src = getJSON(SITE + "judet/" + JUDET + "/zone.geojson").then(function (fc) {
      return fc.features.map(dinRand).filter(function (f) { return TOATE || ROSU[f.properties.stare]; });
    });
  } else {
    src = getJSON(SITE + "data/rosii.json").then(function (d) { return (d.alerts || []).filter(function (a) { return a.geometry; }).map(dinAlerta); });
  }

  var map = new maplibregl.Map({
    container: "map", center: [25, 45.9], zoom: 5.4, attributionControl: { compact: true }, cooperativeGestures: true,
    style: { version: 8, sources: { sat: { type: "raster", tileSize: 256, maxzoom: 15,
      tiles: ["https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg"],
      attribution: '<a href="https://s2maps.eu" target="_blank" rel="noopener">Sentinel-2 cloudless</a> de EOX (date Copernicus Sentinel modificate) · <a href="' + SITE + 'date/" target="_blank" rel="noopener">Pădurea RO, CC BY 4.0</a>' } },
      layers: [{ id: "sat", type: "raster", source: "sat", paint: { "raster-brightness-max": 0.8 } }] }
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  Promise.all([src, new Promise(function (ok) { map.on("load", ok); })]).then(function (r) {
    var feats = r[0];
    if (!feats.length) { sub(JUDET ? "Nicio zonă fără autorizație în acest județ." : "Nicio zonă."); return; }
    var n = feats.length, tot = feats.reduce(function (s, f) { return s + (f.properties.ha || 0); }, 0);
    if (ID) { var p0 = feats[0].properties; sub(ha(p0.ha) + " · " + p0.loc + " · " + (TXT[p0.stare] || "")); document.getElementById("brand").href = SITE + "zona/" + ID + "/"; }
    else sub(n + (n === 1 ? " zonă" : " zone") + " (" + ha(tot) + ")" + (TOATE ? "" : " fără autorizație care să le acopere") + (JUDET ? "" : ", în toată țara"));
    var pts = feats.map(function (f) {
      var b = bbox(f.geometry);
      return { type: "Feature", geometry: { type: "Point", coordinates: [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] }, properties: f.properties };
    });
    var fc = { type: "FeatureCollection", features: feats };
    map.addSource("z", { type: "geojson", data: fc });
    map.addSource("p", { type: "geojson", data: { type: "FeatureCollection", features: pts } });
    var cul = ["match", ["get", "stare"]];
    Object.keys(CUL).forEach(function (k) { cul.push(k, CUL[k]); });
    cul.push("#bbb7af");
    map.addLayer({ id: "z-fill", type: "fill", source: "z", minzoom: 10, paint: { "fill-color": cul, "fill-opacity": 0.35 } });
    map.addLayer({ id: "z-line", type: "line", source: "z", minzoom: 10, paint: { "line-color": cul, "line-width": 2 } });
    map.addLayer({ id: "p", type: "circle", source: "p", maxzoom: 11, paint: { "circle-color": cul, "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 4, 10, 7],
                   "circle-stroke-color": "#030201", "circle-stroke-width": 1.5 } });
    var all = feats.map(function (f) { return bbox(f.geometry); }).reduce(function (a, b) { return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]; });
    map.fitBounds([[all[0], all[1]], [all[2], all[3]]], { padding: 48, maxZoom: ID ? 14.5 : 11, duration: 0 });
    ["z-fill", "p"].forEach(function (l) {
      map.on("click", l, function (ev) { popup(ev.features[0].properties, ev.lngLat); });
      map.on("mouseenter", l, function () { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", l, function () { map.getCanvas().style.cursor = ""; });
    });
  }).catch(function () { sub(""); msg("Datele nu s-au putut încărca. Deschide Pădurea RO direct."); });

  function popup(p, ll) {
    var d = document.createElement("div"); d.className = "pop";
    var t = document.createElement("b"); t.textContent = ha(p.ha) + " · " + p.loc; d.appendChild(t);
    var m = document.createElement("div"); m.className = "m"; m.textContent = "schimbare văzută pe " + zi(p.data); d.appendChild(m);
    var s = document.createElement("div"); s.className = "s";
    var k = document.createElement("i"); k.style.background = CUL[p.stare] || "#bbb7af"; s.appendChild(k);
    s.appendChild(document.createTextNode(p.txt || TXT[p.stare] || "")); d.appendChild(s);
    var a = document.createElement("a"); a.href = SITE + "zona/" + p.id + "/"; a.target = "_blank"; a.rel = "noopener"; a.textContent = "Pagina zonei ↗"; d.appendChild(a);
    new maplibregl.Popup({ maxWidth: "260px" }).setLngLat(ll).setDOMContent(d).addTo(map);
  }

  function bbox(g) {
    var b = [180, 90, -180, -90];
    (function walk(c) {
      if (typeof c[0] === "number") { b[0] = Math.min(b[0], c[0]); b[1] = Math.min(b[1], c[1]); b[2] = Math.max(b[2], c[0]); b[3] = Math.max(b[3], c[1]); return; }
      c.forEach(walk);
    })(g.coordinates);
    return b;
  }
})();
