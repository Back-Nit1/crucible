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
