# Contribuer à openMedia

Merci de ton intérêt. openMedia est un projet personnel, open source, qui se trompe parfois : les signalements argumentés valent autant que le code.

## Lancer le projet

Prérequis :
- Windows 10 ou 11, avec WebView2 (déjà présent sur Windows 11) ;
- Node.js 20 ou plus ;
- Python 3.12 et `uv` (`python -m pip install uv`) ;
- Rust stable avec les outils de compilation MSVC (Visual Studio Build Tools), pour Tauri.

Commandes :

```
npm install
cd backend && python -m uv sync && cd ..
npm run tauri dev        # l'application
npm run backend:test     # les tests du moteur
npm run build            # vérification TypeScript et build de l'interface
```

## Règles

- **Pas de données personnelles** dans les tests, les captures ou les tickets : ni historique de navigation, ni sujets réels, ni clés. Les tests tournent sur un dossier de données jetable et des faux serveurs.
- **Aucun appel réseau réel dans les tests** : simule les fournisseurs (respx, faux serveurs).
- **Les règles de rigueur sont dans le code**, pas seulement dans les consignes aux modèles (indépendance des sources, statut « confirmé », chiffres retrouvés). Une modification de ces règles vient avec ses tests.
- **Une option qui lit des données personnelles ou envoie des données hors du suivi des sujets** est coupée par défaut, a son interrupteur dans Réglages › Confidentialité, et apparaît dans `src/lib/privacy.ts`.
- Code et commentaires en français, comme le reste du projet.

## Proposer une source ou contester une note

- Le registre de départ est `backend/openmedia/sources/seed_sources.yaml`. Il doit rester équilibré politiquement : voir `backend/openmedia/sources/EQUILIBRE.md` et le test `test_sources_balance.py`.
- Pour contester la propriété d'un média ou une note, ouvre un ticket avec une source vérifiable (registre, article, rapport). openMedia n'étiquette aucun média à gauche ou à droite.
