"""Agentul 3, criticul: pune dovezile cap la cap și dă un nivel de încredere. Reguli simple și vizibile."""
import datetime as dt

AI_FALS = {"nori": "AI-ul vede nori", "toamna": "AI-ul vede doar frunze de toamnă", "agricol": "AI-ul vede teren agricol"}
AI_DA = {"taiere": "AI-ul vede pădure dispărută", "incendiu": "AI-ul vede o zonă arsă"}
GAP_MAX = 40   # zile între „ultima dată intactă" și „prima dată schimbată" peste care nu mai știm bine când
VIS_TXT = {
    "deschisa": "în poza de dinainte zona era deja mai luminoasă decât pădurea din jur: luminiș, pajiște sau drum, nu pădure tăiată acum",
    "nevazut": "în poze, zona nu se schimbă vizibil mai mult decât pădurea din jur",
    "vizibil": "în poze, zona se schimbă vizibil față de pădurea din jur",
}


def _days(a, b):
    try:
        return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
    except (TypeError, ValueError):
        return None


def _autumn_only(a):
    from .detect import autumn
    first, last = a.get("first_seen"), a.get("after_date") or a.get("first_seen")
    return bool(first) and autumn(first) and autumn(last) and first[:4] == last[:4]


def score(a):
    from . import config as C
    n = a.get("n_dates", 0) or 0
    if n < C.CONFIRM_DATES:   # și pentru zonele vechi, confirmate pe vremea când ajungeau 2 imagini
        a["confirmed"] = False
        return "de confirmat", 0, [("văzută schimbată într-o singură imagine" if n <= 1 else f"văzută schimbată în {n} imagini")
                                   + f"; o confirmăm de la {C.CONFIRM_DATES}"]
    a["confirmed"] = True
    if not a.get("img_before"):
        return "de confirmat", 0, [f"văzută schimbată în {a['n_dates']} imagini diferite",
                                   "nu avem încă o imagine clară cu zona dinainte, deci nu o putem arăta"]
    s, why = 2, [f"văzută schimbată în {a['n_dates']} imagini diferite"]
    if a.get("ha", 0) >= 3:
        s += 1; why.append("peste 3 ha")
    if a.get("neigh_drop", 1) < 0.05:
        s += 1; why.append("pădurea din jur e neschimbată")
    fi = a.get("firms") or {}
    if fi.get("n"):
        s += 2
        cand = fi["prima"] if fi["prima"] == fi["ultima"] else f"{fi['prima']} – {fi['ultima']}"
        why.append(f"sateliții NASA (FIRMS) au văzut foc la {fi['dist_m']} m de zonă, pe {cand}")
    gap = _days(a.get("before_date"), a.get("first_seen"))
    if gap is not None and gap > GAP_MAX:
        s -= 1; why.append(f"ultima imagine cu zona intactă e cu {gap} de zile înainte, deci nu știm bine când s-a schimbat")
    elif gap is None and a.get("vara"):
        s -= 1; why.append(f"ultima dată am văzut-o intactă în vara lui {a['vara']} (de atunci, nori sau zăpadă)")
    ai = a.get("ai")
    if ai:
        c, conf = ai["categorie"], ai.get("incredere", 0.5)
        if c in AI_DA:
            s += 2 if conf >= 0.6 else 1; why.append(AI_DA[c])
        elif c in AI_FALS:
            s -= 3 if conf >= 0.6 else 1; why.append(AI_FALS[c])
        else:
            s -= 1; why.append("AI-ul nu se poate pronunța")
    else:
        why.append("fără părerea AI")
    level = "ridicată" if s >= 5 else ("medie" if s >= 3 else "scăzută")
    # văzută schimbată doar toamna: frunzele care se îngălbenesc mai devreme decât anul trecut arată la fel
    if _autumn_only(a):
        level = "scăzută"
        why.append("văzută schimbată doar toamna, când și frunzele care se îngălbenesc pot arăta așa; o urmărim și primăvara")
    # ce se vede în poze are ultimul cuvânt: dacă pozele nu arată o pădure care dispare, nu dăm încredere
    vis = (a.get("vis") or {}).get("verdict")
    if vis in VIS_TXT:
        why.append(VIS_TXT[vis])
        if vis != "vizibil":
            level = "scăzută"
    return level, s, why


def apply(alerts):
    for a in alerts:
        a["incredere"], a["scor"], a["dovezi"] = score(a)
        a["vant"] = bool(a.get("rafala_kmh") and a["rafala_kmh"] >= 70)
