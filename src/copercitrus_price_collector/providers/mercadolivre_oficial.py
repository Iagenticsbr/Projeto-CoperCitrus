"""Mercado Livre pela API oficial, sem custo por busca.

O caminho nao e o obvio. A busca de anuncios (`/sites/MLB/search`) e o detalhe
de item (`/items/{id}`) respondem 403 para aplicacao sem parceria aprovada. O
que responde e o catalogo:

    /products/search      identifica o produto, com marca e modelo em campo
    /products/{id}/items  lista as ofertas daquele produto, com preco

A vantagem sobre raspagem nao e so o custo zero. O catalogo devolve BRAND e
MODEL como atributo estruturado, entao a identificacao do produto deixa de
depender de interpretar o titulo do anuncio — que foi a origem da maioria dos
erros de casamento deste projeto.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from ..errors import ConfigurationError, ProviderError
from ..models import ProductInput, SearchResult
from ..product_analysis import (
    classificar_oferta,
    codigos_de_modelo,
    descricao_efetiva,
    extract_package_quantity,
    normalize_text,
    similarity_score,
    termos_de_funcao,
)


BASE = "https://api.mercadolibre.com"
TEMPO_LIMITE_SEGUNDOS = 45
# Quantos produtos do catalogo abrir por consulta. Cada um custa uma chamada
# extra para listar as ofertas, entao vale limitar. Com similares ligados o
# alvo deixa de ser um produto so: os modelos vizinhos da mesma familia estao
# justamente nas posicoes seguintes da busca do catalogo.
PRODUTOS_POR_CONSULTA = 8

# Unidade de medida colada no numero tem forma de codigo de modelo, mas
# procurar por "900w" ou "20v" devolve o catalogo inteiro.
_UNIDADES = ("w", "v", "a", "ah", "mm", "cm", "kg", "ml", "l", "psi", "rpm",
             "pcs", "nm", "pol", "cv", "hp", "lbs")


def _e_especificacao(token: str) -> bool:
    """Diz se o token e medida, nao identificacao de modelo."""
    return bool(re.fullmatch(r"\d+(?:" + "|".join(_UNIDADES) + r")", token))


class MercadoLivreOficialProvider:
    name = "Mercado Livre"
    requires_browser = False

    def __init__(self, browser) -> None:
        self.settings = getattr(browser, "settings", browser)

    def _token(self) -> str:
        token = getattr(self.settings, "ml_token", None)
        if not token:
            raise ConfigurationError(
                "Defina ML_TOKEN para coletar pela API oficial do Mercado Livre"
            )
        return token

    def _get(self, caminho: str, parametros: dict | None = None) -> dict:
        url = f"{BASE}{caminho}"
        if parametros:
            url = f"{url}?{urllib.parse.urlencode(parametros)}"
        requisicao = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self._token()}"}
        )
        try:
            with urllib.request.urlopen(
                requisicao, timeout=TEMPO_LIMITE_SEGUNDOS
            ) as resposta:
                return json.loads(resposta.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise ProviderError(
                    f"{self.name}: token recusado ou sem permissao ({exc.code}). "
                    "O token expira em 6 horas."
                ) from exc
            if exc.code == 404:
                return {}
            raise ProviderError(
                f"{self.name}: a API respondeu {exc.code} em {caminho}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                f"{self.name}: nao foi possivel alcancar a API ({exc.reason})"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"{self.name}: resposta nao e JSON") from exc

    def search(self, product: ProductInput, limit: int) -> list[SearchResult]:
        """Procura o produto no catalogo, da consulta mais especifica a mais ampla.

        Uma consulta so nao serve. A busca do catalogo pondera o texto inteiro,
        entao a descricao completa da planilha afoga o codigo do modelo: com
        "INVERSOR digital MASCARA automatica IM125 VONDER" o produto certo nao
        aparecia, e com "IM125" ele e o primeiro resultado. O mesmo valeu para
        CIV200B. Eram quatro SKUs dados como inexistentes no catalogo que na
        verdade estavam la.
        """
        # Reunir os candidatos de todas as consultas antes de buscar preco.
        # Parar na primeira consulta que enchesse o limite gastava as vagas com
        # o resultado ruim da consulta mais especifica e nunca chegava na
        # consulta que achava o produto certo.
        candidatos: dict[str, dict] = {}
        for consulta in self._consultas(product):
            catalogo = self._get(
                "/products/search",
                {"status": "active", "site_id": "MLB", "q": consulta},
            )
            for produto in (catalogo.get("results") or [])[:PRODUTOS_POR_CONSULTA]:
                identificador = produto.get("id")
                if identificador:
                    candidatos.setdefault(identificador, produto)

        # Buscar oferta so dos melhores: cada produto custa uma chamada extra,
        # e o catalogo devolve muito parente distante.
        avaliados = sorted(
            (
                (self._pontuar(product, produto, (produto.get("name") or "")), produto)
                for produto in candidatos.values()
            ),
            key=lambda par: par[0],
            reverse=True,
        )
        resultados: list[SearchResult] = []
        for _, produto in avaliados[:PRODUTOS_POR_CONSULTA]:
            if len(resultados) >= limit:
                break
            resultados.extend(
                self._ofertas_do_produto(product, produto, limit - len(resultados))
            )
        return resultados

    @staticmethod
    def _consultas(product: ProductInput) -> list[str]:
        """Variantes de consulta, da mais discriminante para a mais ampla."""
        descricao = descricao_efetiva(product)
        marca = (product.marca or "").split()[0].strip()
        codigos = [
            codigo
            for codigo in codigos_de_modelo(f"{descricao} {product.modelo or ''}")
            if not _e_especificacao(codigo)
        ]
        variantes: list[str] = []
        # Codigo primeiro, sozinho: e o termo que identifica o modelo exato.
        for codigo in sorted(codigos, key=len, reverse=True):
            variantes.append(codigo.upper())
            if marca:
                variantes.append(f"{codigo.upper()} {marca}")
        variantes.append(product.query)
        # Por ultimo a funcao com a marca, que acha o parente quando o modelo
        # exato nao esta catalogado.
        funcao = " ".join(termos_de_funcao(descricao, product.marca))
        if funcao:
            variantes.append(f"{funcao} {marca}".strip())
        vistas: set[str] = set()
        return [
            variante
            for variante in variantes
            if variante and not (variante.casefold() in vistas or vistas.add(variante.casefold()))
        ]

    def _ofertas_do_produto(
        self, product: ProductInput, produto: dict, restantes: int
    ) -> list[SearchResult]:
        nome = (produto.get("name") or "").strip()
        if not nome:
            return []
        pontuacao = self._pontuar(product, produto, nome)
        classe = classificar_oferta(product, self._texto_do_catalogo(produto, nome), pontuacao)
        listagem = self._get(f"/products/{produto['id']}/items", {"limit": 10})
        ofertas: list[SearchResult] = []
        for posicao, item in enumerate((listagem.get("results") or []), 1):
            preco = item.get("price")
            if not isinstance(preco, (int, float)) or preco <= 0:
                continue
            ofertas.append(
                self._mapear(produto, item, nome, float(preco), pontuacao, classe, posicao)
            )
            if len(ofertas) >= restantes:
                break
        return ofertas

    def _texto_do_catalogo(self, produto: dict, nome: str) -> str:
        """Nome mais atributos, para julgar funcao e voltagem.

        A voltagem raramente aparece no nome do catalogo; costuma estar em
        atributo proprio. Sem juntar os dois, todo produto pareceria omissa
        a voltagem e a regra nunca reprovaria nada.
        """
        atributos = produto.get("attributes", [])
        extras = " ".join(
            (item.get("value_name") or "")
            for item in atributos
            if item.get("id")
            in {"BRAND", "MODEL", "VOLTAGE", "INPUT_VOLTAGE", "POWER"}
        )
        return f"{nome} {extras}".strip()

    def _pontuar(self, product: ProductInput, produto: dict, nome: str) -> float:
        """Similaridade usando os atributos do catalogo quando existem.

        Marca e modelo vem como campo, entao entram na comparacao sem depender
        de interpretar o titulo. O texto do nome continua valendo para o resto.
        """
        atributos = {
            item.get("id"): (item.get("value_name") or "")
            for item in produto.get("attributes", [])
        }
        marca = atributos.get("BRAND", "")
        modelo = atributos.get("MODEL", "")
        base = similarity_score(product, f"{nome} {marca} {modelo}")
        # Modelo do catalogo batendo com o modelo pedido e evidencia forte.
        pedido = normalize_text(f"{product.modelo or ''} {product.produto}")
        if modelo and normalize_text(modelo) in pedido:
            base = min(base + 15.0, 100.0)
        return round(base, 1)

    @staticmethod
    def _endereco(produto: dict, item: dict) -> str:
        """Endereco do anuncio, sem inventar formato de URL.

        A versao anterior montava `MLB-1234567890` cortando o identificador
        em duas partes. O endereco ate abria, mas era um palpite sobre o
        formato do Mercado Livre e nao havia como conferir se levava ao
        anuncio certo. Aqui a ordem e: o permalink que a API devolver; senao
        a pagina do produto no catalogo, que e exatamente o produto cujo nome
        aparece no painel. Palpite, nenhum.
        """
        permalink = item.get("permalink") or item.get("item_permalink")
        if isinstance(permalink, str) and permalink.startswith("http"):
            return permalink
        identificador = produto.get("id")
        if identificador:
            return f"https://www.mercadolivre.com.br/p/{identificador}"
        return ""

    def _mapear(
        self,
        produto: dict,
        item: dict,
        nome: str,
        preco: float,
        pontuacao: float,
        classe: str,
        posicao: int,
    ) -> SearchResult:
        atributos = {
            entrada.get("id"): (entrada.get("value_name") or "")
            for entrada in produto.get("attributes", [])
        }
        cheio = item.get("original_price")
        imagens = produto.get("pictures") or []
        return SearchResult(
            provider=self.name,
            rank=posicao,
            title=nome,
            description=(
                "Novo" if item.get("condition") == "new" else item.get("condition") or nome
            ),
            price_min=round(preco, 2),
            price_max=round(float(cheio), 2) if isinstance(cheio, (int, float)) and cheio > preco else round(preco, 2),
            currency=item.get("currency_id") or "BRL",
            purchase_url=self._endereco(produto, item),
            brand=atributos.get("BRAND") or None,
            package_quantity=extract_package_quantity(nome),
            similarity_score=pontuacao,
            match_type=classe,
            seller=self.name,
            image_url=(imagens[0].get("url") if imagens and isinstance(imagens[0], dict) else None),
            loja_preferida=True,
        )
