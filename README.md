# Optimisation Sélection Produits — Agent IA HelloPro

Agent IA supervisé pour l'optimisation itérative du pipeline de sélection produits.

## Structure

```
optim-scoring/
├── .claude/settings.json      ← Config MCP (URLs à remplir par l'équipe tech)
├── .gitignore
├── CLAUDE.md                  ← Règles agent (IMMUTABLE)
├── EVAL.md                    ← Critères d'évaluation (IMMUTABLE)
├── BASELINE.json              ← Résultats itération 0 (IMMUTABLE après génération)
├── ITERATIONS.md              ← Journal de bord (APPEND-ONLY)
├── config/
│   ├── scoring.cypher         ← Requête scoring Neo4j (à fournir puis MODIFIABLE)
│   └── prompt_cleanup.txt     ← Prompt GPT-4o (à fournir puis MODIFIABLE)
├── scripts/
│   ├── run_scoring.py         ← Scoring via MCP Neo4j (généré par l'agent)
│   ├── run_cleanup.py         ← Nettoyage via API OpenAI (généré par l'agent)
│   ├── run_pipeline.py        ← Orchestrateur (généré par l'agent)
│   └── evaluate.py            ← Calcul métriques (généré par l'agent)
├── test_data/
│   └── parcours.json          ← 34 parcours audités (à structurer)
├── results/
│   └── iteration_XXX.json     ← Résultats par itération (générés)
└── reports/
    ├── diagnostic.md           ← Rapport phase 1 (généré)
    └── final.md                ← Rapport final (généré)
```

## Avant de démarrer

1. Remplir `.claude/settings.json` avec les URLs MCP internes
2. Coller le code Cypher dans `config/scoring.cypher`
3. Coller le prompt GPT-4o dans `config/prompt_cleanup.txt`
4. Structurer les 34 parcours dans `test_data/parcours.json`
5. Configurer `OPENAI_API_KEY` en variable d'environnement (ne PAS commiter)

## Utilisation

L'agent Claude Code exécute le pipeline depuis la racine du projet.
Les scripts dans `scripts/` sont générés par l'agent à l'étape E8.
Voir `CLAUDE.md` pour les règles et `EVAL.md` pour les critères.
