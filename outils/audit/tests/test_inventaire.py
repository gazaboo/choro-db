import zipfile

import pytest

from inventaire import analyser_mxl, analyser_nom, est_accord, normaliser


@pytest.mark.parametrize(
    "nom, attendu",
    [
        ("Pixinguinha - Cheguei - Theme - C.pdf", ("Pixinguinha", "Cheguei", "theme", "c", 0, 0)),
        ("Candinho - Curitibana - Theme - Clarinet Bb.pdf", ("Candinho", "Curitibana", "theme", "bb", 0, 0)),
        (
            "Rossini Ferreira - Cinema mudo - Theme - Saxophone Eb - variant 1.pdf",
            ("Rossini Ferreira", "Cinema mudo", "theme", "eb", 1, 0),
        ),
        ("João Lyra - Alumiando - Theme - Bb.mxl", ("João Lyra", "Alumiando", "theme", "bb", 0, 0)),
        ("X - Y - Contracanto - Saxophone Eb.mxl", ("X", "Y", "contraponto", "eb", 0, 0)),
        ("X - Y - Theme - C(1).pdf", ("X", "Y", "theme", "c", 0, 1)),
    ],
)
def test_analyser_nom(nom, attendu):
    r = analyser_nom(nom)
    assert r["nom_conforme"]
    assert (r["compositeur"], r["titre"], r["partie"], r["instrument"], r["variant"], r["copie"]) == attendu


def test_nom_non_conforme():
    r = analyser_nom("Já te digo -  Pixinguinha - pdf.pdf")
    assert not r["nom_conforme"]


def test_normaliser_ignore_accents_et_casse():
    assert normaliser("Lágrimas de  Virgem") == normaliser("lagrimas de virgem")


@pytest.mark.parametrize("s", ["C", "F♯7", "G♯dim", "Bbm7(b5)", "C/E", "Ebdim", "D7(b9)", "Am6"])
def test_est_accord(s):
    assert est_accord(s)


@pytest.mark.parametrize("s", ["Bambino", "Theme", "Choro", "11", "Allegro"])
def test_pas_accord(s):
    assert not est_accord(s)


XML = """<?xml version="1.0"?>
<score-partwise><work><work-title>Essai</work-title></work>
<identification><creator type="composer">Quelqu'un</creator></identification>
<part id="P1">
<measure number="1"><attributes><key><fifths>-1</fifths></key><time><beats>2</beats><beat-type>4</beat-type></time>
<transpose><chromatic>-2</chromatic></transpose></attributes>
<harmony><root><root-step>F</root-step></root><kind>major</kind></harmony>
<note><pitch><step>E</step><octave>3</octave></pitch></note>
<note><pitch><step>C</step><alter>1</alter><octave>6</octave></pitch></note>
<note><rest/></note></measure>
<measure number="2"><direction><direction-type><rehearsal>B</rehearsal></direction-type></direction></measure>
</part></score-partwise>"""


def test_analyser_mxl(tmp_path):
    f = tmp_path / "essai.mxl"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("META-INF/container.xml",
                   '<container><rootfiles><rootfile full-path="essai.musicxml"/></rootfiles></container>')
        z.writestr("essai.musicxml", XML)
    r = analyser_mxl(f)
    assert r["titre_lu"] == "Essai" and r["compositeur_lu"] == "Quelqu'un"
    assert r["mesures"] == 2 and r["notes"] == 2 and r["accords"] == 1
    assert r["ambitus"] == [52, 85]  # Mi3, Do#6
    assert r["armure"] == -1 and r["mesure_type"] == "2/4" and r["transpose"] == -2
    assert r["reperes"] == ["B"]


def test_ordre_de_lecture():
    from inventaire import ordre_de_lecture

    els = [((50, 102, 0, 0), "D7"), ((10, 300, 0, 0), "G"), ((10, 100, 0, 0), "C"), ((90, 98, 0, 0), "Am")]
    assert [e[1] for e in ordre_de_lecture(els)] == ["C", "D7", "Am", "G"]


def test_accords_du_style_dominant_ignore_les_reperes():
    from inventaire import accords_du_style_dominant

    accord, repere = ("Edwin", 12.0), ("Edwin-Bold", 14.0)
    cand = [(repere, "A"), (accord, "C"), (accord, "G7"), (accord, "Am"), (repere, "B"), (accord, "F")]
    assert accords_du_style_dominant(cand) == ["C", "G7", "Am", "F"]
