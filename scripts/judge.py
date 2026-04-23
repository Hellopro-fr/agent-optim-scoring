#!/usr/bin/env python3
"""
judge.py — Juge LLM de conformité produit vs besoin parcours.

Remplace le matching mots-clés dans evaluate.py par un appel à Claude Haiku 4.5
qui évalue chaque produit retourné par l'API en se basant sur :
  - Questions/Réponses du parcours
  - Catégorie + sous-type + caractéristiques déduites
  - Titre, description, prix, fournisseur du produit

Sortie = grille 4 niveaux (parfait / proche / acceptable / hors_sujet) mappée
en score gradué (Option B) : 1.0 / 0.8 / 0.5 / 0.0.

Cache disque : results/judge_cache.json, clé = (parcours_id, id_produit, hash).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
RESULTS_DIR = PROJECT_ROOT / "results"
PROMPT_FILE = CONFIG_DIR / "judge_prompt.md"
CACHE_FILE = RESULTS_DIR / "judge_cache.json"

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 400

# Option B — score gradué
SCORE_MAP = {
    "parfait": 1.0,
    "proche": 0.8,
    "acceptable": 0.5,
    "hors_sujet": 0.0,
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str, max_len: int = 1500) -> str:
    """Retire les tags HTML et normalise les espaces. Tronque à max_len."""
    if not text:
        return ""
    cleaned = _HTML_TAG_RE.sub(" ", text)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "…"
    return cleaned


def _product_hash(product_detail: dict, caracteristiques_api: list) -> str:
    """Hash du contenu produit (titre+desc+prix+caract matchées). Invalide le cache
    si la donnée produit change."""
    produit = product_detail.get("produit", {}) if product_detail else {}
    payload = {
        "titre": produit.get("titre_produit", ""),
        "description": produit.get("description_produit", "")[:3000],
        "prix": produit.get("prix_produit", ""),
        "caract": sorted(
            [(c.get("nom", ""), c.get("valeur", ""), c.get("bareme", 0))
             for c in (caracteristiques_api or [])]
        ),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_cache(cache: dict) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _load_prompt_template() -> str:
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()


def _format_questions_reponses(qr_list: list) -> str:
    if not qr_list:
        return "(aucune question/réponse)"
    lines = []
    for i, item in enumerate(qr_list, 1):
        q = item.get("question", "").strip()
        r = item.get("reponse", "").strip()
        lines.append(f"- Q{i} : {q}\n  R{i} : {r}")
    return "\n".join(lines)


def _format_caracteristiques_api(caracteristiques: list) -> str:
    """Les caractéristiques matchées par l'API (format interne au scoring)."""
    if not caracteristiques:
        return "(aucune caractéristique matchée)"
    parts = []
    for c in caracteristiques:
        nom = c.get("nom", "?")
        valeur = c.get("valeur", "?")
        bareme = c.get("bareme", 0)
        parts.append(f"- {nom} : {valeur} (bareme={bareme})")
    return "\n".join(parts)


def build_prompt(product_detail: dict, caracteristiques_api: list, parcours: dict) -> str:
    """Construit le prompt en substituant les placeholders du template."""
    template = _load_prompt_template()
    produit = product_detail.get("produit", {}) if product_detail else {}
    vendeur = product_detail.get("vendeur", {}) if product_detail else {}

    caracteristiques_deduites = parcours.get("caracteristiques_deduites", {})
    qr_list = parcours.get("questions_reponses", [])

    replacements = {
        "{categorie}": parcours.get("categorie", "(non précisée)"),
        "{sous_type}": parcours.get("sous_type", "(non précisé)"),
        "{caracteristiques_deduites}": json.dumps(caracteristiques_deduites, ensure_ascii=False),
        "{questions_reponses}": _format_questions_reponses(qr_list),
        "{titre}": produit.get("titre_produit", "(sans titre)"),
        "{description}": _strip_html(produit.get("description_produit", "")),
        "{caracteristiques_produit}": _format_caracteristiques_api(caracteristiques_api),
        "{prix}": produit.get("prix_produit") or "(non affiché)",
        "{fournisseur}": vendeur.get("nom", "(inconnu)"),
    }

    prompt = template
    for k, v in replacements.items():
        prompt = prompt.replace(k, str(v))
    return prompt


def _parse_verdict(raw_text: str) -> dict:
    """Parse le JSON retourné par le LLM. Résilient aux ```json wrappers."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def get_client() -> Optional["Anthropic"]:
    """Retourne un client Anthropic ou None si SDK/clé indisponibles."""
    if Anthropic is None:
        return None
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    return Anthropic(api_key=api_key)


def judge_product(
    product_detail: dict,
    caracteristiques_api: list,
    parcours: dict,
    cache: dict,
    client: Optional["Anthropic"],
) -> dict:
    """Juge un produit. Retourne un dict {correspondance, raison, critères, anomalies, score}.

    Cache clé = "{parcours_id}:{id_produit}", invalidé via un hash du contenu produit.
    """
    parcours_id = parcours.get("parcours_id", "?")
    id_produit = (product_detail or {}).get("produit", {}).get("id_produit", "?")
    cache_key = f"{parcours_id}:{id_produit}"
    product_h = _product_hash(product_detail, caracteristiques_api)

    cached = cache.get(cache_key)
    if cached and cached.get("hash") == product_h:
        return cached["verdict"]

    if client is None:
        verdict = {
            "correspondance": "acceptable",
            "raison": "LLM indisponible — valeur neutre",
            "critères": {"categorie": "inconnu", "sous_type": "inconnu",
                         "caracteristiques": "inconnu", "etat": "inconnu",
                         "prix": "non_affiché"},
            "anomalies": ["LLM juge non configuré"],
            "score": SCORE_MAP["acceptable"],
        }
        cache[cache_key] = {"hash": product_h, "verdict": verdict}
        return verdict

    prompt = build_prompt(product_detail, caracteristiques_api, parcours)

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text if resp.content else "{}"
        verdict = _parse_verdict(raw)
    except Exception as e:
        verdict = {
            "correspondance": "acceptable",
            "raison": f"Erreur LLM : {e}",
            "critères": {"categorie": "inconnu", "sous_type": "inconnu",
                         "caracteristiques": "inconnu", "etat": "inconnu",
                         "prix": "non_affiché"},
            "anomalies": [f"llm_error: {type(e).__name__}"],
            "score": SCORE_MAP["acceptable"],
        }
        cache[cache_key] = {"hash": product_h, "verdict": verdict}
        return verdict

    correspondance = verdict.get("correspondance", "acceptable")
    if correspondance not in SCORE_MAP:
        correspondance = "acceptable"
        verdict["correspondance"] = correspondance
    verdict["score"] = SCORE_MAP[correspondance]

    cache[cache_key] = {"hash": product_h, "verdict": verdict}
    return verdict
