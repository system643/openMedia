# Tâche : proposer des sujets à suivre

Tu reçois les titres à la une de plusieurs médias (numérotés, avec le nom du média) et la liste des sujets que le lecteur suit déjà. Les médias couvrent tout l'éventail politique : ne favorise aucun bord.

- Regroupe les titres qui parlent de la même histoire. Ne retiens que les histoires qui peuvent durer plusieurs jours et se prêtent à un suivi (négociations, procès, crises, réformes, lancements, conflits, enquêtes), pas les faits divers isolés ni les résultats sportifs ponctuels.
- Pour chaque histoire : un titre neutre, un résumé factuel d'une phrase tiré des titres, la rubrique (un code parmi WORLD, NATION, BUSINESS, TECHNOLOGY, SCIENCE, HEALTH, ENTERTAINMENT, SPORTS), les indices des titres regroupés, et un brouillon de prompt de suivi à la première personne.
- Si une histoire touche un sujet déjà suivi, indique son identifiant dans `related_topic_id` ; sinon null.
- Classe les histoires de la plus couverte (le plus de médias différents) à la moins couverte, en mettant en avant celles qui sont proches des centres d'intérêt du lecteur. Au plus 12 histoires.
