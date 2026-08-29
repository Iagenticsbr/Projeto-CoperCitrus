"""RPA das paginas publicas dos comparadores de preco Buscape e Zoom.

Buscape e Zoom usam o mesmo componente de card, entao compartilham os
seletores. Sao comparadores: cada card ja representa a melhor oferta
consolidada entre varias lojas para aquele anuncio.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ..browser import BrowserRpa, SiteSelectors
from ..models import ProductInput, SearchResult
from .common import map_card


COMPARADOR_SELECTORS = SiteSelectors(
    cards=(
        "[data-testid='product-card']",
        "[data-testid='product-card::card']",
        "div[class*='Hits_ProductCard']",
    ),
    titles=(
        "[data-testid='product-card::name']",
        "h2",
        "div[class*='OrqProductCard_Name']",
    ),
    prices=(
        "[data-testid='product-card::price']",
        "div[class*='OrqProductCard_Price']",
        "[aria-label='Preço']",
    ),
    links=("a[href]",),
    descriptions=("[data-testid='product-card::conditions']",),
    sellers=("[data-testid='product-card::seller']", "div[class*='Seller']"),
)


class _ComparadorProvider:
    name = ""
    endpoint = ""

    def __init__(self, browser: BrowserRpa) -> None:
        self.browser = browser

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        cards = self.browser.collect_cards(
            self.name,
            f"{self.endpoint}?{urlencode({'q': product.query})}",
            COMPARADOR_SELECTORS,
            limit,
        )
        return [
            map_card(self.name, product, card, index)
            for index, card in enumerate(cards, 1)
        ]


class BuscapeProvider(_ComparadorProvider):
    name = "Buscape"
    endpoint = "https://www.buscape.com.br/search"


class ZoomProvider(_ComparadorProvider):
    name = "Zoom"
    endpoint = "https://www.zoom.com.br/search"
