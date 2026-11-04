"""Compară o judecată cu etichetele oarbe. Folosire: python3 evaluare/compara.py JUDECATA ETICHETE CHEIE"""
import json, math, sys
from collections import Counter

J = json.load(open(sys.argv[1]))["zone"]
et = json.load(open(sys.argv[2]))
ch = json.load(open(sys.argv[3]))
TAIERE = {"taiere_rasa", "rarire"}

def wilson(k, n, z=1.96):
    if not n: return (0, 0)
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n); s = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return ((c - s)/d, (c + s)/d)
def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} = {100*k/n:.0f}% (IC {100*lo:.0f}–{100*hi:.0f})" if n else "–"

rows = []
for nn, e in et.items():
    c = ch[nn]; j = J.get(c["id"])
    rows.append((nn, c["id"], c["stare"], e, j))
lipsa = [r for r in rows if r[4] is None]
print("judecate:", len(rows) - len(lipsa), "lipsă:", len(lipsa))
rows = [r for r in rows if r[4]]

# acord judecător–eu pe „e tăiere?”
acord = sum((r[4]["categorie"] in TAIERE) == (r[3] in TAIERE) for r in rows if r[3] != "neclar")
n = sum(r[3] != "neclar" for r in rows)
print("acord pe tăiere/nu-tăiere (fără neclar):", pct(acord, n))
conf = Counter((r[3] in TAIERE, r[4]["categorie"] in TAIERE) for r in rows if r[3] != "neclar")
print("  eu=tăiere & AI=tăiere", conf[(True, True)], "| eu=tăiere & AI=nu", conf[(True, False)], "| eu=nu & AI=tăiere", conf[(False, True)], "| eu=nu & AI=nu", conf[(False, False)])

# roșiile de acum: ce-ar rămâne roșu cu noul judecător la diverse praguri
rosii = [r for r in rows if r[2] in ("fara", "neacoperit")]
print("\nroșii în eșantion:", len(rosii), "| din ele, tăieri după mine:", sum(r[3] in TAIERE for r in rosii), "| neclare:", sum(r[3] == "neclar" for r in rosii))
for thr in (0.5, 0.6, 0.7, 0.8):
    tin = [r for r in rosii if r[4]["categorie"] in TAIERE and r[4]["incredere"] >= thr and r[4].get("padure_inainte") != "nu"]
    k = sum(r[3] in TAIERE for r in tin); kc = sum(r[3] != "neclar" for r in tin)
    pierdute = sum(r[3] in TAIERE for r in rosii) - k
    print(f"  prag {thr}: rămân roșii {len(tin)}; precizie {pct(k, len(tin))}; fără neclar {pct(k, kc)}; tăieri reale scoase din roșu: {pierdute}")

print("\nunde nu ne potrivim (roșii):")
for r in rosii:
    if (r[4]["categorie"] in TAIERE) != (r[3] in TAIERE):
        print(f"  {r[0]} eu={r[3]:12s} AI={r[4]['categorie']} ({r[4]['incredere']}, {r[4].get('padure_inainte')}) {r[4]['motiv'][:150]}")
