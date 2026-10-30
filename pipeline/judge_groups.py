"""Analistul AI pe zonele găsite de detector (out/group_*.json), după ce s-au făcut imaginile.

python -m pipeline.judge_groups
"""
import json

from . import config as C
from .judge import backend, judge
from .sat import log


def main():
    which = backend()
    img = C.OUT / "img"
    n = 0
    for f in sorted(C.OUT.glob("group_*.json")):
        g = json.loads(f.read_text())
        for p in g["patches"][:C.JUDGE_MAX_PER_GROUP] + g["rejected"][:6]:
            b, a = p.get("img_before"), p.get("img_after")
            if p.get("ai") or not a:
                continue
            try:
                p["ai"] = judge(img / b["file"] if b else None, img / a["file"], b["date"] if b else "?", a["date"], which)
                n += 1
                log(f"  {p['key']}: {p['ai']['categorie']} ({p['ai']['incredere']}) {p['ai']['secunde']}s - {p['ai']['motiv'][:90]}")
            except Exception as exc:
                log("  AI sărit pentru", p["key"], repr(exc)[:150])
        f.write_text(json.dumps(g, ensure_ascii=False))
    log(f"Analistul AI ({which}): {n} zone judecate")


if __name__ == "__main__":
    main()
