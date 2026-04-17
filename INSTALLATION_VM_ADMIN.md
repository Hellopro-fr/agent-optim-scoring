# Installation Claude CLI dans la VM
## Document pour les admins système

---

## 📋 Prérequis système

| Composant | Minimum | Recommandé |
|-----------|---------|-----------|
| OS | Linux/macOS/Windows | Ubuntu 20.04 LTS+ |
| Python | 3.9+ | 3.11+ |
| Disque libre | 500 MB | 2 GB |
| RAM | 1 GB | 4 GB |
| Réseau | Accès internet | Réseau stable |

---

## 🔧 Étapes d'installation

### **1. Installer Python (si absent)**

#### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv
python3 --version  # Vérifier >= 3.9
```

#### macOS
```bash
brew install python3
python3 --version
```

#### Windows Server
- Télécharger : https://www.python.org/downloads/ (3.11+)
- Installer avec "Add Python to PATH" coché

---

### **2. Installer Claude CLI**

```bash
# Installation via pip (recommandé)
pip install claude-code

# Vérifier l'installation
claude --version
```

**Alternative - Installation locale depuis source** :
```bash
# Si accès internet limité, télécharger le wheel depuis Anthropic
pip install /chemin/vers/claude_code-X.X.X-py3-none-any.whl
```

---

### **3. Configurer l'authentification Claude**

Claude a besoin d'un **token API Anthropic** :

```bash
# Option 1 : Interactif (connexion personnelle)
claude login
# Ouvrira un navigateur pour se connecter à claudeai.com

# Option 2 : Avec token d'API (pour automation)
export ANTHROPIC_API_KEY="sk-ant-..."
# Ou sur Windows:
set ANTHROPIC_API_KEY=sk-ant-...
```

**Où obtenir le token API** :
1. Aller sur https://console.anthropic.com/
2. Créer un compte ou se connecter
3. Générer une nouvelle API key
4. Conserver le secret (ne pas partager)

---

### **4. Installer les dépendances du projet**

```bash
cd /chemin/vers/optim-scoring
pip install -r requirements.txt
```

**Contenu de requirements.txt** :
```
requests>=2.31.0
python-dotenv>=1.0.0
flask>=3.0
```

---

### **5. Configurer les variables d'environnement**

Créer/modifier le fichier `.env` dans `/chemin/vers/optim-scoring/` :

```bash
# .env
TOKEN_INFO_PRODUIT=<TOKEN_API_HELLOPRO>
NEXT_TOKEN_API_QUESTION=<TOKEN_API_QUESTION>
RAG_HP_PUB_PATH=/chemin/vers/RAG-HP-PUB
```

**Note** : Les tokens sont spécifiques à HelloPro API et doivent être fournis par l'équipe dev.

---

## ✅ Vérification de l'installation

### **Vérifier Claude**
```bash
claude --version
# Output: claude version X.X.X

claude list
# Affiche les modèles disponibles
```

### **Vérifier Python & Flask**
```bash
python --version  # >= 3.9
pip list | grep -i flask
# Output: Flask X.X.X
```

### **Tester le Dashboard**
```bash
cd /chemin/vers/optim-scoring
python dashboard/app.py
# Écoute sur http://0.0.0.0:5050
# Tester: curl http://localhost:5050/
```

---

## 🚀 Démarrage du service

### **Mode développement**
```bash
cd /chemin/vers/optim-scoring
python dashboard/app.py
```
- Accessible sur `http://<IP_VM>:5050`
- Logs dans la console
- Arrêter avec `Ctrl+C`

### **Mode production** (avec systemd - Linux)

Créer `/etc/systemd/system/optim-dashboard.service` :
```ini
[Unit]
Description=HelloPro Optimization Dashboard
After=network.target

[Service]
Type=simple
User=optim
WorkingDirectory=/chemin/vers/optim-scoring
Environment="PATH=/usr/local/bin:/usr/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 dashboard/app.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Démarrer le service :
```bash
sudo systemctl enable optim-dashboard
sudo systemctl start optim-dashboard
sudo systemctl status optim-dashboard
```

### **Mode production** (avec Docker)

Si Docker est disponible, créer `Dockerfile` :
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5050
CMD ["python", "dashboard/app.py"]
```

Construire et lancer :
```bash
docker build -t optim-dashboard .
docker run -p 5050:5050 -e ANTHROPIC_API_KEY=sk-ant-... optim-dashboard
```

---

## 🔗 Architecture & Flux

```
User (Browser)
    ↓
http://VM:5050 (Dashboard Flask)
    ↓
POST /iterate/N/start → Subprocess: claude -p "/iterate N"
    ↓
Claude CLI exécute le prompt
    ↓
Modifie RAG-HP-PUB (API optimisation)
    ↓
GET /iterate/N/stream (SSE) ← Logs en temps réel
    ↓
run_pipeline.py → Mesure les métriques
    ↓
Dashboard rafraîchit
```

---

## 📞 Support & Troubleshooting

| Problème | Solution |
|----------|----------|
| `claude: command not found` | Ajouter `/usr/local/bin` à `$PATH` |
| `ANTHROPIC_API_KEY not found` | Vérifier `.env` ou variable d'environnement |
| Port 5050 occupé | `lsof -i :5050` puis `kill -9 <PID>` |
| Permissions refusées | Ajouter user au groupe : `usermod -aG docker optim` |
| Slow performance | Augmenter RAM/CPU de la VM |

---

## 📚 Ressources

- **Claude CLI** : https://claude.com/claude-code
- **Anthropic API** : https://console.anthropic.com/
- **Documentation officielle** : https://github.com/anthropics/claude-code
- **HelloPro API** : [Spécifications internes]

---

## ✋ Checkpoints d'acceptation

Avant de valider l'installation, vérifier :

- [ ] `claude --version` retourne une version valide
- [ ] `python -m flask --version` fonctionne
- [ ] `.env` contient tous les tokens requis
- [ ] `python dashboard/app.py` démarre sans erreur
- [ ] http://VM:5050 retourne le dashboard (HTML)
- [ ] POST /iterate/0/start retourne `{"status": "started", ...}`
- [ ] Les logs `/dashboard/logs/iteration_*.log` sont créés

---

## 👤 Responsabilités

| Rôle | Tâche |
|------|-------|
| Admin | Installer Python, Claude CLI, gérer le service |
| Dev | Configurer `.env`, tester l'intégration |
| Utilisateur final | Accéder au dashboard et lancer itérations |

---

**Document révisé** : 2026-04-16  
**Version** : 1.0
