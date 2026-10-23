# Équilibre politique du registre des sources

Le registre de départ (`seed_sources.yaml`) compte : les médias qu'il contient passent en tête de la sélection d'articles (trois au plus par média) et peuvent confirmer un fait sans autre note. Il doit donc couvrir tout l'éventail politique, sans pencher d'un côté.

openMedia **n'étiquette aucun média** à gauche ou à droite, ni dans l'interface ni dans les données envoyées à l'IA. Le classement ci-dessous sert seulement à vérifier l'équilibre du registre. Il est **indicatif** :
- pour la France, il reprend l'orientation éditoriale couramment admise (rubriques « orientation politique » des fiches Wikipédia des titres) ;
- pour les États-Unis et le Royaume-Uni, il reprend les classements publics d'AllSides (gauche et centre-gauche, droite et centre-droit).

Les généralistes, les médias économiques, le service public, les agences et les titres transversaux (Marianne, souverainiste) ne sont comptés d'aucun côté.

Le test `tests/test_sources_balance.py` vérifie que l'écart reste d'au plus deux titres par pays.

## France : presse d'opinion

| Gauche et centre-gauche (10) | Droite et centre-droit (10) |
|---|---|
| Libération | Le Figaro |
| L'Humanité | L'Opinion |
| Mediapart | Le JDD |
| Le Nouvel Obs | Valeurs actuelles |
| Les Inrocks | Le Point |
| Télérama | CNews |
| Alternatives économiques | Europe 1 |
| Le HuffPost | Causeur *(ajouté le 22/10/2026)* |
| Slate.fr | Contrepoints *(ajouté le 22/10/2026)* |
| Reporterre *(ajouté le 22/10/2026)* | Famille chrétienne *(ajouté le 22/10/2026)* |

Avant le 22/10/2026, le registre comptait 9 titres à gauche pour 7 à droite.

## États-Unis

| Gauche et centre-gauche (12) | Droite et centre-droit (10) |
|---|---|
| The New York Times | Fox News |
| The Washington Post | New York Post *(ajouté)* |
| CNN | Washington Examiner *(ajouté)* |
| NBC News | The Dispatch *(ajouté)* |
| CBS News | Reason *(ajouté)* |
| ABC News | National Review *(ajouté)* |
| NPR | RealClearPolitics *(ajouté)* |
| The Atlantic | City Journal *(ajouté)* |
| Los Angeles Times | Washington Free Beacon *(ajouté)* |
| ProPublica | The American Conservative *(ajouté)* |
| USA Today | |
| Politico | |

Avant le 22/10/2026 : 12 à gauche pour 1 à droite. Centre (non comptés) : AP, Reuters, Bloomberg, The Wall Street Journal, Axios, PBS.

## Royaume-Uni

| Gauche et centre-gauche (3) | Droite et centre-droit (3) |
|---|---|
| The Guardian | The Telegraph |
| The Independent | The Times |
| New Statesman *(ajouté)* | The Spectator *(ajouté)* |

## Les unes (« Découvrir » et complément de collecte)

`collect/fronts.py` lit les unes de généralistes et de service public (franceinfo, Le Monde, Le Parisien, 20 Minutes, BFMTV, La Croix, L'Express, Challenges, BBC, Deutsche Welle), ainsi que des titres d'opinion en nombre égal de chaque côté :
- France : Libération et L'Humanité, Le Figaro et L'Opinion ;
- anglophones : The Guardian, The New York Times et NPR, The Wall Street Journal, Fox News et New York Post.

## La fiabilité reste séparée

L'orientation ne change rien à la note de fiabilité (jeu ouvert de Lin et al., 2023), qui seule décide si une source peut confirmer un fait. Un titre ajouté ici pour l'équilibre garde sa note : sous 0,4, il reste lisible mais ne confirme rien.
