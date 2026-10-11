"""Régénère un PDF depuis son MXL avec MuseScore (mscore en ligne de commande).

Usage :
    outils/audit/.venv/bin/python -I outils/audit/reexporter.py "mxl/Bb/X - T - Theme - Bb.mxl" ...
Le PDF produit remplace pdf/<Compositeur - Titre - Partie - Instrument>.pdf
(Bb → « Clarinet Bb », Eb → « Saxophone Eb », C → « C »).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
NOM_PDF = {"C": "C", "Bb": "Clarinet Bb", "Eb": "Saxophone Eb"}


def pdf_pour(mxl: Path) -> Path:
    base, instrument = mxl.stem.rsplit(" - ", 1)
    return RACINE / "pdf" / f"{base} - {NOM_PDF[instrument]}.pdf"


# Code de sortie de mscore quand il juge la partition corrompue (souvent une
# mesure de durée incohérente dans la source) : on réessaie avec -f.
CODE_CORROMPU = 40


def reexporter(mxl: Path) -> tuple[Path, bool]:
    """Renvoie (PDF produit, True si MuseScore a jugé la source corrompue)."""
    cible = pdf_pour(mxl)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    r = subprocess.run(["mscore", "-o", str(cible), str(mxl)], env=env, capture_output=True, timeout=300)
    if r.returncode == CODE_CORROMPU:
        subprocess.run(["mscore", "-f", "-o", str(cible), str(mxl)], check=True, env=env, capture_output=True, timeout=300)
        return cible, True
    r.check_returncode()
    return cible, False


if __name__ == "__main__":
    for f in sys.argv[1:]:
        cible, corrompu = reexporter(Path(f))
        print(f"{f} → {cible.relative_to(RACINE)}{' (source jugée corrompue, forcé)' if corrompu else ''}")
