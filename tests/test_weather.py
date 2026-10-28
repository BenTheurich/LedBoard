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
    def test_readiness_waits_for_forecast_or_a_completed_error(self):
        forecast = weather.parse_forecast(response_fixture(), CET)
        for result in (forecast, OSError("offline")):
            with self.subTest(result=result):
                fetcher = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
                display = weather.Weather(fetcher, tz=CET, clock=lambda: NOW, start_worker=False)
                self.assertFalse(display.ready)
                with patch("builtins.print"):
                    display.refresh()
                self.assertTrue(display.ready)

    def test_truncated_response_is_retried_instead_of_ending_the_worker(self):
        forecast = weather.parse_forecast(response_fixture(), CET)
        display = weather.Weather(Mock(side_effect=[IncompleteRead(b"partial", 50), forecast]),
                                  tz=CET, clock=lambda: NOW, start_worker=False)
        with patch("builtins.print"):
            self.assertFalse(display.refresh())
        self.assertEqual(display.pages(), [("WEATHER", "UNAVAILABLE")])
        self.assertTrue(display.refresh())
        self.assertEqual(display.pages()[0][0], "NOW 12C")

    def test_detail_cards_use_explicit_labels_and_units(self):
        forecast = weather.parse_forecast(response_fixture(), CET)
        pages = weather.forecast_pages(forecast, NOW, CET)
        self.assertEqual(pages[:4], [("NOW 12C", "RAIN"), ("HIGH 16C", "LOW 4C"),
                                    ("RAIN TODAY", "80% 3.2MM"), ("FEELS 9C", "WIND 18KM/H")])
        self.assertEqual(pages[4:], [(f"RAIN {hour:02d}H", "65% 0.8MM")
                                    for hour in (8, 12, 16, 20)])

    def test_four_fixed_points_include_earlier_hours_and_do_not_use_tomorrow(self):
        data = response_fixture()
        data["hourly"]["temperature_2m"] = list(range(48))
        forecast = weather.parse_forecast(data, CET)
        for hour in (1, 14, 23):
            now = datetime(2026, 10, 25, hour, 30, tzinfo=CET).timestamp()
            points = weather.overview_points(forecast, now, CET)
            self.assertEqual([hour for hour, _ in points], [8, 12, 16, 20])
            self.assertEqual([value.temperature for _, value in points], [8, 12, 16, 20])
        tomorrow = datetime(2026, 10, 26, 0, 30, tzinfo=CET).timestamp()
        points = weather.overview_points(forecast, tomorrow, CET)
        self.assertEqual([value.temperature for _, value in points], [32, 36, 40, 44])

    def test_null_missing_and_invalid_values_are_not_reported_as_zero(self):
        data = response_fixture()
        data["current"].update(temperature_2m=None, apparent_temperature=float("nan"), weather_code=True)
        data["daily"]["precipitation_probability_max"] = [None]
        del data["daily"]["precipitation_sum"]
        data["hourly"]["precipitation_probability"] = [101] * 48
        data["hourly"]["precipitation"] = [-1] * 48
        pages = weather.forecast_pages(weather.parse_forecast(data, CET), NOW, CET)
        self.assertIn(("NOW --C", "CONDITION --"), pages)
        self.assertIn(("RAIN TODAY", "--% --MM"), pages)
        self.assertIn(("FEELS --C", "WIND 18KM/H"), pages)
        self.assertEqual(pages[-1], ("RAIN 20H", "--% --MM"))
        points = weather.overview_points(weather.parse_forecast(data, CET), NOW, CET)
        self.assertTrue(all(value.probability is None for _, value in points))
        for bad in ({"error": True}, {}, {"current": []}, {"hourly": {"time": "bad"}}):
            with self.subTest(response=bad), self.assertRaises(ValueError):
                weather.parse_forecast(bad, CET)
        data = response_fixture()
        del data["current"]["time"]
        forecast = weather.parse_forecast(data, CET)
        self.assertIsNone(forecast.temperature)

    def test_daily_summary_switches_at_midnight_and_missing_dates_stay_missing(self):
        forecast = weather.parse_forecast(response_fixture(), CET)
        late = datetime(2026, 10, 25, 23, 30, tzinfo=CET).timestamp()
        pages = weather.forecast_pages(forecast, late, CET)
        self.assertEqual(pages[1], ("HIGH 16C", "LOW 4C"))
        tomorrow = late + 3600
        pages = weather.forecast_pages(forecast, tomorrow, CET)
        self.assertEqual(pages[1], ("HIGH 18C", "LOW 5C"))
        day_after = datetime(2026, 10, 27, 12, tzinfo=CET).timestamp()
        pages = weather.forecast_pages(forecast, day_after, CET)
        self.assertEqual(pages[1], ("HIGH --C", "LOW --C"))
        self.assertTrue(all(value is None for _, value in weather.overview_points(forecast, day_after, CET)))

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
        self.assertEqual(display.pages()[0][0], "NOW 12C")
        with patch("builtins.print"):
            self.assertFalse(display.refresh())
        self.assertEqual(display.pages(), [("WEATHER OLD", "RETRYING")])
        with patch("weather.render_overview") as overview:
            display.render(0, 0)
        overview.assert_not_called()
        now[0] += weather.EXPIRE_SECONDS
        self.assertEqual(display.pages(), [("WEATHER", "UNAVAILABLE")])

    def test_aged_data_is_marked_old_even_before_a_failed_refresh(self):
        now = [NOW]
        display = weather.Weather(lambda: weather.parse_forecast(response_fixture(), CET),
                                  tz=CET, clock=lambda: now[0], start_worker=False)
        display.refresh()
        now[0] += weather.STALE_SECONDS
        self.assertEqual(display.pages(), [("WEATHER OLD", "RETRYING")])

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
        times = [0, 8, weather.OVERVIEW_SECONDS]
        for page in display.pages():
            times.append(times[-1] + weather.panel_duration(page, font=weather._FONT, minimum=weather.PAGE_SECONDS))
        for index, elapsed in enumerate(times):
            with self.subTest(page=index):
                image = display.render(elapsed, 0)
                self.assertEqual(image.mode, "1")
                self.assertEqual(image.size, (64, 16))
                self.assertIsNotNone(image.getbbox())

    def test_long_cards_finish_scrolling_before_the_next_page(self):
        display = weather.Weather(lambda: weather.parse_forecast(response_fixture(), CET),
                                  tz=CET, clock=lambda: NOW, start_worker=False)
        display.refresh()
        long_card = ("WEATHER DATA UNAVAILABLE", "FREEZING RAIN")
        next_card = ("HIGH -10C", "LOW -20C")
        duration = weather.panel_duration(long_card, font=weather._FONT, minimum=weather.PAGE_SECONDS)
        self.assertGreater(duration, weather.PAGE_SECONDS)
        with patch("weather.forecast_pages", return_value=[long_card, next_card]), patch("weather.render_lines") as draw:
            display.render(weather.OVERVIEW_SECONDS + duration - 0.1, 0)
            self.assertEqual(draw.call_args.args[0], long_card)
            self.assertAlmostEqual(draw.call_args.args[1], duration - 0.1)
            self.assertIs(draw.call_args.kwargs["font"], weather._FONT)
            display.render(weather.OVERVIEW_SECONDS + duration + 0.5, 0)
            self.assertEqual(draw.call_args.args[0], next_card)
            self.assertAlmostEqual(draw.call_args.args[1], 0.5)

    def test_overview_uses_two_readable_rows_with_all_four_celsius_temperatures(self):
        data = response_fixture()
        for hour, temperature, chance in ((8, -12, 0), (12, 3, 25), (16, 17, 50), (20, 7, 100)):
            data["hourly"]["temperature_2m"][hour] = temperature
            data["hourly"]["precipitation_probability"][hour] = chance
        points = weather.overview_points(weather.parse_forecast(data, CET), NOW, CET)
        image = weather.render_overview(points)
        self.assertEqual((image.mode, image.size), ("1", (64, 16)))
        for column in range(4):
            left = column * 16
            top = image.crop((left, 0, left + 16, 8)).getbbox()
            bottom = image.crop((left, 8, left + 16, 16)).getbbox()
            self.assertEqual(top[3] - top[1], 7)
            self.assertEqual(bottom[3] - bottom[1], 7)
        # A minus sign remains visible inside the first column without clipping.
        self.assertTrue(all(image.getpixel((x, 12)) for x in range(1, 4)))
        for value in ("12C", "-12C", "--C"):
            self.assertLessEqual(weather.textsize(value, weather._NUMERIC_FONT)[0], 16)

    def test_unknown_rain_is_explicit_in_hourly_cards_and_missing_temperatures_remain_visible(self):
        data = response_fixture()
        data["hourly"]["time"][12] = None
        data["hourly"]["precipitation_probability"][8] = 0
        points = weather.overview_points(weather.parse_forecast(data, CET), NOW, CET)
        self.assertIsNone(points[1][1])
        image = weather.render_overview(points)
        self.assertIsNotNone(image.crop((16, 8, 32, 16)).getbbox())
        pages = weather.forecast_pages(weather.parse_forecast(data, CET), NOW, CET)
        self.assertIn(("RAIN 08H", "0% 0.8MM"), pages)
        self.assertIn(("RAIN 12H", "--% --MM"), pages)

    def test_overview_has_no_ambiguous_rain_bars(self):
        data = response_fixture()
        dry = weather.render_overview(weather.overview_points(weather.parse_forecast(data, CET), NOW, CET))
        data["hourly"]["precipitation_probability"] = [100] * 48
        wet = weather.render_overview(weather.overview_points(weather.parse_forecast(data, CET), NOW, CET))
        self.assertEqual(dry.tobytes(), wet.tobytes())

    def test_detail_font_fits_normal_labels_and_each_card_holds_at_least_six_seconds(self):
        for label in ("NOW 12C", "FEELS -12C", "HIGH 13C", "LOW -12C", "RAIN TODAY",
                      "100% 11.5MM", "RAIN 20H", "WIND 18KM/H"):
            self.assertLessEqual(weather.textsize(label, weather._FONT)[0], 64, label)
        self.assertGreaterEqual(weather.PAGE_SECONDS, 6)
        display = weather.Weather(lambda: weather.parse_forecast(response_fixture(), CET),
                                  tz=CET, clock=lambda: NOW, start_worker=False)
        display.refresh()
        with patch("weather.render_lines") as detail:
            display.render(weather.OVERVIEW_SECONDS + 5.9, 0)
            self.assertEqual(detail.call_args.args[0], display.pages()[0])
            display.render(weather.OVERVIEW_SECONDS + 6.0, 0)
            self.assertEqual(detail.call_args.args[0], display.pages()[1])

    def test_overview_stays_static_for_sixteen_seconds_before_detail_cards(self):
        display = weather.Weather(lambda: weather.parse_forecast(response_fixture(), CET),
                                  tz=CET, clock=lambda: NOW, start_worker=False)
        display.refresh()
        self.assertEqual(display.render(0, 0).tobytes(), display.render(15.9, 0).tobytes())
        with patch("weather.render_lines") as detail:
            display.render(weather.OVERVIEW_SECONDS, 0)
            detail.assert_called_once_with(display.pages()[0], 0, font=weather._FONT)

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
