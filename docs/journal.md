# Journal technique — LOL Assistant

Journal de bord détaillé du projet, phase par phase : décisions, erreurs détectées et corrigées, alternatives écartées. Pour la vue d'ensemble, voir le [README](../README.md).

Projet éducatif : construire, étape par étape, un assistant qui aide un joueur de League of Legends à établir un **plan de jeu** à partir d'une **composition d'équipe** (10 champions, 2 équipes). L'objectif premier est d'apprendre — l'API Riot Games, le ML, et l'intégration d'un LLM — pas de livrer un produit fini rapidement.

## Ce que l'assistant final fera (et ne fera pas)

- **Entrée** : une composition **choisie librement par l'utilisateur** (les 10 champions des deux équipes), hypothétique — pas une partie en cours.
- **Sortie** : un plan de jeu textuel expliquant les forces/faiblesses de la composition et les champions décisifs, pas juste un pourcentage de victoire brut.
- **Ce que ce n'est pas** : l'assistant ne va *pas* chercher la partie en cours d'un joueur précis. Aucun pseudo n'est nécessaire pour l'utiliser. Les pseudos utilisés pendant le développement (voir phase 1 et 2) ne servent qu'en coulisses, pour collecter des données d'entraînement.

## Architecture globale du pipeline

```
Riot API (ingestion) → SQLite (stockage brut) → pandas (extraction) → Gradient Boosted Trees + SHAP (ML) → LLM (Claude API) → interface
```

## Statut global

| Phase | Statut |
|---|---|
| 1. Ingestion Riot API | ✅ Terminée |
| 2. Collecte du dataset (SQLite + snowball sampling) | ✅ Terminée — 12 482 matchs collectés |
| Chantier — Industrialisation en package Python | ✅ Terminée |
| 3. Modèle ML (Gradient Boosted Trees + SHAP) | ✅ Terminée — modèle entraîné, SHAP étapes 1-2-3 faites |
| 4. LLM (plan de jeu textuel) | ✅ Terminée — plan de jeu généré avec Claude |
| 5. Interface (CLI) | ✅ Terminée — validée en conditions réelles (`data/` + appel Claude), couverte par des tests unitaires |

## Phase 1 — Bases de l'API Riot ✅ Terminée

Fichier : [`notebooks/01_riot_api_basics.ipynb`](../notebooks/01_riot_api_basics.ipynb)

Ce qu'on y a appris et implémenté, concept par concept :
1. Anatomie d'une requête HTTP (méthode, URL, headers) — appel sans clé API pour observer le `401`.
2. Authentification via le header `X-Riot-Token`, clé chargée depuis `.env` (jamais en dur dans le code).
3. Régions (`europe`, `americas`...) vs plateformes (`euw1`, `na1`...) — deux systèmes de routage différents selon les endpoints.
4. **Account-V1** : résoudre un Riot ID (`pseudo#tag`) en `puuid`, avec encodage d'URL (`urllib.parse.quote`).
5. **Match-V5** : lister les IDs de matchs récents d'un `puuid`, puis récupérer le détail complet d'un match.
6. **Rate limiting** : lecture des headers `X-Rate-Limit-*`, gestion du `429` avec une fonction `riot_get` qui attend et réessaie automatiquement (`Retry-After`).
7. **Extraction d'une composition** : à partir du détail d'un match, isoler pour chacun des 10 participants `champion`, `team` (bleue/rouge), `role`, `win`.

Résultat concret validé : récupération du `puuid` de mon compte, de mes matchs récents, et extraction complète d'une composition à 10 lignes.

Ce notebook est un **artefact pédagogique figé** : il ne sera pas refactoré vers le futur package Python (contrairement à la phase 2, voir plus bas), car son but est de documenter l'apprentissage pas-à-pas des concepts API, pas de fournir du code réutilisable.

## Phase 2 — Collecte du dataset ✅ Terminée

Fichier : [`notebooks/02_dataset_collection.ipynb`](../notebooks/02_dataset_collection.ipynb)

**Décisions prises :**
- **Stockage : SQLite** (`data/matches.db`, jamais versionné). Une table `matches` (JSON brut, `match_id` en clé primaire → dédoublonnage automatique) et une table `explored_players` (`puuid` déjà explorés, pour ne pas re-scanner un joueur). Le JSON brut est gardé tel quel : si on veut extraire de nouvelles features plus tard (items, durée de partie...), pas besoin de re-interroger l'API.
- **Stratégie de collecte : snowball sampling.** Chaque match récupéré contient 10 `puuid` (ses participants) qu'on réutilise comme nouvelles graines à explorer — ça donne de la diversité de joueurs sans appels API dédiés à la découverte, via un parcours en largeur (BFS).
- **Rate limiting proactif** (`RateLimiter`, fenêtre glissante 100 appels/120s) plutôt que seulement réactif (attendre après un `429`) — évite de perdre du temps en pénalités pendant une collecte de plusieurs milliers de matchs.

**Fait et validé :**
- Schéma SQLite + fonctions CRUD (`match_already_collected`, `save_match`, `player_already_explored`, `mark_player_explored`).
- `RateLimiter` (fenêtre glissante) + client Riot combinant attente proactive et retry sur `429`.
- Boucle de crawl `crawl_matches` (BFS/snowball sampling) — testée avec succès sur un petit lot (`target_count=20`), y compris la reprise correcte entre deux sessions différentes (un joueur déjà exploré lors d'une exécution précédente est bien ignoré lors de la suivante, sans appel API gaspillé).
- Visualisation du contenu de la base via `pd.read_sql_query` dans le notebook, et via l'extension VS Code *SQLite Viewer* installée pour parcourir `data/matches.db` visuellement.
- Code entièrement industrialisé dans le package `lol_assistant/` (voir section dédiée ci-dessous) — le notebook n'importe plus que des fonctions/classes, il ne les définit plus.
- **Correctif qualité de données (2026-09-15)** : le crawl snowball n'appliquait aucun filtre de mode de jeu — 4 des 20 premiers matchs collectés se sont révélés être en mode Arena (`gameMode="CHERRY"`, 2v2v2v2, sans rapport avec le 5v5 classique). `crawl_matches` ne sauvegarde désormais que les matchs `gameMode == "CLASSIC"` (il continue à explorer les participants de ces matchs pour le snowball sampling, juste sans les stocker).
- **`crawl_matches` évolué pour la collecte à grande échelle** : accepte maintenant une **liste** de graines (`seed_puuids`, pas juste une seule — nécessaire pour relancer efficacement, la file d'attente n'étant pas persistée entre deux exécutions) et une limite de **durée** (`max_duration_seconds`), en plus du `target_count` — utile pour viser "quelques heures de collecte" plutôt qu'un nombre de matchs qu'on ne sait pas estimer précisément à l'avance.
- **`scripts/collect_dataset.py`** : script (pas un notebook — tâche d'infra longue durée, pas un concept à apprendre) qui trouve tous les `puuid` déjà croisés dans les matchs collectés mais jamais explorés (via `metadata.participants` du JSON brut), et relance `crawl_matches` à partir de ces graines. Usage : `python scripts/collect_dataset.py [heures] [db_path]`. Lancé en arrière-plan avec `python -u` (sortie non bufferisée — sans `-u`, les `print()` restent en tampon et n'apparaissent pas en temps réel dans un fichier de log).
- **Collecte à grande échelle lancée le 2026-09-15**, arrêtée le 2026-09-16 après ~7h effectives (le script tourne en tâche de fond, ajustable/arrêtable à la demande) : **12 482 matchs** en base, **3 106 joueurs explorés**. Objectif largement atteint, phase 2 considérée terminée.

Point d'attention pour une collecte future plus longue : la clé de dev Riot expire toutes les 24h — envisager une clé personnelle si besoin.

## Chantier transversal — Industrialisation en package Python ✅ Terminée

Le code réutilisable de la phase 2 (auparavant inline dans le notebook, avec des variables globales comme `conn`, `cursor`, `headers`) est maintenant un vrai package Python structuré par responsabilité, importable depuis n'importe quel notebook ou script futur.

**Structure réalisée :**
- `lol_assistant/rate_limiter.py` — la classe `RateLimiter` (fenêtre glissante), sans effet de bord (pas de `print`, contrairement à la version notebook — une bibliothèque interne ne décide pas de ce qui s'affiche).
- `lol_assistant/riot_client.py` — classe `RiotClient` encapsulant clé API, headers, région et rate limiter, avec des méthodes `get_puuid`, `get_match_ids`, `get_match_detail`. Chaque méthode appelle `response.raise_for_status()` : elle lève une exception (`requests.HTTPError`) plutôt que de renvoyer un objet à vérifier manuellement.
- `lol_assistant/database.py` — `get_connection(db_path)` (ouvre la connexion **et** garantit le schéma) + les fonctions CRUD, prenant désormais `conn` en paramètre explicite plutôt que de dépendre d'un `cursor` global partagé (qui aurait pu créer des interférences entre requêtes).
- `lol_assistant/crawler.py` — `crawl_matches(riot_client, conn, seed_puuids, target_count, matches_per_player=10, max_duration_seconds=None)`, orchestre les deux modules ci-dessus. Utilise `try`/`except requests.HTTPError` plutôt que de vérifier `status_code`, en cohérence avec `RiotClient`. `seed_puuids` accepte une liste ou une simple chaîne ; `max_duration_seconds` permet de borner par le temps plutôt que par un nombre de matchs (ajouté pour la collecte à grande échelle, voir phase 2).
- `pyproject.toml` à la racine — packaging minimal (`setuptools`), avec `[tool.setuptools.packages.find] include = ["lol_assistant*"]` explicite (sans ça, `setuptools` refuse de choisir entre `data/`, `notebooks/` et `lol_assistant/` comme package à inclure). Dépendances du package : `requests`, `python-dotenv` (le strict nécessaire au code lui-même — `pandas`/`jupyter` restent dans `requirements.txt`, ce sont des outils d'environnement, pas des dépendances du code).

`notebooks/01_riot_api_basics.ipynb` reste inchangé (artefact pédagogique figé). `notebooks/02_dataset_collection.ipynb` a été mis à jour : les cellules de code sont devenues de simples imports depuis `lol_assistant/`, les explications pédagogiques en markdown sont conservées avec une note pointant vers l'implémentation réelle.

Validation effectuée : le package s'importe correctement, tests isolés (base de données, `RiotClient` avec un vrai appel API, `crawl_matches` de bout en bout), puis exécution complète du notebook 2 (`jupyter nbconvert --execute`) sans erreur.

## Phase 3 — Modèle ML : Gradient Boosted Trees + SHAP ✅ Terminée

Fichier : [`notebooks/03_model_training.ipynb`](../notebooks/03_model_training.ipynb)

### La vision (redéfinie en cours de route)

L'architecture initialement prévue était une Factorization Machine (FM) sur des embeddings de champions (voir *Décision abandonnée* plus bas). En la concevant plus en détail, j'ai reformulé l'objectif en 3 étapes plus riches, à partir du **déroulé de la partie** plutôt que des picks seuls :
1. Identifier, via le ML, les **faits de jeu** (objectifs, kills, économie, vision...) statistiquement liés à la victoire.
2. Pour **chaque champion**, déterminer lesquels de ces faits comptent le plus **spécifiquement pour lui**.
3. Pour une **composition donnée**, agréger ça en un plan de jeu : quels faits prioriser, lesquels ne changeront pas grand-chose.

### Architecture retenue

**Gradient Boosted Trees (XGBoost/LightGBM) + SHAP**, sur un dataset **au niveau joueur** (une ligne par participant par match, pas par match) :
- SHAP donne l'importance globale des features → étape 1.
- Les valeurs d'interaction SHAP entre `champion` et chaque fait de jeu → étape 2.
- Les contributions SHAP pour une ligne donnée (somme exacte = la prédiction) → étape 3, sans outil d'explicabilité externe supplémentaire.

**Pourquoi pas la Timeline API** : Match-V5 (déjà collecté, aucun nouvel appel nécessaire) contient déjà un champ `challenges` par participant — ~125 statistiques dérivées par Riot (`dragonTakedowns`, `teamBaronKills`, `killParticipation`, `teamDamagePercentage`, `laningPhaseGoldExpAdvantage`, `visionScorePerMinute`...). Ça couvre l'essentiel de ce qu'on serait allé chercher dans la Timeline, sans doubler le budget de rate limiting. La Timeline (`RiotClient.get_match_timeline`, déjà ajouté mais non utilisé) reste une option pour affiner plus tard avec du timing précis.

**Erreur corrigée en cours de route** : une première version sommait les champs individuels (`soloKills`...) en totaux d'équipe avant l'entraînement — ce qui détruit le lien champion↔fait de jeu nécessaire à l'étape 2. Corrigé : le dataset reste à la granularité (match, joueur), jamais agrégé à (match, équipe). Certains champs `challenges` sont en réalité des faits d'équipe dupliqués à l'identique chez les 5 coéquipiers (ex: `teamBaronKills`) plutôt que des faits individuels (ex: `soloKills`) — Riot ne documente pas laquelle des deux catégories s'applique à chaque champ, donc c'est détecté empiriquement sur les données (un champ est "équipe" seulement s'il n'a **jamais** varié entre les 5 joueurs d'une même équipe sur tout le dataset).

### Fait et validé (extraction du dataset)

1. Chargement des matchs bruts depuis SQLite + parsing JSON.
2. Extraction composition/résultat/durée par match, filtrage des remakes (`game_duration < 300s`).
3. **Filtrage des modes de jeu hors-sujet** (ex: Arena/`CHERRY`) — présents dans les tout premiers matchs collectés (voir phase 2, correctif crawler).
4. Classification empirique des champs `challenges` (équipe vs joueur), exclusion des champs Arena/ARAM (`SWARM_*`, `poroExplosions`...).
5. Construction du dataset final : une ligne par (match, joueur), `champion` en vraie feature, faits individuels non sommés, faits d'équipe en contexte partagé.
6. **Rejoué sur la collecte complète (2026-09-16)** après la collecte à grande échelle : **123 460 lignes** (12 346 matchs `CLASSIC` valides × 10 joueurs), **134 colonnes**, 173 champions distincts (minimum 93 occurrences chacun). La classification champ équipe/joueur s'est affinée avec plus de données (19 champs équipe contre 26 sur l'échantillon initial de 20 matchs, plus fiable).
7. **Ajout du `role`** (`teamPosition` Riot : `TOP`/`JUNGLE`/`MIDDLE`/`BOTTOM`/`UTILITY`), oublié dans une première version — indispensable pour distinguer "ce fait compte peu pour ce champion" de "ce fait compte peu pour son rôle en général".
8. **Détection de fuite de donnée** : `maxKillDeficit` (3ᵉ plus forte corrélation dans une première passe) s'est avéré valoir **toujours exactement 0** côté perdant, jamais côté gagnant — un signe de fuite (le champ encode quasiment le résultat) plutôt qu'un vrai fait observable en cours de partie. Détecté systématiquement (tout champ quasi-nul chez les perdants mais présent chez les gagnants) plutôt qu'au cas par cas ; exclu du classement de pertinence et de l'entraînement à venir.
9. **Export CSV pour Power BI** (`data/dataset_for_powerbi.csv`, non versionné) — étape d'exploration visuelle interactive prévue avant l'entraînement (Power BI Desktop ne tourne pas sous Linux ; le fichier est transféré vers une machine Windows). Export volontairement à plat (une ligne par match/joueur, pas pré-agrégé) : Power BI est fait pour construire les pivots/agrégations interactivement.
10. **Classement de pertinence par corrélation** (`data/feature_relevance.csv`), **le même par rôle** (`data/feature_relevance_by_role.csv`, format long rôle×fait), un **état des lieux des valeurs manquantes** (`data/missing_values.csv`, 26 colonnes concernées, 17 à plus de 50%), et une **table de synthèse par champion** (`data/champion_summary.csv` : parties jouées, taux de victoire, rôle principal) — tous non versionnés. En tête du classement global : `turretTakedowns` (corr. 0.60), `turretPlatesTaken` (0.50), `kda` (0.47).
11. **Séparer causes et conséquences de la victoire** : une équipe qui écrase déjà l'autre accumule tours/kills/KDA tout au long de la partie *parce qu'elle gagne déjà* — restreindre aux **faits précoces** (avant ~20 min) rapproche des vraies décisions stratégiques. 128 champs classés en 3 catégories vérifiées (mécaniquement bornés dans le temps, explicitement nommés "early"/"before" par Riot, horodatages) → **29 champs retenus** dans `EARLY_GAME_FIELDS`, exportés dans `data/feature_relevance_early_game.csv`. Nouveau classement, sans le bruit du snowball : `maxLevelLeadLaneOpponent` en tête (corr. 0.37, contre 0.60 pour le classement global — plus faible mais plus honnête).
12. **Vérification web en cours de route** : `turretPlatesTaken` avait été classé "borné dans le temps" (plaques supposées disparaître à 14 min) — recherche web à l'appui, le **patch 26.01** (7-8 janvier 2026, actif pendant toute la collecte) a supprimé cette expiration. Confirmé aussi empiriquement (`turretPlatesTaken` atteint 41 dans nos données, impossible sous l'ancien plafond). Reclassé en cumul sur toute la partie, exclu du sous-ensemble early-game. Bonne illustration qu'un jeu vivant change et qu'une hypothèse doit se vérifier, pas se supposer — encore plus dans un projet où les données sont postérieures à la date de connaissance du modèle.
13. **Guide Power BI pas-à-pas** : [`docs/powerbi_guide.md`](powerbi_guide.md) — import des 6 fichiers, types de colonnes, l'histoire des fuites (`maxKillDeficit`, `turretPlatesTaken`), mesures DAX de base, graphiques (barres, matrice rôle×fait, slicers, cartes), avec le rappel que cette exploration ne remplace pas SHAP.

### Entraînement du modèle (2026-09-16)

14. **Préparation** : features = `EARLY_GAME_FIELDS` (moins les fuites) + `champion` + `role`, en catégorielles natives (`category` dtype + `enable_categorical=True` côté XGBoost — pas de one-hot, qui exploserait en 173 colonnes pour les champions).
15. **Split train/test par `match_id`** (`GroupShuffleSplit`), pas par ligne — un split ligne par ligne aurait fui de l'information entre les 10 lignes d'un même match. 9 876 matchs en train, 2 470 en test, aucun chevauchement.
16. **Premier entraînement** (29 features) : Accuracy 0.815, ROC-AUC 0.887 — plus élevé qu'attendu. SHAP a montré `earliestBaron` dominant très largement (près de 2x le suivant), signe d'alerte.
17. **Correction** : le Baron apparaît à 20:00 précises dans le patch actuel (vérifié sur le web, source 2026) — `earliestBaron` ne peut donc **jamais** représenter un fait "avant 20 min", erreur de classification plutôt qu'insight. Retiré avec `earliestElderDragon` (encore plus tardif). `EARLY_GAME_FIELDS` passe à 27 champs.
18. **Second entraînement** (27 features) : Accuracy 0.779, ROC-AUC 0.860 — score plus bas mais plausible (les indicateurs de lane inclus sont légitimement très prédictifs en solo queue). Importance SHAP bien répartie cette fois (`firstTurretKilledTime` en tête à 0.63, `voidMonsterKill` juste derrière à 0.58 — rapport ~1.08, contre ~1.7 avant correction) : signal distribué sur des faits légitimes, pas une fuite résiduelle qui dominerait tout. Version retenue.
18bis. **Reprise approfondie (2026-09-18)** — split en **train/validation/test** (60/20/20, par `match_id`, deux `GroupShuffleSplit` successifs) plutôt que train/test seul : la validation sert à comparer des hyperparamètres sans jamais toucher au test. Recherche sur une petite grille (`max_depth`, `learning_rate`) avec **arrêt anticipé** (`early_stopping_rounds`, XGBoost choisit lui-même le nombre d'arbres via la validation plutôt qu'un `n_estimators` deviné). Meilleur réglage trouvé : `max_depth=3, learning_rate=0.05, n_estimators=385` — très proche du choix initial (`max_depth=4`), qui s'avère donc avoir été raisonnable. Modèle final réentraîné sur train+validation réunis, évalué une seule fois sur le test : Accuracy 0.780, **Precision 0.766 / Recall 0.807** (plus de faux positifs que de faux négatifs), **Log loss 0.465, Brier score 0.152**, et une **courbe de calibration quasi parfaite** (quand le modèle annonce 70% de victoire, c'est vraiment ~70% dans les faits) — précieux pour la phase 4 si un niveau de confiance est affiché. Comparé à une base de référence naïve (toujours prédire la classe majoritaire, 50%).
19. **SHAP — étape 1 (importance globale)** ✅ faite au point 18 ci-dessus, refaite avec le modèle affiné du point 18bis (résultats quasi identiques — confirme que l'analyse SHAP n'est pas un artefact d'un seul entraînement).
20. **SHAP — étape 2 (interactions champion × fait)** ✅ : `shap_interaction_values` sur tout le jeu de test (24 700 lignes, 18s de calcul), agrégées par (champion, fait) → `data/champion_feature_interactions.csv` (4844 lignes). Résultat marquant, non suggéré au modèle : les supports (Lulu, Nautilus) ont `visionScoreAdvantageLaneOpponent` en tête de leurs interactions — la vision compte différemment pour eux, cohérent avec leur rôle. Répond directement à l'étape 2 de la vision initiale.
21. **Modèle sauvegardé** : `data/xgb_model.joblib` (modèle + liste de features + catégories `champion`/`role` connues à l'entraînement) — pour que la phase 4 (LLM) puisse le réutiliser sans ré-entraîner.

22. **Étape 3 — attribution par composition** : problème conceptuel à résoudre d'abord — le modèle prédit à partir de faits *observés* en partie réelle, impossibles à connaître pour une composition hypothétique. Solution : `composition_fact_ranking(champions)` combine l'importance globale (étape 1) + les interactions champion×fait (étape 2) pour les 5 champions donnés, sans nouveau calcul SHAP.
23. **Correction (2026-09-18)** : sommer les interactions des 5 champions diluait l'info utile (un fait moyennement pertinent pour 3 champions dépassait un fait très pertinent pour 1 seul). Remplacé par le **maximum** parmi les 5, avec le champion associé conservé (`key_champion`) — le conseil devient "priorise ce fait, particulièrement via ce champion" plutôt qu'un score agrégé anonyme. Sur la composition d'exemple (Jayce/Sylas/Yone/Yunara/Lulu) : `voidMonsterKill` (Jayce), `firstTurretKilledTime` (Yone), `maxLevelLeadLaneOpponent` (Sylas), `earliestDragonTakedown` et `visionScoreAdvantageLaneOpponent` (Lulu, cohérent avec la découverte support/vision de l'étape 2).
24. **Artefacts prêts pour la phase 4** : `data/xgb_model.joblib`, `data/global_shap_importance.csv`, `data/champion_feature_interactions.csv`, `data/champion_summary.csv` — le LLM pourra appeler l'équivalent de `composition_fact_ranking` et transformer le classement en texte, sans ré-entraîner ni refaire tourner SHAP.

### Reste à faire (phase 3)

Rien — phase 3 terminée. La suite est la phase 4 (intégration du LLM).

### Piste future documentée : "Phase 3 v2" avec la Timeline (pas commencée)

Limite résiduelle acceptée (pas grave, mais réelle) : `maxLevelLeadLaneOpponent`/`maxCsAdvantageOnLaneOpponent` restent un peu "conséquence" (être en avance sur son adversaire de lane reflète déjà en partie que la lane se passe bien) — aucun seuil "avant 20 min" appliqué à `challenges` (agrégats sur des fenêtres floues côté Riot) ne peut totalement l'éliminer.

Solution documentée pour plus tard, si besoin : reconstruire `EARLY_GAME_FIELDS` depuis **Match-Timeline-V5** plutôt que `challenges`, pour avoir de vrais instantanés à un timestamp précis (ex: écart d'or à exactement 15:00) plutôt que des agrégats Riot flous. `RiotClient.get_match_timeline(match_id)` existe déjà (ajouté tôt dans la réflexion phase 3, jamais branché depuis qu'on a découvert que `challenges` suffisait). Plan : nouvelle table `timelines` (même schéma que `matches`) + une boucle d'enrichissement sur les 12 346 `match_id` déjà connus (pas une nouvelle collecte, ~4h à ~50 req/min) ; choisir des points de mesure fixes (10/15/20 min) ; recalculer or/XP/CS et écarts vs adversaire de lane (matching par rôle à coder nous-mêmes) depuis `participantFrames`, et des compteurs d'objectifs strictement filtrés par timestamp depuis `events` (ça redonnerait un équivalent fiable de `turretTakedownsBefore20Min`, que `turretPlatesTaken` ne peut plus offrir depuis le patch 26.01) ; puis ré-entraîner et comparer au modèle actuel (gardé comme référence, pas jeté).

Pas engagé maintenant : nettement plus de travail que `challenges` (raison initiale de l'avoir évité), payloads de timeline plus volumineux à stocker, logique de matching par lane à écrire de zéro — et pas nécessaire pour débloquer la phase 4 (le modèle actuel fonctionne et est bien calibré).

### Décision abandonnée : Factorization Machine sur embeddings de champions

Idée initiale : `biais global + poids individuel par champion + produit scalaire entre paires d'embeddings` (paires même équipe = synergie, équipes opposées = matchup/contre), embeddings appris de façon supervisée. Abandonnée après avoir identifié un vrai problème mathématique en l'implémentant : un produit scalaire est symétrique (`dot(A,B) = dot(B,A)`), mais quel camp est "bleu" ou "rouge" est arbitraire — un terme de contre symétrique ne peut donc porter **aucun signal prédictif** (il ne change pas de signe quand on inverse les équipes, contrairement au label). Le corriger proprement (embeddings offense/défense séparés, ou matrice bilinéaire antisymétrique apprise) ajoutait une complexité prématurée vu le dataset actuel (~20 matchs, qui overfitterait de toute façon). Combiné à l'envie de raisonner sur le déroulé de partie plutôt que sur les picks seuls, ça a motivé le pivot vers GBT+SHAP.

## Phase 4 — LLM ✅ Terminée

Fichiers : [`lol_assistant/game_plan.py`](../lol_assistant/game_plan.py), [`lol_assistant/live_game.py`](../lol_assistant/live_game.py), [`notebooks/04_llm_game_plan.ipynb`](../notebooks/04_llm_game_plan.ipynb).

**Décision** : Claude (API Anthropic) pour la génération du plan de jeu.

**Fait :**
- `composition_fact_ranking` **industrialisée** dans `lol_assistant/game_plan.py` (jusque-là seulement dans le notebook 3) — lit `data/global_shap_importance.csv` + `data/champion_feature_interactions.csv`, aucun appel modèle/SHAP nécessaire à l'usage. Au passage, filtre `champion`/`role` (présents par erreur dans les CSV exportés, pas de vrais faits de jeu — oubli du notebook 3, corrigé ici à l'usage plutôt qu'en ré-import du notebook).
- `build_game_plan_prompt` : construit le prompt à partir des classements des **deux** équipes — la nôtre ("à prioriser") et l'adverse ("à surveiller/contrer", même analyse légitime appliquée à leurs champions, pas un vrai signal de matchup entraîné).
- `generate_game_plan` : pipeline complet (classement + prompt + appel Claude). Modèle par défaut **Sonnet 5** (tâche de rédaction gabarisée, pas besoin du modèle le plus capable — `claude-opus-5` disponible en passant `model=...`).
- Dépendance `anthropic` ajoutée (`requirements.txt` et `pyproject.toml`, le package en a besoin directement).
- **Premier plan de jeu généré avec succès (2026-09-18)**, `ANTHROPIC_API_KEY` renseignée et testée. Résultat cohérent et actionnable — reprend bien les faits clés avec le bon champion associé (ex: Sylas sur l'avance de lane, Lulu sur vision/dragon) et une vraie logique de contre côté adverse. **Réserve à garder en tête** : Claude enrichit le texte avec de la connaissance générale de LoL au-delà de nos données pures (ex: un rôle attribué à un ADC pas franchement typique) — attendu d'un LLM, mais le plan final mélange signal statistique et connaissances générales, pas 100% traçable à nos données.
- **Validation des entrées ajoutée** : en testant l'assistant, j'ai découvert qu'un nom de champion mal orthographié (`"Arhi"` au lieu de `"Ahri"`) était accepté silencieusement — le champion invalide était juste ignoré, sans erreur, ce qui aurait donné un plan subtilement faux sans avertissement. `composition_fact_ranking` vérifie maintenant : exactement 5 champions, et chaque nom reconnu (sinon `ValueError`, avec suggestion du nom le plus proche via `difflib` — ex: "vouliez-vous dire 'Ahri' ?"). Validation à l'entrée du système (saisie utilisateur), pas de la défense excessive ailleurs.
- **Raccourci de saisie depuis une partie en cours (2026-09-18)** : `lol_assistant/live_game.py` ajoute `get_composition_from_active_game(riot_client, game_name, tag_line)`, qui résout un Riot ID en `puuid`, interroge Spectator-V5 (`RiotClient.get_active_game`, nouveau — routage **plateforme**, ex `euw1`, pas région, comme Match-V5) pour la partie en cours du joueur, et sépare les 10 participants en `your_team`/`enemy_team` via leur `teamId`. Le mapping `championId` numérique → nom de champion vient de Data Dragon (CDN statique Riot, pas de clé API requise), mis en cache dans `data/champion_id_map.json`. **Important** : une fois les 10 noms extraits, le reste de l'état de la partie (kills, or, timers, résultat) est jeté — ce n'est qu'un raccourci de saisie, pas une analyse de partie réelle ; ça ne change rien au contrat produit défini en phase 1 (composition hypothétique en entrée). `get_active_game` renvoie `None` si le joueur n'est pas en partie (cas normal), traduit en `ValueError` explicite par `get_composition_from_active_game`. Démo dans `notebooks/04_llm_game_plan.ipynb`, Concept 5.

**Reste à faire (phase 4) :**

Rien — phase 4 terminée. La suite est la phase 5 (interface).

## Phase 5 — Interface (CLI) ✅ Terminée

Fichier : [`lol_assistant/cli.py`](../lol_assistant/cli.py).

**Décision** : une **CLI** (ligne de commande) plutôt qu'un notebook consolidé — utilisable sans Jupyter, cohérente avec le reste du package. N'assemble que des briques déjà industrialisées (`game_plan.py`, `live_game.py`, `riot_client.py`), aucune nouvelle logique métier.

**Fait :**
- `main()` : propose deux modes — saisie manuelle des deux compositions (5 champions séparés par des virgules par équipe), ou récupération automatique depuis la partie en cours d'un joueur via un Riot ID (`pseudo#tag`, réutilise `get_composition_from_active_game` de la phase 4).
- Boucle de nouvelle tentative sur `ValueError` (composition invalide : mauvais nombre de champions, nom mal orthographié) — l'utilisateur peut corriger sa saisie sans relancer le programme.
- Erreurs réseau/API rattrapées avec un message clair plutôt qu'un traceback brut : `requests.exceptions.RequestException` (API Riot, ex. clé dev expirée — cas réel rencontré en testant sur une machine avec une clé de plus de 24h), `anthropic.AnthropicError` (API Claude), `FileNotFoundError` (artefacts `data/` absents — cas réel sur une machine sans la collecte locale, `data/` n'étant pas versionné).
- Point d'entrée `lol_assistant/__main__.py` (`python -m lol_assistant`) et script `lol-assistant` déclaré dans `pyproject.toml` (`[project.scripts]`, actif après `pip install -e .`).

**Validé en conditions réelles (2026-10-01)**, avec `data/` et un vrai appel Claude :
- Mode 1 (saisie manuelle) : plan de jeu généré de bout en bout, cohérent, avec les bons champions clés.
- Retry sur `ValueError` : une faute de frappe (`"Arhi"`) affiche le message avec suggestion, `n` à "Réessayer ?" quitte proprement, sans traceback.
- Chemin d'erreur réseau : testé avec une clé Riot réellement expirée — message clair (`Erreur d'appel à l'API Riot...`) au lieu d'un traceback brut.
- Mode 2 (partie en cours) **non re-testé via la CLI elle-même** à cause de cette clé expirée, mais `get_composition_from_active_game`, la fonction qu'il appelle, a déjà été validée sur une vraie partie en cours en phase 4. Risque résiduel jugé faible : la CLI ne fait qu'appeler cette fonction et afficher le résultat ou l'erreur.

**Tests** : la logique du pipeline (rate limiter, base SQLite, crawler snowball, classement des faits, construction du prompt, extraction d'une partie en cours) est couverte par une suite `pytest` sans réseau ni clé API, exécutée en intégration continue (GitHub Actions).
