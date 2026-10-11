"""Inventaire de choro-db : une ligne JSON par fichier (pdf/ et mxl/).

Usage (depuis la racine du dépôt) :
    outils/audit/.venv/bin/python -I outils/audit/inventaire.py

Sorties (non versionnées) dans outils/audit/sorties/ :
    inventaire.jsonl  une ligne par fichier
    morceaux.json     déclinaisons disponibles par morceau
et un résumé court sur la sortie standard.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from xml.etree import ElementTree as ET

RACINE = Path(__file__).resolve().parents[2]
SORTIES = Path(__file__).resolve().parent / "sorties"

# Nom de fichier → instrument canonique (c / bb / eb).
INSTRUMENTS = {
    "c": "c",
    "bb": "bb",
    "clarinet bb": "bb",
    "eb": "eb",
    "saxophone eb": "eb",
}
PARTIES = {"theme": "theme", "contraponto": "contraponto", "contracanto": "contraponto"}
RE_VARIANT = re.compile(r"^variant (\d+)$", re.I)
RE_SUFFIXE_COPIE = re.compile(r"^(.*?)\((\d+)\)$")

# Symbole d'accord tel qu'exporté par MuseScore (C, F♯7, G♯dim, Bbm7(b5), C/E…).
RE_ACCORD = re.compile(
    r"^[A-G](?:[#♯b♭])?"
    r"(?:m|min|maj|M|dim|°|ø|aug|\+|sus[24]?|add)?"
    r"[0-9]*(?:\(?(?:[#♯b♭]?[0-9]+|maj7|M7)\)?)*"
    r"(?:/[A-G](?:[#♯b♭])?)?$"
)


def normaliser(texte: str) -> str:
    """Clé de comparaison : sans accents, minuscules, ponctuation réduite."""
    t = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def analyser_nom(nom: str) -> dict:
    """Découpe « Compositeur - Titre - Partie - Instrument[ - variant N].ext »."""
    base = nom.rsplit(".", 1)[0]
    champs = [c.strip() for c in base.split(" - ")]
    res: dict = {"nom_conforme": False, "variant": 0, "copie": 0}
    m = RE_VARIANT.match(champs[-1]) if champs else None
    if m:
        res["variant"] = int(m.group(1))
        champs = champs[:-1]
    if len(champs) < 4:
        res["anomalie_nom"] = f"{len(champs)} champs"
        return res
    instrument = champs[-1]
    m = RE_SUFFIXE_COPIE.match(instrument)
    if m:
        instrument, res["copie"] = m.group(1).strip(), int(m.group(2))
    inst = INSTRUMENTS.get(instrument.lower())
    partie = PARTIES.get(champs[-2].lower())
    res.update(
        compositeur=champs[0],
        titre=" - ".join(champs[1:-2]),
        partie=partie or champs[-2],
        instrument=inst or instrument,
    )
    if inst and partie:
        res["nom_conforme"] = True
    else:
        res["anomalie_nom"] = "partie ou instrument inconnu"
    res["cle"] = f"{normaliser(champs[0])}||{normaliser(res['titre'])}"
    return res


def sha256(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def est_accord(s: str) -> bool:
    return bool(RE_ACCORD.match(s.strip()))


def analyser_pdf(chemin: Path) -> dict:
    import pymupdf

    res: dict = {}
    try:
        doc = pymupdf.open(chemin)
    except Exception as e:  # PDF illisible
        return {"erreur": f"ouverture: {e}"}
    res["pages"] = doc.page_count
    texte_total = 0
    images = 0
    traces = 0
    accords: list[str] = []
    for page in doc:
        texte_total += len(page.get_text("text").strip())
        images += len(page.get_images(full=False))
        traces += len(page.get_drawings())
        for bloc in page.get_text("dict")["blocks"]:
            for ligne in bloc.get("lines", []):
                for span in ligne["spans"]:
                    if est_accord(span["text"]):
                        accords.append(span["text"].strip())
    res.update(texte=texte_total, images=images, traces=traces, accords=len(accords))
    res["accords_debut"] = accords[:16]
    res["scanne"] = texte_total < 20 and images > 0
    if doc.page_count:
        p0 = doc[0]
        res["format"] = [round(p0.rect.width), round(p0.rect.height)]
        # Titre = plus grande police de la première page (hors accords).
        spans = [
            s
            for b in p0.get_text("dict")["blocks"]
            for l in b.get("lines", [])
            for s in l["spans"]
            if s["text"].strip() and not est_accord(s["text"])
        ]
        if spans:
            grand = max(spans, key=lambda s: s["size"])
            res["titre_lu"] = grand["text"].strip()
            # Texte d'en-tête (haut de page) : sert à retrouver le compositeur.
            haut = p0.rect.height * 0.2
            res["entete"] = " | ".join(
                s["text"].strip() for s in spans if s["bbox"][1] < haut
            )[:200]
    return res


def _texte(el) -> str | None:
    return el.text.strip() if el is not None and el.text else None


def lire_musicxml(chemin: Path) -> bytes:
    with zipfile.ZipFile(chemin) as z:
        noms = z.namelist()
        racine = None
        if "META-INF/container.xml" in noms:
            c = ET.fromstring(z.read("META-INF/container.xml"))
            rf = c.find(".//{*}rootfile")
            if rf is not None:
                racine = rf.get("full-path")
        if not racine:
            racine = next(n for n in noms if n.endswith((".musicxml", ".xml")) and not n.startswith("META-INF"))
        return z.read(racine)


PAS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def analyser_mxl(chemin: Path) -> dict:
    try:
        racine = ET.fromstring(lire_musicxml(chemin))
    except Exception as e:
        return {"erreur": f"lecture: {e}"}
    res: dict = {
        "titre_lu": _texte(racine.find("work/work-title")) or _texte(racine.find("movement-title")),
        "compositeur_lu": _texte(racine.find("identification/creator[@type='composer']")),
    }
    parties = racine.findall("part")
    res["parties"] = len(parties)
    if not parties:
        return res
    p = parties[0]
    mesures = p.findall("measure")
    res["mesures"] = len(mesures)
    hauteurs = []
    for n in p.iter("note"):
        h = n.find("pitch")
        if h is None:
            continue
        alter = float(_texte(h.find("alter")) or 0)
        midi = 12 * (int(_texte(h.find("octave"))) + 1) + PAS[_texte(h.find("step"))] + int(alter)
        hauteurs.append(midi)
    res["notes"] = len(hauteurs)
    if hauteurs:
        res["ambitus"] = [min(hauteurs), max(hauteurs)]
    res["accords"] = len(p.findall(".//harmony"))
    res["reperes"] = [_texte(r) for r in p.iter("rehearsal")][:12]
    fifths = p.find(".//attributes/key/fifths")
    res["armure"] = int(_texte(fifths)) if fifths is not None else None
    t = p.find(".//attributes/time")
    if t is not None:
        res["mesure_type"] = f"{_texte(t.find('beats'))}/{_texte(t.find('beat-type'))}"
    tr = p.find(".//attributes/transpose/chromatic")
    res["transpose"] = int(_texte(tr)) if tr is not None else 0
    return res


def analyser(chemin_str: str) -> dict:
    chemin = Path(chemin_str)
    rel = chemin.relative_to(RACINE).as_posix()
    ligne = {"fichier": rel, "type": chemin.suffix.lower().lstrip("."), "octets": chemin.stat().st_size}
    ligne.update(analyser_nom(chemin.name))
    if ligne["type"] == "mxl":
        dossier = chemin.parent.name.lower()
        ligne["dossier_instrument"] = INSTRUMENTS.get(dossier, dossier)
    ligne["sha256"] = sha256(chemin)
    if ligne["type"] == "pdf":
        ligne.update(analyser_pdf(chemin))
    elif ligne["type"] == "mxl":
        ligne.update(analyser_mxl(chemin))
    return ligne


def lister() -> list[Path]:
    return sorted(
        p
        for d in ("pdf", "mxl")
        for p in (RACINE / d).rglob("*")
        if p.is_file()
    )


def resumer(lignes: list[dict], morceaux: dict) -> str:
    out = []
    c = Counter(l["type"] for l in lignes)
    out.append(f"Fichiers : {len(lignes)} ({dict(c)})")
    out.append(f"Morceaux (clé compositeur||titre) : {len(morceaux)}")
    out.append(f"Noms non conformes : {sum(not l['nom_conforme'] for l in lignes)}")
    out.append(f"Variants : {sum(l['variant'] > 0 for l in lignes)} ; suffixes (1) : {sum(l['copie'] > 0 for l in lignes)}")
    err = [l for l in lignes if "erreur" in l]
    out.append(f"Erreurs de lecture : {len(err)}")
    for l in err[:10]:
        out.append(f"  - {l['fichier']} : {l['erreur'][:100]}")
    pdfs = [l for l in lignes if l["type"] == "pdf" and "erreur" not in l]
    out.append(f"PDF scannés (sans texte) : {sum(l.get('scanne', False) for l in pdfs)}")
    out.append(f"PDF sans accord détecté : {sum(l.get('accords', 0) == 0 for l in pdfs)}")
    out.append(f"Pages PDF : {dict(sorted(Counter(l.get('pages') for l in pdfs).items()))}")
    mxls = [l for l in lignes if l["type"] == "mxl" and "erreur" not in l]
    out.append(f"MXL sans notes : {sum(not l.get('notes') for l in mxls)} ; sans accords : {sum(not l.get('accords') for l in mxls)}")
    out.append(f"MXL multi-parties : {sum(l.get('parties', 0) > 1 for l in mxls)}")
    out.append(f"MXL dossier ≠ nom : {sum(l.get('dossier_instrument') != l.get('instrument') for l in mxls)}")
    dup = Counter(l["sha256"] for l in lignes)
    groupes = [h for h, n in dup.items() if n > 1]
    out.append(f"Doublons binaires exacts : {len(groupes)} groupes, {sum(dup[h] - 1 for h in groupes)} fichiers en trop")
    sans_nom = [l["fichier"] for l in lignes if not l["nom_conforme"]]
    out.append("Exemples de noms non conformes :")
    out += [f"  - {f}" for f in sans_nom[:10]]
    # Couverture par morceau.
    couv = Counter()
    for m in morceaux.values():
        couv["mxl"] += bool(m["mxl"])
        couv["pdf_theme_c"] += "c" in m["pdf"].get("theme", {})
        couv["pdf_theme_bb"] += "bb" in m["pdf"].get("theme", {})
        couv["pdf_theme_eb"] += "eb" in m["pdf"].get("theme", {})
        couv["contraponto"] += "contraponto" in m["pdf"]
        couv["ni_mxl_ni_pdf_c"] += not m["mxl"] and "c" not in m["pdf"].get("theme", {})
    out.append(f"Couverture morceaux : {dict(couv)}")
    return "\n".join(out)


def regrouper(lignes: list[dict]) -> dict:
    morceaux: dict = defaultdict(lambda: {"noms": set(), "pdf": defaultdict(lambda: defaultdict(list)), "mxl": defaultdict(list)})
    for l in lignes:
        if "cle" not in l:
            continue
        m = morceaux[l["cle"]]
        m["noms"].add(f"{l['compositeur']} - {l['titre']}")
        if l["type"] == "pdf":
            m["pdf"][l["partie"]][l["instrument"]].append(l["fichier"])
        else:
            m["mxl"][l["instrument"]].append(l["fichier"])
    return {
        k: {"noms": sorted(v["noms"]), "pdf": {p: dict(i) for p, i in v["pdf"].items()}, "mxl": dict(v["mxl"])}
        for k, v in sorted(morceaux.items())
    }


def main() -> int:
    fichiers = lister()
    with ProcessPoolExecutor() as pool:
        lignes = list(pool.map(analyser, map(str, fichiers), chunksize=16))
    SORTIES.mkdir(exist_ok=True)
    with (SORTIES / "inventaire.jsonl").open("w", encoding="utf-8") as f:
        for l in lignes:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    morceaux = regrouper(lignes)
    (SORTIES / "morceaux.json").write_text(json.dumps(morceaux, ensure_ascii=False, indent=1), encoding="utf-8")
    resume = resumer(lignes, morceaux)
    (SORTIES / "resume-inventaire.txt").write_text(resume + "\n", encoding="utf-8")
    print(resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
