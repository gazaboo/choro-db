# Grilles d'accords — générées automatiquement

Une grille par morceau (`<titre>-<compositeur>.json`), en Ut / C, au format des
grilles relevées à la main de l'application d'apprentissage : parties (A, B, C,
Coda), une entrée par mesure écrite (`[]` = accord tenu), fins 1 / 2,
reprises, tonalité de chaque partie. `index.json` liste toutes les grilles.

> ⚠️ **Générées par script, non relues.** Seules sont publiées ici les 338
> grilles qu'une autre partition du morceau confirme (`confidence: high`,
> voir « Confiance ») ; le découpage en parties reste à vérifier sur la
> partition. Les 504 autres attendent une relecture (issue dédiée).

## Deux origines

| `generated` | Source | Ce qui est lu |
|---|---|---|
| `mxl` | `mxl/C/<…> - Theme - C.mxl` | accords exacts mesure par mesure, reprises, fins 1 / 2, coda, armure |
| `pdf` | PDF C vectoriel le plus riche en chiffrages (morceaux sans MXL) | accords du texte rangés sous leurs barres de mesure ; parties coupées aux doubles barres ; reprises et fins non détectées |

Les morceaux disponibles uniquement en scan n'ont pas de grille : leurs
chiffrages ne sont pas du texte.

## Confiance

Chaque grille est comparée à une partition **indépendante** du même morceau
(`outils/grilles/croiser.py`) : un PDF vectoriel d'un autre logiciel que sa
source — jamais un PDF MuseScore pour une grille MXL, puisqu'il est imprimé
depuis ce MXL —, en C, Bb ou Eb (la comparaison ignore la transposition), ou
une grille relevée à la main.

| `confidence` | Règle | Grilles | Publiées |
|---|---|---|---|
| `high` | un témoin indépendant donne le même enchaînement d'accords (≥ 85 %) et les mêmes accords mesure par mesure (≥ 75 %) ; parties de 4 à 48 mesures, au plus 4 accords par mesure | 338 (331 MXL, 7 PDF) | oui |
| `medium` | grille MXL non corroborée (témoin trop différent ou absent) ; grille PDF corroborée mais à la structure douteuse | 279 | non |
| `low` | grille PDF sans témoin ou en désaccord ; grille contredite par un témoin (enchaînement < 50 % : autre version ?) | 225 | non |

`croiser.py` laisse dans `grilles/` les seules grilles `high` et range les
autres dans `outils/audit/sorties/grilles-a-verifier/` (non versionné).

Un accord diminué compte comme le majeur de même fondamentale : les PDF
Encore perdent souvent le signe ° à l'export (« G#° » imprimé « G# »).
Le champ `notes` donne le témoin retenu et son score.

Pourquoi les autres ne sont pas `high` :

- 205 grilles PDF n'ont **aucun témoin** : seul un PDF vectoriel du morceau
  existe (les autres sont des scans) ;
- 234 grilles MXL concordent à moins de 85 % avec leur original : le plus
  souvent, des portées ou des chiffrages que la lecture du PDF témoin ne
  trouve pas sur certaines mises en page ; parfois une harmonisation
  différente.

Face aux grilles relevées à la main : MXL 81 % des mesures identiques et 88 %
de l'enchaînement (30 morceaux) ; lecture PDF 76 % et 86 % (39 morceaux). Une
partie de l'écart vient des grilles manuelles, dont l'alignement sur les
mesures est approximatif.

Le champ `notes` signale aussi « Tonalité de la partition source non
vérifiée » quand la partition porte cet avertissement.

## Régénérer

```sh
outils/audit/.venv/bin/python -I outils/grilles/grilles.py      # MXL → grilles/
outils/audit/.venv/bin/python -I outils/grilles/grilles_pdf.py  # PDF, pour les morceaux sans MXL
outils/audit/.venv/bin/python -I outils/grilles/croiser.py       # témoins indépendants → confidence ; ne garde que les high
outils/audit/.venv/bin/python outils/grilles/valider.py <dossier des grilles manuelles>
```

`grilles_pdf.py` lit `outils/audit/sorties/inventaire.jsonl` (lancer d'abord
`outils/audit/inventaire.py`).
