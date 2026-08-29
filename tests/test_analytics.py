import unittest
from datetime import datetime, timezone

from copercitrus_price_collector.analytics import (
    build_price_statistics,
    build_store_prices,
    describe_prices,
)
from copercitrus_price_collector.models import CollectionRow, ProductInput, SearchResult


def _offer(product, provider, price, seller, match_type="COMPATIVEL"):
    return CollectionRow(
        product=product,
        provider=provider,
        status="OK",
        collected_at=datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc),
        result=SearchResult(
            provider=provider,
            rank=1,
            title=product.produto,
            description="",
            price_min=price,
            price_max=price,
            currency="BRL",
            purchase_url=f"https://loja.example/{price}",
            match_type=match_type,
            similarity_score=90.0,
            seller=seller,
        ),
    )


class DescribePricesTest(unittest.TestCase):
    def test_quartiles_and_dispersion(self):
        resumo = describe_prices([100, 200, 300, 400])

        self.assertEqual(4, resumo["n_ofertas"])
        self.assertEqual(100.0, resumo["menor_preco"])
        self.assertEqual(400.0, resumo["maior_preco"])
        self.assertEqual(250.0, resumo["mediana"])
        self.assertEqual(175.0, resumo["p25"])
        self.assertEqual(325.0, resumo["p75"])
        self.assertEqual(150.0, resumo["amplitude_interquartil"])

    def test_flags_price_far_from_the_pack(self):
        """Uma oferta muito fora da faixa precisa aparecer como outlier."""
        resumo = describe_prices([100, 105, 110, 115, 900])

        self.assertEqual(1, resumo["outliers_alto"])
        self.assertEqual(0, resumo["outliers_baixo"])
        self.assertGreater(resumo["coeficiente_variacao"], 100)

    def test_tight_market_has_low_variation(self):
        resumo = describe_prices([1000, 1010, 1020])

        self.assertLess(resumo["coeficiente_variacao"], 2)
        self.assertEqual(0, resumo["outliers_alto"])

    def test_single_price_has_no_dispersion(self):
        resumo = describe_prices([500])

        self.assertEqual(0.0, resumo["desvio_padrao"])
        self.assertEqual(500.0, resumo["mediana"])

    def test_empty_sample_returns_nothing(self):
        self.assertIsNone(describe_prices([]))
        self.assertIsNone(describe_prices([None, None]))


class PriceStatisticsTest(unittest.TestCase):
    def setUp(self):
        self.product = ProductInput(4, "Lavadora J6600", "Jacto", None, "SKU-1")
        self.rows = [
            _offer(self.product, "Google Shopping", 1000.0, "Shopee"),
            _offer(self.product, "Google Shopping", 1200.0, "Mercado Livre"),
            _offer(self.product, "Buscape", 1100.0, "Shopee"),
            _offer(self.product, "Bing Shopping", 40.0, "Loja Y", "DIVERGENTE"),
        ]

    def test_statistics_ignore_divergent_offers(self):
        estatistica = build_price_statistics(self.rows)[0]

        self.assertEqual(3, estatistica["n_ofertas"])
        self.assertEqual(1000.0, estatistica["menor_preco"])
        self.assertEqual(1100.0, estatistica["mediana"])
        self.assertEqual(2, estatistica["n_lojas"])
        self.assertEqual(2, estatistica["n_fontes"])

    def test_product_without_price_is_skipped(self):
        produto = ProductInput(5, "Sem oferta", None, None, "SKU-2")
        vazio = CollectionRow(
            product=produto,
            provider="Google Shopping",
            status="SEM_RESULTADO",
            collected_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )

        self.assertEqual([], build_price_statistics([vazio]))


class StorePricesTest(unittest.TestCase):
    def setUp(self):
        self.product = ProductInput(4, "Lavadora J6600", "Jacto", None, "SKU-1")
        self.rows = [
            _offer(self.product, "Google Shopping", 900.0, "Shopee"),
            _offer(self.product, "Google Shopping", 1100.0, "Shopee"),
            _offer(self.product, "Buscape", 1000.0, "Mercado Livre"),
        ]

    def test_groups_by_store_and_compares_to_the_median(self):
        linhas = {linha["loja"]: linha for linha in build_store_prices(self.rows)}

        shopee = linhas["Shopee"]
        self.assertEqual(2, shopee["ofertas"])
        self.assertEqual(900.0, shopee["menor_preco"])
        self.assertEqual(1100.0, shopee["maior_preco"])
        # Mediana da amostra e 1000; a Shopee entra 10% abaixo.
        self.assertEqual(-10.0, shopee["variacao_vs_mediana_pct"])
        self.assertEqual(0.0, linhas["Mercado Livre"]["variacao_vs_mediana_pct"])

    def test_offer_without_store_is_labelled(self):
        rows = [_offer(self.product, "Google Shopping", 500.0, None)]

        self.assertEqual("Loja nao informada", build_store_prices(rows)[0]["loja"])


if __name__ == "__main__":
    unittest.main()


class ModoExatoTest(unittest.TestCase):
    """Comparar preco do mesmo item exige descartar o parecido."""

    def _servico(self, resultados, **kwargs):
        from copercitrus_price_collector.service import CollectionService

        class ProvedorFalso:
            name = "Google Shopping"

            def search(self, produto, limite):
                return resultados

        return CollectionService([ProvedorFalso()], 5, 0.0, **kwargs)

    def _oferta(self, score):
        return SearchResult(
            provider="Google Shopping", rank=1, title="Lavadora", description="",
            price_min=900.0, price_max=900.0, currency="BRL",
            purchase_url="https://exemplo.com/1", similarity_score=score,
            match_type="COMPATIVEL" if score >= 80 else "SIMILAR",
        )

    def test_keeps_only_the_requested_product(self):
        produto = ProductInput(4, "Lavadora J6600", "Jacto", None, "SKU-1")
        servico = self._servico(
            [self._oferta(92.0), self._oferta(61.0)], somente_exatos=True
        )

        linhas = servico.collect([produto])

        self.assertEqual(1, len(linhas))
        self.assertEqual(92.0, linhas[0].result.similarity_score)

    def test_similar_offers_kept_when_asked(self):
        produto = ProductInput(4, "Lavadora J6600", "Jacto", None, "SKU-1")
        servico = self._servico(
            [self._oferta(92.0), self._oferta(61.0)], somente_exatos=False
        )

        self.assertEqual(2, len(servico.collect([produto])))

    def test_product_without_exact_match_is_recorded_as_empty(self):
        produto = ProductInput(4, "Lavadora J6600", "Jacto", None, "SKU-1")
        servico = self._servico([self._oferta(40.0)], somente_exatos=True)

        linhas = servico.collect([produto])

        self.assertEqual("SEM_RESULTADO", linhas[0].status)

    def test_threshold_is_configurable(self):
        produto = ProductInput(4, "Lavadora J6600", "Jacto", None, "SKU-1")
        servico = self._servico(
            [self._oferta(65.0)], somente_exatos=True, similaridade_minima=60.0
        )

        self.assertEqual("OK", servico.collect([produto])[0].status)
