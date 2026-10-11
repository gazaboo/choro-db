import pytest
from xml.etree import ElementTree as ET

from transposer import delta_quintes, transposer_note, transposer_racine


@pytest.mark.parametrize(
    "note, pas, dt, attendu",
    [
        (("D", 0, 5), -4, -7, ("G", 0, 4)),   # Ré5 → Sol4 (quinte descendante)
        (("F", 1, 5), -4, -7, ("B", 0, 4)),   # Fa#5 → Si4
        (("B", -1, 4), -4, -7, ("E", -1, 4)),  # Sib4 → Mib4
        (("C", 0, 4), 1, 2, ("D", 0, 4)),     # seconde majeure
        (("E", 0, 5), -7, -12, ("E", 0, 4)),  # octave
    ],
)
def test_transposer_note(note, pas, dt, attendu):
    assert transposer_note(*note, pas, dt) == attendu


def test_delta_quintes():
    assert delta_quintes(-7) == -1 and delta_quintes(2) == 2 and delta_quintes(-12) == 0


XML = """<score-partwise><part id="P1">
<measure number="1"><attributes><key><fifths>-1</fifths></key><transpose><chromatic>-7</chromatic></transpose></attributes>
<harmony><root><root-step>A</root-step></root><kind>dominant</kind><bass><bass-step>C</bass-step><bass-alter>1</bass-alter></bass></harmony>
<note><pitch><step>C</step><alter>1</alter><octave>5</octave></pitch><accidental>sharp</accidental></note></measure>
<measure number="2"><note><pitch><step>D</step><octave>5</octave></pitch></note></measure>
</part></score-partwise>"""


def test_transposer_racine_quinte():
    r = ET.fromstring(XML)
    transposer_racine(r, -4, -7)
    assert r.findtext(".//fifths") == "-2"
    assert r.find(".//transpose") is None and r.find(".//accidental") is None
    assert (r.findtext(".//root-step"), r.findtext(".//bass-step"), r.findtext(".//bass-alter")) == ("D", "F", "1")
    notes = [(p.findtext("step"), p.findtext("alter"), p.findtext("octave")) for p in r.iter("pitch")]
    assert notes == [("F", "1", "4"), ("G", None, "4")]


def test_octave_partielle():
    r = ET.fromstring(XML)
    transposer_racine(r, -7, -12, mesures=(1, 1))  # 2e mesure
    assert [p.findtext("octave") for p in r.iter("pitch")] == ["5", "4"]
    assert r.findtext(".//fifths") == "-1"  # armure inchangée


@pytest.mark.parametrize(
    "accord, attendu",
    [
        (("B", 0, "E", -1), ("D", 1)),   # B/E♭ → B/D♯
        (("F", 1, "B", -1), ("A", 1)),   # F♯/B♭ → F♯/A♯
        (("C", 1, "F", 0), ("E", 1)),    # C♯/F → C♯/E♯
        (("G", 1, "C", 0), ("B", 1)),    # G♯/C → G♯/B♯
        (("D", 0, "F", 1), ("F", 1)),    # D/F♯ déjà juste
        (("C", 0, "B", -1), ("B", -1)),  # C/B♭ déjà juste
    ],
)
def test_orthographier_basse(accord, attendu):
    from transposer import orthographier_basse

    assert orthographier_basse(*accord) == attendu
