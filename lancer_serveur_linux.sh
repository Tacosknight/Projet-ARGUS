#!/usr/bin/env bash
# ==============================================================================
# Lanceur du Serveur Facture-Checker pour Linux / macOS
# ==============================================================================

# Se placer dans le répertoire du script
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

echo "============================================================"
echo "    DÉMARRAGE DU SERVEUR MOBILE FACTURE-CHECKER (LINUX)     "
echo "============================================================"

# Vérification de Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Erreur : python3 n'est pas installé sur ce système."
    exit 1
fi

# Création du venv si absent
if [ ! -d "venv" ]; then
    echo "📦 Création de l'environnement virtuel venv..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ Échec de création du venv."
        exit 1
    fi
    echo "⬇️  Installation des dépendances depuis requirements.txt..."
    PYTHONPATH="" ./venv/bin/pip install -r requirements.txt
fi

# Lancement du serveur avec l'environnement virtuel
echo "🚀 Lancement du serveur web..."
PYTHONPATH="facture-checker" ./venv/bin/python3 server.py
