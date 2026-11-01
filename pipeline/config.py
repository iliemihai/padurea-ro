"""Toate pragurile și setările într-un singur loc, ca să le putem regla și compara."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
# PADUREA_OUT / PADUREA_DOCS: alte foldere, ca testul pe trecut (evaluate.py) să nu atingă site-ul
OUT = Path(os.environ.get("PADUREA_OUT") or ROOT / "out")      # rezultatele unei rulări (nu intră în site)
DOCS = Path(os.environ.get("PADUREA_DOCS") or ROOT / "docs")   # site-ul public (GitHub Pages)
PENDING = Path(os.environ.get("PADUREA_PENDING") or DATA / "neconfirmate.json")  # zonele încă neconfirmate (nu pe site)
EXPIRED = Path(os.environ["PADUREA_EXPIRED"]) if os.environ.get("PADUREA_EXPIRED") else None  # doar la testul pe trecut

PC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
RO_BBOX = [20.2, 43.6, 29.75, 48.3]

# Grila de lucru: 40 m, deci un pixel = 0,16 ha
RES = 40.0
PX_HA = RES * RES / 1e4

# Ferestrele de timp
WINDOW_DAYS = 30          # căutăm schimbări apărute în ultimele N zile (recalculat zilnic)
RECENT_DAYS = 75          # imaginile din cele N zile dinaintea ferestrei: era zona deja schimbată? când era intactă?
LASTYEAR_PAD = 20         # (vechi) referința „anul trecut": aceeași perioadă de acum un an, ± N zile
MAX_REF_SCENES = 4        # câte imagini folosim pentru fiecare referință
MAX_RECENT_SCENES = 5     # câte imagini clare dinaintea ferestrei urmărim, de la cea mai nouă
# Referința de sezon: fiecare imagine nouă se compară cu pădurea de acum un an, din aceeași perioadă a anului.
# Înainte o comparam cu lunile dinainte: primăvara, referința era pădurea fără frunze și foioasele ieșeau din calcul
# (testul pe 2025: în ianuarie–iunie foloseam doar 17% din imagini), iar toamna frunzele căzute arătau ca tăieri.
SEASON_PAD = 30           # imaginile de acum un an, ± N zile față de data imaginii noi
ANCHOR_DAYS = 15          # câte o referință de sezon la fiecare N zile
SUMMER = ("06-15", "08-31")  # „pădure deasă” se verifică pe ultima vară încheiată dinaintea ferestrei
LEAFON_NDVI = 0.70        # căutăm doar unde referința de sezon e pădure cu frunze (sau rășinoase verzi)
# Iarna nu căutăm deloc: testul pe iarna 2024–2025 a dat 5% potriviri cu Hansen (zăpadă și sol ud sub foioasele
# desfrunzite, diferite de la un an la altul). O tăiere de iarnă apare primăvara, când pădurea din jur înverzește,
# cu intervalul în care s-a putut întâmpla.
WINTER = ("12-01", "03-15")
MAX_SCENE_CLOUD = 85      # sărim imaginile cu mai mult de atâția % nori (după metadate)
MIN_SCENE_CLEAR = 0.05    # și pe cele în care se vede curat sub 5% din pădurea plăcii

# Clase SCL Sentinel-2: 4 = vegetație, 5 = sol fără vegetație. Restul (nori, umbre, zăpadă, apă, „neclasificat") nu le credem.
SCL_OK = (4, 5)
SCL_BAD = (3, 8, 9, 10)   # umbre de nori, nori, cirrus: le lărgim cu câțiva pixeli
BAD_DILATE_PX = 3         # 3 × 40 m = 120 m în jurul norilor

# Ce înseamnă „pădure care a dispărut" într-o imagine. Pragurile sunt LARGI: detectorul trebuie să prindă tot ce
# ar putea fi o tăiere. Ce se publică decid apoi regulile (rules.py), analistul AI și criticul.
NDVI_REF_MIN = 0.60       # înainte: pădure verde
NBR_REF_MIN = 0.30        # și deasă (indicele cu SWIR)
# Primăvara și vara: pe locul tăiat cresc repede iarbă și lăstari, așa că verdele scade puțin, iar infraroșul de undă
# scurtă (NBR) mult. Diagnosticul pe 55 de tăieri ratate în 2025: după tăiere, NBR-ul zonei e cu 0,14–0,44 sub pădurea
# din jur (mediana 0,26), verdele doar cu 0,08–0,34, iar NDVI-ul zonei rămâne des peste 0,5; o zonă intactă diferă
# de pădurea din jur cu cel mult 0,09 (în 95% din imagini).
NDVI_DROP = 0.10          # verdele a scăzut cu cel puțin atât mai mult decât în pădurea din jur
NDVI_NOW_MAX = 0.75       # acum: nu mai arată a pădure deasă
NBR_DROP = 0.15           # și indicele cu SWIR a scăzut cu atât mai mult decât în jur
NBR_NOW_MAX = 0.45
# Toamna (frunze care se îngălbenesc la date diferite de la un an la altul) păstrăm pragurile vechi, stricte:
# o tăiere rasă tot trece de ele, iar una parțială apare primăvara.
AUTUMN = ("09-15", "11-30")
NDVI_DROP_AUTUMN = 0.25
NDVI_NOW_MAX_AUTUMN = 0.50
NBR_DROP_AUTUMN = 0.25
NBR_NOW_MAX_AUTUMN = 0.35
HAZE_BLUE = 0.09          # albastru mare ȘI aproape cât roșul = nor sau ceață (solul gol e mai roșu decât albastru)
HAZE_BLUE_RED = 0.85
CONFIRM_DATES = 2         # o zonă e confirmată când se vede schimbată în cel puțin atâtea zile diferite
THUMB_SINGLES = 20        # imagini și pentru cele mai mari zone încă neconfirmate
THUMB_MAX_CONFIRMED = 150 # cel mult atâtea zone confirmate cu imagini, pe placă

# Regulile de publicare (rules.py), aplicate pe măsurătorile salvate pentru fiecare zonă (pe medii, pe toată zona)
RULE_NBR_NOW_MAX = 0.42   # după: indicele SWIR al zonei arată sol, lemn tăiat, ars sau vegetație rară, nu pădure
RULE_ADJ_NBR_MIN = 0.18   # scăderea SWIR față de pădurea din jur
RULE_NBR_NOW_MAX_AUTUMN = 0.25   # toamna, ca înainte
RULE_ADJ_NBR_MIN_AUTUMN = 0.30
RULE_EDGE_MAX = 0.85      # zona nu e doar o fâșie pe marginea pădurii
RULE_BLUE_MAX = 0.12      # albastru atât de mare = nor sau ceață scăpate de masca de nori

# NASA FIRMS (firms.py): focuri văzute în infraroșu de sateliți
FIRMS_BUFFER_M = 750      # cât de departe de zonă poate fi un punct de foc (pixelul VIIRS are ~375 m)
FIRMS_AFTER_DAYS = 3      # căutăm foc până la atâtea zile după ce zona s-a văzut schimbată
FIRMS_KEEP_DAYS = 180     # câte zile de puncte de foc ținem pe hartă

# Verificarea pe poze (vischeck.py): zona comparată cu un inel de 40–200 m în jurul ei, pe pozele înainte/după (0–255)
VIS_OPEN_MAX = 22         # înainte: zona mai luminoasă decât împrejurimile cu peste atât = era deja deschisă
VIS_EXCESS_MIN = 20       # cât trebuie să se schimbe culoarea zonei peste schimbarea din jur…
VIS_DGREEN_MIN = 1.5      # …sau cât trebuie să piardă din verde (puncte procentuale) peste împrejurimi

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
JUDGE_MAX_PER_GROUP = int(os.environ.get("JUDGE_MAX_PER_GROUP", "150"))
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
