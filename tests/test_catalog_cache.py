from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from catalog.cache import FrozenCache


def test_lru_eviction_refreshes_recency_and_zero_disables_storage():
    class Provider:
        def __init__(self):
            self.calls = []

        def get_product(self, key):
            self.calls.append(key)
            return key

    provider = Provider()
    cache = FrozenCache(provider, max_entries=2)
    for key in ("a", "b", "a", "c", "a", "b"):
        assert cache.get_product(key) == key
    assert provider.calls == ["a", "b", "c", "b"]
    assert (cache.hits, cache.misses) == (2, 4)
    disabled = FrozenCache(provider, max_entries=0)
    disabled.get_product("a")
    disabled.get_product("a")
    assert disabled.hits == 0 and not disabled._c
    with pytest.raises(ValueError):
        FrozenCache(provider, max_entries=-1)


def test_concurrent_misses_do_not_hold_lock_during_provider_calls():
    barrier = Barrier(2)

    class Provider:
        def get_product(self, key):
            barrier.wait(timeout=5)
            return key

    cache = FrozenCache(Provider(), max_entries=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(cache.get_product, ["a", "b"])) == ["a", "b"]
    assert len(cache._c) == 1


def test_search_accepts_nested_filters_and_keys_them_canonically():
    class Provider:
        calls = 0

        def search(self, query, filters=None):
            Provider.calls += 1
            return ["p"]

    cache = FrozenCache(Provider())
    a = {"price": {"max": 50, "min": 5}, "brand": "x"}
    b = {"brand": "x", "price": {"min": 5, "max": 50}}
    assert cache.search("q", a) == cache.search("q", b) == ["p"]
    assert Provider.calls == 1
