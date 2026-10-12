"""Grilles d'accords lues dans les PDF vectoriels, pour les morceaux sans MXL.

Les chiffrages sont du texte dans ces PDF ; les barres de mesure se lisent dans
la géométrie (module `geometrie`). Chaque accord est rangé dans la mesure dont
il surplombe l'abscisse. Les parties sont coupées sur les lettres de repère
(A, B, C… écrites dans une autre police que les accords) ; sans repère, le
morceau forme une seule partie. Reprises et fins ne sont pas détectées.

Usage :
    outils/audit/.venv/bin/python -I outils/grilles/grilles_pdf.py             # morceaux sans MXL → grilles/
    outils/audit/.venv/bin/python -I outils/grilles/grilles_pdf.py FICHIER.pdf  # un fichier, sur stdout
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "audit"))

from geometrie.measures import measures_for_page  # noqa: E402
from geometrie.vector_geometry import _segments, page_geometry  # noqa: E402
from grilles import RACINE, SORTIE, ecrire_index, empreinte, normaliser, tonique  # noqa: E402
from inventaire import SMUFL, analyser_nom, est_accord  # noqa: E402

NOTATION = [
    (r"[♯]", "#"), (r"[♭]", "b"), (r"°7", "dim7"), (r"°", "dim"), (r"ø7?", "m7b5"),
    (r"(?<![a-z])min", "m"), (r"7M|M7|maj7|Maj7|Δ", "maj7"), (r"^([A-G][#b]?)-", r"\1m"),
]
RE_REPERE = re.compile(r"^[A-H]$")


def notation(accord: str) -> str:
    for motif, rempl in NOTATION:
        accord = re.sub(motif, rempl, accord)
    return accord


def doubles_barres(page: pymupdf.Page, portees: list) -> list[list[float]]:
    """Abscisses des doubles barres (fin de partie, reprise) de chaque portée.

    Une double barre = deux traits verticaux couvrant toute la portée, à moins
    d'un interligne l'un de l'autre (mince + épais pour une barre de reprise).
    """
    _, verticales = _segments(page)
    out = []
    for st in portees:
        tol = max(st.space * 0.15, 0.5)
        xs = sorted(x for x, y0, y1 in verticales if abs(y0 - st.y_top) <= tol and abs(y1 - st.y_bottom) <= tol)
        out.append([b for a, b in zip(xs, xs[1:]) if 0.3 < b - a <= st.space * 1.2])
    return out


def lire_page(page: pymupdf.Page) -> tuple[list, list, set]:
    """(mesures, textes, fins) d'une page : boîtes de mesure, lignes de texte avec leur
    style, et indices des boîtes closes par une double barre."""
    geo = page_geometry(page)
    boites = sorted(measures_for_page(geo), key=lambda b: (b.staff_index, b.index_in_staff))
    portees = sorted(geo.staves, key=lambda s: s.y_top)
    doubles = doubles_barres(page, portees)
    fins = {
        i
        for i, b in enumerate(boites)
        if any(abs(b.x + b.w - x) <= portees[b.staff_index].space * 1.5 for x in doubles[b.staff_index])
    }
    textes = []
    for bloc in page.get_text("dict")["blocks"]:
        for ligne in bloc.get("lines", []):
            spans = ligne["spans"]
            t = "".join(sp["text"] for sp in spans).translate(SMUFL).strip()
            if spans and t:
                textes.append((ligne["bbox"], (spans[0]["font"], round(spans[0]["size"], 1)), t))
    return boites, textes, fins


def grille_pdf(chemin: Path) -> dict | None:
    doc = pymupdf.open(chemin)
    pages = [lire_page(p) for p in doc]
    styles = Counter(st for _, textes, _ in pages for _, st, t in textes if est_accord(t) and len(t) > 1)
    if not styles:
        return None
    style = styles.most_common(1)[0][0]
    mesures, reperes, coupes_barres = [], {}, set()  # reperes : indice de mesure → lettre
    for boites, textes, fins in pages:
        if not boites:
            continue
        base = len(mesures)
        cases = [[] for _ in boites]
        for bbox, st, t in textes:
            x, y = bbox[0], (bbox[1] + bbox[3]) / 2
            dedans = [i for i, b in enumerate(boites) if b.x - 2 <= x < b.x + b.w and b.y <= y <= b.y + b.h]
            if not dedans:
                continue
            i = dedans[0]
            if st == style and est_accord(t):
                cases[i].append((x, notation(t)))
            elif RE_REPERE.match(t) and st != style:
                # Lettre de repère : début de partie, sauf si elle apparaît déjà.
                if t not in reperes.values():
                    reperes[base + i] = t
        coupes_barres |= {base + i + 1 for i in fins}
        for c in cases:
            accords = []
            for _, a in sorted(c):
                if not accords or accords[-1] != a:
                    accords.append(a)
            mesures.append(accords)
    if not any(mesures):
        return None
    # Mesures vides en tête (titre, levée) : on part du premier accord.
    debut = next(i for i, m in enumerate(mesures) if m)
    coupes = sorted({debut} | {i for i in reperes if i > debut} | {i for i in coupes_barres if debut < i < len(mesures)})
    # Pas de partie de moins de 4 mesures (double barre de passage, coda) : rattachée à la précédente.
    coupes = [c for j, c in enumerate(coupes) if j == 0 or c - coupes[j - 1] >= 4 or c in reperes]
    if len(coupes) > 1 and len(mesures) - coupes[-1] < 4:
        coupes.pop()
    if len(coupes) > 6:  # trop de doubles barres : détection non fiable sur ce graveur
        coupes = sorted({debut} | {i for i in reperes if i > debut})
    parties, forme = [], []
    for j, a in enumerate(coupes):
        b = coupes[j + 1] if j + 1 < len(coupes) else len(mesures)
        seq = mesures[a:b]
        while seq and not seq[-1]:
            seq.pop()
        if not seq:
            continue
        emp = empreinte(seq)
        deja = next((p for p in parties if p["name"] != "Coda" and SequenceMatcher(None, p["_emp"], emp).ratio() >= 0.85), None)
        if deja:  # partie réécrite (A après B) : seulement dans la forme
            forme.append(deja["name"])
            continue
        derniere = j == len(coupes) - 1
        nom = "Coda" if derniere and parties and len(seq) <= 8 else "ABCDEFGHIJKL"[min(len([p for p in parties if p["name"] != "Coda"]), 11)]
        forme.append(nom)
        parties.append({"name": nom, "tonic": tonique(seq, 0, None), "bars": f"{a - debut + 1}–{a - debut + len(seq)}", "sequence": seq, "_emp": emp})
    for p in parties:
        del p["_emp"]
    n = analyser_nom(chemin.name)
    notes = [
        "Grille générée automatiquement depuis le texte du PDF : à vérifier.",
        "Reprises et fins non détectées : les mesures sont dans l'ordre d'écriture.",
    ]
    if len(parties) == 1:
        notes.append("Parties non repérées dans la partition : une seule partie.")
    return {
        "song_id": f"{normaliser(n['titre'])}-{normaliser(n['compositeur'])}",
        "title": n["titre"],
        "composer": n["compositeur"],
        "transposition": "c",
        "meter": "2/4",
        "form": " — ".join(forme),
        "parts": parties,
        "notes": notes,
        "confidence": "low",
        "source": [str(chemin.relative_to(RACINE)) if chemin.is_relative_to(RACINE) else chemin.name],
        "generated": "pdf",
    }


def choisir_pdf() -> dict[str, Path]:
    """Pour chaque morceau sans MXL : le PDF C (thème) vectoriel le plus riche en accords."""
    inv = [json.loads(l) for l in (RACINE / "outils" / "audit" / "sorties" / "inventaire.jsonl").open(encoding="utf-8")]
    avec_mxl = {l["cle"] for l in inv if l["type"] == "mxl"}
    meilleurs: dict[str, dict] = {}
    for l in inv:
        if l["type"] != "pdf" or l["cle"] in avec_mxl or l.get("scanne") or l.get("instrument") != "c":
            continue
        if not str(l.get("partie", "")).lower().startswith("th") or (l.get("accords") or 0) < 16:
            continue
        if l["cle"] not in meilleurs or l["accords"] > meilleurs[l["cle"]]["accords"]:
            meilleurs[l["cle"]] = l
    return {k: RACINE / l["fichier"] for k, l in meilleurs.items()}


def main(argv: list[str]) -> int:
    if argv:
        print(json.dumps(grille_pdf(Path(argv[0]).resolve()), ensure_ascii=False, indent=1))
        return 0
    ecrites, echecs, uniques = 0, [], 0
    for cle, chemin in sorted(choisir_pdf().items()):
        try:
            g = grille_pdf(chemin)
        except Exception as e:  # PDF mal formé : on passe
            echecs.append(f"{chemin.name} : {e}")
            continue
        if not g or sum(len(p["sequence"]) for p in g["parts"]) < 8:
            echecs.append(f"{chemin.name} : moins de 8 mesures lues")
            continue
        cible = SORTIE / f"{g['song_id']}.json"
        if cible.exists():
            continue  # une grille MXL existe déjà sous ce nom
        cible.write_text(json.dumps(g, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        ecrites += 1
        uniques += len(g["parts"]) == 1
    ecrire_index()
    print(f"{ecrites} grilles PDF écrites ({uniques} en une seule partie) ; {len(echecs)} échecs")
    for e in echecs[:15]:
        print("  ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
