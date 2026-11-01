"""Conturul României, din limitele județelor de pe hartă (docs/data/static/counties.geojson).

Îl folosim ca să arătăm pe hartă doar ce e în țară: punctele de foc, numele localităților, conturul.
"""
import json
from functools import lru_cache

from . import config as C


@lru_cache(maxsize=1)
def outline():
    """Un singur poligon (sau câteva, dacă sunt insule), fără crăpăturile dintre județe."""
    from shapely.geometry import Polygon, shape
    from shapely.ops import unary_union
    fc = json.loads((C.DOCS / "data" / "static" / "counties.geojson").read_text(encoding="utf-8"))
    u = unary_union([shape(f["geometry"]).buffer(0) for f in fc["features"]])
    u = u.buffer(0.002, join_style="mitre").buffer(-0.002, join_style="mitre")
    parts = [Polygon(p.exterior) for p in getattr(u, "geoms", [u]) if p.area > 1e-4]
    return unary_union(parts)


@lru_cache(maxsize=4)
def _prepared(margin):
    from shapely.prepared import prep
    return prep(outline().buffer(margin) if margin else outline())


def contains(lon, lat, margin=0.0):
    """margin, în grade: toleranța la graniță (orașele de pe Dunăre au punctul uneori chiar pe apă)."""
    from shapely.geometry import Point
    return _prepared(margin).contains(Point(lon, lat))
