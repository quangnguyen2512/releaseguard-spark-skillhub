from endpoints.search_api import search_items_endpoint


def test_search_items_pattern_validation():
    assert search_items_endpoint("SKU_100")["valid"] is True
