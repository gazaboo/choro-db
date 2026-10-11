"""Tessiture des versions Sib (clarinette) et Mib (sax alto) d'après les MXL.

Pour chaque MXL de thème en Bb / Eb, on cherche le déplacement d'octave qui
fait tenir la mélodie dans la tessiture écrite de l'instrument :
1. d'abord un déplacement unique pour tout le morceau ;
2. sinon, un déplacement par section (repères, doubles barres, reprises),
   en restant si possible sur le choix de la section précédente.
On ne descend pas plus fin (blocs de quelques mesures) : la ligne serait
hachée de sauts d'octave. Les notes restantes sont signalées.
Ce qui ne tient toujours pas est signalé.

Usage :
    outils/audit/.venv/bin/python -I outils/audit/tessiture.py              # rapport
    outils/audit/.venv/bin/python -I outils/audit/tessiture.py --appliquer  # modifie les MXL
Sortie : sorties/tessiture.json (plan par fichier) + résumé.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inventaire import PAS, lire_musicxml  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
SORTIES = Path(__file__).resolve().parent / "sorties"

# Tessiture écrite (MIDI) : clarinette Sib Mi3–Do7, sax alto Mib Sib3–Fa♯6.
PLAGES = {"Bb": (52, 96), "Eb": (58, 90)}
DECALAGES = (0, -12, 12, -24)  # ordre = préférence à égalité


@dataclass
class Mesure:
    numero: str
    notes: list[int]
    debut_section: bool
    position: int = 0


def lire_mesures(racine: ET.Element) -> list[Mesure]:
    """Mesures de la première partie, avec les débuts de section."""
    part = racine.find("part")
    mesures: list[Mesure] = []
    coupure_suivante = True
    for position, m in enumerate(part.findall("measure")):
        notes = []
        for n in m.iter("note"):
            p = n.find("pitch")
            if p is None:
                continue
            alter = int(float(p.findtext("alter") or 0))
            notes.append(12 * (int(p.findtext("octave")) + 1) + PAS[p.findtext("step")] + alter)
        repere = m.find(".//direction/direction-type/rehearsal") is not None
        reprise_debut = any(r.get("direction") == "forward" for r in m.iter("repeat"))
        mesures.append(Mesure(m.get("number"), notes, coupure_suivante or repere or reprise_debut, position))
        # Double barre, barre finale ou fin de reprise : la mesure suivante ouvre une section.
        styles = {b.findtext("bar-style") for b in m.findall("barline") if b.get("location", "right") == "right"}
        reprise_fin = any(r.get("direction") == "backward" for r in m.iter("repeat"))
        coupure_suivante = bool(styles & {"light-light", "light-heavy", "heavy-light"}) or reprise_fin
    return mesures


def sections(mesures: list[Mesure]) -> list[list[Mesure]]:
    out: list[list[Mesure]] = []
    for m in mesures:
        if m.debut_section or not out:
            out.append([])
        out[-1].append(m)
    return out


def hors_plage(notes: list[int], plage: tuple[int, int], decalage: int) -> int:
    bas, haut = plage
    return sum(not (bas <= n + decalage <= haut) for n in notes)


def meilleur(notes: list[int], plage: tuple[int, int], prefere: int | None = None) -> tuple[int, int]:
    """(décalage, notes hors plage) ; à égalité : le décalage préféré, puis l'ordre de DECALAGES."""
    ordre = ([prefere] if prefere is not None else []) + [d for d in DECALAGES if d != prefere]
    return min(((d, hors_plage(notes, plage, d)) for d in ordre), key=lambda x: x[1])


def planifier(mesures: list[Mesure], plage: tuple[int, int]) -> dict:
    toutes = [n for m in mesures for n in m.notes]
    if not toutes:
        return {"cas": "sans notes"}
    avant = hors_plage(toutes, plage, 0)
    if avant == 0:
        return {"cas": "ok", "hors_plage": 0}
    d, reste = meilleur(toutes, plage)
    if reste == 0:
        return {"cas": "global", "decalage": d, "avant": avant, "hors_plage": 0}
    plan, precedent, total = [], 0, 0
    for sec in sections(mesures):
        notes = [n for m in sec for n in m.notes]
        ds, r = meilleur(notes, plage, prefere=precedent)
        total += r
        plan.append(
            {
                "mesures": [sec[0].numero, sec[-1].numero],
                "positions": [sec[0].position, sec[-1].position],
                "decalage": ds,
                "hors_plage": r,
            }
        )
        precedent = ds
    # Regrouper les sections consécutives de même décalage.
    fusion: list[dict] = []
    for p in plan:
        if fusion and fusion[-1]["decalage"] == p["decalage"]:
            fusion[-1]["mesures"][1] = p["mesures"][1]
            fusion[-1]["positions"][1] = p["positions"][1]
            fusion[-1]["hors_plage"] += p["hors_plage"]
        else:
            fusion.append({**p, "mesures": list(p["mesures"]), "positions": list(p["positions"])})
    if len(fusion) == 1:
        return {"cas": "global", "decalage": fusion[0]["decalage"], "avant": avant, "hors_plage": total}
    return {"cas": "sections", "sections": fusion, "avant": avant, "hors_plage": total}


def analyser(chemin: Path) -> dict:
    instrument = chemin.parent.name
    racine = ET.fromstring(lire_musicxml(chemin))
    plan = planifier(lire_mesures(racine), PLAGES[instrument])
    return {"fichier": chemin.relative_to(RACINE).as_posix(), "instrument": instrument, **plan}


def appliquer(plan: dict) -> bool:
    """Applique le plan au MXL ; renvoie True si le fichier a changé."""
    from transposer import transposer_fichier

    chemin = RACINE / plan["fichier"]
    if plan["cas"] == "global" and plan["decalage"]:
        o = plan["decalage"] // 12
        transposer_fichier(chemin, 7 * o, 12 * o)
        return True
    if plan["cas"] == "sections":
        for s in plan["sections"]:
            if s["decalage"]:
                o = s["decalage"] // 12
                transposer_fichier(chemin, 7 * o, 12 * o, tuple(s["positions"]))
        return True
    return False


NOM_PDF = {"Bb": "Clarinet Bb", "Eb": "Saxophone Eb"}


def pdf_de(fichier_mxl: str) -> str:
    base, inst = Path(fichier_mxl).stem.rsplit(" - ", 1)
    return f"pdf/{base} - {NOM_PDF[inst]}.pdf"


def editions_differentes() -> set[str]:
    """MXL Bb/Eb des morceaux dont les PDF viennent d'une autre édition (identite.py) :
    les régénérer remplacerait cette édition, on ne les touche pas."""
    ide = json.loads((SORTIES / "identite.json").read_text(encoding="utf-8"))
    inv = [json.loads(l) for l in (SORTIES / "inventaire.jsonl").open(encoding="utf-8")]
    cles = {v["morceau"] for v in ide["versions"] if v["verdict"] == "differente"}
    return {l["fichier"] for l in inv if l["type"] == "mxl" and l.get("cle") in cles}


def avertir(plans: list[dict]) -> int:
    """Ajoute « tessiture-hors-plage » dans avertissements.json pour les PDF concernés."""
    chemin = RACINE / "avertissements.json"
    av = json.loads(chemin.read_text(encoding="utf-8"))
    fichiers = av["fichiers"]
    for codes in fichiers.values():
        if "tessiture-hors-plage" in codes:
            codes.remove("tessiture-hors-plage")
    n = 0
    for p in plans:
        pdf = pdf_de(p["fichier"])
        if p.get("hors_plage") and (RACINE / pdf).exists():
            fichiers.setdefault(pdf, []).append("tessiture-hors-plage")
            n += 1
    av["fichiers"] = {k: sorted(set(v)) for k, v in sorted(fichiers.items()) if v}
    av["_doc"] = (
        "Avertissements par fichier, affichés par l'application. Codes : "
        "tonalite-non-verifiee = les versions du morceau ne concordent pas, tonalité à confirmer ; "
        "tessiture-hors-plage = quelques notes restent hors de la tessiture de l'instrument "
        "(clarinette Sib Mi3–Do7, sax alto Mib Sib3–Fa♯6, écrit)."
    )
    chemin.write_text(json.dumps(av, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return n


def main(argv: list[str]) -> int:
    fichiers = sorted(p for i in PLAGES for p in (RACINE / "mxl" / i).glob("* - Theme - *.mxl"))
    plans = [analyser(f) for f in fichiers]
    (SORTIES / "tessiture.json").write_text(json.dumps(plans, ensure_ascii=False, indent=1), encoding="utf-8")
    for inst in PLAGES:
        ps = [p for p in plans if p["instrument"] == inst]
        c = Counter(p["cas"] for p in ps)
        dec = Counter(p.get("decalage") for p in ps if p["cas"] == "global")
        reste = [p for p in ps if p.get("hors_plage")]
        print(f"{inst} : {len(ps)} MXL — {dict(c)} ; décalages globaux {dict(dec)}")
        print(f"   encore hors plage après correction : {len(reste)} fichiers, {sum(p['hors_plage'] for p in reste)} notes")
        for p in sorted(reste, key=lambda p: -p["hors_plage"])[:6]:
            print(f"     {p['hors_plage']:>3} | {Path(p['fichier']).stem[:70]}")
    nb_sections = Counter(len(p["sections"]) for p in plans if p["cas"] == "sections")
    print(f"Plans par sections — nombre de blocs : {dict(sorted(nb_sections.items()))}")
    if "--appliquer" in argv:
        exclus = editions_differentes()
        modifies = [p["fichier"] for p in plans if p["fichier"] not in exclus and appliquer(p)]
        (SORTIES / "tessiture-modifies.json").write_text(json.dumps(modifies, ensure_ascii=False, indent=1))
        print(f"MXL modifiés : {len(modifies)} (exclus, PDF d'une autre édition : {len(exclus)})")
        n = avertir(plans)
        print(f"PDF avec avertissement de tessiture : {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
