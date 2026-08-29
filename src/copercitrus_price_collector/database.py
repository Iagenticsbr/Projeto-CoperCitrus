"""Base de dados da coleta, usada como fonte do dashboard.

Gera um SQLite com tres tabelas (`produtos`, `ofertas`, `resumo_precos`) e a
exportacao equivalente em CSV, para BI que nao le SQLite diretamente.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from statistics import mean

from .analytics import build_price_statistics, build_store_prices
from .models import CollectionRow


SCHEMA = """
DROP TABLE IF EXISTS ofertas;
DROP TABLE IF EXISTS produtos;
DROP TABLE IF EXISTS resumo_precos;
DROP TABLE IF EXISTS estatisticas_precos;
DROP TABLE IF EXISTS precos_por_loja;

CREATE TABLE produtos (
    sku TEXT,
    produto TEXT NOT NULL,
    marca TEXT,
    modelo TEXT,
    quantidade_solicitada TEXT,
    consulta TEXT,
    linha_origem INTEGER
);

CREATE TABLE ofertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT,
    produto TEXT NOT NULL,
    fonte TEXT NOT NULL,
    posicao INTEGER,
    titulo TEXT,
    marca_encontrada TEXT,
    embalagem TEXT,
    preco REAL,
    moeda TEXT,
    loja TEXT,
    url TEXT,
    imagem TEXT,
    similaridade REAL,
    classificacao TEXT,
    loja_preferida INTEGER,
    status TEXT NOT NULL,
    erro TEXT,
    coletado_em TEXT NOT NULL
);

CREATE TABLE resumo_precos (
    sku TEXT,
    produto TEXT NOT NULL,
    marca TEXT,
    ofertas INTEGER NOT NULL,
    ofertas_relevantes INTEGER NOT NULL,
    compativeis INTEGER NOT NULL,
    similares INTEGER NOT NULL,
    menor_preco REAL,
    maior_preco REAL,
    preco_medio REAL,
    amplitude_percentual REAL,
    menor_preco_geral REAL,
    maior_preco_geral REAL,
    fonte_menor_preco TEXT,
    url_menor_preco TEXT,
    fonte_maior_preco TEXT,
    url_maior_preco TEXT,
    fontes_consultadas TEXT,
    coletado_em TEXT
);

CREATE TABLE estatisticas_precos (
    sku TEXT,
    produto TEXT NOT NULL,
    n_ofertas INTEGER NOT NULL,
    n_lojas INTEGER NOT NULL,
    n_fontes INTEGER NOT NULL,
    lojas TEXT,
    menor_preco REAL,
    p25 REAL,
    mediana REAL,
    p75 REAL,
    maior_preco REAL,
    preco_medio REAL,
    desvio_padrao REAL,
    coeficiente_variacao REAL,
    amplitude_interquartil REAL,
    limite_inferior REAL,
    limite_superior REAL,
    outliers_baixo INTEGER,
    outliers_alto INTEGER
);

CREATE TABLE precos_por_loja (
    sku TEXT,
    produto TEXT NOT NULL,
    loja TEXT NOT NULL,
    fonte TEXT,
    ofertas INTEGER NOT NULL,
    menor_preco REAL,
    maior_preco REAL,
    preco_medio REAL,
    variacao_vs_mediana_pct REAL,
    url TEXT
);

CREATE INDEX idx_ofertas_sku ON ofertas (sku);
CREATE INDEX idx_ofertas_fonte ON ofertas (fonte);
CREATE INDEX idx_ofertas_preco ON ofertas (preco);
CREATE INDEX idx_precos_loja ON precos_por_loja (loja);
"""

ESTATISTICA_COLUMNS = [
    "sku", "produto", "n_ofertas", "n_lojas", "n_fontes", "lojas",
    "menor_preco", "p25", "mediana", "p75", "maior_preco", "preco_medio",
    "desvio_padrao", "coeficiente_variacao", "amplitude_interquartil",
    "limite_inferior", "limite_superior", "outliers_baixo", "outliers_alto",
]

LOJA_COLUMNS = [
    "sku", "produto", "loja", "fonte", "ofertas", "menor_preco",
    "maior_preco", "preco_medio", "variacao_vs_mediana_pct", "url",
]

OFERTA_COLUMNS = [
    "sku",
    "produto",
    "fonte",
    "posicao",
    "titulo",
    "marca_encontrada",
    "embalagem",
    "preco",
    "moeda",
    "loja",
    "url",
    "imagem",
    "similaridade",
    "classificacao",
    "loja_preferida",
    "status",
    "erro",
    "coletado_em",
]

RESUMO_COLUMNS = [
    "sku",
    "produto",
    "marca",
    "ofertas",
    "ofertas_relevantes",
    "compativeis",
    "similares",
    "menor_preco",
    "maior_preco",
    "preco_medio",
    "amplitude_percentual",
    "menor_preco_geral",
    "maior_preco_geral",
    "fonte_menor_preco",
    "url_menor_preco",
    "fonte_maior_preco",
    "url_maior_preco",
    "fontes_consultadas",
    "coletado_em",
]


def _oferta_values(row: CollectionRow) -> tuple:
    item = row.result
    return (
        row.product.sku,
        row.product.produto,
        row.provider,
        item.rank if item else None,
        item.title if item else None,
        item.brand if item else None,
        item.package_quantity if item else None,
        item.price_min if item else None,
        item.currency if item else None,
        item.seller if item else None,
        item.purchase_url if item else None,
        item.image_url if item else None,
        item.similarity_score if item else None,
        item.match_type if item else None,
        int(bool(item.loja_preferida)) if item else None,
        row.status,
        row.error,
        row.collected_at.replace(microsecond=0).isoformat(),
    )


RELEVANT_MATCHES = {"COMPATIVEL", "SIMILAR"}


def _is_priced(row: CollectionRow) -> bool:
    return row.result is not None and row.result.price_min is not None


def _is_relevant(row: CollectionRow) -> bool:
    """Oferta que representa o produto pedido, nao um acessorio dele.

    Sem esse filtro a gaxeta de R$ 25,90 virava o menor preco do
    pulverizador e a faixa de preco do dashboard ficava sem sentido.
    """
    return _is_priced(row) and row.result.match_type in RELEVANT_MATCHES


def build_summary(rows: list[CollectionRow]) -> list[dict]:
    """Consolida menor, maior e preco medio por produto solicitado.

    `menor_preco`/`maior_preco` usam somente ofertas classificadas como
    COMPATIVEL ou SIMILAR; `menor_preco_geral`/`maior_preco_geral` mantem a
    faixa bruta, incluindo pecas e acessorios.
    """
    grouped: dict[tuple[str | None, str], list[CollectionRow]] = {}
    for row in rows:
        grouped.setdefault((row.product.sku, row.product.produto), []).append(row)

    summary: list[dict] = []
    for (sku, produto), product_rows in grouped.items():
        priced = [row for row in product_rows if _is_priced(row)]
        relevant = [row for row in priced if _is_relevant(row)]
        base = relevant or priced
        prices = [row.result.price_min for row in base]
        all_prices = [row.result.price_min for row in priced]
        cheapest = min(base, key=lambda row: row.result.price_min) if base else None
        expensive = max(base, key=lambda row: row.result.price_min) if base else None
        menor = min(prices) if prices else None
        maior = max(prices) if prices else None
        amplitude = (
            round((maior - menor) / menor * 100, 2)
            if menor and maior and menor > 0
            else None
        )
        summary.append(
            {
                "sku": sku,
                "produto": produto,
                "marca": product_rows[0].product.marca,
                "ofertas": len(priced),
                "ofertas_relevantes": len(relevant),
                "compativeis": sum(
                    1
                    for row in product_rows
                    if row.result is not None and row.result.match_type == "COMPATIVEL"
                ),
                "similares": sum(
                    1
                    for row in product_rows
                    if row.result is not None and row.result.possible_similar
                ),
                "menor_preco": menor,
                "maior_preco": maior,
                "preco_medio": round(mean(prices), 2) if prices else None,
                "amplitude_percentual": amplitude,
                "menor_preco_geral": min(all_prices) if all_prices else None,
                "maior_preco_geral": max(all_prices) if all_prices else None,
                "fonte_menor_preco": cheapest.provider if cheapest else None,
                "url_menor_preco": cheapest.result.purchase_url if cheapest else None,
                "fonte_maior_preco": expensive.provider if expensive else None,
                "url_maior_preco": expensive.result.purchase_url if expensive else None,
                "fontes_consultadas": ", ".join(
                    sorted({row.provider for row in product_rows})
                ),
                "coletado_em": max(row.collected_at for row in product_rows)
                .replace(microsecond=0)
                .isoformat(),
            }
        )
    return summary


def export_database(rows: list[CollectionRow], path: str | Path) -> Path:
    """Grava o SQLite da coleta e devolve o caminho do arquivo."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(SCHEMA)
        produtos: dict[tuple[str | None, str], tuple] = {}
        for row in rows:
            produtos.setdefault(
                (row.product.sku, row.product.produto),
                (
                    row.product.sku,
                    row.product.produto,
                    row.product.marca,
                    row.product.modelo,
                    row.product.quantidade_solicitada,
                    row.product.query,
                    row.product.row_number,
                ),
            )
        connection.executemany(
            "INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?)",
            list(produtos.values()),
        )
        oferta_placeholders = ", ".join(["?"] * len(OFERTA_COLUMNS))
        connection.executemany(
            "INSERT INTO ofertas ("
            + ", ".join(OFERTA_COLUMNS)
            + ") VALUES ("
            + oferta_placeholders
            + ")",
            [_oferta_values(row) for row in rows],
        )
        resumo_placeholders = ", ".join(["?"] * len(RESUMO_COLUMNS))
        connection.executemany(
            "INSERT INTO resumo_precos ("
            + ", ".join(RESUMO_COLUMNS)
            + ") VALUES ("
            + resumo_placeholders
            + ")",
            [
                tuple(entry[column] for column in RESUMO_COLUMNS)
                for entry in build_summary(rows)
            ],
        )
        _insert_rows(
            connection,
            "estatisticas_precos",
            ESTATISTICA_COLUMNS,
            build_price_statistics(rows),
        )
        _insert_rows(
            connection, "precos_por_loja", LOJA_COLUMNS, build_store_prices(rows)
        )
        connection.commit()
    finally:
        connection.close()
    return destination


def _insert_rows(connection, table: str, columns: list[str], entries: list[dict]) -> None:
    if not entries:
        return
    connection.executemany(
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(['?'] * len(columns))})",
        [tuple(entry.get(column) for column in columns) for entry in entries],
    )


def export_csv(rows: list[CollectionRow], directory: str | Path) -> list[Path]:
    """Exporta ofertas e resumo em CSV UTF-8 com BOM (abre direto no Excel)."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    ofertas_path = folder / "ofertas.csv"
    with ofertas_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(OFERTA_COLUMNS)
        writer.writerows(_oferta_values(row) for row in rows)
    written.append(ofertas_path)

    resumo_path = folder / "resumo_precos.csv"
    with resumo_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(RESUMO_COLUMNS)
        for entry in build_summary(rows):
            writer.writerow([entry[column] for column in RESUMO_COLUMNS])
    written.append(resumo_path)

    for name, columns, entries in (
        ("estatisticas_precos.csv", ESTATISTICA_COLUMNS, build_price_statistics(rows)),
        ("precos_por_loja.csv", LOJA_COLUMNS, build_store_prices(rows)),
    ):
        path = folder / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(columns)
            for entry in entries:
                writer.writerow([entry.get(column) for column in columns])
        written.append(path)
    return written
