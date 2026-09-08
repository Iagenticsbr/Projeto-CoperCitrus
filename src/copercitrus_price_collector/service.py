"""Price collection orchestration."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Iterable

from .errors import ProviderError
from .models import CollectionRow, ProductInput
from .providers.base import PriceProvider


class CollectionService:
    def __init__(
        self,
        providers: Iterable[PriceProvider],
        result_limit: int,
        request_delay_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
        somente_exatos: bool = False,
        similaridade_minima: float = 70.0,
        somente_lojas_preferidas: bool = False,
        incluir_similares: bool = False,
    ) -> None:
        self.providers = list(providers)
        self.result_limit = result_limit
        self.request_delay_seconds = request_delay_seconds
        self.sleeper = sleeper
        self.somente_exatos = somente_exatos
        self.similaridade_minima = similaridade_minima
        self.somente_lojas_preferidas = somente_lojas_preferidas
        self.incluir_similares = incluir_similares

    def _filtrar(self, results: list) -> list:
        """Descarta o que nao e o produto pedido.

        Sem esse corte a base enche de "parecido": outra potencia, outra
        voltagem, kit com acessorio. Para comparar preco do mesmo item, isso
        e ruido, nao alternativa.
        """
        if self.somente_exatos:
            # Similar aqui nao e "parecido": e mesma funcao e mesma voltagem,
            # decidido pelo provedor. Sem esse criterio estreito, aceitar
            # similar traria acessorio e outra categoria junto.
            results = [
                item
                for item in results
                if item.similarity_score >= self.similaridade_minima
                or (self.incluir_similares and item.match_type == "SIMILAR")
            ]
        if self.somente_lojas_preferidas:
            # Só os marketplaces escolhidos entram na base. Comparador e loja
            # avulsa saem, mesmo quando o preco e bom: o pedido e acompanhar
            # esses canais especificamente.
            results = [item for item in results if item.loja_preferida]
        return results

    def collect(self, products: Iterable[ProductInput]) -> list[CollectionRow]:
        rows: list[CollectionRow] = []
        requests_made = 0
        catalog = list(products)
        total = len(catalog) * len(self.providers)
        step = 0
        for position, product in enumerate(catalog, 1):
            for provider in self.providers:
                step += 1
                print(
                    f"[{step}/{total}] produto {position}/{len(catalog)} "
                    f"| {provider.name} | {product.query[:60]}",
                    flush=True,
                )
                if requests_made and self.request_delay_seconds:
                    self.sleeper(self.request_delay_seconds)
                requests_made += 1
                try:
                    results = provider.search(product, self.result_limit)
                except ProviderError as exc:
                    print(f"        bloqueio/erro: {exc}", flush=True)
                    rows.append(CollectionRow.failed(product, provider.name, str(exc)))
                    continue
                except Exception as exc:
                    # Guardar tipo e mensagem: "falha inesperada" sozinho nao
                    # deixa ninguem diagnosticar nada depois do lote.
                    detail = str(exc).strip().splitlines()
                    rows.append(
                        CollectionRow.failed(
                            product,
                            provider.name,
                            f"Falha inesperada ({type(exc).__name__}): "
                            f"{detail[0] if detail else 'sem mensagem'}",
                        )
                    )
                    print(f"        falha: {type(exc).__name__}", flush=True)
                    traceback.print_exc()
                    continue

                provider_results = list(results)
                brutos = len(results)
                results = self._filtrar(results)
                if not results:
                    if brutos:
                        melhor = max(item.similarity_score for item in provider_results)
                        lojas = sorted(
                            {item.seller for item in provider_results if item.seller}
                        )
                        print(
                            f"        {brutos} ofertas descartadas "
                            f"(melhor similaridade {melhor:.0f}%"
                            + (f", lojas: {', '.join(lojas[:4])}" if lojas else "")
                            + ")",
                            flush=True,
                        )
                    else:
                        print("        sem resultado", flush=True)
                    rows.append(CollectionRow.empty(product, provider.name))
                    continue
                precos = [item.price_min for item in results if item.price_min]
                faixa = (
                    f" | R$ {min(precos):.2f} a R$ {max(precos):.2f}" if precos else ""
                )
                print(f"        {len(results)} ofertas{faixa}", flush=True)
                rows.extend(CollectionRow.success(product, item) for item in results)
        return rows
