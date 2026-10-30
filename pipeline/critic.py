"""Agentul 3, criticul: pune dovezile cap la cap și dă un nivel de încredere. Reguli simple și vizibile."""

AI_FALS = ("nori", "toamna", "agricol")


def score(a):
    s, why = 0, []
    if a.get("n_dates", 0) >= 2:
        s += 2; why.append(f"văzută în {a['n_dates']} imagini")
    else:
        why.append("văzută într-o singură imagine")
    if a.get("ha", 0) >= 3:
        s += 1; why.append("peste 3 ha")
    if a.get("neigh_drop", 1) < 0.05:
        s += 1; why.append("pădurea din jur e neschimbată")
    ai = a.get("ai")
    if ai:
        c, conf = ai["categorie"], ai.get("incredere", 0.5)
        if c == "taiere":
            s += 2 if conf >= 0.6 else 1; why.append("AI-ul vede pădure dispărută")
        elif c in AI_FALS:
            s -= 3 if conf >= 0.6 else 1; why.append({"nori": "AI-ul vede nori", "toamna": "AI-ul vede doar frunze de toamnă",
                                                      "agricol": "AI-ul vede teren agricol"}[c])
        else:
            why.append("AI-ul nu se poate pronunța")
    level = "ridicată" if s >= 4 else ("medie" if s >= 2 else "scăzută")
    return level, s, why


def apply(alerts):
    for a in alerts:
        a["incredere"], a["scor"], a["dovezi"] = score(a)
        a["vant"] = bool(a.get("rafala_kmh") and a["rafala_kmh"] >= 70)
