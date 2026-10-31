# Integration (about 10 lines of changes in your existing files)

Copy the folders into your project keeping the same relative paths:
`backend/app/services/*`, `backend/app/routers/insights.py`, `backend/tests/test_new_modules.py`,
`frontend/src/api/insights.js`, `frontend/src/insights.css`, `frontend/src/components/*`.

## 1. Backend
```bash
cd backend
pip install -r requirements-additions.txt      # rasterio, numpy, pytest
# merge .env.additions into your .env and fill the keys
python -m pytest tests/test_new_modules.py -q   # should print 11 passed
```
In `backend/app/main.py`:
```python
from app.routers.insights import router as insights_router
app.include_router(insights_router)
```
New endpoints: `GET /insights/risk`, `GET /insights/grid`, `GET /satellite/ndvi`, `POST /advise/v2`.
Your existing routes stay untouched. `/advise/v2` is the Gemini-429 fix: switch the frontend to it, or in
`agent/graph.py` replace the body of `_call_llm` with `llm_router.generate(prompt, system)`.

## 2. Frontend
In your main dashboard component:
```jsx
import FarmMap from "./components/FarmMap";
import RiskEvidence from "./components/RiskEvidence";
import NdviPanel from "./components/NdviPanel";
import AdvisoryV2 from "./components/AdvisoryV2";
import { adviseV2, getGrid } from "./api/insights";
// <FarmMap lat={lat} lon={lon} onSelect={(a,b)=>{setLat(a);setLon(b)}} cells={grid?.cells} cellKm={grid?.cell_km} />
// const res = await adviseV2({ lat, lon, crop, stage, soil_type, state, language })
// <AdvisoryV2 result={res} />  <RiskEvidence risks={res?.assessment.risks} sources={res?.assessment.sources} />  <NdviPanel lat={lat} lon={lon} />
```
Use farm-profile fields for `crop` (lowercase id: rice, wheat, maize, cotton, soybean, groundnut, mustard, potato, tomato,
sugarcane, chickpea), `stage`, `soil_type` and `state`. Persist `res.alerts` with your alerts table, skipping any whose
`dedupe_key` already exists (`alert_engine.only_new`). Save `res.assessment.actions_v2` into your field-actions table.
