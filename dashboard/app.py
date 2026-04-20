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


def parse_iterations_md():
    """Parse ITERATIONS.md pour extraire l'historique"""
    iterations_file = PROJECT_ROOT / "ITERATIONS.md"
    iterations = []

    if not iterations_file.exists():
        return iterations

    with open(iterations_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Regex pour trouver les sections "## Itération N — date" (avec ou sans crochets)
    pattern = r"## Itération (\d+) — \[?(.*?)\]?$"
    for match in re.finditer(pattern, content, re.MULTILINE):
        iter_num = int(match.group(1))
        timestamp = match.group(2).strip()

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


# Mapping problème → itération selon l'ordre d'attaque de CLAUDE.md :
# "Ordre itérations suggéré : P1 (iter 1), P3 (iter 2), P2 (iter 3),
#  P5 (iter 4), P6 (iter 5), P7 (iter 6), P8 (iter 7), P9 (iter 8)"
# P4 est un diagnostic, pas d'itération dédiée.
PROBLEM_TO_ITERATION = {1: 1, 2: 3, 3: 2, 4: None, 5: 4, 6: 5, 7: 6, 8: 7, 9: 8}


def parse_problems_md():
    """Parse PROBLEMS.md pour extraire la liste des 9 problèmes.

    L'état réel (running/waiting/done/never) est calculé côté template à partir
    de iteration_states via PROBLEM_TO_ITERATION. Pas de statut statique ici.
    """
    problems_file = PROJECT_ROOT / "PROBLEMS.md"
    problems = []

    if not problems_file.exists():
        return problems

    # Note: Pour maintenant, créer une liste statique des 9 problèmes
    # La lecture du fichier PROBLEMS.md nécessiterait un parsing plus sophistiqué
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
            "iteration": PROBLEM_TO_ITERATION.get(i),
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
    Retourne l'état de chaque itération 0..max_n.

    États possibles :
    - "never"    : jamais lancée (pas de metrics_N.json, pas de session)
    - "done"     : terminée (metrics_N.json existe ET pas de session active)
    - "running"  : Claude est en train d'exécuter
    - "waiting"  : Claude attend une réponse utilisateur
    - "starting" : session en cours de démarrage
    """
    states = {}
    for n in range(max_n + 1):
        metrics_file = RESULTS_DIR / f"metrics_{n:03d}.json"
        metrics_exists = metrics_file.exists()

        session = _sessions.get(n)
        session_status = session.get("status") if session else None

        if session_status == "running":
            state = "running"
        elif session_status == "waiting_input":
            state = "waiting"
        elif session_status == "starting":
            state = "starting"
        elif metrics_exists:
            state = "done"
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

    # Déterminer si on est en CP1 (baseline non validée)
    in_cp1 = (baseline and baseline.get("_status") == "EN ATTENTE") or latest_metrics is None

    return render_template("index.html",
                          metrics=latest_metrics,
                          baseline=baseline,
                          iterations=iterations,
                          iteration_states=iteration_states,
                          format_metric=format_metric_value,
                          get_status=get_metric_status,
                          in_cp1=in_cp1)


@app.route("/api/iteration-states")
def api_iteration_states():
    """API JSON — retourne l'état de toutes les itérations (pour polling live)."""
    return jsonify(get_iteration_states())


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
    """Page — statut des 9 problèmes P1-P9"""
    problems_list = parse_problems_md()
    iterations_list = parse_iterations_md()
    iteration_states = get_iteration_states()

    return render_template("problems.html",
                          problems=problems_list,
                          iterations=iterations_list,
                          iteration_states=iteration_states)


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


@app.route("/reset-all", methods=["POST"])
def reset_all():
    """Stoppe toutes les sessions actives et archive logs + métriques dans
    un sous-dossier backup/<timestamp>/ (pas de suppression : déplacement).

    Déclenché par le bouton Iter 0 (baseline) : relancer la baseline invalide
    l'ensemble des itérations, donc on repart d'un dashboard vierge tout en
    conservant l'historique sur disque.

    Fichiers immuables préservés : BASELINE.json, ITERATIONS.md, PROBLEMS.md,
    EVAL.md, CLAUDE.md, test_data/parcours.json (cf. CLAUDE.md).
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # 1. Terminer tous les subprocess actifs
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

    # 2. Vider le registre de sessions mémoire
    _sessions.clear()

    # 3. Archiver les logs (déplacement, pas suppression)
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

    # 4. Archiver les résultats (métriques + parcours) pour que les boutons
    #    repassent en état "never"
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

    _launch_turn(n, f"/iterate {n}", is_first=True)

    return jsonify({"status": "started", "iteration": n})


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
