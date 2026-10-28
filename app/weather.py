"""Four-point Garching forecast for the 64x16 board; imports never touch SPI."""

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from http.client import HTTPException
import json
import math
import os
import threading
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw
from luma.core.legacy import text, textsize
from luma.core.legacy.font import LCD_FONT, SEG7_FONT, proportional

from matrix_text import panel_duration, render_lines


PAGE_SECONDS = 6.0
OVERVIEW_SECONDS = 16.0
OVERVIEW_HOURS = (8, 12, 16, 20)
REFRESH_SECONDS = 600
RETRY_SECONDS = 60
STALE_SECONDS = 1200
EXPIRE_SECONDS = 7200
MAX_RESPONSE_BYTES = 256 * 1024
_FONT = proportional(LCD_FONT)
_NUMERIC_BITMAPS = list(SEG7_FONT)
# SEG7 has no minus sign. Keep negative temperatures explicit and readable.
_NUMERIC_BITMAPS[ord("-")] = [0x10, 0x10, 0x10, 0]
_NUMERIC_FONT = proportional(_NUMERIC_BITMAPS)


@dataclass(frozen=True)
class Hour:
    timestamp: float
    temperature: float | None
    probability: float | None
    precipitation: float | None


@dataclass(frozen=True)
class Day:
    date: str
    high: float | None
    low: float | None
    probability: float | None
    precipitation: float | None


@dataclass(frozen=True)
class Forecast:
    current_at: float | None
    temperature: float | None
    apparent: float | None
    condition: float | None
    wind: float | None
    hours: tuple[Hour, ...]
    days: tuple[Day, ...]


def _number(value, low=-1000, high=1000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not low <= value <= high or not math.isfinite(value):
        return None
    return float(value)


def _timestamp(value):
    # Bound timestamps before datetime conversion.
    return _number(value, 0, 4102444800)


def _at(section, key, index):
    values = section.get(key)
    return values[index] if isinstance(values, list) and index < len(values) else None


def parse_forecast(data, tz=None):
    """Keep missing provider values missing instead of turning them into dry weather."""
    tz = tz or ZoneInfo("Europe/Berlin")
    if not isinstance(data, dict) or data.get("error"):
        raise ValueError("Weather service returned an error")
    sections = [data.get(key, {}) for key in ("current", "hourly", "daily")]
    if any(not isinstance(section, dict) for section in sections):
        raise ValueError("Invalid weather response sections")
    current, hourly, daily = sections
    hours = []
    times = hourly.get("time", [])
    if not isinstance(times, list) or len(times) > 100:
        raise ValueError("Invalid hourly weather times")
    for index, value in enumerate(times):
        stamp = _timestamp(value)
        if stamp is not None:
            hours.append(Hour(stamp,
                              _number(_at(hourly, "temperature_2m", index), -100, 70),
                              _number(_at(hourly, "precipitation_probability", index), 0, 100),
                              _number(_at(hourly, "precipitation", index), 0, 1000)))
    days = []
    times = daily.get("time", [])
    if not isinstance(times, list) or len(times) > 16:
        raise ValueError("Invalid daily weather times")
    for index, value in enumerate(times):
        stamp = _timestamp(value)
        if stamp is not None:
            date = datetime.fromtimestamp(stamp, tz).date().isoformat()
            days.append(Day(date,
                            _number(_at(daily, "temperature_2m_max", index), -100, 70),
                            _number(_at(daily, "temperature_2m_min", index), -100, 70),
                            _number(_at(daily, "precipitation_probability_max", index), 0, 100),
                            _number(_at(daily, "precipitation_sum", index), 0, 1000)))
    current_at = _timestamp(current.get("time"))
    if current_at is None:
        current = {}
    forecast = Forecast(current_at,
                        _number(current.get("temperature_2m"), -100, 70),
                        _number(current.get("apparent_temperature"), -120, 80),
                        _number(current.get("weather_code"), 0, 99),
                        _number(current.get("wind_speed_10m"), 0, 500),
                        tuple(sorted(hours, key=lambda hour: hour.timestamp)), tuple(days))
    if (forecast.temperature is None
            and not any(hour.temperature is not None for hour in hours)
            and not any(day.high is not None or day.low is not None for day in days)):
        raise ValueError("Weather response contains no usable forecast")
    return forecast


def coordinates():
    values = []
    for name, default, bound in (("LATITUDE", "48.25", 90), ("LONGITUDE", "11.65", 180)):
        try:
            value = float(os.environ.get("GARCHING_WEATHER_" + name, default))
        except ValueError as error:
            raise ValueError("Invalid weather " + name.lower()) from error
        if not math.isfinite(value) or not -bound <= value <= bound:
            raise ValueError("Invalid weather " + name.lower())
        values.append(value)
    return tuple(values)


def fetch_forecast(tz=None):
    latitude, longitude = coordinates()
    query = urlencode({
        "latitude": latitude, "longitude": longitude,
        "timezone": "Europe/Berlin", "timeformat": "unixtime", "forecast_days": 2,
        "temperature_unit": "celsius", "wind_speed_unit": "kmh", "precipitation_unit": "mm",
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "hourly": "temperature_2m,precipitation_probability,precipitation",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
    })
    with urlopen("https://api.open-meteo.com/v1/forecast?" + query, timeout=8) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Weather response is too large")
    return parse_forecast(json.loads(body), tz)


def _temperature(celsius):
    return "--" if celsius is None else str(round(celsius))


def condition_label(code):
    if code is None:
        return "CONDITION --"
    if code == 0:
        return "CLEAR"
    if code in (1, 2):
        return "PARTLY CLOUDY"
    if code == 3:
        return "CLOUDY"
    if code in (45, 48):
        return "FOG"
    if code in (51, 53, 55):
        return "DRIZZLE"
    if code in (56, 57, 66, 67):
        return "FREEZING RAIN"
    if code in (61, 63, 65):
        return "RAIN"
    if code in (71, 73, 75, 77, 85, 86):
        return "SNOW"
    if code in (80, 81, 82):
        return "SHOWERS"
    if code in (95, 96, 97, 99):
        return "THUNDERSTORM"
    return "CONDITION --"


def _probability(value):
    return "--%" if value is None else f"{value:.0f}%"


def _amount(value):
    return "--MM" if value is None else f"{value:.1f}MM"


def overview_points(forecast, now, tz):
    """Keep the same four points for today's date, including hours already past."""
    today = datetime.fromtimestamp(now, tz).date()
    by_hour = {}
    for hour in forecast.hours:
        local = datetime.fromtimestamp(hour.timestamp, tz)
        if local.date() == today and local.minute == 0:
            by_hour[local.hour] = hour
    return tuple((hour, by_hour.get(hour)) for hour in OVERVIEW_HOURS)


@lru_cache(maxsize=8)
def render_overview(points):
    """Four columns with 7px hour labels above 7px Celsius temperatures."""
    image = Image.new("1", (64, 16), 0)
    draw = ImageDraw.Draw(image)
    for index, (hour, forecast) in enumerate(points):
        left = index * 16
        temperature = _temperature(forecast.temperature if forecast else None) + "C"
        width, _ = textsize(f"{hour:02d}", _FONT)
        text(draw, (left + (16 - width) // 2, 0), f"{hour:02d}", fill="white", font=_FONT)
        width, _ = textsize(temperature, _NUMERIC_FONT)
        strip = Image.new("1", (width, 8), 0)
        text(ImageDraw.Draw(strip), (0, 0), temperature, fill="white", font=_NUMERIC_FONT)
        if width > 16:
            # Preserve the sign and unit even for an extreme three-digit reading.
            strip = strip.resize((16, 8), Image.Resampling.NEAREST)
            width = 16
        image.paste(strip, (left + (16 - width) // 2, 8))
    return image


def forecast_pages(forecast, now, tz):
    """Label each reading explicitly instead of packing abbreviations together."""
    today = datetime.fromtimestamp(now, tz).date().isoformat()
    day = next((day for day in forecast.days if day.date == today), None)
    high = _temperature(day.high if day else None)
    low = _temperature(day.low if day else None)
    rain = (_probability(day.probability if day else None)
            + " " + _amount(day.precipitation if day else None))
    wind = "--" if forecast.wind is None else str(round(forecast.wind))
    pages = [(f"NOW {_temperature(forecast.temperature)}C", condition_label(forecast.condition)),
             (f"HIGH {high}C", f"LOW {low}C"),
             ("RAIN TODAY", rain),
             (f"FEELS {_temperature(forecast.apparent)}C", f"WIND {wind}KM/H")]
    for hour, point in overview_points(forecast, now, tz):
        chance = _probability(point.probability if point else None)
        amount = _amount(point.precipitation if point else None)
        pages.append((f"RAIN {hour:02d}H", chance + " " + amount))
    return pages


class Weather:
    def __init__(self, fetcher=None, *, tz=None, clock=time.time, start_worker=True):
        self.tz = tz or ZoneInfo("Europe/Berlin")
        self.clock = clock
        self.fetcher = fetcher or (lambda: fetch_forecast(self.tz))
        self.forecast = None
        self.updated_at = None
        self.failed = False
        self.lock = threading.Lock()
        if start_worker:
            # A slow or failed network request must never stall the display loop.
            threading.Thread(target=self._refresh_loop, daemon=True, name="weather-fetch").start()

    def refresh(self):
        try:
            forecast = self.fetcher()
            if not isinstance(forecast, Forecast):
                raise ValueError("Invalid forecast")
        except (OSError, HTTPException, ValueError, TypeError, KeyError) as error:
            print(f"Weather update failed: {error}", flush=True)
            with self.lock:
                self.failed = True
            return False
        with self.lock:
            self.forecast = forecast
            self.updated_at = self.clock()
            self.failed = False
        return True

    def _refresh_loop(self):
        while True:
            time.sleep(REFRESH_SECONDS if self.refresh() else RETRY_SECONDS)

    def _state(self):
        now = self.clock()
        with self.lock:
            forecast, updated, failed = self.forecast, self.updated_at, self.failed
        if forecast is None:
            return None, now, ("WEATHER", "UNAVAILABLE" if failed else "LOADING")
        age = max(0, now - updated,
                  now - forecast.current_at if forecast.current_at is not None else 0)
        if age >= EXPIRE_SECONDS:
            return None, now, ("WEATHER", "UNAVAILABLE")
        if failed or age >= STALE_SECONDS:
            return None, now, ("WEATHER OLD", "RETRYING")
        return forecast, now, None

    def pages(self):
        forecast, now, status = self._state()
        return [status] if status else forecast_pages(forecast, now, self.tz)

    def render(self, elapsed, delta):
        forecast, now, status = self._state()
        if status:
            return render_lines(status, elapsed, font=_FONT)
        pages = forecast_pages(forecast, now, self.tz)
        durations = [panel_duration(page, font=_FONT, minimum=PAGE_SECONDS) for page in pages]
        remaining = max(0.0, elapsed) % (OVERVIEW_SECONDS + sum(durations))
        if remaining < OVERVIEW_SECONDS:
            return render_overview(overview_points(forecast, now, self.tz))
        remaining -= OVERVIEW_SECONDS
        for page, duration in zip(pages, durations):
            if remaining < duration:
                return render_lines(page, remaining, font=_FONT)
            remaining -= duration
        return render_lines(pages[-1], 0.0, font=_FONT)


def main():
    from effect_runner import run
    run(Weather())


if __name__ == "__main__":
    main()
