---
description: Lance l'itération N du protocole d'optimisation scoring HelloPro (CLAUDE.md)
argument-hint: <N> [problem]
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
---

# Itération $ARGUMENTS — Protocole d'optimisation scoring HelloPro

Tu exécutes **l'itération N** du protocole défini dans [CLAUDE.md](CLAUDE.md).
Argument reçu : `$ARGUMENTS` (format : `N` ou `N P<num>` pour forcer un problème).

---

## Étape 0 — Pré-vol (OBLIGATOIRE avant toute action)

Lis dans cet ordre et résume ce que tu comprends :

1. [EVAL.md](EVAL.md) — les 6 métriques cibles (source de vérité des métriques)
2. [PROBLEMS.md](PROBLEMS.md) — les 9 problèmes P1–P9 (source de vérité des problèmes)
3. [ITERATIONS.md](ITERATIONS.md) — **historique PROD uniquement** (fichier reset au 2026-04-21)
4. [BASELINE.json](BASELINE.json) — valeurs de référence (itération 0 PROD)

**`git log` uniquement avec filtre `--grep="^iter-"`** : les seuls commits d'itération commencent par `iter-N:`. Tous les autres commits (setup Dockerfile, docker-compose, fix, refactor, docs, etc.) **doivent être ignorés**.

Commande autorisée : `git log --oneline --grep="^iter-"`
Commande interdite : `git log` (sans filtre) — capturerait les commits de setup/config.

`ITERATIONS.md` reste la source principale (plus riche). Voir CLAUDE.md §"Point de départ PROD — 2026-04-21".

**Si `N == 0`** → c'est la baseline, va directement à l'étape 5 sans modifier RAG-HP-PUB.

**Si `N > 0`** → continue les étapes 1 → 7.

---

## Étape 1 — Identifier et déclarer le problème à attaquer

### Cas A : itérations originales (N ∈ [1, 8])

**Verrouillage problème/itération** (cf. CLAUDE.md §"Verrouillage problème/itération") — le `Pn` attaqué est **épinglé** et ne change pas de l'initiative de l'agent. Procédure stricte :

1. **Lire `ITERATIONS.md`** — récupérer le **dernier bloc d'itération** (N-1) et en extraire :
   - Le `Pn` attaqué
   - La décision finale (GARDÉ / ROLLBACK)
   - Le numéro de l'essai (compteur par `Pn`)

2. **Déterminer le `Pn` à attaquer pour l'itération N** selon la règle :
   - Si l'utilisateur a passé `P<num>` en second argument → force ce problème (**override humain, priorité absolue**).
   - Sinon, appliquer la règle de verrouillage :

   | Dernière décision (iter N-1) | Métrique cible `Pn` atteinte ? | Action pour iter N |
   |---|---|---|
   | **ROLLBACK** | n/a | **Rester sur le même `Pn`**, proposer un angle différent |
   | **GARDÉ** | ✅ atteinte | Passer au `Pn` suivant selon l'ordre ci-dessous |
   | **GARDÉ** | ❌ pas encore | **Rester sur le même `Pn`**, amplifier/consolider la modif |

3. **Ordre des priorités** (utilisé uniquement quand on passe à un `Pn` suivant) :
   - P1 → P3 → P2 → P5 → P6 → P7 → P8 → P9

4. **Compteur d'essais par `Pn`** :
   - Essai 1 = première tentative sur ce `Pn`
   - Essai K = K-ième tentative (après K-1 ROLLBACK sur le même `Pn`)
   - Le compteur **repart à 1** dès qu'on change de `Pn`

5. **Escalade automatique** — Si la dernière itération est la **3ᵉ ROLLBACK consécutive** sur le même `Pn` :
   🚫 **NE PAS proposer de nouvelle hypothèse automatiquement**.
   ⏹️ **Déclencher CP-Escalade** (cf. §"Checkpoints") : afficher un résumé des 3 hypothèses testées, leur échec, et **attendre la décision humaine** (continuer `Pn` / plafond atteint / pause sourcing).

### Cas B : itérations custom (N ≥ 9)

Ces itérations correspondent à des problèmes **ajoutés par l'utilisateur via le dashboard** (`/problems`) et persistés dans `custom_problems.json`. Ils ne figurent pas dans PROBLEMS.md — c'est normal et légitime, pas une violation du protocole.

**Le prompt qui te parvient contient déjà le contexte complet** (libellé, sévérité, description, métriques affectées) sous un bloc markdown `**Problème custom P<num>**`. Utilise ces informations directement comme source d'hypothèse. Ne demande PAS à l'utilisateur de préciser le problème et **ne force pas `P<num>`** en second argument, c'est inutile.

Si ce bloc est absent (cas rare : problème supprimé entre l'ajout et le lancement), demande à l'utilisateur les détails ou lis `custom_problems.json` directement.

Règles spécifiques pour les itérations custom :
- Le checkpoint CP4 s'applique toujours (cibles atteintes ou plateau définitif déclaré par l'humain). Les itérations custom suivent la même logique que les iter originales, sans contrainte supplémentaire de numérotation.
- Les trous dans ITERATIONS.md (iter originales non exécutées) ne sont pas un blocage pour une itération custom : ce sont deux pistes indépendantes.
- Les règles de modification de RAG-HP-PUB (jamais `graph-service/matching`) restent identiques.

### Déclaration obligatoire du problème (avant de passer à l'Étape 2)

**Avant de commencer l'Étape 2**, écris explicitement dans ta réponse un bloc de déclaration au format suivant, encadré par un séparateur visuel :

```
═══════════════════════════════════════════════════════
ÉTAPE 1 — PROBLÈME IDENTIFIÉ
═══════════════════════════════════════════════════════
Itération       : N
Problème        : P<num> — <libellé court>
Essai           : K/3 sur Pn  (K incrémenté après chaque ROLLBACK consécutif)
Dernière iter   : iter N-1 → <GARDÉ | ROLLBACK> sur <P…>
Sévérité        : <élevée | modérée | faible>
Justification   : <1-2 phrases — pourquoi ce Pn à cette itération,
                   en cohérence avec la règle de verrouillage>
═══════════════════════════════════════════════════════
```

⚠️ **Si `Essai` = 3/3 et décision N-1 = ROLLBACK** → ne PAS continuer, déclencher CP-Escalade.

🚫 **Interdit** : passer à l'Étape 2 sans avoir écrit ce bloc. Le bloc rend le problème lisible pour l'humain qui supervise et sert d'ancrage pour le self-challenge de l'Étape 2b.

---

## Étape 2a — Formuler l'hypothèse initiale

Après avoir écrit le bloc "ÉTAPE 1 — PROBLÈME IDENTIFIÉ", écris le bloc "ÉTAPE 2a — HYPOTHÈSE INITIALE" avec le même séparateur visuel :

```
═══════════════════════════════════════════════════════
ÉTAPE 2a — HYPOTHÈSE INITIALE
═══════════════════════════════════════════════════════
Hypothèse       : Je résous P<num> en modifiant <chemin exact dans RAG-HP-PUB>
                  car <raison basée sur PROBLEMS.md + métriques de l'iter N-1>.
Fichier cible   : <chemin absolu dans RAG-HP-PUB/apps-microservices/graph-rag-api-recherche-optim-service/>
Type de modif   : <Cypher scoring | Prompt LLM cleanup | Logique matching | Config>
Impact attendu  : <+X% conformité | -Y doublons | etc. (estimation chiffrée)>
═══════════════════════════════════════════════════════
```

Identifie **UN SEUL** fichier à modifier parmi :
- Cypher de scoring lié à `graphoptim-service/matching`
- Prompt LLM de nettoyage lié à `graphoptim-service/matching`
- Logique de matching liée à `graphoptim-service/matching`

🚫 **INTERDIT** : toucher `graph-service/matching` (endpoint prod).
🚫 **INTERDIT** : modifier ce repo `agent-optim-scoring` (c'est le harness).

---

## Étape 2b — Self-challenge de l'hypothèse (max 2 cycles)

Avant de présenter l'hypothèse au user, **challenge-toi toi-même**. Objectif : confronter ton hypothèse au **code réel** et au **problème exact** pour valider ou reformuler.

**Tools autorisés pendant 2b** : `Read`, `Glob`, `Grep` uniquement (pour lire et explorer le code dans RAG-HP-PUB).
🚫 **Interdits pendant 2b** : `Edit`, `Write`, `Bash`, `NotebookEdit` (pas encore d'action sur le code).

### Procédure pour CHAQUE cycle de self-challenge

Écris explicitement dans ta réponse l'en-tête du cycle :
```
=== SELF-CHALLENGE CYCLE X/2 ===
```

Puis effectue l'analyse structurée en liste ✓/⚠️ :

**1. Lecture du fichier cible**
- `Read` du fichier que tu as identifié dans l'hypothèse
- Si `Read` échoue (fichier inexistant, permission, mauvais chemin) → **hypothèse invalide par défaut** → `🔄 À REFORMULER` (mauvais ciblage, retrouve le bon chemin via `Glob`/`Grep`)
- Si le fichier existe mais le code actuel contient déjà ta modif proposée → `🔄 À REFORMULER`

**2. Confrontation au code réel**
- ✓ ou ⚠️ : le fichier existe bien au chemin indiqué
- ✓ ou ⚠️ : le code actuel n'a pas déjà la modif proposée
- ✓ ou ⚠️ : la modification est structurellement cohérente (pas un copier-coller hors contexte, pas une rupture de convention)
- ✓ ou ⚠️ : les coefficients/paramètres sont alignés avec la convention existante (pas une valeur arbitraire qui clasherait)

**3. Confrontation au problème PROBLEMS.md**
- ✓ ou ⚠️ : l'hypothèse adresse la cause racine (pas juste un symptôme)
- ✓ ou ⚠️ : tu n'as pas confondu avec un autre Pn voisin
- ✓ ou ⚠️ : l'impact attendu sur les métriques EVAL.md est plausible

**4. Questions challengeantes**
- ✓ ou ⚠️ : "Y a-t-il une approche plus simple/ciblée que celle-ci ?"
- ✓ ou ⚠️ : "Est-ce que cette modif peut casser un autre comportement (side-effect) ?"

**5. Décision explicite** — écris une de ces 2 lignes :
- `✅ HYPOTHÈSE VALIDÉE PAR SELF-CHALLENGE` → passe à l'Étape 2c (checkpoint humain)
- `🔄 HYPOTHÈSE À REFORMULER` → reformule ci-dessous avec une phrase type "Je résous [Pn] en modifiant..." puis relance un nouveau cycle (2/2)

### Règle stricte : maximum 2 cycles

- Cycle 1 validé → passe directement à 2c
- Cycle 1 à reformuler → Cycle 2
- Cycle 2 validé → passe à 2c
- Cycle 2 toujours à reformuler → **STOP au 2e cycle**. Présente la meilleure formulation trouvée avec un avertissement :
  > ⚠️ **SELF-CHALLENGE NON CONCLUANT (2 cycles épuisés)**
  > L'hypothèse ci-dessus reste la meilleure formulation trouvée, mais mon auto-critique n'est pas complètement satisfaite. Validation humaine particulièrement critique ici.
  
  Puis passe quand même à 2c (le user décidera en connaissance de cause).

---

## Étape 2c — Checkpoint humain (Validation de l'hypothèse, OBLIGATOIRE)

Après le self-challenge (2b), **ARRÊTE IMMÉDIATEMENT**. Ne passe PAS à l'étape 3.

🚫 **RÈGLE ABSOLUE** : à partir d'ici, n'utilise **AUCUN tool** (ni Edit, ni Write, ni Bash, ni Read, ni Grep, ni Glob, ni NotebookEdit). Termine ta réponse après le message ci-dessous.

Écris ce message final, puis termine ta réponse :

> ⏸️ **Hypothèse proposée — J'attends ta validation**
>
> Réponds :
> - **`GO`** (ou `ok`, `oui`, `valide`, `continue`, `proceed`) → je passe à l'étape 3 (documentation + modification + pipeline)
> - **`NO`** (ou `stop`, `rejette`, `non`, `abort`) → j'abandonne cette hypothèse, aucune modification faite
> - **Commentaire libre** (ex: « essaye plutôt X », « change le coefficient », « attaque un autre problème ») → je reformule l'hypothèse selon ton feedback

### Traitement de la réponse utilisateur (au tour suivant)

Quand l'utilisateur répond via le chat du dashboard :

1. **Si la réponse contient un mot de validation** (`GO`, `ok`, `oui`, `valide`, `continue`, `proceed`, `yes`, etc.) :
   - Continue avec l'Étape 3 (documentation dans ITERATIONS.md + modification dans RAG-HP-PUB + pipeline).
   - Ne repose pas la question, passe à l'action directement.

2. **Si la réponse contient un mot de rejet** (`NO`, `stop`, `rejette`, `non`, `abort`, `abandonne`, etc.) :
   - Écris : « Itération N abandonnée par l'utilisateur. Aucune modification effectuée dans RAG-HP-PUB. »
   - Termine l'itération sans rien toucher (pas de commit, pas de modif fichier, pas de pipeline).
   - Ne passe pas à l'Étape 3.

3. **Sinon (commentaire libre)** :
   - Interprète le commentaire comme un feedback sur l'hypothèse.
   - **Reformule** une nouvelle hypothèse qui tient compte du feedback (retour à l'Étape 2a).
   - **Relance un nouveau self-challenge (2b)** avec le compteur de cycles **remis à zéro** (2 nouveaux cycles possibles). Chaque feedback utilisateur = nouveau contexte = nouvelle fenêtre d'auto-critique.
   - Re-applique le checkpoint (2c) avec l'hypothèse post-challenge — autant de cycles user que nécessaire jusqu'à `GO` ou `NO`.

---

## Étape 3 — Documenter AVANT d'exécuter

Ajoute une section dans [ITERATIONS.md](ITERATIONS.md) au format exact défini dans [CLAUDE.md](CLAUDE.md#format-iterationsmd) :

```markdown
## Itération N — [YYYY-MM-DD HH:MM]

**Hypothèse** : ...
**Fichier modifié** : [chemin exact dans RAG-HP-PUB]
**Avant modification** :
​```
[5-10 lignes pertinentes avant]
​```
**Après modification** :
​```
[mêmes lignes après]
​```
**Résultats** : (à remplir après exécution)
**Décision** : (à remplir après analyse)
```

Capture le snippet **AVANT** dès maintenant (lecture du fichier cible dans RAG-HP-PUB).

---

## Étape 4 — Appliquer la modification dans RAG-HP-PUB

1. Éditer le fichier identifié (UN SEUL).
2. Demander à l'utilisateur de **redémarrer l'API** si le redémarrage n'est pas automatique — ou exécuter le script de restart si disponible.
3. Capturer le snippet **APRÈS** dans [ITERATIONS.md](ITERATIONS.md).

---

## Étape 5 — Exécuter le pipeline

```bash
python scripts/run_pipeline.py --iteration $ARGUMENTS
```

⚠️ **Jamais de simulation** — toujours l'exécution réelle.
Si le script échoue, diagnostique et corrige avant de continuer.

---

## Étape 6 — Analyser et décider

### ⚠️ Rappel — catalogue vivant

Entre iter N-1 et iter N, les produits remontés par l'API peuvent différer
(contrats fournisseurs, désactivations, nouveaux produits). Règle d'interprétation :

- **Analyser les métriques agrégées**, pas les IDs de produits individuels
- **Marge de bruit catalogue : ±2-3%** → en dessous, ne pas conclure à un effet
  de ta modif (probablement du bruit catalogue)
- **Au-dessus de ±5%** → effet réel probable de la modif Cypher/prompt. Entre
  3% et 5% : zone grise, note l'observation sans conclusion ferme.

Voir `CLAUDE.md` §"Volatilité du catalogue produits" pour le détail.

---

Compare les 5 métriques avec l'itération précédente (ou la baseline pour iter 1) :

| Métrique | Avant | Après | Δ |
|---|---|---|---|
| Taux conformité | … | … | … |
| Doublons | … | … | … |
| Diversité fournisseurs | … | … | … |
| Cohérence score | … | … | … |
| Présence estimatif | … | … | … |
| **Score global** | **…** | **…** | **…** |

Décision :
- ✅ **score_global amélioré** → `GARDÉ`, commit RAG-HP-PUB `iter-N: [desc] — conformité Y%`
- ❌ **score_global régressé** → `ROLLBACK` **immédiat** dans RAG-HP-PUB (annuler le diff de l'étape 4)
- 🔄 **plateau 3 iters** → changer d'angle, noter le replan dans ITERATIONS.md

---

## Étape 7 — Mettre à jour ITERATIONS.md

Compléter les sections `Résultats`, `Décision`, `Raison`, `Actions` du bloc créé à l'étape 3.
Cocher les cases `Actions` au fur et à mesure (commit, API redémarrée).

---

## Checkpoints (STOP obligatoire)

- **CP1** — après itération `0` → STOP, attendre validation humaine sur BASELINE.json
- **CP-Hypothèse** — à chaque itération N > 0, après l'Étape 2c → STOP, attendre `GO` / `NO` / commentaire humain (voir §"Étape 2c — Checkpoint humain")
- **CP-Escalade** — détecté à l'Étape 1 quand la 3ᵉ tentative consécutive sur le même `Pn` vient d'être ROLLBACK → STOP **avant de formuler toute nouvelle hypothèse**. Présente à l'humain :
  - Le `Pn` concerné + métrique cible vs valeur actuelle
  - Résumé des 3 hypothèses testées + raison de chaque ROLLBACK
  - Attendre la décision : **(a) continuer `Pn`** (nouvel angle à proposer) / **(b) plafond atteint** (passer au `Pn` suivant) / **(c) pause sourcing** (cf. CLAUDE.md §"Absence de produit…")
  - 🚫 L'agent **n'a jamais le droit** de basculer sur un autre `Pn` sans réponse humaine.
- **CP4** — si cibles EVAL.md atteintes OU plateau définitif (déclaré par l'humain) → STOP, préparer merge `graphoptim-service/matching` → `graph-service/matching`

À CP1, CP-Escalade et CP4 : **ne lance pas l'itération suivante automatiquement**. Affiche le résumé et attends.

---

## Contraintes dures (rappel)

1. Une seule modification par itération
2. Jamais toucher `graph-service/matching` prod
3. Pipeline exécuté réellement, pas simulé
4. Documentation **AVANT** modification
5. Rollback immédiat si régression
6. Ne jamais modifier `agent-optim-scoring/` (ce repo)
7. Commit + push après chaque itération GARDÉE

---

**Commence maintenant par l'étape 0.** Si `$ARGUMENTS` est vide ou invalide, demande le numéro d'itération à l'utilisateur avant toute action.
