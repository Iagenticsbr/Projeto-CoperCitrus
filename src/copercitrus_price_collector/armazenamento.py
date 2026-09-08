"""Acesso ao banco: arquivo SQLite ou PostgreSQL, pela mesma interface.

O painel roda no Railway, onde o disco e efemero por padrao: um deploy novo
apagava o historico junto. Com `DATABASE_URL` apontando para o PostgreSQL do
proprio Railway, o dado sobrevive ao deploy — e passa a ser legivel por outras
ferramentas, o que arquivo SQLite dentro do container nunca foi.

O SQLite continua valendo. A coleta roda na maquina de quem opera e grava em
arquivo; so a publicacao precisa do banco compartilhado. Manter os dois pela
mesma interface evita duas versoes do mesmo SQL se desencontrarem.

As diferencas de dialeto sao poucas e ficam todas aqui:

    ?                     vira %s
    AUTOINCREMENT         vira BIGSERIAL
    REAL                  vira DOUBLE PRECISION
    INSERT OR IGNORE      vira INSERT ... ON CONFLICT DO NOTHING

`INSERT OR REPLACE` nao esta na lista de proposito: no PostgreSQL exigiria
declarar a coluna do conflito e repetir todas as atribuicoes. Onde ele era
usado, apagar antes de inserir da o mesmo resultado e le igual nos dois.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from .errors import ConfigurationError


PREFIXOS_POSTGRES = ("postgres://", "postgresql://")


def destino_padrao(arquivo: str | Path) -> str | Path:
    """DATABASE_URL quando existe; o arquivo indicado quando nao.

    Uma variavel de ambiente so, decidida num lugar so: a coleta local e o
    painel publicado usam o mesmo codigo sem saber qual dos dois esta ativo.
    """
    url = (os.getenv("DATABASE_URL") or "").strip()
    return url or arquivo


def e_postgres(destino: str | Path) -> bool:
    return isinstance(destino, str) and destino.startswith(PREFIXOS_POSTGRES)


def _para_postgres(sql: str) -> str:
    """Traduz o SQL escrito no dialeto do SQLite."""
    convertido = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    convertido = re.sub(r"\bREAL\b", "DOUBLE PRECISION", convertido)
    convertido = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", convertido, flags=re.I
    )
    # A clausula do conflito vai no fim do comando, depois do VALUES.
    if re.search(r"\bINSERT\s+OR\s+IGNORE\b", sql, flags=re.I):
        convertido = convertido.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return convertido.replace("?", "%s")


def _dividir(script: str) -> list[str]:
    """Separa um script em comandos, ignorando comentario e linha vazia."""
    sem_comentario = re.sub(r"--[^\n]*", "", script)
    return [trecho.strip() for trecho in sem_comentario.split(";") if trecho.strip()]


class Banco:
    """Conexao unica com a mesma interface para SQLite e PostgreSQL."""

    def __init__(self, destino: str | Path) -> None:
        self.destino = destino
        self.postgres = e_postgres(destino)
        if self.postgres:
            self._conexao = self._abrir_postgres(str(destino))
        else:
            caminho = Path(destino)
            caminho.parent.mkdir(parents=True, exist_ok=True)
            self._conexao = sqlite3.connect(caminho)
            self._conexao.row_factory = sqlite3.Row

    @staticmethod
    def _abrir_postgres(url: str):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise ConfigurationError(
                "DATABASE_URL aponta para PostgreSQL, mas o driver nao esta "
                "instalado. Adicione psycopg[binary] as dependencias."
            ) from exc
        return psycopg.connect(url, row_factory=dict_row, autocommit=False)

    def __enter__(self) -> "Banco":
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def _traduzir(self, sql: str) -> str:
        return _para_postgres(sql) if self.postgres else sql

    def criar(self, script: str) -> None:
        """Aplica o esquema. Repetir a chamada nao muda nada."""
        for comando in _dividir(script):
            self.executar(comando)
        self.confirmar()

    def executar(self, sql: str, parametros: Sequence[Any] = ()) -> Any:
        cursor = self._conexao.cursor()
        cursor.execute(self._traduzir(sql), tuple(parametros))
        return cursor

    def executar_muitos(self, sql: str, linhas: Iterable[Sequence[Any]]) -> None:
        dados = [tuple(linha) for linha in linhas]
        if not dados:
            return
        cursor = self._conexao.cursor()
        cursor.executemany(self._traduzir(sql), dados)

    def consultar(self, sql: str, parametros: Sequence[Any] = ()) -> list[dict]:
        cursor = self.executar(sql, parametros)
        return [dict(linha) for linha in cursor.fetchall()]

    def valor(self, sql: str, parametros: Sequence[Any] = ()) -> Any:
        """Primeira coluna da primeira linha, ou None."""
        linhas = self.consultar(sql, parametros)
        if not linhas:
            return None
        return next(iter(linhas[0].values()))

    def inserir_e_devolver_id(self, sql: str, parametros: Sequence[Any]) -> int:
        """Insere e devolve a chave gerada.

        O SQLite entrega em `lastrowid`; o PostgreSQL exige pedir com
        RETURNING, entao a clausula e acrescentada aqui em vez de poluir cada
        comando de insercao com dialeto.
        """
        if self.postgres:
            cursor = self.executar(sql.rstrip().rstrip(";") + " RETURNING id", parametros)
            return int(next(iter(cursor.fetchone().values())))
        return int(self.executar(sql, parametros).lastrowid)

    def existe_tabela(self, nome: str) -> bool:
        if self.postgres:
            return bool(
                self.valor("SELECT to_regclass(%s) IS NOT NULL", (f"public.{nome}",))
            )
        return bool(
            self.valor(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?",
                (nome,),
            )
        )

    def colunas(self, tabela: str) -> set[str]:
        """Nomes das colunas existentes; conjunto vazio quando nao ha tabela."""
        if not self.existe_tabela(tabela):
            return set()
        if self.postgres:
            linhas = self.consultar(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ?",
                (tabela,),
            )
            return {linha["column_name"] for linha in linhas}
        return {
            linha["name"] for linha in self.consultar(f"PRAGMA table_info({tabela})")
        }

    def garantir_coluna(self, tabela: str, coluna: str, tipo: str) -> bool:
        """Acrescenta a coluna quando ela falta. Devolve se mexeu na tabela.

        `CREATE TABLE IF NOT EXISTS` nao altera tabela que ja existe: uma base
        gravada por versao antiga fica sem as colunas novas e quebra na
        leitura, com erro de coluna inexistente. Como a base do painel e
        acumulada e nao pode ser recriada, a coluna entra por ALTER.
        """
        if coluna in self.colunas(tabela):
            return False
        self.executar(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
        self.confirmar()
        return True

    def confirmar(self) -> None:
        self._conexao.commit()

    def fechar(self) -> None:
        self._conexao.close()


def disponivel(destino: str | Path) -> bool:
    """Diz se ha dado para ler, sem estourar erro quando nao ha.

    O painel e chamado antes da primeira coleta com frequencia: nesse momento
    o arquivo nao existe e o banco esta sem tabela. Os dois casos sao "vazio",
    nao falha.
    """
    if e_postgres(destino):
        try:
            with Banco(destino) as banco:
                return banco.existe_tabela("historico_ofertas")
        except Exception:
            return False
    return Path(destino).is_file()
