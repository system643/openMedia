# Sécurité

openMedia lit des textes venus du web avec des modèles d'IA, peut lire l'historique des navigateurs (si l'utilisateur l'active) et expose une API locale. Le modèle de sécurité est décrit dans le README (« Sécurité : des agents sans pouvoir ») :

- les agents n'ont aucun outil d'action ;
- le backend ne télécharge que des pages de l'Internet public ;
- le matériau web reste une donnée, jamais une consigne ;
- l'API locale exige un jeton et refuse les en-têtes Host étrangers.

## Signaler une faille

Ne publie pas de détail exploitable dans un ticket public. Utilise le signalement privé de vulnérabilité de la plateforme qui héberge le dépôt (« Report a vulnerability » sur GitHub), en décrivant la classe du problème et comment le reproduire. Une réponse est donnée dès que possible ; ce projet est maintenu bénévolement.

Sont particulièrement utiles :
- une page web qui fait agir un agent au-delà de rendre du texte ;
- un accès à l'API locale sans le jeton ;
- une requête qui part vers le réseau local ou le PC ;
- un envoi de données hors de ce que décrit Réglages › Confidentialité.
