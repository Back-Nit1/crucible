from tests.fixtures.real_snapshot import real_snapshot_cases


def test_real_snapshot_cases_are_manifest_backed_without_raw_review_data():
    cases = real_snapshot_cases()
    assert {case.category for case in cases} == {
        "Clothing_Shoes_and_Jewelry",
        "Electronics",
        "Office_Products",
        "Sports_and_Outdoors",
    }
    assert all(len(case.manifest_hash) == 64 for case in cases)
    assert sum(case.product_count for case in cases) == 590
    assert sum(case.review_count for case in cases) == 14_541
    assert all(case.batch_config.feasible_percent == 75 for case in cases)
    assert all(case.review_sensitive for case in cases)
