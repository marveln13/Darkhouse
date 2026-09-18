"""
Thin REST client for the Unusual Whales public API
(https://api.unusualwhales.com/docs). Bearer-token auth, one retry on a
429 respecting Retry-After, everything else raises.
"""
import os
import time

import requests

BASE_URL = "https://api.unusualwhales.com"


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
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def get(self, path, params=None):
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 1))
            time.sleep(retry_after)
            response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()
