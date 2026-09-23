"""
Thin REST client for the Unusual Whales public API
(https://api.unusualwhales.com/docs). Bearer-token auth, one retry on a
429 respecting Retry-After, one retry on a dropped connection / timeout / 5xx, everything else raises.
"""
import os
import time

import requests

BASE_URL = "https://api.unusualwhales.com"
# Client-id header UW's own agent guide (unusualwhales.com/skill.md) asks for on every request.
CLIENT_API_ID = "100001"
TRANSIENT_RETRY_SECONDS = 1.0


class UnusualWhalesAuthError(RuntimeError):
    pass


class UnusualWhalesClient:
    def __init__(self, api_key=None, base_url=BASE_URL, timeout=10):
        self.api_key = api_key or os.getenv("UNUSUAL_WHALES_API_KEY")
        if not self.api_key or self.api_key == "your_unusual_whales_api_key":
            raise UnusualWhalesAuthError(
                "UNUSUAL_WHALES_API_KEY is not set. Get a trial key at "
                "https://unusualwhales.com/public-api#pricing and put it in .env."
            )
        self.base_url = base_url
        self.timeout = timeout
        self.daily_request_count = 0      # from the x-uw-daily-req-count header; limit is x-uw-token-req-limit
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "UW-CLIENT-API-ID": CLIENT_API_ID,
        })

    def _send(self, url, params):
        """One GET, retried once after a short pause on a dropped connection, a timeout or a 5xx -- transient
        failures seen live that would otherwise abort a whole scan."""
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(TRANSIENT_RETRY_SECONDS)
            return self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code >= 500:
            time.sleep(TRANSIENT_RETRY_SECONDS)
            return self.session.get(url, params=params, timeout=self.timeout)
        return response

    def get(self, path, params=None):
        url = f"{self.base_url}{path}"
        response = self._send(url, params)
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 1))
            time.sleep(retry_after)
            response = self._send(url, params)
        try:
            self.daily_request_count = int(response.headers.get("x-uw-daily-req-count", self.daily_request_count))
        except ValueError:
            pass
        response.raise_for_status()
        return response.json()
