"""Importacao de cookies exportados pelo navegador.

Aceita o JSON da extensao Cookie-Editor (lista de cookies) e tambem o
`storage_state` do proprio Playwright, para a sessao poder vir de qualquer
um dos dois caminhos.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import ConfigurationError


SAME_SITE = {
    "no_restriction": "None",
    "none": "None",
    "lax": "Lax",
    "strict": "Strict",
    "unspecified": "Lax",
}


def _convert(raw: dict) -> dict | None:
    name = raw.get("name")
    value = raw.get("value")
    if not name or value is None:
        return None
    cookie: dict[str, object] = {
        "name": str(name),
        "value": str(value),
        "path": raw.get("path") or "/",
        "httpOnly": bool(raw.get("httpOnly", False)),
        "secure": bool(raw.get("secure", False)),
        "sameSite": SAME_SITE.get(
            str(raw.get("sameSite", "")).casefold(), "Lax"
        ),
    }
    domain = raw.get("domain")
    if domain:
        cookie["domain"] = str(domain)
    elif raw.get("url"):
        cookie["url"] = str(raw["url"])
    else:
        return None

    # Cookie-Editor grava expirationDate; o Playwright espera expires.
    expires = raw.get("expires", raw.get("expirationDate"))
    if expires is not None and not raw.get("session"):
        try:
            cookie["expires"] = float(expires)
        except (TypeError, ValueError):
            pass
    return cookie


def load_cookie_file(path: str | Path) -> list[dict]:
    """Le o arquivo e devolve cookies no formato aceito pelo Playwright."""
    source = Path(path).expanduser()
    if not source.is_file():
        raise ConfigurationError(f"Arquivo de cookies nao encontrado: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"O arquivo {source.name} nao e um JSON valido"
        ) from exc

    if isinstance(data, dict):
        raw_cookies = data.get("cookies")
        if not isinstance(raw_cookies, list):
            raise ConfigurationError(
                f"{source.name} nao contem uma lista de cookies"
            )
    elif isinstance(data, list):
        raw_cookies = data
    else:
        raise ConfigurationError(f"Formato nao reconhecido em {source.name}")

    cookies = [
        converted
        for converted in (_convert(item) for item in raw_cookies if isinstance(item, dict))
        if converted is not None
    ]
    if not cookies:
        raise ConfigurationError(f"Nenhum cookie utilizavel em {source.name}")
    return cookies
