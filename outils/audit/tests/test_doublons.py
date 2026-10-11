from doublons import plan_suppression


def ligne(fichier, sha, conforme=True, variant=0, copie=0):
    return {"fichier": fichier, "sha256": sha, "nom_conforme": conforme, "variant": variant, "copie": copie}


def test_garde_le_fichier_sans_variant():
    plan = plan_suppression([
        ligne("pdf/A - T - Theme - C - variant 1.pdf", "x", variant=1),
        ligne("pdf/A - T - Theme - C.pdf", "x"),
        ligne("pdf/A - U - Theme - C.pdf", "y"),
    ])
    assert plan == [{"sha256": "x", "garde": "pdf/A - T - Theme - C.pdf",
                     "retire": ["pdf/A - T - Theme - C - variant 1.pdf"]}]


def test_nom_conforme_prioritaire_puis_sans_copie():
    plan = plan_suppression([
        ligne("pdf/T -  A - pdf.pdf", "x", conforme=False),
        ligne("pdf/A - T - Theme - C(1).pdf", "x", copie=1),
        ligne("pdf/A - T - Theme - C.pdf", "x"),
    ])
    assert plan[0]["garde"] == "pdf/A - T - Theme - C.pdf"
    assert sorted(plan[0]["retire"]) == ["pdf/A - T - Theme - C(1).pdf", "pdf/T -  A - pdf.pdf"]
