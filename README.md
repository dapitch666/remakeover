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
2. The page shows an edit form for the currently selected device, or a creation form when no device is configured yet
3. Fill in the fields:
   - **Name**: a free-form label to identify the device
   - **IP address**: the tablet's IP (USB or Wi-Fi)
   - **SSH password**: the tablet's root password (visible in Settings > Help > About > Copyrights and licences)
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
│   ├── templates/          # Local SVG and .template (JSON) files
│   ├── templates.json      # Local template index
│   ├── templates.backup.json  # Backup of the remote templates.json
│   └── .tpl_sync           # Sync-state sentinel (MD5 of last pushed templates.json)
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
Manage custom templates (SVG and `.template` JSON format):
- **Import** templates from the tablet (initial setup)
- **Add** new SVG or `.template` files
- **Edit categories** and **icon code** for each template
- **Rename**, **delete**, or **reload** templates
- **Sync** changes to the tablet (a warning badge appears when local templates are out of sync with the last deployed state)

### 🚀 Deployment
Re-deploy your configuration after a firmware update (which resets all customisations):
- Sends the preferred sleep-screen image (or a random one)
- Uploads SVG / `.template` files, creates symlinks in the device's templates directory, and pushes `templates.json`
- Disables the carousel (moves stock illustrations to a backup folder)
- Restarts `xochitl` to apply the changes

> **Note:** All SSH operations automatically remount the root filesystem read-write before executing, and restore the read-only state if it was changed.

### ⚙️ Configuration
Add, edit, or delete devices.

### ✏️ Éditeur de templates
Create and edit `.template` JSON-format files with a live SVG preview. Save results to the local device library for deployment from the Templates page.

### 🔤 Police d'icônes
Extract the icomoon TTF font from the xochitl binary and browse all available icon glyphs. Filter by in-use or unused glyphs, and copy icon codes for use in template definitions.

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

---

## 🧑‍💻 Contributing

### Install development dependencies

```bash
pip install -r requirements-dev.txt
```

This installs `ruff` (linter + formatter), `mypy` (type checker), `pytest-cov` (coverage), and `pre-commit`.

### Code quality

```bash
# Lint — report issues
ruff check src/ pages/ app.py

# Lint — auto-fix everything possible
ruff check src/ pages/ app.py --fix

# Format — check only (no changes written)
ruff format src/ pages/ app.py --check

# Format — apply
ruff format src/ pages/ app.py

# Type check
mypy src/ app.py --ignore-missing-imports
```

Run lint + format + types in one shot:

```bash
ruff check src/ pages/ app.py --fix && ruff format src/ pages/ app.py && mypy src/ app.py --ignore-missing-imports
```

### Tests and coverage

```bash
# Run tests (coverage report printed automatically)
pytest

# Generate an interactive HTML coverage report
pytest --cov=src --cov=pages --cov=app --cov-report=html
open htmlcov/index.html
```

The test suite enforces a minimum coverage threshold defined in `pytest.ini`. A failure means existing coverage regressed — add tests or update the threshold intentionally.

### Pre-commit hooks

Hooks run ruff and mypy automatically on every `git commit`:

```bash
# Install hooks (once, after cloning)
pre-commit install

# Run all hooks manually against every file
pre-commit run --all-files
```

This is the most reliable way to verify that a commit will pass before pushing.

---
## 📌 Important notes

- Configuration and data are persisted in `data/` — back up this folder
- The SSH connection uses the tablet's root password, visible in **Settings > Help > About > Copyrights and licences**
- Developer mode is not required on recent models
