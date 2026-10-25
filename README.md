# openMedia

**Ton journal personnel, tenu par une IA qui recoupe ses sources.**

Tu choisis les sujets que tu veux suivre : un projet de loi, une entreprise, une découverte scientifique, une ville… Chaque jour, openMedia lit la presse à ta place. Il garde les faits, écarte l'opinion, la réaction à chaud et la rumeur, vérifie que chaque fait est rapporté par au moins deux sources indépendantes, puis met à jour une **fiche** par sujet. Après chaque passage, **Le Brief** résume ce qui a changé ; tu peux le lire ou l'écouter.

- Application de bureau pour **Windows 10 et 11**, gratuite et open source (licence Apache 2.0).
- **Aucun compte openMedia, aucun serveur** : tout reste sur ton PC. L'auteur ne reçoit aucune donnée.
- Il faut une **IA** pour faire le travail : une clé API (de l'ordre de 5 à 10 $ par mois et par sujet suivi chaque jour), un abonnement Claude, ou une IA installée sur ton PC (gratuite). Voir [Choisir son IA](#2-choisir-son-ia).

> Projet personnel et expérimental. Les fiches sont rédigées par une IA, qui peut se tromper : chaque phrase renvoie aux articles d'où elle vient, vérifie ceux qui comptent pour toi.

## Sommaire

1. [Installer](#1-installer)
2. [Choisir son IA](#2-choisir-son-ia)
3. [Premier lancement](#3-premier-lancement)
4. [Au quotidien](#4-au-quotidien)
5. [Problèmes fréquents](#5-problèmes-fréquents)
6. [Mettre à jour, désinstaller](#6-mettre-à-jour-désinstaller)
7. [Ce qui sort de ton PC](#7-ce-qui-sort-de-ton-pc)
8. [Limites](#8-limites)
9. [Pour les curieux : comment ça marche](#9-pour-les-curieux--comment-ça-marche)
10. [Pour les développeurs](#10-pour-les-développeurs)

## 1. Installer

Compte deux minutes. Pas besoin de droits d'administrateur, ni d'installer autre chose.

1. **Télécharge l'installeur** : ouvre la page [**Dernière version**](../../releases/latest) et clique sur le fichier **`openMedia_…_x64-setup.exe`**, dans la liste « Assets » en bas de la version.
2. **Si ton navigateur hésite** (« n'est pas fréquemment téléchargé ») : clique sur **⋯** à côté du téléchargement, puis **Conserver**, puis **Conserver quand même**.
3. **Ouvre le fichier téléchargé.** Windows affiche sans doute un écran bleu « **Windows a protégé votre ordinateur** » : clique sur **Informations complémentaires**, puis sur **Exécuter quand même**.
   *Pourquoi ?* openMedia n'est pas signé par un certificat commercial (payant chaque année) : Windows prévient pour tout logiciel qu'il ne connaît pas encore. Le code source complet est sur cette page.
4. **Suis l'installeur** (Suivant, Installer, Fermer). openMedia s'ouvre ; tu le retrouves ensuite dans le **menu Démarrer**.

Si ton antivirus bloque le fichier, c'est une fausse alerte fréquente pour les logiciels non signés qui embarquent un moteur Python : tu peux le déclarer comme « faux positif » à ton antivirus.

## 2. Choisir son IA

openMedia ne contient pas d'IA : il en utilise une, au choix. Le tutoriel du premier lancement te la fait choisir ; prépare-la avant si tu peux.

| | Pour qui | Coût | Ce qu'il faut |
|---|---|---|---|
| **Une clé API** : Anthropic, Grok, OpenAI, DeepSeek, Gemini, Mistral… | Tout le monde | À l'usage : de l'ordre de 5 à 10 $ par mois et par sujet suivi chaque jour, selon l'actualité et le fournisseur. Un plafond mensuel t'empêche de dépasser ce que tu as choisi | Un compte chez le fournisseur et un peu de crédit |
| **L'IA sur ce PC** | PC récent et puissant : 16 Go de mémoire au moins, idéalement une carte graphique | Gratuit | Installer Ollama et un modèle |
| **Claude Code** (facultatif) | Ceux qui ont déjà un abonnement Claude Pro ou Max | Inclus dans l'abonnement (compte dans ses limites) | Installer Claude Code (voir plus bas) |

Aucune n'est obligatoire : une seule suffit, et **Claude n'est pas nécessaire**. Les clés Anthropic, OpenAI, DeepSeek, Google Gemini, Mistral, Kimi, GLM (Z.ai), Qwen, Grok (xAI), Groq et OpenRouter fonctionnent, ainsi que tout fournisseur compatible OpenAI (Together, Fireworks…) : colle-les au même endroit, le fournisseur est reconnu tout seul.

**Mélanger** : dans Réglages › Moteur IA, chacun des trois rôles (tri, sujets, Directeur) a son modèle, en ligne ou sur ce PC. Par exemple le tri sur Ollama (gratuit) et les fiches chez Groq ou Grok.

**Groq** (à ne pas confondre avec Grok, l'IA de xAI) fait tourner des modèles ouverts (GPT-OSS) très vite et pour pas cher. Son offre gratuite limite les tokens par minute : une fiche longue peut la dépasser, et openMedia le dit alors en clair. L'offre payante (Developer) lève cette limite. **Petit budget** : DeepSeek coûte 3 à 5 fois moins que Claude Sonnet, mais traite tes articles en Chine, et son filtre de contenu peut refuser des sujets politiques sensibles. Dans Réglages › Moteur IA, le bouton « Tester » vérifie qu'un modèle marche avec openMedia, et `python -m openmedia banc --modeles a,b` compare des modèles sur un même jeu d'articles.

### Obtenir une clé Anthropic (5 minutes)

1. Va sur [platform.claude.com](https://platform.claude.com) et crée un compte (adresse e-mail, puis le code reçu).
2. Dans **Billing** (facturation), clique sur **Buy credits** et achète du crédit : **10 à 20 $** pour un mois avec un ou deux sujets (5 $ minimum). Laisse le rechargement automatique coupé : tu ne pourras jamais dépenser plus que ce crédit.
3. Dans **API keys**, clique sur **Create key**, nomme-la « openMedia », puis **copie la clé** : elle commence par `sk-ant-` et ne s'affiche qu'une fois.
4. Dans le tutoriel d'openMedia, colle-la dans **Une clé API**. Elle est vérifiée, puis rangée dans le coffre-fort de Windows (Gestionnaire d'identifiants) ; elle n'est envoyée qu'à Anthropic.
5. Choisis un **plafond mensuel** (5, 15 ou 30 $). Une fois atteint, les passages automatiques s'arrêtent jusqu'au mois suivant. Pour dépenser moins : moins de sujets, un passage tous les deux jours (Réglages › Général), ou le préréglage Économique (Réglages › Moteur IA).

### Utiliser l'IA sur ce PC (gratuit)

1. Installe [Ollama](https://ollama.com/download).
2. Ouvre le Terminal Windows et tape `ollama pull qwen3:14b` (environ 9 Go à télécharger), ou un autre modèle d'au moins 14 milliards de paramètres.
3. Lance openMedia : Ollama et ses modèles sont détectés tout seuls.

L'analyse se fait alors sur ton PC, mais Internet reste nécessaire pour lire la presse. Un passage est plus lent qu'avec une clé API, et un petit modèle se trompe plus souvent.

### Utiliser Claude Code (abonnement Claude)

1. Installe [Node.js](https://nodejs.org), version « LTS ».
2. Dans le Terminal Windows, tape `npm install -g @anthropic-ai/claude-code`, puis `claude`, et connecte-toi à ton compte Claude.
3. Relance openMedia : Claude Code est détecté.

C'est réservé à ton usage personnel, avec ton propre compte.

## 3. Premier lancement

Un tutoriel plein écran (environ 3 minutes) te guide. Rien n'est envoyé nulle part avant ton accord.

1. **Ce que fait openMedia**, et ses limites.
2. **Le choix de l'IA** (voir plus haut).
3. **Les conditions de fonctionnement** : la liste de ce qui est envoyé, et à qui. C'est la seule chose obligatoire.
4. **Les options**, toutes **coupées par défaut** : sujets proposés d'après l'historique de tes navigateurs, Découvrir, Brief audio… Tu peux tout laisser coupé.
5. **Ton premier sujet** : décris en une phrase ce que tu veux suivre, par exemple « Les négociations sur le budget 2027 à l'Assemblée nationale ». openMedia en tire ses mots-clés et te montre un aperçu.
6. **La languette** : un petit onglet au bord droit de l'écran pour enregistrer un article (coupée par défaut).

Le premier passage démarre aussitôt : compte quelques minutes avant que la fiche apparaisse.

## 4. Au quotidien

- **Aujourd'hui** : les sujets qui ont bougé depuis ta dernière visite, et Le Brief.
- **Un sujet** : sa fiche (quoi de neuf, faits clés, chronologie), son calendrier et ses sources. Chaque phrase porte ses références : clique dessus pour lire l'article.
- **« Confirmé »** veut dire rapporté par deux sources indépendantes, dont une au moins de fiabilité reconnue. **« Non confirmé »** ne veut pas dire faux, seulement pas encore recoupé.
- **Mettre à jour**, en haut d'un sujet (ou `Ctrl + R`), lance un passage tout de suite.
- **Suivre un sujet** (`Ctrl + N`) en ajoute un.
- **Réglages** : le rythme des passages (par défaut chaque jour à 6 h 30), l'IA, la confidentialité, la consommation du mois.
- Fermer la fenêtre ne quitte pas openMedia : il reste près de l'horloge (zone de notification) pour faire ses passages. Un passage manqué, PC éteint, est rattrapé au démarrage suivant.

## 5. Problèmes fréquents

**« Moteur IA non prêt », ou rien ne se passe.** Ouvre Réglages › Moteur IA : la clé doit être enregistrée et vérifiée. Avec l'IA sur ce PC, Ollama doit être lancé.

**« Crédit épuisé » ou « plafond atteint ».** Ajoute du crédit chez ton fournisseur (par exemple [platform.claude.com](https://platform.claude.com) pour Anthropic, [console.x.ai](https://console.x.ai) pour Grok), ou relève ton plafond dans Réglages › Moteur IA. Les passages automatiques reprennent seuls.

**Un sujet reste vide.** Relance le sujet et regarde les messages du passage : la ligne « Collecte » dit ce que chaque source a trouvé. Si tout est à 0, vérifie ta connexion et que GDELT et Bing Actualités sont actifs (Réglages › Confidentialité), puis élargis les mots-clés du sujet.

**« On me demande Claude, je n'en veux pas. »** Claude n'est jamais obligatoire. Colle ta clé (Grok, OpenAI, DeepSeek…) ou lance Ollama, puis dans Réglages › Moteur IA choisis le modèle de chaque rôle. Une ligne orange signale un rôle encore réglé sur un modèle indisponible, et dit par quoi il est remplacé.

**Une fiche dit « rien de neuf ».** C'est normal sur un sujet calme : openMedia n'invente rien. Un sujet très pointu peut aussi être peu couvert par la presse ; élargis alors sa consigne.

**Un article n'a que son titre.** Il est réservé aux abonnés du journal : openMedia ne contourne aucun paywall et se contente du titre et du résumé.

**L'application ne s'ouvre plus.** Regarde près de l'horloge (flèche ^) : elle est peut-être déjà lancée. Sinon, redémarre le PC.

## 6. Mettre à jour, désinstaller

- **Mettre à jour** : télécharge la nouvelle version depuis [Dernière version](../../releases/latest) et installe-la par-dessus. Tes sujets et tes fiches sont gardés.
- **Désinstaller** : Paramètres Windows › Applications › openMedia › Désinstaller. Tes données restent dans `%APPDATA%\openMedia` (tape-le dans la barre d'adresse de l'Explorateur) : supprime ce dossier pour tout effacer. Ta clé API se retire dans le Gestionnaire d'identifiants de Windows (entrées « openMedia »).

## 7. Ce qui sort de ton PC

- **Les articles collectés pour tes sujets et ta consigne** partent à l'IA que tu as choisie (sauf avec l'IA sur ce PC).
- **Les recherches de presse** partent à GDELT, un index mondial de la presse, à Bing Actualités (Microsoft) et aux sites des journaux, comme quand tu les lis. GDELT et Bing se coupent dans Réglages › Confidentialité.
- **Rien d'autre sans ton accord** : l'historique de tes navigateurs n'est lu que si tu l'actives, et pour les navigateurs que tu choisis. Le détail exact est dans Réglages › Confidentialité, où tu peux aussi tout effacer ou retirer ton accord.
- Aucune statistique, aucun pisteur, aucun serveur openMedia.

## 8. Limites

- **Les fiches et le Brief sont rédigés par une IA.** Elle peut se tromper : chaque phrase renvoie à ses articles, vérifie ceux qui comptent pour toi.
- **« Confirmé » veut dire recoupé, pas vérifié** : deux sources indépendantes le rapportent, dont une au moins de fiabilité établie hors IA. Ce n'est pas une enquête, et un fait « non confirmé » n'est pas faux pour autant.
- **La couverture dépend de GDELT, de Bing Actualités, des unes de vingt médias et de tes flux RSS.** GDELT limite parfois ses requêtes, et Bing prend alors le relais ; un sujet de niche peut rester mal couvert.
- **La note de fiabilité d'un média ne mesure pas son bord politique.** Elle ne sert qu'à décider si une source peut confirmer un fait seule, et tu peux la changer.
- **Coût indicatif** avec le réglage par défaut (Claude Sonnet), d'après les premiers passages observés, encore peu nombreux : de l'ordre de 0,15 $ pour un passage sans nouveauté et de 0,80 à 1,30 $ pour un passage riche, soit 5 à 10 $ par mois et par sujet suivi chaque jour. Le premier passage d'un sujet, qui remonte une semaine, coûte le plus. Gratuit avec l'IA sur ton PC.

## 9. Pour les curieux : comment ça marche

### Un passage, étape par étape

1. **Fenêtre de temps.** Au premier passage, l'agent remonte au plus 7 jours, moins si le sujet est plus récent. Ensuite, il reprend depuis le dernier passage, avec 6 h de recouvrement ; un sujet espacé remonte jusqu'à son dernier passage et ratisse plus large (jusqu'à 100 articles au lieu de 60).
2. **Collecte gratuite, la même avec toutes les IA.** GDELT (recherche datée, FR et EN, données du [GDELT Project](https://www.gdeltproject.org/)), Bing Actualités (son flux RSS de recherche, sans clé : `collect/bing_news.py`), les unes de vingt médias de tous bords qui citent les mots-clés du sujet (`collect/fronts.py`), tes flux RSS et les liens que tu as glissés. Les médias du registre passent en premier, avec au plus 3 articles par média. Google News n'est plus utilisé : son `robots.txt` interdit ses flux de recherche et ses pages d'articles (vérifié le 22/10/2026). GDELT accepte une requête toutes les 5 secondes et refuse parfois une adresse pendant plusieurs minutes : après deux refus, il se repose cinq minutes et Bing Actualités, les unes et les flux RSS prennent le relais. Le journal de chaque passage dit ce que chaque source a apporté (« Collecte : GDELT 0 (saturé), Bing Actualités 24, unes des médias 3 »).
3. **Extraction** du texte avec trafilatura. openMedia se présente comme tel (agent `openMedia`) et lit chaque page pour toi, à ta demande, comme ton navigateur : ce n'est pas un robot d'indexation, il ne suit aucun lien et ne republie rien, et il ne consulte donc ni robots.txt ni les réservations de fouille de textes (TDMRep). Aucun paywall n'est contourné : une page fermée garde son titre et le résumé de son flux. Quand un flux RSS publie l'article entier, ce texte sert si la page refuse.
4. **Fiabilité des sources.** Chaque domaine reçoit une note de 0 à 1, affichée seulement comme « établie », « estimée par l'IA » ou « faible ». Elle vient d'abord de la notation ouverte de Lin et al. (2023, [PNAS Nexus](https://doi.org/10.1093/pnasnexus/pgad286), [données](https://github.com/hauselin/domain-quality-ratings)), qui agrège six organismes (NewsGuard, Media Bias/Fact Check, Ad Fontes Media…) sur 11 520 domaines. Ce jeu n'est pas redistribué avec openMedia : il est téléchargé depuis le dépôt de ses auteurs après ton accord. Un domaine absent est qualifié une seule fois par l'IA : presse, média d'État, source officielle, blog, agrégateur ou ferme de contenu ; une note de l'IA reste sous 0,6 et ne confirme jamais un fait seule. Ta note, dans Réglages › Sources, l'emporte toujours. Une source « faible » reste lisible, mais ne confirme jamais un fait. Le registre de départ couvre l'éventail politique à parts égales (autant de titres d'opinion à gauche qu'à droite, voir `backend/openmedia/sources/EQUILIBRE.md`) ; aucun média n'est étiqueté à gauche ou à droite dans l'application.
5. **Tri** de chaque article : fait, analyse, opinion, réaction ou rumeur, avec un score de sensationnalisme et les affirmations qu'il contient, datées quand l'article situe l'événement.
6. **Recherche complémentaire** par la recherche web du modèle (Claude, OpenAI, Gemini ou OpenRouter), seulement s'il y a moins de N sources indépendantes.
7. **Recoupement.** Un fait n'est « confirmé » qu'avec deux sources indépendantes : une dépêche reprise ou un même groupe de presse ne comptent qu'une fois. Au moins l'une d'elles doit avoir une fiabilité établie hors IA (jeu ouvert, registre de départ ou ta note) : deux sites inconnus, peut-être du même réseau, ne confirment rien seuls. Une règle déterministe le vérifie après le modèle. Les faits à source unique des 14 derniers jours restent ouverts : une source parue le lendemain peut les confirmer. Les faits établis des 45 derniers jours qui ressemblent à une affirmation du jour sont aussi fournis : un article en retard qui redit un fait connu le rejoint au lieu de redevenir une nouveauté, et un fait confirmé ne perd jamais son statut faute de source du jour.
8. **Recherche active.** Pour les quatre faits à source unique les plus pertinents, l'agent cherche d'autres médias (GDELT et Bing Actualités, puis la recherche web du modèle pour deux d'entre eux) et recoupe à nouveau. La recherche complémentaire d'un sujet peu couvert passe par la recherche web du modèle (Anthropic, OpenAI, Gemini, OpenRouter) ; chez les autres fournisseurs et avec l'IA de ce PC, par Bing Actualités.
9. **Fraîcheur.** Un article du jour peut relater une nouvelle ancienne. L'agent compare chaque fait à la date de l'événement et aux titres parus sur 90 jours. Une nouvelle déjà parue avant le passage sort de « Quoi de neuf » et du brief ; elle reste dans les faits clés, avec sa date.
10. **Que du neuf.** Avant la rédaction, le programme classe chaque fait. Seuls les faits nouveaux et les rectifications sont rédigés. Un fait connu qu'une nouvelle source confirme, ou qu'un nouveau média rapporte alors qu'il en avait moins de trois, va dans « Confirmé depuis le dernier passage ». Une reprise d'un fait déjà bien couvert est seulement comptée (« Aussi : 6 articles ont repris des faits déjà connus »). Un article qui reprend tel quel un article déjà retenu (même texte ou même titre) n'est même pas trié.
11. **Rédaction** de la nouvelle version de la fiche, avec la fiche précédente comme contexte, et seulement s'il y a du neuf. Sinon, la fiche est reconduite par le programme, statuts et sources à jour, sans appel au modèle : c'est l'étape la plus coûteuse d'un passage.
12. **Garde-fous.** Les références inventées sont retirées, les chiffres introuvables dans les articles sont signalés, puis une relecture de neutralité est suivie d'une seule révision par correctifs ciblés. Un correctif ne s'applique que si son extrait figure une seule fois dans la fiche et s'il n'ajoute ni chiffre ni source.
13. **Spectre des sources.** La fiche montre la répartition par pays, par famille et par groupe de presse, avec les angles morts.


### Moteur IA : l'IA sur ce PC, Claude Code ou clés API

**L'IA sur ce PC.** Ollama (`127.0.0.1:11434`) et LM Studio (`127.0.0.1:1234`) sont détectés avec leurs modèles ; les adresses se changent dans `local_urls`. En mode local, tous les appels (tri, agents de sujet, Directeur, vérifications, sujets de lectures) passent par le modèle choisi, un à la fois, et rien ne part chez un fournisseur en ligne : si le serveur local ne répond pas, les passages s'arrêtent au lieu de se replier en ligne. Ollama est appelé par son API native avec un contexte de 32 768 tokens ; pour LM Studio, règle ce contexte au chargement du modèle. La recherche complémentaire passe par Bing Actualités (pas de recherche web du modèle en local). Un modèle d'au moins 14 milliards de paramètres est conseillé. Internet reste nécessaire pour la collecte (GDELT, Bing Actualités, unes et sites des médias, flux RSS).

Tout se règle dans Réglages → Moteur IA. Colle une clé : le fournisseur est reconnu (Anthropic `sk-ant-`, OpenAI `sk-proj-`, Gemini `AIza`, Grok `xai-`, Groq `gsk_`, OpenRouter `sk-or-`, Mistral…), puis la clé est vérifiée. Une clé reconnue sur un compte sans crédit est gardée, avec un message qui le dit. Elle est rangée dans le Gestionnaire d'identifiants de Windows.

| | Claude Code installé | Clé API (Anthropic, OpenAI, DeepSeek, Gemini, Mistral, Kimi, GLM, Qwen, Grok, Groq, OpenRouter, ou tout fournisseur compatible OpenAI) |
|---|---|---|
| Ce qu'il faut | `npm install -g @anthropic-ai/claude-code`, puis lancer `claude` une fois pour te connecter | Une clé du fournisseur |
| Facturation | Ton abonnement Claude : le coût est affiché au tarif de l'API, mais il n'est pas facturé en plus ; il compte dans les limites de ton abonnement | À l'usage. Le budget mensuel arrête les passages planifiés au-delà ; ceux que tu lances toi-même restent possibles |
| Fonctionnement | Un `claude -p` isolé par appel : aucun outil (sauf WebSearch), aucun MCP, aucun réglage ni CLAUDE.md chargé | Anthropic : SDK officiel, cache de prompt, repli serveur en cas de refus. Autres fournisseurs : appels HTTP directs, schéma JSON strict |

Chaque rôle prend un modèle de n'importe quel fournisseur (`fournisseur:modèle`, par exemple `gemini:gemini-3.8-flash`). Les modèles sont rangés par gamme : Maximum, Premium, Équilibré, Rapide. Les préréglages Économique, Équilibrée et Qualité remplissent les trois rôles chez le fournisseur choisi. Le rôle « Agents de sujet », qui écrit et recoupe les faits, ne descend jamais sous Équilibré. Si un rôle vise un fournisseur sans clé, le modèle de même gamme d'un fournisseur disponible prend le relais, et le journal du passage le note.

**Claude Code et ton abonnement.** openMedia lance le Claude Code officiel installé sur ton PC, sans le modifier, avec le compte auquel tu t'y es connecté toi-même par la procédure d'Anthropic ; il ne lit, ne garde ni ne transmet tes identifiants. Les règles d'Anthropic ([Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)) n'empêchent pas « an end user from signing in to the unmodified Claude Code binary with their own Claude subscription », mais interdisent à un développeur de faire passer les requêtes de ses utilisateurs par des identifiants d'abonnement, et les limites Pro et Max supposent un usage « ordinary, individual ». C'est donc pour ton usage personnel, avec ton propre compte ; pour un usage intensif ou partagé, utilise une clé API.

Réglage par défaut : Haiku 5.5 trie les articles, Sonnet 5.5 fait tourner les agents de sujet et le Directeur. Les prix sont dans `backend/openmedia/agents/providers/catalog.py`, relevés le 19/10/2026 ; ceux d'OpenRouter sont lus en direct.

#### Consommation et fréquence

Avec Claude Code sur abonnement, l'usage compte dans les limites de ton abonnement (Anthropic ne les publie pas en tokens) ; openMedia les estime en tokens, comptés ainsi : tokens lus, cache compris, plus tokens écrits.
- **La jauge en bas de la barre latérale** donne :
  - les tokens du mois ;
  - l'estimation de fin de mois au rythme réglé ;
  - le prochain passage.
- **Réglages → Consommation** :
  - les tokens du mois : lus, dont ceux lus depuis le cache, et écrits ;
  - les barres des 30 derniers jours : sujets, brief, autres ;
  - un plafond mensuel de tokens. Au-delà, les passages planifiés s'arrêtent. « Tout mettre à jour » reste possible.
  - les montants en dollars : facturé, équivalent abonnement, projection et budget ;
  - le détail du dernier passage et du dernier brief.
- **Rythme des passages** :
  - les jours : tous les N jours (de 1 à 30), ou certains jours de la semaine ;
  - les heures : jusqu'à six passages par jour ;
  - des raccourcis : Chaque jour, Matin et soir, En semaine, Un jour sur deux, Chaque semaine.
  - Le rythme général se règle dans Réglages → Général. Chaque sujet peut avoir le sien, dans son onglet Agent ; Consommation montre ce que chacun coûte.
  - Chaque sujet affiche ses passages et ses tokens par mois, qui se recalculent aussitôt.
  - Les jours de passage sont alignés sur le calendrier : les sujets d'un même rythme tournent ensemble.
  - Le brief suit les passages des sujets et ceux du rythme général.
  - Changer les jours du rythme général fait d'aujourd'hui un jour de passage.
- **Jours d'échéance** : un sujet peut passer aussi le jour de chaque échéance datée au jour près, et le lendemain pour en lire l'issue. C'est activé par défaut ; ces passages sont comptés dans les estimations.
- **Rythme conseillé** (sans IA) : après six passages au même rythme, openMedia regarde ce que chacun a réellement apporté.
  - Un sujet qui bouge peu reçoit une proposition chiffrée, par exemple : « 2 passages sur les 8 derniers ont apporté du neuf. À 1 jour sur 3, tu aurais eu les mêmes nouvelles avec 1,5 jour de retard en moyenne, pour ≈ 20 passages de moins par mois ». Le retard est simulé sur l'historique réel, l'économie comptée comme dans Consommation, au coût d'un passage calme.
  - Un sujet mort se voit proposer un passage par semaine ; un sujet espacé qui s'accélère, un rythme plus serré. Un sujet important (5 sur 5) n'est jamais espacé au-delà d'un jour sur deux.
  - **Rythme adaptatif** (par sujet, ou par défaut pour les nouveaux sujets) : l'app applique le conseil elle-même, entre des bornes, revient au rythme le plus serré dès qu'un passage est riche, et te prévient à chaque changement. Le journal du rythme permet de revenir en arrière.
  - **Le pouls** : les jours sans passage, un relevé gratuit des titres de GDELT (sans IA). Si un sujet espacé s'emballe (plusieurs médias, des titres jamais vus), son passage est avancé.
  - L'onglet Agent montre la bande des 30 derniers jours : passages avec du neuf, avec seulement des confirmations, ou sans rien, et le pouls.

#### Calendrier

Chaque sujet a un onglet Calendrier, qui se remplit au fil des passages :
- les échéances relevées dans les sources : promesses, votes, audiences, sommets, sorties, dates butoirs, avec leur état (à venir, en retard, réalisée, reportée, abandonnée) ; celles datées seulement au mois sont rangées à part ;
- les dates de la chronologie de la fiche ;
- les passages faits (on rouvre la version de ce jour-là) et les passages prévus, dont ceux ajoutés pour une échéance.

La page Échéances propose la même vue pour tous les sujets (Liste ou Calendrier).

Toute dépense est consignée, y compris les liens glissés, les vérifications d'article, l'audio et Découvrir.

**Mode Économie** (option) : le passage quotidien regroupe ses appels Anthropic (clé API) et OpenAI dans l'API Batch, à moitié prix. Il peut prendre de quelques minutes à quelques heures. Un appel que le lot ne sert pas est rejoué aussitôt. Les actions manuelles restent immédiates.

### Sécurité : des agents sans pouvoir

Les agents d'openMedia lisent des textes venus du web, et un texte peut cacher des consignes (« ignore tes instructions… »). La protection tient d'abord à ce que **les agents ne peuvent rien faire** : ils rendent du JSON et, au plus, lancent une recherche web.

1. **Aucun outil d'action.**
   - Claude Code est lancé verrouillé : `--tools ""` (WebSearch seul pour la recherche), `--safe-mode` (ni CLAUDE.md, hooks, plugins, skills ni MCP personnels), `--restricted`, `--permission-mode dontAsk --permission-prompts none` (toute permission est refusée), `--strict-mcp-config`, `--setting-sources ""`, et un plafond de 2 $ par appel.
   - Il tourne dans un dossier vide, avec un environnement sans le jeton de l'API locale ni aucune clé.
   - Les appels API n'acceptent aucun outil autre que la recherche web. Tout autre outil est refusé avant l'envoi.
   - Réglages → Moteur IA indique si le verrouillage est complet.
2. **Internet public seulement.** Le backend ne télécharge jamais une page qui mène au PC, à la box ou au réseau local, même après une redirection, et même si l'adresse vient d'un modèle ou d'un flux.
3. **Le matériau reste une donnée.**
   - Les caractères invisibles et les balises sont retirés des textes avant qu'ils entrent dans un prompt.
   - Un article qui s'adresse à une IA est marqué `suspect`, puis écarté par le tri. Un article qui *parle* d'IA reste utilisable.
   - La charte rappelle au modèle que le matériau n'est jamais une consigne.
4. **Ce qui sort est nettoyé.**
   - Les phrases suspectes d'une fiche sont signalées.
   - Le serveur MCP, qui parle à ton Claude Code personnel, masque ces phrases, n'envoie que des adresses web et rappelle sur chaque réponse que ce sont des données.
   - L'API locale exige son jeton, comparé en temps constant, et refuse les en-têtes Host étrangers (DNS rebinding).

### Enregistrements

Un article enregistré n'est pas suivi : il attend ta décision dans l'onglet **Enregistrements**.

- **Rassembler des sources** cherche d'autres médias sur le même sujet (GDELT et Bing Actualités, puis la recherche web du modèle si la couverture est maigre). Les faits de l'article sont recoupés avec la règle des deux sources indépendantes. Une synthèse neutre est ensuite rédigée : l'essentiel, le contexte, les questions ouvertes et la suite attendue. Les garde-fous sont ceux des fiches : références vérifiées, chiffres retrouvés dans les articles cités, passages suspects masqués. Compte une à trois minutes ; la dépense est consignée.
- **Suivre** en fait un nouveau sujet, ou ajoute l'article à un sujet existant.
- **Supprimer** retire l'enregistrement.

### Bon à savoir

- Fermer la fenêtre la cache seulement : openMedia reste dans la zone de notification pour le passage quotidien. Un passage manqué est rattrapé au lancement.
- La languette, collée au bord droit de l'écran, se déplace en la glissant verticalement. Si tu actives le repérage (coupé par défaut), elle s'allume quand le navigateur au premier plan affiche un article de presse.
  - Survole-la pour **enregistrer** l'article, ou appuie sur `Ctrl + Alt + S`.
  - Elle reçoit aussi les liens glissés. `Ctrl + Alt + N` enregistre le lien copié dans le presse-papiers.
  - L'adresse est lue dans la barre d'adresse par l'UI Automation de Windows, sans extension. Elle n'est gardée que si tu enregistres, et les fenêtres privées sont ignorées. Tout se coupe dans Réglages → Général.
- Les données sont dans `%APPDATA%\openMedia` : la base SQLite, l'audio et les réglages.

## 10. Pour les développeurs

**Construire depuis les sources.** Prérequis : Windows 10 ou 11 avec WebView2 (présent sur Windows 11), Node.js 20 ou plus, Python 3.12 et `uv` (`python -m pip install uv`), Rust stable avec les outils de compilation MSVC (Visual Studio Build Tools). Voir aussi `CONTRIBUTING.md`.

```
npm install
cd backend && python -m uv sync && cd ..
npm run tauri dev           # l'application ; le moteur Python démarre tout seul
npm run backend:test        # tests du moteur
npm run bundle              # installeur Windows (moteur Python embarqué)
```

Pour tester le moteur sans l'interface :

```
cd backend
python -m uv run python -m openmedia add "Suis la mission Artemis III : calendrier, essais, retards."
python -m uv run python -m openmedia run 1 --dry   # collecte et tri, sans fiche
python -m uv run python -m openmedia run 1         # passage complet
python -m uv run python -m openmedia fiche 1
```

**Publier une version** : `npm run bundle` construit l'installeur dans `src-tauri/target/release/bundle/nsis/`, à joindre à une release GitHub.

### Licence et mentions

openMedia est distribué sous licence Apache 2.0 (`LICENSE`). Les attributions (GDELT, Lin et al., polices, bibliothèques) sont dans `NOTICE`. Données du [GDELT Project](https://www.gdeltproject.org/). Claude et Claude Code sont des marques d'Anthropic ; openMedia n'est affilié à aucun fournisseur d'IA ni à aucun média. Contribuer : `CONTRIBUTING.md` ; signaler une faille : `SECURITY.md`.
