"""RPA da pagina publica de resultados do Google Shopping."""

from __future__ import annotations

from urllib.parse import urlencode

from ..browser import BrowserRpa, SiteSelectors
from ..models import ProductInput, SearchResult
from .common import buscar_em_lojas_preferidas


GOOGLE_SELECTORS = SiteSelectors(
    cards=(
        "[data-docid]",
        ".sh-dgr__content",
        ".sh-dlr__list-result",
        ".pla-unit",
        "div[role='listitem']",
        "div[aria-label*='resultado']",
        "div[aria-label*='product']",
        "div[role='article']",
    ),
    titles=(
        "h3",
        "h2",
        ".tAxDx",
        ".sh-np__product-title",
        "[role='heading']",
        "div[role='heading']",
    ),
    prices=(
        ".a8Pemb",
        ".kHxwFf",
        ".T14wmb",
        ".HRLxBb",
        "[aria-label*='R$']",
        "span[aria-label*='R$']",
        "div[data-price]",
    ),
    # Ordem importa: o primeiro seletor que casar vira o link de compra.
    # O link organico da pagina do produto vem antes do anuncio, porque o
    # destino do `aclk` so existe apos o clique — e clique em anuncio cobra
    # o anunciante, entao o RPA nao segue esse redirecionamento.
    links=(
        "a[href*='/shopping/product/']",
        "a[href*='/products/']",
        "a[href*='/url?']",
        "a[href]",
    ),
    descriptions=(".vEjMR", ".sh-np__product-title", ".hP4iBf", ".b5YqMe"),
    sellers=(".aULzUe", ".IuHnof", ".sh-np__seller-container", "div[aria-label*='loja']"),
)


class GoogleShoppingProvider:
    name = "Google Shopping"
    endpoint = "https://www.google.com/search"

    def __init__(self, browser: BrowserRpa) -> None:
        self.browser = browser

    def _url(self, consulta: str) -> str:
        params = {"tbm": "shop", "hl": "pt-BR", "gl": "br", "q": consulta}
        return f"{self.endpoint}?{urlencode(params)}"

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        return buscar_em_lojas_preferidas(
            self.browser, self.name, self._url, GOOGLE_SELECTORS, product, limit
        )
