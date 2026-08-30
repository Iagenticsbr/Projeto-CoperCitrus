import unittest

from copercitrus_price_collector.errors import ConfigurationError
from copercitrus_price_collector.models import ProductInput
from copercitrus_price_collector.providers.mercadolivre import (
    MercadoLivreProvider,
    _preco,
)


class ConfiguracaoFalsa:
    apify_token = "token-de-teste"
    lojas_preferidas = ("mercado livre", "shopee")


class BrowserFalso:
    def __init__(self, settings=None):
        self.settings = settings or ConfiguracaoFalsa()


# Resposta reduzida no formato que o ator devolve.
ITENS = [
    {
        "eTituloProduto": "Lavadora De Alta Pressao Jactoclean J6600 1950psi 1400w",
        "novoPreco": "988,43",
        "precoAnterior": "1.659,99",
        "precoDiscount": "40% OFF",
        "Moeda": "BRL",
        "Vendedor": "JACTO",
        "quantidadeVendida": 50,
        "produtoReviews": "4.9",
        "numeroAvaliacoes": 10,
        "idPublicacao": "MLB4520643983",
        "zProdutoLink": "https://www.mercadolivre.com.br/lavadora/p/MLB65463481",
        "imagemLink": "https://http2.mlstatic.com/imagem.webp",
    },
    {
        "eTituloProduto": "",
        "novoPreco": "100,00",
        "idPublicacao": "MLB999",
    },
    {
        "eTituloProduto": "Sem preco",
        "novoPreco": "",
        "idPublicacao": "MLB888",
    },
]


def _provider(itens=None):
    provider = MercadoLivreProvider(BrowserFalso())
    provider._consultar = lambda keyword, paginas: (
        ITENS if itens is None else itens
    )
    return provider


class PrecoTest(unittest.TestCase):
    def test_reads_brazilian_format(self):
        self.assertEqual(1659.99, _preco("1.659,99"))
        self.assertEqual(988.43, _preco("988,43"))

    def test_empty_and_invalid_are_none(self):
        self.assertIsNone(_preco(""))
        self.assertIsNone(_preco(None))
        self.assertIsNone(_preco("gratis"))
        self.assertIsNone(_preco("0"))


class MercadoLivreProviderTest(unittest.TestCase):
    def setUp(self):
        self.product = ProductInput(
            4, "LAVADORA ALTA PRESSAO J6600 220V", "Jacto", None, "1271265"
        )

    def test_maps_price_and_previous_price_as_range(self):
        ofertas = _provider().search(self.product, 5)

        self.assertEqual(1, len(ofertas))
        oferta = ofertas[0]
        self.assertEqual(988.43, oferta.price_min)
        # Preco anterior vira o teto da faixa do proprio anuncio.
        self.assertEqual(1659.99, oferta.price_max)
        self.assertEqual("BRL", oferta.currency)
        self.assertEqual(50, oferta.sold_count)
        self.assertEqual(4.9, oferta.rating)
        self.assertEqual(10, oferta.review_count)

    def test_offer_is_always_flagged_as_preferred_store(self):
        self.assertTrue(_provider().search(self.product, 5)[0].loja_preferida)

    def test_seller_keeps_the_marketplace_and_the_store(self):
        self.assertEqual(
            "Mercado Livre (JACTO)", _provider().search(self.product, 5)[0].seller
        )

    def test_entries_without_title_or_price_are_skipped(self):
        self.assertEqual(1, len(_provider().search(self.product, 5)))

    def test_respects_the_limit(self):
        muitos = [dict(ITENS[0], idPublicacao=f"MLB{i}") for i in range(9)]

        self.assertEqual(3, len(_provider(muitos).search(self.product, 3)))

    def test_duplicate_listing_id_enters_once(self):
        repetidos = [ITENS[0], dict(ITENS[0])]

        self.assertEqual(1, len(_provider(repetidos).search(self.product, 5)))

    def test_missing_token_is_reported(self):
        class SemToken:
            apify_token = None

        provider = MercadoLivreProvider(BrowserFalso(SemToken()))

        with self.assertRaises(ConfigurationError):
            provider.search(self.product, 5)

    def test_does_not_need_a_browser(self):
        """A fonte e HTTP; quem chama pode pular o Chromium."""
        self.assertFalse(MercadoLivreProvider.requires_browser)


if __name__ == "__main__":
    unittest.main()


class ShopeeApiTest(unittest.TestCase):
    """Os valores da Shopee chegam em centavos."""

    def setUp(self):
        from copercitrus_price_collector.providers.shopee import ShopeeProvider

        self.product = ProductInput(4, "LAVADORA ALTA PRESSAO J6600", "Jacto")
        self.itens = [
            {
                "item_id": 58206718499,
                "name": "Lavadora De Alta Pressao Jacto J6600 1600w 127v",
                "price": 89408,
                "original_price": 146900,
                "rating": 4.7,
                "rating_count": 12,
                "sold_count": 30,
                "currency": "BRL",
                "is_mall": False,
                "url": "https://shopee.com.br/produto-i.979559296.58206718499",
                "image_url": "https://down-br.img.susercontent.com/file/abc",
            }
        ]
        self.provider = ShopeeProvider(BrowserFalso())
        self.provider._consultar = lambda keyword, maximo: self.itens

    def test_converts_cents_to_reais(self):
        oferta = self.provider.search(self.product, 5)[0]

        self.assertEqual(894.08, oferta.price_min)
        self.assertEqual(1469.0, oferta.price_max)

    def test_offer_is_flagged_as_preferred_store(self):
        self.assertTrue(self.provider.search(self.product, 5)[0].loja_preferida)

    def test_mall_listing_is_named(self):
        self.itens[0]["is_mall"] = True

        self.assertEqual("Shopee Mall", self.provider.search(self.product, 5)[0].seller)

    def test_entry_without_price_is_skipped(self):
        self.itens.append({"item_id": 1, "name": "Sem preco", "price": 0})

        self.assertEqual(1, len(self.provider.search(self.product, 5)))

    def test_implausible_price_is_discarded(self):
        """price 1 ou 2 centavos e artefato do coletor, nao promocao."""
        self.itens.append(
            {"item_id": 2, "name": "Lavadora Alta Pressao J6000", "price": 1}
        )
        self.itens.append(
            {"item_id": 3, "name": "Lavadora Alta Pressao J5000", "price": 2}
        )

        ofertas = self.provider.search(self.product, 5)

        self.assertEqual(1, len(ofertas))
        self.assertEqual(894.08, ofertas[0].price_min)
