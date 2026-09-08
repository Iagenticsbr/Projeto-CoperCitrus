import unittest

from copercitrus_price_collector.models import ProductInput
from copercitrus_price_collector.product_analysis import (
    classificar_oferta,
    extrair_voltagem,
    mesma_funcao,
    similarity_score,
    termos_de_funcao,
    voltagem_compativel,
)
from copercitrus_price_collector.service import CollectionService


def _produto(descricao, marca="Jacto", modelo=None):
    return ProductInput(1, descricao, marca, modelo)


def _classificar(produto, titulo):
    return classificar_oferta(produto, titulo, similarity_score(produto, titulo))


class VoltagemTest(unittest.TestCase):
    def test_reads_declared_mains_voltage(self):
        self.assertEqual({"220"}, extrair_voltagem("Lavadora J6600 220V"))
        self.assertEqual({"127"}, extrair_voltagem("Esmerilhadeira 127 v"))

    def test_bivolt_wins_over_any_number(self):
        self.assertEqual({"bivolt"}, extrair_voltagem("Furadeira Bivolt 127/220"))

    def test_battery_voltage_is_not_mains(self):
        """20V de bateria nao pode ser lido como voltagem de rede."""
        self.assertEqual(set(), extrair_voltagem("Chave de impacto BAT20V"))

    def test_bivolt_serves_any_mains(self):
        self.assertTrue(voltagem_compativel({"220"}, {"bivolt"}))
        self.assertTrue(voltagem_compativel({"bivolt"}, {"127"}))

    def test_different_mains_voltages_do_not_match(self):
        self.assertFalse(voltagem_compativel({"220"}, {"127"}))

    def test_silence_does_not_disqualify(self):
        """Anuncio que omite a voltagem nao pode ser reprovado por omissao."""
        self.assertTrue(voltagem_compativel({"220"}, set()))
        self.assertTrue(voltagem_compativel(set(), {"127"}))


class FuncaoTest(unittest.TestCase):
    def test_function_terms_drop_brand_model_and_numbers(self):
        produto = _produto("LAVADORA ALTA PRESSAO J6600 220V")

        self.assertEqual(
            ["lavadora", "alta", "pressao"],
            termos_de_funcao(produto.produto, produto.marca),
        )

    def test_same_function_needs_every_term(self):
        produto = _produto("LAVADORA ALTA PRESSAO J6600 220V")

        self.assertTrue(mesma_funcao(produto, "Lavadora de Alta Pressao Jacto J7600"))
        self.assertFalse(mesma_funcao(produto, "Lavadora de Roupas Jacto"))


class ClassificacaoTest(unittest.TestCase):
    def test_same_model_is_compatible(self):
        produto = _produto("LAVADORA ALTA PRESSAO J6600 220V")

        self.assertEqual(
            "COMPATIVEL", _classificar(produto, "Lavadora Alta Pressao Jacto J6600 220v")
        )

    def test_other_model_same_function_is_similar(self):
        produto = _produto("LAVADORA ALTA PRESSAO J6600 220V")

        self.assertEqual(
            "SIMILAR", _classificar(produto, "Lavadora Alta Pressao Jacto J7600 220v")
        )

    def test_other_category_is_never_similar(self):
        """Foi assim que um pulverizador entrou como equivalente de lavadora."""
        produto = _produto("LAVADORA ALTA PRESSAO J6600 220V")

        self.assertEqual(
            "DIVERGENTE", _classificar(produto, "Pulverizador Costal Jacto PJH 20L")
        )

    def test_accessory_of_the_same_family_is_not_similar(self):
        produto = _produto("LAVADORA ALTA PRESSAO J6600 220V")

        self.assertEqual(
            "DIVERGENTE", _classificar(produto, "Bico Para Lavadora Jacto")
        )

    def test_wrong_voltage_is_not_similar(self):
        produto = _produto("LAVADORA ALTA PRESSAO J6600 220V")

        self.assertEqual(
            "DIVERGENTE", _classificar(produto, "Lavadora Alta Pressao Jacto J7600 127v")
        )


class Oferta:
    def __init__(self, score, tipo):
        self.similarity_score = score
        self.match_type = tipo
        self.loja_preferida = True


class FiltroTest(unittest.TestCase):
    def _servico(self, **extras):
        return CollectionService([], 5, 0.0, somente_exatos=True, **extras)

    def test_similar_stays_out_by_default(self):
        mantidas = self._servico()._filtrar([Oferta(58.0, "SIMILAR")])

        self.assertEqual([], mantidas)

    def test_similar_enters_when_asked(self):
        ofertas = [Oferta(58.0, "SIMILAR"), Oferta(20.0, "DIVERGENTE")]

        mantidas = self._servico(incluir_similares=True)._filtrar(ofertas)

        self.assertEqual([ofertas[0]], mantidas)

    def test_exact_still_passes_on_score(self):
        oferta = Oferta(91.0, "COMPATIVEL")

        self.assertEqual([oferta], self._servico()._filtrar([oferta]))


if __name__ == "__main__":
    unittest.main()


class DiscrepanciaTest(unittest.TestCase):
    def _ofertas(self, *precos, sku="A"):
        return [{"sku": sku, "preco": preco} for preco in precos]

    def test_price_far_below_the_median_is_flagged(self):
        from copercitrus_price_collector.validacao import marcar_discrepancias

        marcadas = marcar_discrepancias(self._ofertas(500, 520, 540, 12))

        self.assertEqual("abaixo", marcadas[-1]["alerta_preco"])
        self.assertEqual("", marcadas[0]["alerta_preco"])

    def test_price_far_above_the_median_is_flagged(self):
        from copercitrus_price_collector.validacao import marcar_discrepancias

        marcadas = marcar_discrepancias(self._ofertas(500, 520, 540, 4000))

        self.assertEqual("acima", marcadas[-1]["alerta_preco"])

    def test_normal_spread_is_not_flagged(self):
        from copercitrus_price_collector.validacao import marcar_discrepancias

        marcadas = marcar_discrepancias(self._ofertas(475, 499, 556, 589, 692))

        self.assertEqual([""] * 5, [item["alerta_preco"] for item in marcadas])

    def test_a_single_offer_cannot_be_judged(self):
        """Sem outra oferta do mesmo SKU nao ha com o que comparar."""
        from copercitrus_price_collector.validacao import marcar_discrepancias

        marcadas = marcar_discrepancias(self._ofertas(500))

        self.assertEqual("", marcadas[0]["alerta_preco"])

    def test_skus_are_judged_separately(self):
        from copercitrus_price_collector.validacao import marcar_discrepancias

        ofertas = self._ofertas(50, 55, 60, sku="barato") + self._ofertas(
            5000, 5200, 5400, sku="caro"
        )

        marcadas = marcar_discrepancias(ofertas)

        self.assertEqual([""] * 6, [item["alerta_preco"] for item in marcadas])

    def test_deviation_from_the_median_is_reported(self):
        from copercitrus_price_collector.validacao import marcar_discrepancias

        marcadas = marcar_discrepancias(self._ofertas(100, 200, 300))

        self.assertEqual(-50.0, marcadas[0]["desvio_mediana_pct"])
        self.assertEqual(50.0, marcadas[2]["desvio_mediana_pct"])

    def test_classification_counts_reach_the_panel(self):
        from copercitrus_price_collector.validacao import resumo_classificacao

        contagem = resumo_classificacao(
            [
                {"classificacao": "COMPATIVEL"},
                {"classificacao": "similar"},
                {"classificacao": None},
            ]
        )

        self.assertEqual(1, contagem["COMPATIVEL"])
        self.assertEqual(1, contagem["SIMILAR"])
        self.assertEqual(1, contagem["SEM CLASSE"])

    def test_a_common_discount_is_not_an_alert(self):
        """13% abaixo da mediana e desconto de loja, nao erro de coleta."""
        from copercitrus_price_collector.validacao import marcar_discrepancias

        marcadas = marcar_discrepancias(
            self._ofertas(432.16, 495.00, 499.55, 509.90, 511.48)
        )

        self.assertEqual([""] * 5, [item["alerta_preco"] for item in marcadas])

    def test_a_price_a_fifth_of_the_median_is_still_an_alert(self):
        from copercitrus_price_collector.validacao import marcar_discrepancias

        marcadas = marcar_discrepancias(
            self._ofertas(113.05, 386.01, 475.00, 499.00, 556.00)
        )

        self.assertEqual("abaixo", marcadas[0]["alerta_preco"])
