# Praxys

Sports science that meets you where you are. Praxys syncs data from Garmin, Stryd, and Oura Ring, computes training metrics (fitness/fatigue/form, zone analysis, CP trend, race predictions), and serves a modern web dashboard with AI-powered coaching skills — for elite athletes, serious amateurs, and curious beginners alike.

![Praxys — Sports science that meets you where you are.](data/screenshots/hero-showcase.png)

> **Note:** Praxys is the new name for the project formerly known as Trainsight. The on-disk database file (`trainsight.db`) and legacy `TRAINSIGHT_*` environment variables continue to work during the deprecation window — see `docs/brand/index.html` for the brand guideline.

## Usage Modes

**Cloud app (recommended):** Deployed on Azure at [praxys.run](https://praxys.run). Register, connect your platforms, sync data, and view the dashboard from anywhere. AI features available via the CLI plugin in remote mode.

**Local development:** Same codebase runs locally. Start the backend and frontend dev servers, register as the first user (becomes admin), and you are up and running.

## Quick Start (Local Development)

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add the generated key as PRAXYS_LOCAL_ENCRYPTION_KEY in .env

# 3. Start the API server
python -m uvicorn api.main:app --reload

# 4. Start the frontend dev server (separate terminal)
cd web && npm install && npm run dev

# 5. Open http://localhost:5173 and register as the first user (becomes admin)
```

For sample data without API credentials: `python scripts/seed_sample_data.py`

## Documentation

- [Brand Guideline](docs/brand/index.html)
- [Getting Started](docs/getting-started.md)
- [Security](docs/security.md)
- [Architecture](docs/dev/architecture.md)
- [Deployment](docs/deployment.md)
- [CLI Skills](docs/skills.md)
- [Features](docs/features.md)
- [API Reference](docs/dev/api-reference.md)
- [Contributing](docs/dev/contributing.md)
- [Webhook Feasibility (Oura + Garmin)](docs/studies/webhook-feasibility.md)

## Legal

### License

Praxys is released under the [MIT License](LICENSE).

### Trademarks

Garmin, Stryd, Oura, and WeChat are trademarks of their respective owners. Praxys is not affiliated with, endorsed by, or sponsored by any of these companies. Logos and names are used solely to identify the data sources the app can sync from.

### Third-party data sources

- **Garmin Connect** — synced via the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) Python library. There is no official Garmin partnership; the integration depends on Garmin's consumer web endpoints continuing to work. Garmin's [Terms of Use](https://www.garmin.com/en-US/legal/general-terms-of-use/) restrict automated access — use at your own risk.
- **Stryd** — synced via the same email/password endpoints the Stryd web app uses. There is no official partner API for individual users. Same risk class as Garmin.
- **Oura Ring** — synced via the [official Oura API v2](https://cloud.ouraring.com/v2/docs) using a Personal Access Token. This is a supported integration path.

You retain full ownership of your data. Praxys stores it on your own database (local for local development, your own Azure deployment for cloud).
