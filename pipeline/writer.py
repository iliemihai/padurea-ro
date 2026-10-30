"""Agentul 4, redactorul: textul public al fiecărei alerte. Spune ce se vede și când, fără acuzații."""
import datetime as dt

LUNI = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
        "septembrie", "octombrie", "noiembrie", "decembrie"]


def zi(s):
    d = dt.date.fromisoformat(s)
    return f"{d.day} {LUNI[d.month - 1]} {d.year}"


def ha(x):
    return f"{x:.1f}".replace(".", ",") + " ha"


def text(a):
    loc = ""
    if a.get("localitate"):
        loc = f" lângă {a['localitate']}" if (a.get("localitate_km") or 99) <= 8 else f" la {a['localitate_km']:.0f} km de {a['localitate']}".replace(".", ",")
    jud = f", județul {a['county']}" if a.get("county") else ""
    if a.get("before_date"):
        cand = f"Între {zi(a['before_date'])} și {zi(a['first_seen'])}"
    else:
        cand = f"Până pe {zi(a['first_seen'])}"
    s = [f"{cand}, pe aproximativ {ha(a['ha'])} de pădure{loc}{jud}, imaginile Sentinel-2 arată că vegetația a dispărut sau s-a schimbat puternic."]
    if a.get("n_dates", 0) >= 2:
        s.append(f"Schimbarea se vede în {a['n_dates']} imagini diferite.")
    else:
        s.append("Deocamdată schimbarea se vede într-o singură imagine.")
    ai = a.get("ai")
    if ai and ai.get("motiv"):
        s.append(f"Analistul AI: „{ai['motiv'].strip().rstrip('.')}.”")
    if a.get("vant"):
        s.append(f"În acel interval a fost vânt puternic în zonă (rafale de până la {a['rafala_kmh']} km/h), deci poate fi și o doborâtură.")
    hj = a.get("hansen_jur")
    if hj and hj.get("ani"):
        s.append("În jur s-a mai pierdut pădure în " + ", ".join(str(y) for y in hj["ani"]) + " (Hansen).")
    s.append("Nu știm dacă e o tăiere autorizată: autorizațiile nu sunt publice. E o schimbare care merită verificată.")
    return " ".join(s)


def apply(alerts):
    for a in alerts:
        a["text"] = text(a)
