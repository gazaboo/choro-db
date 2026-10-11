"""Doublons binaires exacts de choro-db, d'après sorties/inventaire.jsonl.

Dans chaque groupe de fichiers identiques (même sha256), on garde un seul
fichier : nom conforme d'abord, puis sans « - variant N », puis sans « (1) »,
puis le chemin le plus court. Les autres sont à supprimer.

Usage (depuis la racine du dépôt) :
    outils/audit/.venv/bin/python -I outils/audit/doublons.py             # rapport
    outils/audit/.venv/bin/python -I outils/audit/doublons.py --appliquer # git rm
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SORTIES = Path(__file__).resolve().parent / "sorties"


def priorite(ligne: dict) -> tuple:
    """Plus petit = meilleur fichier à garder."""
    return (
        not ligne["nom_conforme"],
        ligne["variant"],
        ligne["copie"],
        len(ligne["fichier"]),
        ligne["fichier"],
    )


def plan_suppression(lignes: list[dict]) -> list[dict]:
    """Un enregistrement par groupe de doublons : fichier gardé + fichiers retirés."""
    groupes: dict[str, list[dict]] = defaultdict(list)
    for l in lignes:
        groupes[l["sha256"]].append(l)
    plan = []
    for sha, g in sorted(groupes.items(), key=lambda kv: min(x["fichier"] for x in kv[1])):
        if len(g) < 2:
            continue
        g = sorted(g, key=priorite)
        plan.append({"sha256": sha, "garde": g[0]["fichier"], "retire": [x["fichier"] for x in g[1:]]})
    return plan


def main(argv: list[str]) -> int:
    lignes = [json.loads(x) for x in (SORTIES / "inventaire.jsonl").open(encoding="utf-8")]
    plan = plan_suppression(lignes)
    (SORTIES / "doublons.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    retires = [f for p in plan for f in p["retire"]]
    print(f"Groupes de doublons exacts : {len(plan)} ; fichiers à retirer : {len(retires)}")
    gardes_variant = [p["garde"] for p in plan if " - variant " in p["garde"]]
    print(f"Groupes où le fichier gardé est un variant : {len(gardes_variant)}")
    for f in gardes_variant[:10]:
        print(f"  - {f}")
    if "--appliquer" in argv and retires:
        for i in range(0, len(retires), 200):
            subprocess.run(["git", "rm", "-q", "--", *retires[i : i + 200]], cwd=RACINE, check=True)
        print(f"{len(retires)} fichiers retirés de l'index git.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
