"""Estatistica de preco por produto e por loja.

Menor e maior preco respondem "quanto custa"; nao respondem "esse preco e
normal". Mediana, quartis e dispersao respondem — e sao o que sustenta uma
decisao de compra ou de precificacao.
"""

from __future__ import annotations

from statistics import mean, median, pstdev
from typing import Iterable, Sequence

from .models import CollectionRow


# Fator classico do criterio de Tukey para separar outlier do resto.
IQR_FACTOR = 1.5


def _quantile(ordered: Sequence[float], fraction: float) -> float:
    """Quantil por interpolacao linear entre os vizinhos."""
    if not ordered:
        raise ValueError("amostra vazia")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def describe_prices(prices: Iterable[float]) -> dict | None:
    """Resumo estatistico de uma amostra de precos.

    `coeficiente_variacao` e o desvio padrao como percentual da media: e o
    numero que diz se a faixa esta apertada (mercado consolidado) ou larga
    (produto mal identificado, ou oportunidade de compra).
    """
    sample = sorted(float(price) for price in prices if price is not None)
    if not sample:
        return None

    p25 = _quantile(sample, 0.25)
    p50 = median(sample)
    p75 = _quantile(sample, 0.75)
    iqr = p75 - p25
    average = mean(sample)
    deviation = pstdev(sample) if len(sample) > 1 else 0.0
    lower_fence = p25 - IQR_FACTOR * iqr
    upper_fence = p75 + IQR_FACTOR * iqr

    return {
        "n_ofertas": len(sample),
        "menor_preco": round(sample[0], 2),
        "p25": round(p25, 2),
        "mediana": round(p50, 2),
        "p75": round(p75, 2),
        "maior_preco": round(sample[-1], 2),
        "preco_medio": round(average, 2),
        "desvio_padrao": round(deviation, 2),
        "coeficiente_variacao": (
            round(deviation / average * 100, 2) if average else None
        ),
        "amplitude_interquartil": round(iqr, 2),
        "limite_inferior": round(lower_fence, 2),
        "limite_superior": round(upper_fence, 2),
        "outliers_baixo": sum(1 for price in sample if price < lower_fence),
        "outliers_alto": sum(1 for price in sample if price > upper_fence),
    }


def _priced_offers(rows: Iterable[CollectionRow], relevant_only: bool) -> list[CollectionRow]:
    from .database import RELEVANT_MATCHES

    offers = [
        row
        for row in rows
        if row.result is not None and row.result.price_min is not None
    ]
    if not relevant_only:
        return offers
    relevant = [row for row in offers if row.result.match_type in RELEVANT_MATCHES]
    return relevant or offers


def build_price_statistics(rows: Iterable[CollectionRow]) -> list[dict]:
    """Uma linha de estatistica por produto solicitado."""
    grouped: dict[tuple[str | None, str], list[CollectionRow]] = {}
    for row in rows:
        grouped.setdefault((row.product.sku, row.product.produto), []).append(row)

    statistics: list[dict] = []
    for (sku, produto), product_rows in grouped.items():
        offers = _priced_offers(product_rows, relevant_only=True)
        if not offers:
            continue
        summary = describe_prices(row.result.price_min for row in offers)
        if summary is None:
            continue
        lojas = {row.result.seller for row in offers if row.result.seller}
        fontes = {row.provider for row in offers}
        statistics.append(
            {
                "sku": sku,
                "produto": produto,
                "n_lojas": len(lojas),
                "n_fontes": len(fontes),
                "lojas": ", ".join(sorted(lojas)),
                **summary,
            }
        )
    return statistics


def build_store_prices(rows: Iterable[CollectionRow]) -> list[dict]:
    """Preco por loja e por produto, com posicao em relacao a mediana.

    `variacao_vs_mediana_pct` negativo significa loja abaixo do mercado.
    """
    grouped: dict[tuple[str | None, str], list[CollectionRow]] = {}
    for row in rows:
        grouped.setdefault((row.product.sku, row.product.produto), []).append(row)

    lines: list[dict] = []
    for (sku, produto), product_rows in grouped.items():
        offers = _priced_offers(product_rows, relevant_only=True)
        if not offers:
            continue
        reference = median(sorted(row.result.price_min for row in offers))
        by_store: dict[str, list[CollectionRow]] = {}
        for row in offers:
            by_store.setdefault(row.result.seller or "Loja nao informada", []).append(row)

        for loja, store_rows in sorted(by_store.items()):
            prices = sorted(row.result.price_min for row in store_rows)
            cheapest = min(store_rows, key=lambda row: row.result.price_min)
            lines.append(
                {
                    "sku": sku,
                    "produto": produto,
                    "loja": loja,
                    "fonte": cheapest.provider,
                    "ofertas": len(prices),
                    "menor_preco": round(prices[0], 2),
                    "maior_preco": round(prices[-1], 2),
                    "preco_medio": round(mean(prices), 2),
                    "variacao_vs_mediana_pct": (
                        round((prices[0] - reference) / reference * 100, 2)
                        if reference
                        else None
                    ),
                    "url": cheapest.result.purchase_url,
                }
            )
    return lines
