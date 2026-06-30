#!/usr/bin/env bash
# Lance l'interface de chat TechCorp en une seule commande.
# Usage : ./run.sh

set -e

cd "$(dirname "$0")/backend"

if [ ! -f ".env" ]; then
  echo "ℹ️  Aucun .env trouvé, copie de .env.example..."
  cp .env.example .env
fi

if [ ! -d "venv" ]; then
  echo "📦 Création de l'environnement virtuel..."
  python3 -m venv venv
fi

source venv/bin/activate
pip install --quiet -r requirements.txt

echo ""
echo "🚀 Démarrage du serveur sur http://localhost:8080"
echo "   (config actuelle dans backend/.env — à ajuster avec l'URL donnée par INFRA)"
echo ""

uvicorn main:app --host 0.0.0.0 --port 8080
