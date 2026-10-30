"""Agentul 1, analistul de imagini: un model de viziune se uită la perechea înainte/după și își dă cu părerea.

Două variante, cu aceleași instrucțiuni și aceeași formă a răspunsului:
  - Claude (prin API), dacă există cheia ANTHROPIC_API_KEY;
  - un model local prin Ollama (implicit qwen3.5:4b), gratuit, rulează pe procesor.
"""
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont

from . import config as C

CATEGORII = ["taiere", "incendiu", "toamna", "nori", "agricol", "neclar"]

PROMPT = """You are a remote-sensing analyst checking an automatic forest-change alert in Romania.
The picture shows the SAME place twice, seen by the Sentinel-2 satellite (about 10 m per pixel, natural colours):
LEFT = BEFORE ({d0}), RIGHT = AFTER ({d1}). The flagged area is in the middle of each image.
A simple detector flagged it because the vegetation became much less green.
Decide what really happened in the middle of the image. Pick exactly one category:
- "taiere": trees were removed (clear-cut, logging or windthrow). New bare soil, stumps or slash with sharp edges; often new tracks or roads.
- "incendiu": a burn scar. Black, dark brown or purple-grey burned area with irregular edges.
- "toamna": the same forest with autumn colours. Green turned brown, yellow or orange, but the shapes and texture of the canopy stay the same.
- "nori": clouds, haze, smoke or cloud shadow cover the BEFORE or the AFTER image, so it only looks changed.
- "agricol": farmland, pasture or a meadow (ploughed, mowed or harvested fields), not a forest.
- "neclar": you cannot tell.
Give "incredere" between 0 and 1 and "motiv": one short sentence in Romanian about what you see."""

SCHEMA = {
    "type": "object",
    "properties": {
        "categorie": {"type": "string", "enum": CATEGORII},
        "incredere": {"type": "number"},
        "motiv": {"type": "string"},
    },
    "required": ["categorie", "incredere", "motiv"],
}


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def pair_png(before_path, after_path, d0, d1, min_h=320):
    """Cele două imagini una lângă alta, cu etichete. Întoarce PNG ca bytes."""
    b = Image.open(after_path).convert("RGB")
    a = Image.open(before_path).convert("RGB") if before_path else Image.new("RGB", b.size, (90, 90, 90))
    h = max(a.height, b.height, min_h)
    a = a.resize((round(a.width * h / a.height), h), Image.LANCZOS)
    b = b.resize((round(b.width * h / b.height), h), Image.LANCZOS)
    img = Image.new("RGB", (a.width + 16 + b.width, h + 34), "white")
    img.paste(a, (0, 34))
    img.paste(b, (a.width + 16, 34))
    d = ImageDraw.Draw(img)
    d.text((6, 6), f"BEFORE {d0}" if before_path else "BEFORE: no clear image", fill="black", font=_font(20))
    d.text((a.width + 22, 6), f"AFTER {d1}", fill="black", font=_font(20))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _parse(text):
    """Ultimul obiect JSON din text care are cheia „categorie" (modelele mai scriu și alt text în jur)."""
    import re
    j = None
    for m in reversed(list(re.finditer(r"\{[^{}]*\}", text or "", re.S))):
        try:
            cand = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(cand, dict) and "categorie" in cand:
            j = cand
            break
    if j is None:
        raise ValueError("fără JSON în răspuns: " + (text or "")[:160].replace("\n", " "))
    cat = str(j.get("categorie", "neclar")).strip().lower()
    if cat not in CATEGORII:
        cat = "neclar"
    try:
        conf = max(0.0, min(1.0, float(j.get("incredere", 0.5))))
    except (TypeError, ValueError):
        conf = 0.5
    return {"categorie": cat, "incredere": round(conf, 2), "motiv": str(j.get("motiv", ""))[:300]}


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _post(url, body, headers, opener=None, timeout=600):
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    with (opener or urllib.request.build_opener()).open(req, timeout=timeout) as r:
        return json.load(r)


def _raw(rec):
    """Răspunsurile brute ale modelului, ca să putem vedea ce a mers prost."""
    try:
        C.OUT.mkdir(parents=True, exist_ok=True)
        with open(C.OUT / "ai_raw.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False)[:4000] + "\n")
    except OSError:
        pass


def ask_local(png, d0, d1, model=None):
    model = model or C.LOCAL_MODEL
    msg = {"role": "user", "content": PROMPT.format(d0=d0, d1=d1) + "\nAnswer only with a JSON object with the keys categorie, incredere, motiv.",
           "images": [base64.b64encode(png).decode()]}
    base = {"model": model, "stream": False, "messages": [msg], "options": {"temperature": 0, "num_predict": 400}, "keep_alive": "30m"}
    url, h, last = C.OLLAMA_URL + "/api/chat", {"Content-Type": "application/json"}, ""
    for extra in ({"think": False, "format": SCHEMA}, {"think": False}, {}):
        try:
            r = _post(url, {**base, **extra}, h, _LOCAL)
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read()[:200]!r}"
            _raw({"model": model, "try": list(extra), "error": last})
            continue
        m = r.get("message", {})
        text = (m.get("content") or "").strip() or (m.get("thinking") or "")
        _raw({"model": model, "try": list(extra), "content": m.get("content"), "thinking": (m.get("thinking") or "")[:800]})
        try:
            return _parse(text), model
        except ValueError as exc:
            last = str(exc)
    raise RuntimeError(last)


def ask_claude(png, d0, d1, model=None):
    model = model or C.CLAUDE_MODEL
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode()}},
        {"type": "text", "text": PROMPT.format(d0=d0, d1=d1) + "\nAnswer only with a JSON object with the keys categorie, incredere, motiv."},
    ]
    headers = {"Content-Type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
    fast = {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}}
    plain = {}
    last = ""
    for extra in (fast, plain):
        body = {"model": model, "max_tokens": 1024, "messages": [{"role": "user", "content": content}], **extra}
        for attempt in range(4):
            try:
                r = _post("https://api.anthropic.com/v1/messages", body, headers, timeout=120)
            except urllib.error.HTTPError as exc:
                detail = exc.read()[:300].decode("utf-8", "replace")
                last = f"HTTP {exc.code}: {detail}"
                if exc.code in (429, 500, 502, 503, 529) and attempt < 3:
                    time.sleep(5 * (attempt + 1))
                    continue
                if exc.code in (401, 403):
                    raise RuntimeError("cheia ANTHROPIC_API_KEY nu e bună: " + detail)
                break  # 400: încercăm fără parametrii de viteză
            text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
            _raw({"model": model, "fast": bool(extra), "text": text})
            try:
                return _parse(text), model
            except ValueError as exc:
                last = str(exc)
                break
    raise RuntimeError(last)


def backend():
    """Claude dacă există cheia; modelul local doar dacă îl ceri explicit (USE_LOCAL=1); altfel fără AI."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("USE_LOCAL") == "1":
        return "local"
    return None


def judge(before_path, after_path, d0, d1, which=None, model=None):
    png = pair_png(before_path, after_path, d0, d1)
    t0 = time.time()
    which = which or backend()
    r, used = (ask_claude if which == "claude" else ask_local)(png, d0, d1, model)
    r["model"] = used
    r["secunde"] = round(time.time() - t0, 1)
    return r
