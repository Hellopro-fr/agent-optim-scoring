# Installation Claude Code sur VM — Guide Admin Système

## 📋 Contexte

Un agent IA autonome (Claude) doit optimiser un pipeline de scoring HelloPro en modifiant le code de l'API et en exécutant des tests itératifs. Claude Code est l'outil d'Anthropic qui permet à Claude de travailler directement avec le code et les systèmes.

---

## ⚙️ Configuration VM requise

### 1. **Accès SSH**
- L'agent Claude Code doit pouvoir se connecter à la VM via SSH (clé publique + authentification par token)
- User : `claude-code` (dedicated service account, sans shell interactif)
- Permissions : lecture/écriture sur les répertoires des repos (voir ci-dessous)w²

### 2. **Répertoires Git** (clonés)
```
/home/claude-code/
├── optim-scoring/           ← Harness d'évaluation (lire les résultats uniquement)
│   ├── scripts/run_pipeline.py
│   ├── test_data/parcours.json
│   ├── EVAL.md
│   ├── BASELINE.json
│   ├── ITERATIONS.md
│   └── requirements.txt
│
└── RAG-HP-PUB/              ← API à modifier (READ + WRITE)
    ├── src/
    │   ├── matching_optim/  ← Endpoint dupliqué (agent modifie ICI)
    │   │   ├── scoring.cypher
    │   │   ├── prompt.txt (LLM cleanup)
    │   │   └── matching_logic.py
    │   │
    │   └── matching/        ← PRODUCTION (JAMAIS toucher)
    │
    ├── deploy.sh            ← Script de redéploiement accessible par agent
    └── .env (avec endpoint `/matching-optim`)
```

**Permissions** :
```bash
# optim-scoring : lire uniquement
chmod 755 /home/claude-code/optim-scoring
chmod 644 /home/claude-code/optim-scoring/test_data/parcours.json
chmod 644 /home/claude-code/optim-scoring/EVAL.md

# RAG-HP-PUB : lire + écrire
chmod 755 /home/claude-code/RAG-HP-PUB
chmod 755 /home/claude-code/RAG-HP-PUB/src/matching_optim
chmod 644 /home/claude-code/RAG-HP-PUB/src/matching_optim/*
```

### 3. **Dépendances logicielles**
```bash
# Python 3.11+ (pour run_pipeline.py)
python3 --version  # ≥ 3.11

# Git (pour commits/pushes)
git --version

# Docker (si API déploie en containers)
docker --version

# Pip + dépendances Python
pip3 install -r optim-scoring/requirements.txt  # requests, python-dotenv
pip3 install -r RAG-HP-PUB/requirements.txt    # (à spécifier)
```

### 4. **API HelloPro accessible**
- Endpoint `/matching-optim` doit être déployé (copie de `/matching`)
- Accessible en local ou réseau interne depuis la VM
- Variables d'env : 
  ```
  MATCHING_OPTIM_URL=http://localhost:8000/matching-optim
  BASELINE_JSON_PATH=/home/claude-code/optim-scoring/BASELINE.json
  ```

---

## 🔧 Installation Claude Code CLI

### Sur la VM (une fois)

```bash
# 1. Créer user service
sudo useradd -m -s /usr/sbin/nologin claude-code

# 2. Installer Claude Code CLI (via npm ou binaire Anthropic)
# Option A : via npm
sudo npm install -g @anthropic-ai/claude-code

# Option B : via binaire officiel (recommandé pour production)
wget https://releases.anthropic.com/claude-code/latest/claude-code-linux-x64
sudo mv claude-code-linux-x64 /usr/local/bin/claude-code
sudo chmod +x /usr/local/bin/claude-code

# 3. Configurer authentification
sudo -u claude-code claude-code auth login --token YOUR_ANTHROPIC_API_KEY

# 4. Vérifier l'installation
claude-code --version
```

### Authentification persistante
```bash
# Stocker le token API Anthropic de manière sécurisée
sudo -u claude-code mkdir -p ~/.config/claude-code
echo "ANTHROPIC_API_KEY=sk-..." | sudo tee ~/.config/claude-code/env > /dev/null
sudo chmod 600 ~/.config/claude-code/env
```

---

## ✅ Checklist de validation

Avant de valider auprès de Gustave (CP1), vérifier :

```bash
# ✅ Accès SSH fonctionne
ssh claude-code@VM_IP "pwd"

# ✅ Repos clonés
ssh claude-code@VM_IP "ls -la optim-scoring RAG-HP-PUB"

# ✅ Python 3.11+
ssh claude-code@VM_IP "python3 --version"

# ✅ Dépendances installées
ssh claude-code@VM_IP "python3 -c 'import requests; import dotenv'"

# ✅ Claude Code CLI accessible
ssh claude-code@VM_IP "which claude-code && claude-code --version"

# ✅ API /matching-optim répond
ssh claude-code@VM_IP "curl http://localhost:8000/matching-optim/health"

# ✅ Script de déploiement peut s'exécuter
ssh claude-code@VM_IP "test -x RAG-HP-PUB/deploy.sh && echo OK"

# ✅ Agent peut exécuter le pipeline
ssh claude-code@VM_IP "python3 optim-scoring/scripts/run_pipeline.py --iteration 0"
```

---

## 🚨 Points critiques pour admin

| Point | Détail |
|---|---|
| **Isolation** | User `claude-code` ne doit PAS toucher `/matching` (production) |
| **Permissions** | Lecture optim-scoring, lecture+écriture RAG-HP-PUB/src/matching_optim/ |
| **Redéploiement** | Script deploy.sh doit être exécutable par `claude-code` |
| **Logs** | Configurer /var/log/claude-code/ pour l'audit |
| **Rollback** | Git branching : une branche par itération, facile à revenir en arrière |
| **Monitoring** | Alerte si API `/matching-optim` crash (agent ne peut pas redéployer) |

---

## 📞 Escalade

Si Claude Code rencontre une erreur :
1. **Permission denied** → vérifier chmod + owner
2. **API not reachable** → vérifier déploiement + firewall VM
3. **Git push fails** → vérifier tokens GitHub + SSH key
4. **Python/dépendances manquent** → pip3 install manquante

Contacter **Dev 2** pour les questions API + permissions.

