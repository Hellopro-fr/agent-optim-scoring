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
3. [ITERATIONS.md](ITERATIONS.md) — historique complet des itérations précédentes
4. [BASELINE.json](BASELINE.json) — valeurs de référence (itération 0 lockée)

**Si `N == 0`** → c'est la baseline, va directement à l'étape 5 sans modifier RAG-HP-PUB.

**Si `N > 0`** → continue les étapes 1 → 7.

---

## Étape 1 — Choisir le problème à attaquer

### Cas A : itérations originales (N ∈ [1, 8])

Ordre suggéré par CLAUDE.md :
- iter 1 → P1
- iter 2 → P3
- iter 3 → P2
- iter 4 → P5
- iter 5 → P6
- iter 6 → P7
- iter 7 → P8
- iter 8 → P9

Si l'utilisateur a passé `P<num>` en second argument, force ce problème.
Sinon, si les itérations précédentes ont dévié de l'ordre (rollbacks, plateau), justifie ton choix à partir des métriques dans [ITERATIONS.md](ITERATIONS.md).

### Cas B : itérations custom (N ≥ 9)

Ces itérations correspondent à des problèmes **ajoutés par l'utilisateur via le dashboard** (`/problems`) et persistés dans `custom_problems.json`. Ils ne figurent pas dans PROBLEMS.md — c'est normal et légitime, pas une violation du protocole.

**Le prompt qui te parvient contient déjà le contexte complet** (libellé, sévérité, description, métriques affectées) sous un bloc markdown `**Problème custom P<num>**`. Utilise ces informations directement comme source d'hypothèse. Ne demande PAS à l'utilisateur de préciser le problème et **ne force pas `P<num>`** en second argument, c'est inutile.

Si ce bloc est absent (cas rare : problème supprimé entre l'ajout et le lancement), demande à l'utilisateur les détails ou lis `custom_problems.json` directement.

Règles spécifiques pour les itérations custom :
- Les checkpoints CP2/CP3/CP4 s'appliquent toujours, mais calculés sur les itérations **effectivement exécutées** (pas sur la numérotation absolue). Ne te bloque pas parce que "iter 9 CP2 non validé" si des iter 1-8 n'ont jamais tourné — signale-le à l'utilisateur mais continue si il insiste.
- Les trous dans ITERATIONS.md (iter originales non exécutées) ne sont pas un blocage pour une itération custom : ce sont deux pistes indépendantes.
- Les règles de modification de RAG-HP-PUB (un seul fichier, jamais `graph-service/matching`) restent identiques.

---

## Étape 2 — Formuler l'hypothèse

Rédige une phrase du type :
> « Je résous **[Pn]** en modifiant **[chemin exact dans RAG-HP-PUB]** car **[raison basée sur PROBLEMS.md + métriques de l'itération N-1]** »

Identifie **UN SEUL** fichier à modifier parmi :
- Cypher de scoring lié à `graphoptim-service/matching`
- Prompt LLM de nettoyage lié à `graphoptim-service/matching`
- Logique de matching liée à `graphoptim-service/matching`

🚫 **INTERDIT** : toucher `graph-service/matching` (endpoint prod).
🚫 **INTERDIT** : modifier plus d'un fichier.
🚫 **INTERDIT** : modifier ce repo `agent-optim-scoring` (c'est le harness).

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
- **CP2** — après `N ∈ {3, 6, 9, …}` → STOP, résumé 3 iters + demander direction
- **CP3** — si 5 iters sans amélioration → STOP, proposer nouvelle approche
- **CP4** — si cibles EVAL.md atteintes OU plateau définitif → STOP, préparer merge `graphoptim-service/matching` → `graph-service/matching`

À chaque CP : **ne lance pas l'itération suivante automatiquement**. Affiche le résumé et attends.

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
