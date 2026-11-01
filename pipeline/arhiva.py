"""Arhiva pe luni, ca site-ul să rămână rapid oricât crește istoricul. Nimic nu se șterge.

docs/data/alerts.json             ce încarcă site-ul din start: zonele cu ultima schimbare în ultimele 90 de zile
docs/data/arhiva/AAAA-LL.json     restul, după luna în care au fost văzute prima dată:
                                    - zonele cu ultima schimbare mai veche de 90 de zile
                                    - zonele rămase „de confirmat” după 30 de zile; primesc "expirata": true
                                      și se văd pe site doar dacă cineva bifează arhiva
docs/data/arhiva/index.json       ce luni există și câte zone are fiecare

python -m pipeline.arhiva         reîmparte datele de acum (după data imaginilor din alerts.json)
"""
import datetime as dt
import json

from . import config as C

RECENT_DAYS = 90
CONFIRM_DAYS = 30
DIR = C.DOCS / "data" / "arhiva"


def last_activity(a):
    """Ultima schimbare văzută: prima observație sau ultima lărgire."""
    return max(a["first_seen"], a.get("extinsa") or a["first_seen"])


def month(a):
    return a["first_seen"][:7]


def split(alerts, until):
    """Întoarce (recente, de arhivat). Marchează "expirata" la cele rămase neconfirmate."""
    u = dt.date.fromisoformat(until)
    recent, old = [], []
    for a in alerts:
        age = (u - dt.date.fromisoformat(last_activity(a))).days
        expired = a.get("incredere") == "de confirmat" and age >= CONFIRM_DAYS
        if expired:
            a["expirata"] = True
        else:
            a.pop("expirata", None)
        (old if expired or age >= RECENT_DAYS else recent).append(a)
    return recent, old


def load():
    """Lunile din arhivă: {"2026-08": [zone], ...}."""
    months = {}
    if DIR.exists():
        for f in sorted(DIR.glob("????-??.json")):
            months[f.stem] = json.loads(f.read_text(encoding="utf-8")).get("alerts", [])
    return months


def order(alerts):
    return sorted(alerts, key=lambda a: (a["first_seen"], a["ha"]), reverse=True)


def save(months, generated):
    """Scrie doar lunile care s-au schimbat, ca istoricul din git să crească puțin; refăcut indexul."""
    DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for m in sorted(months):
        f = DIR / f"{m}.json"
        zone = order(months[m])
        if not zone:
            if f.exists():
                f.unlink()
            continue
        text = json.dumps({"luna": m, "alerts": zone}, ensure_ascii=False, separators=(",", ":"))
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8")
        lv = {}
        for a in zone:
            lv[a["incredere"]] = lv.get(a["incredere"], 0) + 1
        index.append({"luna": m, "n": len(zone), "expirate": sum(1 for a in zone if a.get("expirata")), "niveluri": lv,
                      "de_la": min(a["first_seen"] for a in zone), "pana_la": max(a["first_seen"] for a in zone)})
    (DIR / "index.json").write_text(json.dumps({"generated": generated, "luni": index}, ensure_ascii=False, separators=(",", ":")),
                                    encoding="utf-8")
    return index


def write_recent(path, doc, recent, until, window, generated):
    doc = dict(doc)
    doc.update({"generated": generated, "data_until": until, "window": window,
                "istoric_de_la": min(doc.get("istoric_de_la") or window[0], window[0]),
                "recent_de_la": (dt.date.fromisoformat(until) - dt.timedelta(days=RECENT_DAYS - 1)).isoformat(),
                "alerts": order(recent)})
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    path = C.DOCS / "data" / "alerts.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    months = load()
    everything = doc.get("alerts", []) + [a for zone in months.values() for a in zone]
    seen, unique = set(), []
    for a in everything:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)
    recent, old = split(unique, doc["data_until"])
    by_month = {}
    for a in old:
        by_month.setdefault(month(a), []).append(a)
    idx = save(by_month, doc.get("generated"))
    write_recent(path, doc, recent, doc["data_until"], doc.get("window") or [doc["data_until"]] * 2, doc.get("generated"))
    print(f"Recente: {len(recent)}; în arhivă: {len(old)} ({sum(i['expirate'] for i in idx)} rămase neconfirmate), luni: {[i['luna'] for i in idx]}")


if __name__ == "__main__":
    main()
