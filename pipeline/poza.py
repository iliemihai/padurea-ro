"""Poza „ce era înainte”: imaginea detaliată Esri World Imagery pentru o zonă de pe site, lipită din plăci.

Sentinel-2 are 10 m pe pixel și găsește tăierea; Esri (0,3–1 m, poze de acum 1–4 ani) arată ce era acolo înainte:
pădure bătrână, pășune cu copaci răzleți sau tăieri mai vechi. Scriptul descarcă plăcile din jurul zonei, le lipește,
desenează conturul zonei și întreabă metadatele Esri de când e poza.

    python -m pipeline.poza 20260828_45365_22085 [alt_id ...]   -> out/poza_<id>.jpg
    python -m pipeline.poza --bbox 22.07,45.35,22.12,45.39       -> out/poza_bbox.jpg
"""
import argparse
import io
import json
import math
import sys

import requests
from PIL import Image, ImageDraw

from . import config as C

TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
META = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/4/query"
UA = {"User-Agent": "padurea-ro/1.0 (+https://github.com/iliemihai/padurea-ro)"}


def _xy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def poza(bbox, z=17, pad=0.25, contur=None):
    w, s, e, n = bbox
    dw, dh = (e - w) * pad, (n - s) * pad
    w, s, e, n = w - dw, s - dh, e + dw, n + dh
    x0, y1 = _xy(w, s, z)
    x1, y0 = _xy(e, n, z)
    tx0, tx1, ty0, ty1 = int(x0), int(x1), int(y0), int(y1)
    im = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            r = requests.get(TILE.format(z=z, x=tx, y=ty), timeout=30, headers=UA)
            r.raise_for_status()
            im.paste(Image.open(io.BytesIO(r.content)).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    # tai la bbox-ul cerut
    l, t = (x0 - tx0) * 256, (y0 - ty0) * 256
    rr, b = (x1 - tx0) * 256, (y1 - ty0) * 256
    im = im.crop((int(l), int(t), int(rr), int(b)))
    if contur:
        d = ImageDraw.Draw(im)
        cw, cs, ce, cn = contur
        px = lambda lon, lat: ((_xy(lon, lat, z)[0] - x0) * 256, (_xy(lon, lat, z)[1] - y0) * 256)
        d.rectangle([px(cw, cn), px(ce, cs)], outline=(255, 90, 40), width=4)
    return im


def data_pozei(lon, lat):
    try:
        r = requests.get(META, timeout=30, headers=UA, params={
            "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "SRC_DATE2,SRC_RES,SRC_DESC,NICE_DESC", "returnGeometry": "false", "f": "json"})
        feats = r.json().get("features") or []
        return [f["attributes"] for f in feats]
    except Exception as e:
        return [{"eroare": str(e)}]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--bbox", help="W,S,E,N în grade")
    ap.add_argument("--zoom", type=int, default=17)
    a = ap.parse_args(argv)
    out = C.ROOT / "out"
    out.mkdir(exist_ok=True)
    cereri = []
    if a.bbox:
        bb = [float(v) for v in a.bbox.split(",")]
        cereri.append(("bbox", bb, None))
    if a.ids:
        from .permise import zone_site
        zone = zone_site()
        for zid in a.ids:
            z = zone.get(zid)
            if not z:
                print("nu găsesc zona", zid, file=sys.stderr)
                continue
            cereri.append((zid, z.get("chip_bbox") or z["bbox"], z["bbox"]))
    for nume, bb, contur in cereri:
        im = poza(bb, a.zoom, contur=contur)
        im.save(out / f"poza_{nume}.jpg", quality=88)
        meta = data_pozei((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
        (out / f"poza_{nume}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
        print(nume, im.size, meta)


if __name__ == "__main__":
    main()
