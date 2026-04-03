# API-4: Ensemble Weather Models — Wire ECMWF + GFS Into weather_trader.py

## The Problem

The weather trading strategy is the bot's top performer (57% of exposure, 30–100%+ returns) and currently uses two data sources: METAR for current conditions (`metar_client.py`) and NOAA for forecasts (`noaa_client.py`). These are real, working clients. Adding ECMWF and GFS ensemble data would allow the bot to price temperature bracket markets with much tighter confidence intervals — if four independent models agree within 2°F, that is an edge worth pressing. The clients for ECMWF and GFS do not yet exist. `weather_trader.py` needs an ensemble aggregation layer that takes all four model outputs and produces a confidence-weighted position size.

## Context Files to Read First

- `polymarket-bot/src/metar_client.py` (understand the data format it returns — particularly the temperature field name and units)
- `polymarket-bot/src/noaa_client.py` (understand its forecast format — how temperatures are structured, what time horizons it covers)
- `polymarket-bot/strategies/weather_trader.py` (the full strategy — understand how it currently calls metar_client and noaa_client, how it sizes positions, what its bet selection logic looks like)
- `polymarket-bot/src/client.py` (PolymarketClient — for understanding how the strategy places trades)
- `polymarket-bot/knowledge/strategies/weather_edges.md` (if it exists — edge documentation)

## Prompt

Read the existing code first — understand the data formats that metar_client.py and noaa_client.py return, and how weather_trader.py currently consumes them. The new ensemble clients must return data in the same format so weather_trader.py can treat all four sources uniformly.

### 1. Understand Existing Data Formats

Before writing any new code, read metar_client.py and noaa_client.py and document the exact return format of their main methods:

```python
# Example — confirm the actual field names by reading the files
metar_data = await metar_client.get_conditions("KORD")
# → {"temp_f": 72.4, "humidity": 65, "wind_mph": 12, "station": "KORD", "timestamp": ...}

noaa_data = await noaa_client.get_forecast("Chicago", hours_ahead=6)
# → {"temp_f": 74.0, "temp_f_min": 71.0, "temp_f_max": 76.0, "period": "tonight", ...}
```

The two new clients must return dicts with at minimum: `temp_f`, `temp_f_min`, `temp_f_max`, `source`, `timestamp`, `city`. Add whatever fields the existing clients already return so all four are interchangeable in the ensemble logic.

### 2. Create polymarket-bot/src/ecmwf_client.py

Use the Open-Meteo free API for ECMWF data (no API key needed):

```
https://api.open-meteo.com/v1/ecmwf?latitude={lat}&longitude={lon}&hourly=temperature_2m&forecast_days=3&timezone=auto
```

```python
class ECMWFClient:
    BASE_URL = "https://api.open-meteo.com/v1/ecmwf"
    
    CITY_COORDS = {
        # Build from the cities active in weather_trader.py — read that file for the city list
        "Chicago": (41.878, -87.630),
        "New York": (40.712, -74.006),
        "Los Angeles": (34.052, -118.244),
        # Add all cities weather_trader.py already trades
    }
    
    async def get_forecast(self, city: str, target_hour: int = 6) -> dict:
        """
        Fetch ECMWF forecast for city at target_hour hours from now.
        Returns same format as noaa_client.get_forecast().
        """
```

- Use `httpx` or `aiohttp` (whichever is already in requirements.txt — check before adding a new dependency)
- Convert Celsius to Fahrenheit: `temp_f = (temp_c * 9/5) + 32`
- The API returns hourly arrays — find the entry closest to `target_hour` hours from now
- Return `{"temp_f": float, "temp_f_min": float, "temp_f_max": float, "source": "ecmwf", "city": city, "timestamp": float}`
- Cache responses in Redis for 30 minutes (`weather:ecmwf:{city}:{hour}`) to avoid hammering the API

### 3. Create polymarket-bot/src/gfs_client.py

Use the Open-Meteo GFS endpoint (also free, no API key):

```
https://api.open-meteo.com/v1/gfs?latitude={lat}&longitude={lon}&hourly=temperature_2m&models=gfs_seamless&forecast_days=3&timezone=auto
```

```python
class GFSClient:
    BASE_URL = "https://api.open-meteo.com/v1/gfs"
    
    async def get_forecast(self, city: str, target_hour: int = 6) -> dict:
        """
        Fetch GFS ensemble forecast for city.
        GFS seamless model includes ensemble spread — use temperature_2m_mean and temperature_2m_spread if available.
        Returns same format as ECMWFClient.get_forecast().
        """
```

- Use the same `CITY_COORDS` dict — import it from `ecmwf_client.py` so it is defined in one place
- If the API returns ensemble spread (`temperature_2m_p10`, `temperature_2m_p90`), compute `temp_f_min` and `temp_f_max` from the 10th/90th percentiles
- Otherwise compute min/max as ±(spread/2) around the mean
- Cache in Redis: `weather:gfs:{city}:{hour}` for 30 minutes

### 4. Build Ensemble Logic in weather_trader.py

Add a new method `get_ensemble_forecast(city: str, target_hour: int)` to `WeatherTrader` (or whatever the class name is — read the file):

```python
async def get_ensemble_forecast(self, city: str, target_hour: int = 6) -> EnsembleForecast:
    """
    Fetch from all 4 sources concurrently, compute agreement, return confidence-scored forecast.
    """
    results = await asyncio.gather(
        self.metar_client.get_conditions(...),   # current conditions
        self.noaa_client.get_forecast(city, target_hour),
        self.ecmwf_client.get_forecast(city, target_hour),
        self.gfs_client.get_forecast(city, target_hour),
        return_exceptions=True
    )
    
    # Filter out failures (network errors, missing cities) — work with whatever succeeded
    valid = [r for r in results if not isinstance(r, Exception)]
    
    return self._compute_ensemble(valid)
```

```python
def _compute_ensemble(self, forecasts: list[dict]) -> EnsembleForecast:
    temps = [f["temp_f"] for f in forecasts]
    spread = max(temps) - min(temps)
    mean_temp = sum(temps) / len(temps)
    
    if len(forecasts) == 4 and spread <= 2.0:
        confidence = 0.95
    elif len(forecasts) >= 3 and spread <= 2.0:
        confidence = 0.75
    elif len(forecasts) >= 2 and spread <= 3.0:
        confidence = 0.50
    else:
        confidence = 0.25  # too much disagreement or too few sources
    
    return EnsembleForecast(
        city=forecasts[0]["city"],
        mean_temp_f=mean_temp,
        spread_f=spread,
        confidence=confidence,
        sources_available=len(forecasts),
        sources_agreeing=sum(1 for t in temps if abs(t - mean_temp) <= 1.5),
        raw_forecasts=forecasts,
    )
```

Add a `EnsembleForecast` dataclass at the top of the file (or in a separate `weather_types.py` if there are already dataclasses defined somewhere).

### 5. Wire Ensemble Confidence Into Position Sizing

In the existing position sizing logic within `weather_trader.py`:

- Find where the current bet size is calculated (likely calls Kelly sizer or uses a fixed fraction)
- Multiply the base position size by the ensemble confidence:

```python
ensemble = await self.get_ensemble_forecast(city, target_hour)

if ensemble.confidence < 0.50:
    logger.info(f"Skipping {city} — ensemble confidence too low ({ensemble.confidence:.0%}, spread {ensemble.spread_f:.1f}°F)")
    return None  # do not trade

# Scale position size by confidence
base_size = self._calculate_base_size(market, edge)
position_size = base_size * ensemble.confidence

logger.info(
    f"Ensemble {city}: {ensemble.sources_available}/4 sources, "
    f"mean={ensemble.mean_temp_f:.1f}°F, spread={ensemble.spread_f:.1f}°F, "
    f"confidence={ensemble.confidence:.0%}, size={position_size:.2f} USDC"
)
```

- Do not change the base sizing logic — only apply the ensemble multiplier on top
- If all four sources fail to respond, fall back to the existing two-source logic (METAR + NOAA) with no confidence multiplier

### 6. Test With a Current Market

Add a quick test at the bottom of `gfs_client.py` and `ecmwf_client.py`:

```python
if __name__ == "__main__":
    import asyncio
    client = ECMWFClient()  # or GFSClient
    result = asyncio.run(client.get_forecast("Chicago", target_hour=6))
    print(result)
```

Run both:
```bash
python polymarket-bot/src/ecmwf_client.py
python polymarket-bot/src/gfs_client.py
```

Both should print a forecast dict with a real temperature (not 0.0, not None). Then run the full weather trader in paper mode to confirm the ensemble logic fires without errors.
