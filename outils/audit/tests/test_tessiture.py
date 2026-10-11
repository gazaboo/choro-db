from tessiture import Mesure, planifier, sections

SAX = (58, 90)


def m(num, notes, debut=False):
    return Mesure(str(num), notes, debut, num - 1)


def test_deja_dans_la_plage():
    assert planifier([m(1, [60, 72], True)], SAX)["cas"] == "ok"


def test_octave_globale():
    p = planifier([m(1, [80, 95], True), m(2, [70, 88])], SAX)
    assert p == {"cas": "global", "decalage": -12, "avant": 1, "hors_plage": 0}


def test_octave_par_section_et_reste_signale():
    # Section B trop aiguë : descendue d'une octave ; son Lab2 (56 → 44) reste hors plage.
    ms = [m(1, [60, 62], True), m(2, [64]), m(3, [93, 95], True), m(4, [91, 56])]
    p = planifier(ms, SAX)
    assert p["cas"] == "sections"
    assert p["sections"] == [
        {"mesures": ["1", "2"], "positions": [0, 1], "decalage": 0, "hors_plage": 0},
        {"mesures": ["3", "4"], "positions": [2, 3], "decalage": -12, "hors_plage": 1},
    ]
    assert p["hors_plage"] == 1


def test_sections_coupees_aux_reperes():
    ms = [m(1, [], True), m(2, []), m(3, [], True)]
    assert [len(s) for s in sections(ms)] == [2, 1]
