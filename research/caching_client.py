"""On-disk cache around the UW client so a re-run never re-spends API quota.
Cache dir is gitignored: UW data is personal-use and must not be committed."""
import hashlib
import json
import os


class CachingClient:
    def __init__(self, inner, cache_dir):
        self.inner, self.cache_dir = inner, cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get(self, path, params=None):
        key = hashlib.sha1(json.dumps([path, params or {}], sort_keys=True).encode()).hexdigest()
        file = os.path.join(self.cache_dir, key + ".json")
        if os.path.exists(file):
            with open(file, encoding="utf-8") as f:
                return json.load(f)
        data = self.inner.get(path, params=params)
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return data
