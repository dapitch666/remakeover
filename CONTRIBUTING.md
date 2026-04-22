# Contributing to reMakeover

Contributions are welcome — feel free to open issues or pull requests.


## Development setup

Install development dependencies:

```bash
pip install -r requirements-dev.txt
```

This installs ruff (linter + formatter), mypy (type checker), pytest-cov (coverage), vulture (dead code detector), and pre-commit


## Code quality

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

## Tests and coverage

```bash
# Run tests (coverage report printed automatically)
pytest

# Generate an interactive HTML coverage report
pytest --cov=src --cov=pages --cov=app --cov-report=html
open htmlcov/index.html
```

The test suite enforces a minimum coverage threshold defined in `pyproject.toml`. A failure means existing coverage regressed — add tests or update the threshold intentionally.

### Pre-commit hooks

Hooks run ruff and mypy automatically on every `git commit`:

```bash
# Install hooks (once, after cloning)
pre-commit install

# Run all hooks manually against every file
pre-commit run --all-files
```

This is the most reliable way to verify that a commit will pass before pushing.

## 🌐 Localization

The app uses [gettext](https://docs.python.org/3/library/gettext.html) via [Babel](https://babel.pocoo.org/) for localization. English is the default language (msgids are plain English strings). Translations live in `locales/<lang>/LC_MESSAGES/remakeover.po`.

### After modifying UI strings in source files

Re-extract the message catalog and update existing `.po` files:

```bash
# Re-extract and update all .po files in one step
scripts/update_locales.sh

# Compile .po → .mo (required for non-English languages to take effect)
pybabel compile -d locales -D remakeover
```

The script reads the mapping configuration from `pyproject.toml` (`[tool.babel]`) and skips the `tests/` directory automatically.

Review any entries marked `#, fuzzy` in the `.po` file — they were matched approximately and may need manual correction. Remove the `#, fuzzy` flag once the translation is verified.

### Adding a new language

```bash
# Initialize a new .po file for the language (e.g. German)
pybabel init -i locales/remakeover.pot -d locales -D remakeover -l de

# Edit the generated locales/de/LC_MESSAGES/remakeover.po and fill in msgstr values

# Compile
pybabel compile -d locales -D remakeover
```

Then add the new language code to `SUPPORTED_LANGUAGES` in [src/i18n.py](src/i18n.py) and its display name to the `format_func` dict in [app.py](app.py).

### Rules

- Wrap all UI-visible strings with `_("...")`
- Do not translate log messages
- Do not commit `.mo` files (compiled artifacts)