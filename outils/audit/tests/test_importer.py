import pytest

from importer import instrument_du_nom, nom_libre


@pytest.mark.parametrize(
    "nom, attendu",
    [
        ("Jacob do Bandolim - Feitiço - Clarinet Bb", "bb"),
        ("Bionne-clarone", "bb"),
        ("Pixinguinha Diplomata sib (1)", "bb"),
        ("Zequinha de Abreu - Nao me toques - Saxophone Eb", "eb"),
        ("Feitico_C_Bb_Eb_Fa", "c"),
        ("Proezas de Solon C Bb Eb", "c"),
        ("Um a Zero ut - Pixinguinha - choro duetos", "c"),
        ("Abigail - Candinho", None),
    ],
)
def test_instrument_du_nom(nom, attendu):
    assert instrument_du_nom(nom) == attendu


def test_nom_libre_ajoute_variant():
    pris = {"a - t - theme - c.pdf"}
    assert nom_libre("A - T - Theme - C", pris) == "A - T - Theme - C - variant 1.pdf"
    assert nom_libre("A - T - Theme - C", pris) == "A - T - Theme - C - variant 2.pdf"
