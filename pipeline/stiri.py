"""Zonele noastre, în presă: a ajuns tăierea asta la știri? A constatat-o Garda Forestieră?

Harta spune ce se vede din satelit și ce scrie în registrul de autorizații. Dacă o tăiere a fost cu adevărat
ilegală se dovedește altundeva: în constatările Gărzii Forestiere, în dosare penale, și în presă. Aici căutăm
partea din presă, automat, și o punem lângă zonă, ca „verificat și din alte surse".

Pentru fiecare zonă care merită privită (roșie, sau în arie protejată) căutăm în Google News știri care numesc
localitatea și județul, cu cuvinte despre tăieri ilegale, apărute de la câteva săptămâni înainte de prima imagine
cu schimbarea până la șase luni după. O potrivire de nume de loc nu e o dovadă că e vorba de aceeași tăiere, de
aceea o numim „probabilă" și arătăm linkul: cititorul decide.

    python -m pipeline.stiri                 zonele roșii și cele din arii protejate, din ultimele 12 luni
    python -m pipeline.stiri --toate         toate zonele cu verdict
    python -m pipeline.stiri --limit 50      pentru probe

Scrie docs/data/stiri.json, în același format ca verificari.json (zone -> listă de surse), și tipărește
corelația: câte zone roșii au ajuns în presă, față de câte verzi (martorul).
"""
import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET

from . import config as C
from .permise import zone_site, OUT as PERMISE

OUT = C.DOCS / "data" / "stiri.json"
RSS = "https://news.google.com/rss/search?q={q}&hl=ro&gl=RO&ceid=RO:ro"
# doar cuvinte despre tăieri: „lemn", „pădure", „arbori", „ocol" singure prindeau biserici de lemn, urși în pădure, case arse
CUVINTE = ["tăier", "taier", "tăiat", "taiat", "defrișa", "defrisa", "exploatar", "drujb", "garda forestier", "masă lemnoas",
           "masa lemnoas", "bușteni", "busteni", "furt de lemn", "lemn furat", "tăietori", "taietori"]
ILEGAL = ["ilegal", "fără autorizație", "fara autorizatie", "fără aviz", "contraven", "dosar penal", "amend", "garda forestier",
          "furt de lemn", "braconaj", "sesizat", "confisc"]
PAUZA_S = 2.0          # între cereri; e un serviciu public, nu al nostru
ZILE_INAINTE = 30
ZILE_DUPA = 180


def _plain(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c)).lower()


def cauta(localitate, judet):
    q = f'"{localitate}" "{judet}" (tăieri OR tăiere OR defrișare OR lemn OR "Garda Forestieră")'
    url = RSS.format(q=urllib.parse.quote(q))
    try:
        import requests
        r = requests.get(url, timeout=30, headers={"User-Agent": "padurea-ro/1.0 (+https://github.com/iliemihai/padurea-ro)"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
    except Exception as e:
        print("  eroare la", localitate, judet, e, file=sys.stderr)
        return []
    out = []
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        src = it.find("{https://news.google.com/rss}source")
        sursa = (src.text if src is not None else "") or ""
        desc = html.unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or ""))
        try:
            data = dt.datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S").date()
        except Exception:
            data = None
        out.append({"titlu": t, "url": link, "data": data, "sursa": sursa, "text": desc})
    return out


def potriveste(a, stiri):
    """Știrile care chiar par despre o tăiere la locul și în perioada zonei."""
    loc = _plain(a.get("localitate") or "")
    jud = _plain(a.get("county") or "")
    fs = dt.date.fromisoformat(a["first_seen"])
    d0, d1 = fs - dt.timedelta(days=ZILE_INAINTE), fs + dt.timedelta(days=ZILE_DUPA)
    out = []
    for s in stiri:
        text = _plain(s["titlu"] + " " + s["text"])
        if loc and loc not in text:
            continue
        if not any(k in text for k in CUVINTE):
            continue
        if s["data"] and not (d0 <= s["data"] <= d1):
            continue
        tare = any(k in text for k in ILEGAL)
        out.append({"sursa": s["sursa"] or "presă", "tip": "stiri", "potrivire": "probabilă",
                    "url": s["url"], "data": s["data"].isoformat() if s["data"] else None,
                    "text": ("Știre despre tăieri la " + (a.get("localitate") or "") + (", " + a.get("county") if a.get("county") else "")
                             + (", " + s["data"].strftime("%d.%m.%Y") if s["data"] else "") + ": „" + s["titlu"][:140] + "”"
                             + (" Menționează ilegalitate, autorizații sau Garda Forestieră." if tare else " Nu e sigur că e vorba de aceeași tăiere.")),
                    "ilegal": tare})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--toate", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--luni", type=int, default=12, help="doar zonele din ultimele N luni")
    a = ap.parse_args(argv)

    zone = zone_site()
    verd = json.loads(PERMISE.read_text(encoding="utf-8")).get("zone", {}) if PERMISE.exists() else {}
    vechi = json.loads(OUT.read_text(encoding="utf-8")).get("zone", {}) if OUT.exists() else {}
    prag = (dt.date.today() - dt.timedelta(days=30 * a.luni)).isoformat()

    def merita(zid, z):
        if z["first_seen"] < prag or not z.get("localitate"):
            return False
        if a.toate:
            return zid in verd
        st = verd.get(zid, {}).get("stare")
        return st in ("fara", "neacoperit") or bool(z.get("arii"))

    tinta = {k: v for k, v in zone.items() if merita(k, v)}
    if a.limit:
        tinta = dict(list(tinta.items())[: a.limit])
    print(f"{len(tinta)} zone de căutat în presă")

    cache, rez, n = {}, dict(vechi), 0
    for zid, z in tinta.items():
        cheie = (z["localitate"], z.get("county"))
        if cheie not in cache:
            cache[cheie] = cauta(*cheie)
            time.sleep(PAUZA_S)
        gasite = potriveste(z, cache[cheie])
        if gasite:
            rez[zid] = gasite
            n += 1
        elif zid in rez:
            del rez[zid]
    OUT.write_text(json.dumps({"despre": "Știri care numesc locul și perioada zonei; potrivire probabilă, nu dovadă.",
                               "actualizat": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                               "zone": rez}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{n} zone cu știri -> {OUT}")

    # corelația: roșu vs verde (martor)
    def rata(stari):
        ids = [k for k, v in verd.items() if v.get("stare") in stari and k in zone and zone[k]["first_seen"] >= prag]
        cu = sum(1 for k in ids if k in rez)
        return cu, len(ids)
    r1, r2 = rata(("fara", "neacoperit")), rata(("acoperit",))
    print(f"\nCORELAȚIE (ultimele {a.luni} luni):")
    print(f"  zone roșii (fără autorizație valabilă): {r1[0]} din {r1[1]} au apărut în presă" + (f" ({100*r1[0]/r1[1]:.0f}%)" if r1[1] else ""))
    print(f"  zone verzi (cu autorizație), martor:    {r2[0]} din {r2[1]}" + (f" ({100*r2[0]/r2[1]:.0f}%)" if r2[1] else "") + "  (căutate doar dacă --toate)")
    print("  Presa scrie despre puține tăieri, oricât de ilegale; ce contează e dacă roșiile apar mai des decât verzile.")


if __name__ == "__main__":
    main()
