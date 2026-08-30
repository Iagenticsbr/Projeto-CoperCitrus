"""Shopee pela API da Apify.

Substitui a raspagem da vitrine, que a Shopee recusa de forma consistente:
verificacao que falha mesmo respondida corretamente, exigencia de login e
bloqueio por IP. A API entrega o mesmo dado sem nada disso, e roda em
servidor sem tela.

Os valores chegam em centavos: 89408 significa R$ 894,08.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..errors import ConfigurationError, ProviderError
from ..models import ProductInput, SearchResult
from ..product_analysis import (
    classify_match,
    extract_package_quantity,
    identify_brand,
    similarity_score,
)


ATOR = "cZrxaxPbcqHwGwSlm"
ENDPOINT = f"https://api.apify.com/v2/acts/{ATOR}/run-sync-get-dataset-items"
TEMPO_LIMITE_SEGUNDOS = 420
CENTAVOS = 100
# Piso de plausibilidade. O coletor devolve `price` igual a 1 ou 2 centavos em
# alguns anuncios, com titulo que nem corresponde ao link — e artefato de
# leitura, nao promocao. Uma oferta de R$ 0,01 destruiria o menor preco do
# painel, entao ela e descartada e registrada.
PRECO_MINIMO = 1.0


def _preco(valor: object) -> float | None:
    try:
        numero = float(valor) / CENTAVOS
    except (TypeError, ValueError):
        return None
    return round(numero, 2) if numero > 0 else None


def _inteiro(valor: object) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


class ShopeeProvider:
    name = "Shopee"
    requires_browser = False

    def __init__(self, browser) -> None:
        self.settings = getattr(browser, "settings", browser)

    def _consultar(self, keyword: str, maximo: int) -> list[dict]:
        token = getattr(self.settings, "apify_token", None)
        if not token:
            raise ConfigurationError("Defina APIFY_TOKEN para coletar da Shopee")
        corpo = json.dumps(
            {
                "country": "br",
                "delay": 1,
                "fetchDetail": False,
                "keyword": keyword,
                "maxProducts": maximo,
                "mode": "keyword",
                "sort": "relevancy",
            }
        ).encode("utf-8")
        requisicao = urllib.request.Request(
            f"{ENDPOINT}?token={token}",
            data=corpo,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                requisicao, timeout=TEMPO_LIMITE_SEGUNDOS
            ) as resposta:
                dados = json.loads(resposta.read())
        except urllib.error.HTTPError as exc:
            detalhe = exc.read().decode("utf-8", "replace")[:200]
            raise ProviderError(
                f"{self.name}: a API respondeu {exc.code} ({detalhe})"
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"{self.name}: nao foi possivel alcancar a API ({exc.reason})"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.name}: resposta nao e JSON") from exc
        return dados if isinstance(dados, list) else []

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        itens = self._consultar(product.query, limit)
        resultados: list[SearchResult] = []
        vistos: set[str] = set()
        for item in itens:
            if not isinstance(item, dict):
                continue
            titulo = (item.get("name") or "").strip()
            preco = _preco(item.get("price"))
            if not titulo or preco is None:
                continue
            if preco < PRECO_MINIMO:
                print(
                    f"        preco implausivel descartado: R$ {preco:.2f} "
                    f"em {titulo[:40]}",
                    flush=True,
                )
                continue
            chave = str(item.get("item_id") or f"{titulo}|{preco}")
            if chave in vistos:
                continue
            vistos.add(chave)
            resultados.append(
                self._mapear(product, item, titulo, preco, len(resultados) + 1)
            )
            if len(resultados) >= limit:
                break
        return resultados

    def _mapear(
        self, product: ProductInput, item: dict, titulo: str, preco: float, rank: int
    ) -> SearchResult:
        pontuacao = similarity_score(product, titulo)
        cheio = _preco(item.get("original_price"))
        return SearchResult(
            provider=self.name,
            rank=rank,
            title=titulo,
            description="Shopee Mall" if item.get("is_mall") else titulo,
            price_min=preco,
            price_max=cheio if cheio and cheio > preco else preco,
            currency=item.get("currency") or "BRL",
            purchase_url=item.get("url") or "",
            brand=identify_brand(titulo, product.marca),
            package_quantity=extract_package_quantity(titulo),
            similarity_score=pontuacao,
            match_type=classify_match(pontuacao),
            seller=self.name,
            rating=item.get("rating") if isinstance(item.get("rating"), (int, float)) else None,
            review_count=_inteiro(item.get("rating_count")),
            sold_count=_inteiro(item.get("sold_count")),
            image_url=item.get("image_url") or None,
            loja_preferida=True,
        )
