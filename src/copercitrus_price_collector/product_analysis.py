"""Normalizacao e classificacao dos produtos encontrados pelo RPA."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import ProductInput


STOP_WORDS = {
    "a",
    "as",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "o",
    "os",
    "para",
    "por",
}


# Abreviacoes usadas nas descricoes de retail da CoperCitrus. Sao expandidas
# apenas quando o significado e inequivoco; o resto do texto e preservado.
ABBREVIATIONS = {
    "aut": "automatica",
    "bat": "bateria",
    "dig": "digital",
    "esmerilh": "esmerilhadeira",
    "ferram": "ferramentas",
    "jg": "jogo",
    "lavad": "lavadora",
    "parafus": "parafusadeira",
    "press": "pressao",
    "pulveriz": "pulverizador",
    "qtde": "",
    "un": "",
}

# Sufixos de fornecedor/cadastro que aparecem coladas na descricao e nao
# existem em anuncio nenhum. Removidas antes de montar a consulta.
SUPPLIER_TAGS = {"vd", "vonder vd", "bem", "fech", "nove54 vd"}


def _clean_fragment(value: str | None) -> str:
    """Remove espaco nao separavel, barras e ruido tipografico da planilha."""
    text = (value or "").replace(" ", " ").replace(" ", " ")
    text = text.replace("/", " ").replace("\\", " ")
    text = re.sub(r'["“”]', " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_search_terms(
    produto: str | None,
    marca: str | None = None,
    modelo: str | None = None,
) -> str:
    """Monta a consulta enviada ao marketplace.

    Junta descricao, marca e codigo do fabricante, expande abreviacoes de
    retail, remove tags internas de fornecedor e nao repete a marca.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for fragment in (produto, modelo, marca):
        for raw in _clean_fragment(fragment).split():
            token = raw.strip(".,;:-")
            if not token:
                continue
            key = normalize_text(token)
            if not key or key in SUPPLIER_TAGS:
                continue
            if len(key) == 1 and key.isalpha():
                continue
            expanded = ABBREVIATIONS.get(key, token)
            if not expanded:
                continue
            expanded_key = normalize_text(expanded)
            if expanded_key in seen:
                continue
            seen.add(expanded_key)
            tokens.append(expanded)
    return " ".join(tokens)


def _sem_valor_descritivo(descricao: str | None, marca: str | None) -> bool:
    """Diz se a descricao nao identifica produto nenhum sozinha.

    Descricao que so tem marca, numero de cadastro ou codigo de barras casa
    com qualquer item daquela marca. Foi o que deixou um pulverizador entrar
    como equivalente de uma lavadora.
    """
    da_marca = set(match_tokens(marca)) if marca else set()
    uteis = [
        token
        for token in match_tokens(descricao)
        if token not in da_marca
        and token not in STOP_WORDS
        and not (token.isdigit() and len(token) >= 6)
        and len(token) >= 3
    ]
    return len(uteis) < 2


def descricao_efetiva(product: ProductInput) -> str:
    """Descricao utilizavel do item pedido.

    Normalmente e a propria descricao da planilha. Quando ela nao identifica
    nada — o SKU 1271261 tem "7909439011096" no lugar do nome — entra a
    categoria da planilha, que diz a familia do item ("LAVADORAS"). Nao e o
    nome exato, mas transforma um SKU impossivel de buscar em um SKU
    buscavel, e mantem a funcao conhecida, que e o que impede casar com
    equipamento de outra categoria.
    """
    categoria = getattr(product, "categoria", None)
    if categoria and _sem_valor_descritivo(product.produto, product.marca):
        return f"{categoria} {product.produto}"
    return product.produto


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.casefold())).strip()


def parse_price(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d[\d.\s]*(?:,\d{1,2})?|\d+(?:\.\d{1,2})", value)
    if not match:
        return None
    number = match.group(0).replace(" ", "")
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")
    elif "." in number and len(number.rsplit(".", 1)[1]) == 3:
        number = number.replace(".", "")
    try:
        return float(number)
    except ValueError:
        return None


def extract_package_quantity(text: str | None) -> str | None:
    if not text:
        return None
    patterns = (
        r"\b(?:kit|pack|caixa|fardo)\s*(?:com|c/|de)?\s*(\d{1,4})\s*(?:unidades?|un\.?|pcs?)?\b",
        r"\b(\d{1,4})\s*(?:unidades?|un\.?|pcs?|pecas?)\b",
        r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|mg|l|ml)\b",
        r"\b(\d{1,3})\s*[xX]\b",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if index == 2:
            return f"{match.group(1)} {match.group(2).lower()}"
        return f"{match.group(1)} un"
    return None


# Linhas do card que nao sao nome de loja. O Google intercala politica de
# entrega, parcelamento e selos entre o preco e o nome do vendedor.
SELLER_NOISE = (
    "a partir de", "avaliac", "cashback", "compar", "cupom", "de volta",
    "desconto", "devoluc", "economize", "em ate", "entrega", "estoque",
    "frete", "gratis", "juros", "loja toda", "mes x", "no pix", "oferta",
    "parcel", "patrocinado", "promoc", "similar", "usado", "ver mais",
    "vendas", "vendido e entregue",
)

# Dominio do anuncio identifica o marketplace com certeza. O nome escrito no
# card e menos confiavel: comparador exibe promocao no lugar do vendedor.
MARKETPLACES = (
    ("mercadolivre", "Mercado Livre"),
    ("mercadolibre", "Mercado Livre"),
    ("produto.mercadolivre", "Mercado Livre"),
    ("shopee", "Shopee"),
    ("amazon", "Amazon"),
    ("magazineluiza", "Magalu"),
    ("magalu", "Magalu"),
    ("americanas", "Americanas"),
    ("casasbahia", "Casas Bahia"),
    ("pontofrio", "Ponto"),
    ("leroymerlin", "Leroy Merlin"),
    ("madeiramadeira", "MadeiraMadeira"),
    ("lojadomecanico", "Loja do Mecanico"),
    ("aliexpress", "AliExpress"),
    ("shoptime", "Shoptime"),
    ("carrefour", "Carrefour"),
)


def normalizar_loja(nome: str | None) -> str | None:
    """Reduz o vendedor ao nome do marketplace.

    O anuncio traz "Mercado Livre (JACTO por Magazine Brasileiro Loja
    oficial)", que fragmenta o mesmo canal em dezenas de rotulos e torna
    qualquer agregacao por loja inutil. O que interessa e o canal.
    """
    if not nome:
        return None
    normalizado = normalize_text(nome)
    for _, marketplace in MARKETPLACES:
        if normalize_text(marketplace) in normalizado:
            return marketplace
    return nome.strip() or None


def identificar_marketplace(url: str | None) -> str | None:
    """Nome do marketplace a partir do dominio do anuncio."""
    if not url:
        return None
    endereco = normalize_text(url)
    for fragmento, nome in MARKETPLACES:
        if fragmento in endereco:
            return nome
    return None
SELLER_PREFIX = "vendido por"


def extract_seller(raw_text: str | None) -> str | None:
    """Nome da loja a partir do texto do card.

    O Google ofusca as classes do card, mas mantem a ordem visivel: titulo,
    precos e entao o vendedor. Ler a linha e mais estavel do que perseguir
    seletor gerado.
    """
    if not raw_text:
        return None
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    for line in lines:
        normalized = normalize_text(line)
        if normalized.startswith(SELLER_PREFIX):
            candidate = line[len(SELLER_PREFIX):].strip(" :-")
            if candidate:
                return candidate
    first_price = next(
        (index for index, line in enumerate(lines) if "R$" in line), None
    )
    if first_price is None:
        return None
    for line in lines[first_price + 1:]:
        if "R$" in line or len(line) > 40:
            continue
        # Valor de parcelamento aparece sem o simbolo da moeda ("1.499") e
        # entrava como nome de loja. Nome de loja tem letra.
        if not re.search(r"[a-zA-Z]", line):
            continue
        # Contagem de vendedores do comparador ("em 3 lojas", "1 loja") ocupa
        # a mesma posicao do vendedor no card e nao e nome de ninguem.
        if re.fullmatch(r"(em\s+)?\d+\s+lojas?", normalize_text(line)):
            continue
        normalized = normalize_text(line)
        if not normalized or any(noise in normalized for noise in SELLER_NOISE):
            continue
        return line
    return None


def identify_brand(title: str, requested_brand: str | None) -> str | None:
    normalized_title = normalize_text(title)
    if requested_brand and normalize_text(requested_brand) in normalized_title:
        return requested_brand.strip()
    explicit = re.search(
        r"\bmarca\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9._-]{1,30})",
        title,
        flags=re.IGNORECASE,
    )
    return explicit.group(1) if explicit else None


# Sinonimos de retail: a planilha abrevia, o anuncio escreve por extenso.
TOKEN_SYNONYMS = {
    "jg": "jogo",
    "kit": "jogo",
    "pc": "pecas",
    "pcs": "pecas",
    "peca": "pecas",
    "pecs": "pecas",
    "un": "unidade",
    "unid": "unidade",
    "und": "unidade",
    "volts": "v",
}


def _singular(token: str) -> str:
    """Reduz plural simples ao singular.

    A planilha nomeia a familia no plural ("LAVADORAS", "ESMERILHADEIRAS") e
    o anuncio escreve o produto no singular. Sem isso os dois nunca casam,
    ainda que digam a mesma coisa. So o "s" final, e so em palavra longa:
    cortar mais que isso erraria em "gas", "pcs" e codigo de modelo.
    """
    if len(token) >= 6 and token.endswith("s") and not token[-2].isdigit():
        return token[:-1]
    return token


def match_tokens(value: str | None) -> list[str]:
    """Tokens comparaveis de um texto.

    Separa numero de letra ("110pcs" vira "110" e "pcs", "bat20v" vira
    "bat", "20" e "v") e aplica sinonimos, senao o codigo colado da planilha
    nunca casa com o titulo escrito por extenso no anuncio.
    """
    normalized = normalize_text(value)
    if not normalized:
        return []
    split = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", normalized)
    return [
        TOKEN_SYNONYMS.get(token, _singular(token))
        for token in split.split()
        if token not in STOP_WORDS
    ]


# Peca de reposicao carrega o nome do equipamento no titulo ("Cilindro
# Pulverizador Costal Jacto PJH"), entao a cobertura de tokens sobe e o
# acessorio de R$ 25,90 passava como SIMILAR do equipamento de R$ 900.
ACCESSORY_TERMS = {
    "adaptador",
    "bico",
    "bomba",
    "cabecote",
    "camara",
    "capa",
    "carvao",
    "cilindro",
    "conexao",
    "correia",
    "diafragma",
    "engate",
    "escova",
    "filtro",
    "gatilho",
    "gaxeta",
    "lanca",
    "mangueira",
    "mola",
    "oring",
    "pistao",
    "registro",
    "reparo",
    "reposicao",
    "retentor",
    "rolamento",
    "valvula",
    "vedacao",
}
ACCESSORY_PENALTY = 0.5


def is_accessory(requested_tokens: set[str], found_title: str) -> bool:
    """Titulo de peca/acessorio quando o pedido e do equipamento inteiro."""
    found = set(match_tokens(found_title))
    return bool((found & ACCESSORY_TERMS) - requested_tokens)


def similarity_score(product: ProductInput, found_title: str) -> float:
    """Percentual de aderencia entre o item pedido e o anuncio encontrado.

    Usa cobertura (quanto do pedido aparece no anuncio) em vez de Jaccard:
    titulo de marketplace e longo e o denominador da uniao punia justamente
    os anuncios corretos e mais descritivos.
    """
    requested = build_search_terms(
        descricao_efetiva(product), product.marca, product.modelo
    )
    requested_normalized = normalize_text(requested)
    found_normalized = normalize_text(found_title)
    if not requested_normalized or not found_normalized:
        return 0.0

    requested_tokens = set(match_tokens(requested))
    found_tokens = set(match_tokens(found_title))
    # Codigo de cadastro do fabricante (so digitos, longo) nao aparece no
    # titulo do anuncio: nenhum vendedor escreve "6878125125". Mantido na
    # cobertura, ele punia justamente o produto certo. Codigo de modelo
    # alfanumerico (IM125, J6600, DWE4120B2B) continua contando, porque esse
    # o anuncio escreve.
    descritivos = {
        token
        for token in requested_tokens
        if not (token.isdigit() and len(token) >= 6)
    }
    marca_tokens = set(match_tokens(product.marca)) if product.marca else set()
    # Sem nenhum termo descritivo alem da marca, a consulta nao identifica
    # produto nenhum: qualquer item daquela marca casaria 100%. Foi assim que
    # um pulverizador entrou como equivalente de uma lavadora, num SKU cuja
    # descricao na planilha e so um codigo de barras.
    #
    # Um termo basta, desde que diga o que o produto e. "lavadora" sozinho ja
    # separa lavadora de pulverizador, que era o erro a evitar; exigir dois
    # descartava o SKU inteiro em vez de corrigi-lo.
    if not descritivos - marca_tokens:
        return 0.0
    if descritivos:
        requested_tokens = descritivos
    if not requested_tokens:
        return 0.0

    coverage = len(requested_tokens & found_tokens) / len(requested_tokens)
    sequence_score = SequenceMatcher(None, requested_normalized, found_normalized).ratio()
    score = (coverage * 70.0) + (sequence_score * 15.0)

    # Codigo alfanumerico (IM125, J6600, DWE4120B2B) e o sinal mais forte de
    # que o anuncio e o mesmo item, nao um parente dele.
    codes = {
        token
        for token in requested_tokens
        if len(token) > 2 and any(c.isdigit() for c in token) and any(c.isalpha() for c in token)
    }
    if codes and codes <= found_tokens:
        score += 15.0
    if product.marca and set(match_tokens(product.marca)) <= found_tokens:
        score += 5.0
    if is_accessory(requested_tokens, found_title):
        score *= ACCESSORY_PENALTY
    return round(min(score, 100.0), 1)


def classify_match(score: float) -> str:
    if score >= 80.0:
        return "COMPATIVEL"
    if score >= 50.0:
        return "SIMILAR"
    return "DIVERGENTE"


# Voltagem declarada no texto. Rede (127/220/380) e bateria (12/18/20/24) sao
# lidas juntas porque a planilha as escreve do mesmo jeito, mas comparadas so
# entre iguais: 20V de bateria nao contradiz 220V de rede.
VOLTAGENS_REDE = {"110", "127", "220", "380"}
BIVOLT = {"bivolt", "biv"}


def extrair_voltagem(texto: str | None) -> set[str]:
    """Voltagens de rede declaradas no texto, ou {'bivolt'}."""
    if not texto:
        return set()
    normalizado = normalize_text(texto)
    if any(marca in normalizado for marca in BIVOLT):
        return {"bivolt"}
    achadas = set()
    for numero in re.findall(r"\b(\d{3})\s*v\b", normalizado):
        if numero in VOLTAGENS_REDE:
            achadas.add(numero)
    return achadas


def voltagem_compativel(pedida: set[str], ofertada: set[str]) -> bool:
    """Bivolt atende qualquer rede; ausencia de declaracao nao reprova.

    Nao dava para exigir declaracao dos dois lados: muito anuncio omite a
    voltagem, e reprovar por omissao descartaria oferta boa.
    """
    if not pedida or not ofertada:
        return True
    if "bivolt" in pedida or "bivolt" in ofertada:
        return True
    return bool(pedida & ofertada)


def termos_de_funcao(produto: str | None, marca: str | None = None) -> list[str]:
    """O que o produto e, sem marca, modelo nem especificacao numerica.

    "LAVADORA ALTA PRESSAO J6600 220V" vira ["lavadora", "alta", "pressao"].
    E isso que define se duas ofertas sao do mesmo tipo de equipamento.
    """
    da_marca = set(match_tokens(marca)) if marca else set()
    termos = []
    for token in match_tokens(produto):
        if token in da_marca or token in STOP_WORDS:
            continue
        if any(c.isdigit() for c in token) or len(token) < 4:
            continue
        termos.append(token)
        if len(termos) == 3:
            break
    return termos


def mesma_funcao(produto: ProductInput, titulo: str) -> bool:
    """O anuncio e do mesmo tipo de equipamento que o item pedido."""
    termos = termos_de_funcao(descricao_efetiva(produto), produto.marca)
    if not termos:
        return False
    do_titulo = set(match_tokens(titulo))
    return all(termo in do_titulo for termo in termos)


def codigos_de_modelo(texto: str | None) -> set[str]:
    """Codigos alfanumericos do texto: J6600, DWE4120B2B, CIV200B.

    Extraidos antes de tokenizar de proposito: `match_tokens` separa letra de
    digito e transformaria DWE4120 em "dwe" + "4120", que casa com qualquer
    outro DWE.
    """
    if not texto:
        return set()
    normalizado = normalize_text(texto.replace("-", " ").replace("/", " "))
    return {
        token
        for token in re.findall(r"[a-z]+\d[a-z\d]*|\d+[a-z]+[a-z\d]*", normalizado)
        # "220v" tem forma de codigo e aparecia em J6600 e J7600 igual, o que
        # fazia dois modelos diferentes parecerem o mesmo produto.
        if len(token) >= 4 and not re.fullmatch(r"\d{2,3}v", token)
    }


def classificar_oferta(
    produto: ProductInput, titulo: str, pontuacao: float, corte_exato: float = 70.0
) -> str:
    """Classifica em COMPATIVEL, SIMILAR ou DIVERGENTE.

    SIMILAR tem definicao estreita de proposito: mesma funcao e mesma
    voltagem. Sem isso, "similar" viraria qualquer item da mesma marca — foi
    assim que um pulverizador entrou como equivalente de uma lavadora.
    """
    # Peca de reposicao carrega o nome do equipamento no titulo, entao ela
    # passa no teste de funcao: "Bico Para Lavadora Jacto" e mesma funcao que
    # "Lavadora Jacto" para qualquer comparacao de texto. Nao e alternativa
    # de compra nenhuma, entao nao entra nem como similar.
    if set(match_tokens(titulo)) & ACCESSORY_TERMS:
        return "DIVERGENTE"
    pedidos = codigos_de_modelo(f"{descricao_efetiva(produto)} {produto.modelo or ''}")
    ofertados = codigos_de_modelo(titulo)
    # J6600 e J7600 dividem nome, funcao e voltagem: a pontuacao de texto
    # sozinha dava 83% e chamava os dois de mesmo produto. Codigo declarado
    # nos dois lados e sem interseccao decide contra.
    outro_modelo = bool(pedidos and ofertados and not (pedidos & ofertados))
    # SKU identificado so pela categoria da planilha nao tem modelo conhecido:
    # da para afirmar que e uma lavadora Jacto, nao qual delas. Chamar de
    # exato seria afirmar mais do que a planilha diz.
    sem_nome_proprio = descricao_efetiva(produto) != produto.produto
    if pontuacao >= corte_exato and not outro_modelo and not sem_nome_proprio:
        return "COMPATIVEL"
    if mesma_funcao(produto, titulo) and voltagem_compativel(
        extrair_voltagem(f"{produto.produto} {produto.modelo or ''}"),
        extrair_voltagem(titulo),
    ):
        return "SIMILAR"
    return "DIVERGENTE"
