"""Judecătorul cu context: AI-ul vede zona cu tot ce știm despre ea, nu doar două poze de 10 m.

Prima judecată (judge.py) primește doar perechea înainte/după și greșește exact unde omul ar greși fără hartă: o pășune
curățată, o fâșie de cale ferată, un câmp cosit arată toate ca „verde care dispare”. Aici îi dăm:
  - poza Esri de dinainte (0,3–1 m): se văd copacii unul câte unul;
  - perechea Sentinel-2 înainte/după (10 m) și o vedere largă, de 2 km, a imaginii de după: continuă fâșia? sunt câmpuri în jur?
  - fișa de context din peisaj.json: relief, ce e în jur, coronament, distanțe la drum/cale ferată/apă/sat, forma;
  - ce spune registrul de autorizații (permise.json).
și îi cerem o categorie fină, un verdict „a fost pădure închisă înainte?”, un motiv pentru om și unul tehnic.

    python -m pipeline.rejudeca                 zonele roșii, nejudecate și probabile, fără judecată nouă
    python -m pipeline.rejudeca --si-martori    plus un eșantion de zone verzi (martor pentru evaluare)
    python -m pipeline.rejudeca --full          le reface pe toate cele vizate
    python -m pipeline.rejudeca --ids ID ...    anumite zone

Scrie docs/data/judecata.json: {"zone": {id: {categorie, padure_inainte, incredere, motiv, detalii, model, intrari}}}.
Are nevoie de ANTHROPIC_API_KEY. Pozele Esri se iau doar pentru zonele vizate (câteva sute), nu pentru tot site-ul.
"""
import argparse
import base64
import datetime as dt
import io
import json
import os
import pathlib
import random
import time
import urllib.error

from PIL import Image, ImageDraw

from . import config as C
from .judge import _font, _post, _raw
from .permise import zone_site, OUT as PERMISE
from .peisaj import OUT as PEISAJ, FEL_T

OUT = C.DOCS / "data" / "judecata.json"

CATEGORII = ["taiere_rasa", "rarire", "pasune", "santier", "camp", "foc", "sezon_nori", "altceva", "neclar"]

PROMPT = """You are a remote-sensing analyst checking an automatic forest-change alert in Romania. You must decide what really
happened INSIDE THE ORANGE OUTLINE, and whether it was a closed forest before.

You get up to four pictures of the same place, labelled:
  1. "DETAILED BEFORE": a very high-resolution image (0.3–1 m per pixel) from {esri_date}. Individual tree crowns are visible. It is older than the change, so it shows what the land was.
  2. "BEFORE" ({d0}) and 3. "AFTER" ({d1}): Sentinel-2, about 10 m per pixel, natural colours. The change happened between these two dates.
  4. "AFTER, WIDE": the AFTER date again, but 2 km across, so you can see whether a strip continues beyond the outline, or whether the area sits among fields, a village, a river or inside a large forest.

Facts about the place (from public maps, not from the pictures):
{context}

Pick exactly one category:
- "taiere_rasa": trees were removed over an area that was closed forest before (clear-cut, logging, or windthrow). New bare soil, stumps or slash with sharp edges, skid trails.
- "rarire": the forest is still there but thinned: canopy opened, trees remain, soil visible between crowns.
- "pasune": scattered trees or shrubs on pasture/meadow were removed or the pasture was cleaned, scraped or burned; it was NOT a closed forest before (crowns separated by grass in DETAILED BEFORE).
- "santier": works, not forestry: a new road, railway, pipeline, power line, quarry, building site, dam or solar park. Usually a long narrow strip that continues outside the outline, or a geometric shape with machinery, gravel or buildings.
- "camp": agricultural land: ploughed, harvested or mowed field, orchard or vineyard. Rows, straight field edges, no tree crowns before.
- "foc": burn scar (black or dark brown with irregular edges, often with smoke in AFTER).
- "sezon_nori": nothing really changed: autumn colours, leafless or snowy forest, clouds, haze, shadow, or different light. The outline looks like the forest around it in AFTER, with the same canopy texture.
- "altceva": something else that is not a forest cut (water level, landslide, riverbed, scrub, built-up land).
- "neclar": the pictures do not allow a decision.

Also answer "padure_inainte": "da" if DETAILED BEFORE (or BEFORE, if no detailed image) shows closed forest canopy over most of the outline, "partial" if a mix of crowns and open ground, "nu" if open land with few or no trees.

Be strict about "taiere_rasa": it needs closed forest BEFORE and open ground AFTER with sharp edges. A wrong "taiere_rasa" publicly accuses someone of illegal logging, so when in doubt choose the other category or "neclar".

Check these traps, in order, before choosing "taiere_rasa":
 a) Season or light. Compare the outline with OTHER forest in "AFTER, WIDE". If whole hillsides or many patches far from the outline show the same brown, orange, purple or grey tone, it is autumn colour, leaf-off, snow, haze or shadow: "sezon_nori". This is the most common error from October to April (AFTER date {d1}). A real cut is a bare patch that stands out from forest that stays green.
 b) Fire. Dark brown to black, irregular, spreading over pasture and scrub as well as trees, often several patches in the wide view: "foc".
 c) Not closed forest before. In DETAILED BEFORE, if grass or soil shows between separate crowns, or the trees are shrubs, young regrowth, a hedge, orchard rows or a tree line along a field or a river bank, it is not a closed forest: "pasune", "camp" or "altceva". Tree canopy in 2000 below 40% and land cover with much pasture or cropland point the same way, but the detailed picture decides.
 d) Works. A strip that continues beyond the outline, a geometric platform, bright white or grey ground (gravel, rock), machinery, next to a road, railway, quarry or village edge: "santier".
 e) Fields. Straight edges that match neighbouring parcels, ploughing or harvest tone: "camp".
 f) Floodplain and wetlands near big rivers: water level and reed or willow colour change with the season; prefer "altceva" or "sezon_nori" unless a sharp rectangular cut is obvious.
 g) Nothing visible. If the outline looks the same in BEFORE and AFTER, or the "change" is only inside an existing clearing, answer "sezon_nori" or "altceva", not a cut.
Only when none of these applies, and the AFTER picture shows new bare ground, slash or stumps with sharp edges inside forest that stays green around it, answer "taiere_rasa" (or "rarire" when crowns remain).
Confidence: 0.8 or more only when the evidence is unmistakable in two pictures; 0.6 when plausible but one trap is possible; below 0.5 when guessing.

First write two or three short lines of reasoning in English going through the traps, then the JSON object with the keys:
  "categorie", "padure_inainte", "incredere" (0–1),
  "motiv": one or two plain sentences in Romanian for a reader with no technical background, saying what is seen and why that means this category (call the pictures «înainte», «după», «poza detaliată», and the area «zona marcată»),
  "detalii": one or two technical sentences in Romanian for a journalist: the visual evidence (edges, texture, colour, continuation outside the outline) and which facts above support or contradict it."""


# ---------------------------------------------------------------- pozele
def _esri(a, zoom=17):
    try:
        from .poza import poza, data_pozei
        bb = a.get("chip_bbox") or a["bbox"]
        im = poza(bb, zoom, pad=0.0, contur=None)
        meta = [m for m in data_pozei((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2) if m.get("SRC_DATE2")]
        meta.sort(key=lambda m: m.get("SRC_RES") or 99)
        d = dt.datetime.utcfromtimestamp(meta[0]["SRC_DATE2"] / 1000).strftime("%Y-%m-%d") if meta else "an unknown date"
        return im, d
    except Exception as e:
        print("  esri:", a["id"], repr(e)[:100], flush=True)
        return None, None


def _larg(cat, a, lat_m=1000):
    """Vederea largă (2 km) din imaginea de după, Sentinel-2, pentru context."""
    try:
        import math
        from .sat import search, read_chip, item_date
        d = dt.date.fromisoformat(a["after_date"])
        dlat = lat_m / 111320.0
        dlon = dlat / max(math.cos(math.radians(a["lat"])), 0.2)
        bb = [a["lon"] - dlon, a["lat"] - dlat, a["lon"] + dlon, a["lat"] + dlat]
        items = search(cat, "sentinel-2-l2a", bb, (d - dt.timedelta(days=1)).isoformat(), (d + dt.timedelta(days=1)).isoformat())
        items = [i for i in items if item_date(i) == d] or items
        if not items:
            return None
        rgb, clear = read_chip(items[0], bb, (400, 400))
        return Image.fromarray(rgb), bb
    except Exception as e:
        print("  larg:", a["id"], repr(e)[:100], flush=True)
        return None


def _contur(im, bb_img, a, color=(255, 120, 0), w=3):
    """Conturul zonei (bbox-ul ei) desenat pe o imagine care acoperă bb_img."""
    x0, y0, x1, y1 = bb_img
    bx0, by0, bx1, by1 = a["bbox"]
    W, H = im.size
    r = [(bx0 - x0) / (x1 - x0) * W, (y1 - by1) / (y1 - y0) * H, (bx1 - x0) / (x1 - x0) * W, (y1 - by0) / (y1 - y0) * H]
    ImageDraw.Draw(im).rectangle(r, outline=color, width=w)
    return im


def plansa(a, esri, esri_date, larg):
    """Până la patru imagini, etichetate, pe o singură planșă PNG."""
    S = 420
    panouri = []
    bb = a.get("chip_bbox")
    if esri is not None:
        panouri.append(("DETAILED BEFORE " + str(esri_date), _contur(esri.resize((S, S)), bb, a)))
    for key, lab in (("img_before", "BEFORE"), ("img_after", "AFTER")):
        inf = a.get(key)
        if not inf:
            continue
        im = Image.open(C.DOCS / "img" / inf["file"]).convert("RGB").resize((S, S), Image.LANCZOS)
        panouri.append((lab + " " + inf["date"], _contur(im, bb, a) if bb else im))
    if larg is not None:
        im, bbl = larg
        panouri.append(("AFTER, WIDE (2 km) " + a["after_date"], _contur(im.resize((S, S), Image.LANCZOS), bbl, a)))
    img = Image.new("RGB", (len(panouri) * (S + 12), S + 30), "white")
    d = ImageDraw.Draw(img)
    for i, (lab, im) in enumerate(panouri):
        img.paste(im, (i * (S + 12), 30))
        d.text((i * (S + 12) + 4, 6), lab, fill="black", font=_font(18))
    buf = io.BytesIO(); img.save(buf, "PNG")
    nume = {"DETAILED": "poza detaliată", "BEFORE": "înainte", "AFTER": "după", "AFTER,": "vederea largă"}
    return buf.getvalue(), [nume.get(p[0].split(" ")[0], p[0]) for p in panouri]


# ---------------------------------------------------------------- fișa de context
def fisa(a, p, v):
    r = []
    if p:
        if p.get("relief"):
            r.append(f"- relief: {p['relief']}, {p.get('alt_m')} m altitude, slope {p.get('panta_grade')}°")
        if p.get("wc_zona"):
            r.append("- land cover inside the outline (ESA WorldCover 2021): " + ", ".join(f"{k} {v}%" for k, v in p["wc_zona"].items()))
        if p.get("wc_jur"):
            r.append("- land cover within 500 m around: " + ", ".join(f"{k} {v}%" for k, v in p["wc_jur"].items()))
        if p.get("coronament2000") is not None:
            r.append(f"- tree canopy density in 2000 (Hansen): {p['coronament2000']}% inside, {p.get('coronament2000_jur')}% around (closed forest is usually above 60%)")
        o = p.get("osm") or {}
        nume = {"drum_mare": "major road", "drum": "any road or track", "drum_in_lucru": "road under construction/proposed", "cale_ferata": "railway",
                "cale_ferata_in_lucru": "railway under construction", "apa": "river or lake", "intravilan": "built-up area", "cariera": "quarry",
                "agricol_osm": "farmland/meadow (OSM)", "linie_electrica": "power line", "conducta": "pipeline"}
        for k, lab in nume.items():
            if k in o:
                r.append(f"- nearest {lab}: {o[k]['m']} m ({o[k]['ce']})")
        if p.get("alungire"):
            r.append(f"- shape of the flagged area: {p.get('lungime_m')} m long, {p.get('latime_m')} m wide (elongation {p['alungire']})")
        if p.get("fel"):
            r.append(f"- automatic landscape guess: {FEL_T.get(p['fel'], p['fel'])} ({p.get('fel_motiv')})")
    if a.get("ha"):
        r.append(f"- flagged area: {a['ha']} ha, seen changed in {a.get('n_dates')} satellite images")
    if a.get("arii"):
        r.append("- inside a protected area: " + ", ".join(x.get("nume", "") for x in a["arii"] if isinstance(x, dict))[:200])
    if v:
        st = v.get("stare")
        if v.get("apv"):
            r.append(f"- logging permit registry: nearest permit APV {v['apv']} ({v.get('ocol')}), {v.get('dist_m')} m away, overlap {int((v.get('suprapunere') or 0) * 100)}%, valid {v.get('start')} to {v.get('end')}; registry verdict: {st}")
        else:
            r.append("- logging permit registry: no permit found within 5 km for this period")
        if v.get("amenajament") is not None:
            r.append(f"- share of the outline inside published forest-management parcels: {int(v['amenajament'] * 100)}% (0% means pasture, riparian strip, or private forest without a published plan)")
    return "\n".join(r) if r else "- (no extra facts available)"


def _taie(t, n):
    """Taie la n caractere, dar la sfârșit de propoziție."""
    if len(t) <= n:
        return t
    cut = t[:n]
    k = max(cut.rfind(". "), cut.rfind(".\n"))
    return (cut[: k + 1] if k > n // 2 else cut).strip()


def _json_din(txt):
    """Primul obiect JSON complet din text (ignoră ``` și textul din jur)."""
    txt = txt.replace("```json", "").replace("```", "")
    dec = json.JSONDecoder()
    i = txt.find("{")
    while i != -1:
        try:
            j, _ = dec.raw_decode(txt, i)
            if isinstance(j, dict) and "categorie" in j:
                return j
        except ValueError:
            pass
        i = txt.find("{", i + 1)
    return None


# ---------------------------------------------------------------- întrebarea
def intreaba(png, a, context, esri_date, model=None):
    model = model or C.CLAUDE_MODEL
    text = PROMPT.format(esri_date=esri_date or "an unknown date", d0=(a.get("img_before") or {}).get("date", "?"), d1=(a.get("img_after") or {}).get("date", "?"), context=context)
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}},
               {"type": "text", "text": text}]
    headers = {"Content-Type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
    body = {"model": model, "max_tokens": 3000, "messages": [{"role": "user", "content": content}]}
    last = ""
    scurt = 0  # de câte ori am cerut un răspuns mai scurt / doar JSON
    for attempt in range(6):
        try:
            r = _post("https://api.anthropic.com/v1/messages", body, headers, timeout=180)
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode("utf-8", "replace")
            last = f"HTTP {exc.code}: {detail}"
            if exc.code in (429, 500, 502, 503, 529) and attempt < 5:
                time.sleep(8 * (attempt + 1)); continue
            raise RuntimeError(last)
        txt = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
        _raw({"model": model, "rejudeca": a["id"], "text": txt, "stop": r.get("stop_reason")})
        j = _json_din(txt)
        if not j or r.get("stop_reason") == "max_tokens":
            # răspuns tăiat sau fără JSON valid: mai cerem o dată, explicit doar JSON și mai scurt
            if scurt < 2:
                scurt += 1
                body["messages"] = [{"role": "user", "content": content + [{"type": "text", "text":
                    "Răspunde NUMAI cu obiectul JSON cerut, fără text în afara lui și fără ```; «motiv» sub 400 de caractere, «detalii» sub 700."}]}]
                continue
            raise RuntimeError("fără JSON: " + txt[:160])
        cat = str(j.get("categorie", "neclar")).strip().lower()
        pi = str(j.get("padure_inainte", "")).strip().lower()
        try:
            conf = max(0.0, min(1.0, float(j.get("incredere", 0.5))))
        except (TypeError, ValueError):
            conf = 0.5
        return {"categorie": cat if cat in CATEGORII else "neclar", "padure_inainte": pi if pi in ("da", "partial", "nu") else None,
                "incredere": round(conf, 2), "motiv": _taie(str(j.get("motiv", "")), 450), "detalii": _taie(str(j.get("detalii", "")), 800), "model": model}
    raise RuntimeError(last)


def main(argv=None):
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--si-martori", action="store_true", help="și un eșantion de zone verzi, pentru evaluare")
    ap.add_argument("--martori", type=int, default=60)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--fara-esri", action="store_true")
    ap.add_argument("--fara-larg", action="store_true")
    ap.add_argument("--model", help="modelul (implicit config.CLAUDE_MODEL)")
    ap.add_argument("--out", help="fișierul de ieșire (implicit docs/data/judecata.json)")
    ap.add_argument("--planse", help="doar planșele + fișa neutră, pentru evaluare oarbă, în acest director (fără model)")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    if not os.environ.get("ANTHROPIC_API_KEY") and not args.planse:
        raise SystemExit("lipsește ANTHROPIC_API_KEY")

    zone = zone_site()
    verd = json.loads(PERMISE.read_text(encoding="utf-8")).get("zone", {}) if PERMISE.exists() else {}
    peis = json.loads(PEISAJ.read_text(encoding="utf-8")).get("zone", {}) if PEISAJ.exists() else {}
    vechi = json.loads(OUT.read_text(encoding="utf-8")).get("zone", {}) if OUT.exists() else {}

    if args.planse:
        return planse_oarbe(args, zone, verd, peis)
    if args.out:
        OUT = pathlib.Path(args.out)
        vechi = json.loads(OUT.read_text(encoding="utf-8")).get("zone", {}) if OUT.exists() else {}

    if args.ids:
        tinta = [k for k in args.ids if k in zone]
    else:
        tinta = [k for k, v in verd.items() if v.get("stare") in ("fara", "neacoperit", "nejudecat", "probabil") and k in zone and zone[k].get("img_after")]
        if args.si_martori:
            verzi = [k for k, v in verd.items() if v.get("stare") == "acoperit" and k in zone and zone[k].get("img_after")]
            random.seed(7); tinta += random.sample(verzi, min(args.martori, len(verzi)))
        if not args.full:
            tinta = [k for k in tinta if k not in vechi]
    tinta.sort(key=lambda k: zone[k]["first_seen"], reverse=True)
    if args.limit:
        tinta = tinta[: args.limit]
    print(f"{len(tinta)} zone de judecat, {len(vechi)} deja judecate", flush=True)

    cat = None
    if not args.fara_larg:
        try:
            from .sat import client
            cat = client()
        except Exception as e:
            print("fără Planetary Computer:", repr(e)[:100], flush=True)

    rez, n, t0 = dict(vechi), 0, time.time()
    for zid in tinta:
        a = zone[zid]
        esri, esri_date = (None, None) if args.fara_esri else _esri(a)
        larg = None if cat is None else _larg(cat, a)
        png, intrari = plansa(a, esri, esri_date, larg)
        context = fisa(a, peis.get(zid), verd.get(zid))
        try:
            j = intreaba(png, a, context, esri_date, model=args.model)
        except Exception as e:
            print("  eroare la", zid, repr(e)[:160], flush=True); continue
        j["intrari"] = intrari
        j["esri_data"] = esri_date
        j["cand"] = dt.date.today().isoformat()
        rez[zid] = j
        n += 1
        print(f"  {n}/{len(tinta)} {zid} {j['categorie']} ({j['padure_inainte']}, {j['incredere']}): {j['motiv'][:110]}", flush=True)
        if n % 20 == 0:
            OUT.write_text(json.dumps({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "zone": rez}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "zone": rez}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    from collections import Counter
    print(f"{n} judecate în {int(time.time() - t0)} s -> {OUT}; categorii: {dict(Counter(v['categorie'] for v in rez.values()))}", flush=True)


def planse_oarbe(args, zone, verd, peis):
    """Eșantion stratificat pe stările de acum (60 roșii, 15 vegetație, 15 nu_taiere, 10 acoperit), amestecat.
    Scrie NN.png (planșa) și NN.txt (fișa fără registru și fără ghicirea de peisaj), plus cheie.json separat."""
    rnd = random.Random(args.seed)
    ids = []
    for stari, n in ((("fara", "neacoperit"), 60), (("vegetatie",), 15), (("nu_taiere",), 15), (("acoperit",), 10)):
        c = [k for k, v in verd.items() if v.get("stare") in stari and k in zone and zone[k].get("img_after")]
        ids += rnd.sample(c, min(n, len(c)))
    rnd.shuffle(ids)
    if args.limit:
        ids = ids[: args.limit]
    out = pathlib.Path(args.planse); out.mkdir(parents=True, exist_ok=True)
    cat = None
    if not args.fara_larg:
        try:
            from .sat import client
            cat = client()
        except Exception as e:
            print("fără Planetary Computer:", repr(e)[:100], flush=True)
    cheie = {}
    for i, zid in enumerate(ids, 1):
        a = zone[zid]
        esri, esri_date = (None, None) if args.fara_esri else _esri(a)
        larg = None if cat is None else _larg(cat, a)
        png, intrari = plansa(a, esri, esri_date, larg)
        (out / f"{i:03d}.png").write_bytes(png)
        p = dict(peis.get(zid) or {}); p.pop("fel", None); p.pop("fel_motiv", None)
        (out / f"{i:03d}.txt").write_text(f"Esri: {esri_date}; S2 înainte {(a.get('img_before') or {}).get('date')} / după {(a.get('img_after') or {}).get('date')}\n" + fisa(a, p, None), encoding="utf-8")
        cheie[f"{i:03d}"] = {"id": zid, "stare": verd[zid].get("stare"), "motiv": verd[zid].get("motiv")}
        print(f"  {i}/{len(ids)} {zid}", flush=True)
    (out / "cheie.json").write_text(json.dumps(cheie, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(ids)} planșe -> {out}", flush=True)


if __name__ == "__main__":
    main()
