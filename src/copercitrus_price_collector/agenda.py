"""Catalogo de itens monitorados e execucao mensal automatica.

O catalogo e a lista de produtos que o sistema acompanha. Ele e substituido
por upload de planilha ou CSV e fica gravado no volume, para sobreviver a
reinicio e a novo deploy.

A execucao automatica roda no dia configurado de cada mes e grava no mesmo
historico deduplicado do resto do sistema, entao a serie temporal se forma
sozinha sem ninguem abrir a tela.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


CATALOGO_NOMES = ("catalogo.xlsx", "catalogo.csv")
ESTADO = "agenda.json"
INTERVALO_VERIFICACAO_SEGUNDOS = 900  # 15 minutos


def caminho_catalogo(pasta: Path) -> Path | None:
    """Devolve o catalogo gravado, seja planilha ou CSV."""
    for nome in CATALOGO_NOMES:
        candidato = pasta / nome
        if candidato.is_file():
            return candidato
    return None


def salvar_catalogo(pasta: Path, nome_original: str, conteudo: bytes) -> Path:
    """Grava o catalogo, substituindo o anterior.

    Substituir e o comportamento certo: a lista monitorada e uma so. Manter
    varias versoes faria a execucao mensal ficar ambigua sobre qual usar.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    extensao = ".csv" if nome_original.casefold().endswith((".csv", ".txt")) else ".xlsx"
    for antigo in CATALOGO_NOMES:
        alvo = pasta / antigo
        if alvo.is_file():
            alvo.unlink()
    destino = pasta / f"catalogo{extensao}"
    destino.write_bytes(conteudo)
    return destino


def ler_estado(pasta: Path) -> dict:
    arquivo = pasta / ESTADO
    if not arquivo.is_file():
        return {}
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def gravar_estado(pasta: Path, estado: dict) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / ESTADO).write_text(
        json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def deve_executar(agora: datetime, dia_alvo: int, ultima: str | None) -> bool:
    """Decide se a coleta mensal deve rodar agora.

    Compara por competencia (ano-mes) em vez de intervalo de tempo: se o
    servico estiver fora do ar no dia 1, ele executa assim que voltar, dentro
    do mesmo mes, em vez de perder a medicao.
    """
    if agora.day < dia_alvo:
        return False
    competencia = f"{agora.year:04d}-{agora.month:02d}"
    return ultima != competencia


class AgendaMensal:
    """Fio de execucao que dispara a coleta uma vez por mes."""

    def __init__(
        self,
        pasta: Path,
        executor,
        dia: int = 1,
        intervalo: int = INTERVALO_VERIFICACAO_SEGUNDOS,
    ) -> None:
        self.pasta = pasta
        self.executor = executor
        self.dia = dia
        self.intervalo = intervalo
        self._parar = threading.Event()
        self._fio: threading.Thread | None = None

    def iniciar(self) -> None:
        if self._fio is not None:
            return
        self._fio = threading.Thread(target=self._laco, daemon=True)
        self._fio.start()

    def parar(self) -> None:
        self._parar.set()

    def verificar(self, agora: datetime | None = None) -> bool:
        """Executa a coleta se a competencia do mes ainda nao foi coletada."""
        momento = agora or datetime.now(timezone.utc)
        estado = ler_estado(self.pasta)
        if not deve_executar(momento, self.dia, estado.get("ultima_competencia")):
            return False
        catalogo = caminho_catalogo(self.pasta)
        if catalogo is None:
            return False

        estado["ultima_competencia"] = f"{momento.year:04d}-{momento.month:02d}"
        estado["ultima_execucao"] = momento.replace(microsecond=0).isoformat()
        estado["catalogo"] = catalogo.name
        gravar_estado(self.pasta, estado)
        self.executor(catalogo)
        return True

    def _laco(self) -> None:
        while not self._parar.is_set():
            try:
                self.verificar()
            except Exception as exc:  # pragma: no cover - o fio nao pode morrer
                print(f"Agenda mensal falhou: {type(exc).__name__}: {exc}", flush=True)
            self._parar.wait(self.intervalo)
            time.sleep(0)
