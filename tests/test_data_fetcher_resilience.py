"""Unit tests for data_fetcher HTTP retries and 3rd-exchange Kraken fallbacks."""
from __future__ import annotations

import io
import json
import time
import unittest
import urllib.error
from unittest.mock import patch

from engine import data_fetcher


class _FakeResp:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class DataFetcherResilienceTests(unittest.TestCase):
    def test_get_json_retries_transient_http_503_and_succeeds(self) -> None:
        calls = 0

        def fake_urlopen(req, timeout=12):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise urllib.error.HTTPError(
                    req.full_url, 503, "Service Unavailable", None, io.BytesIO(b"")
                )
            return _FakeResp({"ok": True})

        errors: list[str] = []
        with patch("engine.data_fetcher.urllib.request.urlopen", side_effect=fake_urlopen), patch(
            "engine.data_fetcher.time.sleep"
        ) as mock_sleep:
            res = data_fetcher._get_json("https://example.com/api", "test_api", errors)

        self.assertEqual(res, {"ok": True})
        self.assertEqual(errors, [])
        self.assertEqual(calls, 2)
        mock_sleep.assert_called_once()

    def test_get_json_does_not_retry_http_404(self) -> None:
        calls = 0

        def fake_urlopen(req, timeout=12):
            nonlocal calls
            calls += 1
            raise urllib.error.HTTPError(
                req.full_url, 404, "Not Found", None, io.BytesIO(b"")
            )

        errors: list[str] = []
        with patch("engine.data_fetcher.urllib.request.urlopen", side_effect=fake_urlopen), patch(
            "engine.data_fetcher.time.sleep"
        ) as mock_sleep:
            res = data_fetcher._get_json("https://example.com/missing", "test_404", errors)

        self.assertIsNone(res)
        self.assertEqual(calls, 1)
        self.assertEqual(len(errors), 1)
        self.assertIn("404", errors[0])
        mock_sleep.assert_not_called()

    def test_fetch_klines_falls_back_to_kraken_closed_only(self) -> None:
        now_s = int(time.time())
        interval_s = 3600  # 1h
        base_closed_s = now_s - 20 * interval_s
        rows = []
        for i in range(14):
            t = base_closed_s + i * interval_s
            rows.append([t, "60000", "60200", "59800", "60100", "60050", "12.5", 42])
        # 15th bar is currently open/forming: t + 3600s > now_s
        forming_t = now_s - 600
        rows.append([forming_t, "60100", "60300", "59900", "60250", "60150", "3.2", 15])

        def fake_get_json(url, name, errors, timeout=12, headers=None, retries=2):
            if "kraken.com" in url:
                return {"error": [], "result": {"XXBTZUSD": rows, "last": forming_t}}
            return None

        errors: list[str] = []
        with patch("engine.data_fetcher._get_json", side_effect=fake_get_json):
            bars, src = data_fetcher.fetch_klines("BTC-USDT-SWAP", "BTCUSDT", "1H", "1h", 168, errors)

        self.assertEqual(src, "KrakenSpot XBTUSD")
        self.assertEqual(len(bars), 14)
        self.assertEqual(bars[-1]["ts"], (base_closed_s + 13 * interval_s) * 1000)

    def test_fetch_live_ticker_falls_back_to_kraken(self) -> None:
        def fake_get_json(url, name, errors, timeout=12, headers=None, retries=2):
            if "kraken.com" in url:
                return {
                    "error": [],
                    "result": {
                        "XXBTZUSD": {
                            "c": ["60500.0", "0.1"],
                            "h": ["60800.0", "61000.0"],
                            "l": ["59900.0", "59500.0"],
                            "o": "60000.0",
                        }
                    },
                }
            return None

        errors: list[str] = []
        with patch("engine.data_fetcher._get_json", side_effect=fake_get_json):
            ticker = data_fetcher.fetch_live_ticker(errors)

        self.assertEqual(ticker["source"], "KrakenSpot XBTUSD")
        self.assertEqual(ticker["price"], 60500.0)
        self.assertEqual(ticker["high24"], 61000.0)
        self.assertEqual(ticker["low24"], 59500.0)
        self.assertEqual(ticker["chg24_pct"], 0.83)


if __name__ == "__main__":
    unittest.main()
