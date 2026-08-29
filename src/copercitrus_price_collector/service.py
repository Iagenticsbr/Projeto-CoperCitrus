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
    ) -> None:
        self.providers = list(providers)
        self.result_limit = result_limit
        self.request_delay_seconds = request_delay_seconds
        self.sleeper = sleeper

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

                if not results:
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
