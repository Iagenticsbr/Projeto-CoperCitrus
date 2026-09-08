"""Marcacao de preco fora da curva e de link improvavel.

O painel compara preco entre lojas, entao um valor errado nao fica so errado:
ele desloca a media, alarga a amplitude e muda a conclusao sobre o SKU. Ja
apareceram tres origens de valor errado nesta base — anuncio de acessorio
vendido sob o nome do equipamento, preco em centavos vindo da API e kit com
quantidade diferente. Nenhuma delas se resolve olhando a oferta isolada; todas
aparecem quando a oferta e comparada com as outras do mesmo SKU.

Por isso a marcacao e relativa a mediana do proprio SKU, nao a um limite fixo:
um cortador de R$ 80 e barato, um trator de R$ 80 e um erro, e nenhuma regra
de valor absoluto separa os dois.

Marcar, nao remover. Quem olha o painel precisa ver que a oferta existe e por
que ela e suspeita; apagar em silencio esconderia tanto o erro de coleta
quanto a promocao real.
"""

from __future__ import annotations

from collections.abc import Iterable
from statistics import median

from .analytics import IQR_FACTOR, _quantile


# Abaixo disso a dispersao de tres ou quatro ofertas nao diz nada: o quartil
# cai em cima de uma unica observacao e qualquer diferenca vira "outlier".
MINIMO_PARA_QUARTIL = 5
# Fora dessa faixa em torno da mediana, a oferta e suspeita mesmo em amostra
# pequena. Metade ou o dobro do preco tipico raramente e o mesmo produto.
FATOR_BAIXO = 0.5
FATOR_ALTO = 2.0
# Distancia minima da mediana para a marcacao valer a pena.
#
# So o criterio de Tukey nao serve aqui. Num SKU com cinco ofertas quase
# iguais o intervalo interquartil fica minusculo e qualquer diferenca sai
# fora da cerca: um pulverizador a R$ 432 num grupo de mediana R$ 499 foi
# marcado como suspeito por 13% de diferenca, que e desconto comum de loja.
# Marcacao que dispara em preco normal treina quem le a ignorar.
DESVIO_MINIMO_PCT = 25.0


def _fences(precos: list[float]) -> tuple[float, float]:
    """Limites de Tukey, ou a faixa por fator quando a amostra e pequena."""
    ordenados = sorted(precos)
    meio = median(ordenados)
    if len(ordenados) < MINIMO_PARA_QUARTIL:
        return meio * FATOR_BAIXO, meio * FATOR_ALTO
    p25 = _quantile(ordenados, 0.25)
    p75 = _quantile(ordenados, 0.75)
    intervalo = p75 - p25
    if intervalo <= 0:
        return meio * FATOR_BAIXO, meio * FATOR_ALTO
    return p25 - IQR_FACTOR * intervalo, p75 + IQR_FACTOR * intervalo


def _preco(oferta: dict) -> float | None:
    valor = oferta.get("preco")
    if isinstance(valor, (int, float)) and valor > 0:
        return float(valor)
    return None


def marcar_discrepancias(ofertas: Iterable[dict]) -> list[dict]:
    """Devolve as ofertas com `alerta_preco` e `desvio_mediana_pct`.

    `alerta_preco` fica vazio quando o preco esta na faixa esperada, e traz
    "abaixo" ou "acima" quando esta fora. O desvio percentual acompanha para
    que quem olha decida: R$ 40 acima da mediana e ruido, R$ 4.000 nao e.
    """
    lista = [dict(oferta) for oferta in ofertas]
    por_sku: dict[object, list[float]] = {}
    for oferta in lista:
        preco = _preco(oferta)
        if preco is not None:
            por_sku.setdefault(oferta.get("sku"), []).append(preco)

    limites = {
        sku: _fences(precos) for sku, precos in por_sku.items() if len(precos) >= 2
    }
    medianas = {sku: median(precos) for sku, precos in por_sku.items()}

    for oferta in lista:
        oferta["alerta_preco"] = ""
        oferta["desvio_mediana_pct"] = None
        preco = _preco(oferta)
        sku = oferta.get("sku")
        if preco is None or sku not in medianas:
            continue
        meio = medianas[sku]
        if meio:
            oferta["desvio_mediana_pct"] = round((preco - meio) / meio * 100, 1)
        if sku not in limites:
            # Oferta unica no SKU nao tem com o que ser comparada. Dizer que
            # esta na faixa seria afirmar mais do que o dado sustenta.
            continue
        baixo, alto = limites[sku]
        desvio = abs(oferta["desvio_mediana_pct"] or 0.0)
        if desvio < DESVIO_MINIMO_PCT:
            continue
        if preco < baixo:
            oferta["alerta_preco"] = "abaixo"
        elif preco > alto:
            oferta["alerta_preco"] = "acima"
    return lista


def resumo_discrepancias(ofertas: Iterable[dict]) -> dict:
    """Contagem por tipo de alerta, para o painel exibir sem recalcular."""
    marcadas = list(ofertas)
    return {
        "abaixo": sum(1 for item in marcadas if item.get("alerta_preco") == "abaixo"),
        "acima": sum(1 for item in marcadas if item.get("alerta_preco") == "acima"),
        "total": len(marcadas),
    }


def resumo_classificacao(ofertas: Iterable[dict]) -> dict:
    """Quantas ofertas sao o produto pedido e quantas sao equivalentes.

    O painel mistura os dois de proposito — o similar de mesma funcao e mesma
    voltagem e alternativa real de compra — mas a media de um SKU muda
    conforme a proporcao, entao a contagem precisa estar visivel.
    """
    contagem = {"COMPATIVEL": 0, "SIMILAR": 0, "DIVERGENTE": 0, "SEM CLASSE": 0}
    for oferta in ofertas:
        classe = (oferta.get("classificacao") or "").strip().upper()
        contagem[classe if classe in contagem else "SEM CLASSE"] += 1
    return contagem


__all__ = [
    "marcar_discrepancias",
    "resumo_classificacao",
    "resumo_discrepancias",
]
