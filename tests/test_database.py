import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from copercitrus_price_collector.database import (
    build_summary,
    export_csv,
    export_database,
)
from copercitrus_price_collector.models import CollectionRow, ProductInput, SearchResult


def _offer(product, provider, price, match_type="COMPATIVEL", rank=1):
    result = SearchResult(
        provider=provider,
        rank=rank,
        title=f"{product.produto} {price}",
        description="",
        price_min=price,
        price_max=price,
        currency="BRL",
        purchase_url=f"https://loja.example/{price}",
        match_type=match_type,
        similarity_score=90.0 if match_type == "COMPATIVEL" else 60.0,
        seller="Loja X",
    )
    return CollectionRow(
        product=product,
        provider=provider,
        status="OK",
        collected_at=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        result=result,
    )


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.product = ProductInput(4, "Pulverizador costal", "Jacto", "PJH", "SKU-9")
        self.rows = [
            _offer(self.product, "Buscape", 900.0),
            _offer(self.product, "Buscape", 1200.0, rank=2),
            _offer(self.product, "Bing Shopping", 1000.0, "SIMILAR"),
            # Acessorio barato: nao pode virar o menor preco do equipamento.
            _offer(self.product, "Bing Shopping", 25.9, "DIVERGENTE", rank=2),
        ]

    def test_summary_ignores_divergent_offers_in_price_range(self):
        summary = build_summary(self.rows)[0]

        self.assertEqual(900.0, summary["menor_preco"])
        self.assertEqual(1200.0, summary["maior_preco"])
        self.assertEqual(25.9, summary["menor_preco_geral"])
        self.assertEqual(3, summary["ofertas_relevantes"])
        self.assertEqual(4, summary["ofertas"])
        self.assertEqual(1033.33, summary["preco_medio"])
        self.assertEqual(33.33, summary["amplitude_percentual"])
        self.assertEqual("Buscape", summary["fonte_menor_preco"])

    def test_summary_falls_back_to_all_offers_when_nothing_is_relevant(self):
        rows = [_offer(self.product, "Bing Shopping", 25.9, "DIVERGENTE")]

        summary = build_summary(rows)[0]

        self.assertEqual(0, summary["ofertas_relevantes"])
        self.assertEqual(25.9, summary["menor_preco"])

    def test_exports_sqlite_with_offers_products_and_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = export_database(self.rows, Path(directory) / "precos.db")

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    4, connection.execute("SELECT count(*) FROM ofertas").fetchone()[0]
                )
                self.assertEqual(
                    1, connection.execute("SELECT count(*) FROM produtos").fetchone()[0]
                )
                menor, maior = connection.execute(
                    "SELECT menor_preco, maior_preco FROM resumo_precos"
                ).fetchone()
                self.assertEqual((900.0, 1200.0), (menor, maior))
                consulta = connection.execute(
                    "SELECT consulta FROM produtos"
                ).fetchone()[0]
                self.assertNotIn("SKU-9", consulta)
            finally:
                connection.close()

    def test_rewrites_database_instead_of_duplicating_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "precos.db"
            export_database(self.rows, destination)
            export_database(self.rows, destination)

            connection = sqlite3.connect(destination)
            try:
                self.assertEqual(
                    4, connection.execute("SELECT count(*) FROM ofertas").fetchone()[0]
                )
            finally:
                connection.close()

    def test_exports_one_csv_per_table(self):
        with tempfile.TemporaryDirectory() as directory:
            written = export_csv(self.rows, directory)

            nomes = {path.name for path in written}
            self.assertEqual(
                {
                    "ofertas.csv",
                    "resumo_precos.csv",
                    "estatisticas_precos.csv",
                    "precos_por_loja.csv",
                },
                nomes,
            )
            self.assertTrue(all(path.exists() for path in written))
            content = (Path(directory) / "ofertas.csv").read_text(encoding="utf-8-sig")
            self.assertIn("Buscape", content)
            self.assertEqual(5, len(content.strip().splitlines()))


if __name__ == "__main__":
    unittest.main()
