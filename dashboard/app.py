#!/usr/bin/env python3
"""
Flask dashboard pour l'optimisation scoring HelloPro.
Permet aux non-devs de lancer des itérations et suivre la progression en live.
"""

import json
import re
import subprocess
import shutil
import time
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = Flask(__name__, template_folder=str(TEMPLATES_DIR))

# Dictionnaire global pour tracker les subprocessus en cours
_processes = {}  # {iteration_num: {"proc": process, "log_file": path}}


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


def parse_iterations_md():
    """Parse ITERATIONS.md pour extraire l'historique"""
    iterations_file = PROJECT_ROOT / "ITERATIONS.md"
    iterations = []

    if not iterations_file.exists():
        return iterations

    with open(iterations_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Regex pour trouver les sections "## Itération N"
    pattern = r"## Itération (\d+) — \[(.*?)\]"
    for match in re.finditer(pattern, content):
        iter_num = int(match.group(1))
        timestamp = match.group(2)

        # Charger les métriques
        metrics = load_metrics(iter_num)
        if metrics:
            iterations.append({
                "number": iter_num,
                "timestamp": timestamp,
                "metrics": metrics,
                "decision": "GARDÉ" if iter_num == 0 else "EN ATTENTE"  # À améliorer
            })

    return sorted(iterations, key=lambda x: x["number"])


def parse_problems_md():
    """Parse PROBLEMS.md pour extraire le statut des 9 problèmes"""
    problems_file = PROJECT_ROOT / "PROBLEMS.md"
    problems = []

    if not problems_file.exists():
        return problems

    # Note: Pour maintenant, créer une liste statique des 9 problèmes
    # La lecture du fichier PROBLEMS.md nécessiterait un parsing plus sophistiqué

    # Pour maintenant, créer une liste statique des 9 problèmes
    # À améliorer : parser le fichier PROBLEMS.md
    problem_names = [
        "Absence caractéristique → pénalité manquante",
        "Produits hors catégorie remontent trop haut",
        "LLM juge sur titre seul, ignore descriptif",
        "86% Prix sur demande (diagnostic)",
        "Zéro résultat certains parcours1",
        "Mélange produits neuf/occasion",
        "Erreur calcul scoring multi-caractéristiques",
        "Manque reranking après matching",
        "Caching produits dénormalisés"
    ]

    for i, name in enumerate(problem_names, 1):
        problems.append({
            "number": i,
            "name": name,
            "status": "BACKLOG" if i != 1 else "EN COURS",
            "iteration": i if i <= 8 else None
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


def get_metric_status(name, value):
    """Retourne le statut (🟢/🟡/🔴) d'une métrique"""
    if value is None:
        return "⚪"

    # Seuils cibles (de EVAL.md)
    thresholds = {
        "taux_conformite": {"target": 80, "type": "min"},
        "aberrations_prix": {"target": 0, "type": "max"},
        "doublons": {"target": 0, "type": "max"},
        "diversite_fournisseurs": {"target": 3, "type": "min"},
        "coherence_score": {"target": 0.5, "type": "min"},
        "presence_estimatif": {"target": 90, "type": "min"},
        "score_global": {"target": 80, "type": "min"}
    }

    if name not in thresholds:
        return "⚪"

    threshold = thresholds[name]
    if threshold["type"] == "min":
        return "🟢" if value >= threshold["target"] else "🔴"
    else:  # max
        return "🟢" if value <= threshold["target"] else "🔴"


@app.route("/")
def index():
    """Page principale — tableau de bord"""
    latest_metrics = load_latest_metrics()
    baseline = load_baseline()
    iterations = parse_iterations_md()

    # Déterminer si on est en CP1 (baseline non validée)
    in_cp1 = (baseline and baseline.get("_status") == "EN ATTENTE") or latest_metrics is None

    return render_template("index.html",
                          metrics=latest_metrics,
                          baseline=baseline,
                          iterations=iterations,
                          format_metric=format_metric_value,
                          get_status=get_metric_status,
                          in_cp1=in_cp1)


@app.route("/iterations")
def iterations():
    """Page — historique des itérations"""
    iterations_list = parse_iterations_md()

    return render_template("iterations.html",
                          iterations=iterations_list,
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
    """Page — statut des 9 problèmes P1-P9"""
    problems_list = parse_problems_md()
    iterations_list = parse_iterations_md()

    return render_template("problems.html",
                          problems=problems_list,
                          iterations=iterations_list)


@app.route("/api/metrics/latest")
def api_metrics_latest():
    """API — retourne les dernières métriques en JSON (pour polling)"""
    metrics = load_latest_metrics()
    return jsonify(metrics or {})


@app.route("/iterate/<int:n>/start", methods=["POST"])
def start_iteration(n):
    """Démarre une itération N en subprocess avec capture via fichier de log"""
    if n in _processes:
        return jsonify({"error": "Iteration already running"}), 400

    try:
        # Trouver le chemin complet de claude
        claude_cmd = shutil.which("claude")
        if not claude_cmd:
            return jsonify({"error": "claude command not found in PATH"}), 500

        # Créer le répertoire de logs
        log_dir = PROJECT_ROOT / "dashboard" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"iteration_{n}.log"

        # Lancer Claude en redirigeant stdout vers le fichier de log
        with open(log_file, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                [claude_cmd, "-p", f"/iterate {n}"],
                stdout=logf,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(PROJECT_ROOT),
                encoding="utf-8"
            )

        _processes[n] = {
            "proc": proc,
            "log_file": str(log_file),
            "start_time": time.time()
        }

        return jsonify({
            "status": "started",
            "iteration": n,
            "message": f"Itération {n} en cours... Consultez la console ci-dessous"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/iterate/<int:n>/stream")
def stream_iteration(n):
    """SSE - Stream la sortie de Claude depuis le fichier de log"""
    def generate():
        proc_info = _processes.get(n)
        if not proc_info:
            yield "data: {\"error\": \"Iteration not started\"}\n\n"
            return

        log_file_path = proc_info.get("log_file")
        proc = proc_info.get("proc")

        if not log_file_path or not Path(log_file_path).exists():
            yield "data: {\"error\": \"Log file not found\"}\n\n"
            return

        try:
            last_position = 0
            max_wait = 600  # 10 minutes max
            start_time = time.time()

            while time.time() - start_time < max_wait:
                # Lire les nouvelles lignes du fichier
                try:
                    with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last_position)
                        for line in f:
                            line_clean = line.rstrip("\n\r")
                            if line_clean:
                                yield f"data: {json.dumps({'line': line_clean})}\n\n"
                        last_position = f.tell()
                except Exception:
                    pass

                # Vérifier si le processus est terminé
                poll_result = proc.poll()
                if poll_result is not None:
                    # Dernière lecture pour capturer ce qui reste
                    try:
                        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_position)
                            for line in f:
                                line_clean = line.rstrip("\n\r")
                                if line_clean:
                                    yield f"data: {json.dumps({'line': line_clean})}\n\n"
                    except Exception:
                        pass

                    # Signal que c'est terminé
                    yield f"data: {json.dumps({'done': True, 'code': poll_result})}\n\n"
                    break

                # Attendre avant de relire
                time.sleep(0.2)

            # Timeout atteint
            if time.time() - start_time >= max_wait:
                yield f"data: {json.dumps({'error': 'Timeout', 'done': True})}\n\n"

        finally:
            # Nettoyer
            if n in _processes:
                try:
                    proc.terminate()
                except:
                    pass
                _processes.pop(n, None)

    return Response(generate(), mimetype="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "X-Accel-Buffering": "no",
                        "Connection": "keep-alive"
                    })


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
    print("  POST /iterate/<N>/start - Commande a lancer")
    print()
    print("=" * 70)
    print()
    app.run(host="0.0.0.0", port=5050, debug=False)
