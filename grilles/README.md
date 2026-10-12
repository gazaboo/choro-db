# Grilles d'accords — générées automatiquement

Une grille par morceau (`<titre>-<compositeur>.json`), en Ut / C, au format des
grilles relevées à la main de l'application d'apprentissage : parties (A, B, C,
Coda), une entrée par mesure écrite (`[]` = accord tenu), fins 1 / 2,
reprises, tonalité de chaque partie. `index.json` liste toutes les grilles.

> ⚠️ **Générées par script, non relues.** Les accords et leur ordre sont
> fiables ; le découpage en parties et l'alignement exact sur les mesures sont à
> vérifier sur la partition.

## Deux origines

| `generated` | `confidence` | Source | Ce qui est lu |
|---|---|---|---|
| `mxl` | `medium` | `mxl/C/<…> - Theme - C.mxl` | accords exacts mesure par mesure, reprises, fins 1 / 2, coda, armure |
| `pdf` | `low` | PDF C vectoriel le plus riche en chiffrages (morceaux sans MXL) | accords du texte rangés sous leurs barres de mesure ; parties coupées aux doubles barres ; reprises et fins non détectées |

Les morceaux disponibles uniquement en scan n'ont pas de grille : leurs
chiffrages ne sont pas du texte.

## Ce que valent les grilles

Comparées aux grilles relevées à la main (mêmes morceaux, accords simplifiés,
toutes tonalités confondues) :

- **MXL** (30 morceaux) : 81 % des mesures identiques, 88 % de l'enchaînement
  d'accords ; même nombre de parties 23 fois sur 30.
- **PDF** (44 morceaux) : 70 % des mesures, 81 % de l'enchaînement ; même
  nombre de parties 30 fois sur 44.

Les écarts restants viennent pour moitié des grilles manuelles elles-mêmes, dont
l'alignement sur les mesures est approximatif ; les autres sont des
partitions d'une autre version (tonalité ou harmonisation différente).

Le champ `notes` signale les points douteux, dont « Tonalité de la partition
source non vérifiée » quand la partition porte cet avertissement.

## Régénérer

```sh
outils/audit/.venv/bin/python -I outils/grilles/grilles.py      # MXL → grilles/
outils/audit/.venv/bin/python -I outils/grilles/grilles_pdf.py  # PDF, pour les morceaux sans MXL
outils/audit/.venv/bin/python outils/grilles/valider.py <dossier des grilles manuelles>
```

`grilles_pdf.py` lit `outils/audit/sorties/inventaire.jsonl` (lancer d'abord
`outils/audit/inventaire.py`).
