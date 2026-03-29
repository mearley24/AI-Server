"""METAR/TAF Aviation Weather Client — Real sensor data for Polymarket temperature markets.

Aviation weather data (METAR observations + TAF forecasts) gives temperature
readings accurate to 0.1°C, updating every 1-3 hours from meteorological
stations worldwide. This data is available hours before public forecasts.

Source: aviationweather.gov (free, no API key needed)

Key edge: Polymarket weather markets for international cities (Shanghai, Seoul,
Ankara, etc.) lag behind real sensor data by 6-12 hours. METAR data is the
ground truth that these markets eventually converge to.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# aviationweather.gov METAR/TAF endpoints (free, no auth)
METAR_URL = "https://aviationweather.gov/api/data/metar"
TAF_URL = "https://aviationweather.gov/api/data/taf"

# Polymarket weather cities → nearest ICAO airport codes
# Multiple stations per city for redundancy
CITY_STATIONS: dict[str, list[str]] = {
    # Asia
    "shanghai": ["ZSPD", "ZSSS"],       # Pudong, Hongqiao
    "beijing": ["ZBAA", "ZBAD"],         # Capital, Daxing
    "tokyo": ["RJTT", "RJAA"],           # Haneda, Narita
    "seoul": ["RKSI", "RKSS"],           # Incheon, Gimpo
    "hong kong": ["VHHH"],               # Chek Lap Kok
    "shenzhen": ["ZGSZ"],
    "chengdu": ["ZUTF", "ZUUU"],         # Tianfu, Shuangliu
    "mumbai": ["VABB"],
    "delhi": ["VIDP"],
    "singapore": ["WSSS"],               # Changi
    "bangkok": ["VTBS"],                 # Suvarnabhumi
    # Europe
    "london": ["EGLL", "EGSS"],          # Heathrow, Stansted
    "paris": ["LFPG", "LFPO"],           # CDG, Orly
    "ankara": ["LTAC", "ESBA"],          # Esenboga
    "munich": ["EDDM"],
    "istanbul": ["LTFM", "LTBA"],
    "moscow": ["UUEE", "UUDD"],
    "wellington": ["NZWN"],
    # Americas
    "sao paulo": ["SBGR", "SBSP"],       # Guarulhos, Congonhas
    "buenos aires": ["SAEZ", "SABE"],    # Ezeiza, Aeroparque
    "dallas": ["KDFW", "KDAL"],          # DFW, Love Field
    "seattle": ["KSEA"],
    "toronto": ["CYYZ"],                 # Pearson
    "new york": ["KJFK", "KLGA"],
    "los angeles": ["KLAX"],
    "chicago": ["KORD"],
    "denver": ["KDEN"],
    "miami": ["KMIA"],
    # Africa / Middle East
    "johannesburg": ["FAOR"],            # OR Tambo
    "cairo": ["HECA"],
    "dubai": ["OMDB"],
}


def parse_metar_temp(metar_text: str) -> Optional[float]:
    """Extract temperature in Celsius from a METAR string.
    
    METAR format: ... T12/M01 ... (temp 12°C, dewpoint -1°C)
    Or: ... 12/M01 ... in the body
    """
    if not metar_text:
        return None
    
    # Try the standard T group: TXX/XX where M = minus
    match = re.search(r'\b(M?\d{2})/(M?\d{2})\b', metar_text)
    if match:
        temp_str = match.group(1)
        temp_c = -int(temp_str[1:]) if temp_str.startswith('M') else int(temp_str)
        return float(temp_c)
    
    return None


def parse_taf_temps(taf_text: str) -> list[dict[str, Any]]:
    """Extract forecast temperatures from a TAF string.
    
    TAF includes TX (max) and TN (min) groups:
    TX25/1218Z TN12/1306Z
    """
    temps = []
    if not taf_text:
        return temps
    
    # TX = max temp, TN = min temp
    for match in re.finditer(r'T([XN])(M?\d{2})/(\d{4})Z', taf_text):
        kind = "max" if match.group(1) == "X" else "min"
        temp_str = match.group(2)
        temp_c = -int(temp_str[1:]) if temp_str.startswith('M') else int(temp_str)
        valid_time = match.group(3)  # DDhh format
        temps.append({
            "type": kind,
            "temp_c": float(temp_c),
            "valid_time": valid_time,
        })
    
    return temps


class METARClient:
    """Async client for aviation weather data — METAR observations + TAF forecasts."""
    
    def __init__(self) -> None:
        self._http = httpx.AsyncClient(timeout=15.0)
        self._cache: dict[str, dict[str, Any]] = {}  # station -> last data
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = 300  # 5 min cache
    
    async def close(self) -> None:
        if not self._http.is_closed:
            await self._http.aclose()
    
    async def get_current_temp(self, city: str) -> Optional[dict[str, Any]]:
        """Get current temperature for a city from METAR observations.
        
        Returns dict with: temp_c, station, observed_at, raw_metar
        """
        stations = CITY_STATIONS.get(city.lower())
        if not stations:
            return None
        
        for station in stations:
            # Check cache
            if station in self._cache and time.time() - self._cache_time.get(station, 0) < self._cache_ttl:
                return self._cache[station]
            
            try:
                resp = await self._http.get(
                    METAR_URL,
                    params={"ids": station, "format": "json", "hours": 3},
                )
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                if not data:
                    continue
                
                # Get most recent observation
                latest = data[0] if isinstance(data, list) else data
                temp_c = latest.get("temp")
                if temp_c is None:
                    # Try parsing raw METAR text
                    raw = latest.get("rawOb", "")
                    temp_c = parse_metar_temp(raw)
                
                if temp_c is not None:
                    result = {
                        "temp_c": float(temp_c),
                        "temp_f": round(float(temp_c) * 9/5 + 32, 1),
                        "station": station,
                        "city": city,
                        "observed_at": latest.get("reportTime", ""),
                        "raw_metar": latest.get("rawOb", ""),
                    }
                    self._cache[station] = result
                    self._cache_time[station] = time.time()
                    return result
                    
            except Exception as exc:
                logger.debug("metar_fetch_error", station=station, error=str(exc)[:80])
                continue
        
        return None
    
    async def get_forecast_temps(self, city: str) -> list[dict[str, Any]]:
        """Get forecast high/low temperatures from TAF data.
        
        Returns list of {type: max/min, temp_c, valid_time, station}
        """
        stations = CITY_STATIONS.get(city.lower())
        if not stations:
            return []
        
        for station in stations:
            try:
                resp = await self._http.get(
                    TAF_URL,
                    params={"ids": station, "format": "json"},
                )
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                if not data:
                    continue
                
                latest = data[0] if isinstance(data, list) else data
                raw_taf = latest.get("rawTAF", latest.get("rawOb", ""))
                temps = parse_taf_temps(raw_taf)
                
                for t in temps:
                    t["station"] = station
                    t["city"] = city
                
                if temps:
                    return temps
                    
            except Exception as exc:
                logger.debug("taf_fetch_error", station=station, error=str(exc)[:80])
                continue
        
        return []
    
    async def get_all_city_temps(self) -> dict[str, dict[str, Any]]:
        """Fetch current temps for all tracked cities in parallel."""
        cities = list(CITY_STATIONS.keys())
        results = await asyncio.gather(
            *[self.get_current_temp(city) for city in cities],
            return_exceptions=True,
        )
        
        temps = {}
        for city, result in zip(cities, results):
            if isinstance(result, dict):
                temps[city] = result
        
        logger.info("metar_bulk_fetch", cities_fetched=len(temps), total=len(cities))
        return temps
    
    def find_city_in_market(self, market_question: str) -> Optional[str]:
        """Extract city name from a Polymarket weather market question.
        
        E.g., "Will the highest temperature in Shanghai be 15°C on March 27?" → "shanghai"
        """
        q_lower = market_question.lower()
        for city in CITY_STATIONS:
            if city in q_lower:
                return city
        return None
    
    def extract_target_temp(self, market_question: str) -> Optional[dict[str, Any]]:
        """Extract target temperature from market question.
        
        Returns {temp: float, unit: 'C' or 'F', type: 'exact' or 'range'}
        """
        q = market_question
        
        # "be 15°C" or "be 15 °C"
        match = re.search(r'be\s+(\d+)\s*°?\s*C', q, re.IGNORECASE)
        if match:
            return {"temp": float(match.group(1)), "unit": "C", "type": "exact"}
        
        # "be between 56-57°F"
        match = re.search(r'between\s+(\d+)\s*[-–]\s*(\d+)\s*°?\s*F', q, re.IGNORECASE)
        if match:
            return {"temp_low": float(match.group(1)), "temp_high": float(match.group(2)), "unit": "F", "type": "range"}
        
        # "be 88°F" or "be 88-89°F"
        match = re.search(r'be\s+(\d+)\s*[-–]\s*(\d+)\s*°?\s*F', q, re.IGNORECASE)
        if match:
            return {"temp_low": float(match.group(1)), "temp_high": float(match.group(2)), "unit": "F", "type": "range"}
        
        match = re.search(r'be\s+(\d+)\s*°?\s*F', q, re.IGNORECASE)
        if match:
            return {"temp": float(match.group(1)), "unit": "F", "type": "exact"}
        
        return None
    
    def evaluate_weather_edge(
        self,
        market_question: str,
        market_price: float,
        metar_temp: float,
    ) -> Optional[dict[str, Any]]:
        """Compare METAR actual temp against market question to find edge.
        
        Returns edge info if there's a tradeable discrepancy, None otherwise.
        """
        target = self.extract_target_temp(market_question)
        if not target:
            return None
        
        city = self.find_city_in_market(market_question)
        
        if target["unit"] == "C":
            actual = metar_temp
            if target["type"] == "exact":
                target_temp = target["temp"]
                diff = abs(actual - target_temp)
                # If actual is very close to target, the market should be high
                if diff <= 1.0:
                    fair_price = max(0.1, 1.0 - (diff * 0.3))  # rough estimate
                else:
                    fair_price = max(0.05, 1.0 - (diff * 0.15))
                
                edge = fair_price - market_price
                if abs(edge) > 0.05:  # 5 cent minimum edge
                    return {
                        "city": city,
                        "actual_temp_c": actual,
                        "target_temp_c": target_temp,
                        "diff_c": round(diff, 1),
                        "market_price": market_price,
                        "fair_price": round(fair_price, 2),
                        "edge": round(edge, 2),
                        "direction": "BUY" if edge > 0 else "SELL",
                        "confidence": "high" if diff <= 0.5 else "medium" if diff <= 2 else "low",
                    }
        
        elif target["unit"] == "F":
            actual_f = metar_temp * 9/5 + 32
            if target["type"] == "range":
                in_range = target["temp_low"] <= actual_f <= target["temp_high"]
                fair_price = 0.75 if in_range else 0.15
                edge = fair_price - market_price
                if abs(edge) > 0.05:
                    return {
                        "city": city,
                        "actual_temp_f": round(actual_f, 1),
                        "target_range_f": f"{target['temp_low']}-{target['temp_high']}",
                        "in_range": in_range,
                        "market_price": market_price,
                        "fair_price": round(fair_price, 2),
                        "edge": round(edge, 2),
                        "direction": "BUY" if edge > 0 else "SELL",
                        "confidence": "high" if in_range else "medium",
                    }
            elif target["type"] == "exact":
                diff = abs(actual_f - target["temp"])
                fair_price = max(0.05, 1.0 - (diff * 0.1))
                edge = fair_price - market_price
                if abs(edge) > 0.05:
                    return {
                        "city": city,
                        "actual_temp_f": round(actual_f, 1),
                        "target_temp_f": target["temp"],
                        "diff_f": round(diff, 1),
                        "market_price": market_price,
                        "fair_price": round(fair_price, 2),
                        "edge": round(edge, 2),
                        "direction": "BUY" if edge > 0 else "SELL",
                    }
        
        return None
