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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`penalite-uniforme-trop-forte`) : pénalité unique appliquée à tous
  les types de caractéristiques absentes (critique + secondaire), élimine des
  conformes à fiches incomplètes.
- **Mode B** (`penalite-uniforme-trop-faible`) : pénalité absente ou trop douce,
  les fiches vides remontent indûment.
- **Mode C** (`asymetrie-critique-secondaire`) : la pénalité actuelle ne distingue
  pas critique vs secondaire, alors que les deux ont des poids différents.

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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`hors-categorie-structurel`) : sous-type fonctionnel incompatible
  (pont enfoui ≠ pont colonnes, distributeur comptoir ≠ sur-pied). Discriminateur
  lisible dans titre ou description.
- **Mode B** (`hors-categorie-numerique`) : produit dans la bonne famille mais
  hors plage de spécification (puissance, capacité, tonnage). Discriminateur
  dans les caractéristiques techniques.
- **Mode C** (`tolerance-limite`) : valeur en limite de tolérance numérique
  (ex : 90-110 % vs 80-120 %), produit qui aurait dû être Score 2 et passe
  en Score 4.

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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`description-blind`) : discriminateur présent dans `description`,
  absent du `titre`, le LLM rate l'info parce qu'il s'arrête au titre.
  Exemple : titre "Tracteur" / description "Conçu pour vignobles étroits" /
  besoin "tracteur agricole standard" → faux positif Score 4.
- **Mode B** (`title-correct`) : discriminateur présent dans `titre`,
  description vide ou laconique, le LLM utilise correctement le titre.
  Exemple : titre "Tracteur Vigneron Xtra 60" / description vide → vrai
  négatif Score 1. **Ne pas dégrader ce mode.**
- **Mode C** (`data-gap`) : discriminateur absent partout (titre + description +
  caractéristiques). Hors périmètre prompt → relève de la caractérisation amont.

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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`cypher-strict`) : les filtres Cypher sont trop stricts et éliminent
  tous les candidats avant scoring. Levier : assouplir les seuils.
- **Mode B** (`caracteristique-mismatch`) : la `liste_caracteristique` du parcours
  ne correspond à aucune fiche produit (problème de mapping
  questions → caractéristiques en amont). Levier : revoir le mapping ou
  introduire un fallback.
- **Mode C** (`corpus-gap`) : la catégorie n'est réellement pas couverte par
  les fournisseurs dans la base. Hors périmètre prompt → relève du sourcing
  fournisseur ou du parcours UX résultats faibles.

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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`filtre-defaillant`) : filtre `etat_produit` ne s'applique pas
  côté Cypher. Levier : corriger ou ajouter le filtre.
- **Mode B** (`question-non-posee`) : le parcours n'a pas demandé l'état à
  l'acheteur, donc pas d'input pour filtrer. Levier : fallback "neuf par défaut".
- **Mode C** (`mapping-defaillant`) : la valeur est demandée mais mal mappée
  vers le champ `etat_produit` côté API. Levier : corriger le mapping.

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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`dedup-absente`) : aucune logique de déduplication appliquée.
  Levier : ajouter une règle "max N par fournisseur".
- **Mode B** (`dedup-trop-large`) : dedup sur produit identique uniquement,
  ne traite pas les variantes du même fournisseur. Levier : élargir la
  définition du "même produit".
- **Mode C** (`top-N-trop-restreint`) : déduplication réduit à si peu de
  produits qu'on retombe sur le même fournisseur dominant la catégorie.
  Levier : élargir le pool initial avant dedup.

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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`poids-faible`) : la caractéristique est bien intégrée dans le
  scoring mais sous-pondérée. Levier : repondérer.
- **Mode B** (`caracteristique-absente-prompt`) : la caractéristique n'est pas
  exposée au LLM reranker (manque dans la structure d'entrée). Levier :
  enrichir l'input du reranker.
- **Mode C** (`extraction-failed`) : la caractéristique est demandée à l'acheteur
  mais absente de la majorité des fiches produit côté fournisseur.
  Hors périmètre prompt → relève de la caractérisation amont.

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

**Modes d'échec hypothétiques** (grille FMA, sans préjugé sur leur fréquence) :
- **Mode A** (`filtre-dur-trop-strict`) : un filtre Cypher exclut des produits
  viables sur un cas-limite de seuil. Levier : assouplir le seuil ou passer
  en filtre souple.
- **Mode B** (`scoring-trop-selectif`) : le scoring discrimine trop fortement,
  écart important entre top-1 et reste, peu de candidats remontent. Levier :
  réduire l'amplitude des pondérations.
- **Mode C** (`force-hors-sujet`) : trop peu de candidats valables au départ,
  le système comble la sélection avec du hors sujet pour atteindre N résultats.
  Levier : score plancher de qualité (mieux vaut afficher 2 résultats que 5
  dont 3 hors sujet).

**Fichiers concernés** :
- RAG-HP-PUB: `src/matching_optim/scoring.cypher`
- RAG-HP-PUB: `src/matching_optim/matching_logic.py`

**Métriques affectées** :
- Conformité ↓
- Diversité fournisseurs ↓

---

## Suivi par itération

> La FMA est désormais **universelle** (cf. CLAUDE.md §"Règle Failure Mode
> Analysis (FMA)") : exécutée systématiquement avant la 1ʳᵉ itération de
> chaque P. La colonne "FMA requise" n'a donc plus lieu d'être.

| Problème | Statut | Itération | Hypothèse | Raison décision |
|---|---|---|---|---|
| P1 | ⏳ PENDING | 1 | — | À attaquer en priorité (🔴 CRITIQUE) |
| P2 | ⏳ BACKLOG | 3 | — | Après P1, P3 |
| P3 | 🔄 EN COURS | 2 | — | 2 rollbacks essai 1 et 2 |
| P4 | ⏹️ SKIPPED | — | N/A | Limitation données, pas corrigible |
| P5 | ⏳ BACKLOG | 4 | — | Après P1-P3 |
| P6 | ⏳ BACKLOG | 5 | — | — |
| P7 | ⏳ BACKLOG | 6 | — | — |
| P8 | ⏳ BACKLOG | 7 | — | — |
| P9 | ⏳ BACKLOG | 8 | — | — |

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

**Checkpoints** (cf. CLAUDE.md §"Checkpoints") :
- **CP1** après iter 0 (baseline établie, validation humaine)
- **CP-Hypothèse** à chaque itération N > 0 (validation humaine de l'hypothèse avant modification RAG-HP-PUB)
- **CP-Escalade** après 3 ROLLBACK consécutifs sur le même iter (pas de synthèse, pas d'abandon — proposer une 4ᵉ hypothèse ou demander une piste à l'utilisateur)
- **CP4** final (cibles EVAL.md atteintes ou plateau définitif déclaré par l'humain → préparer merge prod)

---

## Notes importantes

- Chaque itération applique **UNE seule modification atomique** (cf. CLAUDE.md §"Règle anti-bundling")
- Pour **tous les Pn**, une **FMA est exécutée avant la 1ʳᵉ itération** (universelle, cf. CLAUDE.md §"Règle Failure Mode Analysis (FMA)"). Le verdict (mono-cause / multi-modes / hors périmètre) est dérivé des données et conditionne le levier autorisé.
- P4 est marqué SKIPPED (diagnostic, pas corrigible par code)
- Les hypothèses spécifiques sont documentées dans ITERATIONS.md avant chaque modif, avec référence au rapport FMA et au mode ciblé
- En cas de régression → ROLLBACK immédiat, essai K+1 sous le même iter N
- Après 3 ROLLBACK consécutifs : CP-Escalade (proposer 4ᵉ hypothèse ou main à l'utilisateur — jamais d'abandon agent)

