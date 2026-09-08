import tempfile
import unittest
from pathlib import Path

from copercitrus_price_collector.armazenamento import (
    Banco,
    _para_postgres,
    destino_padrao,
    disponivel,
    e_postgres,
)


ESQUEMA = """
CREATE TABLE IF NOT EXISTS ofertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT,
    preco REAL
);

-- comentario que nao pode virar comando
CREATE UNIQUE INDEX IF NOT EXISTS idx_unico ON ofertas (sku, preco);
"""


class DialetoTest(unittest.TestCase):
    def test_placeholders_become_percent_s(self):
        self.assertEqual(
            "SELECT * FROM t WHERE a = %s AND b = %s",
            _para_postgres("SELECT * FROM t WHERE a = ? AND b = ?"),
        )

    def test_autoincrement_becomes_bigserial(self):
        traduzido = _para_postgres("CREATE TABLE t (id INTEGER PRIMARY KEY AUTOINCREMENT)")

        self.assertIn("BIGSERIAL PRIMARY KEY", traduzido)
        self.assertNotIn("AUTOINCREMENT", traduzido)

    def test_real_becomes_double_precision(self):
        self.assertIn("DOUBLE PRECISION", _para_postgres("CREATE TABLE t (preco REAL)"))

    def test_real_inside_a_word_is_untouched(self):
        """Trocar por substring quebraria uma coluna chamada preco_real."""
        traduzido = _para_postgres("CREATE TABLE t (preco_real REAL)")

        self.assertIn("preco_real DOUBLE PRECISION", traduzido)

    def test_insert_or_ignore_becomes_on_conflict(self):
        traduzido = _para_postgres("INSERT OR IGNORE INTO t (a) VALUES (?)")

        self.assertEqual("INSERT INTO t (a) VALUES (%s) ON CONFLICT DO NOTHING", traduzido)

    def test_plain_insert_gets_no_conflict_clause(self):
        traduzido = _para_postgres("INSERT INTO t (a) VALUES (?)")

        self.assertNotIn("ON CONFLICT", traduzido)


class DestinoTest(unittest.TestCase):
    def test_url_is_recognized_as_postgres(self):
        self.assertTrue(e_postgres("postgresql://u:p@host/db"))
        self.assertTrue(e_postgres("postgres://u:p@host/db"))

    def test_path_is_not_postgres(self):
        self.assertFalse(e_postgres(Path("dados/historico.db")))
        self.assertFalse(e_postgres("dados/historico.db"))

    def test_environment_url_wins_over_the_file(self):
        import os

        anterior = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = "postgresql://u:p@host/db"
        try:
            self.assertEqual(
                "postgresql://u:p@host/db", destino_padrao("dados/historico.db")
            )
        finally:
            if anterior is None:
                del os.environ["DATABASE_URL"]
            else:
                os.environ["DATABASE_URL"] = anterior

    def test_file_is_used_when_no_url_is_set(self):
        import os

        anterior = os.environ.pop("DATABASE_URL", None)
        try:
            self.assertEqual("dados/historico.db", destino_padrao("dados/historico.db"))
        finally:
            if anterior is not None:
                os.environ["DATABASE_URL"] = anterior


class BancoSqliteTest(unittest.TestCase):
    def test_schema_insert_and_read(self):
        with tempfile.TemporaryDirectory() as pasta:
            with Banco(Path(pasta) / "sub" / "base.db") as banco:
                banco.criar(ESQUEMA)
                identificador = banco.inserir_e_devolver_id(
                    "INSERT INTO ofertas (sku, preco) VALUES (?, ?)", ("A", 10.0)
                )
                banco.confirmar()

                self.assertEqual(1, identificador)
                self.assertEqual(
                    [{"id": 1, "sku": "A", "preco": 10.0}],
                    banco.consultar("SELECT id, sku, preco FROM ofertas"),
                )

    def test_schema_is_idempotent(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "base.db"
            with Banco(caminho) as banco:
                banco.criar(ESQUEMA)
            with Banco(caminho) as banco:
                banco.criar(ESQUEMA)

                self.assertTrue(banco.existe_tabela("ofertas"))

    def test_duplicate_is_ignored(self):
        with tempfile.TemporaryDirectory() as pasta:
            with Banco(Path(pasta) / "base.db") as banco:
                banco.criar(ESQUEMA)
                linhas = [("A", 10.0), ("A", 10.0), ("B", 12.0)]
                banco.executar_muitos(
                    "INSERT OR IGNORE INTO ofertas (sku, preco) VALUES (?, ?)", linhas
                )
                banco.confirmar()

                self.assertEqual(2, banco.valor("SELECT count(*) AS n FROM ofertas"))

    def test_empty_batch_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as pasta:
            with Banco(Path(pasta) / "base.db") as banco:
                banco.criar(ESQUEMA)

                banco.executar_muitos("INSERT INTO ofertas (sku) VALUES (?)", [])

                self.assertEqual(0, banco.valor("SELECT count(*) AS n FROM ofertas"))

    def test_missing_table_is_reported_as_absent(self):
        with tempfile.TemporaryDirectory() as pasta:
            with Banco(Path(pasta) / "base.db") as banco:
                self.assertFalse(banco.existe_tabela("ofertas"))


class MigracaoTest(unittest.TestCase):
    """Base gravada por versao antiga precisa ganhar as colunas novas.

    Foi assim que uma base real parou de abrir: o esquema ganhou
    `loja_preferida`, `CREATE TABLE IF NOT EXISTS` nao alterou a tabela ja
    existente, e a leitura passou a falhar com "no such column".
    """

    def _base_antiga(self, pasta):
        caminho = Path(pasta) / "antiga.db"
        with Banco(caminho) as banco:
            banco.executar("CREATE TABLE ofertas (id INTEGER PRIMARY KEY, sku TEXT)")
            banco.executar("INSERT INTO ofertas (sku) VALUES ('A')")
            banco.confirmar()
        return caminho

    def test_missing_column_is_added(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._base_antiga(pasta)

            with Banco(caminho) as banco:
                self.assertTrue(banco.garantir_coluna("ofertas", "preco", "REAL"))

                self.assertEqual(
                    [{"sku": "A", "preco": None}],
                    banco.consultar("SELECT sku, preco FROM ofertas"),
                )

    def test_existing_column_is_left_alone(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._base_antiga(pasta)

            with Banco(caminho) as banco:
                self.assertFalse(banco.garantir_coluna("ofertas", "sku", "TEXT"))
                self.assertEqual("A", banco.valor("SELECT sku FROM ofertas"))

    def test_column_on_a_missing_table_is_not_attempted(self):
        with tempfile.TemporaryDirectory() as pasta:
            with Banco(Path(pasta) / "vazia.db") as banco:
                self.assertEqual(set(), banco.colunas("ofertas"))

    def test_reading_an_old_history_repairs_it(self):
        from copercitrus_price_collector.historico import SCHEMA, load_offers

        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "historico.db"
            with Banco(caminho) as banco:
                banco.criar(SCHEMA)
                # Volta a tabela ao formato anterior a coluna nova.
                banco.executar("ALTER TABLE historico_ofertas DROP COLUMN loja_preferida")
                banco.executar(
                    "INSERT INTO historico_ofertas (execucao_id, coletado_em, dia, "
                    "sku, produto, fonte, loja, titulo, preco) "
                    "VALUES (1, '2026-09-08T00:00:00', '2026-09-08', 'A', "
                    "'Produto', 'Mercado Livre', 'Mercado Livre', 'Anuncio', 10.0)"
                )
                banco.confirmar()

            ofertas = load_offers(caminho)

            self.assertEqual(1, len(ofertas))
            self.assertIsNone(ofertas[0]["loja_preferida"])


class DisponivelTest(unittest.TestCase):
    def test_missing_file_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as pasta:
            self.assertFalse(disponivel(Path(pasta) / "nao-existe.db"))

    def test_unreachable_postgres_is_empty_not_an_error(self):
        """O painel abre antes da primeira coleta; sem banco e vazio, nao erro."""
        self.assertFalse(disponivel("postgresql://u:p@127.0.0.1:1/naoexiste"))


if __name__ == "__main__":
    unittest.main()
