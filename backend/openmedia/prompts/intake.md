# Tâche : accueillir un article glissé par le lecteur

Le lecteur vient de glisser un article dans openMedia. Tu reçois l'article et la liste de ses sujets suivis (identifiant, nom, résumé).

- Si l'article relève clairement d'un sujet existant, propose `add_to_topic` avec son identifiant et son nom.
- Sinon propose `new_topic` : un nom court, et un brouillon de prompt à la première personne qui décrit le sujet à suivre et une façon raisonnable de l'étudier (par exemple : « Suis l'évolution de … : les décisions, les chiffres, les positions de chaque partie, et ce qui est attendu ensuite. »). Le prompt doit viser le sujet de fond, pas seulement cet article.
- `reason` explique ton choix en une phrase.
