# Tâche : nommer les sujets récurrents des lectures et rédiger leur prompt de suivi

Tu reçois des sujets qu'un algorithme a trouvés dans l'historique de lecture du lecteur : pour chacun, ses mots-clés, le nombre d'articles lus, de jours et de médias, et quelques titres lus. L'ordre et les chiffres sont déjà établis : ne les change pas.

Pour chaque sujet, rends :
- `name` : un nom neutre et précis de 3 à 6 mots, tiré des titres (« Procès de l'assassinat de Brahim Kessaci », « Budget 2027 de la France »).
- `prompt` : un prompt de suivi à la première personne, de 2 à 4 phrases, qui dit précisément quoi suivre : l'histoire, ses acteurs principaux, les faits nouveaux à guetter et les échéances connues d'après les titres. Rien qui ne soit dans les titres ; pas de date inventée.
- `followable` : faux si ce n'est pas un sujet d'actualité qui se suit dans la durée (bons plans, promotions, recettes, horoscope, météo, résultats sportifs isolés, tutoriels, programme télé) ; vrai sinon.

Si les titres d'un sujet mêlent deux histoires sans rapport, nomme la principale.
