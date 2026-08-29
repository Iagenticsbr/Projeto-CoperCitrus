import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from copercitrus_price_collector.historico import append_run, load_history
from copercitrus_price_collector.models import CollectionRow, ProductInput, SearchResult


def _offer(product, price, seller="Shopee", provider="Google Shopping"):
    return CollectionRow(
        product=product,
        provider=provider,
        status="OK",
        collected_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        result=SearchResult(
            provider=provider,
            rank=1,
            title=f"{product.produto} anuncio",
            description="",
            price_min=price,
            price_max=price,
            currency="BRL",
            purchase_url="https://loja.example/1",
            match_type="COMPATIVEL",
            similarity_score=90.0,
            seller=seller,
        ),
    )


class HistoricoTest(unittest.TestCase):
    def setUp(self):
        self.product = ProductInput(4, "Lavadora J6600", "Jacto", None, "SKU-1")

    def _contagem(self, path, tabela):
        connection = sqlite3.connect(path)
        try:
            return connection.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        finally:
            connection.close()

    def test_records_offers_and_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historico.db"

            append_run([_offer(self.product, 900.0)], path, "planilha.xlsx", "google")

            self.assertEqual(1, self._contagem(path, "execucoes"))
            self.assertEqual(1, self._contagem(path, "historico_ofertas"))
            self.assertEqual(1, self._contagem(path, "historico_estatisticas"))

    def test_same_search_twice_in_a_day_does_not_duplicate(self):
        """Rodar a mesma busca de novo atualiza o painel, nao duplica linha."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historico.db"
            rows = [_offer(self.product, 900.0), _offer(self.product, 1100.0)]

            append_run(rows, path)
            append_run(rows, path)

            self.assertEqual(2, self._contagem(path, "historico_ofertas"))
            self.assertEqual(1, self._contagem(path, "historico_estatisticas"))
            # As duas execucoes ficam registradas, mesmo sem gerar linha nova.
            self.assertEqual(2, self._contagem(path, "execucoes"))

    def test_new_price_in_the_same_day_is_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historico.db"

            append_run([_offer(self.product, 900.0)], path)
            append_run([_offer(self.product, 850.0)], path)

            self.assertEqual(2, self._contagem(path, "historico_ofertas"))

    def test_different_store_is_a_separate_offer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historico.db"

            append_run(
                [
                    _offer(self.product, 900.0, seller="Shopee"),
                    _offer(self.product, 900.0, seller="Mercado Livre"),
                ],
                path,
            )

            self.assertEqual(2, self._contagem(path, "historico_ofertas"))

    def test_history_of_a_missing_file_is_empty(self):
        vazio = load_history("nao-existe.db")

        self.assertEqual([], vazio["execucoes"])
        self.assertEqual([], vazio["variacoes"])

    def test_single_measurement_has_no_variation_yet(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "historico.db"
            append_run([_offer(self.product, 900.0)], path)

            historico = load_history(path)

            self.assertEqual(1, len(historico["execucoes"]))
            self.assertEqual([], historico["variacoes"])


if __name__ == "__main__":
    unittest.main()
