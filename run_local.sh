#!/bin/bash

# Script pour lancer l'application en mode développement local
# Assurez-vous d'être dans le bon répertoire avant d'exécuter ce script
echo "🚀 Lancement de reMarkable Manager en mode développement..."
echo "📂 Données stockées dans: ./data/"
echo ""

venv/bin/streamlit run app.py
