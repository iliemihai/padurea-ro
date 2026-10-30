"""Analistul AI pe zonele găsite de detector (out/group_*.json), după ce s-au făcut imaginile.

python -m pipeline.judge_groups
"""
import json
from concurrent.futures import ThreadPoolExecutor

from . import config as C
from .judge import backend, judge
from .sat import log


def box_of(p):
    """Unde e zona în imaginea mică (fracții 0–1: stânga, sus, dreapta, jos), ca s-o încadrăm cu roșu."""
    cb, b = p.get("chip_bbox"), p.get("bbox")
    if not cb or not b:
        return None
    w, h = cb[2] - cb[0], cb[3] - cb[1]
    return ((b[0] - cb[0]) / w, (cb[3] - b[3]) / h, (b[2] - cb[0]) / w, (cb[3] - b[1]) / h)


def main():
    which = backend()
    if which is None:
        log("Fără analist AI (nu există ANTHROPIC_API_KEY)")
        return
    img = C.OUT / "img"
    files = sorted(C.OUT.glob("group_*.json"))
    groups = [json.loads(f.read_text()) for f in files]
    todo = []
    for g in groups:
        conf = [p for p in g["patches"] if p.get("confirmed")][:C.JUDGE_MAX_PER_GROUP]
        ctrl = [p for p in g["rejected"] if p.get("confirmed")][:40]   # control: le judecăm și pe respinse
        todo += [p for p in conf + ctrl if p.get("img_after") and not p.get("ai")]

    def one(p):
        b, a = p.get("img_before"), p["img_after"]
        try:
            p["ai"] = judge(img / b["file"] if b else None, img / a["file"], b["date"] if b else "?", a["date"],
                            which, box=box_of(p))
        except Exception as exc:
            log("  AI sărit pentru", p.get("key"), repr(exc)[:150])

    with ThreadPoolExecutor(6 if which == "claude" else 1) as ex:
        list(ex.map(one, todo))
    for f, g in zip(files, groups):
        f.write_text(json.dumps(g, ensure_ascii=False))
    log(f"Analistul AI ({which}): {sum(1 for p in todo if p.get('ai'))} zone judecate")


if __name__ == "__main__":
    main()
