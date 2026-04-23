#!/usr/bin/env python3
"""
coherence.py — Calcule la cohérence score/pertinence d'un parcours.

Utilise les verdicts du juge LLM (scripts/judge.py) comme pertinence graduée
et compare avec le classement API (`score` de top_produit) via :
  - NDCG@10 : ordre cohérent + top-lourd (standard IR)
  - Precision@5 : % de produits "parfait" ou "proche" dans le top 5

coherence_score exposé dans Metrics = moyenne(NDCG@10, Precision@5).
"""

from __future__ import annotations

import math
from typing import Optional

NDCG_K = 10
PRECISION_K = 5
PRECISION_THRESHOLD = 0.8  # "parfait"=1.0, "proche"=0.8 → comptés conformes


def _dcg(relevances: list, k: int) -> float:
    """DCG sur les k premiers éléments. Formule : Σ rel_i / log2(i+1), i en 1-based."""
    return sum(
        rel / math.log2(i + 1)
        for i, rel in enumerate(relevances[:k], start=1)
    )


def compute_ndcg(
    products_sorted_by_score: list,
    relevances_by_id: dict,
    k: int = NDCG_K,
) -> float:
    """NDCG@k ∈ [0, 1]. Retourne 0.0 si IDCG = 0 (aucun produit pertinent)."""
    if not products_sorted_by_score:
        return 0.0

    relevances_observed = [
        relevances_by_id.get(pid, 0.0) for pid in products_sorted_by_score
    ]
    relevances_ideal = sorted(relevances_observed, reverse=True)

    k_eff = min(k, len(relevances_observed))
    dcg = _dcg(relevances_observed, k_eff)
    idcg = _dcg(relevances_ideal, k_eff)

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def compute_precision_at_k(
    products_sorted_by_score: list,
    relevances_by_id: dict,
    k: int = PRECISION_K,
    threshold: float = PRECISION_THRESHOLD,
) -> float:
    """Precision@k : proportion de produits dans le top-k avec relevance >= threshold."""
    if not products_sorted_by_score:
        return 0.0

    top_k = products_sorted_by_score[:k]
    k_eff = len(top_k)
    if k_eff == 0:
        return 0.0
    count = sum(
        1 for pid in top_k
        if relevances_by_id.get(pid, 0.0) >= threshold
    )
    return count / k_eff


def sort_by_score(scores_by_id: dict) -> list:
    """Retourne les id_produit triés par score API décroissant (ordre observé)."""
    return sorted(scores_by_id.keys(), key=lambda pid: scores_by_id.get(pid, 0.0), reverse=True)


def compute_parcours_coherence(
    scores_by_id: dict,
    verdicts_by_id: dict,
    ndcg_k: int = NDCG_K,
    precision_k: int = PRECISION_K,
) -> dict:
    """Calcule NDCG + Precision + détail de classement pour un parcours.

    Args:
        scores_by_id: {id_produit: score API}
        verdicts_by_id: {id_produit: verdict_dict (contient 'score' et 'correspondance')}

    Returns:
        {
            "ndcg": float ∈ [0, 1],
            "precision": float ∈ [0, 1],
            "ranking": [{"rang_api", "id_produit", "score_api", "score_llm", "correspondance"}, ...]
        }
    """
    products_sorted = sort_by_score(scores_by_id)
    relevances_by_id = {
        pid: (v or {}).get("score", 0.0) for pid, v in verdicts_by_id.items()
    }

    ndcg = compute_ndcg(products_sorted, relevances_by_id, k=ndcg_k)
    precision = compute_precision_at_k(products_sorted, relevances_by_id, k=precision_k)

    ranking = []
    for rang, pid in enumerate(products_sorted, start=1):
        verdict = verdicts_by_id.get(pid, {})
        ranking.append({
            "rang_api": rang,
            "id_produit": pid,
            "score_api": scores_by_id.get(pid),
            "score_llm": (verdict or {}).get("score", 0.0),
            "correspondance": (verdict or {}).get("correspondance", "inconnu"),
        })

    return {
        "ndcg": ndcg,
        "precision": precision,
        "ranking": ranking,
    }
