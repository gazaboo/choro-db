"""Moteur de détection principal : géométrie vectorielle via PyMuPDF.

Les PDF du corpus sont tous des gravures natives (MuseScore, Finale, PScript).
On lit donc directement les traits du document plutôt que de deviner sur une
image rastérisée. Deux signaux complémentaires donnent les barres de mesure :

1. **La segmentation des lignes de portée.** MuseScore interrompt ses cinq
   lignes à chaque barre : les extrémités des segments *sont* les frontières
   de mesure, au point près.
2. **Les traits verticaux.** Finale et les exports PostScript tracent des
   lignes de portée continues ; on retombe alors sur la détection des barres
   proprement dites, reconnues au fait qu'elles épousent exactement la hauteur
   de la portée — ce qui écarte les hampes de notes.
"""

from __future__ import annotations

import pymupdf

from .measures import PageGeometry, build_levels, group_staves

# --- Seuils géométriques (en points PDF) -----------------------------------
MAX_LINE_THICKNESS = 3.0  # au-delà, ce n'est plus une ligne de portée
MAX_BARLINE_THICKNESS = 6.0  # les barres épaisses (fin, reprise) restent fines
LEVEL_TOLERANCE = 0.4  # deux traits à moins de ça sont sur le même niveau y
# Écart toléré entre les extrémités d'une barre et les lignes extrêmes de la
# portée. Volontairement serré : sur le corpus, une vraie barre tombe à moins
# de 0.15 pt des deux lignes, tandis que la hampe la plus proche en est déjà à
# 0.5 pt. C'est ce qui les sépare proprement.
BARLINE_END_TOLERANCE = 0.05  # en interlignes
BARLINE_END_FLOOR = 0.25  # en points, plancher absolu


def _segments(
    page: pymupdf.Page,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Extrait les segments horizontaux et verticaux axis-aligned.

    Retourne (horizontaux, verticaux) où un horizontal est (y, x_start, x_end)
    et un vertical (x, y_start, y_end).
    """
    horizontals: list[tuple[float, float, float]] = []
    verticals: list[tuple[float, float, float]] = []

    def add_line(x0: float, y0: float, x1: float, y1: float, thickness: float) -> None:
        if abs(y1 - y0) <= LEVEL_TOLERANCE and abs(x1 - x0) > 0:
            if thickness <= MAX_LINE_THICKNESS:
                horizontals.append(((y0 + y1) / 2.0, min(x0, x1), max(x0, x1)))
        elif abs(x1 - x0) <= LEVEL_TOLERANCE and abs(y1 - y0) > 0:
            if thickness <= MAX_BARLINE_THICKNESS:
                verticals.append(((x0 + x1) / 2.0, min(y0, y1), max(y0, y1)))

    def add_rect(rect: pymupdf.Rect) -> None:
        if rect.height <= MAX_LINE_THICKNESS and rect.width > rect.height:
            horizontals.append(((rect.y0 + rect.y1) / 2.0, rect.x0, rect.x1))
        elif rect.width <= MAX_BARLINE_THICKNESS and rect.height > rect.width:
            verticals.append(((rect.x0 + rect.x1) / 2.0, rect.y0, rect.y1))

    for path in page.get_drawings():
        width = path.get("width") or 0.0
        for item in path["items"]:
            kind = item[0]
            if kind == "l":
                p0, p1 = item[1], item[2]
                add_line(p0.x, p0.y, p1.x, p1.y, width)
            elif kind == "re":
                add_rect(item[1])
            elif kind == "qu":
                add_rect(item[1].rect)
            # 'c' (courbes de Bézier) : liaisons, crochets -> ignorées.

    return horizontals, verticals


def _barline_boundaries(staff, verticals: list[tuple]) -> list[float]:
    """Frontières déduites des traits verticaux (cas Finale / PostScript).

    Une barre de mesure épouse exactement la hauteur de portée : ses deux
    extrémités coïncident avec la première et la cinquième ligne. Une hampe de
    note, même longue, rate au moins une des deux bornes — c'est ce test à
    deux extrémités qui les élimine, là où une simple morphologie verticale
    les confondrait.
    """
    tol = max(staff.space * BARLINE_END_TOLERANCE, BARLINE_END_FLOOR)
    return [
        x
        for x, y0, y1 in verticals
        if abs(y0 - staff.y_top) <= tol and abs(y1 - staff.y_bottom) <= tol
    ]


def page_geometry(page: pymupdf.Page) -> PageGeometry:
    """Détecte portées et barres de mesure sur une page vectorielle."""
    width, height = page.rect.width, page.rect.height
    horizontals, verticals = _segments(page)
    levels = build_levels(horizontals, width, LEVEL_TOLERANCE)
    staves = group_staves(levels)

    for staff in staves:
        # Les deux signaux ne se cumulent pas : quand le graveur segmente ses
        # lignes (MuseScore), les coupures sont exactes et exhaustives, alors
        # que la détection de traits verticaux ramasserait au passage les
        # hampes qui traversent fortuitement toute la portée. On ne sollicite
        # donc les verticales que si la segmentation n'a rien donné.
        found = staff.barlines or _barline_boundaries(staff, verticals)
        staff.barlines = sorted(x for x in found if staff.x_left < x < staff.x_right)

    return PageGeometry(width=width, height=height, staves=staves, source="vector")
