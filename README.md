# ClimateGuard AI

ClimateGuard AI is a FastAPI and React application for farm profiles, forecast-based risk indicators, conditional field checks, and crop advisories. Provider data is shown only when it is returned successfully; missing soil, market, or AI output is labeled unavailable rather than replaced with invented readings.

## Run locally on Windows

1. Copy `.env.example` to `.env` and add your own Gemini and data.gov.in keys as needed. Set `OPENAI_API_KEY` to enable OpenAI backup, `GNANI_API_KEY` to enable voice recognition and playback, and `SARVAM_API_KEY` to enable translated assistant advisories. Keep `.env` private and never commit it.
2. From the project root, activate your existing Python 3.11 environment, install `backend/requirements.txt` if needed, and start the API:

   ```powershell
   Set-Location .\backend
   python -m pip install -r requirements.txt
   python -m uvicorn app.main:app --reload
   ```

3. In a separate terminal, install frontend dependencies if needed and run Vite:

   ```powershell
   Set-Location .\frontend
   npm install
   npm run dev
   ```

The dashboard is served at `http://localhost:5173`; FastAPI docs are at `http://localhost:8000/docs`. `VITE_API_BASE_URL` can override the frontend's default API URL.

## Implemented API

- `GET /health`
- `POST /advise` — uses actual forecast, SoilGrids, Agmarknet and configured LLM responses where available.
- `GET/POST /farms`, `GET/PATCH/DELETE /farms/{farm_id}` — local SQLite farm profiles.
- `GET /farms/{farm_id}/actions`, `PATCH /actions/{action_id}` — persisted forecast-conditioned actions and status transitions.
- `GET /alerts`, `PATCH /alerts/{alert_id}`, and farm-scoped alert preference routes.
- `GET /history/weather` — Open-Meteo archive historical reanalysis, explicitly not station observations.
- `GET /analytics/model-status` and `GET /satellite/status` — current capability status.
- `GET /voice/capabilities`, `POST /voice/stt`, and `POST /voice/tts` — Gnani speech services. The installed SDK supports English, Hindi, Bengali, Gujarati, Tamil, Kannada, Telugu, Marathi, Malayalam, and Punjabi for both STT and TTS.
- `POST /assistant/translate` — translates an English advisory using Sarvam's [`sarvam-translate:v1` Text Translation API](https://docs.sarvam.ai/api-reference/text/translate-text) through the official `sarvamai` SDK. Supported language codes are Hindi (`hi`), Bengali (`bn`), Tamil (`ta`), Telugu (`te`), Marathi (`mr`), Gujarati (`gu`), Kannada (`kn`), Malayalam (`ml`), Punjabi (`pa`), Odia (`or`, mapped to API code `od-IN`), Assamese (`as`), Urdu (`ur`), and English (`en`). Translation is independent of the advisory LLM and preserves numerical details, dates, crop names, and source citations.

SQLite data is stored in `backend/data/climateguard.sqlite3`. No authentication or multi-user isolation is implemented; treat the database and API as local development data.

## Provider and model limitations

- Weather forecasts use Open-Meteo. Historical data is requested from Open-Meteo's archive and is labeled reanalysis.
- Soil properties use ISRIC SoilGrids estimates. A successful response may still contain null values for a location; current soil moisture is not measured by SoilGrids.
- Mandi prices use the configured data.gov.in Agmarknet resource and require `MANDI_API_KEY`. Market matches are not claimed to be geographically nearest unless state/district filters are provided.
- Gemini uses Google's `v1beta/models/{model}:generateContent` endpoint and the `x-goog-api-key` header. The configured key must have access to the selected model. A failed, blocked, or malformed response is returned as unavailable.
- When Gemini is unavailable, the LLM router can use OpenAI as a backup. Set backend-only `OPENAI_API_KEY` and optionally `OPENAI_MODEL` (defaults to `gpt-4o-mini`). The selected model must be enabled for the OpenAI API account; authentication, model-access, quota, and rate-limit failures are surfaced safely before the existing rules-based fallback is used.
- Advisory translation uses Sarvam's Text Translation API with the backend-only `SARVAM_API_KEY`. The Sarvam model accepts up to 2,000 characters per request; longer advisories are split at whitespace boundaries. Translation failures, missing credentials, timeouts, and quota errors are shown explicitly rather than returning English as if translated.
- Satellite endpoint currently reports capability status only: STAC search, raster retrieval, cloud masking, and NDVI calculation are not implemented.
- No local crop-risk ML model or labeled dataset is configured. Risk cards are heuristic indicators, not calibrated crop-loss probabilities.

## Tests

From `backend` in the activated environment:

```powershell
python -m unittest discover -s tests -v
```

The live Gemini test is opt-in and makes an external API request:

```powershell
$env:CLIMATEGUARD_LIVE_GEMINI_TEST = "1"
python -m unittest discover -s tests -p test_llm.py -v
Remove-Item Env:CLIMATEGUARD_LIVE_GEMINI_TEST
```

After setting `OPENAI_API_KEY` and `OPENAI_MODEL` in the root `.env`, verify that the model is available to the account with this opt-in API check:

```powershell
$env:CLIMATEGUARD_LIVE_OPENAI_MODEL_TEST = "1"
python -m pytest tests/test_llm.py -k configured_model_is_available_to_api_account -q
Remove-Item Env:CLIMATEGUARD_LIVE_OPENAI_MODEL_TEST
```

## Project layout

- `backend/app` — FastAPI routes, LangGraph orchestration, providers, risk logic and persistence.
- `backend/tests` — unit and API tests.
- `frontend/src` — React dashboard and components.
- `.env.example` — safe environment-variable template; configure secrets only in the untracked local `.env`.
