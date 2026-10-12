"""Compare les grilles générées aux grilles relevées à la main.

Les grilles manuelles alignent les accords sur les mesures de façon approximative
(voir leur README) : on compare donc les suites d'accords simplifiés, mesure par
mesure, avec un alignement tolérant (SequenceMatcher), partie par partie.

Usage :
    outils/audit/.venv/bin/python -I outils/grilles/valider.py DOSSIER_GRILLES_MANUELLES
"""

from __future__ import annotations

import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

from rapidfuzz import fuzz

from grilles import RACINE, demi_ton, empreinte, normaliser

NOMS = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def transposer(x: str, d: int) -> str:
    """Transpose une empreinte « Am|E7 » de `d` demi-tons (orthographe neutre)."""
    if not d or not x:
        return x
    out = []
    for a in x.split("|"):
        r = 2 if len(a) > 1 and a[1] in "#b" else 1
        out.append(NOMS[(demi_ton(a[:r]) + d) % 12] + a[r:])
    return "|".join(out)


def neutre(x: str) -> str:
    return transposer(x, 12)  # même hauteur, orthographe unique (D# = Eb)


def suite(g: dict) -> list[str]:
    """Toutes les mesures, fins comprises, dans l'ordre d'écriture."""
    out = []
    for p in g["parts"]:
        out += empreinte((p.get("transition_in") or []) + p["sequence"])
        for n in sorted(p.get("endings") or {}):
            out += empreinte(p["endings"][n])
    return [x for x in out if x]


def accords(g: dict) -> list[str]:
    """Suite des changements d'accord, sans tenir compte des mesures."""
    out = []
    for x in suite(g):
        for a in x.split("|"):
            if not out or out[-1] != a:
                out.append(a)
    return out


def main(argv: list[str]) -> int:
    manuelles = {f.stem: json.loads(f.read_text()) for f in Path(argv[0]).glob("*-*.json")}
    dossier = Path(argv[1]) if len(argv) > 1 else RACINE / "grilles"
    generees = {f.stem: json.loads(f.read_text()) for f in dossier.glob("*-*.json")}
    lignes, absentes = [], []
    for sid, m in sorted(manuelles.items()):
        cle = normaliser(m["title"])
        candidats = [g for g in generees.values() if normaliser(g["title"]) == cle]
        if not candidats:
            absentes.append(sid)
            continue
        g = max(candidats, key=lambda g: fuzz.ratio(normaliser(g["composer"]), normaliser(m["composer"])))
        sm, sg = [neutre(x) for x in suite(m)], suite(g)
        am, ag = [neutre(x) for x in accords(m)], accords(g)
        d = max(range(12), key=lambda d: SequenceMatcher(None, am, [transposer(x, d + 12) for x in ag], autojunk=False).ratio())
        mesures = SequenceMatcher(None, sm, [transposer(x, d + 12) for x in sg], autojunk=False).ratio()
        enchainement = SequenceMatcher(None, am, [transposer(x, d + 12) for x in ag], autojunk=False).ratio()
        pm = len([p for p in m["parts"] if p["name"] != "Coda"])
        pg = len([p for p in g["parts"] if p["name"] != "Coda"])
        decalage = f" décalage {d if d <= 6 else d - 12:+d} demi-tons" if d else ""
        lignes.append((mesures, enchainement, sid + decalage, pm, pg, g["form"]))
    lignes.sort()
    print(f"Comparées : {len(lignes)} ; sans MXL : {len(absentes)} ({', '.join(absentes)})")
    if lignes:
        moy = sum(l[0] for l in lignes) / len(lignes)
        moy2 = sum(l[1] for l in lignes) / len(lignes)
        print(f"Mesures identiques (moyenne) : {moy:.0%} ; enchaînement d'accords : {moy2:.0%}")
        print(f"≥ 90 % : {sum(l[0] >= 0.9 for l in lignes)} ; 70–90 % : {sum(0.7 <= l[0] < 0.9 for l in lignes)} ; < 70 % : {sum(l[0] < 0.7 for l in lignes)}")
        print(f"Même nombre de parties (hors coda) : {sum(l[3] == l[4] for l in lignes)}/{len(lignes)}")
        for l in lignes:
            print(f"  {l[0]:.0%} {l[1]:.0%}  {l[2]}  parties {l[3]}→{l[4]}  {l[5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
