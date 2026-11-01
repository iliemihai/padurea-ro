"""Agentul 4, redactorul: textul public al fiecărei alerte. Spune ce se vede și când, fără acuzații."""
import datetime as dt

from .uat import ro

GEN = {"comuna": "comunei", "orașul": "orașului", "municipiul": "municipiului", "sectorul": "sectorului"}

LUNI = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
        "septembrie", "octombrie", "noiembrie", "decembrie"]


def zi(s):
    d = dt.date.fromisoformat(s)
    return f"{d.day} {LUNI[d.month - 1]} {d.year}"


def ha(x):
    return f"{x:.1f}".replace(".", ",") + " ha"


def unde(a):
    """Unde e zona, în cuvinte: comuna (din limitele UAT), satul apropiat dacă e altul, județul."""
    u = a.get("uat") or {}
    sat = ro(a.get("localitate"))
    aproape = (a.get("localitate_km") or 99) <= 8
    if u:
        s = f" din {u['tip']} {u['nume']}" if not u.get("aproape") else f" de la marginea {GEN.get(u['tip'], u['tip'])} {u['nume']}"
        if sat and aproape and sat != u["nume"]:
            s += f", lângă {sat}"
        judet = u.get("judet") or a.get("county")
        return s + (f", județul {judet}" if judet and u["tip"] != "sectorul" else "")
    loc = ""
    if sat:
        loc = f" lângă {sat}" if aproape else f" la {a['localitate_km']:.0f} km de {sat}".replace(".", ",")
    return loc + (f", județul {a['county']}" if a.get("county") else "")


def text(a):
    if a.get("before_date"):
        cand = f"Între {zi(a['before_date'])} și {zi(a['first_seen'])}"
    else:
        cand = f"Până pe {zi(a['first_seen'])}"
    s = [f"{cand}, pe aproximativ {ha(a['ha'])} de pădure{unde(a)}, imaginile Sentinel-2 arată că vegetația a dispărut sau s-a schimbat puternic."]
    if a.get("n_dates", 0) >= 2:
        s.append(f"Schimbarea se vede în {a['n_dates']} imagini diferite.")
    else:
        s.append("Deocamdată schimbarea se vede într-o singură imagine.")
    ai = a.get("ai")
    fi = a.get("firms") or {}
    if fi.get("n"):
        cand = zi(fi["prima"]) if fi["prima"] == fi["ultima"] else f"între {zi(fi['prima'])} și {zi(fi['ultima'])}"
        s.append(f"Sateliții NASA (FIRMS) au văzut foc la {fi['dist_m']} m de zonă, {('pe ' + cand) if fi['prima'] == fi['ultima'] else cand}.")
    if a.get("vant"):
        s.append(f"În acel interval a fost vânt puternic în zonă (rafale de până la {a['rafala_kmh']} km/h), deci poate fi și o doborâtură.")
    hj = a.get("hansen_jur")
    if hj and hj.get("ani"):
        s.append("În jur s-a mai pierdut pădure în " + ", ".join(str(y) for y in hj["ani"]) + " (Hansen).")
    if (ai and ai.get("categorie") == "incendiu") or fi.get("n"):
        s.append("Nu știm ce a provocat schimbarea. E o schimbare care merită verificată.")
    else:
        s.append("Nu am verificat dacă există o autorizație de exploatare (unele se pot căuta în aplicația Inspectorul Pădurii). E o schimbare care merită verificată.")
    return " ".join(s)


def apply(alerts):
    for a in alerts:
        a["text"] = text(a)
