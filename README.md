# Pădurea RO

Hartă publică a schimbărilor din pădurile României, din imagini de satelit gratuite, actualizată zilnic.

**Site:** https://iliemihai.github.io/padurea-ro/

Arătăm unde și când a dispărut pădurea, cu imagini înainte și după, ca oricine să poată verifica. **Nu spunem dacă o tăiere e legală sau nu**: arătăm doar dacă în registrul public (Inspectorul Pădurii) există o autorizație care să acopere locul. O alertă înseamnă doar „aici s-a schimbat ceva și merită verificat”.

## Cum merge

```
imagini Sentinel-2 noi (la 2–5 zile)
        │
        ▼
1. Detectorul (cod, fără AI)          pipeline/detect.py
   - unde căutăm: pădure în ESA WorldCover, deasă și verde în ultima vară
   - referința de sezon: fiecare imagine nouă se compară cu aceeași perioadă de acum un an,
     ca frunzele care vin sau cad la alte date să nu arate ca o tăiere
   - pentru fiecare imagine nouă: unde a scăzut infraroșul de undă scurtă (NBR, SWIR) și verdele (NDVI)
     mai mult decât în pădurea din jur
   - iarna (15 decembrie – 15 martie) nu caută: o tăiere din iarnă apare primăvara, cu intervalul ei;
     din iulie până în octombrie pragurile sunt mai stricte, iar ce găsim toamna rămâne cel mult „scăzută”
   - păstrează doar ce rămâne schimbat în imaginile următoare (confirmată = în cel puțin 4 imagini)
   - respinge ce se vedea deja schimbat înainte și schimbările care cuprind tot dealul (ceață)
        │  candidați
        ▼
2. Analistul AI                        pipeline/judge.py
   - un model de viziune se uită la perechea înainte/după: tăiere, nori, toamnă, câmp sau neclar
   - Claude Haiku 5.5 dacă există cheia ANTHROPIC_API_KEY, altfel un model local (Qwen) prin Ollama
        │
        ▼
3. Contextul                           pipeline/context.py, pipeline/firms.py
   - localitatea cea mai apropiată, vântul din acele zile, pierderile Hansen din jur
   - focurile văzute în infraroșu de sateliții NASA (FIRMS) lângă zonă, dacă există cheia FIRMS_MAP_KEY
     (gratuită, pe e-mail: https://firms.modaps.eosdis.nasa.gov/api/map_key)
        │
        ▼
4. Verificarea pe poze și criticul     pipeline/vischeck.py, pipeline/critic.py
   - zona trebuie să fi arătat ca pădurea din jur înainte și să se schimbe vizibil după
   - pune dovezile cap la cap: încredere ridicată, medie sau scăzută
   - zonele văzute schimbate într-o singură imagine („de confirmat”) nu apar pe site: stau în
     data/neconfirmate.json până le vedem iar (atunci devin publice) sau 30 de zile (apoi le uităm)
        │
        ▼
5. Redactorul                          pipeline/writer.py
   - textul fișei, în cuvinte neutre
        │
        ▼
docs/data/alerts.json (ultimele 90 de zile) + docs/data/arhiva/ (pe luni)  →  harta (docs/)
```

Totul rulează în fiecare dimineață în GitHub Actions (`.github/workflows/daily.yml`): detectorul pe 8 grupe de plăci în paralel, apoi agenții, apoi publicarea pe GitHub Pages.

## Rulare locală

```bash
pip install -r requirements.txt
python -m pipeline.run_tiles --group 0 --groups 8 --days 30      # o grupă de plăci
python -m pipeline.run_finish                                     # agenții și publicarea în docs/
python -m tests.test_synthetic                                    # test pe date inventate
python -m tests.test_season                                       # detectorul pe o placă inventată, iarna și toamna
python -m pipeline.eval_judge qwen3.5:4b                          # testează judecătorul AI pe alertele verificate
```

## Date

- Copernicus Sentinel-2 L2A (ESA), prin [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/)
- [ESA WorldCover 2021](https://esa-worldcover.org/) (10 m), pentru masca de pădure
- Hansen et al., [Global Forest Change 2000–2025](https://glad.earthengine.app/view/global-forest-change), Universitatea Maryland
- [GeoNames](https://www.geonames.org/) (localități), [Open-Meteo](https://open-meteo.com/) (vânt)
- Limitele comunelor, orașelor și municipiilor (UAT): [geo-spatial.org](https://www.geo-spatial.org/), simplificate în [akaleeroy/romania-uat](https://github.com/akaleeroy/romania-uat), adunate în `data/uat_ro.geojson`
- Fundalul hărții: [Sentinel-2 cloudless](https://s2maps.eu) de EOX IT Services GmbH (CC BY-NC-SA 4.0), Esri World Imagery, © OpenStreetMap
- Ariile protejate: [Agenția Europeană de Mediu](https://www.eea.europa.eu/), Natura 2000 și ariile protejate naționale (CDDA), CC BY 4.0; le aduce workflow-ul „Arii protejate” (`python -m pipeline.static_arii`) în `data/arii_ro.geojson` și `docs/data/static/arii.geojson`. La fiecare zonă scriem doar în ce arie cade; nivelul de încredere nu se schimbă după asta
- Numele localităților de pe hartă: GeoNames, în `docs/data/static/places.json`, și conturul țării în `docs/data/static/romania.geojson`; le reface `python -m pipeline.static_map`
- Autorizațiile de tăiere (APV): [Inspectorul Pădurii](https://inspectorulpadurii.ro) (SUMAL 2.0, Ministerul Mediului), aduse de `python -m pipeline.permise` în `docs/data/permise.json`; site-ul le arată doar dacă fișierul există

## Linkuri permanente, date deschise, rapoarte

Ca o zonă să poată fi citată, fiecare are o pagină a ei, fără JavaScript, care nu dispare (`python -m pipeline.deschis`,
în rularea zilnică, după paginile pe județe):

- `docs/zona/<id>/` — pagina zonei: când, unde, cât, înainte/după, autorizația, cui te adresezi, textul de citare, istoricul
  stării; `zona.json` (GeoJSON) alături; `og.jpg`, poza care apare când linkul e pus pe WhatsApp/Facebook/X (doar la zonele
  roșii și la cele cu știri sau verificări). Dacă o zonă iese de pe hartă, pagina rămâne, cu data retragerii.
- `docs/date/` — toate zonele (`zone.csv`, `zone.geojson`), `index.json` (intrarea în API: fișiere statice, fără cheie),
  `datapackage.json` (câmpurile), `registru.json` (ce a fost publicat vreodată și cum s-a schimbat), licența: **CC BY 4.0**.
- `docs/feed.xml` — fluxul Atom: zonele noi fără autorizație și rapoartele lunare.
- `docs/metodologie/` — „Cum lucrăm”, pentru oricine; cifrele vin din `data/evaluare_2025.json` și din starea de azi.
- `docs/embed/?a=<id>` · `?judet=<slug>` · fără nimic (zonele roșii din țară) — harta de pus în articole, ca iframe.
- `docs/raport/<AAAA-LL>/` — raportul lunar (`python -m pipeline.raport`, workflow-ul „Raportul lunar”, pe 5 ale lunii):
  instantaneul lunii, care nu se mai rescrie, plus un Release pe GitHub cu datele atașate.

Paginile se rescriu doar când se schimbă ceva în ele (nu poartă data rulării), ca istoricul din git să crească puțin.

**Domeniu propriu.** Adresa din linkuri vine din `SITE_URL` (`pipeline/config.py`). Pentru un domeniu: pune-l în
`docs/CNAME`, fă înregistrările DNS spre GitHub Pages, bifează „Enforce HTTPS” (Settings → Pages) și setează variabila de repo
`SITE_URL` (Settings → Secrets and variables → Actions → Variables), de exemplu `https://padurea.exemplu.ro/`. Linkurile vechi
de pe github.io trimit singure spre domeniu.

## Autorizația de tăiere

Pentru fiecare zonă căutăm în Inspectorul Pădurii autorizațiile (APV) de la mai puțin de 500 m și ne uităm la două lucruri: parcela autorizată acoperă zona schimbată, și perioada autorizației cuprinde intervalul în care s-a tăiat.

Intervalul contează, și e partea ușor de greșit. Satelitul nu vede tăierea când se întâmplă, ci când revine frunza: o tăiere din ianuarie, cu autorizație valabilă până în decembrie, apare ca schimbare abia în aprilie. Dacă am compara perioada autorizației cu data la care am văzut-o noi, am declara „expirat” o tăiere perfect legală — așa s-a și întâmplat la prima încercare, cu 277 de zone în loc de 27. Așa că folosim intervalul dintre ultima imagine cu pădurea întreagă și prima imagine cu schimbarea. Când nu avem o imagine întreagă recentă (iarnă, nori), zona are doar „intactă în vara lui X”: intervalul e de aproape un an, spunem mai puțin, dar tot putem exclude o autorizație închisă înainte de vara aceea.

Înainte de orice autorizație, întrebăm **ce fel de schimbare e**. Un drum prin pădure, un teren arat sau un incendiu n-au autorizație de tăiere și nu trebuie judecate după ea: o linie lungă și îngustă (de cel puțin 5 ori mai lungă decât lată, sub 120 m lățime) e un coridor — drum, autostradă, linie electrică — iar categoriile analistului AI (agricol, incendiu, nori, toamnă) spun restul.

| stare | culoare | ce înseamnă |
|---|---|---|
| fără autorizație | roșu | nicio autorizație în jurul zonei |
| autorizația nu acoperă | portocaliu | parcela e publicată, dar nu cuprinde zona, sau autorizația nu era valabilă când s-a tăiat; fișa spune care |
| probabil cu autorizație | verde gol | autorizație în zonă, dar amenajamentul nu publică parcela ei; nu putem confirma |
| cu autorizație | verde plin | parcela autorizată acoperă zona, în intervalul tăierii |
| nu e tăiere de pădure | gri | drum, agricol, incendiu, nori sau toamnă: autorizațiile de tăiere nu se aplică |
| neverificată | contur punctat | zona n-a fost încă comparată |

O singură scară: cu cât mai cald, cu atât mai mult merită privit. Albastrul rămâne doar al ariilor protejate.

Ca să spunem că o autorizație **nu** acoperă tăierea, trebuie întâi să știm unde e parcela ei. Statul publică hărțile amenajistice doar în parte, mai ales pentru pădurile private; acolo punem un cerc în jurul punctului autorizației, pe măsura volumului, și nu afirmăm nimic despre perioadă — zona rămâne „probabil cu autorizație”.

Nicăieri nu scriem „ilegal”. Autorizațiile se pot prelungi, parcelele lipsesc, iar o zonă fără autorizație găsită e un motiv de verificat, nu o dovadă.

## Cât de des avem dreptate

Harta nu poate răspunde singură la „câte din zonele roșii sunt tăieri ilegale pe bune”. Răspunsul vine dintr-un eșantion verificat de un om: `python -m pipeline.esantion` scoate 30 de zone roșii alese la întâmplare într-un CSV, cu linkuri spre fișa de pe site și spre Inspectorul Pădurii; omul completează `verdict_om`, apoi `python -m pipeline.esantion --raport out/esantion_fara.csv` calculează precizia, cu interval de încredere. Fără pasul ăsta, numărul de zone roșii e o estimare, nu o constatare.

## La cine te duci

Fișa fiecărei zone spune de care Gardă Forestieră ține județul (cele nouă gărzi și județele arondate, după HG 743/2015, anexa 1) și ce ocol silvic a emis autorizația găsită în zonă. Sesizările se pot trimite, și fără nume, prin [formularul Gărzii Forestiere Naționale](https://gfn.gov.ro/taieri-ilegale/); dacă tăierea e în desfășurare, 112.

## Aspectul site-ului

Designul vine din [Hallmark](https://github.com/Nutlope/hallmark), tema Rim: hârtie aproape neagră, Switzer pentru text, Geist Mono pentru tot ce se măsoară (date, hectare, coordonate), o singură culoare de semnal (portocaliu). Culorile stau în `docs/tokens.css` și în blocul `:root` din `docs/style.css`; harta le citește de acolo.

Literele sunt incluse în `docs/fonts.css`, ca site-ul să nu depindă de alt server: Switzer (Indian Type Foundry, licența ITF Free Font License, de pe [Fontshare](https://www.fontshare.com/fonts/switzer)) și Geist Mono (Vercel, SIL Open Font License 1.1). Numele de pe hartă folosesc Noto Sans (SIL Open Font License 1.1), în formatul pentru MapLibre, din [protomaps/basemaps-assets](https://github.com/protomaps/basemaps-assets), puse în `docs/fonts/`.

## Cât de bine merge

Testul pe 2025 (`.github/workflows/evaluare.yml`, `pipeline/evaluate.py`): detectorul rulat pe tot anul 2025, în ferestre de 90 de zile care se suprapun, ca în rulările zilnice, cu AI-ul și criticul, apoi comparat cu pierderile de pădure Hansen din 2025 (Universitatea Maryland, Landsat 30 m). O zonă „se potrivește” dacă măcar 20% din ea e pierdere Hansen în 2024–2025.

| Nivel | Zone în 2025 | Se potrivesc cu Hansen |
|---|---|---|
| ridicată | 413 | 78,5% |
| medie | 984 | 76,8% |
| scăzută | 1.784 | 65,4% |

Câte pete de pierdere Hansen din 2025 ating o zonă de pe site (orice nivel public; între paranteze, doar „ridicată”):

| Mărime | Pete | Găsite |
|---|---|---|
| 0,5–1 ha | 4.779 | 7,8% (0,9%) |
| 1–5 ha | 5.664 | 31,3% (3,4%) |
| peste 5 ha | 636 | 74,1% (25,0%) |

Suprafața: 38,7% din cele 20.557 ha pierdute în 2025 (doar „ridicată”: 9,4%).

Hansen e o referință independentă, dar nu perfectă: ratează tăierile parțiale (rărituri, tăieri progresive), iar o tăiere din toamnă o trece uneori la anul următor. Când ne-am uitat pe poze la zonele care nu se potrivesc, multe erau tot schimbări reale (incendii, tăieri parțiale), deci precizia adevărată e probabil mai mare. Zonele sub 1 ha nu le căutăm. Tăierile din iarnă apar abia primăvara.

## Limite

Norii ascund pădurea uneori zile întregi. Între mijlocul lui decembrie și mijlocul lui martie nu căutăm deloc: o tăiere făcută atunci apare primăvara, cu intervalul în care s-a putut întâmpla. Nu vedem zone mai mici de 1 ha și nici tăierile de sub coronament. Și AI-ul greșește. Dacă vezi o alertă greșită, deschide un issue.

## Cheile (secrete)

- `ANTHROPIC_API_KEY`: analistul AI (Claude Haiku 5.5).
- `FIRMS_MAP_KEY`: focurile văzute de NASA. Gratuită: https://firms.modaps.eosdis.nasa.gov/api/map_key

Pe calculator stau în `../.env` (în afara repo-ului). Pe GitHub: Settings → Secrets and variables → Actions.
Site-ul nu are nevoie de nicio cheie.
