# Les 9 problèmes d'optimisation — HelloPro Scoring

> Source unique de vérité pour les hypothèses d'optimisation.
> Mis à jour à chaque itération selon les découvertes.

---

## Vue d'ensemble

Le pipeline de scoring HelloPro présente **9 problèmes identifiés** qui limitent la qualité de sélection des produits. Chaque problème a une priorité (sévérité) et une itération suggérée pour être traité.

**Score baseline** : 55.2% (voir BASELINE.json)
**Cible finale** : ≥80% conformité, 0 aberrations, 0 doublons

---

## Les 9 problèmes

### P1 — Absence caractéristique traitée comme neutre (pénalité manquante)
**Sévérité** : 🔴 CRITIQUE  
**Itération** : 1  
**Description** :
Quand une caractéristique requise est absente du produit, le score actuel = 0 (neutre).
Le système devrait appliquer une **pénalité** (ex: -0.5) plutôt que d'ignorer l'absence.
Cela permet aux produits avec fiches incomplètes de remonter indûment.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/scoring.cypher` (règles scoring)

**Métriques affectées** :
- Conformité ↓

---

### P2 — Produits hors catégorie remontent trop haut
**Sévérité** : 🔴 CRITIQUE  
**Itération** : 3  
**Description** :
Certains produits ne correspondent pas au besoin exprimé (ex: distributeur comptoir au lieu de sur-pied)
mais restent dans le top 5 recommandé. Le LLM reranker doit mieux filtrer ces cas.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/prompt_reranking.txt` (instructions LLM)

**Métriques affectées** :
- Conformité ↓

---

### P3 — LLM juge sur titre seul, ignore le descriptif
**Sévérité** : 🔴 CRITIQUE  
**Itération** : 2  
**Description** :
Le LLM analyse le titre du produit sans tenir compte de sa description technique.
Exemple: "Tracteur" remonte même si le type (vigneron vs standard) ne correspond pas au besoin.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/prompt_reranking.txt` (contexte fourni au LLM)

**Métriques affectées** :
- Conformité ↓
- Cohérence score/pertinence ↓

---

### P4 — 86% des produits en "Prix sur demande" (diagnostic)
**Sévérité** : ⚪ OBSERVATION  
**Itération** : Diagnostic (ne pas corriger)  
**Description** :
Manque massif de données pricing chez les fournisseurs.
Impact : estimatif imprécis, impossible de détecter aberrations prix.
À ignorer pour les itérations (limité par les données sources, pas par le code).

**Fichiers concernés** :
- Aucun (limitation données fournisseurs)

**Métriques affectées** :
- Aberrations prix (mesuré, pas corrigible)

---

### P5 — Zéro résultat pour certains parcours (bloquant)
**Sévérité** : 🟠 ÉLEVÉE  
**Itération** : 4  
**Description** :
Certains parcours ne retournent aucun produit conforme.
Cause possible: `liste_caracteristique` trop restritive, ou Cypher/logique matching trop stricte.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/scoring.cypher` (filtrages)
- RAG-HP-PUB: `src/matching_optim/matching_logic.py` (seuils)

**Métriques affectées** :
- Conformité ↓↓ (résultat 0%)

---

### P6 — Mélange produits neuf/occasion
**Sévérité** : 🟠 ÉLEVÉE  
**Itération** : 5  
**Description** :
Quand le parcours spécifie "Neuf", l'API retourne aussi des produits d'occasion.
Le filtre sur `etat_produit` ne fonctionne pas correctement.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/scoring.cypher` (filtre etat)

**Métriques affectées** :
- Conformité ↓
- Doublons (implicite)

---

### P7 — Doublons et surreprésentation fournisseur
**Sévérité** : 🔵 MODÉRÉE  
**Itération** : 6  
**Description** :
La même marque/fournisseur apparaît plusieurs fois dans le top 5 (ex: même modèle en deux variantes).
Le système doit diversifier par fournisseur.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/deduplication.py` (ou logique intégrée dans Cypher)

**Métriques affectées** :
- Doublons ↑
- Diversité fournisseurs ↓

---

### P8 — Caractéristiques discriminantes ignorées
**Sévérité** : 🔵 MODÉRÉE  
**Itération** : 7  
**Description** :
Certaines caractéristiques critiques (ex: largeur de passage pour minipelle)
ne sont pas prises en compte par le scoring, ou ont un poids insuffisant.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/scoring.cypher` (poids caractéristiques)

**Métriques affectées** :
- Conformité ↓
- Cohérence score/pertinence ↓

---

### P9 — Sélections trop restreintes ou hors sujet
**Sévérité** : 🔵 MODÉRÉE  
**Itération** : 8  
**Description** :
Inversement de P5: certains parcours retournent des produits non pertinents ou trop restrictifs.
Exemple: un filtre sur capacité exclut tous les produits viables.

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/scoring.cypher`
- RAG-HP-PUB: `src/matching_optim/matching_logic.py`

**Métriques affectées** :
- Conformité ↓
- Diversité fournisseurs ↓

---

## Suivi par itération

| Problème | Statut | Itération | Hypothèse | Raison décision |
|---|---|---|---|---|
| P1 | ⏳ PENDING | 1 | — | À attaquer en priorité (🔴 CRITIQUE) |
| P2 | ⏳ BACKLOG | 3 | — | Dépend de P3 |
| P3 | ⏳ BACKLOG | 2 | — | Dépend de P1 |
| P4 | ⏹️ SKIPPED | — | N/A | Limitation données, pas corrigible |
| P5 | ⏳ BACKLOG | 4 | — | Après P1-P3 |
| P6 | ⏳ BACKLOG | 5 | — | Après P1-P3 |
| P7 | ⏳ BACKLOG | 6 | — | Affinage deduplication |
| P8 | ⏳ BACKLOG | 7 | — | Fine-tuning poids |
| P9 | ⏳ BACKLOG | 8 | — | Derniers ajustements |

---

## Stratégie d'optimisation

1. **Iter 0** : Baseline établie (55.2%)
2. **Iter 1** : P1 — pénalité absence caractéristique
3. **Iter 2** : P3 — LLM considère descriptif
4. **Iter 3** : P2 — filtre produits hors catégorie
5. **Iter 4** : P5 — gestion zéro résultat
6. **Iter 5** : P6 — filtre neuf/occasion
7. **Iter 6** : P7 — deduplication/diversité
8. **Iter 7** : P8 — poids caractéristiques discriminantes
9. **Iter 8** : P9 — restriction/pertinence

**Checkpoints** :
- CP1 après iter 0 (baseline)
- CP2 après iter 3 (3 problèmes critiques)
- CP2bis après iter 6 (6 problèmes)
- CP3 après iter 8+ (plateau ou cibles atteintes)
- CP4 final (validation + merge prod)

---

## Notes importantes

- Chaque itération modifie **UN SEUL problème** (un seul fichier dans RAG-HP-PUB)
- P4 est marqué SKIPPED (diagnostic, pas corrigible par code)
- Les hypothèses spécifiques sont documentées dans ITERATIONS.md avant chaque modif
- En cas de régression → ROLLBACK immédiat, puis essayer autre hypothèse

