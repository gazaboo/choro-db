"""Corrobore chaque grille par une partition indépendante et fixe sa confiance.

Une grille MXL n'est pas confirmée par les PDF MuseScore du même morceau : ils
sont imprimés depuis ce MXL. Ses témoins sont les PDF vectoriels d'un autre
logiciel (originaux Encore, Finale, Sibelius…). Une grille PDF a pour témoins
les PDF d'un autre logiciel que sa source. Toutes tonalités (C, Bb, Eb) : la
comparaison ignore la transposition.

Confiance attribuée :
- high   : une source indépendante donne le même enchaînement d'accords (≥ 85 %,
           un diminué valant le majeur de même fondamentale, voir `souple`)
           et les mêmes accords mesure par mesure (≥ 75 %), et la structure est
           plausible (parties de 4 à 48 mesures, au plus 4 accords par mesure) ;
- medium : grille MXL non corroborée, ou grille PDF corroborée mais à la structure douteuse ;
- low    : grille PDF non corroborée, ou contredite par une source indépendante.

Seules les grilles `high` restent publiées dans `grilles/` ; les autres sont
déplacées dans `outils/audit/sorties/grilles-a-verifier/` (non versionné), en
attente de relecture. Lancer toute la chaîne (grilles.py, grilles_pdf.py, puis
ce script) : relancé seul, il ne réévalue que les grilles déjà publiées.

Usage :
    outils/audit/.venv/bin/python -I outils/grilles/croiser.py [--grilles-manuelles DOSSIER]
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))

from grilles import RACINE, SORTIE, ecrire_index, normaliser  # noqa: E402
from grilles_pdf import grille_pdf  # noqa: E402
from valider import accords, neutre, suite, transposer  # noqa: E402

SORTIES = RACINE / "outils" / "audit" / "sorties"
SEUIL_ENCHAINEMENT = 0.85
SEUIL_MESURES = 0.75
A_VERIFIER = SORTIES / "grilles-a-verifier"


def souple(x: str) -> str:
    """Les PDF Encore perdent souvent le signe diminué à l'export (« G#° » imprimé « G# ») :
    pour corroborer, un diminué vaut l'accord majeur de même fondamentale."""
    return "|".join(a.removesuffix("dim") for a in x.split("|"))


def accord_entre(a: dict, b: dict) -> tuple[float, float, int]:
    """(mesures, enchaînement, décalage en demi-tons) entre deux grilles."""
    sa, aa = [souple(neutre(x)) for x in suite(a)], [souple(neutre(x)) for x in accords(a)]
    sb, ab = [souple(x) for x in suite(b)], [souple(x) for x in accords(b)]
    d = max(range(12), key=lambda d: SequenceMatcher(None, aa, [transposer(x, d + 12) for x in ab], autojunk=False).ratio())
    mesures = SequenceMatcher(None, sa, [transposer(x, d + 12) for x in sb], autojunk=False).ratio()
    ench = SequenceMatcher(None, aa, [transposer(x, d + 12) for x in ab], autojunk=False).ratio()
    return mesures, ench, (d if d <= 6 else d - 12)


def structure_plausible(g: dict) -> list[str]:
    defauts = []
    for p in g["parts"]:
        n = len(p["sequence"])
        if p["name"] != "Coda" and not 4 <= n <= 48:
            defauts.append(f"partie {p['name']} de {n} mesures")
        if any(len(c) > 4 for c in p["sequence"]):
            defauts.append(f"partie {p['name']} : mesure à plus de 4 accords")
    vides = sum(1 for p in g["parts"] for c in p["sequence"] if not c)
    total = sum(len(p["sequence"]) for p in g["parts"]) or 1
    if vides / total > 0.4:
        defauts.append(f"{vides}/{total} mesures sans accord")
    return defauts


def producteurs(fichiers: list[str]) -> dict[str, str]:
    cache_f = SORTIES / "producteurs.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    for f in fichiers:
        if f not in cache:
            m = pymupdf.open(RACINE / f).metadata or {}
            cache[f] = f"{m.get('creator', '')} {m.get('producer', '')}".lower()
    cache_f.write_text(json.dumps(cache))
    return cache


def graveur(producteur: str) -> str:
    """Famille de logiciel d'un PDF (la chaîne brute contient versions et noms de fichiers)."""
    for nom in ("musescore", "pscript", "finale", "sibelius", "encore", "lilypond", "fpdf", "qt"):
        if nom in producteur:
            return nom
    return producteur.split(" ")[0] if producteur.strip() else "inconnu"


def sources_par_morceau() -> tuple[dict[str, list[str]], dict[str, str]]:
    """song_id → PDF vectoriels (thème) lisibles, et fichier → famille de graveur."""
    inv = [json.loads(l) for l in (SORTIES / "inventaire.jsonl").open(encoding="utf-8")]
    pdfs = [
        l for l in inv
        if l["type"] == "pdf" and not l.get("scanne") and (l.get("accords") or 0) >= 16
        and str(l.get("partie", "")).lower().startswith("th")
    ]
    prod = producteurs([l["fichier"] for l in pdfs])
    out = defaultdict(list)
    for l in pdfs:
        out[f"{normaliser(l['titre'])}-{normaliser(l['compositeur'])}"].append(l["fichier"])
    return out, {f: graveur(p) for f, p in prod.items()}


def independant(temoin: str, g: dict, graveurs: dict[str, str]) -> bool:
    """Un PDF MuseScore est imprimé depuis le MXL : il ne corrobore pas une grille MXL.
    Pour une grille PDF, le témoin doit venir d'un autre logiciel que la source."""
    if temoin in g["source"]:
        return False
    if g["generated"] == "mxl":
        return graveurs[temoin] != "musescore"
    return all(graveurs.get(src, "?") != graveurs[temoin] for src in g["source"])


def main(argv: list[str]) -> int:
    manuelles = {}
    if "--grilles-manuelles" in argv:
        d = Path(argv[argv.index("--grilles-manuelles") + 1])
        for f in d.glob("*-*.json"):
            m = json.loads(f.read_text())
            manuelles.setdefault(normaliser(m["title"]), []).append(m)
    sources, graveurs = sources_par_morceau()
    A_VERIFIER.mkdir(parents=True, exist_ok=True)
    for f in A_VERIFIER.glob("*-*.json"):
        f.unlink()
    bilan, rapport = Counter(), []
    for f in sorted(SORTIE.glob("*-*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        temoins = []
        for chemin in sources.get(g["song_id"], []):
            if not independant(chemin, g, graveurs):
                continue
            try:
                autre = grille_pdf(RACINE / chemin)
            except Exception:
                continue
            if autre and autre["parts"]:
                temoins.append((accord_entre(g, autre), chemin))
        for m in manuelles.get(normaliser(g["title"]), []):
            temoins.append((accord_entre(g, m), "grille relevée à la main"))
        meilleur = max(temoins, key=lambda t: (t[0][1], t[0][0]), default=None)
        defauts = structure_plausible(g)
        corrobore = bool(meilleur) and meilleur[0][1] >= SEUIL_ENCHAINEMENT and meilleur[0][0] >= SEUIL_MESURES
        contredit = bool(meilleur) and meilleur[0][1] < 0.5
        if corrobore and not defauts:
            confiance = "high"
        elif g["generated"] == "mxl" and not contredit:
            confiance = "medium"
        elif corrobore:
            confiance = "medium"
        else:
            confiance = "low"
        g["confidence"] = confiance
        g["notes"] = [n for n in g["notes"] if not n.startswith(("Corroborée", "Non corroborée", "Contredite", "Structure"))]
        if meilleur:
            (mes, ench, d), qui = meilleur
            qui = "une grille relevée à la main" if qui.startswith("grille") else "une autre partition"
            ecart = f", transposée de {d:+d} demi-tons" if d else ""
            if corrobore:
                g["notes"].append(f"Corroborée par {qui}{ecart} : enchaînement {ench:.0%}, mesures {mes:.0%}.")
            elif contredit:
                g["notes"].append(f"Contredite par {qui}{ecart} (enchaînement {ench:.0%}) : version différente ?")
            else:
                g["notes"].append(f"Non corroborée : {qui}{ecart} ne concorde qu'à {ench:.0%} (enchaînement).")
        else:
            g["notes"].append("Non corroborée : aucune autre partition lisible de ce morceau.")
        if defauts:
            g["notes"].append("Structure à vérifier : " + " ; ".join(defauts) + ".")
        cible = f if confiance == "high" else A_VERIFIER / f.name
        cible.write_text(json.dumps(g, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if cible != f:
            f.unlink()
        bilan[(g["generated"], confiance)] += 1
        etat = "corroborée" if corrobore else "contredite" if contredit else "sans témoin" if not meilleur else "faible accord"
        bilan[(g["generated"], etat)] += 1
        rapport.append({"song_id": g["song_id"], "generated": g["generated"], "confidence": confiance, "etat": etat,
                        "accord": meilleur[0] if meilleur else None, "temoin": meilleur[1] if meilleur else None, "defauts": defauts})
    (SORTIES / "croisement-grilles.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding="utf-8")
    ecrire_index()
    for k, v in sorted(bilan.items()):
        print(f"{k[0]:4} {k[1]:13} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
