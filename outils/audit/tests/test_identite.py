from identite import comparer, en_concert, meilleur_decalage

SUITE = [0, 0, 5, 7, 0, 9, 2, 7, 0, 4, 9, 2, 7, 0]


def test_meme_suite_ok():
    assert comparer(SUITE, list(SUITE))["verdict"] == "ok"


def test_versions_transposees_ramenees_en_concert():
    bb = [(r + 2) % 12 for r in SUITE]
    eb = [(r + 9) % 12 for r in SUITE]
    assert en_concert(bb, "bb") == SUITE and en_concert(eb, "eb") == SUITE


def test_version_mal_etiquetee_detectee_par_decalage():
    # Une « C » qui est en réalité écrite pour Sib : un ton au-dessus.
    fausse_c = [(r + 2) % 12 for r in SUITE]
    r = comparer(SUITE, fausse_c)
    assert r["verdict"] == "decalee" and r["decalage"] == -2


def test_autre_morceau_different():
    autre = [4, 11, 4, 6, 11, 1, 8, 3, 3, 10, 6, 1, 1, 8]
    assert comparer(SUITE, autre)["verdict"] == "differente"


def test_meilleur_decalage():
    assert meilleur_decalage(SUITE, [(r - 5) % 12 for r in SUITE]) == (5, 1.0)


def test_reference_majoritaire_plutot_que_mxl_c_isole():
    from identite import choisir_reference

    def v(fichier, type_, inst, racines):
        return {"fichier": fichier, "type": type_, "instrument": inst, "variant": 0, "racines": racines}

    haut = [(r + 2) % 12 for r in SUITE]  # tout le monde, sauf le MXL C, est un ton plus haut
    versions = [
        v("mxl/C/x.mxl", "mxl", "c", SUITE),
        v("mxl/Bb/x.mxl", "mxl", "bb", [(r + 2) % 12 for r in haut]),
        v("pdf/x - C.pdf", "pdf", "c", haut),
        v("pdf/x - Bb.pdf", "pdf", "bb", [(r + 2) % 12 for r in haut]),
    ]
    assert choisir_reference(versions)["fichier"] == "mxl/Bb/x.mxl"
