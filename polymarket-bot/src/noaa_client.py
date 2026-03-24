"""Dedicated NOAA weather data client — pulls from api.weather.gov every 5 minutes.

Supports 7 tracked stations (KNYC, KORD, KLAX, KDEN, KJFK, KATL, KMIA) with
parallel fetches for current observations, forecast highs/lows, and hourly forecasts.

Optional Visual Crossing API fallback when VISUAL_CROSSING_API_KEY is set.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

NOAA_API_BASE = "https://api.weather.gov"
NOAA_HEADERS = {
    "User-Agent": "(polymarket-weather-bot, contact@example.com)",
    "Accept": "application/geo+json",
}

VISUAL_CROSSING_BASE = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"

# Station metadata for the 7 Kalshi-tracked cities
KALSHI_STATIONS: dict[str, dict[str, Any]] = {
    "KNYC": {"lat": 40.7789, "lon": -73.9692, "city": "New York", "nws_station": "KNYC"},
    "KORD": {"lat": 41.9742, "lon": -87.9073, "city": "Chicago", "nws_station": "KORD"},
    "KLAX": {"lat": 33.9425, "lon": -118.4081, "city": "Los Angeles", "nws_station": "KLAX"},
    "KDEN": {"lat": 39.8561, "lon": -104.6737, "city": "Denver", "nws_station": "KDEN"},
    "KJFK": {"lat": 40.6413, "lon": -73.7781, "city": "JFK/New York", "nws_station": "KJFK"},
    "KATL": {"lat": 33.6407, "lon": -84.4277, "city": "Atlanta", "nws_station": "KATL"},
    "KMIA": {"lat": 25.7959, "lon": -80.2870, "city": "Miami", "nws_station": "KMIA"},
}


class NOAAClient:
    """Async NOAA weather data client with parallel station fetching.

    Primary: NWS API (api.weather.gov) — free, no key needed.
    Secondary: Visual Crossing API — faster sub-hourly data (optional).
    """

    def __init__(
        self,
        stations: list[str] | None = None,
        visual_crossing_key: str = "",
    ) -> None:
        self._stations = stations or list(KALSHI_STATIONS.keys())
        self._vc_key = visual_crossing_key or os.environ.get("VISUAL_CROSSING_API_KEY", "")
        self._http = httpx.AsyncClient(timeout=30.0, headers=NOAA_HEADERS)
        self._vc_http = httpx.AsyncClient(timeout=20.0) if self._vc_key else None

        # Caches
        self._grid_cache: dict[str, dict[str, Any]] = {}  # station -> grid info
        self._obs_cache: dict[str, dict[str, Any]] = {}  # station -> latest obs
        self._forecast_cache: dict[str, dict[str, Any]] = {}  # station -> forecast
        self._hourly_cache: dict[str, list[dict[str, Any]]] = {}  # station -> hourly
        self._last_fetch: float = 0.0
        self._initialized = False

    async def initialize(self) -> None:
        """Resolve all station grid points for forecast lookups."""
        if self._initialized:
            return
        await self._resolve_all_grids()
        self._initialized = True

    async def close(self) -> None:
        """Close HTTP clients."""
        if not self._http.is_closed:
            await self._http.aclose()
        if self._vc_http and not self._vc_http.is_closed:
            await self._vc_http.aclose()

    # ── Public API ────────────────────────────────────────────────────────

    async def get_current_temp(self, station: str) -> dict[str, Any] | None:
        """Get latest temperature observation for a station.

        Returns: {"station": "KNYC", "temp_f": 72.1, "observed_at": "...", "source": "nws"}
        """
        try:
            url = f"{NOAA_API_BASE}/stations/{station}/observations/latest"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                logger.warning("noaa_obs_failed", station=station, status=resp.status_code)
                return await self._vc_fallback_current(station)

            data = resp.json()
            props = data.get("properties", {})
            temp_c = props.get("temperature", {}).get("value")

            if temp_c is None:
                return await self._vc_fallback_current(station)

            temp_f = temp_c * 9 / 5 + 32

            return {
                "station": station,
                "temp_f": round(temp_f, 1),
                "observed_at": props.get("timestamp", ""),
                "description": props.get("textDescription", ""),
                "wind_speed_mph": _ms_to_mph(props.get("windSpeed", {}).get("value")),
                "humidity_pct": props.get("relativeHumidity", {}).get("value"),
                "source": "nws",
            }

        except Exception as exc:
            logger.error("noaa_obs_error", station=station, error=str(exc))
            return await self._vc_fallback_current(station)

    async def get_forecast_high(self, station: str) -> dict[str, Any] | None:
        """Get forecast high/low temperature for today.

        Returns: {"station": "KNYC", "forecast_high_f": 75, "forecast_low_f": 58, "updated_at": "..."}
        """
        grid = self._grid_cache.get(station)
        if not grid:
            return None

        try:
            url = f"{NOAA_API_BASE}/gridpoints/{grid['office']}/{grid['gridX']},{grid['gridY']}/forecast"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                logger.warning("noaa_forecast_failed", station=station, status=resp.status_code)
                return None

            data = resp.json()
            periods = data.get("properties", {}).get("periods", [])
            updated_at = data.get("properties", {}).get("updateTime", "")

            high_f = None
            low_f = None

            for period in periods[:4]:  # Look at first 4 periods (today/tonight)
                temp = period.get("temperature")
                if temp is None:
                    continue
                if period.get("isDaytime", False):
                    high_f = float(temp)
                else:
                    low_f = float(temp)

            if high_f is None and periods:
                high_f = float(periods[0].get("temperature", 0))

            return {
                "station": station,
                "forecast_high_f": high_f,
                "forecast_low_f": low_f,
                "updated_at": updated_at,
                "periods": periods[:4],
                "source": "nws",
            }

        except Exception as exc:
            logger.error("noaa_forecast_error", station=station, error=str(exc))
            return None

    async def get_forecast_hourly(self, station: str, hours: int = 24) -> list[dict[str, Any]]:
        """Get hourly forecast for next N hours.

        Returns list of {"hour": "...", "temp_f": 72, "precip_pct": 10, "wind_mph": 8}
        """
        grid = self._grid_cache.get(station)
        if not grid:
            return []

        try:
            url = f"{NOAA_API_BASE}/gridpoints/{grid['office']}/{grid['gridX']},{grid['gridY']}/forecast/hourly"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return []

            data = resp.json()
            periods = data.get("properties", {}).get("periods", [])

            result = []
            for period in periods[:hours]:
                temp = period.get("temperature")
                if temp is None:
                    continue
                result.append({
                    "hour": period.get("startTime", ""),
                    "temp_f": float(temp),
                    "precip_pct": period.get("probabilityOfPrecipitation", {}).get("value", 0) or 0,
                    "wind_mph": _parse_wind_speed(period.get("windSpeed", "")),
                    "short_forecast": period.get("shortForecast", ""),
                })

            return result

        except Exception as exc:
            logger.error("noaa_hourly_error", station=station, error=str(exc))
            return []

    async def get_all_stations(self) -> dict[str, dict[str, Any]]:
        """Get current observations + forecasts for all tracked stations in parallel.

        Returns dict keyed by station ID with current temp, forecast high/low, and hourly.
        """
        if not self._initialized:
            await self.initialize()

        async def _fetch_station(station: str) -> tuple[str, dict[str, Any]]:
            current, forecast, hourly = await asyncio.gather(
                self.get_current_temp(station),
                self.get_forecast_high(station),
                self.get_forecast_hourly(station, hours=24),
                return_exceptions=True,
            )

            # Handle exceptions from gather
            if isinstance(current, Exception):
                logger.error("station_current_error", station=station, error=str(current))
                current = None
            if isinstance(forecast, Exception):
                logger.error("station_forecast_error", station=station, error=str(forecast))
                forecast = None
            if isinstance(hourly, Exception):
                logger.error("station_hourly_error", station=station, error=str(hourly))
                hourly = []

            meta = KALSHI_STATIONS.get(station, {})

            result = {
                "station": station,
                "city": meta.get("city", ""),
                "current": current,
                "forecast": forecast,
                "hourly": hourly,
                "fetched_at": time.time(),
            }

            # Update caches
            if current:
                self._obs_cache[station] = current
            if forecast:
                self._forecast_cache[station] = forecast
            if hourly:
                self._hourly_cache[station] = hourly

            return station, result

        tasks = [_fetch_station(s) for s in self._stations]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output: dict[str, dict[str, Any]] = {}
        for item in results:
            if isinstance(item, Exception):
                logger.error("station_fetch_error", error=str(item))
                continue
            station_id, station_data = item
            output[station_id] = station_data

        self._last_fetch = time.time()

        logger.info(
            "noaa_all_stations_fetched",
            stations=len(output),
            total_configured=len(self._stations),
        )

        return output

    # ── Cached accessors ──────────────────────────────────────────────────

    def get_cached_temp(self, station: str) -> float | None:
        """Get the most recent cached temperature for a station."""
        obs = self._obs_cache.get(station)
        return obs.get("temp_f") if obs else None

    def get_cached_forecast(self, station: str) -> dict[str, Any] | None:
        """Get the most recent cached forecast for a station."""
        return self._forecast_cache.get(station)

    def get_cached_hourly(self, station: str) -> list[dict[str, Any]]:
        """Get the most recent cached hourly forecast for a station."""
        return self._hourly_cache.get(station, [])

    @property
    def last_fetch_time(self) -> float:
        return self._last_fetch

    @property
    def stations(self) -> list[str]:
        return list(self._stations)

    # ── Grid resolution ───────────────────────────────────────────────────

    async def _resolve_all_grids(self) -> None:
        """Resolve all stations to NWS grid points in parallel."""
        tasks = [self._resolve_grid(s) for s in self._stations]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info(
            "noaa_grids_resolved",
            resolved=len(self._grid_cache),
            total=len(self._stations),
        )

    async def _resolve_grid(self, station: str) -> None:
        """Resolve a single station to its NWS grid point."""
        meta = KALSHI_STATIONS.get(station)
        if not meta:
            logger.warning("noaa_unknown_station", station=station)
            return

        try:
            # Get grid coordinates from lat/lon
            lat, lon = meta["lat"], meta["lon"]
            resp = await self._http.get(f"{NOAA_API_BASE}/points/{lat},{lon}")
            if resp.status_code != 200:
                logger.warning("noaa_points_failed", station=station, status=resp.status_code)
                return

            data = resp.json()
            props = data.get("properties", {})

            self._grid_cache[station] = {
                "office": props.get("gridId", ""),
                "gridX": props.get("gridX", 0),
                "gridY": props.get("gridY", 0),
                "forecast_url": props.get("forecast", ""),
                "hourly_url": props.get("forecastHourly", ""),
                "city": props.get("relativeLocation", {}).get("properties", {}).get("city", ""),
                "state": props.get("relativeLocation", {}).get("properties", {}).get("state", ""),
            }

            logger.debug(
                "noaa_grid_resolved",
                station=station,
                office=self._grid_cache[station]["office"],
                city=self._grid_cache[station]["city"],
            )

        except Exception as exc:
            logger.error("noaa_grid_resolve_error", station=station, error=str(exc))

    # ── Visual Crossing fallback ──────────────────────────────────────────

    async def _vc_fallback_current(self, station: str) -> dict[str, Any] | None:
        """Fetch current conditions from Visual Crossing as fallback."""
        if not self._vc_key or not self._vc_http:
            return None

        meta = KALSHI_STATIONS.get(station)
        if not meta:
            return None

        try:
            location = f"{meta['lat']},{meta['lon']}"
            url = f"{VISUAL_CROSSING_BASE}/{location}?unitGroup=us&key={self._vc_key}&include=current"
            resp = await self._vc_http.get(url)
            if resp.status_code != 200:
                return None

            data = resp.json()
            current = data.get("currentConditions", {})
            temp_f = current.get("temp")
            if temp_f is None:
                return None

            return {
                "station": station,
                "temp_f": round(float(temp_f), 1),
                "observed_at": current.get("datetime", ""),
                "description": current.get("conditions", ""),
                "wind_speed_mph": current.get("windspeed"),
                "humidity_pct": current.get("humidity"),
                "source": "visual_crossing",
            }

        except Exception as exc:
            logger.error("vc_fallback_error", station=station, error=str(exc))
            return None


# ── Utility functions ─────────────────────────────────────────────────────

def _ms_to_mph(ms: float | None) -> float | None:
    """Convert m/s to mph."""
    if ms is None:
        return None
    return round(ms * 2.237, 1)


def _parse_wind_speed(wind_str: str) -> float:
    """Parse wind speed from NWS string like '10 mph' or '5 to 10 mph'."""
    import re

    if not wind_str:
        return 0.0
    nums = re.findall(r"(\d+)", wind_str)
    if not nums:
        return 0.0
    # Return the average if range, otherwise the single value
    values = [float(n) for n in nums]
    return round(sum(values) / len(values), 1)
