# 🌍 ClimateGuard AI

### AI-Powered Climate Risk Assessment, Agricultural Intelligence, Smart Grid Planning & Emergency Relief Logistics

**ClimateGuard AI** is a full-stack climate resilience and decision-support platform that combines live environmental data, rule-based risk assessment, AI-assisted recommendations, energy planning, and emergency logistics in one application.

It aims to help farmers, communities, and local infrastructure operators understand climate-related risks and plan practical responses using available weather, soil, satellite, river, and market data.

## 🚀 Live Demo

| Resource | Link |
|---|---|
| 🌐 **Live Application** | [ClimateGuard AI](https://climate-guard-ai-beige.vercel.app/) |
| ⚙️ **Backend Health Check** | [API Health](https://climateguard-ai-kd6e.onrender.com/health) |
| 📚 **Interactive API Documentation** | [FastAPI Swagger UI](https://climateguard-ai-kd6e.onrender.com/docs) |

> **Deployment note:** The frontend is hosted on Vercel and the backend on Render. Free hosting may introduce a delay on the first request after inactivity. Individual features may also depend on third-party service availability and configured API credentials.

---

## 📌 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Application Modules](#-application-modules)
- [Technology Stack](#️-technology-stack)
- [System Architecture](#️-system-architecture)
- [Data Sources and Integrations](#-data-sources-and-integrations)
- [Getting Started](#-getting-started)
- [Environment Configuration](#-environment-configuration)
- [Using the Application](#-using-the-application)
- [API Reference](#-api-reference)
- [Decision Engines](#-decision-engines)
- [Reliability and Error Handling](#-reliability-and-error-handling)
- [Deployment](#-deployment)
- [Testing](#-testing)
- [Repository Structure](#-repository-structure)
- [Security Considerations](#-security-considerations)
- [Limitations](#️-limitations)
- [Troubleshooting](#-troubleshooting)
- [Future Roadmap](#-future-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🌱 Overview

Climate-related events can affect crop productivity, water availability, electricity demand, and the delivery of essential supplies. Addressing these problems requires more than displaying forecasts: users also need to interpret risks and identify possible actions.

ClimateGuard AI combines environmental information with transparent decision rules and optional AI-generated explanations to support several connected workflows.

The platform brings together:

- Environmental data retrieval and analysis.
- Crop-specific climate-risk indicators.
- Agricultural recommendations and field-action planning.
- Multilingual conversational assistance.
- Solar and battery-aware energy scheduling.
- Hazard-aware emergency supply planning.
- Operational records and outcome validation.

### Design Philosophy

ClimateGuard AI follows four principles:

1. **Evidence over assumptions:** Missing observations should be reported rather than silently replaced with fabricated values.
2. **Explainable decisions:** Risk and planning calculations should be inspectable.
3. **Graceful degradation:** An unavailable optional provider should not unnecessarily disable unrelated features.
4. **Responsible automation:** Recommendations and simulated operations should be reviewed before being used in real-world decisions.

---

## ✨ Key Features

- 🌦️ **Climate intelligence:** Forecast-driven assessment of heat, rainfall, flooding, and water stress.
- 🌾 **Crop-aware advisory:** Recommendations based on available environmental conditions and crop context.
- 🛰️ **Satellite monitoring:** Vegetation-health trends using Sentinel-2 imagery and NDVI.
- 🤖 **AI-assisted recommendations:** Configurable language-model providers with fallback mechanisms where implemented.
- 🗣️ **Multilingual assistance:** Support for conversational interaction in multiple Indian languages.
- ⚡ **Smart-grid planning:** Solar generation estimates, load prioritization, battery reserve management, and scheduling.
- 🚚 **Relief logistics:** Hazard checks, supplier inventory evaluation, vehicle assignment, and proposed deliveries.
- 📊 **Outcome validation:** Infrastructure for comparing assessments with recorded outcomes.
- 🔄 **Resilient integrations:** Timeouts, caching, provider status reporting, and partial results where supported.
- 🗺️ **Interactive maps:** Location selection and geographic visualization.

---

## 🧩 Application Modules

### 1. 🌾 Farm Advisory

Provides agricultural guidance based on location, crop information, and available environmental data.

**Capabilities:**

- Weather forecasts and historical weather information.
- Crop-specific risk indicators.
- Soil-property estimates.
- Market-price information through configured data sources.
- Field-action plans and alerts.
- Farm profiles and crop information.
- AI-assisted recommendations with rule-based fallback where available.

**Workflow:**

1. Select a location.
2. Choose the crop and language.
3. Enter or select relevant farm information.
4. Retrieve available environmental data.
5. Review risk indicators, recommendations, and suggested actions.

### 2. 🌍 Climate & Yield Risk

Assesses potential climate hazards for a selected location and crop.

**Capabilities:**

- Heat-stress indicators.
- Heavy-rainfall and flood-risk indicators.
- Drought and water-deficit assessment.
- Waterlogging indicators.
- Soil-moisture and temperature context.
- Irrigation-demand estimates.
- Sowing and dry-weather windows.
- Hazard-grid visualization.
- Satellite-based vegetation trends.
- Supporting evidence and data-source status.

The risk engine uses transparent rules and generalized crop parameters. Its scores should be interpreted as risk indicators, not calibrated probabilities of crop loss.

### 3. 🗣️ Voice Assistant

Provides conversational access to climate and agricultural information.

**Capabilities:**

- Typed questions and supported voice interactions.
- Location- and crop-aware context where available.
- Multilingual responses.
- Browser-based speech input and read-aloud functionality.
- Optional third-party voice and translation integrations.

Language support and voice quality depend on the configured providers, browser, and device.

### 4. ⚡ Smart Grid

Supports energy planning for local infrastructure such as clinics, water pumps, and micro-grids.

**Capabilities:**

- Solar generation estimates.
- Battery reserve management.
- Priority-based load scheduling.
- Cooling-demand estimates.
- Deferrable-load scheduling.
- Water-pump scheduling when sufficient information is available.
- Energy plans based on available inputs.
- Telemetry-aware planning.

**Workflow:**

1. Register a site and select its location.
2. Enter solar, battery, inverter, and grid-limit information.
3. Register electrical loads and assign priorities.
4. Submit recent device telemetry where available.
5. Generate and review the energy plan.

The planner is rule-based and does not automatically learn electricity-demand patterns.

### 5. 🚚 Relief Logistics

Helps plan emergency supply deliveries for registered communities and sites.

**Capabilities:**

- Hazard assessment for registered zones.
- Supplier and inventory management.
- Vehicle registration and assignment.
- Rain-aware route evaluation.
- Relief-order generation.
- Response-cycle logs and operational status tracking.
- Optional supplier inventory APIs and dispatch webhooks.
- Dry-run operation for safer testing.

**Workflow:**

1. Register the communities or sites that require protection.
2. Register suppliers and available stock.
3. Register vehicles and their positions.
4. Check hazards for the registered zones.
5. Run a response cycle.
6. Review the proposed orders, routes, and agent logs.
7. Verify the outcome before enabling any real dispatch integration.

If the application reports **“No zones registered,”** add zone records before running the response cycle.

Keep **Dry run** enabled while testing. In dry-run mode, the planner should not contact suppliers or reserve stock.

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React, Vite, JavaScript |
| Maps | Leaflet and map-tile providers |
| Backend | Python, FastAPI, Uvicorn |
| Data validation | Pydantic |
| AI orchestration | LangGraph and Python services |
| Language models | Configurable Gemini, OpenAI, Anthropic, or Groq integrations |
| Database | SQLite |
| Weather data | Open-Meteo |
| Soil data | ISRIC SoilGrids |
| Satellite data | Sentinel-2 through Earth Search STAC |
| Climate indicators | NASA POWER and NOAA CPC datasets |
| Market data | Agmarknet through data.gov.in |
| Routing | OSRM |
| Deployment | Vercel, Render, Docker, Docker Compose |

The availability of individual integrations depends on provider access, API quotas, credentials, and current service conditions.

---

## 🏗️ System Architecture

ClimateGuard AI uses a React/Vite frontend and a Python FastAPI backend.

### Request Workflow

1. The user selects a location, crop, site, or operational task.
2. The frontend sends a request to the backend API.
3. The backend validates the input and retrieves relevant data.
4. Rule-based services calculate risk indicators, schedules, or proposed actions.
5. Optional language-model providers generate contextual advisory text.
6. The backend returns results and any available warnings or source-status information.
7. The frontend presents the results to the user.

### Architectural Principles

- **Modular services:** Weather, soil, market, advisory, grid, and logistics responsibilities are separated.
- **Inspectable decision logic:** Risk calculations and planning rules can be reviewed independently.
- **Partial results:** Optional provider failures should not unnecessarily disable unrelated features.
- **Separated persistence:** Farm/advisory records and operational records use separate SQLite databases.
- **Explicit uncertainty:** Modelled measurements and estimated soil properties should not be mistaken for direct observations.

---

## 🌐 Data Sources and Integrations

| Provider | Purpose | Credentials |
|---|---|---|
| Open-Meteo | Weather forecasts, historical weather, ET0, modelled soil variables, and irradiance | No key required for configured public endpoints |
| Open-Meteo Flood API / GloFAS | River discharge forecasts and flood indicators | No key required for configured public endpoints |
| NASA POWER | Long-term monthly rainfall normals | No key required for configured service |
| ISRIC SoilGrids | Estimated soil texture, organic carbon, pH, and related properties | No key required |
| NOAA Climate Prediction Center | ENSO indicators such as the Oceanic Niño Index | No key required |
| data.gov.in / Agmarknet | Agricultural market prices | `MANDI_API_KEY` |
| Earth Search STAC / Sentinel-2 | Satellite imagery and NDVI time series | No key configured by default |
| OSRM | Road-route estimates | Public routing endpoint by default |
| OpenStreetMap contributors | Map data and attribution | Depends on tile provider |
| NASA GIBS | Optional satellite-map layers | No key configured by default |
| Gemini, OpenAI, Anthropic, Groq | Optional AI advisory providers | Provider-specific API keys |
| Gnani and Sarvam | Optional voice and translation services | Provider-specific API keys |

Provider access, quotas, licensing, and commercial-use conditions can change. Review each provider's current documentation before relying on an integration.

---

## 🚀 Getting Started

### Prerequisites

Install the following:

- Python **3.11**
- Node.js **18 or later**
- npm
- Git
- Optional: Docker and Docker Compose

Some features require API credentials. The application can run without optional credentials, but the associated integrations may return unavailable results or use a labelled fallback.

### 1. Clone the Repository

```bash
git clone https://github.com/khushi-srivastava4/ClimateGuard-AI.git
cd ClimateGuard-AI
```

If your repository has a different URL, replace the URL above with your repository's clone URL.

### 2. Configure Environment Variables

Copy `.env.example` to `.env`.

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

**macOS / Linux:**

```bash
cp .env.example .env
```

Open `.env` and configure the variables required for your intended features.

Never commit `.env` or paste private API keys into public issues, logs, or README files.

### 3. Start the Backend

Run these commands from the repository root.

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

**macOS / Linux:**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

If your current repository revision uses a different requirements file, follow the file actually present in the backend directory.

The backend should be available at:

- API: `http://localhost:8000`
- Health check: `http://localhost:8000/health`
- Interactive API documentation: `http://localhost:8000/docs`

### 4. Start the Frontend

Open a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Vite normally serves the frontend at:

`http://localhost:5173`

The frontend needs the correct API origin. For local development, this is usually `http://localhost:8000`.

### 5. Verify the Application

1. Open `http://localhost:8000/health`.
2. Open `http://localhost:8000/docs`.
3. Start the frontend.
4. Open the application in your browser.
5. Test the Climate & Yield Risk module with a selected location.
6. Test Smart Grid and Relief Logistics using sample records.
7. Check the browser console and backend logs if any API request fails.

---

## ⚙️ Environment Configuration

Use `.env.example` as the starting point. Check `backend/app/config.py` for the variables supported by your current revision.

| Variable | Purpose |
|---|---|
| `ENV` | Runtime environment, such as development or production |
| `CORS_ORIGINS` | Comma-separated list of permitted browser origins |
| `DATA_DIR` | Directory used for application databases and disk-backed caches |
| `CACHE_TTL` | Cache lifetime in seconds |
| `HTTP_TIMEOUT` | Base timeout for external provider requests |
| `ADVISE_TIMEOUT` | Overall time limit for an advisory request |
| `MANDI_API_KEY` | Key for data.gov.in / Agmarknet integration |
| `LLM_PROVIDER` | Primary language-model provider |
| `LLM_API_KEY`, `LLM_MODEL` | Primary LLM credentials and model selection |
| `LLM_BASE_URL` | Optional OpenAI-compatible API endpoint |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional OpenAI provider |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Optional Anthropic provider |
| `GROQ_API_KEY`, `GROQ_MODEL` | Optional Groq provider |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini credentials and model selection |
| `OSRM_URL` | Routing-service base URL |
| `RELIEF_AUTOPILOT_MINUTES` | Optional interval for automatic relief-agent runs |
| `RELIEF_MIN_LEVEL` | Minimum hazard level for autopilot |
| `OPS_DB` | Optional explicit path to the operations database |
| `ADMIN_TOKEN` | Token for selected protected write operations |
| `RATE_LIMIT_PER_MIN` | General request rate limit |
| `RATE_LIMIT_HEAVY_PER_MIN` | Rate limit for expensive requests |
| `TRUST_PROXY` | Whether to trust forwarded client IP headers |
| `MAX_REQUEST_BODY_BYTES` | Maximum accepted request-body size where enforced |
| `ALLOWED_SUPPLIER_HOSTS` | Optional allow-list for supplier API/webhook hosts |
| `GNANI_API_KEY` | Optional Gnani integration |
| `SARVAM_API_KEY` | Optional Sarvam integration |
| `VITE_API_BASE_URL` | Frontend API origin embedded at build time |

Only configure variables that the current code reads. An environment variable has no effect unless the application uses it.

### API Key Security

- Keep provider API keys on the backend.
- Never expose secret keys through `VITE_*` environment variables.
- Never commit `.env` files.
- Configure credentials through the hosting provider's environment-variable settings.
- Rotate credentials immediately if they are accidentally exposed.

---

## 🖥️ Using the Application

### Farm Advisory

1. Select a location on the map or provide coordinates.
2. Choose the crop and language.
3. Enter farm details if required.
4. Review the available forecasts and risk indicators.
5. Read the recommendations, action plan, and alerts.

An unavailable value should not be interpreted as zero risk.

### Climate & Yield Risk

1. Select a location.
2. Choose a crop and relevant agricultural parameters.
3. Run the assessment.
4. Review the risk indicators and their supporting evidence.
5. Inspect the available satellite, rainfall, irrigation, and source-status information.
6. Record observed outcomes where the application supports it.

### Voice Assistant

Type a question or use the microphone if voice input is supported and permission is granted. Browser-based speech features work best in a supported browser over HTTPS.

### Smart Grid

1. Register a site.
2. Configure solar, battery, inverter, and grid limits.
3. Register loads and assign priorities.
4. Submit current telemetry where available.
5. Generate the energy plan.
6. Review the schedule and warnings before taking action.

Stale or missing battery and tank readings can limit the actions the planner can safely recommend.

### Relief Logistics

1. Register the zones or communities to protect.
2. Add suppliers and their stock information.
3. Register vehicles and their positions.
4. Run the hazard check.
5. Run a response cycle with **Dry run** enabled.
6. Review proposed orders and the agent log.
7. Verify supplier and dispatch integrations before enabling real operations.

The relief planner cannot generate useful deliveries if the required zones or supplier information are missing.

---

## 📚 API Reference

The deployed API documentation is available here:

**[Open ClimateGuard AI API Documentation](https://climateguard-ai-kd6e.onrender.com/docs)**

The following table summarises selected routes. The deployed `/docs` page is the authoritative reference for the routes actually registered by the running backend.

### Core and Farm Advisory

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/advise` | Advisory workflow |
| `GET`, `POST` | `/farms` | List or create farm profiles |
| `GET`, `PATCH`, `DELETE` | `/farms/{id}` | Read, update, or delete a farm |
| `GET` | `/farms/{id}/actions` | Read field actions |
| `PATCH` | `/actions/{id}` | Update an action |
| `GET` | `/alerts` | List alerts |
| `PATCH` | `/alerts/{id}` | Update an alert |
| `GET`, `PUT` | `/farms/{id}/alert-preferences` | Read or update alert settings |
| `GET` | `/history/weather` | Historical weather |
| `GET` | `/analytics/model-status` | Model and validation status |
| `GET` | `/satellite/status` | Satellite capability status |

### Climate Insights and Assistant

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/insights/risk` | Crop-aware risk assessment |
| `GET` | `/insights/grid` | Hazard-grid information |
| `GET` | `/satellite/ndvi` | NDVI time series and trend |
| `POST` | `/advise/v2` | Assessment and multilingual advisory |
| `POST` | `/assistant/chat` | Conversational assistant |

### Smart Grid

| Method | Path | Purpose |
|---|---|---|
| `GET`, `POST` | `/grid/sites` | List or create sites |
| `DELETE` | `/grid/sites/{id}` | Delete a site |
| `POST` | `/grid/telemetry` | Submit device telemetry |
| `GET` | `/grid/telemetry/{site}` | Read site telemetry |
| `GET` | `/grid/plan/{site}` | Generate an energy plan |

### Relief Logistics

| Method | Path | Purpose |
|---|---|---|
| `GET`, `POST` | `/relief/zones` | List or register zones |
| `GET`, `POST` | `/relief/suppliers` | List or register suppliers |
| `GET`, `POST` | `/relief/fleet` | List or register vehicles |
| `GET` | `/relief/hazards` | Assess hazards by zone |
| `POST` | `/relief/run` | Run a response cycle |
| `GET` | `/relief/runs` | Read agent logs |
| `GET` | `/relief/orders` | Read relief orders |
| `PATCH` | `/relief/orders/{id}` | Update an order |

### Validation

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/analytics/outcomes` | Record an observed outcome |
| `GET` | `/analytics/validation` | Read validation statistics |

---

## 🧠 Decision Engines

ClimateGuard AI currently relies on transparent rules and thresholds for its risk and planning calculations. It should not be described as a trained crop-loss prediction system.

### Climate Risk Engine

The original risk engine includes rules such as:

- **Heat score:** `(forecast maximum temperature − 28) × 7.25`, clamped to `0–100`.
- **Heavy rainfall:** Uses forecast rainfall totals and heavy-rainfall thresholds.
- **Waterlogging:** Uses multi-day rainfall and crop tolerance, with soil information where available.
- **Drought:** Uses the drought service when required inputs are available.
- **Overall score:** Uses the highest available hazard score.

In this original engine, categories are high at scores of `75` or more, moderate at `40–74`, and low below `40`.

The crop-aware risk engine also considers weather history, modelled soil moisture, soil temperature, ET0, rainfall normals, river discharge, and estimated soil texture where available.

These calculations are heuristic indicators, not calibrated probabilities of crop loss.

### AI Advisory

The advisory workflow can use configured language-model providers to generate contextual recommendations. Provider failover may be used when configured.

If a provider is unavailable, the application may return a labelled rule-based summary. A fallback summary should not be presented as an AI-generated response.

### Smart Grid Planner

The planner uses deterministic rules to:

- Estimate solar generation from installed capacity and irradiance.
- Apply performance and temperature adjustments.
- Respect inverter and grid-import limits.
- Prioritize loads.
- Preserve configured battery reserves.
- Schedule deferrable loads when possible.
- Consider water-tank readings when scheduling pumps.

The planner is not a formal mathematical optimization solver.

### Relief Logistics Agent

The relief agent follows an **observe → plan → route → act → recover** workflow.

It can:

- Assess hazards for registered zones.
- Check supplier inventory where configured.
- Compare candidate routes using travel estimates and rainfall information.
- Consider alternatives when stock or route conditions are unsuitable.
- Assign available vehicles where possible.
- Prepare orders for dispatch or use a configured webhook.
- Record actions and outcomes in an audit log.

Route evaluation does not provide a complete view of road closures, damaged bridges, traffic, or real-time emergency conditions.

### Outcome Validation

The project provides mechanisms for recording observed outcomes and evaluating assessments. Metrics such as AUC and Brier score require sufficient labelled observations. Until adequate data is available, the results should not be treated as evidence of validated predictive performance.

---

## 🔄 Reliability and Error Handling

The application includes mechanisms intended to improve reliability:

- Bounded provider timeouts and retries.
- Caching for selected data sources.
- Stale-data warnings where supported.
- Source-health information for risk assessments.
- Partial results when optional providers are unavailable.
- Input validation for coordinates and relevant parameters.
- Fallback map-tile sources.
- An edge agent that can use a cached plan for a limited period.

These behaviours should be verified against the deployed revision and current provider responses.

---

## 🐳 Docker

### Development

```bash
docker compose up --build
```

The development configuration is intended to run the backend and frontend, typically on ports `8000` and `5173`.

### Production-Oriented Compose

```bash
docker compose -f docker-compose.prod.yml up --build
```

The production-oriented setup serves the frontend through Nginx, typically on port `8080`, with the API on port `8000`.

Review the Compose files and configure the frontend API origin for your own network before deployment.

---

## 🌐 Deployment

Deployment configuration is also documented in [`DEPLOY.md`](DEPLOY.md).

### Render Backend + Vercel Frontend

The current hosted deployment uses:

- **Frontend:** [Vercel](https://climate-guard-ai-beige.vercel.app/)
- **Backend:** [Render](https://climateguard-ai-kd6e.onrender.com/)
- **API documentation:** [Swagger UI](https://climateguard-ai-kd6e.onrender.com/docs)

#### Backend configuration

In Render, configure the environment variables through the service dashboard.

For example:

```env
ENV=production
CORS_ORIGINS=https://climate-guard-ai-beige.vercel.app
```

Use the exact deployed frontend origin without a trailing slash. Keep other required variables configured according to the backend code.

#### Frontend configuration

In Vercel, set:

```env
VITE_API_BASE_URL=https://climateguard-ai-kd6e.onrender.com
```

Do not add a trailing slash.

Because Vite embeds `VITE_*` variables during the build, redeploy the frontend after changing this value.

#### Deployment verification

1. Open the backend health endpoint.
2. Open the backend `/docs` page.
3. Confirm `CORS_ORIGINS` matches the frontend origin exactly.
4. Confirm `VITE_API_BASE_URL` points to the backend.
5. Redeploy after environment-variable changes.
6. Open browser DevTools → **Network** and **Console**.
7. Verify that API requests use the expected paths and return appropriate status codes.

**Diagnosing common errors:**

- `Failed to fetch`: May indicate CORS, an unavailable backend, an incorrect API URL, or a network failure.
- `404 Not Found`: The requested path may be incorrect or absent from the deployed backend.
- `500 Internal Server Error`: Inspect backend logs for the exception.
- Changes to frontend environment variables not appearing: Trigger a new frontend build and deployment.

### Storage Considerations

SQLite data on ephemeral hosting storage may disappear after restarts or redeployments. Use durable storage if farm profiles, operational records, or other data must persist.

---

## 🧪 Testing

### Backend Tests

From the repository root:

```bash
cd backend
python -m pytest tests -q
```

Run tests in the project's supported Python environment.

### Frontend Production Build

```bash
cd frontend
npm ci
npm run build
```

A successful build verifies frontend compilation but does not prove that deployed APIs, external providers, CORS, or credentials are configured correctly.

### Manual Smoke-Test Checklist

- [ ] Backend `/health` responds successfully.
- [ ] API documentation loads.
- [ ] Frontend loads over HTTPS.
- [ ] Browser console has no CORS errors.
- [ ] API requests target the expected backend origin.
- [ ] Climate-risk assessment returns results or clear availability warnings.
- [ ] Voice functionality works when configured.
- [ ] Smart-grid site and telemetry flows work.
- [ ] Relief zones, suppliers, and vehicles can be registered.
- [ ] Relief response cycles work in dry-run mode.
- [ ] Optional provider integrations are tested individually.

---

## 📁 Repository Structure

```text
ClimateGuard-AI/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── agent/
│   │   ├── routers/
│   │   ├── services/
│   │   ├── persistence/
│   │   ├── models/
│   │   └── utils/
│   └── tests/
├── frontend/
│   └── src/
│       ├── Root.jsx
│       ├── App.jsx
│       ├── components/
│       ├── i18n/
│       └── api/
├── edge/
│   └── edge_agent.py
├── docker-compose.yml
├── docker-compose.prod.yml
├── render.yaml
├── DEPLOY.md
├── .env.example
└── README.md
```

This is a high-level guide to the major components. Refer to the current repository tree for the exact files included in your revision.

---

## 🔐 Security Considerations

- The current design does not provide comprehensive authentication and per-user data isolation.
- `ADMIN_TOKEN` protects selected write operations only and is not a replacement for full authentication.
- CORS is a browser access policy, not an authentication mechanism.
- Keep `.env` and private API keys out of version control.
- Never expose provider secrets through frontend code or browser-visible environment variables.
- Restrict supplier API and webhook destinations to trusted hosts where possible.
- In-process rate limits are not coordinated across multiple backend instances.
- Redact API keys, tokens, personal information, and sensitive request content from shared logs.
- Do not enable relief autopilot or real dispatch until integrations and failure handling have been tested.
- Do not connect the edge agent to critical equipment until its decisions and fail-safe behaviour have been independently reviewed.

---

## ⚠️ Limitations

- **No trained crop-loss model:** Risk scores are heuristic indicators and are not calibrated probabilities.
- **Estimated soil inputs:** SoilGrids values are estimates, and soil moisture may be modelled rather than directly measured.
- **General crop thresholds:** Crop parameters are broad rules of thumb and should be reviewed against local agricultural conditions.
- **Satellite coverage:** NDVI quality depends on image availability, cloud filtering, and spatial resolution.
- **Incomplete route context:** Rain-aware route checks do not fully model road closures, damaged bridges, or traffic.
- **Market-data dependency:** Market information depends on published records and provider availability.
- **Rule-based energy planning:** The grid planner does not automatically learn demand patterns.
- **Browser-based voice:** Speech features depend on browser support and permissions.
- **Partial interface localisation:** Interface labels are available in English and Hindi; other interface text may fall back to English.
- **Hosting constraints:** Free hosting may have cold starts and ephemeral storage.

ClimateGuard AI is a decision-support prototype. It is not a replacement for official warnings, emergency services, qualified agronomic advice, or site-specific electrical safety assessments.

---

## 🛠️ Troubleshooting

| Problem | Possible cause | Suggested action |
|---|---|---|
| Backend fails to start | Dependency or import error | Check the traceback and installed Python dependencies |
| AI advisory falls back to rules | Missing key, quota, timeout, or provider outage | Check backend logs and provider configuration |
| Gemini returns `429` | Provider quota or rate limit reached | Check quota and configure a backup provider |
| Market prices unavailable | Missing key, source outage, or timeout | Check `MANDI_API_KEY` and backend logs |
| Soil values unavailable | No provider value or rate limit | Check source status and retry later |
| NDVI returns `501` | Optional raster dependency unavailable | Check the installed `rasterio` and `numpy` versions |
| Map tiles are blank | Tile provider or network issue | Inspect failed tile requests in DevTools |
| Microphone unavailable | Permission or browser limitation | Use a supported browser over HTTPS and allow microphone access |
| Relief agent creates no orders | No zones, missing stock, or unsuitable routes | Review the agent log and register required operational records |
| Grid planner ignores battery state | Missing or stale telemetry | Submit current telemetry and verify timestamps |
| Frontend shows `Failed to fetch` | Wrong API URL, CORS, backend outage, or network issue | Inspect DevTools → Network and Console |
| API returns `404` | Incorrect URL or route not registered | Compare the request with the deployed `/docs` page |
| API returns `500` | Backend exception | Inspect Render logs for the failing request |
| Frontend environment changes have no effect | Old Vite build | Update Vercel environment variables and redeploy |
| Data disappears after restart | Ephemeral database storage | Configure durable storage if persistence is required |

When reporting a bug, include the endpoint, HTTP status, and relevant error message. Never include API keys or other secrets.

---

## 🔮 Future Roadmap

- Improve integration between crop-risk insights and farm advisory workflows.
- Add field-polygon support for satellite vegetation monitoring.
- Expand interface localisation and improve Indian-language speech support.
- Introduce authentication, user roles, and stronger operational access controls.
- Add optional SMS and WhatsApp alerts.
- Calibrate risk scores using labelled observations and official loss data.
- Improve routing with road-closure and traffic information.
- Explore optimization-based dispatch and energy scheduling.
- Improve persistent storage and deployment observability.

---

## 📚 Data Sources and Attribution

The project uses or may use data and services from:

- Open-Meteo
- NASA POWER
- ISRIC SoilGrids
- NOAA Climate Prediction Center
- Copernicus Sentinel-2
- OpenStreetMap contributors
- OSRM
- CARTO
- Esri
- NASA GIBS
- India's Open Government Data Platform and Agmarknet

Review the current licence, attribution, API usage policy, rate limits, and commercial-use terms for each provider before deployment or redistribution. Keep required map attributions visible.

---

## 🤝 Contributing

Contributions that improve correctness, reliability, accessibility, testing, and documentation are welcome.

Before opening a pull request:

1. Keep secrets and local data out of commits.
2. Run backend tests and the frontend production build.
3. Document new environment variables and provider requirements.
4. Add tests for new decision logic and failure paths.
5. Make missing-data behaviour and uncertainty explicit.
6. Update this README and `DEPLOY.md` when setup or deployment steps change.

---

## 📄 License

No project licence is specified in this README. Add a `LICENSE` file if you intend to grant others explicit rights to use, modify, and redistribute the project.

---

<p align="center">
  Built to explore practical applications of climate intelligence, AI-assisted decision support, and community resilience.
</p>
