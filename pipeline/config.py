"""Toate pragurile și setările într-un singur loc, ca să le putem regla și compara."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"            # rezultatele unei rulări (nu intră în site)
DOCS = ROOT / "docs"          # site-ul public (GitHub Pages)

PC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
RO_BBOX = [20.2, 43.6, 29.75, 48.3]

# Grila de lucru: 40 m, deci un pixel = 0,16 ha
RES = 40.0
PX_HA = RES * RES / 1e4

# Ferestrele de timp
WINDOW_DAYS = 30          # căutăm schimbări apărute în ultimele N zile (recalculat zilnic)
RECENT_DAYS = 75          # referința „recentă": cele N zile dinaintea ferestrei
LASTYEAR_PAD = 20         # referința „anul trecut": aceeași perioadă de acum un an, ± N zile
MAX_REF_SCENES = 4        # câte imagini folosim pentru fiecare referință
MAX_SCENE_CLOUD = 85      # sărim imaginile cu mai mult de atâția % nori (după metadate)
MIN_SCENE_CLEAR = 0.05    # și pe cele în care se vede curat sub 5% din pădurea plăcii

# Clase SCL Sentinel-2: 4 = vegetație, 5 = sol fără vegetație. Restul (nori, umbre, zăpadă, apă, „neclasificat") nu le credem.
SCL_OK = (4, 5)
SCL_BAD = (3, 8, 9, 10)   # umbre de nori, nori, cirrus: le lărgim cu câțiva pixeli
BAD_DILATE_PX = 3         # 3 × 40 m = 120 m în jurul norilor

# Ce înseamnă „pădure care a dispărut" într-o imagine
NDVI_REF_MIN = 0.60       # înainte: pădure verde
NBR_REF_MIN = 0.30        # și deasă (indicele cu SWIR)
NDVI_DROP = 0.30          # verdele a scăzut cu cel puțin atât MAI MULT decât în pădurea din jur
NDVI_NOW_MAX = 0.45       # acum: nu mai arată a pădure
NBR_DROP = 0.30           # și indicele cu SWIR a scăzut cu atât mai mult decât în jur (sol gol, lemn tăiat, ars)
NBR_NOW_MAX = 0.20        # acum: sol gol sau ars, nu frunze de toamnă
HAZE_BLUE = 0.09          # albastru peste atât în pădure = ceață sau nor subțire: nu credem pixelul
CONFIRM_DATES = 2         # o zonă e confirmată când se vede schimbată în cel puțin atâtea zile diferite
THUMB_SINGLES = 20        # imagini și pentru cele mai mari zone încă neconfirmate

# Teste contra alarmelor false
SCENE_MAX_CHANGED = 0.05  # dacă într-o imagine s-a „schimbat" peste 5% din pădure, e ceață sau toamnă: o sărim
NEIGH_PX = 25             # „pădurea din jur": 25 × 40 m = 1 km
NEIGH_MAX = 0.15          # dacă și pădurea din jur a pierdut atâta verde, respingem
PERSIST_MIN = 0.5         # după prima apariție, schimbarea trebuie să se vadă în cel puțin jumătate din imaginile clare
MIN_HA = 1.0              # cea mai mică zonă raportată

# Imaginile înainte/după
THUMB_RES = 0.0001        # grade, cam 10 m
THUMB_PAD_M = 350         # margine în jurul zonei
THUMB_MAX_PX = 320

# Judecătorul AI
JUDGE_MAX_PER_GROUP = int(os.environ.get("JUDGE_MAX_PER_GROUP", "25"))
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen3.5:4b")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "2")
os.environ.setdefault("GDAL_HTTP_MULTIPLEX", "YES")
os.environ.setdefault("GDAL_HTTP_VERSION", "2")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF,.tiff")
