"""Captura as telas do sistema para o documento de apresentacao.

Roda contra a instancia publicada e grava um PNG por aba do painel, mais a
tela de envio de planilha. As imagens entram no documento como data URI, para
o arquivo abrir sozinho, sem depender do servidor no ar.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


URL = "https://copercitrus-web-production.up.railway.app"
DESTINO = Path("docs/telas")
LARGURA, ALTURA = 1500, 1000

# Cada aba do painel vira uma imagem; o nome do botao e o seletor.
ABAS = [
    ("visao-geral", "Visão geral"),
    ("oportunidades", "Oportunidades"),
    ("lojas", "Lojas"),
    ("dispersao", "Dispersão"),
    ("ofertas", "Ofertas"),
    ("evolucao", "Evolução"),
]


def capturar(url: str = URL) -> list[Path]:
    DESTINO.mkdir(parents=True, exist_ok=True)
    gravadas: list[Path] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        contexto = navegador.new_context(
            viewport={"width": LARGURA, "height": ALTURA},
            device_scale_factor=2,
            locale="pt-BR",
        )
        pagina = contexto.new_page()

        pagina.goto(f"{url}/", wait_until="networkidle", timeout=60000)
        pagina.wait_for_timeout(1500)
        alvo = DESTINO / "envio.png"
        pagina.screenshot(path=str(alvo), full_page=True)
        gravadas.append(alvo)

        pagina.goto(f"{url}/dashboard", wait_until="networkidle", timeout=60000)
        pagina.wait_for_timeout(2500)
        for nome, rotulo in ABAS:
            botao = pagina.get_by_role("button", name=rotulo, exact=True)
            if botao.count():
                botao.first.click()
                pagina.wait_for_timeout(900)
            alvo = DESTINO / f"{nome}.png"
            pagina.screenshot(path=str(alvo))
            gravadas.append(alvo)

        navegador.close()
    return gravadas


if __name__ == "__main__":
    endereco = sys.argv[1] if len(sys.argv) > 1 else URL
    for caminho in capturar(endereco):
        print(f"{caminho} ({caminho.stat().st_size // 1024} KB)")
