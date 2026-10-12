"""Assemblage des portées et calcul des bounding boxes de mesures.

Ce module est agnostique de la provenance des traits : les deux moteurs de
détection (`vector_geometry` sur la géométrie PDF, `raster_geometry` sur une
image OpenCV) lui fournissent des niveaux horizontaux, et il en tire les
portées puis les boîtes composites « accords + portée » normalisées 0.0–1.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Assemblage des portées ------------------------------------------------
MIN_STAFF_COVERAGE = 0.25  # part de la largeur de page couverte par une ligne
MIN_CONTIGUITY = 0.80  # couverture / étendue : une ligne de portée est continue
SPACING_TOLERANCE = 0.15  # écart relatif toléré entre interlignes
X_EXTENT_TOLERANCE = 0.20  # écart relatif toléré entre étendues x des 5 lignes
ENDPOINT_CONSENSUS = 3  # nb de lignes sur 5 devant partager une coupure

# --- Boîtes de mesure ------------------------------------------------------
# Padding vertical exprimé en multiples de la hauteur de portée.
PAD_TOP_RATIO = 1.4  # englobe la grille d'accords chiffrés au-dessus
PAD_BOTTOM_RATIO = 1.4  # englobe lignes supplémentaires basses et nuances
# Une mesure plus étroite que ceci (en interlignes) est un artefact.
MIN_MEASURE_SPACES = 2.0


@dataclass
class Staff:
    """Une portée de 5 lignes, avec les abscisses de ses barres de mesure."""

    x_left: float
    x_right: float
    y_top: float
    y_bottom: float
    barlines: list[float] = field(default_factory=list)

    @property
    def height(self) -> float:
        return self.y_bottom - self.y_top

    @property
    def space(self) -> float:
        """Interligne (la portée compte 4 interlignes entre ses 5 lignes)."""
        return self.height / 4.0


@dataclass
class PageGeometry:
    width: float
    height: float
    staves: list[Staff]
    source: str  # "vector" ou "raster"


@dataclass
class MeasureBox:
    """Boîte d'une mesure, en coordonnées absolues de la page."""

    x: float
    y: float
    w: float
    h: float
    staff_index: int
    index_in_staff: int
    is_last_of_staff: bool


# ---------------------------------------------------------------------------
# Niveaux horizontaux -> portées
# ---------------------------------------------------------------------------


def merge_intervals(
    intervals: list[tuple[float, float]], gap: float = 0.5
) -> list[tuple[float, float]]:
    """Fusionne les intervalles qui se touchent ou se recouvrent."""
    if not intervals:
        return []
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start - merged[-1][1] <= gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


class Level:
    """Un niveau y candidat au rôle de ligne de portée.

    On conserve deux vues des segments : `raw_spans` garde les coupures telles
    que le graveur les a tracées (c'est le signal des barres de mesure chez
    MuseScore), tandis que `spans` les fusionne pour mesurer la couverture
    réelle de la ligne.
    """

    __slots__ = ("y", "raw_spans", "spans")

    def __init__(self, y: float, raw_spans: list[tuple[float, float]]):
        self.y = y
        self.raw_spans = sorted(raw_spans)
        self.spans = merge_intervals(self.raw_spans)

    @property
    def x_left(self) -> float:
        return self.spans[0][0]

    @property
    def x_right(self) -> float:
        return self.spans[-1][1]

    @property
    def coverage(self) -> float:
        return sum(b - a for a, b in self.spans)

    def interior_endpoints(self, tol: float) -> list[float]:
        """Coupures internes de la ligne, dédoublonnées.

        Les segments contigus de MuseScore se touchent : la fin d'un segment
        et le début du suivant désignent la même barre et ne doivent compter
        qu'une fois.
        """
        left, right = self.x_left, self.x_right
        points = sorted(
            x for span in self.raw_spans for x in span if left + tol < x < right - tol
        )
        deduped: list[float] = []
        for x in points:
            if not deduped or x - deduped[-1] > tol:
                deduped.append(x)
        return deduped


def build_levels(
    horizontals: list[tuple[float, float, float]],
    page_width: float,
    level_tolerance: float,
) -> list[Level]:
    """Regroupe des segments (y, x0, x1) par ordonnée, puis écarte les parasites.

    Deux filtres successifs. La **couverture** élimine les traits courts
    (lignes supplémentaires, hampes horizontales). La **contiguïté**
    (couverture / étendue) élimine les alignements fortuits : les arêtes de
    barres de croches d'un même passage se retrouvent à la même ordonnée et
    couvrent ensemble une bonne part de la largeur, mais en laissant des trous
    — là où une ligne de portée est continue d'un bout à l'autre.
    """
    if not horizontals:
        return []

    buckets: list[tuple[float, list[tuple[float, float]]]] = []
    for y, x0, x1 in sorted(horizontals, key=lambda s: s[0]):
        if buckets and y - buckets[-1][0] <= level_tolerance:
            buckets[-1][1].append((x0, x1))
        else:
            buckets.append((y, [(x0, x1)]))

    min_coverage = page_width * MIN_STAFF_COVERAGE
    levels = []
    for y, spans in buckets:
        level = Level(y, spans)
        extent = level.x_right - level.x_left
        if level.coverage < min_coverage or extent <= 0:
            continue
        if level.coverage / extent < MIN_CONTIGUITY:
            continue
        levels.append(level)
    return levels


def group_staves(levels: list[Level]) -> list[Staff]:
    """Assemble les niveaux en portées de 5 lignes régulièrement espacées.

    Le balayage est glouton : une fenêtre valide consomme ses 5 niveaux, sinon
    on avance d'un cran. Cela ignore proprement les traits parasites de même
    longueur (crochets de reprise, lignes d'ottava) intercalés entre systèmes.
    """
    staves: list[Staff] = []
    i = 0
    while i + 4 < len(levels):
        window = levels[i : i + 5]
        gaps = [window[k + 1].y - window[k].y for k in range(4)]
        mean_gap = sum(gaps) / 4.0
        if mean_gap <= 0:
            i += 1
            continue
        regular = all(abs(g - mean_gap) <= mean_gap * SPACING_TOLERANCE for g in gaps)

        x_left = min(lv.x_left for lv in window)
        x_right = max(lv.x_right for lv in window)
        span = x_right - x_left
        aligned = span > 0 and all(
            abs((lv.x_right - lv.x_left) - span) <= span * X_EXTENT_TOLERANCE
            for lv in window
        )

        if regular and aligned:
            staff = Staff(
                x_left=x_left, x_right=x_right, y_top=window[0].y, y_bottom=window[4].y
            )
            staff.barlines = endpoint_boundaries(window, staff)
            staves.append(staff)
            i += 5
        else:
            i += 1
    return staves


def endpoint_boundaries(window: list[Level], staff: Staff) -> list[float]:
    """Frontières déduites des coupures des lignes de portée (cas MuseScore).

    On n'accepte une abscisse que si elle apparaît sur au moins trois des cinq
    lignes : une interruption isolée est un artefact, une barre de mesure coupe
    les cinq lignes.
    """
    tol = max(staff.space * 0.3, 0.5)
    candidates: list[tuple[float, int]] = []
    for line_no, level in enumerate(window):
        candidates.extend((x, line_no) for x in level.interior_endpoints(tol))
    if not candidates:
        return []
    candidates.sort()

    boundaries: list[float] = []
    cluster = [candidates[0]]
    for entry in candidates[1:]:
        if entry[0] - cluster[-1][0] <= tol:
            cluster.append(entry)
        else:
            _emit_cluster(cluster, boundaries)
            cluster = [entry]
    _emit_cluster(cluster, boundaries)
    return boundaries


def _emit_cluster(cluster: list[tuple[float, int]], boundaries: list[float]) -> None:
    """Retient un amas d'extrémités s'il est corroboré par assez de lignes."""
    if len({line_no for _, line_no in cluster}) >= ENDPOINT_CONSENSUS:
        boundaries.append(sum(x for x, _ in cluster) / len(cluster))


# ---------------------------------------------------------------------------
# Portées -> boîtes de mesure
# ---------------------------------------------------------------------------


def _boundaries(staff: Staff) -> list[float]:
    """Frontières de mesure : bords de portée + barres, dédoublonnées."""
    tol = max(staff.space * 0.6, 0.5)
    raw = sorted([staff.x_left, *staff.barlines, staff.x_right])
    merged: list[float] = []
    for x in raw:
        if merged and x - merged[-1] <= tol:
            # Les deux traits d'une barre de reprise ne font qu'une frontière.
            merged[-1] = (merged[-1] + x) / 2.0
        else:
            merged.append(x)
    return merged


def measures_for_page(geometry: PageGeometry) -> list[MeasureBox]:
    """Découpe chaque portée en mesures et applique le padding composite."""
    staves = sorted(geometry.staves, key=lambda s: s.y_top)
    boxes: list[MeasureBox] = []

    for i, staff in enumerate(staves):
        if staff.height <= 0:
            continue

        # La frontière entre deux systèmes est posée au milieu de leur écart :
        # chaque portée récupère ainsi le maximum de place pour ses accords et
        # ses lignes supplémentaires, sans que deux masques ne se chevauchent.
        ceiling = 0.0
        if i > 0:
            ceiling = (staves[i - 1].y_bottom + staff.y_top) / 2.0
        floor = geometry.height
        if i + 1 < len(staves):
            floor = (staff.y_bottom + staves[i + 1].y_top) / 2.0

        y_top = max(staff.y_top - staff.height * PAD_TOP_RATIO, ceiling, 0.0)
        y_bottom = min(
            staff.y_bottom + staff.height * PAD_BOTTOM_RATIO, floor, geometry.height
        )
        if y_bottom <= y_top:
            continue

        bounds = _boundaries(staff)
        min_width = staff.space * MIN_MEASURE_SPACES
        spans = [(a, b) for a, b in zip(bounds, bounds[1:]) if (b - a) >= min_width]
        for j, (x_start, x_end) in enumerate(spans):
            boxes.append(
                MeasureBox(
                    x=x_start,
                    y=y_top,
                    w=x_end - x_start,
                    h=y_bottom - y_top,
                    staff_index=i,
                    index_in_staff=j,
                    is_last_of_staff=(j == len(spans) - 1),
                )
            )

    return boxes


def normalise(box: MeasureBox, width: float, height: float) -> dict:
    """Convertit en coordonnées relatives 0.0–1.0, arrondies à 4 décimales."""

    def clamp(v: float) -> float:
        return round(min(max(v, 0.0), 1.0), 4)

    return {
        "x": clamp(box.x / width),
        "y": clamp(box.y / height),
        "w": clamp(box.w / width),
        "h": clamp(box.h / height),
    }
