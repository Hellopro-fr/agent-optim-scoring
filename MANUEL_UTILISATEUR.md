# Manuel utilisateur — Dashboard HelloPro Scoring

> **À qui s'adresse ce document ?**
> Chefs de projet, product owners, équipe métier. Vous n'avez pas besoin de savoir coder.
> Ce manuel vous explique **à quoi sert l'outil, comment l'utiliser au quotidien, et comment interpréter ce que vous voyez**.

---

## 1. À quoi sert ce projet ?

Le moteur de recherche HelloPro propose à un acheteur une liste de produits correspondant à son besoin. Aujourd'hui, cette liste n'est pas toujours pertinente : produits hors catégorie, doublons, fiches techniques incomplètes, prix manquants…

Ce projet est un **outil d'amélioration continue** piloté par un agent IA (Claude). L'agent :

1. Lance une **batterie de 13 requêtes de test** ("parcours") représentatives des cas réels d'acheteurs.
2. Mesure la qualité des résultats renvoyés par l'API via **5 métriques** (voir §3).
3. Propose une modification ciblée pour résoudre un problème (P1 à P9).
4. Re-lance le test, compare à la référence ("baseline"), puis **garde** l'amélioration ou **annule** (rollback) si c'est pire.

Votre rôle en tant que non-dev : **piloter l'outil depuis le dashboard**, valider les paliers (checkpoints), et suivre la progression.

---

## 2. Accéder au dashboard

Le dashboard est une page web.

- **URL locale** (sur votre poste si le service tourne en local) : http://127.0.0.1:5050
- **URL VM** (installation serveur) : http://<ip-de-la-vm>:5050

> Si la page ne répond pas, contactez l'admin système : le service est peut-être arrêté. Vous n'avez rien à installer de votre côté.

Le dashboard a **3 pages** dans le menu de gauche :

| Page | À quoi ça sert |
|---|---|
| **Tableau de bord** | Vue d'ensemble : métriques actuelles + boutons pour lancer les itérations (originales + personnalisées) |
| **Iterations** | Historique détaillé de chaque essai (hypothèse, avant/après, décision) |
| **Problèmes** | Statut des 9 problèmes à résoudre (P1–P9) **+ ajout / modification / suppression de problèmes personnalisés** |

---

## 3. Les 5 métriques à surveiller

Ces 5 indicateurs mesurent la **qualité de la sélection produits**. Ils sont affichés en haut du Tableau de bord.

| Métrique | Ce que ça signifie | Cible |
|---|---|---|
| **Score global** | Note synthétique pondérée (la plus importante à regarder en premier). | ≥ 80% |
| **Conformité** | % de produits qui correspondent vraiment au besoin (bonne catégorie, bon sous-type, bon état neuf/occasion). **Poids double** dans le score global. | ≥ 80% |
| **Doublons** | Nombre de produits quasi-identiques dans la liste (même fournisseur + même descriptif). | 0 |
| **Diversité fournisseurs** | Nombre de fournisseurs différents sur l'ensemble des tests. Permet la mise en concurrence. | ≥ 3 |
| **Cohérence score** | Est-ce que les produits les mieux notés par l'API sont bien les plus pertinents ? | ≥ 0,5 |
| **Présence estimatif** | % de produits affichant un prix (vs "prix sur demande"). | ≥ 90% |

> Chaque carte a une petite icône **?** : passez la souris dessus pour relire la définition.

**Code couleur** : 🟢 cible atteinte · 🔴 cible non atteinte.

---

## 4. Les 9 problèmes (P1 à P9)

Chaque itération s'attaque à **un seul problème** identifié, dans un ordre défini.

| Code | Problème | Sévérité | Itération |
|---|---|---|---|
| P1 | Absence de caractéristique non pénalisée dans le scoring | 🔴 CRITIQUE | 1 |
| P3 | Le LLM juge sur le titre seul, ignore le descriptif technique | 🔴 CRITIQUE | 2 |
| P2 | Produits hors catégorie qui remontent trop haut | 🔴 CRITIQUE | 3 |
| P4 | 86% des prix en "Prix sur demande" | ⚪ OBSERVATION | *Diagnostic — pas traité* |
| P5 | Zéro résultat pour certains parcours | 🟠 ÉLEVÉE | 4 |
| P6 | Mélange produits neuf / occasion | 🟠 ÉLEVÉE | 5 |
| P7 | Doublons et sur-représentation d'un fournisseur | 🔵 MODÉRÉE | 6 |
| P8 | Caractéristiques discriminantes ignorées | 🔵 MODÉRÉE | 7 |
| P9 | Sélections trop restrictives ou hors sujet | 🔵 MODÉRÉE | 8 |

**Code couleur sévérité** : 🔴 CRITIQUE (à attaquer en premier) · 🟠 ÉLEVÉE · 🔵 MODÉRÉE · ⚪ OBSERVATION (diagnostic seulement).

> **P4 est un constat**, pas un problème qu'on peut corriger : il dépend des données fournisseurs, pas du code. Il reste affiché pour mémoire.

La page **Problèmes** du dashboard montre l'état de chaque problème (Backlog / En cours / Résolu).

### 4.1. Problèmes personnalisés (P10, P11…)

En plus des 9 problèmes d'origine, **vous pouvez ajouter vos propres problèmes** depuis la page Problèmes. Ils reçoivent automatiquement :

- Un **numéro** à partir de P10 (auto-incrémenté, jamais réutilisé même après suppression).
- Une **itération dédiée** à partir de 9 (iter 9, iter 10, iter 11…).
- Un nouveau **bouton** dans le bloc "Lancer une itération" du tableau de bord.

**Les 9 problèmes d'origine (P1-P9) sont immuables** : ils ne peuvent être ni modifiés ni supprimés. Seuls les problèmes que vous avez créés sont éditables.

Voir §5.4 pour la procédure de création.

---

## 5. Utiliser le dashboard — pas à pas

### 5.1. Première fois : lancer la baseline

La **baseline** (itération 0) est la mesure de référence sans aucune modification. Elle sert à comparer toutes les améliorations futures.

1. Ouvrir le **Tableau de bord**.
2. Une bannière jaune "**CP1 — Validation baseline requise**" s'affiche tant que la baseline n'a pas été posée.
3. Cliquer sur le bouton **Iter 0 — Baseline**.
4. Une fenêtre de confirmation apparaît :
   - *"Relancer la baseline va arrêter toutes les itérations en cours, réinitialiser le dashboard, archiver les logs et métriques…"*
   - Cliquer **OK** pour continuer (c'est normal au premier lancement : rien n'est encore archivé).
5. Une console noire s'ouvre. L'agent HelloPro va :
   - Appeler l'API sur les 13 parcours de test.
   - Calculer les métriques.
   - Remplir `BASELINE.json`.
6. Quand c'est terminé, le message "**Session terminée**" s'affiche.
7. Fermer la console. Les 5 métriques apparaissent sur le tableau de bord.

> **Important — Checkpoint CP1** : relisez les métriques. Elles doivent vous sembler cohérentes (pas de 0 partout, pas de 100% partout). Si c'est OK, vous pouvez enchaîner sur l'itération 1. Sinon, prévenez l'équipe tech.

### 5.2. Lancer une itération d'optimisation (1, 2, 3…)

1. Ouvrir le **Tableau de bord**.
2. Cliquer sur le bouton de l'itération voulue (ex. **Iter 1 — P1**).
3. Une console s'ouvre. L'agent va :
   - Formuler son hypothèse (ex. "Je pénalise l'absence de caractéristique de −0,25").
   - Modifier le code du service d'optimisation (sans toucher à la production).
   - Redémarrer l'API d'optimisation.
   - Relancer le test sur les 13 parcours.
   - Calculer les nouvelles métriques et les comparer à la baseline.
4. **L'agent peut vous poser une question** pendant le processus (le bouton clignote en orange "Attend réponse"). Une zone de texte apparaît en bas de la console : répondez comme dans un chat.
5. À la fin, l'agent annonce sa décision :
   - ✅ **GARDÉ** : le score s'est amélioré, la modification est conservée.
   - ❌ **ROLLBACK** : le score a régressé, la modification est annulée.
6. Fermer la console. Les métriques du tableau de bord se mettent à jour.

### 5.3. États des boutons d'itération

| Couleur / badge | État | Signification |
|---|---|---|
| ⚪ gris | **Jamais lancée** | Itération pas encore tentée |
| 🟢 vert + "OK" | **Terminée** | Itération bouclée, résultats disponibles |
| 🔵 bleu + "…" | **En cours** | L'agent est en train d'exécuter |
| 🟠 orange + "?" | **Attend réponse** | L'agent vous pose une question, cliquez pour ouvrir la console |

Les badges se rafraîchissent automatiquement toutes les 5 secondes.

### 5.4. Créer un problème personnalisé

1. Aller sur la page **Problèmes**.
2. Cliquer sur **+ Nouveau problème** en haut à droite.
3. Remplir le formulaire :

   | Champ | Obligatoire | Description |
   |---|---|---|
   | **Libellé** | ✅ | Titre court du problème (ex. "Latence API trop élevée") |
   | **Sévérité** | ✅ | CRITIQUE · ÉLEVÉE · MODÉRÉE (défaut) · OBSERVATION |
   | **Itération** | (auto) | Numéro attribué automatiquement, non modifiable |
   | **Description** | ✅ | Ce que vous observez, pourquoi c'est un problème, sur quel cas |
   | **Métriques affectées** | Facultatif | Cocher les métriques concernées dans la liste. Pour en ajouter une qui n'existe pas encore, la saisir dans "Ajouter une nouvelle métrique" puis cliquer **Ajouter** (elle est cochée automatiquement). |

4. Cliquer **Enregistrer**.

Le problème apparaît dans la grille avec le badge de sévérité coloré, et un nouveau bouton **Iter N — P<num>** est disponible sur le tableau de bord pour le lancer.

> Astuce : les nouvelles métriques que vous créez sont proposées dans la liste pour tous les problèmes suivants.

### 5.5. Modifier ou supprimer un problème personnalisé

Sur la carte d'un problème personnalisé, deux boutons :

- **Modifier** → rouvre le formulaire avec les valeurs existantes. Vous pouvez changer libellé / sévérité / description / métriques. Le numéro d'itération reste figé.
- **Supprimer** → après confirmation, retire le problème et son bouton du tableau de bord.

> **Les problèmes P1-P9 n'ont pas ces boutons** : ils sont immuables par contrat avec l'équipe tech.

> **Supprimer un problème ne libère pas son numéro d'itération** : si vous supprimez P10 (iter 9), le prochain problème créé sera P11 (iter 10), pas P10/iter 9 à nouveau. C'est pour éviter toute confusion avec des résultats précédemment calculés.

### 5.6. Lancer une itération sur un problème personnalisé

Exactement comme pour les itérations 1 à 8 (§5.2) :

1. Tableau de bord → cliquer sur le bouton **Iter N — P<num>** correspondant.
2. La console s'ouvre. L'agent reçoit automatiquement le contexte du problème (libellé, sévérité, description, métriques) — vous n'avez rien à lui redonner.
3. Il formule une hypothèse, modifie un fichier dans `graphoptim-service/matching`, relance le pipeline, compare les métriques, décide GARDÉ / ROLLBACK.
4. À la fin, le bouton passe au vert avec le badge "OK".

---

## 6. Les checkpoints (paliers de validation)

L'agent **ne peut pas tout faire seul**. Il s'arrête à des moments clés pour attendre votre accord :

| Checkpoint | Quand | Ce que vous devez faire |
|---|---|---|
| **CP1** | Après Iter 0 (baseline) | Vérifier que la baseline est cohérente avant d'autoriser les optimisations |
| **CP2** | Toutes les 3 itérations | Relire les 3 derniers essais, donner la direction pour les 3 suivants |
| **CP3** | Plateau 5+ itérations sans amélioration | Décider d'une nouvelle approche |
| **CP4** | Quand les cibles sont atteintes (ou blocage définitif) | Validation finale avant de passer la modif en production |

> Entre deux checkpoints, vous pouvez laisser l'agent tourner en autonomie.

---

## 7. Consulter l'historique

### Page Iterations

Affiche le journal complet (`ITERATIONS.md`) avec pour chaque essai :
- L'**hypothèse** testée et le problème attaqué (P1–P9).
- Le **fichier modifié** et un extrait avant / après.
- Le **tableau comparatif** des métriques (avant / après / différence).
- La **décision** (GARDÉ / ROLLBACK) et la raison.

### Page Problèmes

Un **tableau unique** liste tous les problèmes (P1-P9 officiels immuables + vos problèmes personnalisés P10, P11…). Colonnes :

| Colonne | Contenu |
|---|---|
| **Code** | P1 à P9 (officiels) ou P10+ (personnalisés) |
| **Libellé** | Titre du problème. Description complète visible au survol. |
| **Sévérité** | Badge coloré : 🔴 CRITIQUE · 🟠 ÉLEVÉE · 🔵 MODÉRÉE · ⚪ OBSERVATION |
| **Itération** | Numéro d'itération dédiée (ou `—` pour P4 diagnostic) |
| **État** | Backlog / En cours / Attend réponse / Résolu |
| **Métriques** | Métriques impactées. Si plus de 2, affichage "+N" (survoler pour la liste complète). |
| **Actions** | **Modifier** / **Supprimer** pour les personnalisés. Mention "immuable" pour P1-P9. |

En haut à droite, le bouton **+ Nouveau problème** ouvre le formulaire de création (voir §5.4).

En bas de la page, la **frise "Ordre d'attaque suggéré"** rappelle la séquence originale P1 → P3 → P2 → P5 → P6 → P7 → P8 → P9 (les itérations personnalisées s'enchaînent ensuite librement, sans ordre imposé).

---

## 8. Dialoguer avec l'agent

Dans la console, quand l'agent "attend une réponse", vous pouvez lui écrire en langage naturel.

### Ce que vous POUVEZ lui demander

- Formuler une hypothèse pour une itération ("Qu'est-ce que tu proposes pour P5 ?").
- Analyser les métriques d'une itération ("Pourquoi la conformité a baissé ?").
- Décider de garder ou d'annuler ("On garde ou on rollback ?").
- Clarifier l'état courant ("Où en est-on sur P3 ?").
- Expliquer la baseline ou l'ordre d'attaque.

### Ce que l'agent REFUSERA poliment

- Tout ce qui sort du protocole d'optimisation (poèmes, emails, code sans rapport).
- Modifier les fichiers protégés (EVAL.md, PROBLEMS.md, CLAUDE.md, BASELINE.json, parcours de test).
- Toucher à l'API de production (`graph-service/matching`) — il ne travaille **que** sur l'environnement d'optimisation `graphoptim-service/matching`.

> Les problèmes personnalisés (P10+) que vous créez depuis la page Problèmes sont stockés à part (`custom_problems.json`) et ne touchent donc **pas** au fichier protégé PROBLEMS.md.

Si vous recevez un refus, c'est normal. Reformulez dans le scope : "Analyse la dernière itération", "Propose l'hypothèse pour la suivante", etc.

---

## 9. Cas particuliers

### Re-cliquer sur une itération déjà lancée

- **Si l'itération est en cours** → la console reprend là où on en était.
- **Si elle est terminée** → on vous demande : *"Relancer (écrase l'historique) ou revoir la conversation (lecture seule) ?"*

### Re-cliquer sur Iter 0 (Baseline)

Relancer la baseline **réinitialise tout le dashboard** :
- Toutes les itérations repassent en état "Jamais lancée".
- Les logs et métriques précédents sont **archivés** (pas supprimés) dans `results/backup/<date>/` et `dashboard/logs/backup/<date>/`.

Une confirmation vous est demandée avant.

### La console reste bloquée sur "L'agent réfléchit…"

- Patience : certaines itérations peuvent prendre plusieurs minutes (13 appels API + évaluation).
- Si ça dure plus de 10 min sans message, fermez la console et prévenez l'équipe tech.

### "Connexion perdue"

Rafraîchissez la page. Si la session était en cours, elle reprendra automatiquement.

---

## 10. Questions fréquentes

**Q. Est-ce que je peux casser quelque chose en cliquant ?**
R. Non. L'agent est cadré : il ne touche **ni** aux fichiers de configuration immuables, **ni** à l'API en production. Même un rollback mal géré est annulé automatiquement côté code.

**Q. Que se passe-t-il si la conformité baisse après une itération ?**
R. L'agent déclenche un **ROLLBACK immédiat** : la modification est annulée. Le score revient à son niveau précédent. C'est le comportement normal, on apprend et on essaye autre chose.

**Q. Pourquoi seulement 13 parcours de test ?**
R. Ce sont 13 cas **audités manuellement** par l'équipe produit, choisis pour couvrir les cas typiques. C'est suffisant pour mesurer de manière fiable les 5 métriques.

**Q. Quand s'arrête-t-on ?**
R. Quand **toutes les cibles** de §3 sont atteintes, ou quand on constate un plateau définitif après plusieurs essais (CP4). À ce moment, l'équipe tech pousse la version optimisée en production.

**Q. Qui a le droit de modifier EVAL.md ou PROBLEMS.md ?**
R. Personne en cours de protocole. Ces fichiers sont la **source de vérité** : les modifier en cours de route invaliderait toutes les comparaisons. Seul un changement explicite validé avec l'équipe tech (et tracé) y touche.

**Q. Peut-on ajouter un problème qu'on a découvert en production ?**
R. Oui, via la page **Problèmes** → bouton **+ Nouveau problème** (§5.4). Ce nouveau problème est stocké à part (il ne modifie pas PROBLEMS.md) et génère automatiquement son propre bouton d'itération sur le tableau de bord.

**Q. Les problèmes personnalisés respectent-ils les checkpoints CP1-CP4 ?**
R. Oui, mais ils sont indépendants du plan original P1-P9. Si vous lancez iter 10 (un problème personnalisé) alors que iter 1-8 n'ont pas tourné, l'agent le signale mais n'est pas bloqué — les deux pistes sont comptabilisées séparément.

---

## 11. Qui contacter ?

| Sujet | Interlocuteur |
|---|---|
| Le dashboard ne répond pas / erreur technique | Admin système / équipe DevOps |
| Question sur une métrique ou un problème (P1–P9) | Équipe produit / dev HelloPro |
| Bug fonctionnel (bouton cassé, badge figé, etc.) | Équipe dev HelloPro |
| Validation d'un checkpoint (CP1–CP4) | Chef de projet (vous) |

---

*Document rédigé pour un utilisateur non-développeur. Pour les détails techniques (installation, configuration, règles internes de l'agent), voir `INSTALLATION_VM_ADMIN.md`, `CLAUDE.md`, `EVAL.md` et `PROBLEMS.md`.*
