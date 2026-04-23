#!/usr/bin/env python3
"""
evaluate.py — Calcule les métriques d'évaluation selon EVAL.md

Charge les résultats d'une itération depuis results/iteration_XXX.json,
calcule les 6 métriques de conformité, et compare avec la baseline.

Usage:
    python scripts/evaluate.py --iteration 3
    python scripts/evaluate.py --iteration 3 --compare 2
"""

import copy
import json
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, fields
from typing import Optional
import requests
from dotenv import load_dotenv

# Juge LLM — remplace le matching mots-clés pour le taux de conformité
sys.path.insert(0, str(Path(__file__).parent))
from judge import judge_product, load_cache, save_cache, get_client, SCORE_MAP
from coherence import compute_parcours_coherence


# Chemins du projet
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
RESULTS_DIR = PROJECT_ROOT / "results"
TEST_DATA_DIR = PROJECT_ROOT / "test_data"
LOGS_DIR = PROJECT_ROOT / "logs"
BASELINE_FILE = PROJECT_ROOT / "BASELINE.json"


def log_api_call_to_file(
    iteration_num: int,
    parcours_id: str,
    method: str,
    url: str,
    payload: dict,
    status: Optional[int] = None,
    response: Optional[dict] = None,
    error: Optional[str] = None,
):
    """Écrit une entrée d'appel API dans logs/api_iteration_NNN.log (mode append)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"api_iteration_{iteration_num:03d}.log"

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 70}\n")
        f.write(f"[{datetime.now().isoformat()}] parcours={parcours_id}\n")
        f.write(f"{'=' * 70}\n")
        f.write(f">>> METHOD: {method}\n")
        f.write(f">>> URL: {url}\n")
        f.write(f">>> PAYLOAD: {json.dumps(payload, ensure_ascii=False, indent=2)}\n")
        if status is not None:
            f.write(f"<<< STATUS: {status}\n")
        if response is not None:
            f.write(f"<<< RESPONSE: {json.dumps(response, ensure_ascii=False, indent=2)}\n")
        if error is not None:
            f.write(f"<<< ERROR: {error}\n")


@dataclass
class Metrics:
    """Conteneur pour les métriques d'une itération"""
    iteration: int
    taux_conformite: float  # % de produits conformes
    doublons: int           # Nombre de doublons détectés
    diversite_fournisseurs: float  # Moyenne de fournisseurs uniques par parcours (cible ≥ 3)
    coherence_score: float  # moyenne(NDCG@10, Precision@5) sur les 13 parcours ∈ [0, 1]
    presence_estimatif: float  # % de cas avec estimatif présent
    coherence_ndcg: float = 0.0  # Composante NDCG@10 de coherence_score (debug)
    coherence_precision: float = 0.0  # Composante Precision@5 de coherence_score (debug)

    def score_global(self) -> float:
        """Calcule le score global pondéré selon EVAL.md"""
        # Poids: conformité x2, tous les autres x1 (total = 6)
        weights = {
            'taux_conformite': 2.0,
            'doublons': 1.0,
            'diversite_fournisseurs': 1.0,
            'coherence_score': 1.0,
            'presence_estimatif': 1.0
        }

        # Normaliser les métriques (0-1)
        norm_values = {
            'taux_conformite': self.taux_conformite / 100.0,  # Déjà en %
            'doublons': 1.0 if self.doublons == 0 else 0.0,  # 0 doublons = 1.0
            'diversite_fournisseurs': min(self.diversite_fournisseurs / 3.0, 1.0),  # Cible >= 3
            'coherence_score': self.coherence_score,  # Déjà 0-1
            'presence_estimatif': self.presence_estimatif / 100.0  # Déjà en %
        }

        weighted_sum = sum(norm_values[k] * weights[k] for k in norm_values)
        total_weight = sum(weights.values())

        return (weighted_sum / total_weight) * 100.0  # En %

    def to_dict(self) -> dict:
        """Convertit les métriques en dictionnaire"""
        return {
            'iteration': self.iteration,
            'taux_conformite': self.taux_conformite,
            'doublons': self.doublons,
            'diversite_fournisseurs': self.diversite_fournisseurs,
            'coherence_score': self.coherence_score,
            'coherence_ndcg': self.coherence_ndcg,
            'coherence_precision': self.coherence_precision,
            'presence_estimatif': self.presence_estimatif,
            'score_global': self.score_global()
        }


def load_config():
    """Charge la configuration de l'API"""
    config_path = CONFIG_DIR / "api_config.json"
    with open(config_path, "r") as f:
        return json.load(f)


def load_iteration_results(iteration_num: int) -> dict:
    """Charge les résultats d'une itération"""
    results_file = RESULTS_DIR / f"iteration_{iteration_num:03d}.json"
    if not results_file.exists():
        raise FileNotFoundError(f"Résultats non trouvés: {results_file}")

    with open(results_file, "r") as f:
        return json.load(f)


def fetch_characteristics_map(
    id_categorie: int,
    config: dict,
) -> dict:
    """
    Récupère les définitions des caractéristiques d'une catégorie.

    Appelle : POST https://api.hellopro.fr/v2/index.php
    Token : Bearer ${NEXT_TOKEN_API_QUESTION}

    Returns:
        Dict indexé par id_caracteristique (int) :
        {
            id_caract: {
                "id_caracteristique": int,
                "nom": str,
                "unite": str|None,
                "type": str,  # "Textuelle" ou "Numérique"
                "valeurs": {id_valeur (int): valeur_label (str), ...}
            }
        }
    """
    api_url = "https://api.hellopro.fr/v2/index.php"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {os.getenv('NEXT_TOKEN_API_QUESTION', '')}"
    }
    timeout = config.get("timeout_seconds", 30)

    payload = {
        "etape": "caracteristique",
        "field": "final",
        "action": "get",
        "data": {
            "id_categorie": str(id_categorie)
        }
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()

        # Réponse attendue : {"code": 0, "response": [caract_items]}
        caract_list = data.get("response", [])
        caract_map = {}

        for caract in caract_list:
            id_caract = int(caract.get("id_caracteristique") or caract.get("id", 0))
            if not id_caract:
                continue

            # Construire la map des valeurs
            valeurs_map = {}
            valeurs = caract.get("valeurs", [])
            for val_item in valeurs:
                id_val = int(val_item.get("id_valeur") or val_item.get("id", 0))
                val_label = val_item.get("valeur", "")
                if id_val:
                    valeurs_map[id_val] = val_label

            caract_map[id_caract] = {
                "id_caracteristique": id_caract,
                "nom": caract.get("nom", ""),
                "unite": caract.get("unite"),
                "type": caract.get("type", ""),
                "valeurs": valeurs_map
            }

        return caract_map

    except Exception as e:
        print(f"  ⚠ Erreur fetch_characteristics_map(cat={id_categorie}): {e}")
        return {}


def fetch_product_details(
    product_ids: list,
    config: dict,
    id_categorie: Optional[int] = None,
    iteration_num: Optional[int] = None,
    parcours_id: Optional[str] = None,
) -> dict:
    """
    Récupère les détails des produits via l'API product_details.

    Structure du payload attendue par l'API (voir test_data/sample_payloads.json) :
        {
            "etape": "get_info_produit",
            "scrapping": 1,
            "action": "get",
            "data": {
                "id_categorie": "<id>",
                "id_produits": ["id1", "id2", ...]
            }
        }

    Args:
        product_ids: Liste des IDs de produits
        config: Configuration contenant l'endpoint et les paramètres
        id_categorie: ID de la catégorie du parcours (inséré dans data.id_categorie)
        iteration_num: Numéro d'itération (pour le nom du fichier de log)
        parcours_id: ID du parcours (pour l'entête de l'entrée de log)

    Returns:
        Dict indexé par product_id avec les détails du produit
    """
    if not product_ids:
        return {}

    api_url = config.get("api_endpoint_product_details")
    headers = config.get("headers", {}).copy()

    # Ajouter le token d'autorisation s'il est disponible
    token = os.getenv("TOKEN_INFO_PRODUIT")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    timeout = config.get("timeout_seconds", 30)

    # Construire le payload: copie du template de config + injection de data
    payload = copy.deepcopy(
        config.get(
            "product_details_request",
            {"etape": "get_info_produit", "scrapping": 1, "action": "get", "data": {}},
        )
    )
    payload.setdefault("data", {})
    payload["data"]["id_categorie"] = str(id_categorie) if id_categorie is not None else ""
    payload["data"]["id_produits"] = [str(pid) for pid in product_ids]

    # On logge dès qu'on a iteration_num et parcours_id
    log_details = iteration_num is not None and parcours_id is not None

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        products_list = response.json()
        if log_details:
            log_api_call_to_file(
                iteration_num=iteration_num,
                parcours_id=parcours_id,
                method="POST",
                url=api_url,
                payload=payload,
                status=response.status_code,
                response=products_list,
            )

        # Indexer par ID (l'API retourne {"items": {"id_produit": {...}, ...}})
        products_dict = {}
        if isinstance(products_list, dict) and "items" in products_list:
            # Format réel : {"items": {"id_produit": {produit, categorie, vendeur}}}
            products_dict = products_list["items"]
        elif isinstance(products_list, list):
            # Fallback pour rétrocompatibilité (ancien format)
            for product in products_list:
                if "id" in product:
                    products_dict[product["id"]] = product

        return products_dict
    except Exception as e:
        if log_details:
            log_api_call_to_file(
                iteration_num=iteration_num,
                parcours_id=parcours_id,
                method="POST",
                url=api_url,
                payload=payload,
                error=str(e),
            )
        print(f"  ⚠ Erreur lors de la récupération des détails produits: {e}")
        return {}


def load_evaluation_data() -> dict:
    """Charge les données d'évaluation : officiels + customs (ajoutés via dashboard)."""
    parcours_file = TEST_DATA_DIR / "parcours.json"
    with open(parcours_file, "r") as f:
        data = json.load(f)

    # Fusion avec custom_parcours.json (optionnel, ajouté via dashboard)
    custom_path = PROJECT_ROOT / "custom_parcours.json"
    if custom_path.exists():
        try:
            with open(custom_path, "r") as f:
                data.extend(json.load(f).get("parcours", []))
        except (json.JSONDecodeError, OSError):
            pass

    # Indexer par parcours_id
    evaluation_index = {}
    for p in data:
        if "parcours_id" in p and "evaluation_humaine" in p:
            evaluation_index[p["parcours_id"]] = p["evaluation_humaine"]

    return evaluation_index


def extract_api_results(api_response: dict) -> dict:
    """
    Extrait les résultats pertinents de la réponse API

    Retourne:
    {
        "produits_acceptes": [...],  # IDs des produits dans top_produit
        "noms_acceptes": [...],      # Noms des produits dans top_produit (llm_response.nom)
        "produits_rejetes": [...],   # Produits dans ecarts
        "fournisseurs": set(),       # IDs uniques de fournisseurs
        "scores": {},                # id_produit -> score
        "caracteristiques_par_produit": {}  # id_produit -> [MatchingCharacteristic, ...]
    }
    """
    results = {
        "produits_acceptes": [],
        "noms_acceptes": [],
        "produits_rejetes": [],
        "fournisseurs": set(),
        "scores": {},
        "caracteristiques_par_produit": {}
    }

    # top_produit = tous les produits sélectionnés par l'API (pas de filtre decision)
    for product in api_response.get("top_produit", []):
        prod_id = product.get("id_produit")
        llm_resp = product.get("llm_response", {})
        nom = llm_resp.get("nom", "")

        results["produits_acceptes"].append(prod_id)
        if nom:
            results["noms_acceptes"].append(nom)
        results["scores"][prod_id] = product.get("score", 0)

        fournisseur = product.get("info_produit", {}).get("id_fournisseur")
        if fournisseur:
            results["fournisseurs"].add(str(fournisseur))

        # Stocker les données de matching des caractéristiques
        caracts = product.get("caracteristique", [])
        if caracts:
            results["caracteristiques_par_produit"][prod_id] = caracts

    # ecarts = produits non retenus
    for product in api_response.get("ecarts", []):
        prod_id = product.get("id_produit")
        llm_resp = product.get("llm_response", {})
        raison = llm_resp.get("raison_exclusion", "Inconnu")
        results["produits_rejetes"].append({
            "id_produit": prod_id,
            "raison": raison
        })

    return results


def calculate_parcours_metrics(
    api_results: dict,
    evaluation: Optional[dict],
    product_details: dict = None,
    caract_map: dict = None,
    parcours: Optional[dict] = None,
    judge_client=None,
    judge_cache: Optional[dict] = None,
    verdicts_log: Optional[list] = None,
) -> dict:
    """
    Calcule les métriques pour un parcours spécifique

    evaluation est optionnel car on peut avoir des parcours sans evaluation_humaine
    product_details : dict indexé par product_id avec détails (prix, nom, etc.)
    caract_map : dict des définitions de caractéristiques {id_caract: {nom, type, valeurs, ...}}
    parcours : parcours complet (catégorie, sous-type, questions/réponses, caract déduites)
    judge_client : client Anthropic pour LLM juge (None = fallback score neutre)
    judge_cache : cache partagé entre parcours (mutable, clé = "{pid}:{id_produit}")
    verdicts_log : liste mutable où on ajoute chaque verdict (pour debug/audit)
    """
    if product_details is None:
        product_details = {}
    if caract_map is None:
        caract_map = {}
    if judge_cache is None:
        judge_cache = {}

    metrics = {
        "conformes": 0.0,
        "total_evalues": 0,
        "doublons": 0,
        "fournisseurs_count": len(api_results["fournisseurs"]),
        "coherence_ndcg": 0.5,
        "coherence_precision": 0.5,
        "coherence_detail": None,  # {ndcg, precision, ranking} pour coherence_detail_NNN.json
        "estimatif_present": False
    }

    # Conformité via LLM juge (Option B — score gradué)
    # + collecte des verdicts par id_produit pour le calcul NDCG/Precision
    produits_acceptes = api_results.get("produits_acceptes", [])
    caract_par_produit = api_results.get("caracteristiques_par_produit", {})
    verdicts_by_id: dict = {}
    if produits_acceptes and parcours is not None:
        score_total = 0.0
        for prod_id in produits_acceptes:
            detail = product_details.get(prod_id)
            if not detail:
                continue
            caract_api = caract_par_produit.get(prod_id, [])
            verdict = judge_product(detail, caract_api, parcours, judge_cache, judge_client)
            verdicts_by_id[prod_id] = verdict
            score_total += verdict.get("score", 0.0)
            if verdicts_log is not None:
                verdicts_log.append({
                    "parcours_id": parcours.get("parcours_id"),
                    "id_produit": prod_id,
                    "correspondance": verdict.get("correspondance"),
                    "raison": verdict.get("raison"),
                    "score": verdict.get("score"),
                })
        metrics["conformes"] = score_total
        metrics["total_evalues"] = len(produits_acceptes)

    # Cohérence score/pertinence : NDCG@10 + Precision@5 via juge LLM
    scores_by_id = api_results.get("scores", {})
    if verdicts_by_id and scores_by_id:
        detail = compute_parcours_coherence(scores_by_id, verdicts_by_id)
        metrics["coherence_ndcg"] = detail["ndcg"]
        metrics["coherence_precision"] = detail["precision"]
        metrics["coherence_detail"] = {
            "parcours_id": parcours.get("parcours_id") if parcours else None,
            "ndcg_at_10": detail["ndcg"],
            "precision_at_5": detail["precision"],
            "ranking": detail["ranking"],
        }

    # Calcul estimatif_present et détection doublons via les détails produits
    if product_details:
        estimatif_count = 0
        for prod_id in api_results["produits_acceptes"]:
            if prod_id in product_details:
                prod = product_details[prod_id]
                prix_str = prod.get("produit", {}).get("prix_produit", "")
                if prix_str:
                    estimatif_count += 1

        # Calculer estimatif_present (% produits avec prix)
        if api_results["produits_acceptes"]:
            metrics["estimatif_present"] = estimatif_count > 0

        # Détection des doublons via les noms de produits
        noms = []
        for prod_id in api_results["produits_acceptes"]:
            if prod_id in product_details:
                nom = product_details[prod_id].get("produit", {}).get("titre_produit", "").lower()
                if nom:
                    noms.append(nom)

        # Chercher les doublons (même nom ou très similaires)
        for i, nom1 in enumerate(noms):
            for nom2 in noms[i+1:]:
                if nom1 == nom2:
                    metrics["doublons"] += 1

    # Anomalies documentées dans l'évaluation (doublons uniquement)
    if evaluation and "anomalies" in evaluation:
        anomalies = evaluation["anomalies"]
        if isinstance(anomalies, list):
            for a in anomalies:
                if "doublon" in a.lower() and metrics["doublons"] == 0:
                    metrics["doublons"] += 1

    return metrics


def evaluate_iteration(iteration_num: int) -> Metrics:
    """Évalue une itération complète"""
    print(f"Chargement des résultats d'itération {iteration_num}...")
    iteration_results = load_iteration_results(iteration_num)
    evaluation_data = load_evaluation_data()
    config = load_config()

    # Accumulateurs
    total_conformite = 0.0
    total_parcours = 0
    total_doublons = 0
    fournisseurs_par_parcours = []  # liste des nb fournisseurs uniques par parcours (moyenne in fine)
    ndcg_scores = []
    precision_scores = []
    coherence_details = []  # détail du classement par parcours (NDCG/Precision + ranking)
    estimatif_present_count = 0
    characteristics_cache = {}  # Cache {id_categorie: caract_map}

    # LLM juge : client + cache partagé + log de verdicts
    judge_client = get_client()
    judge_cache = load_cache()
    verdicts_log: list = []
    if judge_client is None:
        print("  ⚠ LLM juge indisponible (ANTHROPIC_API_KEY manquant ou SDK non installé) — scores neutres")

    # Évaluer chaque parcours
    for parcours_id, result in iteration_results.get("resultats", {}).items():
        if "error" in result:
            print(f"  ⚠ {parcours_id}: Erreur lors de l'appel API")
            continue

        api_response = result.get("api_response", {})
        evaluation = evaluation_data.get(parcours_id)

        # Extraire les résultats de l'API
        api_results = extract_api_results(api_response)

        # Récupérer les détails des produits (pour prix, descriptifs, etc.)
        all_product_ids = api_results["produits_acceptes"] + [p["id_produit"] for p in api_results["produits_rejetes"]]
        id_categorie = result.get("parcours", {}).get("id_categorie")
        product_details = (
            fetch_product_details(
                all_product_ids,
                config,
                id_categorie=id_categorie,
                iteration_num=iteration_num,
                parcours_id=parcours_id,
            )
            if all_product_ids
            else {}
        )

        # Récupérer la map des caractéristiques (avec cache par catégorie)
        caract_map = {}
        if id_categorie:
            if id_categorie not in characteristics_cache:
                try:
                    characteristics_cache[id_categorie] = fetch_characteristics_map(id_categorie, config)
                except Exception as e:
                    print(f"  ⚠ Erreur fetch_characteristics_map(cat={id_categorie}): {e}")
                    characteristics_cache[id_categorie] = {}
            caract_map = characteristics_cache[id_categorie]

        # Calculer les métriques du parcours (inclut LLM juge pour conformité)
        parcours_complet = result.get("parcours", {})
        parcours_metrics = calculate_parcours_metrics(
            api_results,
            evaluation,
            product_details,
            caract_map,
            parcours=parcours_complet,
            judge_client=judge_client,
            judge_cache=judge_cache,
            verdicts_log=verdicts_log,
        )

        # Accumuler
        if parcours_metrics["total_evalues"] > 0:
            conformite_parcours = (parcours_metrics["conformes"] / parcours_metrics["total_evalues"]) * 100
            total_conformite += conformite_parcours
        else:
            total_conformite += 0.0  # Pas de produits jugés → 0%

        total_parcours += 1
        total_doublons += parcours_metrics["doublons"]
        fournisseurs_par_parcours.append(parcours_metrics["fournisseurs_count"])
        ndcg_scores.append(parcours_metrics["coherence_ndcg"])
        precision_scores.append(parcours_metrics["coherence_precision"])
        if parcours_metrics.get("coherence_detail"):
            coherence_details.append(parcours_metrics["coherence_detail"])
        if parcours_metrics["estimatif_present"]:
            estimatif_present_count += 1

    # Calculer les moyennes
    taux_conformite = (total_conformite / total_parcours) if total_parcours > 0 else 0.0
    ndcg_moyen = (sum(ndcg_scores) / len(ndcg_scores)) if ndcg_scores else 0.5
    precision_moyenne = (sum(precision_scores) / len(precision_scores)) if precision_scores else 0.5
    coherence_moyenne = (ndcg_moyen + precision_moyenne) / 2.0
    presence_estimatif = (estimatif_present_count / total_parcours * 100) if total_parcours > 0 else 0.0
    diversite_moyenne = (
        sum(fournisseurs_par_parcours) / len(fournisseurs_par_parcours)
        if fournisseurs_par_parcours else 0.0
    )

    # Créer l'objet Metrics
    metrics = Metrics(
        iteration=iteration_num,
        taux_conformite=taux_conformite,
        doublons=total_doublons,
        diversite_fournisseurs=diversite_moyenne,
        coherence_score=coherence_moyenne,
        coherence_ndcg=ndcg_moyen,
        coherence_precision=precision_moyenne,
        presence_estimatif=presence_estimatif
    )

    # Sauvegarder les métriques
    save_metrics(metrics)

    # Persister le cache LLM juge + log des verdicts pour audit
    save_cache(judge_cache)
    if verdicts_log:
        verdicts_file = RESULTS_DIR / f"judge_verdicts_{iteration_num:03d}.json"
        with open(verdicts_file, "w", encoding="utf-8") as f:
            json.dump(verdicts_log, f, ensure_ascii=False, indent=2)
        print(f"Verdicts LLM sauvegardés: {verdicts_file} ({len(verdicts_log)} entrées)")

    # Détail de cohérence (NDCG@10 + Precision@5 + ranking par parcours) — audit P4
    if coherence_details:
        coherence_file = RESULTS_DIR / f"coherence_detail_{iteration_num:03d}.json"
        with open(coherence_file, "w", encoding="utf-8") as f:
            json.dump(coherence_details, f, ensure_ascii=False, indent=2)
        print(f"Détail cohérence sauvegardé: {coherence_file} ({len(coherence_details)} parcours)")

    # Pour l'itération 0, renseigner aussi BASELINE.json (immuable après)
    if iteration_num == 0:
        save_baseline(metrics, parcours_count=total_parcours)

    return metrics


def save_metrics(metrics: Metrics):
    """Sauvegarde les métriques calculées"""
    metrics_file = RESULTS_DIR / f"metrics_{metrics.iteration:03d}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    with open(metrics_file, "w") as f:
        json.dump(metrics.to_dict(), f, indent=2)

    print(f"Métriques sauvegardées: {metrics_file}")


def save_baseline(metrics: Metrics, parcours_count: int):
    """
    (Re)écrit BASELINE.json à partir des métriques de l'itération 0.

    Garde-fou d'immuabilité : la baseline n'est JAMAIS réécrite pendant
    les itérations 1+ (la référence ne doit pas bouger pendant la boucle
    d'optimisation). Mais à iter 0, chaque lancement recalcule pour
    refléter l'état courant du pipeline.

    Les annotations manuelles (`observations`, `results_par_parcours`)
    sont préservées entre les runs d'iter 0.
    """
    # Garde-fou: immuable pour toute itération ≥ 1
    if metrics.iteration != 0:
        return

    # Charger l'état précédent pour préserver observations / results_par_parcours
    existing = {}
    if BASELINE_FILE.exists():
        with open(BASELINE_FILE, "r", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = {}

    timestamp = datetime.now().isoformat()
    metrics_dict = metrics.to_dict()

    baseline_data = {
        "_info": (
            "Baseline de l'itération 0. Recalculée à chaque lancement d'iter 0. "
            "Immuable pour toutes les itérations suivantes (garantie par save_baseline). "
            "Le champ `observations` est préservé entre les runs."
        ),
        "_status": f"RECALCULATED — dernière mise à jour {timestamp}",
        "generated_at": timestamp,
        "parcours_count": parcours_count,
        "metrics": {
            "taux_conformite": metrics_dict["taux_conformite"],
            "doublons": metrics_dict["doublons"],
            "diversite_fournisseurs": metrics_dict["diversite_fournisseurs"],
            # Note: nom canonique selon EVAL.md (la dataclass utilise "coherence_score")
            "coherence_score_pertinence": metrics_dict["coherence_score"],
            "presence_estimatif": metrics_dict["presence_estimatif"],
            "score_global": metrics_dict["score_global"],
        },
        # Préservés entre runs pour ne pas écraser le travail manuel
        "observations": existing.get("observations", []),
        "results_par_parcours": existing.get("results_par_parcours", []),
    }

    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(baseline_data, f, indent=2, ensure_ascii=False)

    print(f"[OK] BASELINE.json (re)calculée: {BASELINE_FILE}")


def load_baseline() -> Optional[Metrics]:
    """Charge les métriques de la baseline (itération 0)"""
    metrics_file = RESULTS_DIR / "metrics_000.json"
    if not metrics_file.exists():
        return None

    with open(metrics_file, "r") as f:
        data = json.load(f)

    # Ne garder que les champs connus de la dataclass (ignore anciens champs retirés)
    valid_fields = {f.name for f in fields(Metrics)}
    return Metrics(**{k: v for k, v in data.items() if k in valid_fields})


def main(iteration_num: int):
    """Lance l'évaluation"""
    metrics = evaluate_iteration(iteration_num)

    print(f"\n{'='*70}")
    print(f"MÉTRIQUES — Itération {iteration_num}")
    print(f"{'='*70}\n")

    # Métriques déjà à l'échelle 0–100 (présentées avec %)
    PERCENT_METRICS = {"taux_conformite", "presence_estimatif", "score_global"}
    # Métriques à l'échelle 0–1 (à multiplier par 100 pour affichage en %)
    RATIO_METRICS = {"coherence_score"}

    metrics_dict = metrics.to_dict()
    for key, value in metrics_dict.items():
        if key in PERCENT_METRICS:
            print(f"  {key}: {value:.2f}%")
        elif key in RATIO_METRICS:
            print(f"  {key}: {value:.2%}")
        elif isinstance(value, float):
            print(f"  {key}: {value:.3f}")
        else:
            print(f"  {key}: {value}")

    # Comparer avec baseline ou itération antérieure
    if iteration_num > 0:
        baseline = load_baseline()
        if baseline:
            print(f"\nComparaison avec baseline (itération 0):")
            print(f"  Conformité: {baseline.taux_conformite:.2f}% → {metrics.taux_conformite:.2f}%")
            print(f"  Score global: {baseline.score_global():.2f}% → {metrics.score_global():.2f}%")

            if metrics.score_global() >= baseline.score_global():
                print(f"\n[AMÉLIORATION]")
            else:
                print(f"\n[RÉGRESSION]")

    print(f"\n{'='*70}\n")

    return metrics_dict


if __name__ == "__main__":
    # Charger les variables d'environnement depuis .env
    load_dotenv()

    parser = argparse.ArgumentParser(description="Évalue les résultats d'une itération")
    parser.add_argument("--iteration", type=int, required=True, help="Numéro d'itération")
    parser.add_argument("--compare", type=int, help="Comparer avec cette itération")

    args = parser.parse_args()

    try:
        metrics = main(args.iteration)
        sys.exit(0)
    except Exception as e:
        print(f"Erreur: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
