"""Unde stau zonele, ca site-ul să rămână rapid oricât crește istoricul.

docs/data/alerts.json             ce încarcă site-ul din start: zonele cu ultima schimbare în ultimele 90 de zile
docs/data/arhiva/AAAA-LL.json     zonele publice mai vechi, după luna în care au fost văzute prima dată
docs/data/arhiva/index.json       ce luni există și câte zone are fiecare
data/neconfirmate.json            zonele „de confirmat” (văzute într-o singură imagine sau fără poză de dinainte).
                                  Nu apar pe site: testul pe 2025 a arătat că doar 0,5% din ele sunt tăieri.
                                  Le ținem CONFIRM_DAYS zile; dacă le vedem iar, devin publice. Altfel le uităm
                                  (la testul pe trecut, PADUREA_EXPIRED le păstrează ca să le putem număra).

python -m pipeline.arhiva         reîmparte datele de acum (după data imaginilor din alerts.json)
python -m pipeline.arhiva --rescore   și refă înainte nivelurile și textele (după o schimbare a regulilor)
"""
import datetime as dt
import json
import math

from . import config as C

RECENT_DAYS = 90
CONFIRM_DAYS = 30
DIR = C.DOCS / "data" / "arhiva"
PENDING = "de confirmat"


def safe(o):
    """NaN și infinit nu sunt JSON valid: browserul refuză tot fișierul. Le facem null."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: safe(v) for k, v in o.items()}
    if isinstance(o, list):
        return [safe(v) for v in o]
    return o


def dumps(o):
    return json.dumps(safe(o), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def last_activity(a):
    """Ultima schimbare văzută: prima observație sau ultima lărgire."""
    return max(a["first_seen"], a.get("extinsa") or a["first_seen"])


def month(a):
    return a["first_seen"][:7]


def split(alerts, until):
    """Întoarce (recente, de arhivat, neconfirmate, expirate)."""
    u = dt.date.fromisoformat(until)
    recent, old, pending, expired = [], [], [], []
    for a in alerts:
        a.pop("expirata", None)
        age = (u - dt.date.fromisoformat(last_activity(a))).days
        if a.get("incredere") == PENDING:
            (expired if age >= CONFIRM_DAYS else pending).append(a)
        else:
            (old if age >= RECENT_DAYS else recent).append(a)
    return recent, old, pending, expired


def load():
    """Lunile din arhivă: {"2026-08": [zone], ...}."""
    months = {}
    if DIR.exists():
        for f in sorted(DIR.glob("????-??.json")):
            months[f.stem] = json.loads(f.read_text(encoding="utf-8")).get("alerts", [])
    return months


def load_pending():
    return json.loads(C.PENDING.read_text(encoding="utf-8")).get("alerts", []) if C.PENDING.exists() else []


def order(alerts):
    return sorted(alerts, key=lambda a: (a["first_seen"], a["ha"]), reverse=True)


def save(months, generated):
    """Scrie doar lunile care s-au schimbat, ca istoricul din git să crească puțin; reface indexul."""
    DIR.mkdir(parents=True, exist_ok=True)
    index = []
    for m in sorted(months):
        f = DIR / f"{m}.json"
        zone = order(months[m])
        if not zone:
            if f.exists():
                f.unlink()
            continue
        text = dumps({"luna": m, "alerts": zone})
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8")
        lv = {}
        for a in zone:
            lv[a["incredere"]] = lv.get(a["incredere"], 0) + 1
        index.append({"luna": m, "n": len(zone), "niveluri": lv,
                      "de_la": min(a["first_seen"] for a in zone), "pana_la": max(a["first_seen"] for a in zone)})
    (DIR / "index.json").write_text(dumps({"generated": generated, "luni": index}), encoding="utf-8")
    return index


def save_pending(pending, expired, generated):
    """Zonele neconfirmate, fără poze (pozele vin când sunt văzute iar). Cele expirate se uită, în afară de testul pe trecut."""
    drop = []
    for a in pending + expired:
        for k in ("img_before", "img_after"):
            info = a.pop(k, None)
            if info and info.get("file"):
                drop.append(info["file"])
        for k in ("vis", "text", "dovezi"):   # textul și dovezile se refac la fiecare rulare
            a.pop(k, None)
    C.PENDING.parent.mkdir(parents=True, exist_ok=True)
    C.PENDING.write_text(dumps({"generated": generated, "alerts": order(pending)}), encoding="utf-8")
    if C.EXPIRED and expired:
        old = json.loads(C.EXPIRED.read_text(encoding="utf-8")).get("alerts", []) if C.EXPIRED.exists() else []
        C.EXPIRED.write_text(dumps({"alerts": old + expired}), encoding="utf-8")
    img = C.DOCS / "img"
    for f in drop:
        (img / f).unlink(missing_ok=True)
    return len(drop)


def write_recent(path, doc, recent, until, window, generated):
    doc = dict(doc)
    doc.update({"generated": generated, "data_until": until, "window": window,
                "istoric_de_la": min(doc.get("istoric_de_la") or window[0], window[0]),
                "recent_de_la": (dt.date.fromisoformat(until) - dt.timedelta(days=RECENT_DAYS - 1)).isoformat(),
                "alerts": order(recent)})
    path.write_text(dumps(doc), encoding="utf-8")


def main():
    import sys
    path = C.DOCS / "data" / "alerts.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    months = load()
    everything = doc.get("alerts", []) + [a for zone in months.values() for a in zone] + load_pending()
    seen, unique = set(), []
    for a in everything:
        if a["id"] not in seen:
            seen.add(a["id"])
            unique.append(a)
    if "--rescore" in sys.argv:
        from . import critic, writer
        before = {a["id"]: a.get("incredere") for a in unique}
        critic.apply(unique)
        writer.apply(unique)
        moved = sum(1 for a in unique if a.get("incredere") != before[a["id"]])
        print(f"Niveluri refăcute: {moved} zone și-au schimbat nivelul")
    recent, old, pending, expired = split(unique, doc["data_until"])
    by_month = {m: [] for m in months}
    for a in old:
        by_month.setdefault(month(a), []).append(a)
    idx = save(by_month, doc.get("generated"))
    n_img = save_pending(pending, expired, doc.get("generated"))
    write_recent(path, doc, recent, doc["data_until"], doc.get("window") or [doc["data_until"]] * 2, doc.get("generated"))
    print(f"Pe site: {len(recent)} recente, {len(old)} în arhivă (luni: {[i['luna'] for i in idx]}); "
          f"neconfirmate: {len(pending)} în așteptare, {len(expired)} uitate; {n_img} poze scoase")


if __name__ == "__main__":
    main()
