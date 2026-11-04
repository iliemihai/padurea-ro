# Evaluarea zonelor roșii

Întrebarea: când harta arată o zonă cu roșu („tăiere fără autorizație care s-o acopere”), cât de des chiar e pădure tăiată?

## Cum se măsoară

1. `python -m pipeline.rejudeca --planse DIR --strat v1|holdout` alege un eșantion stratificat pe stările hărții și desenează,
   pentru fiecare zonă, aceeași planșă pe care o vede judecătorul AI: poza detaliată Esri (înainte), Sentinel-2 înainte/după,
   vederea largă de 2 km, plus fișa de teren (relief, acoperirea terenului, coronament 2000, OSM). **Fără** starea de pe hartă,
   fără registrul de autorizații și fără verdictul AI-ului. Cheia (ce stare are fiecare planșă) stă separat, în `cheie.json`.
2. Fiecare planșă primește o etichetă oarbă: `taiere_rasa`, `rarire`, `pasune`, `santier`, `camp`, `foc`, `nimic`, `neclar`.
3. `evaluare/simuleaza.py` recalculează stările hărții cu un fișier de judecată dat și dă precizia fiecărei stări,
   cu interval de încredere Wilson 95%. `evaluare/compara.py` arată unde judecătorul și eticheta nu se potrivesc.

## 2026-11-04 — eșantionul 1 (100 de zone: 60 roșii, 15 vegetație, 15 nu e tăiere, 10 verzi)

Etichetele (`etichete_orb.json`) sunt făcute orb de Claude (Opus/Fable), nu de un om. Vor fi verificate de om.

| Judecător | roșii | precizia roșului | tăieri reale păstrate în roșu |
|---|---|---|---|
| v1: Haiku, prompt fără capcane, prag 0,6 | 60 | 58% (IC 46–70) | 35/35 |
| v2: Haiku, prompt cu capcane, prag 0,6 | 39 | 77% (IC 62–87) | 30/35 |
| **v2: Sonnet, prompt cu capcane, prag 0,5** | 36 | **83% (IC 68–92)** | 30/35 |
| v2: Sonnet, prompt cu capcane, prag 0,6 | 26 | 88% (IC 71–96) | 23/35 |

Greșelile v1 erau aceleași mereu: culori de toamnă sau umbră luate drept tăiere, arsuri, tufăriș și pășune cu copaci
(„coroane dese” în poza detaliată), șantiere și câmpuri. Promptul v2 îl obligă să le verifice pe rând înainte de „tăiere”.

**Atenție:** capcanele din v2 au fost scrise după ce am văzut greșelile v1 pe *acest* eșantion, deci cifrele v2 de aici sunt
optimiste. Cifra care contează e cea de pe eșantionul 2 (holdout), pe care promptul nu l-a văzut.

Unde nu e roșu: zonele „vegetație” n-au conținut nicio tăiere de pădure (0 din 14 etichete clare), dar nici nu erau toate
pășuni curățate (și câmp, foc, nimic) — textul de pe hartă spune deci doar „nu pare pădure tăiată”.

## 2026-11-04 — eșantionul 2, holdout (120 de zone)

Ales la întâmplare (`--strat holdout --seed 23`) din toate cele 421 de zone care pot ieși roșii (nicio autorizație nu le
acoperă), fără zonele din eșantionul 1. Promptul v2 nu le-a văzut. Etichetat orb de Claude înainte de a rula judecătorul.

Din cele 120: 47 tăieri reale (43 rase, 4 rărituri), 14 neclare, restul altceva (20 nimic real, 10 câmp, 10 șantier,
9 foc, 8 pășune, 2 altceva). Deci „fără autorizație” singur e tăiere reală doar în **39%** din cazuri.

| Judecător | roșii | precizia roșului | fără neclare | tăieri reale prinse (recall) |
|---|---|---|---|---|
| fără filtru (orice zonă fără autorizație) | 120 | 39% | — | 47/47 |
| v1: Haiku, prompt fără capcane, prag 0,6 | 61 | 62% (IC 50–73) | 76% | 38/47 = 81% |
| **v2: Sonnet, prompt cu capcane, prag 0,5** | 34 | **88% (IC 73–95)** | **100% (IC 89–100)** | 30/47 = 64% |
| v2: Sonnet, prag 0,6 | 26 | 100% (IC 87–100) | 100% | 26/47 = 55% |

Cele 4 roșii „greșite” la prag 0,5 sunt zone pe care nici eticheta oarbă nu le-a putut lămuri; niciuna nu e clar altceva.
Cele 17 tăieri scăpate au toate încredere mică (0,4–0,55) și categorii de ezitare: plantații tăiate în lunca Dunării
luate drept „altceva”, fâșii pe mal, pădure tânără luată drept pășune, o pată pe versant luată drept alunecare.

**Regula pentru stările care nu acuză (de la 2026-11-04):** publicăm o concluzie doar când analistul nu ghicește
(încredere ≥ 0,5, pe scara din prompt: sub 0,5 = „ghicesc”). Sub 0,5, „nu e tăiere” și „pășune” devin „de confirmat”.
Pe holdout, cu regula asta:

| Stare pe hartă | zone | corect | fără neclare |
|---|---|---|---|
| roșu (tăiere fără autorizație care s-o acopere) | 34 | 88% | 100% |
| nu e tăiere de pădure | 38 | 79% | 86% |
| pășune, nu pădure | 10 | 100% | 100% |
| de confirmat | 38 | — | (10 tăieri reale, 21 altceva, 7 neclare) |

**De făcut:** etichete de om pe aceleași 120 de zone (pagina `eticheteaza.html` le are), ca precizia să nu depindă doar
de etichetele lui Claude. Abia apoi cifra poate fi publicată pe site.
