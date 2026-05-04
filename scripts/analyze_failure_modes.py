#!/usr/bin/env python3
"""
analyze_failure_modes.py — Failure Mode Analysis générique pour tout Pn.

Usage :
    python scripts/analyze_failure_modes.py --problem P3 --iteration 1
    python scripts/analyze_failure_modes.py --problem P5 --iteration 4 --max-cases 30

Charge `results/judge_verdicts_<N>.json`, lit la grille des modes
hypothétiques de `<P>` dans PROBLEMS.md, classifie chaque cas de divergence
via Claude Haiku, applique la grille de décision (≥85% mono / ≥15% multi /
hors-périmètre) et produit `reports/failure_modes_<P>.md`.

Un seul script paramétrable pour les 9 P (jamais dupliqué par Pn).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

def _import_anthropic():
    """Import paresseux pour permettre les tests offline (parsing) sans le SDK."""
    try:
        from anthropic import Anthropic
        return Anthropic
    except ImportError:
        print(
            "Erreur : package 'anthropic' non installé. "
            "Faire `pip install anthropic` (>=0.40.0).",
            file=sys.stderr,
        )
        sys.exit(1)


PROJECT_ROOT = Path(__file__).parent.parent
PROBLEMS_FILE = PROJECT_ROOT / "PROBLEMS.md"
RESULTS_DIR = PROJECT_ROOT / "results"
REPORTS_DIR = PROJECT_ROOT / "reports"

MODEL = "claude-haiku-4-5-20251001"
MAX_CASES_DEFAULT = 50
MIN_CASES_FOR_FMA = 10

# Seuils de la grille de décision (cf. CLAUDE.md §"Règle FMA universelle")
THRESHOLD_MONO_CAUSE = 0.85
THRESHOLD_MULTI = 0.15

# Modes considérés "hors périmètre prompt" (relèvent du sourcing/caractérisation)
HORS_PERIMETRE_KEYWORDS = (
    "data-gap",
    "extraction-failed",
    "sourcing-issue",
    "corpus-gap",
)


def parse_problem_modes(problem_id: str) -> tuple[str, list[dict]]:
    """Parse PROBLEMS.md et retourne (description_courte, modes).

    Cherche la fiche `### Pn — ...` puis extrait :
    - la **Description** (1-2 phrases du problème)
    - les modes hypothétiques sous la forme `- **Mode X** (`nom-court`) : ...`
    """
    if not PROBLEMS_FILE.exists():
        raise FileNotFoundError(f"PROBLEMS.md introuvable : {PROBLEMS_FILE}")
    content = PROBLEMS_FILE.read_text(encoding="utf-8")

    # Section du problème : de "### P3 — ..." jusqu'au prochain ### ou ##
    section_re = rf"### {re.escape(problem_id)} —[^\n]*\n(.*?)(?=\n### |\n## |\Z)"
    match = re.search(section_re, content, re.DOTALL)
    if not match:
        raise ValueError(
            f"Problème {problem_id} non trouvé dans PROBLEMS.md (cherché : `### {problem_id} — ...`)"
        )
    section = match.group(1)

    # Description : entre **Description** : et le prochain bloc **...**
    desc_match = re.search(
        r"\*\*Description\*\*\s*:\s*\n(.+?)(?=\n\n\*\*|\Z)",
        section,
        re.DOTALL,
    )
    description = desc_match.group(1).strip() if desc_match else "(non trouvée)"

    # Modes : "- **Mode X** (`nom-court`) : description (multi-ligne possible)"
    mode_re = (
        r"-\s*\*\*Mode (\w+)\*\*\s*\(`([^`]+)`\)\s*:\s*"
        r"((?:[^\n]+(?:\n  [^\n]+)*))"
    )
    modes = []
    for m in re.finditer(mode_re, section):
        modes.append(
            {
                "letter": m.group(1),
                "name": m.group(2),
                "description": re.sub(r"\s+", " ", m.group(3)).strip(),
            }
        )

    return description, modes


def load_verdicts(iteration_num: int) -> list[dict]:
    """Charge les verdicts du juge LLM pour l'itération donnée."""
    verdicts_file = RESULTS_DIR / f"judge_verdicts_{iteration_num:03d}.json"
    if not verdicts_file.exists():
        raise FileNotFoundError(
            f"Verdicts juge introuvables : {verdicts_file}.\n"
            f"Lancer d'abord le pipeline avec le juge LLM activé."
        )
    with open(verdicts_file, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_relevant_cases(verdicts: list[dict]) -> list[dict]:
    """Filtre les cas problématiques (acceptable + hors_sujet).

    Ce sont les produits remontés par l'API mais jugés non satisfaisants
    par le juge HelloPro — donc les cas de divergence pertinents pour FMA.
    """
    return [
        v
        for v in verdicts
        if (v.get("correspondance") or "").lower() in ("acceptable", "hors_sujet")
    ]


def classify_case(
    case: dict,
    modes: list[dict],
    problem_desc: str,
    problem_id: str,
    client,
) -> dict:
    """Demande à Haiku de classer le cas selon les modes hypothétiques."""
    valid_letters = {m["letter"].upper() for m in modes} | {"D"}

    modes_block = "\n".join(
        f"- Mode {m['letter']} (`{m['name']}`) : {m['description']}" for m in modes
    )
    modes_block += "\n- Mode D (`autre`) : ne rentre dans aucun mode ci-dessus."

    prompt = f"""Tu classifies un cas d'échec de scoring produit B2B HelloPro.

PROBLÈME ÉTUDIÉ : {problem_id}
{problem_desc}

MODES D'ÉCHEC HYPOTHÉTIQUES :
{modes_block}

CAS À CLASSIFIER :
- Parcours : {case.get('parcours_id', '?')}
- Produit ID : {case.get('id_produit', '?')}
- Verdict du juge HelloPro : {case.get('correspondance', '?')}
- Raison du juge : {case.get('raison', '(non précisée)')}

Quel mode d'échec correspond le mieux à ce cas ? Réponds UNIQUEMENT avec un JSON :
{{"mode": "A|B|C|D", "raison": "1 phrase courte expliquant ton choix"}}"""

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip() if resp.content else "{}"
        # Strip code fences
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```\s*$", "", raw)
        # Parse JSON (résilient aux artefacts)
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            raw = json_match.group(0)
        result = json.loads(raw)
    except Exception as e:
        return {"mode": "D", "raison": f"erreur classification : {type(e).__name__}"}

    mode = (result.get("mode") or "").upper()
    if mode not in valid_letters:
        mode = "D"
    return {"mode": mode, "raison": result.get("raison", "")}


def determine_verdict(counter: Counter, modes: list[dict], total_cases: int) -> dict:
    """Applique la grille de décision FMA (cf. CLAUDE.md)."""
    sample_size = sum(counter.values())

    if sample_size < MIN_CASES_FOR_FMA:
        return {
            "verdict": "Données insuffisantes",
            "levier": "Asymétriques par défaut (prudence — moins de 10 cas)",
            "note": f"Échantillon : {sample_size} cas (<{MIN_CASES_FOR_FMA})",
        }

    freq = {mode: count / sample_size for mode, count in counter.items()}
    sorted_freq = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    dominant_letter, dominant_freq = sorted_freq[0]

    # Récupérer le nom du mode dominant
    dominant_obj = next((m for m in modes if m["letter"] == dominant_letter), None)
    dominant_name = dominant_obj["name"] if dominant_obj else f"Mode-{dominant_letter}"

    # Cas hors-périmètre (sourcing / caractérisation amont)
    is_hors_perimetre = any(kw in dominant_name for kw in HORS_PERIMETRE_KEYWORDS)
    if is_hors_perimetre and dominant_freq >= THRESHOLD_MULTI:
        return {
            "verdict": "Hors périmètre",
            "levier": "Aucun levier prompt autorisé — ouvrir ticket chantier amont (caractérisation/sourcing)",
            "dominant": f"Mode {dominant_letter} (`{dominant_name}`) à {dominant_freq:.1%}",
        }

    # Mono-cause : un mode ≥ 85 %
    if dominant_freq >= THRESHOLD_MONO_CAUSE:
        return {
            "verdict": "Mono-cause",
            "levier": "Tous leviers autorisés (y compris symétriques : interdictions, restrictions, refonte)",
            "dominant": f"Mode {dominant_letter} (`{dominant_name}`) à {dominant_freq:.1%}",
        }

    # Multi-modes : plusieurs modes ≥ 15 %
    significant = [(m, f) for m, f in sorted_freq if f >= THRESHOLD_MULTI]
    if len(significant) >= 2:
        return {
            "verdict": "Multi-modes",
            "levier": "Asymétriques uniquement (ajout d'instruction/structure/étape — JAMAIS d'interdiction sur règles existantes)",
            "modes_significatifs": [
                f"Mode {m} à {f:.1%}" for m, f in significant
            ],
        }

    # Cas par défaut : mode dominant <85 % et un seul mode ≥15 %
    return {
        "verdict": "Mono-cause faible",
        "levier": "Asymétriques par défaut (prudence)",
        "dominant": f"Mode {dominant_letter} (`{dominant_name}`) à {dominant_freq:.1%}",
    }


def generate_report(
    problem_id: str,
    iteration_num: int,
    description: str,
    modes: list[dict],
    classifications: list[dict],
    decision: dict,
    total_divergent: int,
    sample_size: int,
) -> Path:
    """Génère reports/failure_modes_<P>.md."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORTS_DIR / f"failure_modes_{problem_id}.md"

    counter = Counter(c["mode"] for c in classifications)

    lines: list[str] = []
    lines.append(f"# FMA — {problem_id}")
    lines.append("")
    lines.append(f"**Date** : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(
        f"**Itération source** : {iteration_num} "
        f"(`results/judge_verdicts_{iteration_num:03d}.json`)"
    )
    lines.append(f"**Modèle classificateur** : `{MODEL}`")
    lines.append(f"**Cas divergents totaux** : {total_divergent}")
    lines.append(f"**Échantillon analysé** : {sample_size}")
    lines.append("")
    lines.append("## Problème étudié")
    lines.append("")
    lines.append(description)
    lines.append("")
    lines.append("## Verdict automatique")
    lines.append("")
    lines.append(f"- **Verdict** : **{decision['verdict']}**")
    lines.append(f"- **Levier autorisé** : {decision['levier']}")
    if "dominant" in decision:
        lines.append(f"- **Mode dominant** : {decision['dominant']}")
    if "modes_significatifs" in decision:
        lines.append(
            f"- **Modes significatifs** : {', '.join(decision['modes_significatifs'])}"
        )
    if "note" in decision:
        lines.append(f"- **Note** : {decision['note']}")
    lines.append("")

    lines.append("## Distribution des modes")
    lines.append("")
    lines.append("| Mode | Nom court | Fréquence | Nb cas |")
    lines.append("|---|---|---|---|")
    for m in modes:
        count = counter.get(m["letter"], 0)
        freq = (count / sample_size) if sample_size > 0 else 0.0
        lines.append(f"| {m['letter']} | `{m['name']}` | {freq:.1%} | {count} |")
    other = counter.get("D", 0)
    if other:
        freq = (other / sample_size) if sample_size > 0 else 0.0
        lines.append(f"| D | `autre` | {freq:.1%} | {other} |")
    lines.append("")

    lines.append("## Exemples par mode (jusqu'à 5 cas)")
    lines.append("")
    all_modes = list(modes) + [{"letter": "D", "name": "autre", "description": ""}]
    for m in all_modes:
        examples = [c for c in classifications if c["mode"] == m["letter"]][:5]
        if not examples:
            continue
        lines.append(f"### Mode {m['letter']} (`{m['name']}`)")
        lines.append("")
        for ex in examples:
            raison = (ex.get("raison") or "")[:200]
            classif = ex.get("classif_raison") or ""
            lines.append(
                f"- **Parcours** : `{ex['parcours_id']}` | **Produit** : `{ex['id_produit']}`"
            )
            lines.append(
                f"  - Verdict juge : **{ex['correspondance']}** — {raison}"
            )
            lines.append(f"  - Classification : *{classif}*")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Rapport généré par `scripts/analyze_failure_modes.py` — "
        "cf. CLAUDE.md §\"Règle FMA universelle\"._"
    )
    lines.append("")

    report_file.write_text("\n".join(lines), encoding="utf-8")
    return report_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FMA générique paramétré par Pn (un seul script pour tous les P).",
    )
    parser.add_argument(
        "--problem",
        required=True,
        help="Identifiant du problème (ex: P3, P5, P8). Doit exister dans PROBLEMS.md.",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        required=True,
        help="Numéro d'itération source (charge results/judge_verdicts_<N>.json)",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=MAX_CASES_DEFAULT,
        help=f"Échantillon maximum (défaut : {MAX_CASES_DEFAULT})",
    )
    args = parser.parse_args()

    print(f"=== FMA pour {args.problem} (itération source : {args.iteration}) ===")

    description, modes = parse_problem_modes(args.problem)
    if not modes:
        print(
            f"ERREUR : aucun mode hypothétique trouvé pour {args.problem} dans PROBLEMS.md",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Modes hypothétiques chargés : {len(modes)}")
    for m in modes:
        print(f"  - Mode {m['letter']} (`{m['name']}`)")

    verdicts = load_verdicts(args.iteration)
    print(f"Verdicts chargés : {len(verdicts)}")

    relevant = filter_relevant_cases(verdicts)
    print(f"Cas divergents (acceptable/hors_sujet) : {len(relevant)}")

    if len(relevant) < MIN_CASES_FOR_FMA:
        print(
            f"⚠ ATTENTION : moins de {MIN_CASES_FOR_FMA} cas — verdict 'Données insuffisantes'."
        )

    sample = relevant[: args.max_cases]
    print(f"Échantillon analysé : {len(sample)}")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERREUR : ANTHROPIC_API_KEY non défini", file=sys.stderr)
        sys.exit(1)
    Anthropic = _import_anthropic()
    client = Anthropic(api_key=api_key)

    print(f"\nClassification via {MODEL}...")
    classifications: list[dict] = []
    for i, case in enumerate(sample, 1):
        result = classify_case(case, modes, description, args.problem, client)
        classifications.append(
            {
                "parcours_id": case.get("parcours_id"),
                "id_produit": case.get("id_produit"),
                "correspondance": case.get("correspondance"),
                "raison": case.get("raison"),
                "mode": result["mode"],
                "classif_raison": result["raison"],
            }
        )
        if i % 10 == 0 or i == len(sample):
            print(f"  ... {i}/{len(sample)} cas traités")

    counter = Counter(c["mode"] for c in classifications)
    decision = determine_verdict(counter, modes, total_cases=len(relevant))

    print(f"\n=== Verdict ===")
    print(f"  Verdict : {decision['verdict']}")
    print(f"  Levier  : {decision['levier']}")
    if "dominant" in decision:
        print(f"  Mode dominant : {decision['dominant']}")
    if "modes_significatifs" in decision:
        print(f"  Modes significatifs : {decision['modes_significatifs']}")

    report_file = generate_report(
        problem_id=args.problem,
        iteration_num=args.iteration,
        description=description,
        modes=modes,
        classifications=classifications,
        decision=decision,
        total_divergent=len(relevant),
        sample_size=len(sample),
    )
    print(f"\nRapport généré : {report_file.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
