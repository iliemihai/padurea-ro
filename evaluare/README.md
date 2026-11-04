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
