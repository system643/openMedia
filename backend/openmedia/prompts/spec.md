# Tâche : préparer un agent de suivi

Le lecteur t'a confié un prompt qui décrit un sujet d'actualité à suivre et la manière de l'étudier. Transforme-le en une spécification de recherche que des outils automatiques (GDELT, les unes des médias, flux RSS) pourront exécuter chaque jour.

- Les requêtes sont courtes (2 à 6 mots), comme on les taperait dans un moteur de recherche d'actualité ; elles couvrent les noms propres, les synonymes et la façon dont la presse étrangère nomme le sujet. Évite les opérateurs complexes ; les guillemets sont permis pour une expression exacte.
- Les mots-clés servent à reconnaître un article pertinent dans un flux : noms d'acteurs, de lieux, de lois, d'organisations, termes techniques.
- L'angle reformule fidèlement ce que le lecteur veut savoir et comment il veut que ce soit présenté ; n'ajoute pas d'exigences qu'il n'a pas exprimées.
- Si le prompt demande des parties précises (par exemple « un point chiffré », « les positions de chaque pays »), crée une section par demande.
- La date de départ n'est remplie que si le sujet est manifestement un événement né il y a moins de 7 jours d'après le prompt ; dans le doute, null.
