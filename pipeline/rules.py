"""Regulile de publicare, aplicate pe măsurătorile salvate pentru fiecare zonă.

Detectorul prinde larg tot ce ar putea fi o tăiere. Aici hotărâm ce merge mai departe la analistul AI și pe hartă.
Fiind separate, regulile se pot regla și testa fără să mai citim imaginile din satelit.
"""
from . import config as C


def _num(x):
    return x is not None and x == x  # nu e None și nu e NaN


def leafless(f):
    """Referința de sezon a zonei era pădure fără frunze (iarnă, început de primăvară, sfârșit de toamnă)."""
    return _num(f.get("b_nd")) and f["b_nd"] < C.LEAFON_NDVI


def check(p):
    """Întoarce (trece, motiv). Motivul e scris pentru oameni."""
    f = p.get("f") or {}
    off = leafless(f)
    nb_max = C.RULE_NBR_NOW_MAX_OFF if off else C.RULE_NBR_NOW_MAX
    adj_min = C.RULE_ADJ_NBR_MIN_OFF if off else C.RULE_ADJ_NBR_MIN
    if p.get("neigh_drop", 0) > C.NEIGH_MAX:
        return False, "pădurea din jur a pierdut și ea verde (toamnă sau ceață)"
    if _num(f.get("nb")) and f["nb"] > nb_max:
        return False, "în infraroșu arată încă a vegetație, nu a sol gol (probabil frunze de toamnă)"
    if _num(f.get("adj_nb")) and f["adj_nb"] < adj_min:
        return False, "schimbarea nu iese în evidență față de pădurea din jur"
    if p.get("edge_frac", 0) > C.RULE_EDGE_MAX:
        return False, "doar o fâșie pe marginea pădurii (câmp, drum sau pajiște alături)"
    return True, ""


def split(patches):
    keep, out = [], []
    for p in patches:
        ok, why = check(p)
        if ok:
            keep.append(p)
        else:
            p["motiv"] = why
            out.append(p)
    return keep, out
