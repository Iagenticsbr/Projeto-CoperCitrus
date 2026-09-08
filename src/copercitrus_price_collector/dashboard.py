"""Gerador do dashboard interativo de precos.

Produz um HTML unico, sem servidor e sem dependencia externa: os dados vao
embutidos no arquivo. Assim o painel abre com dois cliques, funciona offline
e pode ser enviado para quem nao tem Python instalado.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .errors import ConfigurationError
from .dashboard_template import HTML_TEMPLATE
from .historico import load_history, load_offers
from .validacao import (
    marcar_discrepancias,
    resumo_classificacao,
    resumo_discrepancias,
)


def _read_table(connection: sqlite3.Connection, table: str) -> list[dict]:
    try:
        return [
            dict(row) for row in connection.execute(f"SELECT * FROM {table}")
        ]
    except sqlite3.OperationalError:
        return []


def collect_dashboard_data(
    database: str | Path, historico: str | Path | None = None
) -> dict:
    """Le a base da coleta e o historico e devolve o payload do painel."""
    source = Path(database)
    vazio = {
        "gerado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "base": str(source),
        "produtos": [],
        "ofertas": [],
        "resumo": [],
        "estatisticas": [],
        "lojas": [],
    }
    if source.is_file():
        connection = sqlite3.connect(source)
        connection.row_factory = sqlite3.Row
        try:
            dados = {
                **vazio,
                "produtos": _read_table(connection, "produtos"),
                "ofertas": _read_table(connection, "ofertas"),
                "resumo": _read_table(connection, "resumo_precos"),
                "estatisticas": _read_table(connection, "estatisticas_precos"),
                "lojas": _read_table(connection, "precos_por_loja"),
            }
        finally:
            connection.close()
    elif historico and Path(historico).is_file():
        # Instancia que so recebe por ingestao nao tem a base da coleta; o
        # historico sozinho ja sustenta o painel inteiro.
        dados = dict(vazio)
    else:
        raise ConfigurationError(f"Base de dados nao encontrada: {source}")

    dados["historico"] = (
        load_history(historico)
        if historico
        else {"execucoes": [], "series": [], "variacoes": []}
    )

    # O historico e a fonte preferida: acumula todas as buscas ja feitas, sem
    # duplicar. A base da ultima execucao so entra quando nao ha historico.
    acumuladas = load_offers(historico) if historico else []
    if acumuladas:
        dados["ofertas"] = acumuladas
        dados["origem"] = "historico acumulado"
    else:
        dados["origem"] = "ultima coleta"

    # Marcar antes de servir: o painel mostra a oferta suspeita junto das
    # outras, sinalizada, em vez de escondê-la ou de deixá-la passar limpa.
    dados["ofertas"] = marcar_discrepancias(dados["ofertas"])
    dados["alertas"] = resumo_discrepancias(dados["ofertas"])
    dados["classificacao"] = resumo_classificacao(dados["ofertas"])
    return dados


def render_dashboard(
    database: str | Path,
    output: str | Path,
    historico: str | Path | None = None,
) -> Path:
    """Grava o HTML do dashboard e devolve o caminho."""
    dados = collect_dashboard_data(database, historico)
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dados, ensure_ascii=False, default=str)
    destination.write_text(
        HTML_TEMPLATE.replace("__DADOS__", payload), encoding="utf-8"
    )
    return destination


__all__ = ["HTML_TEMPLATE", "collect_dashboard_data", "render_dashboard"]
