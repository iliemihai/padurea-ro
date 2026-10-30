"""Agentul 3, criticul: pune dovezile cap la cap și dă un nivel de încredere. Reguli simple și vizibile."""

AI_FALS = {"nori": "AI-ul vede nori", "toamna": "AI-ul vede doar frunze de toamnă", "agricol": "AI-ul vede teren agricol"}
AI_DA = {"taiere": "AI-ul vede pădure dispărută", "incendiu": "AI-ul vede o zonă arsă"}


def score(a):
    if not a.get("confirmed"):
        return "de confirmat", 0, ["văzută schimbată într-o singură imagine; așteptăm a doua"]
    s, why = 2, [f"văzută schimbată în {a['n_dates']} imagini diferite"]
    if a.get("ha", 0) >= 3:
        s += 1; why.append("peste 3 ha")
    if a.get("neigh_drop", 1) < 0.05:
        s += 1; why.append("pădurea din jur e neschimbată")
    ai = a.get("ai")
    if ai:
        c, conf = ai["categorie"], ai.get("incredere", 0.5)
        if c in AI_DA:
            s += 2 if conf >= 0.6 else 1; why.append(AI_DA[c])
        elif c in AI_FALS:
            s -= 3 if conf >= 0.6 else 1; why.append(AI_FALS[c])
        else:
            why.append("AI-ul nu se poate pronunța")
    else:
        why.append("fără părerea AI")
    level = "ridicată" if s >= 5 else ("medie" if s >= 3 else "scăzută")
    return level, s, why


def apply(alerts):
    for a in alerts:
        a["incredere"], a["scor"], a["dovezi"] = score(a)
        a["vant"] = bool(a.get("rafala_kmh") and a["rafala_kmh"] >= 70)
