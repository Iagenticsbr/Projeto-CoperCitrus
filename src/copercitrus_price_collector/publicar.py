"""Envio de uma coleta local para a instancia hospedada.

A coleta precisa de navegador com sessao valida, que o servidor nao tem.
Entao ela roda na maquina do operador e o resultado e publicado aqui. A
gravacao no destino e deduplicada, entao reenviar o mesmo arquivo nao
duplica o painel.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from .errors import ConfigurationError, PriceCollectorError


def carregar_ofertas(database: str | Path) -> list[dict]:
    """Le as ofertas com preco da base gerada pela coleta."""
    source = Path(database)
    if not source.is_file():
        raise ConfigurationError(f"Base nao encontrada: {source}")
    conexao = sqlite3.connect(source)
    conexao.row_factory = sqlite3.Row
    try:
        return [
            {
                "sku": linha["sku"],
                "produto": linha["produto"],
                "marca": linha["marca_encontrada"],
                "fonte": linha["fonte"],
                "loja": linha["loja"],
                "titulo": linha["titulo"],
                "preco": linha["preco"],
                "classificacao": linha["classificacao"],
                "similaridade": linha["similaridade"],
                "url": linha["url"],
            }
            for linha in conexao.execute(
                "SELECT sku, produto, marca_encontrada, fonte, loja, titulo, "
                "preco, classificacao, similaridade, url FROM ofertas "
                "WHERE preco IS NOT NULL"
            )
        ]
    finally:
        conexao.close()


def publicar(
    database: str | Path,
    url: str,
    token: str | None = None,
    planilha: str | None = None,
) -> dict:
    """Publica a base em POST {url}/ingest e devolve a resposta do servidor."""
    ofertas = carregar_ofertas(database)
    if not ofertas:
        raise ConfigurationError("A base nao tem oferta com preco para publicar")

    destino = url.rstrip("/") + "/ingest"
    corpo = json.dumps(
        {"planilha": planilha or str(Path(database).name), "ofertas": ofertas}
    ).encode("utf-8")
    cabecalhos = {"Content-Type": "application/json"}
    if token:
        cabecalhos["x-token"] = token

    requisicao = urllib.request.Request(destino, data=corpo, headers=cabecalhos)
    try:
        with urllib.request.urlopen(requisicao, timeout=60) as resposta:
            return json.loads(resposta.read())
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")[:200]
        raise PriceCollectorError(
            f"O servidor recusou a publicacao ({exc.code}): {detalhe}"
        ) from exc
    except urllib.error.URLError as exc:
        raise PriceCollectorError(
            f"Nao foi possivel alcancar {destino}: {exc.reason}"
        ) from exc
