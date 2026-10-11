"""Importe dans pdf/ des partitions hors MuseScore (scans, originaux vectoriels).

Chaque PDF candidat est :
- écarté s'il est déjà dans le dépôt (même contenu) ou produit par MuseScore ;
- rattaché à un morceau existant (compositeur + titre, tolérant aux graphies),
  sinon il crée un nouveau morceau ;
- étiqueté C / Bb / Eb : d'après son nom s'il le dit, sinon en comparant ses
  accords à ceux des autres versions du morceau (voir identite.py), sinon C ;
- copié sous le nom conventionnel « Compositeur - Titre - Partie - Instrument
  [- variant N].pdf ». L'application les liste tous, au choix du musicien.

Usage :
    outils/audit/.venv/bin/python -I outils/audit/importer.py SOURCES.json            # simulation
    outils/audit/.venv/bin/python -I outils/audit/importer.py SOURCES.json --appliquer
SOURCES.json : [{"dossier": "...", "forme": "compositeur-dossier" | "titre-compositeur-dossier" | "nom-conforme"}]
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf
from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from identite import DECALAGE, MIN_ACCORDS, SEUIL_ACCORDS, choisir_reference, en_concert, meilleur_decalage, versions_comparables  # noqa: E402
from inventaire import analyser_nom, analyser_pdf, normaliser  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]
SORTIES = Path(__file__).resolve().parent / "sorties"
NOM_INSTRUMENT = {"c": "C", "bb": "Clarinet Bb", "eb": "Saxophone Eb"}

RE_BB = re.compile(r"clarinet(?:te)?\s*b[b♭]|\bsib\b|\bsi\s*b\b|\bb[b♭]\b|\bclarone\b|\bclar\b", re.I)
RE_EB = re.compile(r"sax(?:ophone)?\s*(?:alto\s*)?e[b♭]|\bmib\b|\bmi\s*b\b|\be[b♭]\b|\balto\b", re.I)
RE_CONTRA = re.compile(r"contra(?:ponto|canto)", re.I)
RE_C = re.compile(r"(?:^|[\s_-])(?:c|ut)(?:$|[\s_-])", re.I)
# Le dépôt est public : aucun fichier qui puisse porter une donnée personnelle
# (filigrane d'achat, e-mail, nom d'un arrangeur/professeur dans le nom).
RE_NOM_PRIVE = re.compile(r"watermark|contre[\s_-]*chant[\s_-]*de|arrang|prof", re.I)
RE_TEXTE_PRIVE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|licen[cç]|purchased|comprad|achet|watermark|tous droits|all rights", re.I)

# Attributions corrigées d'après la partition imprimée (voir l'étape identité).
RENOMMAGES = {
    ("luiz americano", "atraente"): ("Chiquinha Gonzaga", "Atraente"),
    ("raul de barros", "gloria"): ("Pixinguinha", "Glória"),
    ("rossini ferreira", "foi um sonho"): ("Luperce Miranda", "Foi um sonho"),
    ("rossini ferreira", "labirinto"): ("Ernesto Nazareth", "Labirinto"),
    ("domingosteixeira", "bilinho"): ("Domingos Teixeira", "Polka vergonha"),
    ("domingos teixeira", "bilinho"): ("Domingos Teixeira", "Polka vergonha"),
    ("aristides oliveira", "moleque diabo"): ("Aristides Oliveira", "Não gostei dos seus modos"),
}
# Concert → écrit : demi-tons ajoutés pour chaque instrument.
DECALAGE_VERS_INSTRUMENT = {0: "c", 2: "bb", -3: "eb", 9: "eb"}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def producteur(p: Path) -> str:
    try:
        m = pymupdf.open(p).metadata or {}
    except Exception:
        return "illisible"
    return f"{m.get('creator', '')} | {m.get('producer', '')}".lower()


def instrument_du_nom(nom: str) -> str | None:
    nom = nom.replace("_", " ")
    trouves = {i for i, r in (("bb", RE_BB), ("eb", RE_EB), ("c", RE_C)) if r.search(nom)}
    if len(trouves) > 1:
        return "c"  # PDF multi-instruments (C, Bb, Eb… à la suite) : on l'étiquette C
    return trouves.pop() if trouves else None


def donnee_privee(p: Path) -> str | None:
    """Raison d'écarter le fichier s'il peut contenir une donnée personnelle."""
    if RE_NOM_PRIVE.search(p.stem):
        return "nom de fichier"
    try:
        texte = " ".join(page.get_text() for page in pymupdf.open(p))
    except Exception:
        return "illisible"
    m = RE_TEXTE_PRIVE.search(texte)
    return f"texte : {m.group(0)[:30]}" if m else None


def candidats(source: dict) -> list[dict]:
    """(chemin, compositeur, titre, indice d'instrument, partie) pour chaque PDF de la source."""
    dossier = Path(source["dossier"])
    out = []
    for p in sorted(dossier.rglob("*")):
        if p.suffix.lower() != ".pdf" or ".ipynb_checkpoints" in p.parts:
            continue
        forme = source["forme"]
        if forme == "nom-conforme":
            n = analyser_nom(p.name)
            if not n.get("nom_conforme"):
                continue
            comp, titre, inst = n["compositeur"], n["titre"], n["instrument"]
            partie = n["partie"]
        else:
            champs = [c.strip() for c in p.stem.split(" - ")]
            if forme == "compositeur-dossier":  # <Compositeur>/[sous-dossier/]<Titre>[ - précision] - <Compositeur>.pdf
                comp, titre = p.relative_to(dossier).parts[0], champs[0]
            else:  # <Titre - Compositeur>/<fichier>.pdf
                titre, _, comp = p.parent.name.rpartition(" - ")
            inst = instrument_du_nom(p.stem)
            partie = "contraponto" if RE_CONTRA.search(p.stem) else "theme"
        comp, titre = RENOMMAGES.get((normaliser(comp), normaliser(titre)), (comp, titre))
        out.append({"source": str(p), "compositeur": comp, "titre": titre, "instrument": inst, "partie": partie})
    return out


class Morceaux:
    """Morceaux existants de choro-db, avec leur nom canonique et leurs versions comparables."""

    def __init__(self, inventaire: list[dict]):
        self.noms: dict[str, Counter] = defaultdict(Counter)
        self.versions: dict[str, list[dict]] = defaultdict(list)
        comparables = {id(l) for l in versions_comparables(inventaire)}
        for l in inventaire:
            if "cle" not in l:
                continue
            self.noms[l["cle"]][(l["compositeur"], l["titre"])] += 1
            if id(l) in comparables:
                self.versions[l["cle"]].append(l)
        self.par_compositeur: dict[str, list[str]] = defaultdict(list)
        for cle in self.noms:
            self.par_compositeur[cle.split("||")[0]].append(cle)

    def canonique(self, cle: str) -> tuple[str, str]:
        return self.noms[cle].most_common(1)[0][0]

    def trouver(self, compositeur: str, titre: str) -> tuple[str | None, int]:
        c, t = normaliser(compositeur), normaliser(titre)
        if f"{c}||{t}" in self.noms:
            return f"{c}||{t}", 100
        meilleur, score = None, 0
        for cle, (cc, tt) in ((k, k.split("||")) for k in self.noms):
            sc_c = fuzz.token_set_ratio(c, cc)
            if sc_c < 80:
                continue
            sc_t = fuzz.ratio(t, tt)
            if sc_t > score:
                meilleur, score = cle, sc_t
        return (meilleur, score) if score >= 90 else (None, score)

    def concert_reference(self, cle: str) -> list[int] | None:
        vs = self.versions.get(cle)
        if not vs:
            return None
        ref = choisir_reference(vs)
        return en_concert(ref["racines"], ref["instrument"])


def instrument_par_accords(racines: list[int], reference: list[int] | None) -> tuple[str | None, str]:
    """Instrument déduit en comparant les fondamentales du PDF à la référence en concert."""
    if reference is None or len(racines) < MIN_ACCORDS:
        return None, "pas de référence ou d'accords lisibles"
    s, score = meilleur_decalage(reference, racines)  # s : à ajouter au PDF pour retrouver le concert
    if score < SEUIL_ACCORDS:
        return None, f"accords trop différents ({score:.2f})"
    ecrit = (-s) % 12
    for d, inst in DECALAGE_VERS_INSTRUMENT.items():
        if d % 12 == ecrit:
            return inst, f"accords ({score:.2f})"
    return "c", f"autre tonalité que la référence (+{ecrit}), étiqueté C"


def nom_libre(base: str, pris: set[str]) -> str:
    nom, n = f"{base}.pdf", 0
    while nom.lower() in pris:
        n += 1
        nom = f"{base} - variant {n}.pdf"
    pris.add(nom.lower())
    return nom


def planifier(sources: list[dict]) -> list[dict]:
    inventaire = [json.loads(l) for l in (SORTIES / "inventaire.jsonl").open(encoding="utf-8")]
    morceaux = Morceaux(inventaire)
    connus = {l["sha256"] for l in inventaire}
    connus |= {sha256(p) for p in (RACINE / "archives").rglob("*.pdf")}
    pris = {p.name.lower() for p in (RACINE / "pdf").glob("*.pdf")}
    plan = []
    for source in sources:
        for c in candidats(source):
            chemin = Path(c["source"])
            h = sha256(chemin)
            if h in connus:
                plan.append({**c, "decision": "déjà présent"})
                continue
            if "musescore" in producteur(chemin):
                plan.append({**c, "decision": "MuseScore, écarté"})
                continue
            prive = donnee_privee(chemin)
            if prive:
                plan.append({**c, "decision": "écarté (donnée personnelle possible)", "raison": prive})
                continue
            connus.add(h)
            cle, score = morceaux.trouver(c["compositeur"], c["titre"])
            infos = analyser_pdf(chemin)
            inst, pourquoi = c["instrument"], "nom du fichier"
            if inst is None:
                inst, pourquoi = instrument_par_accords(infos.get("racines", []), morceaux.concert_reference(cle) if cle else None)
            if inst is None:
                inst, pourquoi = "c", f"par défaut ({pourquoi})"
            comp, titre = morceaux.canonique(cle) if cle else (c["compositeur"].strip(), c["titre"].strip())
            partie = "Contraponto" if c["partie"] == "contraponto" else "Theme"
            nom = nom_libre(f"{comp} - {titre} - {partie} - {NOM_INSTRUMENT[inst]}", pris)
            plan.append(
                {
                    **c,
                    "decision": "importé",
                    "morceau": cle or "nouveau",
                    "score_titre": score,
                    "instrument_final": inst,
                    "instrument_pourquoi": pourquoi,
                    "scanne": infos.get("scanne"),
                    "cible": f"pdf/{nom}",
                }
            )
    return plan


def main(argv: list[str]) -> int:
    sources = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    plan = planifier(sources)
    (SORTIES / "import.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    imp = [p for p in plan if p["decision"] == "importé"]
    print(f"Candidats : {len(plan)} — {dict(Counter(p['decision'] for p in plan))}")
    print(f"Importés : rattachés à un morceau existant {sum(p['morceau'] != 'nouveau' for p in imp)}, "
          f"nouveaux morceaux {len({(p['compositeur'], p['titre']) for p in imp if p['morceau'] == 'nouveau'})}")
    print(f"Instrument : {dict(Counter(p['instrument_final'] for p in imp))}")
    print(f"  d'où : {dict(Counter(p['instrument_pourquoi'].split(' (')[0] for p in imp))}")
    print(f"Scans : {sum(bool(p['scanne']) for p in imp)} ; parties : {dict(Counter(p['cible'].split(' - ')[-2] if 'variant' not in p['cible'] else p['cible'].split(' - ')[-3] for p in imp))}")
    for p in [p for p in plan if p["decision"].startswith("écarté (donnée")]:
        print(f"   écarté : {Path(p['source']).name[:60]} — {p['raison']}")
    proches = [p for p in imp if p["morceau"] == "nouveau" and 80 <= p["score_titre"] < 90]
    print(f"Nouveaux morceaux au titre proche d'un existant (à vérifier) : {len(proches)}")
    for p in proches[:10]:
        print(f"   {p['compositeur']} - {p['titre']}")
    if "--appliquer" in argv:
        for p in imp:
            shutil.copy2(p["source"], RACINE / p["cible"])
        print(f"{len(imp)} PDF copiés dans pdf/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
