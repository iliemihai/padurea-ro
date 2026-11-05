"""Imaginea de previzualizare (1200×630): ce apare când cineva pune linkul unei zone pe WhatsApp, Facebook sau X.

Literele vin din docs/fonts.css (Switzer, aceleași ca pe site). Pozele Sentinel-2 au 90 × 90 de pixeli (10 m pe pixel):
le mărim cu „nearest”, ca pixelii să se vadă cinstit, nu încețoșați. Fără litere, imaginea iese tot, cu litera implicită.

    python -m pipeline.og 20260928_44871_24888    -> out/og_<id>.jpg (probă)
"""
import base64
import io
import re
import sys
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from . import config as C

W, H = 1200, 630
# culorile din docs/tokens.css și docs/style.css, trecute din oklch în sRGB
PAPER, PAPER2, INK, INK2, MUTED, RULE, ACCENT = "#030201", "#080604", "#efebe4", "#cecac3", "#9c9890", "#24211c", "#f97c3d"
STARE_CULOARE = {"fara": "#ee3533", "neacoperit": "#ee3533", "vegetatie": "#dc9e12", "probabil": "#249c74",
                 "acoperit": "#249c74", "nu_taiere": "#7e7a73", "nejudecat": "#bbb7af", "nev": "#bbb7af"}


@lru_cache(maxsize=None)
def _fete():
    """{(familie, greutate): octeții TTF} din fonts.css. Gol dacă lipsește fontTools sau fișierul."""
    try:
        from fontTools.ttLib import TTFont
        css = (C.DOCS / "fonts.css").read_text(encoding="utf-8")
    except Exception:
        return {}
    out = {}
    pat = r'font-family:\s*"([^"]+)";\s*font-style:\s*\w+;\s*font-weight:\s*(\d+);.*?base64,([A-Za-z0-9+/=]+)'
    for fam, w, b64 in re.findall(pat, css, re.S):
        if (fam, w) in out:   # Geist Mono are două bucăți; prima are cifrele
            continue
        try:
            f = TTFont(io.BytesIO(base64.b64decode(b64)))
            f.flavor = None
            buf = io.BytesIO()
            f.save(buf)
            out[(fam, w)] = buf.getvalue()
        except Exception:
            continue
    return out


def font(size, w="400", fam="Switzer"):
    data = _fete().get((fam, w)) or _fete().get(("Switzer", w)) or _fete().get(("Switzer", "400"))
    if data:
        return ImageFont.truetype(io.BytesIO(data), size)
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _incape(d, text, f, maxw):
    """Taie textul cu „…” ca să încapă pe un rând."""
    if d.textlength(text, font=f) <= maxw:
        return text
    while text and d.textlength(text + "…", font=f) > maxw:
        text = text[:-1]
    return text.rstrip(" ,·") + "…"


def _poza(path, cb, geom, side):
    """O poză Sentinel mărită, cu conturul zonei peste ea."""
    try:
        im = Image.open(path).convert("RGB").resize((side, side), Image.NEAREST)
    except Exception:
        im = Image.new("RGB", (side, side), PAPER2)
    if cb and geom:
        d = ImageDraw.Draw(im)
        w, h = cb[2] - cb[0], cb[3] - cb[1]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for ring in poly:
                pts = [(side * (x - cb[0]) / w, side * (cb[3] - y) / h) for x, y in ring]
                d.line(pts + pts[:1], fill=ACCENT, width=4, joint="curve")
    return im


def zona(a, titlu, loc, stare, stare_text, data_t, url_t, out):
    """Cardul unei zone: înainte/după, mărimea, locul, starea autorizației."""
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    pad, side = 56, 340
    # marca
    d.rectangle([pad, pad + 6, pad + 16, pad + 22], fill=ACCENT)
    d.text((pad + 30, pad), "Pădurea RO", font=font(28, "500"), fill=INK)
    # pozele
    y0 = 140
    ib, ia, cb = a.get("img_before") or {}, a.get("img_after") or {}, a.get("chip_bbox")
    img = C.DOCS / "img"
    for i, (info, lab) in enumerate(((ib, "înainte"), (ia, "după"))):
        x = pad + i * (side + 16)
        im.paste(_poza(img / (info.get("file") or "-"), cb, a.get("geometry"), side), (x, y0))
        d.text((x, y0 + side + 12), f"{lab} · {_zi(info.get('date'))}", font=font(22), fill=MUTED)
    # textul
    tx = pad + 2 * side + 16 + 48
    maxw = W - tx - pad
    d.text((tx, y0 - 4), _incape(d, titlu, font(56, "500"), maxw), font=font(56, "500"), fill=INK)
    yy = y0 + 72
    for rand in _rupe(d, loc, font(30), maxw, 3):
        d.text((tx, yy), rand, font=font(30), fill=INK2)
        yy += 40
    yy += 18
    d.rectangle([tx, yy + 8, tx + 18, yy + 26], fill=STARE_CULOARE.get(stare, MUTED))
    for rand in _rupe(d, stare_text, font(30, "500"), maxw - 32, 2):
        d.text((tx + 32, yy), rand, font=font(30, "500"), fill=INK)
        yy += 40
    yy += 14
    for rand in _rupe(d, data_t, font(24), maxw, 2):
        d.text((tx, yy), rand, font=font(24), fill=MUTED)
        yy += 32
    # jos
    d.line([(pad, H - 78), (W - pad, H - 78)], fill=RULE, width=1)
    d.text((pad, H - 60), _incape(d, url_t, font(22, "400", "Geist Mono"), W - 2 * pad), font=font(22, "400", "Geist Mono"), fill=MUTED)
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True, progressive=True)
    return _scrie(out, buf.getvalue())


def generic(titlu, sub, out, poze=()):
    """Cardul site-ului (pentru pagini fără poză proprie): titlul și câteva perechi înainte/după."""
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    pad = 64
    d.rectangle([pad, pad + 10, pad + 22, pad + 32], fill=ACCENT)
    d.text((pad + 38, pad), titlu, font=font(44, "500"), fill=INK)
    yy = pad + 80
    for rand in _rupe(d, sub, font(32), W - 2 * pad, 3):
        d.text((pad, yy), rand, font=font(32), fill=INK2)
        yy += 44
    side, gap = 150, 12
    x = pad
    for a in poze:
        if x + 2 * side + gap > W - pad:
            break
        for info in (a.get("img_before") or {}, a.get("img_after") or {}):
            im.paste(_poza(C.DOCS / "img" / (info.get("file") or "-"), a.get("chip_bbox"), a.get("geometry"), side), (x, H - pad - side))
            x += side + 4
        x += gap + 8
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True, progressive=True)
    return _scrie(out, buf.getvalue())


def _zi(s):
    if not s:
        return ""
    from .judete import zi
    return zi(s)


def _rupe(d, text, f, maxw, max_randuri):
    cuv, rand, out = (text or "").split(), "", []
    for c in cuv:
        t = (rand + " " + c).strip()
        if d.textlength(t, font=f) <= maxw:
            rand = t
            continue
        out.append(rand)
        rand = c
        if len(out) == max_randuri:
            break
    if len(out) < max_randuri and rand:
        out.append(rand)
    if len(out) == max_randuri and " ".join(out) != " ".join(cuv):
        out[-1] = _incape(d, out[-1] + " …", f, maxw)
    return out


def _scrie(path, data):
    """Scrie doar dacă s-a schimbat, ca istoricul din git să nu crească degeaba."""
    if path.exists() and path.read_bytes() == data:
        return False
    path.write_bytes(data)
    return True


if __name__ == "__main__":
    from .permise import zone_site
    z = zone_site()
    for i in sys.argv[1:]:
        a = z[i]
        p = C.OUT / f"og_{i}.jpg"
        C.OUT.mkdir(parents=True, exist_ok=True)
        zona(a, f"{a['ha']} ha", a.get("localitate") or "", "fara", "probă", a["first_seen"], C.SITE_URL, p)
        print(p)
