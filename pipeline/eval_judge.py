"""Testăm judecătorul AI pe alertele verificate la ochi. Scrie un tabel cu ce a zis fiecare model.

python -m pipeline.eval_judge qwen3.5:4b qwen3-vl:4b [claude]
"""
import json
import os
import sys
import time

from . import config as C
from .judge import judge

LAB = C.DATA / "labels"


def run(model_spec, labels):
    which = "claude" if model_spec == "claude" else "local"
    model = None if which == "claude" else model_spec
    rows = []
    for k, v in labels.items():
        b, a = v.get("before"), v.get("after")
        if not a:
            continue
        try:
            r = judge(LAB / b["file"] if b else None, LAB / a["file"], b["date"] if b else "?", a["date"], which, model)
        except Exception as exc:
            r = {"categorie": "eroare", "incredere": 0, "motiv": repr(exc)[:120], "secunde": 0, "model": model_spec}
        rows.append({"id": k, "noi": v["eticheta"], **r})
        print(f"{model_spec:14} {k:12} noi={v['eticheta']:8} model={r['categorie']:8} {r['incredere']:.2f} {r['secunde']:5.1f}s  {r['motiv'][:70]}", flush=True)
    clear = [r for r in rows if r["noi"] != "neclar"]
    ok = sum(r["categorie"] == r["noi"] for r in clear)
    cuts = [r for r in clear if r["noi"] == "taiere"]
    false = [r for r in clear if r["noi"] != "taiere"]
    summary = {
        "model": model_spec, "corecte": ok, "total": len(clear),
        "taieri_gasite": sum(r["categorie"] == "taiere" for r in cuts), "taieri": len(cuts),
        "false_eliminate": sum(r["categorie"] != "taiere" for r in false), "false": len(false),
        "sec_medie": round(sum(r["secunde"] for r in rows) / max(1, len(rows)), 1),
    }
    return summary, rows


def main():
    labels = json.loads((LAB / "labels.json").read_text())["etichete"]
    specs = sys.argv[1:] or [C.LOCAL_MODEL]
    out = []
    for s in specs:
        if s == "claude" and not os.environ.get("ANTHROPIC_API_KEY"):
            print("claude: lipsește ANTHROPIC_API_KEY, sar peste")
            continue
        summary, rows = run(s, labels)
        out.append({"summary": summary, "rows": rows})
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    C.OUT.mkdir(parents=True, exist_ok=True)
    (C.OUT / f"eval_{int(time.time())}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    md = ["| model | categoria corectă | tăieri găsite | alarme false eliminate | secunde/alertă |", "|---|---|---|---|---|"]
    for o in out:
        s = o["summary"]
        md.append(f"| {s['model']} | {s['corecte']}/{s['total']} | {s['taieri_gasite']}/{s['taieri']} | {s['false_eliminate']}/{s['false']} | {s['sec_medie']} |")
    report = "\n".join(md)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write("## Judecătorul AI pe alertele verificate\n\n" + report + "\n")


if __name__ == "__main__":
    main()
