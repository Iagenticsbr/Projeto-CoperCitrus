"""Aplicacao web: envio de planilha, acompanhamento da busca e dashboard.

Serve dois papeis conforme onde roda:

- Na maquina do operador, com navegador e sessao valida, executa a coleta.
- Hospedada (Railway e afins), recebe resultados pelo endpoint de ingestao e
  publica o painel. Coleta em servidor sem tela nao funciona: as fontes
  recusam navegador headless e nao ha quem conclua a verificacao humana.

O historico e a fonte unica do painel, e a gravacao e deduplicada, entao
repetir a mesma busca atualiza os numeros sem inflar a base.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    # Import no escopo do modulo, e nao dentro da fabrica: com
    # `from __future__ import annotations` as anotacoes viram texto, e o
    # pydantic precisa resolver `UploadFile` pelos globais do modulo.
    from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
except ImportError:  # pragma: no cover - dependencia opcional
    FastAPI = None

from .agenda import AgendaMensal, caminho_catalogo, ler_estado, salvar_catalogo
from .dashboard import HTML_TEMPLATE, collect_dashboard_data
from .database import export_csv, export_database
from .errors import ConfigurationError, PriceCollectorError
from .historico import append_run
from .spreadsheet import export_results, read_products


DADOS = Path(os.getenv("RPA_DATA_DIR", "dados_web"))
ENVIOS = DADOS / "planilhas"
SAIDAS = DADOS / "resultados"
HISTORICO = DADOS / "historico.db"
BASE_ATUAL = DADOS / "precos.db"
INGEST_TOKEN = os.getenv("RPA_INGEST_TOKEN")
DIA_AGENDA = int(os.getenv("RPA_AGENDA_DIA", "1"))
EXTENSOES = (".xlsx", ".csv", ".txt")


@dataclass
class Execucao:
    """Estado de uma busca, para a tela acompanhar sem recarregar."""

    id: str
    planilha: str
    fontes: str
    estado: str = "na fila"
    linhas: list[str] = field(default_factory=list)
    produtos: int = 0
    ofertas: int = 0
    erros: int = 0
    excel: str | None = None
    csv: list[str] = field(default_factory=list)
    erro: str | None = None
    iniciado_em: str = field(
        default_factory=lambda: datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    )

    def registrar(self, mensagem: str) -> None:
        self.linhas.append(mensagem)

    def resumo(self) -> dict:
        return {
            "id": self.id,
            "planilha": self.planilha,
            "fontes": self.fontes,
            "estado": self.estado,
            "linhas": self.linhas[-200:],
            "produtos": self.produtos,
            "ofertas": self.ofertas,
            "erros": self.erros,
            "excel": self.excel,
            "csv": self.csv,
            "erro": self.erro,
            "iniciado_em": self.iniciado_em,
        }


EXECUCOES: dict[str, Execucao] = {}
_TRAVA = threading.Lock()


def _preparar_pastas() -> None:
    for pasta in (ENVIOS, SAIDAS):
        pasta.mkdir(parents=True, exist_ok=True)


def executar_coleta(execucao: Execucao, caminho: Path, fontes: str, limite: int) -> None:
    """Roda a coleta e grava base, planilha, CSV e historico."""
    try:
        # Import dentro do try de proposito: sem navegador instalado a falha
        # precisa aparecer na tela, e nao matar a thread em silencio deixando
        # a execucao presa em "na fila".
        from .browser import BrowserRpa
        from .cli import _build_providers
        from .service import CollectionService
        from .settings import Settings

        execucao.estado = "lendo planilha"
        produtos = read_products(caminho)
        execucao.produtos = len(produtos)
        execucao.registrar(f"{len(produtos)} produtos lidos de {caminho.name}")

        selecionadas = [
            item.strip().casefold() for item in fontes.split(",") if item.strip()
        ]
        configuracao = Settings.from_env()
        execucao.estado = "coletando"

        with BrowserRpa(configuracao) as navegador:
            provedores = _build_providers(selecionadas, navegador)
            servico = CollectionService(
                provedores,
                limite,
                configuracao.request_delay_seconds,
                somente_exatos=configuracao.somente_exatos,
                similaridade_minima=configuracao.similaridade_minima,
                somente_lojas_preferidas=configuracao.somente_lojas_preferidas,
            )
            linhas = servico.collect(produtos)

        execucao.estado = "gravando"
        destino = SAIDAS / f"{caminho.stem}_{execucao.id[:8]}.xlsx"
        export_results(linhas, destino)
        export_database(linhas, BASE_ATUAL)
        arquivos_csv = export_csv(linhas, SAIDAS / f"csv_{execucao.id[:8]}")
        append_run(linhas, HISTORICO, caminho.name, fontes)

        execucao.excel = str(destino.resolve())
        execucao.csv = [str(item.resolve()) for item in arquivos_csv]
        execucao.ofertas = sum(1 for linha in linhas if linha.status == "OK")
        execucao.erros = sum(1 for linha in linhas if linha.status == "ERRO")
        execucao.estado = "concluido"
        execucao.registrar(
            f"{execucao.ofertas} ofertas, {execucao.erros} erros. Planilha: {destino.name}"
        )
    except PriceCollectorError as exc:
        execucao.estado = "erro"
        execucao.erro = str(exc)
        execucao.registrar(f"Erro: {exc}")
    except BaseException as exc:  # pragma: no cover - falha inesperada
        import traceback

        execucao.estado = "erro"
        execucao.erro = f"{type(exc).__name__}: {exc}"
        execucao.registrar(execucao.erro)
        traceback.print_exc()


def criar_app():
    """Monta a aplicacao FastAPI."""
    if FastAPI is None:
        raise ConfigurationError(
            "Dependencias web ausentes. Execute: pip install -e .[web]"
        )
    _preparar_pastas()
    app = FastAPI(title="CoperCitrus Precos", docs_url="/api")

    @app.get("/", response_class=HTMLResponse)
    def inicio() -> str:
        return PAGINA_ENVIO

    @app.post("/buscar")
    async def buscar(
        planilha: UploadFile = File(...),
        fontes: str = Form("buscape,zoom,bing"),
        limite: int = Form(8),
    ) -> JSONResponse:
        if not planilha.filename or not planilha.filename.lower().endswith(EXTENSOES):
            raise HTTPException(400, "Envie um arquivo .xlsx ou .csv")
        _preparar_pastas()
        execucao = Execucao(uuid.uuid4().hex, planilha.filename, fontes)
        destino = ENVIOS / f"{execucao.id[:8]}_{planilha.filename}"
        destino.write_bytes(await planilha.read())

        with _TRAVA:
            EXECUCOES[execucao.id] = execucao
        threading.Thread(
            target=executar_coleta,
            args=(execucao, destino, fontes, limite),
            daemon=True,
        ).start()
        return JSONResponse({"id": execucao.id})

    @app.get("/execucao/{identificador}")
    def estado(identificador: str) -> JSONResponse:
        execucao = EXECUCOES.get(identificador)
        if execucao is None:
            raise HTTPException(404, "Execucao nao encontrada")
        return JSONResponse(execucao.resumo())

    @app.get("/execucoes")
    def listar() -> JSONResponse:
        return JSONResponse(
            [item.resumo() for item in list(EXECUCOES.values())[-30:]]
        )

    @app.get("/planilha/{identificador}")
    def baixar(identificador: str):
        execucao = EXECUCOES.get(identificador)
        if execucao is None or not execucao.excel:
            raise HTTPException(404, "Planilha ainda nao disponivel")
        return FileResponse(
            execucao.excel,
            filename=Path(execucao.excel).name,
            media_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

    @app.get("/dashboard", response_class=HTMLResponse)
    def painel() -> str:
        if not BASE_ATUAL.is_file() and not HISTORICO.is_file():
            return PAGINA_SEM_DADOS
        dados = collect_dashboard_data(BASE_ATUAL, HISTORICO)
        return HTML_TEMPLATE.replace(
            "__DADOS__", json.dumps(dados, ensure_ascii=False, default=str)
        )

    @app.post("/ingest")
    async def ingerir(
        payload: dict, x_token: str | None = Header(default=None)
    ) -> JSONResponse:
        """Recebe uma coleta feita em outra maquina.

        Existe porque a coleta precisa de navegador com sessao valida, que o
        servidor nao tem. O operador coleta local e publica aqui.
        """
        if INGEST_TOKEN and x_token != INGEST_TOKEN:
            raise HTTPException(401, "Token invalido")
        ofertas = payload.get("ofertas") or []
        if not isinstance(ofertas, list) or not ofertas:
            raise HTTPException(400, "Envie a lista 'ofertas'")
        gravadas = _ingerir_ofertas(ofertas, payload.get("planilha"))
        return JSONResponse({"recebidas": len(ofertas), "novas": gravadas})

    @app.post("/catalogo")
    async def atualizar_catalogo(
        planilha: UploadFile = File(...), buscar_agora: bool = Form(False)
    ) -> JSONResponse:
        """Substitui a lista de itens monitorados pela execucao mensal."""
        if not planilha.filename or not planilha.filename.lower().endswith(EXTENSOES):
            raise HTTPException(400, "Envie um arquivo .xlsx ou .csv")
        destino = salvar_catalogo(DADOS, planilha.filename, await planilha.read())
        try:
            itens = read_products(destino)
        except PriceCollectorError as exc:
            destino.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc

        resposta = {"catalogo": destino.name, "itens": len(itens)}
        if buscar_agora:
            execucao = Execucao(uuid.uuid4().hex, destino.name, "buscape,zoom,bing")
            with _TRAVA:
                EXECUCOES[execucao.id] = execucao
            threading.Thread(
                target=executar_coleta,
                args=(execucao, destino, "buscape,zoom,bing", 8),
                daemon=True,
            ).start()
            resposta["execucao"] = execucao.id
        return JSONResponse(resposta)

    @app.get("/catalogo")
    def ver_catalogo() -> JSONResponse:
        atual = caminho_catalogo(DADOS)
        estado = ler_estado(DADOS)
        if atual is None:
            return JSONResponse({"catalogo": None, "itens": 0, "agenda": estado})
        try:
            itens = len(read_products(atual))
        except PriceCollectorError:
            itens = 0
        return JSONResponse(
            {
                "catalogo": atual.name,
                "itens": itens,
                "atualizado_em": datetime.fromtimestamp(
                    atual.stat().st_mtime
                ).strftime("%d/%m/%Y %H:%M"),
                "dia_execucao": DIA_AGENDA,
                "agenda": estado,
            }
        )

    @app.post("/reiniciar-base")
    def reiniciar_base(x_token: str | None = Header(default=None)) -> JSONResponse:
        """Apaga historico e base para recomecar com dados novos.

        Existe porque trocar a base pelo painel exige remover o que ja esta
        gravado; sem isso a dedup mantem as medicoes antigas convivendo com
        as novas e a comparacao fica sem sentido.
        """
        if INGEST_TOKEN and x_token != INGEST_TOKEN:
            raise HTTPException(401, "Token invalido")
        removidos = []
        for arquivo in (HISTORICO, BASE_ATUAL):
            if arquivo.is_file():
                arquivo.unlink()
                removidos.append(arquivo.name)
        return JSONResponse({"removidos": removidos})

    @app.get("/saude")
    def saude() -> JSONResponse:
        return JSONResponse(
            {
                "estado": "ok",
                "base": BASE_ATUAL.is_file(),
                "historico": HISTORICO.is_file(),
                "execucoes": len(EXECUCOES),
            }
        )

    def _coleta_agendada(catalogo: Path) -> None:
        execucao = Execucao(
            uuid.uuid4().hex, catalogo.name, "buscape,zoom,bing"
        )
        execucao.registrar("Execucao mensal automatica iniciada")
        with _TRAVA:
            EXECUCOES[execucao.id] = execucao
        executar_coleta(execucao, catalogo, "buscape,zoom,bing", 8)

    agenda = AgendaMensal(DADOS, _coleta_agendada, dia=DIA_AGENDA)
    agenda.iniciar()
    app.state.agenda = agenda
    return app


def _ingerir_ofertas(ofertas: list[dict], planilha: str | None) -> int:
    """Grava ofertas vindas de outra maquina, sem duplicar o que ja existe."""
    from .historico import SCHEMA

    HISTORICO.parent.mkdir(parents=True, exist_ok=True)
    momento = datetime.utcnow().replace(microsecond=0).isoformat()
    dia = momento[:10]
    # Piso de plausibilidade tambem na entrada: coleta feita antes da correcao,
    # ou vinda de outra maquina, nao pode contaminar o painel com R$ 0,01.
    ofertas = [
        item
        for item in ofertas
        if isinstance(item.get("preco"), (int, float)) and item["preco"] >= 1.0
    ]
    if not ofertas:
        raise HTTPException(400, "Nenhuma oferta com preco plausivel")
    conexao = sqlite3.connect(HISTORICO)
    try:
        conexao.executescript(SCHEMA)
        cursor = conexao.execute(
            "INSERT INTO execucoes (executado_em, planilha, fontes, produtos, ofertas)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                momento,
                planilha,
                "ingestao",
                len({item.get("sku") for item in ofertas}),
                len(ofertas),
            ),
        )
        execucao_id = cursor.lastrowid
        antes = conexao.execute("SELECT count(*) FROM historico_ofertas").fetchone()[0]
        conexao.executemany(
            "INSERT OR IGNORE INTO historico_ofertas (execucao_id, coletado_em, dia,"
            " sku, produto, marca, fonte, loja, titulo, preco, classificacao,"
            " similaridade, loja_preferida, url)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    execucao_id,
                    momento,
                    dia,
                    item.get("sku"),
                    item.get("produto") or "",
                    item.get("marca"),
                    item.get("fonte") or "ingestao",
                    item.get("loja"),
                    item.get("titulo"),
                    item.get("preco"),
                    item.get("classificacao"),
                    item.get("similaridade"),
                    int(bool(item.get("loja_preferida"))),
                    item.get("url"),
                )
                for item in ofertas
                if item.get("produto")
            ],
        )
        depois = conexao.execute("SELECT count(*) FROM historico_ofertas").fetchone()[0]
        conexao.commit()
        return depois - antes
    finally:
        conexao.close()


PAGINA_SEM_DADOS = """<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Sem dados</title><style>body{background:#0f1720;color:#e8eef4;
font:15px/1.6 "Segoe UI",system-ui,sans-serif;display:grid;place-items:center;
height:100vh;margin:0;text-align:center}a{color:#4ea3ff}</style></head><body><div>
<h1>Nenhuma coleta ainda</h1>
<p>Envie uma planilha em <a href="/">/</a> para o painel aparecer.</p>
</div></body></html>"""


PAGINA_ENVIO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Busca de Preços CoperCitrus</title>
<style>
  :root { --fundo:#0f1720; --painel:#17212c; --linha:#24313f; --texto:#e8eef4;
          --suave:#93a4b5; --destaque:#4ea3ff; --ok:#3ddc97; --erro:#ff6b6b; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--fundo); color:var(--texto);
         font:15px/1.6 "Segoe UI",system-ui,sans-serif; }
  header { padding:20px 28px; border-bottom:1px solid var(--linha);
           display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; }
  h1 { font-size:19px; margin:0; }
  a.botao { background:var(--destaque); color:#062033; text-decoration:none;
            padding:9px 16px; border-radius:8px; font-weight:600; font-size:14px; }
  main { max-width:960px; margin:0 auto; padding:26px 28px 60px; }
  .painel { background:var(--painel); border:1px solid var(--linha);
            border-radius:11px; padding:20px; margin-bottom:20px; }
  h2 { font-size:15px; margin:0 0 14px; }
  label { display:block; font-size:12px; color:var(--suave); margin:14px 0 6px; }
  input, select { background:var(--fundo); color:var(--texto); border:1px solid var(--linha);
                  border-radius:8px; padding:9px 11px; font-size:14px; width:100%; }
  .linha { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  button { background:var(--destaque); color:#062033; border:0; border-radius:8px;
           padding:11px 20px; font-weight:600; font-size:15px; cursor:pointer; margin-top:18px; }
  button[disabled] { opacity:.5; cursor:not-allowed; }
  .dica { color:var(--suave); font-size:13px; }
  pre { background:var(--fundo); border:1px solid var(--linha); border-radius:8px;
        padding:14px; max-height:340px; overflow:auto; font-size:13px; margin:0; white-space:pre-wrap; }
  .estado { display:inline-block; padding:3px 11px; border-radius:20px; font-size:12px;
            border:1px solid var(--linha); color:var(--suave); }
  .estado.concluido { color:var(--ok); border-color:var(--ok); }
  .estado.erro { color:var(--erro); border-color:var(--erro); }
  .arquivo { background:var(--fundo); border:1px solid var(--linha); border-radius:8px;
             padding:12px 14px; margin-top:12px; font-size:13.5px; word-break:break-all; }
  .arquivo strong { display:block; color:var(--suave); font-size:12px;
                    text-transform:uppercase; margin-bottom:5px; letter-spacing:.4px; }
</style>
</head>
<body>
<header>
  <h1>Busca de Preços</h1>
  <a class="botao" href="/dashboard">Abrir dashboard</a>
</header>
<main>
  <div class="painel">
    <h2>Enviar planilha</h2>
    <p class="dica">Arquivo .xlsx com uma coluna de nome de produto
      (<code>Produto</code>, <code>Descrição</code>, <code>Nome</code> ou <code>Item</code>).
      Colunas de marca, modelo, SKU e quantidade são opcionais e melhoram a busca.</p>
    <form id="formulario">
      <label>Planilha</label>
      <input type="file" name="planilha" accept=".xlsx,.csv" required>
      <div class="linha">
        <div>
          <label>Fontes</label>
          <select name="fontes">
            <option value="buscape,zoom,bing">Buscapé + Zoom + Bing</option>
            <option value="google">Google Shopping</option>
            <option value="google,buscape,zoom,bing">Todas</option>
            <option value="buscape">Buscapé</option>
            <option value="bing">Bing Shopping</option>
            <option value="shopee">Shopee</option>
          </select>
        </div>
        <div>
          <label>Ofertas por produto</label>
          <input type="number" name="limite" value="8" min="1" max="20">
        </div>
      </div>
      <button type="submit" id="enviar">Buscar item a item</button>
    </form>
  </div>

  <div class="painel">
    <h2>Lista monitorada</h2>
    <p class="dica">Esta lista roda sozinha todo dia <strong id="dia-agenda">1</strong>
      de cada mes e alimenta o historico do dashboard. Enviar um arquivo novo
      substitui a lista inteira.</p>
    <div class="arquivo" id="estado-catalogo">carregando...</div>
    <form id="form-catalogo">
      <label>Planilha ou CSV com os nomes dos produtos</label>
      <input type="file" name="planilha" accept=".xlsx,.csv" required>
      <label style="display:flex;align-items:center;gap:9px;margin-top:14px;text-transform:none;font-size:14px;color:var(--texto)">
        <input type="checkbox" name="buscar_agora" value="true" style="width:auto">
        Buscar agora, sem esperar o dia da execucao
      </label>
      <button type="submit">Atualizar lista monitorada</button>
    </form>
  </div>

  <div class="painel" id="acompanhamento" hidden>
    <h2>Andamento <span class="estado" id="estado">na fila</span></h2>
    <pre id="log">aguardando…</pre>
    <div id="arquivos"></div>
  </div>
</main>
<script>
const formCatalogo = document.getElementById("form-catalogo");
const estadoCatalogo = document.getElementById("estado-catalogo");

async function carregarCatalogo() {
  const dados = await (await fetch("/catalogo")).json();
  document.getElementById("dia-agenda").textContent = dados.dia_execucao || 1;
  if (!dados.catalogo) {
    estadoCatalogo.innerHTML =
      "<strong>Nenhuma lista monitorada</strong>Envie uma planilha ou CSV para a execucao mensal comecar.";
    return;
  }
  const ultima = dados.agenda && dados.agenda.ultima_execucao
    ? `Ultima execucao automatica: ${dados.agenda.ultima_execucao.slice(0,10)}`
    : "Ainda nao executou automaticamente";
  estadoCatalogo.innerHTML =
    `<strong>Lista monitorada</strong>${dados.itens} itens em ${dados.catalogo}` +
    ` &middot; atualizada em ${dados.atualizado_em || "-"}<br>${ultima}`;
}
carregarCatalogo();

formCatalogo.addEventListener("submit", async evento => {
  evento.preventDefault();
  estadoCatalogo.textContent = "enviando lista...";
  const resposta = await fetch("/catalogo", {method:"POST", body:new FormData(formCatalogo)});
  if (!resposta.ok) {
    estadoCatalogo.textContent = "Falha: " + (await resposta.text());
    return;
  }
  const dados = await resposta.json();
  await carregarCatalogo();
  if (dados.execucao) { painel.hidden = false; acompanhar(dados.execucao); }
});

const formulario = document.getElementById("formulario");
const painel = document.getElementById("acompanhamento");
const estado = document.getElementById("estado");
const log = document.getElementById("log");
const arquivos = document.getElementById("arquivos");
const enviar = document.getElementById("enviar");

formulario.addEventListener("submit", async evento => {
  evento.preventDefault();
  enviar.disabled = true;
  arquivos.innerHTML = "";
  painel.hidden = false;
  log.textContent = "enviando planilha…";

  const resposta = await fetch("/buscar", {method:"POST", body:new FormData(formulario)});
  if (!resposta.ok) {
    log.textContent = "Falha ao enviar: " + await resposta.text();
    enviar.disabled = false;
    return;
  }
  const {id} = await resposta.json();
  acompanhar(id);
});

async function acompanhar(id) {
  const resposta = await fetch("/execucao/" + id);
  const dados = await resposta.json();
  estado.textContent = dados.estado;
  estado.className = "estado " + (dados.estado === "concluido" ? "concluido"
                                : dados.estado === "erro" ? "erro" : "");
  log.textContent = dados.linhas.join("\n") || "aguardando…";
  log.scrollTop = log.scrollHeight;

  if (dados.estado === "concluido") {
    arquivos.innerHTML =
      `<div class="arquivo"><strong>Planilha final salva em</strong>${dados.excel}</div>` +
      dados.csv.map(c => `<div class="arquivo"><strong>CSV</strong>${c}</div>`).join("") +
      `<div style="margin-top:14px">
         <a class="botao" href="/planilha/${id}">Baixar planilha</a>
         <a class="botao" href="/dashboard" style="margin-left:8px">Ver no dashboard</a>
       </div>`;
    enviar.disabled = false;
    return;
  }
  if (dados.estado === "erro") { enviar.disabled = false; return; }
  setTimeout(() => acompanhar(id), 2000);
}
</script>
</body>
</html>
"""


app = None


def main() -> int:
    """Sobe o servidor. A porta vem do ambiente, como o Railway espera."""
    import uvicorn

    porta = int(os.getenv("PORT", "8000"))
    uvicorn.run(criar_app(), host="0.0.0.0", port=porta)
    return 0
