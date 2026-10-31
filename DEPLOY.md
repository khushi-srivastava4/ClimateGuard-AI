# Production deployment

## Architecture

- **API:** FastAPI in `backend/`, shipped as a single-worker Python 3.11 Docker web service on Render.
- **Web app:** React/Vite static build in `frontend/`, hosted by Vercel. `VITE_API_BASE_URL` is embedded during the Vite build.
- **Storage:** all backend SQLite databases and disk caches use `DATA_DIR`. The Render Blueprint mounts a persistent disk there. Local production Compose uses the named `backend-data` volume.
- **Local development:** `docker-compose.yml` and the `Dockerfile.dev` files retain hot-reload/source-mount behavior. `docker-compose.prod.yml` uses production images without source mounts.

The backend runs one worker because SQLite use and in-process rate-limit state are not configured for multi-worker coordination. The in-memory limiter is also per-instance; it is not a distributed abuse-prevention service.

## Render backend and Vercel frontend

Deploy the backend first so Vercel can be configured with its final URL.

1. Push the `main` branch to the Git provider and create a Render Blueprint from the repository using `render.yaml`. The service root is `backend`; the Blueprint builds its production Dockerfile and checks `/health`.
2. Select a paid Render plan that supports persistent disks. The Blueprint mounts its disk at `/var/data`; `DATA_DIR` is set to that path. Free instances do not provide persistent disks and their local filesystem may be discarded on restart or redeploy.
3. In the Render service environment, add the provider keys you use. `LLM_API_KEY` is the primary provider credential selected by `LLM_PROVIDER`; `OPENAI_API_KEY` is an optional OpenAI failover key. Set any voice, translation, and mandi credentials as needed. Keep credentials in Render's secret environment settings.
4. Wait for the Render deployment to become healthy and copy its service URL, for example `https://<render-service>.onrender.com`.
5. In Vercel, import the repository and set **Root Directory** to `frontend`, **Build Command** to `npm run build`, and **Output Directory** to `dist`. Add `VITE_API_BASE_URL` with the exact Render API origin, without a path suffix. Vite embeds this at build time.
6. Deploy the Vercel frontend and copy its production origin, for example `https://<your-project>.vercel.app`.
7. Set Render's `CORS_ORIGINS` to the exact Vercel production origin. Add additional origins only when required (for example a known preview origin). Do not use `*`.
8. Redeploy the Render backend after changing `CORS_ORIGINS`.
9. Verify the API and frontend using the checks below. Changing `VITE_API_BASE_URL` requires a new Vercel build/deployment.

`frontend/vercel.json` provides the SPA fallback, immutable caching for `/assets/`, non-cacheable `index.html`, and basic security headers.

## Environment variables

The checked-in `.env.example` contains the backend variables and safe local defaults; `frontend/.env.example` documents the Vite API URL. Never commit `.env` or put backend credentials in `frontend/.env*` or Vercel.

| Variable | Required | Purpose |
|---|---:|---|
| `ENV` | Deployment | Use `production` on Render for credential-presence and CORS warnings. |
| `PORT` | Platform | Render supplies this; the container binds to it. Locally it defaults to `8000`. |
| `DATA_DIR` | Deployment | Persistent data root; set to `/var/data` on Render. Default is `backend/data`. |
| `CORS_ORIGINS` | Deployment | Comma-separated exact browser origins. Set the Vercel origin after the frontend is deployed. |
| `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | Optional | Primary advisory provider. Defaults use Gemini. Do not configure `LLM_BASE_URL` unless the provider is intentionally OpenAI-compatible. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional | OpenAI backup provider and model override. Default model is `gpt-4o-mini`; confirm model access with the OpenAI account before relying on failover. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`; `GROQ_API_KEY`, `GROQ_MODEL`; `GEMINI_API_KEY`, `GEMINI_MODEL` | Optional | Additional configured LLM backups. |
| `MANDI_API_KEY`, `MANDI_RESOURCE_ID`, `MANDI_CACHE` | Optional | Agmarknet access and cache location. `MANDI_RESOURCE_ID` has an application default; `MANDI_CACHE` defaults under `DATA_DIR`. |
| `GNANI_API_KEY` | Optional | Voice recognition and synthesis. |
| `SARVAM_API_KEY` | Optional | Advisory translation. |
| `OPS_DB` | Optional | Explicit operational SQLite path; when empty, uses `DATA_DIR/ops.sqlite3`. |
| `CACHE_TTL`, `HTTP_TIMEOUT`, `ADVISE_TIMEOUT`, `LLM_CONNECT_TIMEOUT`, `LLM_READ_TIMEOUT`, `LLM_WRITE_TIMEOUT`, `LLM_POOL_TIMEOUT` | Optional | Cache and upstream request timing. |
| `RATE_LIMIT_PER_MIN`, `RATE_LIMIT_HEAVY_PER_MIN` | Optional | Per-client general and costly-route sliding-window limits. |
| `MAX_REQUEST_BODY_BYTES` | Optional | Maximum JSON request body, default 1 MiB. Audio routes retain their own upload cap. |
| `TRUST_PROXY` | Optional | Set to `1` only when requests arrive through a trusted proxy that sets `X-Forwarded-For`. |
| `ADMIN_TOKEN` | Optional | When set, protects selected grid/relief writes and farm deletion using `X-Admin-Token`. Keep it backend-only. |
| `ALLOWED_SUPPLIER_HOSTS` | Optional | Comma-separated exact hostname allow-list for supplier inventory/webhook URLs. Empty means any public hostname is allowed after address checks. |
| `OSRM_URL` | Optional | Routing provider URL; defaults to the public OSRM demo service. Use an operational service for production workloads. |
| `RELIEF_AUTOPILOT_MINUTES`, `RELIEF_MIN_LEVEL` | Optional | Relief scheduler configuration. Autopilot is off by default. |
| `APP_NAME`, `HTTP_USER_AGENT` | Optional | Service display name and provider request identity. |
| `VITE_API_BASE_URL` | Vercel | Public Render API origin, embedded into the frontend build; never a secret. |

Render's `PORT` is platform-managed; do not override it unless you also configure the service's expected port. The production container defaults to port 8000 for local use.

## Verify the deployment

Set the API origin and a location/crop you want to check:

```powershell
$ApiUrl = "https://<render-service>.onrender.com"
$Latitude = Read-Host "Farm latitude"
$Longitude = Read-Host "Farm longitude"
$Crop = Read-Host "Crop identifier"
Invoke-RestMethod "$ApiUrl/health"
Invoke-WebRequest "$ApiUrl/docs"
Invoke-RestMethod "$ApiUrl/insights/risk?lat=$Latitude&lon=$Longitude&crop=$Crop"
Invoke-RestMethod "$ApiUrl/voice/capabilities"
```

The risk request calls upstream data providers. For voice, test recording and playback from the deployed UI after setting `GNANI_API_KEY`; API capabilities alone do not prove that the configured provider credentials work.

## Persistence, cold starts, and operations

- Render free instances do not have persistent disks and may sleep or use ephemeral storage. Use a paid service with a persistent disk for farm profiles, operational records, SQLite cache, and mandi cache to survive replacement/restarts.
- Local production Compose stores these files in the named `backend-data` volume. Preserve that volume when updating containers.
- SQLite is suitable for the single-instance deployment target here. Do not scale this service to multiple instances/workers without moving state to shared managed storage and coordinating rate limits.
- The project uses live external providers. Cold start, upstream quotas, provider outages, and public OSRM limits can delay or degrade responses.

## Security boundaries

- Supplier URLs are checked at registration and again before each fetch. Only HTTP(S) is accepted; private, loopback, link-local, reserved, and metadata destinations are rejected. Redirects are disabled, the connection has a timeout, response bodies are capped at 1 MiB, and `ALLOWED_SUPPLIER_HOSTS` can narrow destinations. The address is validated before HTTPX resolves/connects; this is not DNS pinning and cannot fully prevent a hostile DNS rebinding race. Prefer an allow-list for deployments that use supplier endpoints.
- The in-process sliding-window limiter returns `429` and `Retry-After`, with stricter limits for voice and costly advisory/relief routes. It resets on restart and does not coordinate across instances; it is not a replacement for a WAF, edge limiter, or account-level quotas.
- `TRUST_PROXY=1` trusts the first `X-Forwarded-For` value. Enable it only when direct client access is blocked and the trusted reverse proxy overwrites/normalizes that header.
- `ADMIN_TOKEN` only protects the requested selected write operations. It is not general authentication, authorization, user isolation, or protection for every mutating API route. Do not expose the API as a multi-user service without adding complete auth and access controls.
- CORS and admin tokens are not API authentication. Use HTTPS and keep all provider keys on the backend.

## Rollback

1. In Render, select the last known-good deployment from the deployment history and redeploy it. Keep the persistent disk attached; do not delete the disk when rolling back application code.
2. In Vercel, promote the last known-good production deployment.
3. If a rollback follows an environment change, restore the previous environment values and redeploy the affected service. Check `/health`, CORS, and one advisory flow before reopening the demo.

## Pre-demo checklist

- [ ] Render deployment is healthy at `/health`, and `/docs` loads.
- [ ] `CORS_ORIGINS` contains the exact Vercel origin; no wildcard is configured.
- [ ] Vercel has the correct `VITE_API_BASE_URL` and was rebuilt after it was set.
- [ ] The chosen LLM model is enabled for its API account; optional LLM failover has the intended key/model configured.
- [ ] Required `MANDI_API_KEY`, `GNANI_API_KEY`, and `SARVAM_API_KEY` are configured for the features being demonstrated.
- [ ] Render's persistent disk is mounted at the same path configured by `DATA_DIR`.
- [ ] `ADMIN_TOKEN` is configured if protected write endpoints are being used; it is not present in the frontend.
- [ ] Supplier host allow-list is configured when live supplier endpoints are enabled.
- [ ] Test a risk lookup using the intended location and check external provider availability.
- [ ] Test voice capabilities plus one real microphone/speech playback flow on the target device.
- [ ] Confirm an application rollback is available and the persistent volume will be retained.
