#!/usr/bin/env python3
"""
Flask dashboard pour l'optimisation scoring HelloPro.
Permet aux non-devs de lancer des itérations et suivre la progression en live.
"""

import json
import os
import re
import subprocess
import shutil
import threading
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response, redirect, url_for, flash

# Configuration — PROJECT_ROOT surchargeable en Docker via env var
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).parent.parent))
RESULTS_DIR = PROJECT_ROOT / "results"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# Config des cibles / seuils (modifiables via /config par un utilisateur humain)
CONFIG_DIR = PROJECT_ROOT / "config"
THRESHOLDS_FILE = CONFIG_DIR / "thresholds.json"
EVAL_FILE = PROJECT_ROOT / "EVAL.md"
EVAL_BACKUP_DIR = PROJECT_ROOT / "backup" / "eval"

DEFAULT_THRESHOLDS = {
    "taux_conformite":        {"target": 80,  "type": "min", "unit": "%", "label": "Taux de conformité",     "comparator": "≥"},
    "doublons":               {"target": 0,   "type": "max", "unit": "",  "label": "Doublons",                "comparator": "≤"},
    "diversite_fournisseurs": {"target": 3,   "type": "min", "unit": "",  "label": "Diversité fournisseurs",  "comparator": "≥"},
    "coherence_score":        {"target": 0.5, "type": "min", "unit": "",  "label": "Cohérence score",         "comparator": "≥"},
    "presence_estimatif":     {"target": 90,  "type": "min", "unit": "%", "label": "Présence estimatif",      "comparator": "≥"},
    "score_global":           {"target": 80,  "type": "min", "unit": "%", "label": "Score global",            "comparator": "≥"},
}

app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "hellopro-scoring-dashboard-dev")

# Sessions interactives : chaque itération maintient une conversation Claude
_sessions = {}  # {n: {"proc", "events", "new_event", "status", "log_file"}}


def _parse_stream_event(raw_line):
    """Parse une ligne stream-json Claude CLI. Retourne (texte_affichable, session_id|None)."""
    try:
        event = json.loads(raw_line)
    except (json.JSONDecodeError, TypeError):
        # Pas du JSON → traiter comme texte brut
        return (raw_line, None)

    session_id = event.get("session_id")
    text = ""
    etype = event.get("type", "")

    # content_block_delta → token de texte en streaming
    if etype == "content_block_delta":
        text = event.get("delta", {}).get("text", "")

    # assistant message (certaines versions CLI)
    elif etype == "assistant":
        msg = event.get("message", event)
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text += block.get("text", "")
        elif isinstance(content, str):
            text = content

    # result → fin de réponse, contient session_id
    elif etype == "result":
        session_id = event.get("session_id", session_id)

    return (text, session_id)


def _stdout_reader(proc, session):
    """Thread de lecture : parse le stream-json de Claude, pousse le texte dans events."""
    log_path = session["log_file"]
    try:
        with open(log_path, "a", encoding="utf-8") as logf:
            for raw_line in iter(proc.stdout.readline, ""):
                raw_line = raw_line.rstrip("\n\r")
                if not raw_line:
                    continue

                text, sid = _parse_stream_event(raw_line)

                if sid:
                    session["session_id"] = sid

                if text:
                    logf.write(text + "\n")
                    logf.flush()
                    session["events"].append({"type": "text", "data": text})
                    session["new_event"].set()
    except Exception as e:
        session["events"].append({"type": "error", "data": str(e)})
        session["new_event"].set()
    finally:
        proc.stdout.close()
        proc.wait()
        session["proc"] = None
        session["status"] = "waiting_input"
        session["events"].append({"type": "waiting_input"})
        session["new_event"].set()


def _launch_turn(n, prompt, is_first=False):
    """Lance un tour de conversation Claude (subprocess + reader thread)."""
    session = _sessions[n]
    claude_cmd = shutil.which("claude")

    cmd = [claude_cmd, "-p", prompt, "--output-format", "stream-json", "--verbose"]
    if not is_first and session.get("session_id"):
        cmd.extend(["--resume", session["session_id"]])
    elif not is_first:
        cmd.append("-c")  # Fallback si pas de session_id

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        cwd=str(PROJECT_ROOT),
        bufsize=1,
        env=env,
    )
    session["proc"] = proc
    session["status"] = "running"

    t = threading.Thread(target=_stdout_reader, args=(proc, session), daemon=True)
    t.start()


def load_metrics(iteration_num):
    """Charge les métriques d'une itération donnée"""
    metrics_file = RESULTS_DIR / f"metrics_{iteration_num:03d}.json"
    if metrics_file.exists():
        with open(metrics_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def load_latest_metrics():
    """Charge les dernières métriques disponibles"""
    # Trouver le fichier metrics_NNN.json le plus récent
    metrics_files = sorted(RESULTS_DIR.glob("metrics_*.json"), reverse=True)
    if metrics_files:
        return load_metrics(int(metrics_files[0].stem.split("_")[1]))
    return None


def load_baseline():
    """Charge la baseline"""
    baseline_file = PROJECT_ROOT / "BASELINE.json"
    if baseline_file.exists():
        with open(baseline_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _extract_decision(section_text: str) -> str:
    """Extrait la décision d'une section d'itération.

    Cherche un pattern de type `**Décision** : GARDÉ` ou `**Décision** : ROLLBACK`
    (insensible à la casse, accents optionnels). Retourne "GARDÉ", "ROLLBACK",
    ou "EN ATTENTE" si aucune décision claire.
    """
    # On tolère : **Décision** : GARDÉ | GARDE | ROLLBACK (avec ou sans espaces/ponctuation)
    m = re.search(
        r"\*\*\s*D[ée]cision\s*\*\*\s*[:：]?\s*([A-ZÉ\u00c9]+)",
        section_text,
        flags=re.IGNORECASE,
    )
    if not m:
        return "EN ATTENTE"
    verdict = m.group(1).upper().replace("É", "E")
    if "GARD" in verdict:
        return "GARDÉ"
    if "ROLLBACK" in verdict:
        return "ROLLBACK"
    return "EN ATTENTE"


def parse_iterations_md():
    """Parse ITERATIONS.md pour extraire l'historique avec décision réelle."""
    iterations_file = PROJECT_ROOT / "ITERATIONS.md"
    iterations = []

    if not iterations_file.exists():
        return iterations

    with open(iterations_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Découper en sections par "## Itération N" — garde le texte de chaque section
    # pour y chercher la décision.
    section_pattern = re.compile(
        r"## Itération (\d+) — \[?(.*?)\]?$",
        flags=re.MULTILINE,
    )
    matches = list(section_pattern.finditer(content))
    for i, m in enumerate(matches):
        iter_num = int(m.group(1))
        timestamp = m.group(2).strip()
        # Texte de la section : du début de ce match au début du suivant
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_text = content[start:end]

        decision = _extract_decision(section_text)
        # L'iter 0 n'a pas de décision à prendre : c'est la baseline, elle est
        # implicitement "GARDÉE" dès qu'elle existe.
        if iter_num == 0 and decision == "EN ATTENTE":
            decision = "GARDÉ"

        metrics = load_metrics(iter_num)
        if metrics:
            iterations.append({
                "number": iter_num,
                "timestamp": timestamp,
                "metrics": metrics,
                "decision": decision,
            })

    return sorted(iterations, key=lambda x: x["number"])


# Mapping problème → itération selon l'ordre d'attaque de CLAUDE.md :
# "Ordre itérations suggéré : P1 (iter 1), P3 (iter 2), P2 (iter 3),
#  P5 (iter 4), P6 (iter 5), P7 (iter 6), P8 (iter 7), P9 (iter 8)"
# P4 est un diagnostic, pas d'itération dédiée.
PROBLEM_TO_ITERATION = {1: 1, 2: 3, 3: 2, 4: None, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8}

# Persistance des problèmes custom (P1-P9 immuables restent hardcodés).
CUSTOM_PROBLEMS_FILE = PROJECT_ROOT / "custom_problems.json"
SEVERITIES = ["CRITIQUE", "ÉLEVÉE", "MODÉRÉE", "OBSERVATION"]
BASE_METRICS = [
    "Conformité",
    "Doublons",
    "Diversité fournisseurs",
    "Cohérence score/pertinence",
    "Présence estimatif",
    "Aberrations prix",
]


def load_custom_problems():
    """Charge les problèmes custom depuis le JSON dédié.

    Retourne toujours un dict avec les 3 clés attendues, même si le fichier
    n'existe pas encore (défaut à la première création).
    `next_iteration` commence à 9 car 0-8 sont réservés aux originaux.
    """
    default = {"next_iteration": 9, "custom_metrics": [], "problems": []}
    if not CUSTOM_PROBLEMS_FILE.exists():
        return default
    try:
        with open(CUSTOM_PROBLEMS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return default
    # Garanties de robustesse
    data.setdefault("next_iteration", 9)
    data.setdefault("custom_metrics", [])
    data.setdefault("problems", [])
    return data


def save_custom_problems(data):
    """Sauvegarde atomique : écrit dans un .tmp puis rename."""
    tmp = CUSTOM_PROBLEMS_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(CUSTOM_PROBLEMS_FILE)


def get_all_metrics():
    """Liste complète des métriques proposées (base + custom dédupliquées)."""
    data = load_custom_problems()
    seen = list(BASE_METRICS)
    for m in data.get("custom_metrics", []):
        if m and m not in seen:
            seen.append(m)
    return seen


def parse_problems_md():
    """Retourne la liste des problèmes (9 originaux immuables + customs).

    Les 9 problèmes P1-P9 sont hardcodés (miroir fidèle de PROBLEMS.md qui
    reste intouchée conformément à CLAUDE.md). Les problèmes custom sont
    chargés depuis `custom_problems.json`.

    L'état réel (running/waiting/done/never) est calculé côté template à partir
    de iteration_states. Pas de statut statique ici.
    """
    problems = []

    # Problèmes originaux P1-P9 (immuables, miroir de PROBLEMS.md)
    official = [
        {
            "number": 1,
            "name": "Absence caractéristique → pénalité manquante",
            "severity": "CRITIQUE",
            "description": "Quand une caractéristique requise est absente du produit, le score actuel = 0 (neutre). Le système devrait appliquer une pénalité (ex: -0.5) plutôt que d'ignorer l'absence.",
            "metrics": ["Conformité"],
        },
        {
            "number": 2,
            "name": "Produits hors catégorie remontent trop haut",
            "severity": "CRITIQUE",
            "description": "Certains produits ne correspondent pas au besoin exprimé (ex: distributeur comptoir au lieu de sur-pied) mais restent dans le top 5 recommandé. Le LLM reranker doit mieux filtrer ces cas.",
            "metrics": ["Conformité"],
        },
        {
            "number": 3,
            "name": "LLM juge sur titre seul, ignore descriptif",
            "severity": "CRITIQUE",
            "description": "Le LLM analyse le titre du produit sans tenir compte de sa description technique. Exemple: 'Tracteur' remonte même si le type (vigneron vs standard) ne correspond pas au besoin.",
            "metrics": ["Conformité", "Cohérence score/pertinence"],
        },
        {
            "number": 4,
            "name": "86% Prix sur demande (diagnostic)",
            "severity": "OBSERVATION",
            "description": "Manque massif de données pricing chez les fournisseurs. Impact : estimatif imprécis, impossible de détecter aberrations prix. À ignorer pour les itérations (limité par les données sources).",
            "metrics": ["Aberrations prix"],
        },
        {
            "number": 5,
            "name": "Zéro résultat certains parcours",
            "severity": "ÉLEVÉE",
            "description": "Certains parcours ne retournent aucun produit conforme. Cause possible : liste_caracteristique trop restrictive, ou Cypher/logique matching trop stricte.",
            "metrics": ["Conformité"],
        },
        {
            "number": 6,
            "name": "Mélange produits neuf/occasion",
            "severity": "ÉLEVÉE",
            "description": "Quand le parcours spécifie 'Neuf', l'API retourne aussi des produits d'occasion. Le filtre sur etat_produit ne fonctionne pas correctement.",
            "metrics": ["Conformité", "Doublons"],
        },
        {
            "number": 7,
            "name": "Doublons et surreprésentation fournisseur",
            "severity": "MODÉRÉE",
            "description": "La même marque/fournisseur apparaît plusieurs fois dans le top 5 (ex: même modèle en deux variantes). Le système doit diversifier par fournisseur.",
            "metrics": ["Doublons", "Diversité fournisseurs"],
        },
        {
            "number": 8,
            "name": "Caractéristiques discriminantes ignorées",
            "severity": "MODÉRÉE",
            "description": "Certaines caractéristiques critiques (ex: largeur de passage pour minipelle) ne sont pas prises en compte par le scoring, ou ont un poids insuffisant.",
            "metrics": ["Conformité", "Cohérence score/pertinence"],
        },
        {
            "number": 9,
            "name": "Sélections trop restreintes ou hors sujet",
            "severity": "MODÉRÉE",
            "description": "Inversement de P5 : certains parcours retournent des produits non pertinents ou trop restrictifs. Exemple : un filtre sur capacité exclut tous les produits viables.",
            "metrics": ["Conformité", "Diversité fournisseurs"],
        },
    ]
    for p in official:
        problems.append({
            "number": p["number"],
            "name": p["name"],
            "iteration": PROBLEM_TO_ITERATION.get(p["number"]),
            "immutable": True,
            "severity": p["severity"],
            "description": p["description"],
            "metrics": p["metrics"],
        })

    # Problèmes custom
    for cp in load_custom_problems()["problems"]:
        problems.append({
            "number": cp.get("number"),
            "name": cp.get("name", ""),
            "iteration": cp.get("iteration"),
            "immutable": False,
            "severity": cp.get("severity", "MODÉRÉE"),
            "description": cp.get("description", ""),
            "metrics": cp.get("metrics", []),
        })

    return problems


def format_metric_value(name, value):
    """Formate une métrique pour l'affichage"""
    if value is None:
        return "—"

    percent_metrics = {"taux_conformite", "presence_estimatif", "score_global"}

    if name in percent_metrics:
        return f"{value:.1f}%"
    elif name == "coherence_score":
        return f"{value:.2f}"
    else:
        return str(int(value))


def load_thresholds() -> dict:
    """Charge les cibles/seuils depuis config/thresholds.json.
    Fallback sur DEFAULT_THRESHOLDS si le fichier n'existe pas (1er lancement)."""
    if not THRESHOLDS_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        THRESHOLDS_FILE.write_text(
            json.dumps(DEFAULT_THRESHOLDS, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return dict(DEFAULT_THRESHOLDS)
    try:
        return json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_THRESHOLDS)


def _build_eval_table(thresholds: dict) -> str:
    """Reconstruit le tableau markdown des métriques pour EVAL.md."""
    header = (
        "| Métrique | Description | Seuil cible |\n"
        "|---|---|---|\n"
    )
    descriptions = {
        "taux_conformite": "% de produits de la sélection qui correspondent au besoin",
        "doublons": "Produits identiques ou quasi-identiques dans la sélection",
        "diversite_fournisseurs": "Nombre de fournisseurs différents (si disponibles)",
        "coherence_score": "Les produits les mieux scorés sont les plus pertinents",
        "presence_estimatif": "Un estimatif est présenté quand les données le permettent",
    }
    # Ordre officiel (cf. EVAL.md)
    order = [
        "taux_conformite",
        "doublons",
        "diversite_fournisseurs",
        "coherence_score",
        "presence_estimatif",
    ]
    rows = []
    for name in order:
        if name not in thresholds:
            continue
        t = thresholds[name]
        label = t.get("label", name)
        target = t.get("target")
        unit = t.get("unit", "")
        comp = t.get("comparator", "≥")
        # Cas spéciaux pour rester fidèle au format original d'EVAL.md
        if name == "doublons":
            seuil = "0"
        elif name == "coherence_score":
            seuil = "Corrélation positive"
        else:
            # Formater sans décimale superflue
            if isinstance(target, float) and target.is_integer():
                target_str = str(int(target))
            else:
                target_str = str(target)
            seuil = f"{comp} {target_str}{unit}"
        desc = descriptions.get(name, "")
        rows.append(f"| {label} | {desc} | {seuil} |")
    return header + "\n".join(rows) + "\n"


def save_thresholds(new_values: dict) -> str:
    """Sauvegarde les nouvelles valeurs de cibles.

    new_values: {metric_name: float_or_int}
    Retourne le nom du fichier backup créé (ou "" si EVAL.md absent).
    """
    # 1. Backup EVAL.md s'il existe
    EVAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_name = ""
    if EVAL_FILE.exists():
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_name = f"EVAL_{ts}.md"
        shutil.copy(EVAL_FILE, EVAL_BACKUP_DIR / backup_name)

    # 2. Charger les seuils actuels et mettre à jour les targets
    current = load_thresholds()
    for name, value in new_values.items():
        if name in current:
            current[name]["target"] = value

    # 3. Réécrire le tableau dans EVAL.md (regex sur le bloc métriques)
    if EVAL_FILE.exists():
        eval_content = EVAL_FILE.read_text(encoding="utf-8")
        new_table = _build_eval_table(current)
        eval_content = re.sub(
            r"(## Métriques principales\n\n)(.*?)(\n## Définition de \"conforme\")",
            lambda m: m.group(1) + new_table + m.group(3),
            eval_content,
            count=1,
            flags=re.DOTALL,
        )
        EVAL_FILE.write_text(eval_content, encoding="utf-8")

    # 4. Écrire config/thresholds.json
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    THRESHOLDS_FILE.write_text(
        json.dumps(current, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return backup_name


def list_eval_backups() -> list:
    """Retourne la liste des backups EVAL.md triés par date décroissante.
    Chaque entrée : {filename, timestamp_display}."""
    if not EVAL_BACKUP_DIR.exists():
        return []
    files = sorted(
        [f for f in EVAL_BACKUP_DIR.glob("EVAL_*.md")],
        key=lambda p: p.name,
        reverse=True,
    )
    result = []
    for f in files:
        # Extraire timestamp du nom: EVAL_YYYYMMDD_HHMMSS.md
        m = re.match(r"EVAL_(\d{8})_(\d{6})\.md", f.name)
        if m:
            date_part, time_part = m.group(1), m.group(2)
            display = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} {time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
        else:
            display = f.name
        result.append({"filename": f.name, "timestamp_display": display})
    return result


def get_metric_status(name, value):
    """Retourne le statut (🟢/🔴/⚪) d'une métrique contre sa cible."""
    if value is None:
        return "⚪"

    thresholds = load_thresholds()
    if name not in thresholds:
        return "⚪"

    threshold = thresholds[name]
    target = threshold.get("target")
    if target is None:
        return "⚪"

    if threshold.get("type") == "min":
        return "🟢" if value >= target else "🔴"
    else:  # max
        return "🟢" if value <= target else "🔴"


def get_iteration_states(max_n: int = 8) -> dict:
    """
    Retourne l'état de chaque itération 0..max_n + itérations custom.

    États possibles (ordre de priorité) :
    - "running"  : Claude exécute activement un tour
    - "starting" : session en cours de démarrage

    Cas spécial iter 0 (baseline) : le CP1 de CLAUDE.md fait que Claude termine
    toujours en posant "Accord pour lancer iter 1 ?" (question cosmétique de
    validation, les metrics sont déjà produites). Pour iter 0 uniquement, si
    metrics_000.json existe, on force l'état "done" pour ne pas bloquer l'UI.
    Pour iter 1..8, un "waiting_input" reste bloquant (vraie question Claude).
    """
    # Étendre max_n pour couvrir les itérations custom (9+)
    custom_iters = [cp.get("iteration") for cp in load_custom_problems()["problems"]]
    custom_iters = [i for i in custom_iters if isinstance(i, int)]
    if custom_iters:
        max_n = max(max_n, max(custom_iters))

    states = {}
    for n in range(max_n + 1):
        metrics_file = RESULTS_DIR / f"metrics_{n:03d}.json"
        metrics_exists = metrics_file.exists()

        session = _sessions.get(n)
        session_status = session.get("status") if session else None

        if session_status == "running":
            state = "running"
        elif session_status == "starting":
            state = "starting"
        elif n == 0 and metrics_exists:
            # Iter 0 = baseline : CP1 toujours en "waiting" cosmétique, on override
            state = "done"
        elif session_status == "waiting_input":
            state = "waiting"
        elif metrics_exists:
            # Les métriques sont la vérité terrain : une itération qui a produit
            # metrics_NNN.json est terminée, peu importe que la conversation
            # Claude reste ouverte.
            state = "done"
        elif session_status == "waiting_input":
            state = "waiting"
        else:
            state = "never"

        states[n] = state
    return states


@app.context_processor
def inject_thresholds():
    """Rend `thresholds` accessible dans TOUS les templates (index, iteration_detail, etc.)."""
    return {"thresholds": load_thresholds()}


@app.route("/")
def index():
    """Page principale — tableau de bord"""
    latest_metrics = load_latest_metrics()
    baseline = load_baseline()
    iterations = parse_iterations_md()
    iteration_states = get_iteration_states()
    custom_problems = load_custom_problems()["problems"]

    # Déterminer si on est en CP1 (baseline non validée)
    in_cp1 = (baseline and baseline.get("_status") == "EN ATTENTE") or latest_metrics is None

    return render_template("index.html",
                          metrics=latest_metrics,
                          baseline=baseline,
                          iterations=iterations,
                          iteration_states=iteration_states,
                          custom_problems=custom_problems,
                          format_metric=format_metric_value,
                          get_status=get_metric_status,
                          in_cp1=in_cp1)


@app.route("/api/iteration-states")
def api_iteration_states():
    """API JSON — retourne l'état de toutes les itérations (pour polling live)."""
    return jsonify(get_iteration_states())


@app.route("/api/kept-iterations")
def api_kept_iterations():
    """Liste triée des itérations dont la décision est GARDÉ.

    Utilisé par le frontend pour déclencher un rafraîchissement du tableau
    de bord dès qu'une nouvelle itération GARDÉ est détectée (les KPIs
    doivent alors refléter les nouvelles métriques).
    """
    iters = parse_iterations_md()
    kept = sorted([it["number"] for it in iters if it.get("decision") == "GARDÉ"])
    return jsonify({"kept": kept})


@app.route("/iterations")
def iterations():
    """Page — historique des itérations"""
    iterations_list = parse_iterations_md()

    iterations_file = PROJECT_ROOT / "ITERATIONS.md"
    iterations_raw = ""
    if iterations_file.exists():
        with open(iterations_file, "r", encoding="utf-8") as f:
            iterations_raw = f.read()

    return render_template("iterations.html",
                          iterations=iterations_list,
                          iterations_raw=iterations_raw,
                          format_metric=format_metric_value,
                          get_status=get_metric_status)


@app.route("/iterations/<int:n>")
def iteration_detail(n):
    """Page — détail d'une itération"""
    metrics = load_metrics(n)
    iteration_file = RESULTS_DIR / f"iteration_{n:03d}.json"

    parcours_results = {}
    if iteration_file.exists():
        with open(iteration_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Extraire les résultats par parcours
            if "resultats" in data:
                parcours_results = {pid: result.get("api_response", {}).get("top_produit", [])[:3]
                                    for pid, result in data["resultats"].items()}

    return render_template("iteration_detail.html",
                          iteration_num=n,
                          metrics=metrics,
                          parcours_results=parcours_results,
                          format_metric=format_metric_value)


@app.route("/problems")
def problems():
    """Page — statut des 9 problèmes P1-P9 + problèmes custom."""
    problems_list = parse_problems_md()
    iterations_list = parse_iterations_md()
    iteration_states = get_iteration_states()
    custom_data = load_custom_problems()

    return render_template("problems.html",
                          problems=problems_list,
                          iterations=iterations_list,
                          iteration_states=iteration_states,
                          severities=SEVERITIES,
                          metrics=get_all_metrics(),
                          next_iteration=custom_data["next_iteration"])


@app.route("/api/problems", methods=["GET"])
def api_problems_list():
    """Liste complète (originaux + customs) + listes de choix pour les forms."""
    return jsonify({
        "problems": parse_problems_md(),
        "severities": SEVERITIES,
        "metrics": get_all_metrics(),
        "next_iteration": load_custom_problems()["next_iteration"],
    })


@app.route("/api/problems", methods=["POST"])
def api_problems_create():
    """Crée un nouveau problème custom.

    Body JSON : {name, severity, description, metrics: [...]}
    Le numéro d'itération est auto-incrémenté à partir de 9 (réservés 0-8).
    Les métriques inconnues sont ajoutées à la liste globale custom_metrics.
    """
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    severity = (body.get("severity") or "").strip()
    description = (body.get("description") or "").strip()
    metrics = body.get("metrics") or []

    if not name:
        return jsonify({"error": "Le libellé est obligatoire"}), 400
    if severity not in SEVERITIES:
        return jsonify({"error": f"Sévérité invalide. Valeurs acceptées : {SEVERITIES}"}), 400
    if not description:
        return jsonify({"error": "La description est obligatoire"}), 400
    if not isinstance(metrics, list):
        return jsonify({"error": "metrics doit être une liste"}), 400

    # Nettoyer et dédupliquer les métriques
    clean_metrics = []
    for m in metrics:
        if isinstance(m, str) and m.strip() and m.strip() not in clean_metrics:
            clean_metrics.append(m.strip())

    data = load_custom_problems()

    # Ajouter les nouvelles métriques (hors base) au pool global
    known = set(BASE_METRICS) | set(data.get("custom_metrics", []))
    for m in clean_metrics:
        if m not in known:
            data.setdefault("custom_metrics", []).append(m)
            known.add(m)

    # Numéro de problème : max existant (>= 10) ou 10 si aucun
    existing_numbers = [p.get("number", 0) for p in data["problems"]]
    next_number = max(existing_numbers + [9]) + 1

    problem = {
        "number": next_number,
        "name": name,
        "severity": severity,
        "iteration": data["next_iteration"],
        "description": description,
        "metrics": clean_metrics,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    data["problems"].append(problem)
    data["next_iteration"] += 1
    save_custom_problems(data)

    return jsonify({"status": "created", "problem": problem}), 201


@app.route("/api/problems/<int:number>", methods=["PATCH"])
def api_problems_update(number):
    """Modifie un problème custom (P1-P9 immuables : refus 403).

    Champs modifiables : name, severity, description, metrics.
    Le numéro et l'itération ne sont jamais modifiables.
    """
    if number <= 9:
        return jsonify({"error": "Les problèmes P1-P9 sont immuables"}), 403

    body = request.get_json(silent=True) or {}
    data = load_custom_problems()

    target = next((p for p in data["problems"] if p.get("number") == number), None)
    if target is None:
        return jsonify({"error": "Problème introuvable"}), 404

    if "name" in body:
        name = (body["name"] or "").strip()
        if not name:
            return jsonify({"error": "Le libellé ne peut pas être vide"}), 400
        target["name"] = name

    if "severity" in body:
        if body["severity"] not in SEVERITIES:
            return jsonify({"error": f"Sévérité invalide. Valeurs acceptées : {SEVERITIES}"}), 400
        target["severity"] = body["severity"]

    if "description" in body:
        description = (body["description"] or "").strip()
        if not description:
            return jsonify({"error": "La description ne peut pas être vide"}), 400
        target["description"] = description

    if "metrics" in body:
        metrics = body["metrics"]
        if not isinstance(metrics, list):
            return jsonify({"error": "metrics doit être une liste"}), 400
        clean_metrics = []
        for m in metrics:
            if isinstance(m, str) and m.strip() and m.strip() not in clean_metrics:
                clean_metrics.append(m.strip())
        # Ajouter les nouvelles au pool global
        known = set(BASE_METRICS) | set(data.get("custom_metrics", []))
        for m in clean_metrics:
            if m not in known:
                data.setdefault("custom_metrics", []).append(m)
                known.add(m)
        target["metrics"] = clean_metrics

    save_custom_problems(data)
    return jsonify({"status": "updated", "problem": target})


@app.route("/api/problems/<int:number>", methods=["DELETE"])
def api_problems_delete(number):
    """Supprime un problème custom (P1-P9 immuables : refus 403).

    Ne décrémente PAS next_iteration pour éviter toute collision avec un
    éventuel metrics_NNN.json déjà généré pour cette itération.
    """
    if number <= 9:
        return jsonify({"error": "Les problèmes P1-P9 sont immuables"}), 403

    data = load_custom_problems()
    before = len(data["problems"])
    data["problems"] = [p for p in data["problems"] if p.get("number") != number]
    if len(data["problems"]) == before:
        return jsonify({"error": "Problème introuvable"}), 404

    save_custom_problems(data)
    return jsonify({"status": "deleted", "number": number})


@app.route("/manuel")
def manuel():
    """Page — manuel utilisateur (rendu de MANUEL_UTILISATEUR.md)."""
    manuel_file = PROJECT_ROOT / "MANUEL_UTILISATEUR.md"
    content = ""
    if manuel_file.exists():
        with open(manuel_file, "r", encoding="utf-8") as f:
            content = f.read()
    return render_template("manuel.html", manuel_content=content)


@app.route("/config", methods=["GET", "POST"])
def config_page():
    """Page admin — modifier les cibles/seuils d'affichage.

    GET  : affiche le formulaire pré-rempli avec les valeurs courantes.
    POST : valide, sauvegarde (backup EVAL.md + MAJ config/thresholds.json + MAJ EVAL.md)
           puis redirige vers GET avec un flash message.
    """
    if request.method == "POST":
        action = request.form.get("action", "save")

        if action == "reset":
            new_values = {k: v["target"] for k, v in DEFAULT_THRESHOLDS.items()}
        else:
            new_values = {}
            errors = []
            for name in DEFAULT_THRESHOLDS.keys():
                raw = request.form.get(name, "").strip()
                if raw == "":
                    errors.append(f"Champ '{name}' vide")
                    continue
                try:
                    val = float(raw)
                except ValueError:
                    errors.append(f"Champ '{name}' n'est pas un nombre : {raw!r}")
                    continue
                if val < 0:
                    errors.append(f"Champ '{name}' ne peut pas être négatif")
                    continue
                # Validation par type de métrique
                if name in ("doublons", "diversite_fournisseurs"):
                    new_values[name] = int(val)
                elif name in ("taux_conformite", "presence_estimatif", "score_global"):
                    if val > 100:
                        errors.append(f"Champ '{name}' ne peut pas dépasser 100%")
                        continue
                    # int si entier (évite l'affichage "85.0%"), sinon float
                    new_values[name] = int(val) if val.is_integer() else val
                else:  # coherence_score
                    if val > 1:
                        errors.append(f"Champ '{name}' ne peut pas dépasser 1")
                        continue
                    new_values[name] = val

            if errors:
                for e in errors:
                    flash(e, "error")
                return redirect(url_for("config_page"))

        backup_name = save_thresholds(new_values)
        if action == "reset":
            flash(f"Cibles réinitialisées aux valeurs par défaut. Backup : {backup_name}", "success")
        else:
            flash(f"Cibles mises à jour. Backup EVAL.md : {backup_name}", "success")
        return redirect(url_for("config_page"))

    # GET
    return render_template(
        "config.html",
        history=list_eval_backups(),
    )


@app.route("/config/backup/<filename>")
def config_backup_download(filename):
    """Sert un backup EVAL.md en lecture seule pour historique."""
    # Sécurité : pas de traversée de dossier, uniquement les fichiers EVAL_*.md
    if not re.match(r"^EVAL_\d{8}_\d{6}\.md$", filename):
        return "Invalid filename", 400
    target = EVAL_BACKUP_DIR / filename
    if not target.exists():
        return "Not found", 404
    return Response(
        target.read_text(encoding="utf-8"),
        mimetype="text/markdown; charset=utf-8",
    )


@app.route("/api/metrics/latest")
def api_metrics_latest():
    """API — retourne les dernières métriques en JSON (pour polling)"""
    metrics = load_latest_metrics()
    return jsonify(metrics or {})


# Templates utilisés par le mode `full` de /reset-all pour réinitialiser
# les fichiers d'état local (baseline, journal d'itérations, problèmes custom).
BASELINE_TEMPLATE = {
    "_info": "Baseline de l'itération 0. Sera générée au premier run d'iter 0.",
    "_status": "NON_GÉNÉRÉ",
    "generated_at": None,
    "parcours_count": None,
    "metrics": {
        "taux_conformite": None,
        "doublons": None,
        "diversite_fournisseurs": None,
        "coherence_score_pertinence": None,
        "presence_estimatif": None,
        "score_global": None,
    },
}

ITERATIONS_TEMPLATE = (
    "# Journal des itérations — Optimisation Scoring HelloPro\n"
    "\n"
    "> Ce fichier est APPEND-ONLY. Ne jamais supprimer ou modifier une entrée existante.\n"
    "> Débute à l'itération 0 (baseline).\n"
    "\n"
    "<!-- Les itérations apparaîtront ci-dessous au format défini dans CLAUDE.md §Format ITERATIONS.md -->\n"
)

CUSTOM_PROBLEMS_TEMPLATE = {
    "next_iteration": 9,
    "custom_metrics": [],
    "problems": [],
}


def _full_wipe():
    """Supprime tout l'état local de dev, réécrit les templates vides.

    Utilisé par /reset-all mode=full pour préparer une livraison ou repartir
    d'un état vierge. À la différence du mode archive :
    - Supprime (au lieu de déplacer) tous les artefacts de run
    - Réécrit BASELINE.json, ITERATIONS.md, custom_problems.json en templates
    - Ne touche JAMAIS aux fichiers immuables (EVAL.md, PROBLEMS.md, CLAUDE.md,
      test_data/parcours.json, config/*) ni aux secrets (.env)

    Retourne un dict récapitulant les suppressions effectuées.
    """
    removed = {
        "dashboard_logs": [],
        "api_logs": [],
        "results_files": [],
        "results_backup": False,
        "dashboard_logs_backup": False,
        "flask_logs": [],
        "templates_rewritten": [],
    }

    # 1. Supprimer les logs dashboard (iteration_*.log + backup)
    dashboard_logs_dir = PROJECT_ROOT / "dashboard" / "logs"
    if dashboard_logs_dir.exists():
        for log_file in dashboard_logs_dir.glob("iteration_*.log"):
            try:
                log_file.unlink()
                removed["dashboard_logs"].append(log_file.name)
            except OSError:
                pass
        backup_dir = dashboard_logs_dir / "backup"
        if backup_dir.exists():
            try:
                shutil.rmtree(backup_dir)
                removed["dashboard_logs_backup"] = True
            except OSError:
                pass

    # 2. Supprimer les logs API (logs/api_iteration_*.log)
    api_logs_dir = PROJECT_ROOT / "logs"
    if api_logs_dir.exists():
        for log_file in api_logs_dir.glob("api_iteration_*.log"):
            try:
                log_file.unlink()
                removed["api_logs"].append(log_file.name)
            except OSError:
                pass

    # 3. Supprimer les fichiers de résultats + dossier backup complet
    if RESULTS_DIR.exists():
        for pattern in ("metrics_*.json", "iteration_*.json"):
            for f in RESULTS_DIR.glob(pattern):
                try:
                    f.unlink()
                    removed["results_files"].append(f.name)
                except OSError:
                    pass
        results_backup = RESULTS_DIR / "backup"
        if results_backup.exists():
            try:
                shutil.rmtree(results_backup)
                removed["results_backup"] = True
            except OSError:
                pass

    # 4. Supprimer les logs Flask à la racine
    for flask_log in (PROJECT_ROOT / "debug_flask.log", PROJECT_ROOT / "dashboard" / "flask.log"):
        if flask_log.exists():
            try:
                flask_log.unlink()
                removed["flask_logs"].append(str(flask_log.relative_to(PROJECT_ROOT)))
            except OSError:
                pass

    # 5. Réécrire les templates vides (état attendu pour une nouvelle install)
    try:
        (PROJECT_ROOT / "BASELINE.json").write_text(
            json.dumps(BASELINE_TEMPLATE, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        removed["templates_rewritten"].append("BASELINE.json")
    except OSError:
        pass
    try:
        (PROJECT_ROOT / "ITERATIONS.md").write_text(
            ITERATIONS_TEMPLATE, encoding="utf-8"
        )
        removed["templates_rewritten"].append("ITERATIONS.md")
    except OSError:
        pass
    try:
        (PROJECT_ROOT / "custom_problems.json").write_text(
            json.dumps(CUSTOM_PROBLEMS_TEMPLATE, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        removed["templates_rewritten"].append("custom_problems.json")
    except OSError:
        pass

    return removed


@app.route("/reset-all", methods=["POST"])
def reset_all():
    """Stoppe toutes les sessions et nettoie l'état local.

    Deux modes (body JSON : `{"mode": "archive"|"full"}`, défaut "archive") :

    - **archive** (défaut, comportement historique) : archive (déplace) logs
      dashboard + résultats dans des sous-dossiers `backup/<timestamp>/`.
      Déclenché par le bouton Iter 0 du dashboard. Non-destructif.

    - **full** : destructif. Supprime tous les artefacts de runs (logs API,
      logs dashboard, résultats, backups), puis réécrit BASELINE.json /
      ITERATIONS.md / custom_problems.json en templates vides. Utilisé pour
      préparer une livraison à un nouveau client. Voir INSTALLATION_VM_ADMIN.md.

    Fichiers immuables toujours préservés : EVAL.md, PROBLEMS.md, CLAUDE.md,
    test_data/parcours.json, config/* (cf. CLAUDE.md).
    """
    mode = (request.get_json(silent=True) or {}).get("mode", "archive")
    if mode not in ("archive", "full"):
        return jsonify({"error": f"Mode invalide : {mode}. Valeurs acceptées : archive, full"}), 400

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # 1. Terminer tous les subprocess actifs (commun aux deux modes)
    stopped = []
    for n, session in list(_sessions.items()):
        proc = session.get("proc")
        if proc:
            try:
                proc.terminate()
                stopped.append(n)
            except Exception:
                pass
        # Libérer les threads SSE bloqués sur flag.wait()
        flag = session.get("new_event")
        if flag:
            flag.set()

    # 2. Vider le registre de sessions mémoire (commun)
    _sessions.clear()

    # 3. Mode full : wipe destructif + templates, retour immédiat
    if mode == "full":
        removed = _full_wipe()
        return jsonify({
            "status": "reset",
            "mode": "full",
            "stopped_sessions": stopped,
            "removed": removed,
        })

    # 4. Mode archive (défaut) : déplace les logs dashboard
    logs_dir = PROJECT_ROOT / "dashboard" / "logs"
    archived_logs = []
    if logs_dir.exists():
        logs_backup = logs_dir / "backup" / timestamp
        for log_file in logs_dir.glob("iteration_*.log"):
            logs_backup.mkdir(parents=True, exist_ok=True)
            target = logs_backup / log_file.name
            try:
                shutil.move(str(log_file), str(target))
                archived_logs.append(log_file.name)
            except Exception:
                pass

    # 5. Mode archive : déplace les résultats pour que les boutons repassent en "never"
    archived_results = []
    if RESULTS_DIR.exists():
        results_backup = RESULTS_DIR / "backup" / timestamp
        patterns = ("metrics_*.json", "iteration_*.json")
        for pattern in patterns:
            for f in RESULTS_DIR.glob(pattern):
                results_backup.mkdir(parents=True, exist_ok=True)
                target = results_backup / f.name
                try:
                    shutil.move(str(f), str(target))
                    archived_results.append(f.name)
                except Exception:
                    pass

    return jsonify({
        "status": "reset",
        "mode": "archive",
        "backup_timestamp": timestamp,
        "stopped_sessions": stopped,
        "archived_logs": archived_logs,
        "archived_results": archived_results,
    })


@app.route("/iterate/<int:n>/session-info")
def session_info(n):
    """Retourne l'état en mémoire de la session N — sert à décider côté UI
    si un reclic sur le bouton doit reprendre la session ou en relancer une."""
    session = _sessions.get(n)
    metrics_exists = (RESULTS_DIR / f"metrics_{n:03d}.json").exists()
    if not session:
        return jsonify({
            "exists": False,
            "status": None,
            "has_events": False,
            "metrics_exists": metrics_exists,
        })
    return jsonify({
        "exists": True,
        "status": session.get("status"),
        "has_events": len(session.get("events", [])) > 0,
        "metrics_exists": metrics_exists,
    })


def build_iterate_prompt(n: int) -> str:
    """Construit le prompt envoyé à Claude CLI pour l'itération N.

    Claude CLI 2.x en mode `-p` ne résout pas les slash commands projet
    (`.claude/commands/*.md`) — Claude renvoie `"Unknown command: /iterate"`.
    On lit donc le contenu de `.claude/commands/iterate.md` et on l'injecte
    comme prompt brut. Le fichier reste la source de vérité du skill.

    Pour les itérations custom (N >= 9) → on ajoute en suffixe le libellé,
    la sévérité, la description et les métriques affectées lus depuis
    `custom_problems.json`.
    """
    # Charger le corps du skill depuis .claude/commands/iterate.md
    skill_file = PROJECT_ROOT / ".claude" / "commands" / "iterate.md"
    if skill_file.exists():
        content = skill_file.read_text(encoding="utf-8")
        # Retirer le frontmatter YAML (entre `---` et `---`) s'il est présent
        if content.lstrip().startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].lstrip()
        # Substituer $ARGUMENTS par le numéro d'itération
        base = content.replace("$ARGUMENTS", str(n))
    else:
        # Fallback si le skill manque (ne devrait pas arriver)
        base = f"Exécute l'itération {n} du protocole décrit dans CLAUDE.md"

    if n <= 8:
        return base

    custom = next(
        (p for p in load_custom_problems()["problems"] if p.get("iteration") == n),
        None,
    )
    if not custom:
        return base  # Itération orpheline (problème supprimé) → fallback

    metrics_line = ", ".join(custom.get("metrics") or []) or "non précisées"
    context = (
        f"\n\n---\n"
        f"**Problème custom P{custom.get('number')}** (hors PROBLEMS.md, défini par l'utilisateur via le dashboard)\n\n"
        f"- Libellé : {custom.get('name', '')}\n"
        f"- Sévérité : {custom.get('severity', 'MODÉRÉE')}\n"
        f"- Description : {custom.get('description', '')}\n"
        f"- Métriques affectées : {metrics_line}\n\n"
        f"Tu n'as pas besoin de chercher ce problème dans PROBLEMS.md : il n'y est pas. "
        f"Utilise directement ce contexte comme source pour les étapes 1 et 2 du protocole.\n"
    )
    return base + context


@app.route("/iterate/<int:n>/start", methods=["POST"])
def start_iteration(n):
    """Démarre une session interactive Claude pour l'itération N."""
    # Nettoyer une éventuelle session précédente
    if n in _sessions:
        old = _sessions[n]
        if old.get("status") == "running" and old.get("proc"):
            return jsonify({"error": "Itération déjà en cours"}), 400
        # Session terminée ou en attente → on la remplace
        if old.get("proc"):
            try:
                old["proc"].terminate()
            except Exception:
                pass

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        return jsonify({"error": "claude introuvable dans le PATH"}), 500

    log_dir = PROJECT_ROOT / "dashboard" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"iteration_{n}.log"

    # Vider le log
    open(log_file, "w").close()

    _sessions[n] = {
        "proc": None,
        "events": [],
        "new_event": threading.Event(),
        "status": "starting",
        "log_file": str(log_file),
    }

    _launch_turn(n, build_iterate_prompt(n), is_first=True)

    return jsonify({"status": "started", "iteration": n})


@app.route("/iterate/<int:n>/dismiss", methods=["POST"])
def dismiss_iteration(n):
    """Termine/abandonne une session d'itération.

    Tue le subprocess Claude si présent, purge `_sessions[n]`.
    Après appel, l'état du bouton repasse à :
      - `done` si `metrics_NNN.json` existe (itération terminée avec résultats)
      - `never` sinon (itération abandonnée sans résultats)
    """
    session = _sessions.get(n)
    if not session:
        return jsonify({"status": "no_session", "iteration": n})

    proc = session.get("proc")
    if proc:
        try:
            proc.terminate()
        except Exception:
            pass

    # Libère les threads SSE bloqués sur flag.wait()
    flag = session.get("new_event")
    if flag:
        flag.set()

    _sessions.pop(n, None)
    return jsonify({"status": "dismissed", "iteration": n})


@app.route("/iterate/<int:n>/send", methods=["POST"])
def send_message(n):
    """Envoie un message utilisateur pour continuer la conversation Claude."""
    session = _sessions.get(n)
    if not session:
        return jsonify({"error": "Pas de session active"}), 400
    if session["status"] != "waiting_input":
        return jsonify({"error": "Claude n'attend pas de réponse"}), 400

    data = request.get_json()
    message = (data or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "Message vide"}), 400

    # Enregistrer le message utilisateur dans les events + log
    session["events"].append({"type": "user", "data": message})
    session["new_event"].set()
    with open(session["log_file"], "a", encoding="utf-8") as f:
        f.write(f"\n>>> UTILISATEUR: {message}\n\n")

    _launch_turn(n, message, is_first=False)

    return jsonify({"status": "sent"})


@app.route("/iterate/<int:n>/stream")
def stream_iteration(n):
    """SSE — stream bidirectionnel : texte Claude + signaux waiting_input."""
    def generate():
        session = _sessions.get(n)
        if not session:
            yield f"data: {json.dumps({'error': 'Pas de session'})}\n\n"
            return

        events = session["events"]
        flag = session["new_event"]
        idx = 0
        last_activity = time.time()
        max_idle = 3600  # 1h d'inactivité max

        while True:
            # Drainer tous les events disponibles
            had_events = False
            while idx < len(events):
                event = events[idx]
                idx += 1
                had_events = True

                etype = event.get("type")
                if etype == "text":
                    yield f"data: {json.dumps({'line': event['data']})}\n\n"
                elif etype == "user":
                    yield f"data: {json.dumps({'user': event['data']})}\n\n"
                elif etype == "waiting_input":
                    yield f"data: {json.dumps({'waiting_input': True})}\n\n"
                elif etype == "error":
                    yield f"data: {json.dumps({'error': event['data']})}\n\n"
                elif etype == "done":
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    return

            if had_events:
                last_activity = time.time()

            # Timeout d'inactivité
            if time.time() - last_activity > max_idle:
                yield f"data: {json.dumps({'error': 'Session expirée (1h sans activité)'})}\n\n"
                return

            # Attendre de nouveaux events
            flag.wait(timeout=10)
            flag.clear()

            # Keepalive (data event, pas un commentaire SSE)
            if idx >= len(events):
                yield f"data: {json.dumps({'keepalive': True})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive",
                    })


@app.route("/health")
def health():
    """Health check pour Docker healthcheck et monitoring externe."""
    return jsonify({
        "status": "ok",
        "sessions_active": len(_sessions),
        "project_root": str(PROJECT_ROOT),
    }), 200


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Server error", "details": str(e)}), 500


if __name__ == "__main__":
    # Écoute sur 0.0.0.0:5050 (accessible depuis l'extérieur de la VM)
    # Port 5050 utilisé au lieu de 5000 pour éviter les conflits
    print()
    print("=" * 70)
    print("Dashboard HelloPro Scoring")
    print("=" * 70)
    print()
    print("Accessible sur: http://127.0.0.1:5050")
    print()
    print("Routes:")
    print("  GET  /              - Tableau de bord (KPIs)")
    print("  GET  /iterations    - Historique des itérations")
    print("  GET  /problems      - Statut P1-P9")
    print("  POST /iterate/<N>/start - Démarrer une itération")
    print("  POST /iterate/<N>/send  - Répondre à Claude")
    print("  GET  /iterate/<N>/stream - SSE temps réel")
    print()
    print("=" * 70)
    print()
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
