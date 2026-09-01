"""Renovacao do token do Mercado Livre.

O token vive 6 horas. A coleta mensal roda sozinha, entao ninguem estara na
frente da tela para reautorizar: sem renovacao automatica, a segunda execucao
falharia com 403 e o painel pararia de receber dado sem explicacao.

A renovacao acontece com 5 horas, nao com 6. A margem existe porque uma coleta
longa pode comecar com o token quase vencido e terminar depois do prazo.

Renovar exige `refresh_token`, e o Mercado Livre so o devolve quando a
autorizacao pede o escopo `offline_access`. Sem ele, ha token mas nao ha como
renovar — e este modulo diz isso em vez de falhar em silencio.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .errors import ConfigurationError, PriceCollectorError


ENDPOINT = "https://api.mercadolibre.com/oauth/token"
AUTORIZACAO = "https://auth.mercadolivre.com.br/authorization"
# Renova com 5 horas, uma hora antes do vencimento.
VALIDADE_SEGUNDOS = 5 * 3600


def url_de_autorizacao(client_id: str, redirect_uri: str) -> str:
    """Endereco que a pessoa abre para autorizar a aplicacao.

    Inclui `offline_access` de proposito: sem esse escopo o Mercado Livre nao
    devolve refresh_token e a renovacao automatica fica impossivel.
    """
    parametros = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "offline_access read",
        }
    )
    return f"{AUTORIZACAO}?{parametros}"


def _chamar(dados: dict) -> dict:
    corpo = urllib.parse.urlencode(dados).encode()
    requisicao = urllib.request.Request(
        ENDPOINT,
        data=corpo,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=60) as resposta:
            return json.loads(resposta.read())
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")[:200]
        raise PriceCollectorError(
            f"Mercado Livre recusou a operacao de token ({exc.code}): {detalhe}"
        ) from exc
    except urllib.error.URLError as exc:
        raise PriceCollectorError(
            f"Nao foi possivel alcancar o Mercado Livre: {exc.reason}"
        ) from exc


def trocar_codigo(
    codigo: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    """Troca o codigo da autorizacao pelo primeiro par de tokens."""
    return _chamar(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": codigo,
            "redirect_uri": redirect_uri,
        }
    )


def renovar(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """Gera um token novo a partir do refresh_token."""
    return _chamar(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )


def gravar(caminho: str | Path, resposta: dict) -> Path:
    """Guarda tokens e o momento em que foram emitidos."""
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(
            {
                "access_token": resposta.get("access_token"),
                "refresh_token": resposta.get("refresh_token"),
                "emitido_em": int(time.time()),
                "expires_in": resposta.get("expires_in"),
                "scope": resposta.get("scope"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return destino


def ler(caminho: str | Path) -> dict:
    origem = Path(caminho)
    if not origem.is_file():
        return {}
    try:
        return json.loads(origem.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def precisa_renovar(estado: dict, agora: float | None = None) -> bool:
    """Diz se o token passou das 5 horas de vida."""
    emitido = estado.get("emitido_em")
    if not emitido:
        return True
    momento = agora if agora is not None else time.time()
    return (momento - float(emitido)) >= VALIDADE_SEGUNDOS


def token_valido(
    caminho: str | Path,
    client_id: str | None = None,
    client_secret: str | None = None,
    agora: float | None = None,
) -> str:
    """Devolve um token utilizavel, renovando quando necessario.

    Erro explicito quando falta refresh_token: sem ele a renovacao e
    impossivel e a pessoa precisa reautorizar com `offline_access`.
    """
    estado = ler(caminho)
    if not estado.get("access_token"):
        raise ConfigurationError(
            f"Nenhum token gravado em {caminho}. Autorize a aplicacao primeiro."
        )
    if not precisa_renovar(estado, agora):
        return estado["access_token"]

    if not estado.get("refresh_token"):
        raise ConfigurationError(
            "O token passou de 5 horas e nao ha refresh_token para renovar. "
            "Reautorize incluindo o escopo offline_access."
        )
    identificacao = client_id or os.getenv("ML_CLIENT_ID")
    segredo = client_secret or os.getenv("ML_CLIENT_SECRET")
    if not identificacao or not segredo:
        raise ConfigurationError(
            "Defina ML_CLIENT_ID e ML_CLIENT_SECRET para renovar o token."
        )
    resposta = renovar(estado["refresh_token"], identificacao, segredo)
    gravar(caminho, resposta)
    return resposta["access_token"]
