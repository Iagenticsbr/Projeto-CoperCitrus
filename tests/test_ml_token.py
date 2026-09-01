import json
import tempfile
import time
import unittest
from pathlib import Path

from copercitrus_price_collector import ml_token
from copercitrus_price_collector.errors import ConfigurationError


class RenovacaoTest(unittest.TestCase):
    def test_renews_after_five_hours(self):
        """A margem de uma hora existe para coleta longa nao vencer no meio."""
        emitido = {"access_token": "TG-1", "emitido_em": 1000}

        self.assertFalse(ml_token.precisa_renovar(emitido, agora=1000 + 4 * 3600))
        self.assertTrue(ml_token.precisa_renovar(emitido, agora=1000 + 5 * 3600))

    def test_state_without_timestamp_is_renewed(self):
        self.assertTrue(ml_token.precisa_renovar({"access_token": "TG-1"}))

    def test_fresh_token_is_returned_untouched(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "token.json"
            ml_token.gravar(
                caminho, {"access_token": "TG-atual", "refresh_token": "R-1"}
            )

            self.assertEqual("TG-atual", ml_token.token_valido(caminho))

    def test_expired_without_refresh_token_is_reported(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "token.json"
            caminho.write_text(
                json.dumps({"access_token": "TG-velho", "emitido_em": 0}),
                encoding="utf-8",
            )

            with self.assertRaises(ConfigurationError) as erro:
                ml_token.token_valido(caminho)

            self.assertIn("offline_access", str(erro.exception))

    def test_missing_file_is_reported(self):
        with tempfile.TemporaryDirectory() as pasta:
            with self.assertRaises(ConfigurationError):
                ml_token.token_valido(Path(pasta) / "nao-existe.json")

    def test_expired_token_is_renewed(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "token.json"
            caminho.write_text(
                json.dumps(
                    {
                        "access_token": "TG-velho",
                        "refresh_token": "R-1",
                        "emitido_em": 0,
                    }
                ),
                encoding="utf-8",
            )
            chamadas = []

            def falso(refresh_token, client_id, client_secret):
                chamadas.append(refresh_token)
                return {
                    "access_token": "TG-novo",
                    "refresh_token": "R-2",
                    "expires_in": 21600,
                }

            original = ml_token.renovar
            ml_token.renovar = falso
            try:
                novo = ml_token.token_valido(caminho, "id", "segredo")
            finally:
                ml_token.renovar = original

            self.assertEqual("TG-novo", novo)
            self.assertEqual(["R-1"], chamadas)
            # O refresh_token novo substitui o antigo, senao a proxima
            # renovacao usaria um token ja consumido.
            self.assertEqual("R-2", ml_token.ler(caminho)["refresh_token"])

    def test_saved_state_records_when_it_was_issued(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "token.json"
            ml_token.gravar(caminho, {"access_token": "TG-1"})

            estado = ml_token.ler(caminho)
            self.assertAlmostEqual(estado["emitido_em"], int(time.time()), delta=5)


class AutorizacaoTest(unittest.TestCase):
    def test_url_asks_for_offline_access(self):
        """Sem offline_access nao vem refresh_token e a agenda quebra."""
        url = ml_token.url_de_autorizacao("123", "https://exemplo.com/cb")

        self.assertIn("offline_access", url)
        self.assertIn("client_id=123", url)
        self.assertIn("response_type=code", url)


if __name__ == "__main__":
    unittest.main()
