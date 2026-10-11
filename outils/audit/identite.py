"""« Est-ce bien la partition attendue ? » d'après sorties/inventaire.jsonl.

Contrôles :
- titre lu dans le fichier (en-tête PDF, crédits MXL) ≟ titre du nom de fichier ;
- versions d'un même morceau (MXL et PDF vectoriels, C / Bb / Eb) : une fois
  ramenées en concert, les fondamentales des accords doivent former la même
  suite. Si une version ne colle qu'après un décalage, elle est mal étiquetée
  (ex. une « C » qui est en fait en Sib) ; si aucun décalage ne colle, c'est
  un autre contenu (autre morceau, autre arrangement) ;
- les fichiers « - variant N » sont comparés à l'original de la même façon.

Usage : outils/audit/.venv/bin/python -I outils/audit/identite.py
Sorties : sorties/identite.json (détail) + résumé court.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventaire import normaliser  # noqa: E402

SORTIES = Path(__file__).resolve().parent / "sorties"

# Décalage écrit → concert, en demi-tons (mod 12).
DECALAGE = {"c": 0, "bb": 2, "eb": 9}
SEUIL_TITRE = 70
SEUIL_ACCORDS = 0.8
MIN_ACCORDS = 8


def en_concert(racines: list[int], instrument: str) -> list[int]:
    d = DECALAGE[instrument]
    return [(r - d) % 12 for r in racines]


def similarite(a: list[int], b: list[int]) -> float:
    """Meilleur de : suite ordonnée, ou multiensemble (l'ordre lu dans un PDF
    peut être bruité par le placement des symboles)."""
    if not a or not b:
        return 0.0
    suite = SequenceMatcher(None, a, b, autojunk=False).ratio()
    ca, cb = Counter(a), Counter(b)
    sac = sum((ca & cb).values()) / max(len(a), len(b))
    return max(suite, sac)


def meilleur_decalage(a: list[int], b: list[int]) -> tuple[int, float]:
    """Décalage (en demi-tons, −5..+6) à appliquer à b pour ressembler le plus à a."""
    scores = [(similarite(a, [(r + s) % 12 for r in b]), s) for s in range(-5, 7)]
    score, s = max(scores, key=lambda x: (x[0], -abs(x[1])))
    return s, score


def comparer(ref: list[int], autre: list[int]) -> dict:
    """Verdict d'une version (déjà en concert) face à la référence."""
    sim = similarite(ref, autre)
    if sim >= SEUIL_ACCORDS:
        return {"verdict": "ok", "similarite": round(sim, 2)}
    s, score = meilleur_decalage(ref, autre)
    if s != 0 and score >= SEUIL_ACCORDS:
        return {"verdict": "decalee", "decalage": s, "similarite": round(score, 2)}
    return {"verdict": "differente", "similarite": round(max(sim, score), 2)}


def versions_comparables(lignes: list[dict]) -> list[dict]:
    """Versions avec assez d'accords lus (MXL, ou PDF vectoriel), thème seulement."""
    return [
        l
        for l in lignes
        if l.get("partie") == "theme"
        and l.get("instrument") in DECALAGE
        and not l.get("scanne")
        and len(l.get("racines") or []) >= MIN_ACCORDS
    ]


def choisir_reference(versions: list[dict]) -> dict:
    """La version qui s'accorde avec le plus d'autres (médoïde).

    À égalité : MXL C non variant d'abord, puis tout MXL, puis PDF C. Ainsi une
    version isolée (ex. un MXL C décalé alors que les cinq autres concordent)
    n'est jamais prise pour référence.
    """
    concert = {id(v): en_concert(v["racines"], v["instrument"]) for v in versions}

    def accords(v: dict) -> int:
        return sum(
            similarite(concert[id(v)], concert[id(w)]) >= SEUIL_ACCORDS for w in versions if w is not v
        )

    return min(
        versions,
        key=lambda l: (-accords(l), l["type"] != "mxl", l["instrument"] != "c", l["variant"], l["fichier"]),
    )


def controle_titres(lignes: list[dict]) -> list[dict]:
    ecarts = []
    for l in lignes:
        if l.get("scanne") or not l.get("titre_lu") or "titre" not in l:
            continue
        score = fuzz.token_set_ratio(normaliser(l["titre"]), normaliser(l["titre_lu"]))
        if score < SEUIL_TITRE:
            ecarts.append({"fichier": l["fichier"], "titre_lu": l["titre_lu"], "score": round(score)})
    return ecarts


def controle_versions(lignes: list[dict]) -> list[dict]:
    par_morceau: dict[str, list[dict]] = defaultdict(list)
    for l in versions_comparables(lignes):
        par_morceau[l["cle"]].append(l)
    resultats = []
    for cle, versions in sorted(par_morceau.items()):
        if len(versions) < 2:
            continue
        ref = choisir_reference(versions)
        ref_c = en_concert(ref["racines"], ref["instrument"])
        for v in versions:
            if v is ref:
                continue
            r = comparer(ref_c, en_concert(v["racines"], v["instrument"]))
            if r["verdict"] != "ok":
                resultats.append({"morceau": cle, "fichier": v["fichier"], "reference": ref["fichier"], **r})
    return resultats


def controle_variants(lignes: list[dict]) -> list[dict]:
    originaux = {
        (l["cle"], l["partie"], l["instrument"], l["type"]): l for l in lignes if "cle" in l and not l["variant"]
    }
    out = []
    for l in lignes:
        if not l.get("variant"):
            continue
        o = originaux.get((l["cle"], l["partie"], l["instrument"], l["type"]))
        info = {
            "fichier": l["fichier"],
            "original": o["fichier"] if o else None,
            "pages": [o.get("pages") if o else None, l.get("pages")],
            "scanne": [o.get("scanne") if o else None, l.get("scanne")],
            "titre_lu": [o.get("titre_lu") if o else None, l.get("titre_lu")],
        }
        if o and len(o.get("racines") or []) >= MIN_ACCORDS and len(l.get("racines") or []) >= MIN_ACCORDS:
            info.update(comparer(o["racines"], l["racines"]))
        else:
            info["verdict"] = "non comparable (scan ou sans accords)"
        out.append(info)
    return out


def main() -> int:
    lignes = [json.loads(x) for x in (SORTIES / "inventaire.jsonl").open(encoding="utf-8")]
    titres = controle_titres(lignes)
    versions = controle_versions(lignes)
    variants = controle_variants(lignes)
    (SORTIES / "identite.json").write_text(
        json.dumps({"titres": titres, "versions": versions, "variants": variants}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"Titres lus ≠ nom de fichier : {len(titres)}")
    for e in sorted(titres, key=lambda e: e["score"])[:15]:
        print(f"  {e['score']:>3} | {e['fichier'][4:70]} | lu : {e['titre_lu'][:40]}")
    c = Counter(v["verdict"] for v in versions)
    print(f"Versions en écart avec la référence : {dict(c)}")
    print(f"  décalages : {dict(Counter(v['decalage'] for v in versions if v['verdict'] == 'decalee'))}")
    for v in [v for v in versions if v["verdict"] == "differente"][:15]:
        print(f"  ≠ {v['similarite']:.2f} | {v['fichier'][:80]}")
    print(f"Variants : {dict(Counter(v['verdict'] for v in variants))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
