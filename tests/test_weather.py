from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import weather


# Fixed CET keeps desktop tests independent of Windows' optional IANA tzdata.
CET = timezone(timedelta(hours=1))
NOW = datetime(2026, 10, 25, 14, 30, tzinfo=CET).timestamp()


def response_fixture():
    midnight = datetime(2026, 10, 25, tzinfo=CET).timestamp()
    return {
        "current": {"time": NOW, "temperature_2m": 12.4,
                    "apparent_temperature": 9.2, "weather_code": 61, "wind_speed_10m": 18},
        "hourly": {"time": [midnight + hour * 3600 for hour in range(48)],
                   "temperature_2m": [10] * 48, "precipitation_probability": [65] * 48,
                   "precipitation": [0.8] * 48},
        "daily": {"time": [midnight, midnight + 86400],
                  "temperature_2m_max": [16, 18], "temperature_2m_min": [4, 5],
                  "precipitation_probability_max": [80, 20], "precipitation_sum": [3.2, 0]},
    }


class WeatherTests(unittest.TestCase):
    def test_truncated_response_is_retried_instead_of_ending_the_worker(self):
        forecast = weather.parse_forecast(response_fixture(), CET)
        display = weather.Weather(Mock(side_effect=[IncompleteRead(b"partial", 50), forecast]),
                                  tz=CET, clock=lambda: NOW, start_worker=False)
        with patch("builtins.print"):
            self.assertFalse(display.refresh())
        self.assertEqual(display.pages(), [("WEATHER", "UNAVAILABLE")])
        self.assertTrue(display.refresh())
        self.assertEqual(display.pages()[0][0], "NOW 12C / 54F")

    def test_cards_show_current_high_low_both_units_and_rain_details(self):
        forecast = weather.parse_forecast(response_fixture(), CET)
        pages = weather.forecast_pages(forecast, NOW, CET)
        self.assertIn(("NOW 12C / 54F", "RAIN"), pages)
        self.assertIn(("TODAY HIGH", "16C / 61F"), pages)
        self.assertIn(("TODAY LOW", "4C / 39F"), pages)
        self.assertIn(("RAIN/SNOW 80%", "TODAY 3.2mm"), pages)
        self.assertIn(("FEELS 9C / 49F", "WIND 18km/h"), pages)
        self.assertEqual(pages[-6], ("15h 10C", "65% 0.8mm"))
        self.assertEqual(pages[-1], ("20h 10C", "65% 0.8mm"))

    def test_negative_temperature_conversion(self):
        self.assertEqual(weather.temperature_pair(-10), "-10C / 14F")
        self.assertEqual(weather.temperature_pair(-40), "-40C / -40F")
        self.assertEqual(weather.temperature_pair(-0.1), "0C / 32F")
        self.assertEqual(weather.temperature_pair(None), "--C / --F")

    def test_null_missing_and_invalid_values_are_not_reported_as_zero(self):
        data = response_fixture()
        data["current"].update(temperature_2m=None, apparent_temperature=float("nan"), weather_code=True)
        data["daily"]["precipitation_probability_max"] = [None]
        del data["daily"]["precipitation_sum"]
        data["hourly"]["precipitation_probability"] = [101] * 48
        data["hourly"]["precipitation"] = [-1] * 48
        pages = weather.forecast_pages(weather.parse_forecast(data, CET), NOW, CET)
        self.assertIn(("NOW --C / --F", "CONDITION --"), pages)
        self.assertIn(("RAIN/SNOW --%", "TODAY --mm"), pages)
        self.assertEqual(pages[-1][1], "--% --mm")
        for bad in ({"error": True}, {}, {"current": []}, {"hourly": {"time": "bad"}}):
            with self.subTest(response=bad), self.assertRaises(ValueError):
                weather.parse_forecast(bad, CET)
        data = response_fixture()
        del data["current"]["time"]
        forecast = weather.parse_forecast(data, CET)
        self.assertIsNone(forecast.temperature)

    def test_daily_selection_and_upcoming_hours_cross_midnight(self):
        forecast = weather.parse_forecast(response_fixture(), CET)
        late = datetime(2026, 10, 25, 23, 30, tzinfo=CET).timestamp()
        pages = weather.forecast_pages(forecast, late, CET)
        self.assertEqual(pages[-6][0], "TMR 00h 10C")
        tomorrow = late + 3600
        pages = weather.forecast_pages(forecast, tomorrow, CET)
        self.assertIn(("TODAY HIGH", "18C / 64F"), pages)
        day_after = datetime(2026, 10, 27, 12, tzinfo=CET).timestamp()
        pages = weather.forecast_pages(forecast, day_after, CET)
        self.assertIn(("TODAY", "NO FORECAST"), pages)
        self.assertNotIn(("TODAY HIGH", "16C / 61F"), pages)

    def test_failed_refresh_marks_cached_data_old_and_eventually_expires(self):
        now = [NOW]
        forecast = weather.parse_forecast(response_fixture(), CET)
        fetcher = Mock(side_effect=[OSError("offline"), forecast, OSError("offline")])
        display = weather.Weather(fetcher, tz=CET, clock=lambda: now[0], start_worker=False)
        self.assertEqual(display.pages(), [("WEATHER", "LOADING")])
        with patch("builtins.print"):
            self.assertFalse(display.refresh())
        self.assertEqual(display.pages(), [("WEATHER", "UNAVAILABLE")])
        self.assertTrue(display.refresh())
        self.assertEqual(display.pages()[0][0], "NOW 12C / 54F")
        with patch("builtins.print"):
            self.assertFalse(display.refresh())
        self.assertTrue(all(top.startswith("OLD ") for top, _ in display.pages()))
        now[0] += weather.EXPIRE_SECONDS
        self.assertEqual(display.pages(), [("WEATHER", "UNAVAILABLE")])

    def test_aged_data_is_marked_old_even_before_a_failed_refresh(self):
        now = [NOW]
        display = weather.Weather(lambda: weather.parse_forecast(response_fixture(), CET),
                                  tz=CET, clock=lambda: now[0], start_worker=False)
        display.refresh()
        now[0] += weather.STALE_SECONDS
        self.assertTrue(display.pages()[0][0].startswith("OLD "))

    def test_an_old_provider_current_timestamp_cannot_appear_fresh(self):
        data = response_fixture()
        data["current"]["time"] = NOW - weather.EXPIRE_SECONDS
        display = weather.Weather(lambda: weather.parse_forecast(data, CET), tz=CET,
                                  clock=lambda: NOW, start_worker=False)
        self.assertTrue(display.refresh())
        self.assertEqual(display.pages(), [("WEATHER", "UNAVAILABLE")])

    def test_every_card_renders_to_the_matrix_shape_without_network(self):
        display = weather.Weather(lambda: weather.parse_forecast(response_fixture(), CET),
                                  tz=CET, clock=lambda: NOW, start_worker=False)
        display.refresh()
        for index, _ in enumerate(display.pages()):
            with self.subTest(page=index):
                image = display.render(index * weather.PAGE_SECONDS, 0)
                self.assertEqual(image.mode, "1")
                self.assertEqual(image.size, (64, 16))
                self.assertIsNotNone(image.getbbox())

    def test_long_cards_finish_scrolling_before_the_next_page(self):
        display = weather.Weather(tz=CET, start_worker=False)
        long_card = ("OLD FEELS -120C / -184F", "WIND 100km/h")
        next_card = ("TODAY HIGH", "-10C / 14F")
        duration = weather.panel_duration(long_card, minimum=weather.PAGE_SECONDS)
        self.assertGreater(duration, weather.PAGE_SECONDS)
        with patch.object(display, "pages", return_value=[long_card, next_card]), patch("weather.render_lines") as draw:
            display.render(duration - 0.1, 0)
            draw.assert_called_with(long_card, duration - 0.1)
            display.render(duration + 0.5, 0)
            draw.assert_called_with(next_card, 0.5)

    def test_fetch_uses_bounded_request_and_dst_safe_times(self):
        response = Mock()
        response.read.return_value = json.dumps(response_fixture()).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.dict("os.environ", {}, clear=True), patch("weather.urlopen", return_value=response) as request:
            forecast = weather.fetch_forecast(CET)
        self.assertEqual(forecast.temperature, 12.4)
        query = parse_qs(urlparse(request.call_args.args[0]).query)
        self.assertEqual(query["timeformat"], ["unixtime"])
        self.assertEqual(query["timezone"], ["Europe/Berlin"])
        self.assertEqual(query["latitude"], ["48.25"])
        self.assertEqual(request.call_args.kwargs["timeout"], 8)
        response.read.assert_called_once_with(weather.MAX_RESPONSE_BYTES + 1)
        response.read.return_value = b" " * (weather.MAX_RESPONSE_BYTES + 1)
        with patch("weather.urlopen", return_value=response), self.assertRaises(ValueError):
            weather.fetch_forecast(CET)

    def test_coordinates_are_configurable_and_reject_invalid_input(self):
        with patch.dict("os.environ", {"GARCHING_WEATHER_LATITUDE": "48.26", "GARCHING_WEATHER_LONGITUDE": "11.67"}):
            self.assertEqual(weather.coordinates(), (48.26, 11.67))
        for value in ("nan", "inf", "bad", "91"):
            with self.subTest(value=value), patch.dict("os.environ", {"GARCHING_WEATHER_LATITUDE": value}), self.assertRaises(ValueError):
                weather.coordinates()


if __name__ == "__main__":
    unittest.main()
