# Copilot Instructions for do-surf-functions

## Project Overview
This repository is a Python backend for surf forecasting and beach data management, with Firebase integration. It consists of modular scripts for interacting with Firestore, external APIs, and cloud storage. The workspace also includes Node.js functions for Firebase deployment.

## Key Components
- `scripts/`: Main Python logic for data fetching, processing, and service integration.
  - `firebase_utils.py`, `firestore_service.py`, `storage.py`: Firebase/Firestore operations
  - `forecast_api.py`, `open_meteo.py`: External weather/forecast API integration
  - `locations.json`: Canonical list of supported beaches (region, beach, lat/lon)
- `functions/`: Node.js Firebase functions (see `package.json` for dependencies)
- `secrets/`: Credentials and secrets (never commit changes here)
- `main.py`: Entrypoint for running scripts or orchestrating workflows

## Developer Workflows
- **Python dependencies:** Install via `pip install -r requirements.txt`
- **Node.js functions:** Use `npm install` in `functions/` for Firebase dependencies
- **Testing:** Python tests are in `scripts/test_update_logger.py` (run with `pytest scripts/test_update_logger.py`)
- **Firebase deployment:** Use Firebase CLI (`firebase deploy`) for cloud functions

## Patterns & Conventions
- All beach/location data is managed via `scripts/locations.json` (format: array of objects with region, beach, lat, lon)
- API keys and credentials are loaded from `secrets/` (never hardcode secrets)
- Service boundaries: Python scripts handle data logic; Node.js functions handle cloud triggers
- Use descriptive function names and docstrings for all service methods
- Prefer modular, single-responsibility scripts in `scripts/`

## Integration Points
- Firestore: Access via `firebase_utils.py` and `firestore_service.py`
- External APIs: Weather/forecast via `forecast_api.py` and `open_meteo.py`
- Cloud Storage: Managed in `storage.py`
- Secrets: Load from `secrets/secrets.json` and `secrets/serviceAccountKey.json`

## Examples
- To add a new beach, update `scripts/locations.json` with a new object
- To fetch forecasts, use methods in `forecast_api.py` or `open_meteo.py`
- To update Firestore, use service methods in `firebase_utils.py` or `firestore_service.py`

## Cautions
- Never commit changes to `secrets/`
- Always validate location data format in `locations.json`
- Keep Python and Node.js dependencies up to date

---

_If any section is unclear or missing important project-specific details, please provide feedback to improve these instructions._
