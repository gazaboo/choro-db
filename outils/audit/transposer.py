"""Transposition directe d'un fichier MusicXML compressé (.mxl).

Agit sur le XML sans passer par un éditeur : hauteurs des notes, fondamentale
et basse des accords, armure. Les altérations d'affichage (<accidental>) sont
retirées : MuseScore les recalcule à l'import. La balise <transpose> (réglage
d'instrument transpositeur) est supprimée : la hauteur écrite devient celle
qu'on veut voir affichée.

Usage :
    outils/audit/.venv/bin/python -I outils/audit/transposer.py FICHIER.mxl \
        --pas -4 --demi-tons -7          # quinte juste descendante
    ... --octaves -1 [--mesures 16-31]    # octave, éventuellement partiel (positions, 0 = 1re mesure)
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

LETTRES = "CDEFGAB"
PAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def transposer_note(step: str, alter: int, octave: int, pas: int, demi_tons: int) -> tuple[str, int, int]:
    """Transpose une note de `pas` degrés diatoniques et `demi_tons` demi-tons."""
    i = LETTRES.index(step) + pas
    nouvelle_octave = octave + i // 7
    nouveau = LETTRES[i % 7]
    midi_cible = 12 * (octave + 1) + PAS[step] + alter + demi_tons
    naturel = 12 * (nouvelle_octave + 1) + PAS[nouveau]
    return nouveau, midi_cible - naturel, nouvelle_octave


def delta_quintes(demi_tons: int) -> int:
    """Variation de l'armure (en quintes) pour un intervalle donné."""
    d = (demi_tons * 7) % 12
    return d - 12 if d > 6 else d


def _set(parent, tag: str, valeur) -> None:
    el = parent.find(tag)
    if valeur == 0 and tag.endswith("alter"):
        if el is not None:
            parent.remove(el)
        return
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = str(valeur)


def transposer_racine(racine: ET.Element, pas: int, demi_tons: int, mesures: tuple[int, int] | None = None) -> None:
    """`mesures` = positions (0 = première mesure de la partie), bornes incluses.

    Par position et non par numéro : MuseScore numérote parfois « 66X1 »,
    l'anacrouse « 0 », et les numéros peuvent se répéter.
    """
    for part in racine.findall("part"):
        for position, mesure in enumerate(part.findall("measure")):
            if mesures is not None and not mesures[0] <= position <= mesures[1]:
                continue
            for p in mesure.iter("pitch"):
                s, a, o = transposer_note(
                    p.findtext("step"), int(float(p.findtext("alter") or 0)), int(p.findtext("octave")), pas, demi_tons
                )
                # Ordre imposé par le schéma : step, alter, octave.
                for enfant in list(p):
                    p.remove(enfant)
                ET.SubElement(p, "step").text = s
                if a:
                    ET.SubElement(p, "alter").text = str(a)
                ET.SubElement(p, "octave").text = str(o)
            if demi_tons % 12 == 0:
                continue  # déplacement d'octave : accords, armure, altérations inchangés
            for note in mesure.iter("note"):
                acc = note.find("accidental")
                if acc is not None:
                    note.remove(acc)
            for h in mesure.iter("harmony"):
                for quoi in ("root", "bass"):
                    el = h.find(quoi)
                    if el is None:
                        continue
                    s, a, _ = transposer_note(
                        el.findtext(f"{quoi}-step"), int(float(el.findtext(f"{quoi}-alter") or 0)), 4, pas, demi_tons
                    )
                    el.find(f"{quoi}-step").text = s
                    _set(el, f"{quoi}-alter", a)
            for k in mesure.iter("key"):
                f = k.find("fifths")
                if f is not None:
                    f.text = str(int(f.text) + delta_quintes(demi_tons))
            for attrs in mesure.iter("attributes"):
                for t in attrs.findall("transpose"):
                    attrs.remove(t)


def transposer_fichier(chemin: Path, pas: int, demi_tons: int, mesures: tuple[int, int] | None = None) -> None:
    with zipfile.ZipFile(chemin) as z:
        contenus = {n: z.read(n) for n in z.namelist()}
        infos = {n: z.getinfo(n) for n in z.namelist()}
    c = ET.fromstring(contenus["META-INF/container.xml"])
    racine_nom = c.find(".//{*}rootfile").get("full-path")
    texte = contenus[racine_nom]
    entete = texte[: texte.index(b"<score-partwise")]  # garde déclaration XML + DOCTYPE
    racine = ET.fromstring(texte)
    transposer_racine(racine, pas, demi_tons, mesures)
    contenus[racine_nom] = entete + ET.tostring(racine, encoding="utf-8")
    with zipfile.ZipFile(chemin, "w") as z:
        for n, data in contenus.items():
            z.writestr(infos[n], data, compress_type=zipfile.ZIP_STORED if n == "mimetype" else zipfile.ZIP_DEFLATED)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fichiers", nargs="+", type=Path)
    ap.add_argument("--pas", type=int, default=0, help="degrés diatoniques")
    ap.add_argument("--demi-tons", type=int, default=0)
    ap.add_argument("--octaves", type=int, default=0)
    ap.add_argument("--mesures", help="plage « début-fin » de positions de mesure (0 = première)")
    a = ap.parse_args(argv)
    pas, dt = a.pas + 7 * a.octaves, a.demi_tons + 12 * a.octaves
    mesures = tuple(map(int, a.mesures.split("-"))) if a.mesures else None
    for f in a.fichiers:
        transposer_fichier(f, pas, dt, mesures)
        print(f"transposé : {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


# Intervalles admis entre fondamentale et basse : degrés (0–6) → demi-tons.
INTERVALLES = {0: {0}, 1: {1, 2}, 2: {3, 4}, 3: {5, 6}, 4: {6, 7, 8}, 5: {8, 9}, 6: {10, 11}}


def orthographier_basse(root_step: str, root_alter: int, bass_step: str, bass_alter: int) -> tuple[str, int]:
    """Réécrit la basse d'un accord « X/Y » sous un nom cohérent avec sa fondamentale.

    La transposition automatique des sources produit des basses comme B/E♭ (quarte
    diminuée) au lieu de B/D♯ (tierce majeure). Même hauteur, autre nom.
    """
    d = (LETTRES.index(bass_step) - LETTRES.index(root_step)) % 7
    s = (PAS[bass_step] + bass_alter - PAS[root_step] - root_alter) % 12
    if s in INTERVALLES[d]:
        return bass_step, bass_alter
    hauteur = PAS[bass_step] + bass_alter
    candidats = []
    for deg, demi in INTERVALLES.items():
        if s not in demi:
            continue
        lettre = LETTRES[(LETTRES.index(root_step) + deg) % 7]
        alter = (hauteur - PAS[lettre] + 6) % 12 - 6
        if abs(alter) <= 1:
            candidats.append((abs(alter), lettre, alter))
    if not candidats:
        return bass_step, bass_alter
    _, lettre, alter = min(candidats)
    return lettre, alter


def corriger_basses(racine: ET.Element) -> int:
    n = 0
    for h in racine.iter("harmony"):
        b = h.find("bass")
        if b is None or h.find("root") is None:
            continue
        rs, ra = h.findtext("root/root-step"), int(float(h.findtext("root/root-alter") or 0))
        bs, ba = b.findtext("bass-step"), int(float(b.findtext("bass-alter") or 0))
        ns, na = orthographier_basse(rs, ra, bs, ba)
        if (ns, na) != (bs, ba):
            b.find("bass-step").text = ns
            _set(b, "bass-alter", na)
            n += 1
    return n


def corriger_basses_fichier(chemin: Path) -> int:
    with zipfile.ZipFile(chemin) as z:
        contenus = {n: z.read(n) for n in z.namelist()}
        infos = {n: z.getinfo(n) for n in z.namelist()}
    c = ET.fromstring(contenus["META-INF/container.xml"])
    racine_nom = c.find(".//{*}rootfile").get("full-path")
    texte = contenus[racine_nom]
    entete = texte[: texte.index(b"<score-partwise")]
    racine = ET.fromstring(texte)
    n = corriger_basses(racine)
    if n:
        contenus[racine_nom] = entete + ET.tostring(racine, encoding="utf-8")
        with zipfile.ZipFile(chemin, "w") as z:
            for nom, data in contenus.items():
                z.writestr(infos[nom], data, compress_type=zipfile.ZIP_STORED if nom == "mimetype" else zipfile.ZIP_DEFLATED)
    return n
