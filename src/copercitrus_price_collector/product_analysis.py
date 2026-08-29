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
    "avaliac", "compar", "cupom", "desconto", "devoluc", "economize",
    "entrega", "estoque", "frete", "gratis", "mes x", "oferta", "parcel",
    "patrocinado", "promoc", "similar", "usado", "ver mais", "vendas",
)
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
        TOKEN_SYNONYMS.get(token, token)
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
    requested = build_search_terms(product.produto, product.marca, product.modelo)
    requested_normalized = normalize_text(requested)
    found_normalized = normalize_text(found_title)
    if not requested_normalized or not found_normalized:
        return 0.0

    requested_tokens = set(match_tokens(requested))
    found_tokens = set(match_tokens(found_title))
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
