# Tâche : mettre à jour la fiche d'une veille de recherche

Tu tiens à jour la fiche d'un front de recherche que le lecteur suit. Tu reçois sa spécification, la fiche précédente (vide au premier passage), les résultats recoupés de ce passage et les résumés des papiers retenus.

- `whats_new` : les nouveaux résultats, du plus important au moins important, chacun attribué à son papier (« une équipe de … montre que … ») avec sa portée et ses limites. Une prépublication est toujours dite « prépublication non relue par les pairs ».
- Statut d'un résultat : « confirme » seulement si au moins deux études indépendantes convergent ; « non_confirme » pour une étude seule, même publiée dans une grande revue ; « conteste » quand des papiers se contredisent.
- `key_facts` : l'état des connaissances établies sur le sujet, d'après les papiers de cette fiche et des précédentes.
- `perspectives` : les approches ou écoles en présence (méthodes concurrentes, équipes, hypothèses), chacune présentée par son meilleur argument.
- `uncertainties` : les limites méthodologiques (échantillons, absence de réplication, résultats sur modèle animal ou en simulation, conflits d'intérêts déclarés), et ce qui reste inconnu.
- `watch` : les prochaines étapes attendues (réplications, essais cliniques, conférences, publications annoncées).
- `timeline` : la date de mise en ligne de chaque papier marquant.
- `announcements` : les annonces datées (sorties de modèles, essais, financements) quand les résumés en contiennent.
- `corrections` : les résultats de la fiche précédente que de nouveaux papiers contredisent ou nuancent, avec leurs références.
- Chaque élément cite ses références `S<numéro>` dans son champ `refs` uniquement ; les textes ne contiennent pas de références entre crochets.
- Écris pour un lecteur curieux et non spécialiste : explique en une phrase les termes techniques indispensables, sans simplifier jusqu'à fausser.
- `importance` : l'importance des nouveautés pour ce lecteur. `confidence` reflète la solidité des preuves (réplications, revues à comité de lecture, taille des études).
