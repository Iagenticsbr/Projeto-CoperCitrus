import unittest

from copercitrus_price_collector.models import ProductInput
from copercitrus_price_collector.providers.shopee_affiliate import ShopeeWebProvider as ShopeeProvider


class FakeBrowser:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def fetch_json(self, provider_name, page_url, api_path):
        self.calls.append((provider_name, page_url, api_path))
        return self.body


# Resposta reduzida no formato que a busca da Shopee devolve. Os valores
# monetarios chegam multiplicados por 100000.
BODY = {
    "items": [
        {
            "item_basic": {
                "itemid": 123,
                "shopid": 456,
                "name": "Lavadora Alta Pressao Jacto J6600 220V",
                "price": 99900000,
                "price_min": 89900000,
                "price_max": 129900000,
                "historical_sold": 42,
                "item_rating": {"rating_star": 4.8123, "rating_count": [17, 1, 0]},
                "images": ["abc123"],
                "shop_location": "SP",
            }
        },
        {
            "item_basic": {
                "itemid": 789,
                "shopid": 456,
                "name": "",
                "price": 1000000,
            }
        },
    ]
}


class ShopeeProviderTest(unittest.TestCase):
    def setUp(self):
        self.product = ProductInput(
            4, "LAVADORA ALTA PRESSAO J6600 220V", "Jacto", "1350780 JACTO", "1271265"
        )

    def test_reads_price_range_from_the_search_api(self):
        browser = FakeBrowser(BODY)

        results = ShopeeProvider(browser).search(self.product, 5)

        self.assertEqual(1, len(results))
        offer = results[0]
        self.assertEqual(899.0, offer.price_min)
        self.assertEqual(1299.0, offer.price_max)
        self.assertEqual("BRL", offer.currency)
        self.assertEqual("https://shopee.com.br/product/456/123", offer.purchase_url)
        self.assertEqual(42, offer.sold_count)
        self.assertEqual(4.81, offer.rating)
        self.assertEqual(17, offer.review_count)
        self.assertIn("abc123", offer.image_url)

    def test_searches_by_keyword_built_from_the_spreadsheet(self):
        browser = FakeBrowser(BODY)

        ShopeeProvider(browser).search(self.product, 5)

        _, page_url, api_path = browser.calls[0]
        self.assertIn("/search?keyword=", page_url)
        self.assertIn("page_type=search", api_path)
        self.assertIn("scenario=PAGE_GLOBAL_SEARCH", api_path)
        self.assertIn("J6600", api_path)
        # O codigo interno da CoperCitrus nao vai para a busca publica.
        self.assertNotIn("1271265", api_path)

    def test_skips_entries_without_a_name(self):
        results = ShopeeProvider(FakeBrowser(BODY)).search(self.product, 5)

        self.assertTrue(all(offer.title for offer in results))

    def test_empty_response_yields_no_offers(self):
        self.assertEqual([], ShopeeProvider(FakeBrowser({})).search(self.product, 5))

    def test_respects_the_limit(self):
        body = {"items": BODY["items"] * 5}

        results = ShopeeProvider(FakeBrowser(body)).search(self.product, 3)

        self.assertLessEqual(len(results), 3)


if __name__ == "__main__":
    unittest.main()
