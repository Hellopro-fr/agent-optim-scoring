# Critères d'évaluation — Optimisation Scoring HelloPro

## Ce fichier est IMMUTABLE. Ne jamais le modifier.

## Métriques principales

| Métrique | Description | Seuil cible |
|---|---|---|
| Taux de conformité | % de produits de la sélection qui correspondent au besoin | ≥ 80% |
| Aberrations prix | Prix manifestement incohérent (facteur x10+) | 0 |
| Doublons | Produits identiques ou quasi-identiques dans la sélection | 0 |
| Diversité fournisseurs | Nombre de fournisseurs différents (si disponibles) | ≥ 3 |
| Cohérence score/pertinence | Les produits les mieux scorés sont les plus pertinents | Corrélation positive |
| Présence estimatif | Un estimatif est présenté quand les données le permettent | ≥ 90% |

## Définition de "conforme"
Un produit est conforme si :
- Sa catégorie correspond au besoin exprimé
- Son sous-type correspond (si spécifié par l'acheteur)
- Ses caractéristiques techniques ne contredisent pas le besoin
- Son état (neuf/occasion) correspond à la demande (ou neuf par défaut)

## Définition de "aberration prix"
Un prix est aberrant si :
- Il est manifestement un prix de location (ex : 400€ pour un tracteur)
- Il est un prix au lot non unitaire (ex : 74€ pour 60 palettes)
- Il présente un facteur x10+ par rapport aux autres prix de la catégorie

## Définition de "doublon"
Deux produits sont doublons si :
- Même fournisseur ET descriptif technique quasi-identique
- ⚠️ Même titre ne suffit PAS à conclure doublon (vérifier le descriptif)

## Évaluation globale
Score global = moyenne pondérée des métriques :
- Taux de conformité : poids 2
- Toutes les autres : poids 1
