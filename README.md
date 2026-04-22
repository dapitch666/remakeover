# reMakeover

Self-hosted web application to customize sleep-screen images and manage templates on reMarkable devices.
- Compatible with reMarkable 2, Paper Pro, Paper Pro Move
- Connects over SSH using the device’s root password — no SSH keys required
- Writes changes to `/home/root`, so they persist across firmware updates
- Requires no hacks or additional software on the device


## ⚡ Quick start

```bash
# Requires Docker Compose
docker-compose up -d
```

Then open http://localhost:8501 in your browser and follow the instructions in the ⚙️ Configuration panel to add your device(s).

---

## 📌 Persistence across firmware updates

Your custom sleep-screen image and templates are written to `/home/root` on the device.

This directory is preserved across firmware updates, so your changes are **not lost when the device is updated**.


## ⚠️ Prerequisites

To use the application, your reMarkable device must allow SSH access over Wi-Fi.

On the device:

1. Enable developer mode  
   https://support.remarkable.com/s/article/Developer-mode

2. Enable **SSH over WLAN** (Wi-Fi)
   Follow the instructions shown on the device:  
   **Settings → Help → About → Copyrights and licenses**

3. Note the **root password**  
   It is displayed on the same screen and will be required by the application.

> ⚠️ Without SSH over WLAN enabled, the application will not be able to connect to your device.

---

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

### Using the pre-built image (recommended)

A Docker image is published automatically on every release to the GitHub Container Registry:

To use it, replace `build: .` in `docker-compose.yml` with:

```yaml
image: ghcr.io/dapitch666/remakeover:latest
```

### Building from source

```bash
# Build and start the container
docker-compose up -d
```

Open http://localhost:8501 in your browser 

---

## ⚙️ Configuration

### First-time setup
1. Open the **⚙️ Configuration** panel in the sidebar
2. The sidebar shows an edit form for the currently selected device, or a creation form when no device is configured
3. Fill in the fields:
   - **Name**: a free-form label to identify the device
   - **IP address**: the device's IP (USB or Wi-Fi)
   - **SSH password**: the device's root password (visible in Settings > Help > About > Copyrights and licences)
4. Click **Test Connection** to verify access and detect the device type/firmware automatically 
5. Click **Save**

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
│   ├── templates/          # Local .template (JSON) files
│   └── manifest.json       # Local template manifest (last_modified + templates keyed by UUID)
└── ...
```

---

## 📝 Application pages

### 🖼️ Sleep Screen
Manage sleep-screen images (`suspended.png`):
- **Import** the image currently on the device
- **Add** a new image from your computer (PNG, JPG, JPEG — resized automatically)
- **Send** an image directly to the device
- **Rename** or **delete** local images
- **Restore** the factory default sleep screen

### 📄 Templates
Manage and edit custom templates (`.template` JSON format) in a split-panel layout:
- **Import** templates from the device (initial setup)
- **Browse and filter** the local template library
- **Edit** categories, labels, icon, and SVG body in the integrated editor with a live preview
- **Add** new templates from scratch
- **Rename**, **delete**, or **reload** templates
- **Check sync status** by comparing local and device manifests
- **Sync** changes to the device (the local manifest is applied)

### 📋 Logs
View the history of operations for the current session.

### ⚙️ Configuration (sidebar)
Add, edit, or delete devices. Accessible from the sidebar panel on every page.

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

---

## 🧑‍💻 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code quality, tests, and localization.

---

## 🔒 Security notes

### Intended network environment

This application is designed to run on a **trusted local network only**. It communicates with your reMarkable device over SSH using the root password, with no additional transport-layer protection beyond what SSH itself provides.

It is **not intended to be exposed to the internet**. A typical safe deployment is a home or office NAS (e.g. a Synology) running the Docker container behind a reverse proxy configured with a private-network-only access policy, so the app is reachable inside the LAN but never from outside.

### SSH host-key trust policy (`AutoAddPolicy`)

Paramiko is configured with `AutoAddPolicy`, which means the app **does not verify the SSH host key** of the device and will connect to any device at the configured IP address without prompting. This is a conscious trade-off:

> The reMarkable device **regenerates its SSH host key on every firmware update**. Storing a known host key would cause every post-update deployment to fail — exactly the scenario this app is built to handle. Persistent known-hosts are therefore not a practical mitigation here.

The residual risk is a local-network MITM attack. This is acceptable given the intended deployment context (private LAN, no internet exposure), but you should be aware of it if your network topology changes.

### Plaintext password storage

The SSH root password of each registered device is stored in plain text in `data/config.json`. This file is excluded from version control (`.gitignore`) but is readable by any process or user with access to the `data/` directory or the Docker volume mount.

Practical mitigations:
- Keep the `data/` directory (and its Docker volume) accessible only to the user running the container.
- Back up `data/config.json` securely (e.g. encrypted backup).
- The reMarkable root password has a limited blast radius: it grants SSH access to the device itself, not to any other system.

---

## 📌 Important notes

- Configuration and data are persisted in `data/` — back up this folder regularly to avoid losing your custom images and templates