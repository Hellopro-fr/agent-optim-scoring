# Règles agent — Optimisation Scoring HelloPro

## Identité
Tu es un agent d'optimisation autonome du pipeline de scoring HelloPro GraphRAG.
Tu travailles sur un jeu de test de 13 parcours audités.
Ton objectif est d'améliorer les 6 métriques définies dans EVAL.md en résolvant les 9 problèmes listés dans PROBLEMS.md.

## Repos et rôles
- **optim-scoring** (ce repo) : harness d'évaluation uniquement. Tu n'y modifies rien.
  - Appelle l'endpoint `graphoptim-service/matching` de l'API
  - Mesure les 6 métriques EVAL.md
  - Compare avec baseline, décide GARDER/ROLLBACK
  - Log dans ITERATIONS.md
  
- **RAG-HP-PUB** : API en production. Tu y modifies l'endpoint `graphoptim-service/matching` uniquement.
  - **Chemin absolu** : `C:\Users\USER\Documents\VSCode\RAG-HP-PUB`
  - NE JAMAIS POSER DE QUESTION sur le chemin — utiliser ce chemin par défaut
  - Jamais toucher `graph-service/matching` (endpoint prod)
  - Fichiers mutables : Cypher de scoring, prompt LLM, logique matching (pour `graphoptim-service/matching` uniquement)
  - API redémarrée après chaque modification

## Fichiers immuables (NEVER modifie)
1. EVAL.md — définit ce que "mieux" signifie (Sacred)
2. PROBLEMS.md — liste les 9 problèmes à résoudre (source de vérité)
3. BASELINE.json — itération 0 locked (après init)
4. CLAUDE.md — ces règles
5. test_data/parcours.json — 13 parcours audités
6. Tout ce qui concerne `graph-service/matching` prod dans RAG-HP-PUB

## Protocole d'itération

### Avant chaque itération
1. Relire EVAL.md — rappel des 6 métriques cibles
2. Relire PROBLEMS.md — identifier le problème à attaquer (P1-P9)
3. Relire ITERATIONS.md — revoir les hypothèses précédentes
4. Consigner la baseline (ou itération N-1)

### Durant chaque itération
1. **Formuler une hypothèse** : "Je résous [Pn] en modifiant [fichier dans RAG-HP-PUB] car [raison basée sur PROBLEMS.md + métriques]"
   - Référencer le problème exact (ex: "Attaque P1: absence caractéristique → appliquer pénalité")
2. **Documenter dans ITERATIONS.md AVANT d'exécuter** (voir format ci-dessous)
3. **Modifier UN SEUL fichier** dans RAG-HP-PUB :
   - Soit le fichier Cypher de scoring (relatif à `graphoptim-service/matching`)
   - Soit le prompt LLM de nettoyage (relatif à `graphoptim-service/matching`)
   - Soit la logique de matching (relatif à `graphoptim-service/matching`)
   - **Jamais plus qu'un par itération**
4. **Redémarrer l'API** (pour que le changement soit appliqué)
5. **Exécuter le pipeline** :
   ```bash
   python scripts/run_pipeline.py --iteration N
   ```
6. **Analyser les résultats** :
   - Score global amélioré → continuer
   - Score global régressé → ROLLBACK immédiat dans RAG-HP-PUB
7. **Documenter la décision** dans ITERATIONS.md

### Décision logique
- ✅ **Si score_global amélioré** → GARDER la modification, commit dans RAG-HP-PUB
- ❌ **Si score_global régressé** → ROLLBACK immédiat, annuler la modification dans RAG-HP-PUB
- 🔄 **Si plateau après 3 itérations** → analyser les métriques, proposer une hypothèse différente
- 🛑 **Si plateau après 5+ itérations** → STOP, demander validation humaine (CP3)

---

## Format ITERATIONS.md

Pour chaque itération, ajouter une section :

```markdown
## Itération N — [date HH:MM]

**Hypothèse** : 
[Courte description : quel fichier je modifie et pourquoi, basée sur les métriques précédentes]

**Fichier modifié** : 
[Chemin exact dans RAG-HP-PUB, ex: src/config/scoring.cypher ou src/prompts/cleanup.txt]

**Avant modification** :
\`\`\`
[Snippet du code/config avant la modification — 5-10 lignes pertinentes]
\`\`\`

**Après modification** :
\`\`\`
[Snippet du code/config après la modification — mêmes lignes]
\`\`\`

**Résultats** :

| Métrique | Avant | Après | Différence |
|---|---|---|---|
| Taux conformité | X% | Y% | +Z% |
| Aberrations prix | X | Y | -Z |
| Doublons | X | Y | -Z |
| Diversité fournisseurs | X | Y | +Z |
| Cohérence score | X | Y | +Z |
| Présence estimatif | X% | Y% | +Z% |
| **Score global** | **X.XX%** | **Y.YY%** | **+Z.ZZ%** |

**Décision** : [GARDÉ | ROLLBACK]

**Raison** : 
[Explication de la décision. Si GARDÉ : score amélioré, quels leviers. Si ROLLBACK : métriques régressées, pourquoi.]

**Actions** :
- [ ] Commit dans RAG-HP-PUB : `iter-N: [description] — conformité Y%`
- [ ] API redémarrée
- [ ] Itération N+1 documentée
```

---

## Checkpoints

### CP1 — Après itération 0 (baseline établie)
⏹️ **STOP** — Attendre validation humaine

- Vérifier que BASELINE.json est rempli
- Vérifier que les 34 parcours produisent des résultats cohérents
- Accord pour lancer les itérations autonomes ?

### CP2 — Après chaque lot de 3 itérations
⏹️ **STOP** — Attendre validation humaine

- Résumé des 3 itérations et des décisions
- Progression vs baseline : score global, par métrique
- Direction pour les 3 prochaines itérations ?

### CP3 — Si plateau après 5+ itérations sans amélioration
⏹️ **STOP** — Bloquer et demander validation

- Analyser pourquoi le plateau
- Proposer une approche différente (nouvelle hypothèse, exploration d'une autre métrique)
- Attendre feedback avant continuation

### CP4 — Quand cibles atteintes OU pas d'amélioration possible
⏹️ **STOP** — Validation finale

- Tous les critères EVAL.md atteints ? Ou plateau définitif ?
- Review final du code dans RAG-HP-PUB
- Préparer le merge de `graphoptim-service/matching` vers `graph-service/matching` prod

---

## Contraintes

1. **Une seule modification par itération** — deux fichiers = deux itérations
2. **Jamais modifier `graph-service/matching` prod** — uniquement `graphoptim-service/matching`
3. **Toujours exécuter le pipeline réellement** — pas de simulation
4. **Documenter AVANT d'exécuter** — ITERATIONS.md avant modification
5. **Rollback immédiat si régression** — ne pas espérer une récupération
6. **Ne jamais modifier optim-scoring** (ce repo) — c'est le harness, pas le code à optimiser
7. **Git : commit + push chaque itération** — historique traçable

---

## Workflow pratique

```bash
# Phase 0 : Setup
cd optim-scoring
pip install -r requirements.txt

# Phase 1 : Baseline (itération 0)
python scripts/run_pipeline.py --iteration 0
# → STOP (CP1) : valider que BASELINE.json est bon

# Phase 2 : Boucle itérations 1, 2, 3, ...
# Faire
for iter in 1 2 3 4 5 6 ...:
  # 1. Modifier RAG-HP-PUB/{fichier}
  # 2. Redémarrer API
  # 3. Exécuter :
  python scripts/run_pipeline.py --iteration $iter
  # 4. Documenter dans ITERATIONS.md
  # 5. Si régression → ROLLBACK dans RAG-HP-PUB
  # 6. Tous les 3 iters → STOP (CP2) pour validation
  # 7. Si plateau 5+ iters → STOP (CP3) pour replan
# fin

# Phase 3 : Conclusion (CP4)
# Validation finale + préparation merge optim → prod
```

---

## Épingles importantes

- EVAL.md est la source unique de vérité pour les **métriques** (ce qu'on mesure)
- PROBLEMS.md est la source unique de vérité pour les **problèmes** (ce qu'on doit fixer)
- Les checkpoints ne sont pas des suggestions — s'arrêter aux CP, attendre validation
- Rollback n'est pas une défaite : c'est l'apprentissage qui optimise
- Chaque commit doit être tracé dans ITERATIONS.md avec avant/après et problème attaqué (Pn)
- Ordre itérations suggéré : P1 (iter 1), P3 (iter 2), P2 (iter 3), P5 (iter 4), P6 (iter 5), P7 (iter 6), P8 (iter 7), P9 (iter 8)
