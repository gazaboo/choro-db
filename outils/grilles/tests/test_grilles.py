import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "audit"))

from grilles import accord, cellules_de, lire, segmenter, simplifier, tonique  # noqa: E402
from grilles_pdf import notation  # noqa: E402


def harmonie(step, kind, alter=0, bass=None, degres=()):
    x = f"<harmony><root><root-step>{step}</root-step>"
    x += f"<root-alter>{alter}</root-alter>" if alter else ""
    x += f"</root><kind>{kind}</kind>"
    if bass:
        x += f"<bass><bass-step>{bass[0]}</bass-step>" + (f"<bass-alter>{bass[1]}</bass-alter>" if bass[1] else "") + "</bass>"
    for typ, val, alt in degres:
        x += f"<degree><degree-value>{val}</degree-value><degree-alter>{alt}</degree-alter><degree-type>{typ}</degree-type></degree>"
    return ET.fromstring(x + "</harmony>")


def test_accords_dans_la_notation_des_grilles():
    assert accord(harmonie("A", "dominant", bass=("C", 1))) == "A7/C#"
    assert accord(harmonie("E", "minor-seventh", degres=[("alter", 5, -1)])) == "Em7b5"
    assert accord(harmonie("E", "diminished", alter=-1)) == "Ebdim"
    assert accord(harmonie("G", "major-minor")) == "Gm(maj7)"
    assert accord(harmonie("D", "dominant", degres=[("add", 9, -1)])) == "D7(b9)"
    assert accord(harmonie("F", "major-seventh")) == "Fmaj7"
    assert accord(harmonie("B", "minor-sixth", alter=-1)) == "Bbm6"


def test_simplification_identique_a_l_application():
    assert [simplifier(a) for a in ("A7/C#", "Gm6", "Dmaj7", "F#dim", "Em7b5", "E7(b9)", "Cm(maj7)")] == [
        "A7", "Gm", "D", "F#dim", "Em7b5", "E7", "Cm",
    ]


def mesure(n, accords=(), gauche="", droite="", fin=None):
    x = f'<measure number="{n}">'
    if gauche:
        x += f'<barline location="left"><bar-style>heavy-light</bar-style><repeat direction="forward"/></barline>'
    for a in accords:
        x += f"<harmony><root><root-step>{a[0]}</root-step></root><kind>{'minor' if 'm' in a else 'major'}</kind></harmony>"
        x += "<note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration></note>"
    if fin:
        x += f'<barline location="left"><ending number="{fin[0]}" type="start"/></barline>'
    if droite or (fin and fin[1]):
        x += '<barline location="right">'
        x += "<bar-style>light-heavy</bar-style>" if droite else ""
        x += '<repeat direction="backward"/>' if droite == "reprise" else ""
        x += f'<ending number="{fin[0]}" type="stop"/>' if fin and fin[1] else ""
        x += "</barline>"
    return x + "</measure>"


def partition(*mesures):
    return ET.fromstring(f'<score-partwise><part id="P1">{"".join(mesures)}</part></score-partwise>')


def test_parties_coupees_aux_reprises_et_fins_rangees_dans_leur_partie():
    r = partition(
        mesure(1, ["C"], gauche=True), mesure(2, ["G"]), mesure(3, ["G"]),
        mesure(4, ["C"], droite="reprise", fin=("1", True)),
        mesure(5, ["C"], droite="double", fin=("2", True)),
        mesure(6, ["Am"]), mesure(7, ["E"]), mesure(8, ["Am"], droite="double"),
    )
    segments = segmenter(lire(r))
    assert [[m.numero for m in s] for s in segments] == [["1", "2", "3", "4", "5"], ["6", "7", "8"]]
    seq, fins = cellules_de(segments[0])
    assert seq == [["C"], ["G"], ["G"]]
    assert fins == {"1": [["C"]], "2": [["C"]]}


def test_tonique_par_armure_et_accord_final():
    assert tonique([["Am"], ["E7"], ["Am"]], 0, None) == "Am"
    assert tonique([["C"], ["G7"]], 0, None) == "C"  # finit sur la dominante : tonique en dessous
    assert tonique([["Dm"], ["A7"], ["Dm"]], -1, None) == "Dm"


def test_notation_des_pdf():
    assert notation("F♯°") == "F#dim"
    assert notation("B♭7M") == "Bbmaj7"
    assert notation("Eø") == "Em7b5"
    assert notation("A-7") == "Am7"


def test_diminue_encore_et_chiffrage_colle():
    assert notation("G#o") == "G#dim"
    assert notation("Co7/E") == "Cdim7/E"


def test_corroboration_tolere_le_diminue_perdu_a_l_export():
    from croiser import souple

    assert souple("G#dim|C7") == "G#|C7"
    assert souple("Em7b5") == "Em7b5"


def test_un_pdf_musescore_ne_corrobore_pas_une_grille_mxl():
    from croiser import independant

    graveurs = {"pdf/a.pdf": "musescore", "pdf/b.pdf": "pscript", "pdf/c.pdf": "pscript"}
    mxl = {"generated": "mxl", "source": ["mxl/C/x.mxl"]}
    pdf = {"generated": "pdf", "source": ["pdf/b.pdf"]}
    assert not independant("pdf/a.pdf", mxl, graveurs)
    assert independant("pdf/b.pdf", mxl, graveurs)
    assert not independant("pdf/c.pdf", pdf, graveurs)  # même logiciel que la source
    assert independant("pdf/a.pdf", pdf, graveurs)
