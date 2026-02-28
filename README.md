# reMarkable Manager

Web application to manage multiple reMarkable tablets (Paper Pro, Paper Pro Move, reMarkable 2, etc.).

Connects over SSH using a password — no SSH keys required.

## 🚀 Installation

### Requirements
- Docker and Docker Compose (for production)
- OR Python 3.11+ (for local development)

---

## 🛠️ Local development (without Docker)

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Start the application
streamlit run app.py
```

The application will be available at http://localhost:8501

**In local mode, all files are stored in `./data/` next to your code.**

---

## 🐳 Docker installation (production)

```bash
# Build and start the container
docker-compose up -d
```

Open your browser at http://localhost:8501

---

## ⚙️ Configuration

### First-time setup
1. Go to **⚙️ Configuration** (sidebar)
2. Select "-- Create a new device --"
3. Fill in the fields:
   - **Name**: a free-form label to identify the device
   - **IP address**: the tablet's IP (USB or Wi-Fi)
   - **SSH password**: the tablet's root password (visible in Settings > Help > About)
   - **Tablet type**: select from the supported models
   - **Enable templates** / **Disable carousel**: as needed
4. Click **Save**

### Supported models and sleep-screen dimensions

| Model | Resolution |
|---|---|
| reMarkable 2 | 1404 × 1872 |
| reMarkable Paper Pro | 1620 × 2160 |
| reMarkable Paper Pro Move | 954 × 1696 |

Imported images are automatically converted and resized to the correct format.

### Data structure

```
data/
├── config.json             # Device configuration (created automatically)
├── MyDevice/               # One sub-folder per device
│   ├── images/             # Sleep-screen images saved locally
│   ├── templates/          # Local SVG templates
│   ├── templates.json      # Local template index
│   └── templates.backup.json  # Backup of the remote templates.json
└── ...
```

---

## 📝 Application pages

### 🖼️ Images
Manage sleep-screen images (`suspended.png`):
- **Import** the image currently on the tablet
- **Add** a new image from your computer (PNG, JPG, JPEG — resized automatically)
- **Send** an image directly to the tablet
- **Set a preferred image** (used first during a deployment)
- **Rename** or **delete** local images

### 📄 Templates
Manage custom SVG templates:
- **Import** templates from the tablet (initial setup)
- **Add** new SVG templates
- **Edit categories** for each template
- **Rename** or **delete** templates
- **Sync** changes to the tablet

### 🚀 Deployment
Re-deploy your configuration after a firmware update (which resets all customisations):
- Sends the preferred sleep-screen image (or a random one)
- Deploys SVG templates and updates `templates.json`
- Disables the carousel (moves stock illustrations to a backup folder)
- Restarts `xochitl` to apply the changes

### ⚙️ Configuration
Add, edit, or delete devices.

### 📋 Logs
View the history of operations for the current session.

---

## 🔧 Useful commands

```bash
# Stop the application
docker-compose down

# View container logs
docker-compose logs -f

# Rebuild after code changes
docker-compose up -d --build

# Run the tests
pytest

# Back up your data
cp -r data/ data.backup/
```

## 📌 Important notes

- Configuration and data are persisted in `data/` — back up this folder
- The SSH connection uses the tablet's root password, visible in **Settings > Help > About > Copyrights and licences**
- Developer mode is not required on recent models
