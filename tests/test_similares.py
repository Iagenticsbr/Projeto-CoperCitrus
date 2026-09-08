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


class CategoriaTest(unittest.TestCase):
    """A planilha tem SKU cuja descricao e um codigo de barras.

    A coluna de grupo diz a familia do item. Sem ela esse SKU nao tinha busca
    nenhuma; com ela, tem busca e mantem a funcao conhecida, que e o que
    impede casar com equipamento de outra categoria.
    """

    def _sem_nome(self):
        return ProductInput(
            3, "7909439011096", "Jacto", "1350764 JACTO", "1271261", None, "LAVADORAS"
        )

    def test_category_fills_in_for_a_barcode_description(self):
        from copercitrus_price_collector.product_analysis import descricao_efetiva

        self.assertEqual("LAVADORAS 7909439011096", descricao_efetiva(self._sem_nome()))

    def test_a_real_description_ignores_the_category(self):
        from copercitrus_price_collector.product_analysis import descricao_efetiva

        produto = ProductInput(
            4, "LAVADORA ALTA PRESSAO J6600 220V", "Jacto", None, "1271265", None,
            "LAVADORAS",
        )

        self.assertEqual("LAVADORA ALTA PRESSAO J6600 220V", descricao_efetiva(produto))

    def test_plural_category_matches_the_singular_title(self):
        produto = self._sem_nome()
        titulo = "Lavadora De Alta Pressao Jacto J6000 Plus"

        self.assertGreater(similarity_score(produto, titulo), 70.0)

    def test_another_category_is_still_rejected(self):
        produto = self._sem_nome()

        self.assertEqual(
            "DIVERGENTE", _classificar(produto, "Pulverizador Costal Jacto PJH 20L")
        )

    def test_the_brand_alone_matches_nothing(self):
        produto = self._sem_nome()

        self.assertEqual("DIVERGENTE", _classificar(produto, "Trator Jacto"))

    def test_without_a_model_the_offer_is_never_exact(self):
        """Da para dizer que e uma lavadora Jacto, nao qual delas."""
        produto = self._sem_nome()

        self.assertEqual(
            "SIMILAR", _classificar(produto, "Lavadora De Alta Pressao Jacto J6000 Plus")
        )

    def test_an_accessory_is_not_a_similar(self):
        produto = self._sem_nome()

        self.assertEqual("DIVERGENTE", _classificar(produto, "Bico Para Lavadora Jacto"))

    def test_a_spare_part_of_the_right_product_is_not_similar(self):
        produto = ProductInput(9, "PULVERIZADOR COSTAL PJH", "Jacto", "825398 JACTO")

        self.assertEqual(
            "DIVERGENTE", _classificar(produto, "Cilindro Pulverizador Costal Jacto PJH")
        )


class MarcaEEmbalagemTest(unittest.TestCase):
    """Casos reais da coleta de 08/09 que entraram errado."""

    def _lavadora(self):
        return ProductInput(
            6, "LAVADORA ALTA PRESSAO J6600 127V", "Jacto", "1350766 JACTO"
        )

    def test_a_competing_brand_is_not_similar(self):
        """Uma Karcher de R$ 2.550 entrou como similar de uma Jacto."""
        produto = self._lavadora()

        self.assertEqual(
            "DIVERGENTE",
            _classificar(produto, "Lavadora De Alta Pressao Karcher Hd-585"),
        )

    def test_the_same_brand_is_still_similar(self):
        produto = self._lavadora()

        self.assertEqual(
            "SIMILAR",
            _classificar(produto, "Lavadora Alta Pressao Residencial Stop Total Jacto"),
        )

    def test_an_offer_without_a_brand_is_not_rejected(self):
        """Muito vendedor escreve so o modelo; reprovar por omissao perde oferta."""
        produto = self._lavadora()

        self.assertEqual(
            "SIMILAR", _classificar(produto, "Lavadora Alta Pressao Residencial 1400w")
        )

    def test_a_different_kit_size_is_not_similar(self):
        produto = ProductInput(9, "JG FERRAMENTAS C/110PCS", "Vonder", None)

        self.assertEqual(
            "DIVERGENTE",
            _classificar(produto, "Jogo Ferramentas Com 5 Pecas Jfn 046 Vonder"),
        )

    def test_the_same_kit_size_stays(self):
        """Mesma marca e mesma contagem de pecas: e o produto pedido."""
        produto = ProductInput(9, "JG FERRAMENTAS C/110PCS", "Vonder", None)

        self.assertEqual(
            "COMPATIVEL",
            _classificar(produto, "Berco Eva Jogo Ferramentas 110pcs Vonder Carrinho"),
        )

    def test_a_strap_is_an_accessory(self):
        """R$ 47,90 de cinta entrou como o pulverizador de R$ 500."""
        produto = ProductInput(8, "PULVERIZADOR COSTAL PJH", "Jacto", "825398 JACTO")

        self.assertEqual(
            "DIVERGENTE",
            _classificar(produto, "1 Par De Cinta Para Pulverizador Costal Jacto Pjh"),
        )

    def test_a_detergent_applicator_is_an_accessory(self):
        produto = ProductInput(
            3, "7909439011096", "Jacto", "1350764 JACTO", "1271261", None, "LAVADORAS"
        )

        self.assertEqual(
            "DIVERGENTE",
            _classificar(produto, "Aplicador Ejetor Detergente Lavadoras Jacto J6000"),
        )

    def test_a_three_phase_machine_is_another_class(self):
        """A J7600 trifasica de R$ 7.999 entrava como similar de uma de R$ 895."""
        produto = ProductInput(
            4, "LAVADORA ALTA PRESSAO J6000 PLUS 220V", "Jacto", "1350759 JACTO"
        )

        self.assertEqual(
            "DIVERGENTE",
            _classificar(produto, "Lavadora Alta Pressao Jacto J7600 Trifasica"),
        )

    def test_accented_piece_count_is_read(self):
        """O anuncio escreve "5 Pecas" com cedilha; o padrao sem acento falhava."""
        from copercitrus_price_collector.product_analysis import (
            extract_package_quantity,
        )

        self.assertEqual("5 un", extract_package_quantity("Jogo Ferramentas 5 Peças"))
