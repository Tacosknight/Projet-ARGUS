#!/usr/bin/env bash
# ==============================================================================
# Lanceur du Serveur Facture-Checker pour Linux / macOS
# Double-clic ou exécution terminal : installe automatiquement les dépendances
# et démarre le serveur web tout en ouvrant le navigateur sans intervention manuelle.
# ==============================================================================
set -euo pipefail

# Se placer dans le répertoire du script
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "${DIR}"

echo "============================================================"
echo "    DÉMARRAGE DU SERVEUR MOBILE FACTURE-CHECKER (LINUX)     "
echo "============================================================"

# 1. Vérification et tentative d'installation automatique de Python 3 si manquant
if ! command -v python3 >/dev/null 2>&1; then
    echo "⚠️ Python 3 n'est pas détecté. Tentative d'installation automatique..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Sy --noconfirm python python-pip
    else
        echo "❌ Erreur : Impossible d'installer Python 3 automatiquement."
        echo "Veuillez installer python3 via votre gestionnaire de paquets."
        exit 1
    fi
fi

# 2. Vérification / Création de l'environnement virtuel venv
if [[ ! -d "venv" ]]; then
    echo "📦 Création de l'environnement virtuel venv..."
    if ! python3 -m venv venv 2>/dev/null; then
        echo "⚠️ Module python3-venv manquant. Tentative d'installation du paquet..."
        if command -v apt-get >/dev/null 2>&1; then
            sudo apt-get update && sudo apt-get install -y python3-venv python3-pip || true
        fi
        python3 -m venv venv || python3 -m venv --without-pip venv
    fi
fi

# 3. Vérification et installation automatique des dépendances si nécessaire
NEED_INSTALL=0
if [[ -f "venv/bin/python3" ]]; then
    if ! ./venv/bin/python3 -c "import fastapi, uvicorn, PIL, pandas" >/dev/null 2>&1; then
        NEED_INSTALL=1
    fi
else
    NEED_INSTALL=1
fi

if [[ "${NEED_INSTALL}" -eq 1 ]]; then
    echo "⬇️  Installation automatique des dépendances depuis requirements.txt..."
    PYTHONPATH="" ./venv/bin/python3 -m pip install --upgrade pip --quiet 2>/dev/null || true
    PYTHONPATH="" ./venv/bin/pip install -r requirements.txt
    echo "✅ Dépendances installées avec succès."
else
    echo "✅ Dépendances déjà prêtes."
fi

# 4. Ouverture automatique du navigateur web sur l'adresse locale
echo "🌐 Ouverture automatique du navigateur sur http://localhost:8000..."
(sleep 2 && (xdg-open "http://localhost:8000" >/dev/null 2>&1 || open "http://localhost:8000" >/dev/null 2>&1 || sensible-browser "http://localhost:8000" >/dev/null 2>&1 || true)) &

# 5. Lancement du serveur avec l'environnement virtuel
echo "🚀 Lancement du serveur web..."
PYTHONPATH="venv/lib/python3.12/site-packages:facture-checker" ./venv/bin/python3 server.py
