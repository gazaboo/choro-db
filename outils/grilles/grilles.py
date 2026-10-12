"""Grilles d'accords générées depuis les MXL (version C, concert).

Une grille par morceau, au format des grilles de l'application d'apprentissage :
parties (A, B, C…, Coda), une entrée par mesure écrite ([] = accord tenu),
fins 1/2, reprises, tonalité de chaque partie.

Les MXL n'ont presque jamais de repères A/B : les parties sont découpées sur
les doubles barres, les reprises, les fins et le signe de coda. Une section
dont les accords reprennent une partie déjà vue (A réécrit après B) n'est pas
dupliquée : elle n'apparaît que dans la forme.

Usage :
    outils/audit/.venv/bin/python -I outils/grilles/grilles.py            # tout mxl/C → grilles/
    outils/audit/.venv/bin/python -I outils/grilles/grilles.py FICHIER.mxl  # un fichier, sur stdout
"""

from __future__ import annotations

import json
import sys
import unicodedata
import re
import zipfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET

RACINE = Path(__file__).resolve().parents[2]
SORTIE = RACINE / "grilles"

LETTRES = "CDEFGAB"
PAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
QUINTES_MAJEUR = ["Cb", "Gb", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#"]
QUINTES_MINEUR = ["Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E", "B", "F#", "C#", "G#", "D#", "A#"]

# kind MusicXML → suffixe dans la notation des grilles (C, Cm, C7, Cm7b5, Cdim, Cmaj7…).
SUFFIXES = {
    "major": "",
    "minor": "m",
    "augmented": "(#5)",
    "diminished": "dim",
    "dominant": "7",
    "major-seventh": "maj7",
    "minor-seventh": "m7",
    "diminished-seventh": "dim7",
    "augmented-seventh": "7(#5)",
    "half-diminished": "m7b5",
    "major-minor": "m(maj7)",
    "major-sixth": "6",
    "minor-sixth": "m6",
    "dominant-ninth": "9",
    "major-ninth": "maj7(9)",
    "minor-ninth": "m9",
    "dominant-11th": "11",
    "minor-11th": "m11",
    "dominant-13th": "13",
    "suspended-fourth": "sus4",
    "suspended-second": "sus2",
    "power": "5",
}
DOUBLES_BARRES = {"light-light", "light-heavy", "heavy-light", "heavy-heavy"}


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def note_nom(step: str, alter: int) -> str:
    return step + ("#" * alter if alter > 0 else "b" * -alter)


def accord(h: ET.Element) -> str | None:
    """Nom d'un <harmony>, ex. « A7(b9)/C# », ou None s'il est illisible."""
    if h.get("print-object") == "no" or h.find("root") is None:
        return None
    racine = note_nom(h.findtext("root/root-step"), int(float(h.findtext("root/root-alter") or 0)))
    kind = (h.findtext("kind") or "major").strip()
    suffixe = SUFFIXES.get(kind, "")
    ajouts = []
    for d in h.findall("degree"):
        typ, val, alt = d.findtext("degree-type"), d.findtext("degree-value"), int(float(d.findtext("degree-alter") or 0))
        signe = "#" if alt > 0 else "b" if alt < 0 else ""
        if kind == "minor-seventh" and typ == "alter" and val == "5" and alt == -1:
            suffixe = "m7b5"
        elif kind == "suspended-fourth" and typ == "add" and val == "7":
            suffixe = "7sus4"
        elif kind == "diminished" and typ == "add" and val == "7":
            suffixe = "dim7"
        elif typ != "subtract":
            ajouts.append(signe + val)
    if ajouts:
        suffixe += "(" + ",".join(ajouts) + ")"
    nom = racine + suffixe
    if h.find("bass") is not None:
        nom += "/" + note_nom(h.findtext("bass/bass-step"), int(float(h.findtext("bass/bass-alter") or 0)))
    return nom


@dataclass
class Mesure:
    position: int
    numero: str
    accords: list[str] = field(default_factory=list)
    implicite: bool = False
    fin_gauche: bool = False  # double barre ou reprise à gauche
    fin_droite: bool = False  # double barre ou reprise à droite
    reprise_debut: bool = False
    reprise_fin: bool = False
    fins: list[str] = field(default_factory=list)  # numéros de fin (« 1 », « 2 ») débutant ici
    fin_stop: bool = False  # une fin (volta) s'arrête ici
    coda: bool = False  # signe de coda en tête de mesure
    segno: bool = False
    renvoi: str | None = None  # « D.S. », « D.C. », « To Coda »
    fifths: int | None = None
    mode: str | None = None
    metrique: str | None = None


def lire(racine: ET.Element) -> list[Mesure]:
    parties = racine.findall("part")
    partie = max(parties, key=lambda p: len(list(p.iter("harmony"))))
    mesures = []
    for i, m in enumerate(partie.findall("measure")):
        me = Mesure(i, m.get("number", str(i + 1)), implicite=m.get("implicit") == "yes")
        pos, divisions, evenements = 0, None, []
        for el in m:
            if el.tag == "attributes":
                cle = el.find("key")
                if cle is not None and cle.findtext("fifths") is not None:
                    me.fifths, me.mode = int(cle.findtext("fifths")), cle.findtext("mode")
                t = el.find("time")
                if t is not None and t.findtext("beats"):
                    me.metrique = f"{t.findtext('beats')}/{t.findtext('beat-type')}"
            elif el.tag == "harmony":
                nom = accord(el)
                decalage = int(float(el.findtext("offset") or 0))
                if nom:
                    evenements.append((pos + decalage, len(evenements), nom))
            elif el.tag == "note":
                if el.find("chord") is None and el.find("grace") is None:
                    pos += int(float(el.findtext("duration") or 0))
            elif el.tag == "backup":
                pos -= int(float(el.findtext("duration") or 0))
            elif el.tag == "forward":
                pos += int(float(el.findtext("duration") or 0))
            elif el.tag == "barline":
                gauche = el.get("location") == "left"
                rep = el.find("repeat")
                if el.findtext("bar-style") in DOUBLES_BARRES or rep is not None:
                    if gauche:
                        me.fin_gauche = True
                    else:
                        me.fin_droite = True
                if rep is not None:
                    if rep.get("direction") == "forward":
                        me.reprise_debut = True
                    else:
                        me.reprise_fin = True
                for e in el.findall("ending"):
                    if e.get("type") == "start":
                        me.fins += [n.strip() for n in re.split(r"[,\s]+", e.get("number", "")) if n.strip()]
                    else:
                        me.fin_stop = True
            elif el.tag == "direction":
                for dt in el.findall("direction-type"):
                    if dt.find("coda") is not None:
                        me.coda = True
                    if dt.find("segno") is not None:
                        me.segno = True
                    mots = " ".join((w.text or "") for w in dt.findall("words")).strip()
                    if re.search(r"D\.?\s?S\.?|dal segno", mots, re.I):
                        me.renvoi = "D.S."
                    elif re.search(r"D\.?\s?C\.?|da capo", mots, re.I):
                        me.renvoi = "D.C."
                    elif re.search(r"to coda|al coda", mots, re.I) and not me.renvoi:
                        me.renvoi = "To Coda"
                son = el.find("sound")
                if son is not None:
                    if son.get("dalsegno"):
                        me.renvoi = "D.S."
                    elif son.get("dacapo") == "yes":
                        me.renvoi = "D.C."
            elif el.tag == "sound":
                if el.get("dalsegno"):
                    me.renvoi = "D.S."
                elif el.get("dacapo") == "yes":
                    me.renvoi = "D.C."
        for _, _, nom in sorted(evenements):
            if not me.accords or me.accords[-1] != nom:
                me.accords.append(nom)
        mesures.append(me)
    # Coda : le second signe de coda marque le début de la coda (le premier, le renvoi).
    codas = [m for m in mesures if m.coda]
    for m in codas[:-1] if len(codas) > 1 else []:
        m.coda = False
    if len(codas) == 1 and codas[0].position < len(mesures) * 0.5:
        codas[0].coda = False
    return mesures


def segmenter(mesures: list[Mesure]) -> list[list[Mesure]]:
    """Coupe la suite de mesures en sections, une fin (1/2) restant dans sa section."""
    segments, courant = [], []
    dans_fins = False
    for i, m in enumerate(mesures):
        if m.fins:
            dans_fins = True
        if courant and not dans_fins and (m.fin_gauche or m.reprise_debut or m.coda):
            segments.append(courant)
            courant = []
        courant.append(m)
        suivant = mesures[i + 1] if i + 1 < len(mesures) else None
        if dans_fins and m.fin_stop and not (suivant and suivant.fins):
            # Dernière fin : la section se clôt ici.
            dans_fins = False
            segments.append(courant)
            courant = []
            continue
        if not dans_fins and (m.fin_droite or m.reprise_fin):
            if suivant is None or not suivant.fins:
                segments.append(courant)
                courant = []
    if courant:
        segments.append(courant)
    # Sections trop courtes (levée isolée, barre double de passage) : rattachées à la voisine.
    fusion = []
    for s in segments:
        court = sum(not m.implicite for m in s) <= 2 and not s[0].coda and not any(m.fins for m in s)
        if court and fusion:
            fusion[-1] = fusion[-1] + s
        elif fusion and len(fusion[-1]) <= 2 and not fusion[-1][0].coda and not any(m.fins for m in fusion[-1]):
            fusion[-1] = fusion[-1] + s
        else:
            fusion.append(s)
    return fusion


def simplifier(nom: str) -> str:
    """Même règle que simplifyChord() de l'application (grille.ts)."""
    m = re.match(r"^([A-G](?:#|b)?)\s*(.*)$", nom.strip())
    if not m:
        return nom
    racine, reste = m.group(1), m.group(2)
    qualite = reste.split("/")[0].strip()
    if re.match(r"^dim", qualite, re.I) or qualite == "°":
        return racine + "dim"
    if re.match(r"^m(?:in)?7b5$", qualite, re.I) or qualite == "ø":
        return racine + "m7b5"
    if re.match(r"^m", qualite, re.I) and not re.match(r"^maj", qualite, re.I):
        return racine + "m"
    if re.match(r"^(?:7|9|11|13)", qualite):
        return racine + "7"
    return racine


def demi_ton(nom: str) -> int:
    return (PAS[nom[0]] + nom[1:].count("#") - nom[1:].count("b")) % 12


def tonique(cellules: list[list[str]], fifths: int, mode: str | None) -> str:
    """Centre tonal : armure (majeur ou relatif mineur), départagée par l'accord final."""
    majeur = QUINTES_MAJEUR[max(-7, min(7, fifths)) + 7]
    mineur = QUINTES_MINEUR[max(-7, min(7, fifths)) + 7] + "m"
    accords = [simplifier(a) for c in cellules for a in c]
    if not accords:
        return mineur if mode == "minor" else majeur
    dernier = accords[-1]
    if dernier in (majeur, mineur):
        return dernier
    if dernier.endswith("7") and not dernier.endswith("m7"):
        cible = (demi_ton(dernier[:-1]) + 5) % 12
        for t in (majeur, mineur):
            if demi_ton(t.rstrip("m")) == cible:
                return t
    if accords.count(mineur) > accords.count(majeur):
        return mineur
    if accords.count(majeur) > accords.count(mineur):
        return majeur
    return mineur if mode == "minor" else majeur


def cellules_de(segment: list[Mesure]) -> tuple[list[list[str]], dict[str, list[list[str]]]]:
    seq, fins, courante = [], {}, None
    for m in segment:
        if m.fins:
            courante = m.fins
            for n in m.fins:
                fins.setdefault(n, [])
        if courante:
            for n in courante:
                fins[n].append(list(m.accords))
            if m.fin_stop:
                courante = None
        elif m.implicite and not m.accords:
            continue  # levée sans accord
        else:
            seq.append(list(m.accords))
    return seq, fins


def empreinte(cellules: list[list[str]]) -> list[str]:
    """Accord sonnant à chaque mesure (accords tenus remplis), simplifié."""
    out, tenu = [], None
    for c in cellules:
        if c:
            tenu = simplifier(c[-1])
            out.append("|".join(dict.fromkeys(simplifier(a) for a in c)))
        else:
            out.append(tenu or "")
    return out


def grille(chemin: Path) -> dict:
    with zipfile.ZipFile(chemin) as z:
        c = ET.fromstring(z.read("META-INF/container.xml"))
        racine = ET.fromstring(z.read(c.find(".//{*}rootfile").get("full-path")))
    mesures = lire(racine)
    compositeur, titre = [s.strip() for s in chemin.stem.split(" - ")[:2]]
    fifths, mode, metrique = 0, None, None
    parties, forme, notes, lettre = [], [], [], 0
    segments = segmenter(mesures)
    for i, segment in enumerate(segments):
        # Une coda clôt le morceau et ne se reprend pas : sinon le signe marque une partie.
        if segment[0].coda and (i < len(segments) - 2 or any(m.reprise_fin or m.fins for m in segment)):
            segment[0].coda = False
    segments = segmenter(mesures)
    transition = []
    for i, segment in enumerate(segments):
        # « Coda » d'une ou deux mesures avant la partie suivante : c'est une liaison (vers le C).
        if segment[0].coda and i < len(segments) - 1 and len(segment) <= 2:
            transition = [list(m.accords) for m in segment]
            continue
        for m in mesures[: segment[0].position + 1]:
            if m.fifths is not None:
                fifths, mode = m.fifths, m.mode
            metrique = metrique or m.metrique
        seq, fins = cellules_de(segment)
        if not any(seq) and not any(any(c) for f in fins.values() for c in f):
            continue
        emp = empreinte(seq)
        deja = next(
            (p for p in parties if p["name"] != "Coda" and SequenceMatcher(None, p["_emp"], emp).ratio() >= 0.85), None
        )
        if deja:
            forme.append(deja["name"])
            continue
        nom = "Coda" if segment[0].coda else LETTRES_PARTIES[lettre]
        if nom != "Coda":
            lettre = min(lettre + 1, len(LETTRES_PARTIES) - 1)
        partie = {
            "name": nom,
            "tonic": tonique(seq + (fins.get(max(fins), []) if fins else []), fifths, mode),
            "bars": f"{segment[0].numero}–{segment[-1].numero}",
            "repeat": any(m.reprise_fin for m in segment) or bool(fins),
            "sequence": seq,
        }
        if fins:
            partie["endings"] = fins
        if transition:
            partie["transition_in"], transition = transition, []
        partie["_emp"] = emp
        if not seq or not seq[0]:
            notes.append(f"{nom} : première mesure sans accord")
        parties.append(partie)
        renvoi = next((m.renvoi for m in segment if m.renvoi in ("D.S.", "D.C.")), None)
        forme.append(nom + (" (reprise)" if partie["repeat"] else ""))
        if renvoi:
            forme.append(renvoi)
    for p in parties:
        del p["_emp"]
    vides = sum(1 for p in parties for c in p["sequence"] if not c)
    total = sum(len(p["sequence"]) for p in parties)
    if total and vides / total > 0.4:
        notes.append(f"{vides}/{total} mesures sans accord écrit")
    return {
        "song_id": f"{normaliser(titre)}-{normaliser(compositeur)}",
        "title": titre,
        "composer": compositeur,
        "transposition": "c",
        "meter": metrique or "2/4",
        "form": " — ".join(forme),
        "parts": parties,
        "notes": ["Grille générée automatiquement depuis la partition MusicXML : à vérifier."] + notes,
        "confidence": "medium" if parties else "low",
        "source": [f"mxl/C/{chemin.name}"],
        "generated": "mxl",
    }


LETTRES_PARTIES = "ABCDEFGH"
NOTE_TONALITE = "Tonalité de la partition source non vérifiée."


def ecrire_index() -> None:
    """index.json de toutes les grilles (MXL et PDF), et note sur les tonalités douteuses."""
    avert = json.loads((RACINE / "avertissements.json").read_text(encoding="utf-8"))["fichiers"]
    douteux = {
        tuple(normaliser(c) for c in Path(f).stem.split(" - ")[:2])
        for f, codes in avert.items()
        if "tonalite-non-verifiee" in codes
    }
    index = []
    for f in sorted(SORTIE.glob("*-*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        if (normaliser(g["composer"]), normaliser(g["title"])) in douteux and NOTE_TONALITE not in g["notes"]:
            g["notes"].append(NOTE_TONALITE)
            f.write_text(json.dumps(g, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        index.append(
            {k: g[k] for k in ("song_id", "title", "composer", "confidence", "generated")}
            | {"file": f.name, "parts": [p["name"] for p in g["parts"]]}
        )
    (SORTIE / "index.json").write_text(
        json.dumps(
            {
                "description": "Grilles d'accords (Ut/C) générées automatiquement depuis le MusicXML ou le "
                "texte d'un PDF vectoriel. Après croiser.py, seules restent celles qu'une partition "
                "indépendante confirme (confidence high) — voir README.md.",
                "count": len(index),
                "songs": index,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    if argv:
        print(json.dumps(grille(Path(argv[0])), ensure_ascii=False, indent=1))
        return 0
    SORTIE.mkdir(exist_ok=True)
    ecrites, vides = 0, 0
    for f in sorted((RACINE / "mxl" / "C").glob("* - Theme - C.mxl")):  # pas les contrechants
        g = grille(f)
        if not g["parts"]:
            vides += 1
            continue
        (SORTIE / f"{g['song_id']}.json").write_text(json.dumps(g, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        ecrites += 1
    ecrire_index()
    print(f"{ecrites} grilles écrites dans grilles/ ; {vides} MXL sans accord")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
