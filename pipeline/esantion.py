"""Un eșantion de zone roșii, de verificat de mână: câte sunt tăieri adevărate, fără autorizație?

Harta nu poate răspunde singură la întrebarea asta. Răspunsul vine dintr-un eșantion aleatoriu verificat om cu om:
pentru fiecare zonă, cineva se uită la pozele înainte/după, caută autorizațiile în Inspectorul Pădurii pe o rază
mai mare, și notează ce a găsit. Din 30-40 de zone verificate reiese cât de des avem dreptate (precizia).

    python -m pipeline.esantion                 30 de zone roșii, alese la întâmplare, cu aceeași sămânță
    python -m pipeline.esantion --n 40 --stare neacoperit
    python -m pipeline.esantion --seed 7

Scrie out/esantion_<stare>.csv cu o coloană goală `verdict_om` (taiere_fara_autorizatie / taiere_cu_autorizatie /
drum / nu_e_taiere / nu_pot_spune) și una `nota`. După completare:

    python -m pipeline.esantion --raport out/esantion_fara.csv
"""
import argparse
import csv
import json
import random

from . import config as C
from .permise import zone_site, OUT as PERMISE

VERDICTE_OM = ["taiere_fara_autorizatie", "taiere_cu_autorizatie", "drum", "nu_e_taiere", "nu_pot_spune"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--stare", default="fara", help="fara | neacoperit | probabil | acoperit")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--raport", help="CSV completat de om: scoate precizia")
    a = ap.parse_args(argv)
    if a.raport:
        return raport(a.raport)

    zone = zone_site()
    verd = json.loads(PERMISE.read_text(encoding="utf-8")).get("zone", {})
    cand = [zid for zid, v in verd.items() if v.get("stare") == a.stare and zid in zone]
    rnd = random.Random(a.seed)
    rnd.shuffle(cand)
    ales = cand[: a.n]
    out = C.OUT / f"esantion_{a.stare}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "judet", "localitate", "ha", "incredere", "ai", "prima_imagine", "ultima_intacta", "stare", "apv", "ocol",
                    "dist_m", "lat", "lon", "link_site", "link_inspectorul_padurii", "verdict_om", "nota"])
        for zid in ales:
            z, v = zone[zid], verd[zid]
            w.writerow([zid, z.get("county"), z.get("localitate"), z.get("ha"), z.get("incredere"), (z.get("ai") or {}).get("categorie"),
                        z.get("first_seen"), z.get("before_date") or (f"vara {z['vara']}" if z.get("vara") else ""),
                        v.get("stare"), v.get("apv"), v.get("ocol"), v.get("dist_m"), z.get("lat"), z.get("lon"),
                        f"https://iliemihai.github.io/padurea-ro/#a={zid}", "https://inspectorulpadurii.ro", "", ""])
    print(f"{len(ales)} zone «{a.stare}» din {len(cand)} -> {out}")
    print("Completează coloana verdict_om cu una din:", ", ".join(VERDICTE_OM))


def raport(path):
    import collections
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    done = [r for r in rows if r.get("verdict_om")]
    if not done:
        print("nicio zonă verificată încă"); return
    c = collections.Counter(r["verdict_om"] for r in done)
    n = len(done)
    print(f"{n} zone verificate de om, din {len(rows)}")
    for k in VERDICTE_OM:
        if c[k]:
            print(f"  {k:26s} {c[k]:3d}  ({100*c[k]/n:.0f}%)")
    sigure = [r for r in done if r["verdict_om"] != "nu_pot_spune"]
    if sigure:
        tp = sum(1 for r in sigure if r["verdict_om"] == "taiere_fara_autorizatie")
        p = tp / len(sigure)
        # interval de încredere ~95% (Wilson), ca să nu ne mințim cu un eșantion mic
        import math
        z = 1.96; m = len(sigure)
        centru = (p + z * z / (2 * m)) / (1 + z * z / m)
        marja = z * math.sqrt(p * (1 - p) / m + z * z / (4 * m * m)) / (1 + z * z / m)
        print(f"\nPrecizia «roșu = tăiere fără autorizație»: {100*p:.0f}%  (între {100*(centru-marja):.0f}% și {100*(centru+marja):.0f}%, la 95%)")
        print("Cu alte cuvinte: din zonele roșii de pe hartă, cam atâtea sunt ce spunem că sunt.")


if __name__ == "__main__":
    main()
