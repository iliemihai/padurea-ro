"""Ariile protejate din România, din datele deschise ale Agenției Europene de Mediu (EEA, licența CC BY 4.0):

  - Natura 2000: siturile de importanță comunitară (ROSCI) și ariile de protecție specială avifaunistică (ROSPA)
  - ariile protejate naționale (baza CDDA): parcuri naționale și naturale, rezervații, monumente ale naturii

Scrie:
  data/arii_ro.geojson                 limite puțin simplificate, pentru potrivirea cu zonele (pipeline/arii.py)
  docs/data/static/arii.geojson        limite mai simplificate, pentru stratul de pe hartă
  out/arii_raport.json                 ce servicii și câmpuri s-au folosit, câte arii de fiecare tip

Are nevoie de internet, deci rulează pe GitHub Actions (workflow-ul „Arii protejate”): python -m pipeline.static_arii
Întâi încearcă serviciile ArcGIS ale EEA (doar România, fără descărcări mari); dacă nu merg, descarcă GeoPackage-urile.
"""
import json
import re
import time
import urllib.parse
import urllib.request

from . import config as C
from .uat import modern

REST = "https://bio.discomap.eea.europa.eu/arcgis/rest/services/ProtectedSites"
N2K_SERVICE = REST + "/Natura2000Sites/MapServer"
WEBDAV = "https://sdi.eea.europa.eu/webdav/datastore/public/"
N2K_DAV = ["eea_v_3035_100_k_natura2000_p_2025_v01_r00", "eea_v_3035_100_k_natura2000_p_2024_v01_r00"]
CDDA_DAV = ["eea_v_3035_100_k_natda-poly_p_2025-2026_v24_r00", "eea_v_3035_100_k_natda-poly_p_2024-2025_v23_r00"]
UA = {"User-Agent": "padurea-ro (github.com/iliemihai/padurea-ro)"}
REPORT = {"surse": [], "tipuri": {}, "cdda_coduri": {}}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(url, params=None, tries=3, timeout=120, raw=False):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                body = r.read()
            return body if raw else json.loads(body)
        except Exception as exc:
            log("  nu a mers:", url[:140], repr(exc)[:160])
            time.sleep(4 * (k + 1))
    return None


# ---------- geometrii ----------
def esri_to_shape(g):
    """Geometrie Esri JSON (rings) -> shapely; inelele în sensul acelor de ceasornic sunt contururi, celelalte găuri."""
    from shapely.geometry import MultiPolygon, Point, Polygon
    rings = (g or {}).get("rings") or []
    def area(r):
        return sum(x0 * y1 - x1 * y0 for (x0, y0, *_), (x1, y1, *_) in zip(r, r[1:] + r[:1])) / 2
    shells = [Polygon([p[:2] for p in r]) for r in rings if len(r) >= 4 and area(r) < 0]
    holes = [[p[:2] for p in r] for r in rings if len(r) >= 4 and area(r) > 0]
    polys = []
    for s in shells:
        hs = [h for h in holes if s.contains(Point(h[0]))]
        polys.append(Polygon(s.exterior.coords, hs))
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def clean(geom):
    from shapely import make_valid
    from shapely.geometry import MultiPolygon, Polygon
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = make_valid(geom)
    parts = [p for p in getattr(geom, "geoms", [geom]) if isinstance(p, (Polygon, MultiPolygon))]
    flat = []
    for p in parts:
        flat.extend(getattr(p, "geoms", [p]))
    if not flat:
        return None
    return flat[0] if len(flat) == 1 else MultiPolygon(flat)


def field(fields, *patterns):
    names = [f["name"] for f in fields]
    for pat in patterns:
        for n in names:
            if re.fullmatch(pat, n, re.I):
                return n
    for pat in patterns:
        for n in names:
            if re.search(pat, n, re.I):
                return n
    return None


def query_layer(layer_url, where, out_fields, chunk=25):
    """Toate obiectele care respectă condiția, câte câteva odată (după id), cu geometria în grade (EPSG:4326)."""
    ids = get(layer_url + "/query", {"where": where, "returnIdsOnly": "true", "f": "json"})
    if not ids or not ids.get("objectIds"):
        return []
    oids = sorted(ids["objectIds"])
    log(f"  {len(oids)} obiecte în {layer_url.rsplit('/services/', 1)[-1]}")
    feats = []
    for i in range(0, len(oids), chunk):
        part = oids[i:i + chunk]
        p = {"objectIds": ",".join(map(str, part)), "outFields": ",".join(out_fields), "returnGeometry": "true",
             "outSR": "4326", "geometryPrecision": "6", "f": "geojson"}
        res = get(layer_url + "/query", p, timeout=300)
        from shapely.geometry import shape
        if res and res.get("features") is not None:
            for f in res["features"]:
                feats.append((clean(shape(f["geometry"])) if f.get("geometry") else None, f.get("properties") or {}))
            continue
        p["f"] = "json"         # serverul nu știe GeoJSON: luăm Esri JSON și îl transformăm noi
        res = get(layer_url + "/query", p, timeout=300)
        if not res or "features" not in res:
            raise RuntimeError("interogarea nu a mers: " + layer_url)
        for f in res["features"]:
            feats.append((clean(esri_to_shape(f.get("geometry"))), f.get("attributes") or {}))
    return [(g, a) for g, a in feats if g is not None]


# ---------- Natura 2000 ----------
def n2k_rest():
    svc = get(N2K_SERVICE, {"f": "json"})
    if not svc:
        return None
    out = {}
    for lay in svc.get("layers", []):
        url = f"{N2K_SERVICE}/{lay['id']}"
        meta = get(url, {"f": "json"}) or {}
        if "Polygon" not in str(meta.get("geometryType")):
            continue
        fs = meta.get("fields") or []
        code, name, typ = field(fs, "SITECODE", "SITE_CODE", r"site.?code"), field(fs, "SITENAME", "SITE_NAME", r"site.?name"), field(fs, "SITETYPE", "SITE_TYPE", r"site.?type")
        if not code:
            continue
        log(f"Natura 2000: stratul {lay['id']} „{lay.get('name')}”, câmpuri {code}/{name}/{typ}")
        REPORT["surse"].append({"natura2000": url, "campuri": [code, name, typ]})
        for g, a in query_layer(url, f"{code} LIKE 'RO%'", [x for x in (code, name, typ) if x]):
            c = str(a.get(code) or "").strip()
            if c and c not in out:
                out[c] = (g, {"cod": c, "nume": modern(str(a.get(name) or "").strip()), "sursa": "Natura 2000"})
    return list(out.values()) or None


# ---------- arii naționale (CDDA) ----------
def cdda_tip(name, iucn, desig):
    n = (name or "").lower()
    if re.search(r"parc(ul)?\s+na[țţt]ional", n):
        return "parc național"
    if re.search(r"parc(ul)?\s+natural", n):
        return "parc natural"
    if "biosfer" in n:
        return "rezervația biosferei"
    i = (iucn or "").strip().upper()
    if i == "IA" or "științific" in n or "stiintific" in n:
        return "rezervație științifică"
    if i == "II":
        return "parc național"
    if i == "V":
        return "parc natural"
    if i == "III" or "monument" in n:
        return "monument al naturii"
    if i in ("IV", "IB") or "rezerva" in n:
        return "rezervație naturală"
    return "arie protejată națională"


def cdda_rest():
    folder = get(REST, {"f": "json"})
    if not folder:
        return None
    names = [s["name"] for s in folder.get("services", []) if s.get("type") == "MapServer" and re.search(r"cdda|natda|designat", s["name"], re.I)]
    def version(n):
        m = re.findall(r"\d+", n)
        return (int(m[-1]) if m else 0, "WM" in n)
    for svc in sorted(names, key=version, reverse=True):
        base = f"{REST.rsplit('/ProtectedSites', 1)[0]}/{svc}/MapServer"
        meta_svc = get(base, {"f": "json"}) or {}
        for lay in meta_svc.get("layers", []):
            url = f"{base}/{lay['id']}"
            meta = get(url, {"f": "json"}) or {}
            if "Polygon" not in str(meta.get("geometryType")):
                continue
            fs = meta.get("fields") or []
            cc = field(fs, "cddaCountryCode", "countryCode", "ISO3", "ISO2", r"country.?code", "MS")
            nm = field(fs, "siteName", "SITE_NAME", "name")
            idf = field(fs, "cddaId", "siteCode", "SITE_CODE", "id")
            iucn = field(fs, "iucnCategory", "IUCNCAT", r"iucn")
            desig = field(fs, "designationTypeCode", "DESIG_TYPE", r"designation.?type")
            if not cc or not nm:
                continue
            for val in ("RO", "ROU"):
                rows = query_layer(url, f"{cc} = '{val}'", [x for x in (cc, nm, idf, iucn, desig) if x])
                if rows:
                    log(f"CDDA: {svc} stratul {lay['id']}, câmpuri {cc}/{nm}/{idf}/{iucn}/{desig}")
                    REPORT["surse"].append({"cdda": url, "campuri": [cc, nm, idf, iucn, desig]})
                    out = []
                    for g, a in rows:
                        nume = modern(str(a.get(nm) or "").strip())
                        key = f"{a.get(desig)}|{a.get(iucn)}"
                        REPORT["cdda_coduri"].setdefault(key, []).append(nume)
                        out.append((g, {"cod": str(a.get(idf) or ""), "nume": nume, "tip": cdda_tip(nume, a.get(iucn), a.get(desig)),
                                        "sursa": "CDDA"}))
                    return out
    return None


# ---------- rezervă: GeoPackage-urile întregi ----------
def dav_files(folder):
    html = get(WEBDAV + folder + "/", raw=True, timeout=60)
    if not html:
        return []
    links = re.findall(r'href="([^"]+\.(?:gpkg|zip))"', html.decode("utf-8", "ignore"), re.I)
    return [urllib.parse.urljoin(WEBDAV + folder + "/", h) for h in links]


def gpkg_rows(folders, where_for):
    import io
    import zipfile
    import pyogrio
    import shapely
    from pyproj import Transformer
    for folder in folders:
        for url in dav_files(folder):
            log("Descarc", url)
            body = get(url, raw=True, timeout=1800, tries=2)
            if not body:
                continue
            path = C.OUT / url.rsplit("/", 1)[-1]
            C.OUT.mkdir(parents=True, exist_ok=True)
            if url.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(body)) as z:
                    inner = next((n for n in z.namelist() if n.lower().endswith(".gpkg")), None)
                    if not inner:
                        continue
                    path = C.OUT / inner.rsplit("/", 1)[-1]
                    path.write_bytes(z.read(inner))
            else:
                path.write_bytes(body)
            tr = Transformer.from_crs(3035, 4326, always_xy=True)
            for lname, gtype in pyogrio.list_layers(path):
                if gtype is None or "polygon" not in str(gtype).lower():
                    continue
                info = pyogrio.read_info(path, layer=lname)
                fs = [{"name": f} for f in info["fields"]]
                where = where_for(fs)
                if not where:
                    continue
                meta, _, geoms, data = pyogrio.raw.read(path, layer=lname, where=where)
                cols = dict(zip(meta["fields"], data))
                gs = shapely.transform(shapely.from_wkb(geoms), lambda xy: __import__("numpy").column_stack(tr.transform(xy[:, 0], xy[:, 1])))
                rows = [(clean(g), {k: (v[i].item() if hasattr(v[i], "item") else v[i]) for k, v in cols.items()}) for i, g in enumerate(gs)]
                log(f"  {lname}: {len(rows)} obiecte")
                REPORT["surse"].append({"gpkg": url, "strat": lname, "campuri": list(cols)})
                return [(g, a) for g, a in rows if g is not None], fs
    return None, None


def n2k_gpkg():
    rows, fs = gpkg_rows(N2K_DAV, lambda fs: (lambda c: f"{c} LIKE 'RO%'" if c else None)(field(fs, "SITECODE", r"site.?code")))
    if not rows:
        return None
    code, name = field(fs, "SITECODE", r"site.?code"), field(fs, "SITENAME", r"site.?name")
    out = {}
    for g, a in rows:
        c = str(a.get(code) or "")
        out.setdefault(c, (g, {"cod": c, "nume": modern(str(a.get(name) or "")), "sursa": "Natura 2000"}))
    return list(out.values())


def cdda_gpkg():
    rows, fs = gpkg_rows(CDDA_DAV, lambda fs: (lambda c: f"{c} = 'RO'" if c else None)(field(fs, "cddaCountryCode", r"country.?code")))
    if not rows:
        return None
    nm, idf = field(fs, "siteName", "name"), field(fs, "cddaId", "siteCode", "id")
    iucn, desig = field(fs, "iucnCategory", r"iucn"), field(fs, "designationTypeCode", r"designation.?type")
    out = []
    for g, a in rows:
        nume = modern(str(a.get(nm) or ""))
        REPORT["cdda_coduri"].setdefault(f"{a.get(desig)}|{a.get(iucn)}", []).append(nume)
        out.append((g, {"cod": str(a.get(idf) or ""), "nume": nume, "tip": cdda_tip(nume, a.get(iucn), a.get(desig)), "sursa": "CDDA"}))
    return out


# ---------- scrierea ----------
def n2k_tip(cod):
    return "sit Natura 2000 pentru păsări" if cod.startswith("ROSPA") else "sit Natura 2000"


def write(rows, path, tol, digits, keep):
    from shapely.geometry import mapping
    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], digits), round(c[1], digits)]
    feats = []
    for g, p in rows:
        s = g.simplify(tol, preserve_topology=True) if tol else g
        if s.is_empty:
            continue
        m = json.loads(json.dumps(mapping(s)))
        m["coordinates"] = rnd(m["coordinates"])
        feats.append({"type": "Feature", "properties": {k: p[k] for k in keep if p.get(k)}, "geometry": m})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "sursa": "EEA: Natura 2000 și arii protejate naționale (CDDA), CC BY 4.0",
                                "features": feats}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path.stat().st_size


def main():
    from . import romania
    n2k = n2k_rest() or n2k_gpkg()
    cdda = cdda_rest() or cdda_gpkg()
    if not n2k and not cdda:
        raise SystemExit("Nu am putut lua ariile protejate de la EEA.")
    rows = []
    for g, p in (n2k or []):
        p["tip"] = n2k_tip(p["cod"])
        rows.append((g, p))
    rows += cdda or []
    ro = romania.outline().buffer(0.05)
    rows = [(g, p) for g, p in rows if g.intersects(ro)]
    for _, p in rows:
        REPORT["tipuri"][p["tip"]] = REPORT["tipuri"].get(p["tip"], 0) + 1
    log("Arii:", REPORT["tipuri"])
    big = write(rows, C.DATA / "arii_ro.geojson", 0.0001, 5, ("cod", "nume", "tip", "sursa"))
    tol = 0.0007
    while True:
        small = write(rows, C.DOCS / "data" / "static" / "arii.geojson", tol, 4, ("cod", "nume", "tip"))
        if small < 4_000_000 or tol > 0.004:
            break
        tol *= 1.6
    log(f"Scris: data/arii_ro.geojson {big / 1e6:.1f} MB, docs/data/static/arii.geojson {small / 1e6:.1f} MB (toleranță {tol:.4f}°)")
    REPORT["cdda_coduri"] = {k: {"n": len(v), "exemple": v[:6]} for k, v in REPORT["cdda_coduri"].items()}
    C.OUT.mkdir(parents=True, exist_ok=True)
    (C.OUT / "arii_raport.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(REPORT, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
