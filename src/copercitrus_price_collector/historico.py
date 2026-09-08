"""Historico acumulado de precos entre execucoes.

A base da coleta e recriada a cada execucao — e o retrato de agora. Este
arquivo e o oposto: so acrescenta, nunca apaga, para que a variacao de preco
ao longo do tempo exista. Sem ele nao ha serie historica, e sem serie
historica nao da para dizer se um preco subiu, caiu ou sempre foi assim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .analytics import build_price_statistics
from .armazenamento import Banco, disponivel
from .models import CollectionRow


SCHEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    executado_em TEXT NOT NULL,
    planilha TEXT,
    fontes TEXT,
    produtos INTEGER NOT NULL,
    ofertas INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS historico_ofertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id INTEGER NOT NULL REFERENCES execucoes (id),
    coletado_em TEXT NOT NULL,
    dia TEXT NOT NULL,
    sku TEXT,
    produto TEXT NOT NULL,
    marca TEXT,
    fonte TEXT NOT NULL,
    loja TEXT,
    titulo TEXT,
    preco REAL,
    classificacao TEXT,
    similaridade REAL,
    loja_preferida INTEGER,
    url TEXT
);

CREATE TABLE IF NOT EXISTS historico_estatisticas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id INTEGER NOT NULL REFERENCES execucoes (id),
    coletado_em TEXT NOT NULL,
    dia TEXT NOT NULL,
    sku TEXT,
    produto TEXT NOT NULL,
    n_ofertas INTEGER,
    n_lojas INTEGER,
    menor_preco REAL,
    mediana REAL,
    maior_preco REAL,
    preco_medio REAL,
    coeficiente_variacao REAL
);

-- Chave de deduplicacao: a mesma oferta, da mesma loja, pelo mesmo preco e
-- no mesmo dia e uma medicao so. Repetir a busca no mesmo dia nao duplica o
-- dashboard; no dia seguinte entra como nova medicao e vira serie historica.
CREATE UNIQUE INDEX IF NOT EXISTS idx_hist_unico ON historico_ofertas (
    dia, sku, fonte, loja, titulo, preco
);

CREATE INDEX IF NOT EXISTS idx_hist_sku ON historico_ofertas (sku);
CREATE INDEX IF NOT EXISTS idx_hist_data ON historico_ofertas (coletado_em);
CREATE INDEX IF NOT EXISTS idx_hist_loja ON historico_ofertas (loja);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hist_est_unico
    ON historico_estatisticas (dia, sku);

CREATE INDEX IF NOT EXISTS idx_hist_est_sku ON historico_estatisticas (sku);
"""


# Colunas acrescentadas depois que a primeira base ja estava em uso. Bases
# antigas nao as tem, e o painel le todas: sem isso a leitura falha com
# "no such column" numa base que so precisava de um ALTER.
COLUNAS_TARDIAS = (
    ("historico_ofertas", "loja_preferida", "INTEGER"),
    ("historico_ofertas", "classificacao", "TEXT"),
    ("historico_ofertas", "similaridade", "REAL"),
    ("historico_ofertas", "url", "TEXT"),
    ("historico_ofertas", "marca", "TEXT"),
)


def preparar(banco: Banco) -> None:
    """Cria o que falta e completa base antiga com as colunas novas."""
    banco.criar(SCHEMA)
    for tabela, coluna, tipo in COLUNAS_TARDIAS:
        banco.garantir_coluna(tabela, coluna, tipo)


def append_run(
    rows: list[CollectionRow],
    path: str | Path,
    planilha: str | None = None,
    fontes: str | None = None,
) -> int:
    """Acrescenta uma execucao ao historico e devolve o id gravado."""
    momento = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    dia = momento[:10]
    produtos = {(row.product.sku, row.product.produto) for row in rows}
    com_preco = [
        row for row in rows if row.result is not None and row.result.price_min is not None
    ]

    banco = Banco(path)
    try:
        preparar(banco)
        execucao_id = banco.inserir_e_devolver_id(
            "INSERT INTO execucoes (executado_em, planilha, fontes, produtos, ofertas) "
            "VALUES (?, ?, ?, ?, ?)",
            (momento, planilha, fontes, len(produtos), len(com_preco)),
        )

        # INSERT OR IGNORE + indice unico: reexecutar a mesma busca no mesmo dia
        # atualiza o painel sem duplicar linha.
        banco.executar_muitos(
            "INSERT OR IGNORE INTO historico_ofertas (execucao_id, coletado_em, dia, "
            "sku, produto, marca, fonte, loja, titulo, preco, classificacao, "
            "similaridade, loja_preferida, url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    execucao_id,
                    momento,
                    dia,
                    row.product.sku,
                    row.product.produto,
                    row.product.marca,
                    row.provider,
                    row.result.seller,
                    row.result.title,
                    row.result.price_min,
                    row.result.match_type,
                    row.result.similarity_score,
                    int(bool(row.result.loja_preferida)),
                    row.result.purchase_url,
                )
                for row in com_preco
            ],
        )

        # Uma medicao por dia: a do dia e apagada antes de entrar a nova.
        # Substituir com INSERT OR REPLACE so existe no SQLite; apagar antes
        # da o mesmo resultado e vale nos dois bancos.
        estatisticas = build_price_statistics(rows)
        banco.executar_muitos(
            "DELETE FROM historico_estatisticas WHERE dia = ? AND sku = ?",
            [(dia, entry["sku"]) for entry in estatisticas],
        )
        banco.executar_muitos(
            "INSERT INTO historico_estatisticas (execucao_id, coletado_em, "
            "dia, sku, produto, n_ofertas, n_lojas, menor_preco, mediana, maior_preco, "
            "preco_medio, coeficiente_variacao) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    execucao_id,
                    momento,
                    dia,
                    entry["sku"],
                    entry["produto"],
                    entry["n_ofertas"],
                    entry["n_lojas"],
                    entry["menor_preco"],
                    entry["mediana"],
                    entry["maior_preco"],
                    entry["preco_medio"],
                    entry["coeficiente_variacao"],
                )
                for entry in estatisticas
            ],
        )
        banco.confirmar()
        return execucao_id
    finally:
        banco.fechar()


def load_history(path: str | Path) -> dict:
    """Le o historico para alimentar a area de evolucao do dashboard."""
    if not disponivel(path):
        return {"execucoes": [], "series": [], "variacoes": []}

    banco = Banco(path)
    try:
        preparar(banco)
        execucoes = banco.consultar(
            "SELECT id, executado_em, planilha, fontes, produtos, ofertas "
            "FROM execucoes ORDER BY id"
        )
        series = banco.consultar(
            "SELECT sku, produto, dia AS coletado_em, n_ofertas, n_lojas, "
            "menor_preco, mediana, maior_preco, preco_medio, "
            "coeficiente_variacao FROM historico_estatisticas "
            "ORDER BY sku, dia"
        )
        return {
            "execucoes": execucoes,
            "series": series,
            "variacoes": _price_changes(banco),
        }
    finally:
        banco.fechar()


def load_offers(path: str | Path) -> list[dict]:
    """Ofertas do historico, uma por chave, sempre a medicao mais recente.

    O painel le daqui e nao da base da ultima execucao: toda busca cai no
    historico deduplicado, entao o painel reflete tudo o que ja foi coletado
    em vez de so o ultimo lote.
    """
    if not disponivel(path):
        return []
    banco = Banco(path)
    try:
        preparar(banco)
        # Agrupar por todas as colunas lidas: o SQLite aceita coluna solta no
        # SELECT com GROUP BY, o PostgreSQL recusa. Como a chave ja e unica
        # por dia, agrupar por tudo devolve as mesmas linhas nos dois.
        return banco.consultar(
            "SELECT sku, produto, marca, fonte, loja, titulo, preco, "
            "classificacao, similaridade, loja_preferida, url, dia, "
            "MAX(coletado_em) AS coletado_em "
            "FROM historico_ofertas WHERE preco IS NOT NULL "
            "GROUP BY sku, produto, marca, fonte, loja, titulo, preco, "
            "classificacao, similaridade, loja_preferida, url, dia "
            "ORDER BY produto, preco"
        )
    finally:
        banco.fechar()


def _price_changes(banco: Banco) -> list[dict]:
    """Diferenca entre a ultima e a penultima medicao de cada SKU."""
    rows = banco.consultar(
        "SELECT sku, produto, dia AS coletado_em, menor_preco, mediana "
        "FROM historico_estatisticas ORDER BY sku, dia"
    )
    por_sku: dict[str, list] = {}
    for row in rows:
        por_sku.setdefault(row["sku"], []).append(row)

    variacoes: list[dict] = []
    for sku, medicoes in por_sku.items():
        if len(medicoes) < 2:
            continue
        anterior, atual = medicoes[-2], medicoes[-1]
        base = anterior["menor_preco"]
        if not base:
            continue
        variacoes.append(
            {
                "sku": sku,
                "produto": atual["produto"],
                "de": anterior["coletado_em"],
                "para": atual["coletado_em"],
                "menor_anterior": anterior["menor_preco"],
                "menor_atual": atual["menor_preco"],
                "variacao_pct": round(
                    (atual["menor_preco"] - base) / base * 100, 2
                ),
            }
        )
    return sorted(variacoes, key=lambda item: item["variacao_pct"])
