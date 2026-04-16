#!/bin/bash
# Script de démarrage du dashboard Flask pour la VM distante
# Usage: bash dashboard/start_dashboard.sh

cd "$(dirname "$0")/.."
echo "📊 Démarrage du dashboard HelloPro Scoring..."
echo ""

# Installer Flask si nécessaire
if ! python3 -c "import flask" 2>/dev/null; then
    echo "Installation de Flask..."
    pip install flask --quiet 2>/dev/null || pip3 install flask --quiet 2>/dev/null
fi

echo "✓ Préparation terminée"
echo ""
echo "🚀 Dashboard accessible sur :"
echo "   http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "Appuyez sur Ctrl+C pour arrêter le serveur"
echo ""

# Lancer Flask sur 0.0.0.0:5000
python3 dashboard/app.py || python dashboard/app.py
