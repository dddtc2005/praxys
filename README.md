# Trainsight

Power-based scientific training system for self-coached endurance athletes. Trainsight syncs data from Garmin, Stryd, and Oura Ring, computes training metrics (fitness/fatigue/form, zone analysis, CP trend, race predictions), and serves a modern web dashboard with AI-powered coaching skills.

![Trainsight — Train like it's a science.](data/screenshots/hero-showcase.png)

## Usage Modes

**Cloud app (recommended):** Deployed on Azure at [jolly-sand-0aeced900.7.azurestaticapps.net](https://jolly-sand-0aeced900.7.azurestaticapps.net). Register, connect your platforms, sync data, and view the dashboard from anywhere. AI features available via the CLI plugin in remote mode.

**Local development:** Same codebase runs locally. Start the backend and frontend dev servers, register as the first user (becomes admin), and you are up and running.

## Quick Start (Local Development)

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add the generated key as ENCRYPTION_KEY in .env

# 3. Start the API server
python -m uvicorn api.main:app --reload

# 4. Start the frontend dev server (separate terminal)
cd web && npm install && npm run dev

# 5. Open http://localhost:5173 and register as the first user (becomes admin)
```

For sample data without API credentials: `python scripts/seed_sample_data.py`

## Documentation

- [Getting Started](docs/getting-started.md)
- [Security](docs/security.md)
- [Architecture](docs/dev/architecture.md)
- [Deployment](docs/deployment.md)
- [CLI Skills](docs/skills.md)
- [Features](docs/features.md)
- [API Reference](docs/dev/api-reference.md)
- [Contributing](docs/dev/contributing.md)
