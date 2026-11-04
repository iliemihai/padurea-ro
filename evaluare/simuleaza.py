"""Stările de pe hartă pentru eșantionul etichetat, dacă judecătorul ar fi cel din fișierul dat; precizia fiecărei stări.
Folosire (din rădăcina repo-ului): python3 evaluare/simuleaza.py JUDECATA ETICHETE CHEIE [prag ...]"""
import json, math, sys
from collections import Counter, defaultdict
sys.path.insert(0, ".")
import pipeline.permise as P
from pipeline.permise import zone_site

J = json.load(open(sys.argv[1]))["zone"]; et = json.load(open(sys.argv[2])); ch = json.load(open(sys.argv[3]))
if "etichete" in et:  # fișierul descărcat din pagina de etichetare: {id_zonă: {"et": ...}} -> {"001": eticheta}
    pe_id = {v["id"]: nn for nn, v in ch.items()}
    et = {pe_id[z]: e["et"] for z, e in et["etichete"].items() if z in pe_id}
    print(f"etichete de om: {len(et)} din {len(ch)} zone")
praguri = [float(x) for x in sys.argv[4:]] or [0.5, 0.6]
P.incarca_context()
baza = dict(P.JUDECATA)
zone = zone_site(None)
verd = json.load(open("docs/data/permise.json"))["zone"]
TAIERE = {"taiere_rasa", "rarire"}
NU_TAIERE = {"santier", "camp", "foc", "nimic", "pasune", "altceva"}
OK = {"fara": TAIERE, "neacoperit": TAIERE, "acoperit": TAIERE, "probabil": TAIERE,
      # „pășune, nu pădure": pe hartă spune în primul rând „nu e pădure tăiată"
      "vegetatie": NU_TAIERE, "nu_taiere": NU_TAIERE, "nejudecat": None}

def wilson(k, n, z=1.96):
    if not n: return (0, 0)
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n); s = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c - s)/d, (c + s)/d)
def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100*k/n:.0f}% (IC {100*lo:.0f}–{100*hi:.0f})" if n else "–"

for prag in praguri:
    P.PRAG_ROSU = {"": prag}
    P.JUDECATA = dict(baza); P.JUDECATA.update(J)
    g = defaultdict(list)
    for nn, e in et.items():
        zid = ch[nn]["id"]
        st, mo = P.clasifica(zone[zid], verd[zid])
        g["rosu" if st in ("fara", "neacoperit") else st].append((nn, e, mo))
    print(f"\n=== prag {prag}")
    for st, rows in sorted(g.items(), key=lambda x: -len(x[1])):
        ok = OK.get("fara" if st == "rosu" else st)
        lab = dict(Counter(e for _, e, _ in rows))
        if ok:
            k = sum(e in ok for _, e, _ in rows); kc = sum(e != "neclar" for _, e, _ in rows)
            print(f"  {st:10s} n={len(rows):3d}  corect {pct(k, len(rows))}  | fără neclar {pct(k, kc)}  | {lab}")
        else:
            print(f"  {st:10s} n={len(rows):3d}  | {lab}")
    # recall: din tăierile reale (după etichete) din zonele fără autorizație care să le acopere, câte ies roșii
    rosii = {r[0] for r in g["rosu"]}
    tai = [nn for nn, e in et.items() if e in TAIERE and P._stare_permis(zone[ch[nn]["id"]], verd[ch[nn]["id"]])[0] in ("fara", "neacoperit")]
    print(f"  tăieri reale fără autorizație care ies roșii (recall): {pct(sum(nn in rosii for nn in tai), len(tai))}")
    scapate = [(nn, et[nn], next(st for st, rows in g.items() if any(r[0] == nn for r in rows))) for nn in tai if nn not in rosii]
    if scapate:
        print("  scăpate:", ", ".join(f"{nn}({e}->{st})" for nn, e, st in scapate))
