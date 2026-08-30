"""Mapeamento compartilhado dos cards visiveis para o modelo de saida."""

from __future__ import annotations

from ..browser import BrowserProductCard, BrowserRpa
from dataclasses import replace

from ..errors import ProviderError
from ..models import ProductInput, SearchResult
from ..product_analysis import (
    classify_match,
    normalize_text,
    extract_package_quantity,
    extract_seller,
    identificar_marketplace,
    normalizar_loja,
    identify_brand,
    parse_price,
    similarity_score,
)


def map_card(
    provider_name: str,
    product: ProductInput,
    card: BrowserProductCard,
    rank: int,
) -> SearchResult:
    score = similarity_score(product, card.title)
    combined_text = " | ".join(
        value for value in (card.title, card.description, card.raw_text) if value
    )
    price = parse_price(card.price_text)
    return SearchResult(
        provider=provider_name,
        rank=rank,
        title=card.title,
        description=card.description or card.title,
        price_min=price,
        price_max=price,
        currency="BRL",
        purchase_url=card.purchase_url,
        brand=identify_brand(card.title, product.marca),
        package_quantity=extract_package_quantity(combined_text),
        similarity_score=score,
        match_type=classify_match(score),
        # Marketplace pelo dominio primeiro: e o dado confiavel. O texto do
        # card vem depois, e so quando nao for promocao disfarcada de loja.
        seller=normalizar_loja(
            identificar_marketplace(card.purchase_url)
            or card.seller
            or extract_seller(card.raw_text)
        ),
        image_url=card.image_url,
    )


def marcar_preferidas(
    resultados: list[SearchResult], preferidas: tuple[str, ...]
) -> list[SearchResult]:
    """Marca ofertas dos marketplaces priorizados e as coloca na frente."""
    if not preferidas:
        return resultados
    alvos = [normalize_text(nome) for nome in preferidas if nome]
    marcados: list[SearchResult] = []
    for item in resultados:
        texto = normalize_text(f"{item.seller or ''} {item.purchase_url}")
        preferida = any(alvo and alvo in texto for alvo in alvos)
        marcados.append(replace(item, loja_preferida=preferida) if preferida else item)
    # Preferida primeiro, e dentro de cada grupo o mais barato antes.
    return sorted(
        marcados,
        key=lambda item: (
            not item.loja_preferida,
            item.price_min if item.price_min is not None else float("inf"),
        ),
    )


def buscar_em_lojas_preferidas(
    browser: BrowserRpa,
    provider_name: str,
    montar_url,
    selectors,
    product: ProductInput,
    limit: int,
) -> list[SearchResult]:
    """Consulta a busca geral e depois cada marketplace priorizado.

    A consulta extra por loja existe porque a busca geral traz o que o
    buscador julga relevante, e nao necessariamente o que a CoperCitrus quer
    acompanhar. Perguntar pela loja diretamente e o que garante a cobertura.
    """
    preferidas = getattr(browser.settings, "lojas_preferidas", ())
    consultas = [product.query] + [
        f"{loja} {product.query}" for loja in preferidas
    ]
    vistos: set[str] = set()
    resultados: list[SearchResult] = []
    falhas: list[ProviderError] = []
    for consulta in consultas:
        try:
            cards = browser.collect_cards(
                provider_name, montar_url(consulta), selectors, limit
            )
        except ProviderError as exc:
            # Uma loja sem resultado nao pode derrubar as demais consultas,
            # mas se todas falharem isso e erro, nao ausencia de oferta:
            # engolir silenciosamente faz bloqueio parecer mercado vazio.
            falhas.append(exc)
            continue
        for card in cards:
            chave = f"{normalize_text(card.title)}|{card.price_text}"
            if chave in vistos:
                continue
            vistos.add(chave)
            resultados.append(map_card(provider_name, product, card, len(resultados) + 1))
    if not resultados and len(falhas) == len(consultas):
        raise falhas[0]
    return marcar_preferidas(resultados, preferidas)
