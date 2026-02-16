# reMarkable Manager

Application web pour gérer plusieurs tablettes reMarkable (Paper Pro, Paper Pro Move, etc.)

## 🚀 Installation

### Prérequis
- Docker et Docker Compose installés (pour production)
- OU Python 3.11+ (pour développement local)
- Les clés SSH de vos tablettes reMarkable

## 🛠️ Développement local (sans Docker)

### Installation rapide
```bash
# Installer les dépendances
pip install -r requirements.txt

# Créer les dossiers nécessaires (si pas déjà créés)
mkdir -p data/ssh_keys

# Copier vos clés SSH
cp ~/.ssh/id_rsa_remarkable_pro data/ssh_keys/id_rsa_paper_pro
cp ~/.ssh/id_rsa_remarkable_move data/ssh_keys/id_rsa_move
chmod 600 data/ssh_keys/*

# Lancer l'application
streamlit run app.py
# OU utiliser le script
./run_local.sh
```

L'application sera accessible sur http://localhost:8501

**En mode local, tous les fichiers sont stockés dans `./data/` à côté de votre code.**

---

## 🐳 Installation Docker (production)

1. **Créer le dossier pour les clés SSH** :
```bash
mkdir -p data/ssh_keys
```

2. **Copier vos clés SSH** :
Placez vos clés SSH privées dans `data/ssh_keys/`. Par exemple :
- `data/ssh_keys/id_rsa_paper_pro` (clé pour la Paper Pro)
- `data/ssh_keys/id_rsa_move` (clé pour la Move)

```bash
cp ~/.ssh/id_rsa_remarkable_pro data/ssh_keys/id_rsa_paper_pro
cp ~/.ssh/id_rsa_remarkable_move data/ssh_keys/id_rsa_move
chmod 600 data/ssh_keys/*
```

3. **Lancer l'application** :
```bash
docker-compose up -d
```

4. **Accéder à l'interface** :
Ouvrez votre navigateur sur http://localhost:8501

## ⚙️ Configuration

### Première utilisation
1. Allez dans l'onglet **Configuration** (barre latérale)
2. Les deux appareils par défaut sont déjà configurés
3. Modifiez les paramètres selon vos besoins :
   - **Adresse IP** : IP de votre tablette (USB ou Wi-Fi)
   - **Nom du fichier clé SSH** : nom du fichier dans `data/ssh_keys/`
   - **Dimensions suspended.png** : 
     - Paper Pro: 1620 x 2160
     - Paper Pro Move: 1404 x 1872
   - **Templates** et **Carousel** : activer/désactiver selon vos besoins

### Ajouter un nouvel appareil
1. Dans Configuration, sélectionnez "-- Créer un nouvel appareil --"
2. Remplissez les informations
3. Placez la clé SSH correspondante dans `data/ssh_keys/`
4. Sauvegardez

### Structure des données
```
data/
├── config.json           # Configuration des appareils (créé automatiquement)
└── ssh_keys/             # Vos clés SSH privées
    ├── id_rsa_paper_pro
    └── id_rsa_move
```

## 📝 Utilisation

### Changer l'écran de veille
1. Sélectionnez votre tablette dans la liste
2. Glissez une image (PNG, JPG, JPEG)
3. L'image sera automatiquement redimensionnée selon la configuration
4. Cliquez sur "Envoyer l'image"

### Maintenance après mise à jour
Utilisez le bouton "Lancer le script complet" pour :
- Sauvegarder les illustrations du carousel
- Redémarrer xochitl

## 🔧 Commandes utiles

```bash
# Arrêter l'application
docker-compose down

# Voir les logs
docker-compose logs -f

# Reconstruire après modification du code
docker-compose up -d --build

# Sauvegarder votre configuration
cp data/config.json config.json.backup
```

## 📌 Notes importantes

- La configuration est stockée dans `data/config.json`
- Les clés SSH ne sont JAMAIS incluses dans le container
- Tout est persisté localement dans le dossier `data/`
- Vous pouvez sauvegarder uniquement le dossier `data/` pour conserver toute votre configuration
