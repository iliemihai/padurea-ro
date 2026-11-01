# Pădurea RO

Hartă publică a schimbărilor din pădurile României, din imagini de satelit gratuite, actualizată zilnic.

**Site:** https://iliemihai.github.io/padurea-ro/

Arătăm unde și când a dispărut pădurea, cu imagini înainte și după, ca oricine să poată verifica. **Nu spunem dacă o tăiere e legală sau nu**: autorizațiile nu sunt publice. O alertă înseamnă doar „aici s-a schimbat ceva și merită verificat”.

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
   - iarna (1 noiembrie – 15 martie) nu caută: o tăiere din iarnă apare primăvara, cu intervalul ei;
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

## Aspectul site-ului

Designul vine din [Hallmark](https://github.com/Nutlope/hallmark), tema Rim: hârtie aproape neagră, Switzer pentru text, Geist Mono pentru tot ce se măsoară (date, hectare, coordonate), o singură culoare de semnal (portocaliu). Culorile stau în `docs/tokens.css` și în blocul `:root` din `docs/style.css`; harta le citește de acolo.

Literele sunt incluse în `docs/fonts.css`, ca site-ul să nu depindă de alt server: Switzer (Indian Type Foundry, licența ITF Free Font License, de pe [Fontshare](https://www.fontshare.com/fonts/switzer)) și Geist Mono (Vercel, SIL Open Font License 1.1). Numele de pe hartă folosesc Noto Sans (SIL Open Font License 1.1), în formatul pentru MapLibre, din [protomaps/basemaps-assets](https://github.com/protomaps/basemaps-assets), puse în `docs/fonts/`.

## Limite

Norii ascund pădurea uneori zile întregi. Între noiembrie și mijlocul lui martie nu căutăm deloc: o tăiere făcută atunci apare primăvara, cu intervalul în care s-a putut întâmpla. Nu vedem zone mai mici de 1 ha și nici tăierile de sub coronament. Și AI-ul greșește. Dacă vezi o alertă greșită, deschide un issue.

## Cheile (secrete)

- `ANTHROPIC_API_KEY`: analistul AI (Claude Haiku 5.5).
- `FIRMS_MAP_KEY`: focurile văzute de NASA. Gratuită: https://firms.modaps.eosdis.nasa.gov/api/map_key

Pe calculator stau în `../.env` (în afara repo-ului). Pe GitHub: Settings → Secrets and variables → Actions.
Site-ul nu are nevoie de nicio cheie.
