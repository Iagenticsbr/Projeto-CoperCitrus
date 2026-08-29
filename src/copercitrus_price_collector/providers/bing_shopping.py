"""RPA da pagina publica do Bing Shopping (mercado brasileiro).

Agrega ofertas de varias lojas, incluindo as mesmas que aparecem no Google
Shopping, e expoe a loja vendedora em cada card.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ..browser import BrowserRpa, SiteSelectors
from ..models import ProductInput, SearchResult
from .common import buscar_em_lojas_preferidas


BING_SELECTORS = SiteSelectors(
    cards=(
        ".br-offCard",
        ".br-narrowOffCard",
        ".br-infOffCard",
        "div[class*='br-offCard']",
    ),
    titles=(".br-offTtl", ".br-offTtl span", "h2"),
    prices=(".br-price", ".br-offPrice", "div[class*='br-price']"),
    links=("a[href]",),
    descriptions=(".br-offSecLbl",),
    sellers=(".br-offSlrTxt", ".br-offSlr"),
    title_attributes=(".br-offTtl span[title]", ".br-offTtl[title]"),
)


class BingShoppingProvider:
    name = "Bing Shopping"
    endpoint = "https://www.bing.com/shop"

    def __init__(self, browser: BrowserRpa) -> None:
        self.browser = browser

    def _url(self, consulta: str) -> str:
        params = {"q": consulta, "cc": "br", "setlang": "pt-BR"}
        return f"{self.endpoint}?{urlencode(params)}"

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        return buscar_em_lojas_preferidas(
            self.browser, self.name, self._url, BING_SELECTORS, product, limit
        )
