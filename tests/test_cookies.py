import json
import tempfile
import unittest
from pathlib import Path

from copercitrus_price_collector.cookies import load_cookie_file
from copercitrus_price_collector.errors import ConfigurationError


def _write(directory, payload, name="cookies.json"):
    path = Path(directory) / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class CookieImportTest(unittest.TestCase):
    def test_reads_cookie_editor_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                [
                    {
                        "name": "SPC_F",
                        "value": "abc",
                        "domain": ".shopee.com.br",
                        "path": "/",
                        "secure": True,
                        "httpOnly": True,
                        "sameSite": "no_restriction",
                        "expirationDate": 1800000000.5,
                    }
                ],
            )

            cookies = load_cookie_file(path)

            self.assertEqual(1, len(cookies))
            self.assertEqual("SPC_F", cookies[0]["name"])
            self.assertEqual("None", cookies[0]["sameSite"])
            self.assertEqual(1800000000.5, cookies[0]["expires"])

    def test_reads_playwright_storage_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                {
                    "cookies": [
                        {"name": "a", "value": "1", "domain": ".shopee.com.br", "path": "/"}
                    ],
                    "origins": [],
                },
            )

            self.assertEqual(1, len(load_cookie_file(path)))

    def test_session_cookie_has_no_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(
                directory,
                [
                    {
                        "name": "a",
                        "value": "1",
                        "domain": ".shopee.com.br",
                        "session": True,
                        "expirationDate": 1800000000,
                    }
                ],
            )

            self.assertNotIn("expires", load_cookie_file(path)[0])

    def test_entry_without_domain_is_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = _write(directory, [{"name": "a", "value": "1"}])

            with self.assertRaises(ConfigurationError):
                load_cookie_file(path)

    def test_missing_file_is_reported(self):
        with self.assertRaises(ConfigurationError):
            load_cookie_file("nao-existe.json")

    def test_invalid_json_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cookies.json"
            path.write_text("{nao e json", encoding="utf-8")

            with self.assertRaises(ConfigurationError):
                load_cookie_file(path)


if __name__ == "__main__":
    unittest.main()


class MarketplaceTest(unittest.TestCase):
    """Loja generica no card era promocao lida como vendedor."""

    def test_cashback_line_is_not_a_store(self):
        from copercitrus_price_collector.product_analysis import extract_seller

        texto = "Lavadora\nR$ 900,00\n1% de volta na loja toda\nMagalu"

        self.assertEqual("Magalu", extract_seller(texto))

    def test_identifies_marketplace_by_domain(self):
        from copercitrus_price_collector.product_analysis import identificar_marketplace

        self.assertEqual(
            "Mercado Livre",
            identificar_marketplace("https://produto.mercadolivre.com.br/MLB-1"),
        )
        self.assertEqual(
            "Shopee", identificar_marketplace("https://shopee.com.br/product/1/2")
        )

    def test_comparison_site_is_not_a_marketplace(self):
        from copercitrus_price_collector.product_analysis import identificar_marketplace

        self.assertIsNone(identificar_marketplace("https://www.buscape.com.br/lead?oid=1"))
        self.assertIsNone(identificar_marketplace(None))

    def test_store_count_is_not_a_store_name(self):
        """"1 loja" e contagem de vendedores do comparador, nao vendedor."""
        from copercitrus_price_collector.product_analysis import extract_seller

        self.assertEqual("Magalu", extract_seller("Lavadora\nR$ 900,00\n1 loja\nMagalu"))
        self.assertEqual(
            "Webcontinental",
            extract_seller("Lavadora\nR$ 900,00\nem 3 lojas\nWebcontinental"),
        )

    def test_store_named_lojas_still_works(self):
        from copercitrus_price_collector.product_analysis import extract_seller

        self.assertEqual(
            "Lojas Americanas",
            extract_seller("Lavadora\nR$ 900,00\nLojas Americanas"),
        )
