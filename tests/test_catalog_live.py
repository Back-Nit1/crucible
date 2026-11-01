"""Opt-in (`pytest -m live`): the frozen contracts against the real Elastic snapshot (read-only)."""
import os

import pytest

from catalog.providers.elastic import Elastic, ElasticCatalogProvider, endpoint_from_cloud_id, load_manifest_hashes

pytestmark = pytest.mark.live


def provider():
    url = os.environ.get("ELASTIC_ENDPOINT") or (endpoint_from_cloud_id(os.environ["ELASTIC_CLOUD_ID"]) if os.environ.get("ELASTIC_CLOUD_ID") else None)
    if not (url and os.environ.get("ELASTIC_API_KEY")):
        pytest.skip("no Elastic credentials")
    return ElasticCatalogProvider(Elastic(url))


def test_every_manifest_category_enumerates_completely_and_review_ids_match_the_manifest():
    p = provider()
    for cat, h in load_manifest_hashes().items():
        prods = list(p.iter_products(cat, h))
        ids = [x.id for x in prods]
        assert ids == sorted(ids) and all(x.snapshot and not x.variants and x.manifest_hash == h for x in prods)
        reviews = sum(len(p.get_review_ids(i).ids) for i in ids)
        import json
        m = json.load(open(f"data/manifests/{cat}.json"))
        assert (len(prods), reviews) == (m["products"], m["reviews"])  # nothing truncated, nothing extra
    assert p.get_review_ids("NOT-A-PRODUCT").product_found is False
