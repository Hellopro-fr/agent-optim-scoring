#!/usr/bin/env python3
"""
run_pipeline.py — Orchestrateur du pipeline d'optimisation

Charge les parcours de test, appelle l'API GraphRAG pour chaque parcours,
évalue les résultats, et génère un rapport d'itération.

Usage:
    python scripts/run_pipeline.py --iteration 0
    python scripts/run_pipeline.py --iteration 3 --compare 2
"""

import json
import sys
import argparse
from datetime import datetime
from pathlib import Path
import requests

# Chemins du projet
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
TEST_DATA_DIR = PROJECT_ROOT / "test_data"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORTS_DIR = PROJECT_ROOT / "reports"

# Imports des autres scripts
sys.path.insert(0, str(SCRIPTS_DIR))
from evaluate import evaluate_iteration, log_api_call_to_file


def load_config():
    """Charge la configuration de l'API"""
    config_path = CONFIG_DIR / "api_config.json"
    with open(config_path, "r") as f:
        return json.load(f)


def load_parcours():
    """Charge tous les parcours depuis test_data/parcours.json"""
    parcours_path = TEST_DATA_DIR / "parcours.json"
    with open(parcours_path, "r") as f:
        data = json.load(f)

    # Filtrer les parcours valides (exclure les placeholders/stubs)
    parcours_list = []
    for p in data:
        # Vérifier que c'est un vrai parcours (pas le header ni le stub)
        if "parcours_id" in p and "caracteristiques_deduites" in p:
            parcours_list.append(p)

    if not parcours_list:
        raise ValueError(f"Aucun parcours valide trouvé dans {parcours_path}")

    return parcours_list


def build_api_payload(parcours, config):
    """
    Construit le payload à envoyer à l'API depuis les données du parcours

    Expect parcours avec structure:
    {
        "parcours_id": "...",
        "categorie": "...",
        "sous_type": "...",
        "questions_reponses": [...],
        "caracteristiques_deduites": {...}
    }
    """
    # TODO: Cette fonction dépend de la structure réelle des parcours
    # et de la correspondance entre IDs de caractéristiques et les réponses
    # Pour maintenant, retourner un payload minimal

    payload = {
        "id_categorie": parcours.get("id_categorie", 0),
        "champs_sortie": config.get("default_output_fields", ["url"]),
        "top_k": config.get("default_top_k", 26),
        "metadonnee_utilisateurs": parcours.get("metadonnee_utilisateurs", {
            "pays": "France",
            "id_pays": 1
        }),
        "liste_caracteristique": parcours.get("liste_caracteristique", []),
        "rerank": {
            "use_rerank": config.get("rerank_enabled", True),
            "parcours": _build_parcours_text(parcours),
            "top_k": config.get("default_rerank_top_k", 26),
            "id_prompt": 118
        },
        "scoring": {
            "c_unknown_score": 0,
            "z_unmatched": 0
        }
    }

    return payload


def _build_parcours_text(parcours):
    """Formatte les questions/réponses en texte pour le rerank"""
    qr = parcours.get("questions_reponses", [])
    parts = []
    for i, item in enumerate(qr, 1):
        q = item.get("question", "")
        r = item.get("reponse", "")
        parts.append(f"Q{i}: {q} | R{i}: {r}")
    return " | ".join(parts)


def call_api(payload, config, parcours_id, iteration_num=None):
    """Appelle l'API GraphRAG pour un parcours"""
    api_url = config["api_endpoint_matching"]
    headers = config.get("headers", {})
    timeout = config.get("timeout_seconds", 30)
    max_retries = config.get("max_retries", 3)
    retry_delay = config.get("retry_delay_seconds", 2)

    # On logge dès qu'on a iteration_num (sinon pas de fichier cible)
    log_details = iteration_num is not None

    last_error = None
    for attempt in range(max_retries):
        try:
            print(f"  [API] Appel pour parcours {parcours_id} (tentative {attempt + 1}/{max_retries})...", flush=True)
            response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            result = response.json()
            if log_details:
                log_api_call_to_file(
                    iteration_num=iteration_num,
                    parcours_id=parcours_id,
                    method="POST",
                    url=api_url,
                    payload=payload,
                    status=response.status_code,
                    response=result,
                )
            print(f"  [API] OK ({len(result.get('top_produit', []))} top produits)")
            return result
        except requests.RequestException as e:
            last_error = e
            if attempt < max_retries - 1:
                print(f"Erreur: {e}. Nouvelle tentative dans {retry_delay}s...")
                import time
                time.sleep(retry_delay)
            else:
                print(f"Échec après {max_retries} tentatives")
                if log_details:
                    log_api_call_to_file(
                        iteration_num=iteration_num,
                        parcours_id=parcours_id,
                        method="POST",
                        url=api_url,
                        payload=payload,
                        error=str(e),
                    )

    raise Exception(f"Impossible d'appeler l'API pour {parcours_id}: {last_error}")


def run_pipeline(iteration_num, compare_to=None):
    """Lance le pipeline complet pour une itération"""
    print(f"\n{'='*70}")
    print(f"Pipeline d'optimisation scoring HelloPro — Itération {iteration_num}")
    print(f"{'='*70}\n")

    config = load_config()
    parcours_list = load_parcours()

    print(f"Chargement: {len(parcours_list)} parcours, API matching: {config['api_endpoint_matching']}\n")

    # Résultats de cette itération
    iteration_results = {
        "iteration": iteration_num,
        "timestamp": datetime.now().isoformat(),
        "api_endpoint_matching": config["api_endpoint_matching"],
        "api_endpoint_product_details": config["api_endpoint_product_details"],
        "parcours_count": len(parcours_list),
        "resultats": {}
    }

    # Appeler l'API pour chaque parcours
    print("Exécution des appels API:")
    for i, parcours in enumerate(parcours_list, 1):
        parcours_id = parcours.get("parcours_id", f"unknown_{i}")
        print(f"\n[{i}/{len(parcours_list)}] {parcours_id}")

        try:
            payload = build_api_payload(parcours, config)
            api_response = call_api(payload, config, parcours_id, iteration_num=iteration_num)

            # Sauvegarder la réponse brute
            iteration_results["resultats"][parcours_id] = {
                "parcours": parcours,
                "api_response": api_response
            }
        except Exception as e:
            print(f"  ⚠ Erreur: {e}")
            iteration_results["resultats"][parcours_id] = {
                "parcours": parcours,
                "error": str(e)
            }

    # Sauvegarder les résultats bruts
    results_file = RESULTS_DIR / f"iteration_{iteration_num:03d}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(results_file, "w") as f:
        json.dump(iteration_results, f, indent=2, ensure_ascii=False)
    print(f"\n[OK] Résultats bruts sauvegardés: {results_file}")

    # Évaluer les résultats
    print(f"\nÉvaluation des résultats...")
    metrics = evaluate_iteration(iteration_num)

    # Afficher le résumé
    print(f"\n{'='*70}")
    print("RÉSUMÉ DES RÉSULTATS")
    print(f"{'='*70}")
    print(f"\nItération {iteration_num}:")
    if metrics:
        # Métriques déjà à l'échelle 0–100 (présentées avec %)
        PERCENT_METRICS = {"taux_conformite", "presence_estimatif", "score_global"}
        # Métriques à l'échelle 0–1 (à multiplier par 100 pour affichage en %)
        RATIO_METRICS = {"coherence_score"}

        for metric_name, metric_value in metrics.to_dict().items():
            if metric_name in PERCENT_METRICS:
                print(f"  {metric_name}: {metric_value:.2f}%")
            elif metric_name in RATIO_METRICS:
                print(f"  {metric_name}: {metric_value:.2%}")
            elif isinstance(metric_value, float):
                print(f"  {metric_name}: {metric_value:.3f}")
            else:
                print(f"  {metric_name}: {metric_value}")
    else:
        print("  (Évaluation non disponible)")

    if compare_to is not None:
        print(f"\nComparaison avec itération {compare_to}:")
        print("  (À implémenter)")

    print(f"\n{'='*70}\n")

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lance le pipeline GraphRAG")
    parser.add_argument("--iteration", type=int, required=True, help="Numéro d'itération")
    parser.add_argument("--compare", type=int, help="Comparer avec cette itération")

    args = parser.parse_args()

    try:
        metrics = run_pipeline(args.iteration, args.compare)
        sys.exit(0)
    except Exception as e:
        print(f"Erreur fatale: {e}", file=sys.stderr)
        sys.exit(1)
