# API-4: Ensemble Weather Model Edge

## Context Files to Read First
- polymarket-bot/ideas.txt (EnsembleForecastEdge entry)
- polymarket-bot/strategies/weather_trader.py
- polymarket-bot/src/noaa_client.py
- polymarket-bot/src/metar_client.py
- polymarket-bot/knowledge/strategies/weather_edges.md

## Prompt

Upgrade the weather trading strategy to use ensemble weather models for tighter bracket pricing:

1. Add new weather data sources (`polymarket-bot/src/weather_ensemble.py`):
   - **NOAA GFS** (already have via noaa_client.py) — keep as primary
   - **Open-Meteo ECMWF** — free API at `https://api.open-meteo.com/v1/ecmwf?latitude=X&longitude=Y&hourly=temperature_2m&forecast_days=3`. European model, often more accurate than GFS. No API key needed.
   - **Open-Meteo GFS Ensemble** — `https://api.open-meteo.com/v1/gfs?latitude=X&longitude=Y&hourly=temperature_2m&models=gfs_seamless&forecast_days=3`. 31-member ensemble — gives us spread/confidence.
   - Map city names to lat/lon (build a lookup for all cities active on Polymarket weather markets)

2. Ensemble scoring:
   - When all 3 models agree within ±2°F on a forecast → high confidence → sigma drops from 3.5°F to ~1.5°F
   - When models disagree by >5°F → low confidence → widen sigma to 5°F, reduce position size
   - Weight: ECMWF 40%, GFS 35%, GFS Ensemble mean 25% (ECMWF historically more accurate)

3. Integration with weather_trader.py:
   - Replace the single-model NOAA sigma with the ensemble-derived sigma
   - The CheapBracketStrategy should use ensemble consensus to pick which brackets to buy
   - If ensemble is tight (high confidence), buy fewer brackets but larger size
   - If ensemble is wide (low confidence), buy more brackets at smaller size (current behavior)

4. Caching:
   - Cache forecasts for 1 hour (weather models update every 6 hours)
   - Store historical forecast accuracy per model per city in a JSON file
   - After resolution, compare each model's forecast to actual temperature → update accuracy weights over time

5. Fallback: if Open-Meteo is down, fall back to NOAA-only with original 3.5°F sigma.

Use standard logging. Redis at redis://172.18.0.100:6379 inside Docker.
