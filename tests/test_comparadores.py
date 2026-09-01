import unittest

from copercitrus_price_collector.browser import BrowserProductCard
from copercitrus_price_collector.models import ProductInput
from copercitrus_price_collector.product_analysis import (
    build_search_terms,
    match_tokens,
    similarity_score,
)
from copercitrus_price_collector.providers import (
    BingShoppingProvider,
    BuscapeProvider,
    ZoomProvider,
)


class ConfiguracaoFalsa:
    lojas_preferidas = ("mercado livre", "shopee")


class FakeBrowser:
    def __init__(self, cards):
        self.cards = cards
        self.calls = []
        self.settings = ConfiguracaoFalsa()

    def collect_cards(self, provider_name, url, selectors, limit):
        self.calls.append((provider_name, url, selectors, limit))
        return self.cards[:limit]


CARD = BrowserProductCard(
    title="Lavadora de Alta Pressao J6000 Plus 220 Volts Jacto",
    price_text="R$ 888,29",
    purchase_url="https://www.buscape.com.br/lead?oid=1",
    seller="Loja A",
)


class ComparadorProviderTest(unittest.TestCase):
    def test_buscape_searches_public_page_and_maps_card(self):
        browser = FakeBrowser([CARD])
        product = ProductInput(
            4, "LAVADORA ALTA PRESSAO J6000 PLUS 220V", "Jacto", "1350759 JACTO", "1271263"
        )

        results = BuscapeProvider(browser).search(product, 5)

        self.assertEqual(888.29, results[0].price_min)
        self.assertEqual("BRL", results[0].currency)
        self.assertIn("buscape.com.br/search", browser.calls[0][1])
        self.assertNotIn("1271263", browser.calls[0][1])

    def test_zoom_and_bing_use_their_own_endpoints(self):
        zoom = FakeBrowser([CARD])
        bing = FakeBrowser([CARD])
        product = ProductInput(4, "Lavadora alta pressao", "Jacto")

        ZoomProvider(zoom).search(product, 3)
        BingShoppingProvider(bing).search(product, 3)

        self.assertIn("zoom.com.br/search", zoom.calls[0][1])
        self.assertIn("bing.com/shop", bing.calls[0][1])
        self.assertIn("cc=br", bing.calls[0][1])


class SearchTermsTest(unittest.TestCase):
    def test_expands_abbreviations_and_drops_supplier_tag(self):
        terms = build_search_terms(
            "INVERSOR DIG C/MASCARA AUT IM125 VD", "Vonder", "6878125125 VONDER"
        )

        self.assertIn("digital", terms)
        self.assertIn("automatica", terms)
        self.assertIn("IM125", terms)
        self.assertIn("6878125125", terms)
        # "VD" e tag interna de fornecedor e nao existe em anuncio publico.
        self.assertNotIn(" VD", f" {terms}")
        # A marca aparece uma vez so, mesmo repetida no codigo do fabricante.
        self.assertEqual(1, terms.casefold().count("vonder"))

    def test_removes_non_breaking_space_from_spreadsheet(self):
        terms = build_search_terms("LAVADORA ALTA PRESSAO\xa0J6600\xa0220V", "Jacto")

        self.assertEqual("LAVADORA ALTA PRESSAO J6600 220V Jacto", terms)


class SimilarityTest(unittest.TestCase):
    def test_splits_glued_quantity_tokens(self):
        self.assertEqual(["jogo", "ferramentas", "110", "pecas"], match_tokens("JG FERRAMENTAS 110PCS"))

    def test_long_marketplace_title_is_not_penalised(self):
        product = ProductInput(4, "PULVERIZADOR COSTAL PJH", "Jacto", "825398 JACTO")

        score = similarity_score(
            product, "Pulverizador Costal Manual 20 Litros Serie 900 PJH Jacto"
        )

        self.assertGreaterEqual(score, 50.0)

    def test_accessory_stays_divergent(self):
        product = ProductInput(4, "PULVERIZADOR COSTAL PJH", "Jacto", "825398 JACTO")

        score = similarity_score(product, "Filtro Oleo Jacto")

        self.assertLess(score, 50.0)

    def test_spare_part_naming_the_equipment_is_divergent(self):
        """Peca repete o nome do equipamento e a cobertura sobe sozinha."""
        product = ProductInput(4, "PULVERIZADOR COSTAL PJH", "Jacto", "825398 JACTO")

        peca = similarity_score(product, "Cilindro Pulverizador Costal Jacto Pjh Completo")
        equipamento = similarity_score(
            product, "Pulverizador Costal Manual 20 Litros Serie 900 PJH Jacto"
        )

        self.assertLess(peca, 50.0)
        self.assertGreaterEqual(equipamento, 50.0)
        self.assertLess(peca, equipamento)

    def test_equivalent_model_stays_similar(self):
        """Modelo equivalente de outra potencia continua sendo alternativa."""
        product = ProductInput(
            4, "ESMERILHADEIRA ANGULAR 4 1/2 900W 220V", "Black & Decker", "DWE4120B2B DEWALT"
        )

        score = similarity_score(product, "Esmerilhadeira Angular 4.1/2 920W Black Decker 220V")

        self.assertGreaterEqual(score, 50.0)


if __name__ == "__main__":
    unittest.main()


class SellerExtractionTest(unittest.TestCase):
    """O Google ofusca as classes do card; a loja sai da ordem do texto."""

    def test_reads_store_after_the_price_lines(self):
        from copercitrus_price_collector.product_analysis import extract_seller

        texto = (
            "Lavadora de Alta Pressao Jacto J7600 Plus\n"
            "R$ 7.197,18 agora\n"
            "R$ 773,89/mes x 10\n"
            "Casa & Video\n"
            "Devolucao em ate 7 dia(s)"
        )

        self.assertEqual("Casa & Video", extract_seller(texto))

    def test_identifies_shopee_inside_google_results(self):
        from copercitrus_price_collector.product_analysis import extract_seller

        self.assertEqual(
            "Shopee",
            extract_seller("Chave de impacto\nR$ 999,99\nShopee\nFrete gratis"),
        )

    def test_prefers_the_explicit_sold_by_line(self):
        from copercitrus_price_collector.product_analysis import extract_seller

        self.assertEqual(
            "Loja do Mecanico",
            extract_seller("Produto\nR$ 10,00\nVendido por: Loja do Mecanico"),
        )

    def test_ignores_installment_value_without_currency_symbol(self):
        """O valor da parcela aparece sem moeda e nao e nome de loja."""
        from copercitrus_price_collector.product_analysis import extract_seller

        texto = "Lavadora Jacto\nR$ 1.499,00\n1.499\nMercado Livre"

        self.assertEqual("Mercado Livre", extract_seller(texto))

    def test_returns_nothing_without_a_price_line(self):
        from copercitrus_price_collector.product_analysis import extract_seller

        self.assertIsNone(extract_seller("Produto sem preco\nalguma coisa"))
        self.assertIsNone(extract_seller(None))


class LojasPreferidasTest(unittest.TestCase):
    """Mercado Livre e Shopee sao buscados ativamente, nao so filtrados."""

    def test_searches_each_preferred_marketplace(self):
        browser = FakeBrowser([CARD])
        product = ProductInput(4, "Lavadora alta pressao", "Jacto")

        BingShoppingProvider(browser).search(product, 3)

        consultas = [chamada[1] for chamada in browser.calls]
        self.assertEqual(3, len(consultas))
        self.assertTrue(any("mercado+livre" in url for url in consultas))
        self.assertTrue(any("shopee" in url for url in consultas))

    def test_preferred_store_is_flagged_and_ranked_first(self):
        from copercitrus_price_collector.providers.common import marcar_preferidas
        from copercitrus_price_collector.models import SearchResult

        def oferta(loja, preco):
            return SearchResult(
                provider="Google Shopping", rank=1, title="Lavadora",
                description="", price_min=preco, price_max=preco, currency="BRL",
                purchase_url="https://exemplo.com/1", seller=loja,
            )

        ordenado = marcar_preferidas(
            [oferta("Magalu", 500.0), oferta("Mercado Livre", 900.0)],
            ("mercado livre", "shopee"),
        )

        self.assertEqual("Mercado Livre", ordenado[0].seller)
        self.assertTrue(ordenado[0].loja_preferida)
        self.assertFalse(ordenado[1].loja_preferida)

    def test_offer_without_preferred_store_is_untouched(self):
        from copercitrus_price_collector.providers.common import marcar_preferidas
        from copercitrus_price_collector.models import SearchResult

        oferta = SearchResult(
            provider="Buscape", rank=1, title="Lavadora", description="",
            price_min=100.0, price_max=100.0, currency="BRL",
            purchase_url="https://buscape.com.br/1", seller="Magalu",
        )

        self.assertFalse(marcar_preferidas([oferta], ("shopee",))[0].loja_preferida)


class FalhaTotalTest(unittest.TestCase):
    """Bloqueio em todas as consultas e erro, nao mercado vazio."""

    class BrowserQueFalha:
        def __init__(self):
            from copercitrus_price_collector.errors import ProviderError

            self.erro = ProviderError("Google Shopping: bloqueio detectado")
            self.settings = ConfiguracaoFalsa()

        def collect_cards(self, *args, **kwargs):
            raise self.erro

    def test_all_queries_blocked_raises(self):
        from copercitrus_price_collector.errors import ProviderError

        product = ProductInput(4, "Lavadora alta pressao", "Jacto")

        with self.assertRaises(ProviderError):
            BingShoppingProvider(self.BrowserQueFalha()).search(product, 5)

    def test_partial_failure_keeps_what_worked(self):
        class BrowserParcial:
            def __init__(self):
                from copercitrus_price_collector.errors import ProviderError

                self.ProviderError = ProviderError
                self.settings = ConfiguracaoFalsa()
                self.chamadas = 0

            def collect_cards(self, *args, **kwargs):
                self.chamadas += 1
                if self.chamadas == 1:
                    return [CARD]
                raise self.ProviderError("bloqueio")

        product = ProductInput(4, "Lavadora alta pressao", "Jacto")

        ofertas = BingShoppingProvider(BrowserParcial()).search(product, 5)

        self.assertEqual(1, len(ofertas))


class CodigoFabricanteTest(unittest.TestCase):
    """Codigo de cadastro nao aparece em anuncio e nao pode punir o acerto."""

    def test_supplier_code_does_not_lower_the_match(self):
        com_codigo = ProductInput(
            4, "INVERSOR DIG C/MASCARA AUT IM125 VD", "Vonder", "6878125125 VONDER"
        )
        titulo = "Inversor Solda Eletrodo E TIG IM125 Com Mascara Vonder"

        self.assertGreaterEqual(similarity_score(com_codigo, titulo), 60.0)

    def test_model_code_still_counts(self):
        """IM125 e J6600 o anuncio escreve; esses continuam valendo."""
        produto = ProductInput(4, "LAVADORA ALTA PRESSAO J6600", "Jacto")

        com_modelo = similarity_score(produto, "Lavadora Alta Pressao Jacto J6600 220v")
        sem_modelo = similarity_score(produto, "Lavadora Alta Pressao Jacto J7000 220v")

        self.assertGreater(com_modelo, sem_modelo)

    def test_accessory_stays_low_even_without_the_code(self):
        produto = ProductInput(4, "PULVERIZADOR COSTAL PJH", "Jacto", "825398 JACTO")

        self.assertLess(similarity_score(produto, "Filtro Oleo Jacto"), 50.0)


class ConsultaSemDescricaoTest(unittest.TestCase):
    """SKU cuja descricao e so codigo de barras nao identifica produto."""

    def test_barcode_only_query_matches_nothing(self):
        ean = ProductInput(4, "7909439011096", "Jacto", "1350764 JACTO")

        # Sem termo descritivo, qualquer item da marca casaria 100%.
        self.assertEqual(0.0, similarity_score(ean, "Pulverizador Costal Jacto PJH 20L"))
        self.assertEqual(0.0, similarity_score(ean, "Lavadora Alta Pressao Jacto J6000"))

    def test_real_description_still_matches(self):
        produto = ProductInput(4, "LAVADORA ALTA PRESSAO J6600 220V", "Jacto", "1350780 JACTO")

        certo = similarity_score(produto, "Lavadora Alta Pressao Jacto J6600 220v")
        errado = similarity_score(produto, "Pulverizador Costal Jacto PJH")

        self.assertGreater(certo, 60.0)
        self.assertLess(errado, 50.0)
