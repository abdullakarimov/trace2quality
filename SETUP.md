# Development Environment Setup

## ⚠️ Important: Use Virtual Environment Only

**Always install dependencies in `.venv` (virtual environment), NOT system-wide.**

This prevents conflicts with system Python packages and ensures reproducibility across development machines.

### Quick Start

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install project in editable mode with dev dependencies
pip install -e .
pip install beautifulsoup4 google-generativeai httpx sqlalchemy alembic

# Optional: install test dependencies
pip install pytest pytest-asyncio pytest-cov
```

### Why Virtual Environment?

- **Isolation**: Project dependencies don't affect system Python
- **Reproducibility**: Different projects can use different package versions
- **Safety**: Protects system Python installation from breakage
- **Cleanliness**: Easy to reset (`rm -rf venv` and start fresh)

### Common Tasks

**Activate venv before working:**
```bash
source venv/bin/activate
```

**Deactivate when done:**
```bash
deactivate
```

**Run with venv (without activating):**
```bash
./venv/bin/pytest tests/
./venv/bin/python -m pytest tests/
```

**Install new dependency:**
```bash
source venv/bin/activate
pip install package_name
```

### Troubleshooting

**"command not found" after pip install**
- Make sure venv is activated: `source venv/bin/activate`
- Or use full path: `./venv/bin/command_name`

**Import errors when running tests**
- Activate venv: `source venv/bin/activate`
- Or use venv python: `./venv/bin/python -m pytest`

**ModuleNotFoundError for 'bs4'**
- Install in venv: `pip install beautifulsoup4`
- Don't use system `pip3 install` (it installs system-wide)

### .env File

Place integration credentials in `.env` (never commit to git):
```
CONFLUENCE_BASE_URL=https://your-workspace.atlassian.net/wiki
CONFLUENCE_EMAIL=your-email@example.com
CONFLUENCE_TOKEN=your-api-token

AZURE_DEVOPS_ORG_URL=https://dev.azure.com/your-org
AZURE_DEVOPS_PROJECT=your-project
AZURE_DEVOPS_PAT=your-pat-token

JIRA_INSTANCE_URL=https://your-instance.atlassian.net
JIRA_EMAIL=your-email@example.com
JIRA_API_TOKEN=your-api-token

GEMINI_API_KEY=your-gemini-api-key
```

See `.env.example` for template.

### Project Structure

```
t2q/
├── venv/                 # Virtual environment (git-ignored)
├── .venv-python3.11      # Marker file (optional, for IDE detection)
├── apps/                 # FastAPI application
├── packages/             # Core workflow packages
├── tests/                # Test suite
├── docs/                 # Documentation
├── pyproject.toml        # Project metadata & dependencies
└── setup.cfg             # Package discovery config
```

### Dependencies by Purpose

**Core runtime:**
- `fastapi`: Web framework
- `sqlalchemy`: ORM for database
- `pydantic`: Data validation
- `httpx`: Async HTTP client
- `beautifulsoup4`: HTML parsing
- `google-generativeai`: Gemini AI API

**Development & Testing:**
- `pytest`: Test framework
- `pytest-asyncio`: Async test support
- `pytest-cov`: Coverage reporting

**Database:**
- `alembic`: Migration tool
- `sqlalchemy`: SQL toolkit

**Installation from source:**
```bash
# Install project + all optional deps (including dev)
pip install -e ".[dev]"
```

### Making Changes to Dependencies

If you modify `pyproject.toml` dependencies:

```bash
# Reinstall to pick up changes
pip install -e . --force-reinstall --no-cache-dir
```

### Next Steps

- See [ARCHITECTURE.md](ARCHITECTURE.md) for system design
- See [docs/operations/GUIDE.md](docs/operations/GUIDE.md) for operational runbooks
- See [README.md](README.md) for project overview
