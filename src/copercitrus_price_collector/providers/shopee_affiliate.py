"""Shopee pela vitrine, com navegador.

Mantida como alternativa: a Shopee bloqueia esse caminho de forma
consistente. Prefira `providers.shopee`, que usa API.

Original:
RPA da busca da Shopee Brasil pela API JSON da propria pagina.

A pesquisa e feita pelo endpoint publico que a propria vitrine consome, a
partir da pagina ja aberta e com a sessao do navegador. E mais estavel do que
raspar HTML — nao existe seletor para quebrar quando o site muda de layout —
e a resposta ja traz faixa de preco e volume de vendas por anuncio.
"""

from __future__ import annotations

from urllib.parse import quote

from ..browser import BrowserRpa
from ..models import ProductInput, SearchResult
from ..product_analysis import (
    classify_match,
    extract_package_quantity,
    identify_brand,
    similarity_score,
)


BASE = "https://shopee.com.br"
IMAGE_BASE = "https://down-br.img.susercontent.com/file/"
# A Shopee representa dinheiro em centavos de micro: R$ 1,00 chega como 100000.
PRICE_SCALE = 100_000


def _money(value: object) -> float | None:
    try:
        amount = float(value) / PRICE_SCALE
    except (TypeError, ValueError):
        return None
    return round(amount, 2) if amount > 0 else None


def _rating(item: dict) -> tuple[float | None, int | None]:
    rating = item.get("item_rating") or {}
    try:
        stars = round(float(rating.get("rating_star") or 0), 2) or None
    except (TypeError, ValueError):
        stars = None
    counts = rating.get("rating_count")
    if isinstance(counts, list) and counts:
        total = counts[0]
    else:
        total = counts
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    return stars, total


class ShopeeWebProvider:
    name = "Shopee"

    def __init__(self, browser: BrowserRpa) -> None:
        self.browser = browser

    def _search_path(self, keyword: str, limit: int) -> str:
        return (
            "/api/v4/search/search_items"
            f"?by=relevancy&keyword={quote(keyword)}&limit={limit}"
            "&newest=0&order=desc&page_type=search"
            "&scenario=PAGE_GLOBAL_SEARCH&version=2"
        )

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        keyword = product.query
        body = self.browser.fetch_json(
            self.name,
            f"{BASE}/search?keyword={quote(keyword)}",
            self._search_path(keyword, limit),
        )
        items = body.get("items") or []
        results: list[SearchResult] = []
        for rank, entry in enumerate(items[:limit], 1):
            item = entry.get("item_basic") or entry
            if not isinstance(item, dict):
                continue
            title = (item.get("name") or "").strip()
            if not title:
                continue
            results.append(self._map(product, item, title, rank))
        return results

    def _map(
        self, product: ProductInput, item: dict, title: str, rank: int
    ) -> SearchResult:
        price = _money(item.get("price"))
        price_min = _money(item.get("price_min")) or price
        price_max = _money(item.get("price_max")) or price
        stars, reviews = _rating(item)
        item_id = item.get("itemid")
        shop_id = item.get("shopid")
        images = item.get("images") or []
        score = similarity_score(product, title)
        sold = item.get("historical_sold") or item.get("sold")
        return SearchResult(
            provider=self.name,
            rank=rank,
            title=title,
            description=title,
            price_min=price_min,
            price_max=price_max,
            currency="BRL",
            purchase_url=f"{BASE}/product/{shop_id}/{item_id}",
            brand=identify_brand(title, product.marca),
            package_quantity=extract_package_quantity(title),
            similarity_score=score,
            match_type=classify_match(score),
            seller=item.get("shop_location"),
            rating=stars,
            review_count=reviews,
            sold_count=int(sold) if isinstance(sold, (int, float)) else None,
            image_url=f"{IMAGE_BASE}{images[0]}" if images else None,
        )
