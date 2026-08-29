import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from copercitrus_price_collector.agenda import (
    AgendaMensal,
    caminho_catalogo,
    deve_executar,
    ler_estado,
    salvar_catalogo,
)


class CatalogoTest(unittest.TestCase):
    def test_saves_and_finds_spreadsheet(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = salvar_catalogo(Path(pasta), "itens.xlsx", b"conteudo")

            self.assertEqual("catalogo.xlsx", destino.name)
            self.assertEqual(destino, caminho_catalogo(Path(pasta)))

    def test_saves_csv_with_its_own_extension(self):
        with tempfile.TemporaryDirectory() as pasta:
            destino = salvar_catalogo(Path(pasta), "itens.csv", b"Produto;Marca")

            self.assertEqual("catalogo.csv", destino.name)

    def test_new_upload_replaces_the_previous_list(self):
        """A lista monitorada e uma so; duas versoes tornariam o mes ambiguo."""
        with tempfile.TemporaryDirectory() as pasta:
            salvar_catalogo(Path(pasta), "antiga.xlsx", b"velho")
            salvar_catalogo(Path(pasta), "nova.csv", b"Produto;Marca")

            arquivos = sorted(p.name for p in Path(pasta).glob("catalogo.*"))
            self.assertEqual(["catalogo.csv"], arquivos)

    def test_no_catalog_yet(self):
        with tempfile.TemporaryDirectory() as pasta:
            self.assertIsNone(caminho_catalogo(Path(pasta)))


class QuandoExecutarTest(unittest.TestCase):
    def test_runs_on_the_target_day(self):
        self.assertTrue(deve_executar(datetime(2026, 9, 1), 1, None))

    def test_does_not_run_twice_in_the_same_month(self):
        self.assertFalse(deve_executar(datetime(2026, 9, 1), 1, "2026-09"))
        self.assertFalse(deve_executar(datetime(2026, 9, 20), 1, "2026-09"))

    def test_runs_again_in_the_next_month(self):
        self.assertTrue(deve_executar(datetime(2026, 10, 1), 1, "2026-09"))

    def test_recovers_a_missed_day(self):
        """Servico fora do ar no dia 1 executa ao voltar, dentro do mes."""
        self.assertTrue(deve_executar(datetime(2026, 9, 7), 1, "2026-08"))

    def test_waits_until_the_target_day(self):
        self.assertFalse(deve_executar(datetime(2026, 9, 3), 5, "2026-08"))


class AgendaTest(unittest.TestCase):
    def test_runs_once_and_records_the_month(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta)
            salvar_catalogo(caminho, "itens.csv", b"Produto\nBroca")
            chamadas = []
            agenda = AgendaMensal(caminho, chamadas.append, dia=1)

            momento = datetime(2026, 9, 1, tzinfo=timezone.utc)
            self.assertTrue(agenda.verificar(momento))
            self.assertFalse(agenda.verificar(momento))

            self.assertEqual(1, len(chamadas))
            self.assertEqual("2026-09", ler_estado(caminho)["ultima_competencia"])

    def test_does_nothing_without_a_catalog(self):
        with tempfile.TemporaryDirectory() as pasta:
            chamadas = []
            agenda = AgendaMensal(Path(pasta), chamadas.append, dia=1)

            self.assertFalse(agenda.verificar(datetime(2026, 9, 1, tzinfo=timezone.utc)))
            self.assertEqual([], chamadas)


if __name__ == "__main__":
    unittest.main()
