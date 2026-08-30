"""Mercado Livre pela API da Apify.

Diferente das outras fontes, esta nao abre navegador: e uma chamada HTTP que
devolve JSON. Isso muda o que o sistema consegue fazer — roda em servidor sem
tela, sem verificacao humana, e nao quebra quando o site muda de layout.

A resposta traz preco atual, preco anterior, desconto, vendedor, quantidade
vendida e avaliacao, campos que a raspagem de card nao entregava.
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


ENDPOINT = (
    "https://api.apify.com/v2/acts/"
    "karamelo~mercadolivre-scraper-brasil-portugues/run-sync-get-dataset-items"
)
TEMPO_LIMITE_SEGUNDOS = 300


def _preco(valor: object) -> float | None:
    """Converte "1.659,99" no numero correspondente."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = float(texto)
    except ValueError:
        return None
    return round(numero, 2) if numero > 0 else None


def _inteiro(valor: object) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _decimal(valor: object) -> float | None:
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


class MercadoLivreProvider:
    name = "Mercado Livre"
    # Nao precisa de navegador: quem chama pode pular o Chromium inteiro.
    requires_browser = False

    def __init__(self, browser) -> None:
        # Recebe o mesmo objeto das outras fontes so para manter a interface;
        # daqui so sai a configuracao.
        self.settings = getattr(browser, "settings", browser)

    def _consultar(self, keyword: str, paginas: int) -> list[dict]:
        token = getattr(self.settings, "apify_token", None)
        if not token:
            raise ConfigurationError(
                "Defina APIFY_TOKEN para coletar do Mercado Livre"
            )
        corpo = json.dumps(
            {
                "keyword": keyword,
                "maxPages": paginas,
                "maxPagesOfertas": 1,
                "promoted": False,
                "scrapeOfertas": False,
                "sort": "relevance",
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
        itens = self._consultar(product.query, paginas=1)
        resultados: list[SearchResult] = []
        vistos: set[str] = set()
        for item in itens:
            if not isinstance(item, dict):
                continue
            titulo = (item.get("eTituloProduto") or "").strip()
            preco = _preco(item.get("novoPreco"))
            if not titulo or preco is None:
                continue
            chave = item.get("idPublicacao") or f"{titulo}|{preco}"
            if chave in vistos:
                continue
            vistos.add(chave)
            resultados.append(self._mapear(product, item, titulo, preco, len(resultados) + 1))
            if len(resultados) >= limit:
                break
        return resultados

    def _mapear(
        self, product: ProductInput, item: dict, titulo: str, preco: float, rank: int
    ) -> SearchResult:
        anterior = _preco(item.get("precoAnterior"))
        vendedor = (item.get("Vendedor") or "").strip() or None
        return SearchResult(
            provider=self.name,
            rank=rank,
            title=titulo,
            description=item.get("promocoes") or titulo,
            price_min=preco,
            # Quando ha preco anterior, a faixa real do anuncio vai do preco
            # promocional ao preco cheio.
            price_max=anterior if anterior and anterior > preco else preco,
            currency=item.get("Moeda") or "BRL",
            purchase_url=item.get("zProdutoLink") or "",
            brand=identify_brand(titulo, product.marca) or (item.get("produtoMarca") or None),
            package_quantity=extract_package_quantity(titulo),
            similarity_score=similarity_score(product, titulo),
            match_type=classify_match(similarity_score(product, titulo)),
            seller=f"Mercado Livre ({vendedor})" if vendedor else self.name,
            rating=_decimal(item.get("produtoReviews")),
            review_count=_inteiro(item.get("numeroAvaliacoes")),
            sold_count=_inteiro(item.get("quantidadeVendida")),
            image_url=item.get("imagemLink") or None,
            loja_preferida=True,
        )
