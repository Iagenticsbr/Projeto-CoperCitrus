from __future__ import annotations

import argparse
import sys
from dataclasses import replace

from .browser import BrowserRpa
from .errors import ConfigurationError, PriceCollectorError
from .database import export_csv, export_database
from .dashboard import render_dashboard
from .historico import append_run
from . import ml_token
from .publicar import publicar, reiniciar
from .providers import (
    BingShoppingProvider,
    BuscapeProvider,
    GoogleShoppingProvider,
    MercadoLivreOficialProvider,
    MercadoLivreProvider,
    PriceProvider,
    ShopeeProvider,
    ShopeeWebProvider,
    ZoomProvider,
)
from .service import CollectionService
from .settings import Settings
from .spreadsheet import create_template, export_results, read_products


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="copercitrus-price",
        description="RPA de precos do Google Shopping e Shopee a partir de um Excel.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    template = subcommands.add_parser("template", help="cria uma planilha-modelo")
    template.add_argument("output", nargs="?", default="produtos.xlsx")

    painel = subcommands.add_parser(
        "dashboard", help="gera o painel HTML a partir da base coletada"
    )
    painel.add_argument("--database", default="resultados/precos.db")
    painel.add_argument("--historico", default="resultados/historico.db")
    painel.add_argument("--output", default="resultados/dashboard.html")

    autorizar = subcommands.add_parser(
        "ml-autorizar", help="mostra o link de autorizacao do Mercado Livre"
    )
    autorizar.add_argument("--client-id", required=True)
    autorizar.add_argument("--redirect-uri", required=True)

    trocar = subcommands.add_parser(
        "ml-token", help="troca o codigo por token e grava com renovacao"
    )
    trocar.add_argument("codigo")
    trocar.add_argument("--client-id", required=True)
    trocar.add_argument("--client-secret", required=True)
    trocar.add_argument("--redirect-uri", required=True)
    trocar.add_argument("--arquivo", default="resultados/ml_token.json")

    renovar_cmd = subcommands.add_parser(
        "ml-renovar", help="renova o token quando passou de 5 horas"
    )
    renovar_cmd.add_argument("--arquivo", default="resultados/ml_token.json")
    renovar_cmd.add_argument("--client-id")
    renovar_cmd.add_argument("--client-secret")

    envio = subcommands.add_parser(
        "publicar", help="envia a base coletada para a instancia hospedada"
    )
    envio.add_argument("url", help="endereco da aplicacao, por exemplo https://app.up.railway.app")
    envio.add_argument("--database", default="resultados/precos.db")
    envio.add_argument("--token", help="valor de RPA_INGEST_TOKEN configurado no servidor")
    envio.add_argument(
        "--substituir",
        action="store_true",
        help="apaga a base publicada antes de enviar, em vez de acumular",
    )

    login = subcommands.add_parser(
        "login",
        help="abre a fonte para voce entrar na sua conta e salva a sessao",
    )
    login.add_argument("fonte", choices=sorted(LOGIN_URLS))
    login.add_argument("--storage-state", required=True)
    login.add_argument("--wait-seconds", type=float, default=300.0)
    login.add_argument("--browser-channel", choices=("chrome", "msedge"))

    collect = subcommands.add_parser("collect", help="processa uma planilha via browser")
    collect.add_argument("input")
    collect.add_argument("--output", default="resultados/precos.xlsx")
    collect.add_argument("--sheet")
    collect.add_argument(
        "--providers",
        default="buscape,zoom,bing",
        help=(
            "fontes separadas por virgula: mercadolivre (API oficial), "
            "mercadolivre-apify, shopee, buscape, "
            "zoom, bing, google, shopee-web"
        ),
    )
    collect.add_argument(
        "--database",
        default="resultados/precos.db",
        help="SQLite gerado para alimentar o dashboard",
    )
    collect.add_argument(
        "--csv-dir",
        default="resultados/csv",
        help="pasta dos CSV de ofertas e resumo",
    )
    collect.add_argument("--limit", type=int)
    collect.add_argument("--max-products", type=int, default=1000)
    collect.add_argument("--delay", type=float)
    collect.add_argument(
        "--headed",
        action="store_true",
        help="exibe o Chromium durante a execucao (padrao)",
    )
    collect.add_argument(
        "--headless",
        action="store_true",
        help=(
            "executa sem janela; os comparadores recusam o Chromium headless, "
            "use apenas com --browser-cdp-url"
        ),
    )
    collect.add_argument(
        "--browser-channel",
        choices=("chrome", "msedge"),
        help="usa o Chrome ou Edge instalado em vez do Chromium do Playwright",
    )
    collect.add_argument(
        "--browser-user-data-dir",
        help="usa um perfil persistente do navegador e preserva a sessao local",
    )
    collect.add_argument(
        "--manual-verification-seconds",
        type=float,
        help=(
            "tempo de espera para um humano concluir a verificacao da fonte "
            "na janela do navegador; 0 desativa a espera"
        ),
    )
    collect.add_argument(
        "--historico",
        default="resultados/historico.db",
        help=(
            "base que acumula as execucoes e sustenta a analise de evolucao; "
            "vazio desativa o registro"
        ),
    )
    collect.add_argument(
        "--somente-exatos",
        action="store_true",
        help="mantem apenas o produto pedido, descartando similares (padrao)",
    )
    collect.add_argument(
        "--incluir-similares",
        action="store_true",
        help="mantem tambem produtos parecidos na base",
    )
    collect.add_argument(
        "--similaridade-minima",
        type=float,
        help="corte de similaridade do modo exato, de 0 a 100 (padrao 80)",
    )
    collect.add_argument(
        "--ml-token-arquivo",
        default="resultados/ml_token.json",
        help="arquivo de token do Mercado Livre, renovado automaticamente",
    )
    collect.add_argument(
        "--somente-lojas-preferidas",
        action="store_true",
        help="mantem na base apenas as lojas de --lojas-preferidas",
    )
    collect.add_argument(
        "--lojas-preferidas",
        help="lista separada por virgula, por exemplo: mercado livre,shopee",
    )
    collect.add_argument(
        "--cookies",
        help=(
            "JSON de cookies exportado do navegador (extensao Cookie-Editor) "
            "ou storage_state do Playwright"
        ),
    )
    collect.add_argument(
        "--storage-state",
        help=(
            "arquivo de cookies e sessao: carrega no inicio e regrava ao fim, "
            "para login e verificacao nao serem refeitos a cada execucao"
        ),
    )
    collect.add_argument(
        "--debug-dump-dir",
        help="salva HTML e captura da pagina quando nenhuma oferta e reconhecida",
    )
    collect.add_argument(
        "--browser-cdp-url",
        help="conecta a um Chrome ja aberto com depuracao remota, por exemplo http://127.0.0.1:9222",
    )
    return parser


LOGIN_URLS = {
    "shopee": "https://shopee.com.br/buyer/login",
    "google": "https://accounts.google.com/",
}

PROVIDER_FACTORIES = {
    "mercadolivre": MercadoLivreOficialProvider,
    "mercadolivre-apify": MercadoLivreProvider,
    "shopee": ShopeeProvider,
    "buscape": BuscapeProvider,
    "zoom": ZoomProvider,
    "bing": BingShoppingProvider,
    "google": GoogleShoppingProvider,
    "shopee-web": ShopeeWebProvider,
}


def _build_providers(selected: list[str], browser: BrowserRpa) -> list[PriceProvider]:
    unknown = sorted(set(selected) - set(PROVIDER_FACTORIES))
    if unknown:
        raise ConfigurationError(f"Fonte desconhecida: {', '.join(unknown)}")
    providers: list[PriceProvider] = [
        PROVIDER_FACTORIES[name](browser)
        for name in PROVIDER_FACTORIES
        if name in selected
    ]
    if not providers:
        raise ConfigurationError("Selecione ao menos uma fonte")
    return providers


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except KeyboardInterrupt:
        return 130
    try:
        if args.command == "template":
            destination = create_template(args.output)
            print(f"Planilha-modelo criada: {destination}")
            return 0

        if args.command == "ml-autorizar":
            print(ml_token.url_de_autorizacao(args.client_id, args.redirect_uri))
            return 0

        if args.command == "ml-token":
            resposta = ml_token.trocar_codigo(
                args.codigo, args.client_id, args.client_secret, args.redirect_uri
            )
            destino = ml_token.gravar(args.arquivo, resposta)
            renovavel = "sim" if resposta.get("refresh_token") else "NAO"
            print(f"Token gravado em {destino} | renovavel: {renovavel}")
            if not resposta.get("refresh_token"):
                print(
                    "Sem refresh_token a coleta automatica para em 6 horas. "
                    "Reautorize com o escopo offline_access."
                )
            return 0

        if args.command == "ml-renovar":
            token = ml_token.token_valido(
                args.arquivo, args.client_id, args.client_secret
            )
            print(f"Token valido: {token[:12]}...")
            return 0

        if args.command == "publicar":
            if args.substituir:
                limpeza = reiniciar(args.url, args.token)
                print(f"Base anterior removida: {limpeza.get('removidos')}")
            resposta = publicar(args.database, args.url, args.token)
            print(
                f"Publicado: {resposta.get('recebidas')} ofertas enviadas, "
                f"{resposta.get('novas')} novas apos deduplicacao."
            )
            return 0

        if args.command == "dashboard":
            destino = render_dashboard(
                args.database, args.output, args.historico or None
            )
            print(f"Dashboard gerado: {destino.resolve()}")
            return 0

        if args.command == "login":
            settings = replace(
                Settings.from_env(),
                headless=False,
                storage_state_path=args.storage_state,
            )
            if args.browser_channel:
                settings = replace(settings, browser_channel=args.browser_channel)
            with BrowserRpa(settings) as browser:
                ok = browser.authenticate(
                    LOGIN_URLS[args.fonte], args.wait_seconds
                )
            return 0 if ok else 1

        settings = Settings.from_env()
        if args.headed and args.headless:
            raise ConfigurationError("Use --headed ou --headless, nao os dois")
        if args.headed:
            settings = replace(settings, headless=False)
        if args.headless:
            settings = replace(settings, headless=True)
        if args.browser_channel:
            settings = replace(settings, browser_channel=args.browser_channel)
        if args.browser_user_data_dir:
            settings = replace(
                settings, browser_user_data_dir=args.browser_user_data_dir
            )
        if args.browser_cdp_url:
            settings = replace(settings, browser_cdp_url=args.browser_cdp_url)
        if args.cookies:
            settings = replace(settings, cookies_path=args.cookies)
        if args.storage_state:
            settings = replace(settings, storage_state_path=args.storage_state)
        if args.debug_dump_dir:
            settings = replace(settings, debug_dump_dir=args.debug_dump_dir)
        if args.manual_verification_seconds is not None:
            if args.manual_verification_seconds < 0:
                raise ConfigurationError(
                    "--manual-verification-seconds nao pode ser negativo"
                )
            settings = replace(
                settings,
                manual_verification_seconds=args.manual_verification_seconds,
            )

        selected = [
            item.strip().casefold() for item in args.providers.split(",") if item.strip()
        ]
        limit = args.limit if args.limit is not None else settings.result_limit
        delay = (
            args.delay
            if args.delay is not None
            else settings.request_delay_seconds
        )
        if not 1 <= limit <= 20:
            raise ConfigurationError("--limit deve estar entre 1 e 20")
        if delay < 0:
            raise ConfigurationError("--delay nao pode ser negativo")

        if args.somente_exatos and args.incluir_similares:
            raise ConfigurationError(
                "Use --somente-exatos ou --incluir-similares, nao os dois"
            )
        if args.incluir_similares:
            settings = replace(settings, somente_exatos=False)
        if args.somente_exatos:
            settings = replace(settings, somente_exatos=True)
        if args.lojas_preferidas:
            settings = replace(
                settings,
                lojas_preferidas=tuple(
                    item.strip()
                    for item in args.lojas_preferidas.split(",")
                    if item.strip()
                ),
            )
        if args.somente_lojas_preferidas:
            settings = replace(settings, somente_lojas_preferidas=True)
        if args.similaridade_minima is not None:
            settings = replace(
                settings, similaridade_minima=args.similaridade_minima
            )

        # Token do Mercado Livre renovado antes da coleta comecar: uma coleta
        # longa nao pode morrer no meio por vencimento.
        if "mercadolivre" in selected and not settings.ml_token:
            try:
                settings = replace(
                    settings,
                    ml_token=ml_token.token_valido(args.ml_token_arquivo),
                )
            except PriceCollectorError as exc:
                print(f"Aviso do token do Mercado Livre: {exc}", file=sys.stderr)

        products = read_products(args.input, args.sheet, args.max_products)
        browser = BrowserRpa(settings)
        providers = _build_providers(selected, browser)
        # Fonte de API nao abre navegador; subir o Chromium a toa custa tempo
        # e impede rodar em servidor sem tela.
        precisa_navegador = any(
            getattr(item, "requires_browser", True) for item in providers
        )
        try:
            if precisa_navegador:
                browser.start()
            rows = CollectionService(
                providers,
                limit,
                delay,
                somente_exatos=settings.somente_exatos,
                similaridade_minima=settings.similaridade_minima,
                somente_lojas_preferidas=settings.somente_lojas_preferidas,
            ).collect(products)
        finally:
            if precisa_navegador:
                browser.close()

        destination = export_results(rows, args.output)
        database = export_database(rows, args.database)
        csv_files = export_csv(rows, args.csv_dir)
        historico = None
        if args.historico:
            append_run(rows, args.historico, args.input, args.providers)
            historico = args.historico
        offers = sum(1 for row in rows if row.status == "OK")
        similars = sum(
            1
            for row in rows
            if row.result is not None and row.result.possible_similar
        )
        errors = sum(1 for row in rows if row.status == "ERRO")
        print(
            f"Concluido: {len(products)} produtos, {offers} ofertas, "
            f"{similars} similares e {errors} erros."
        )
        print(f"Excel: {destination}")
        print(f"Base de dados: {database}")
        print(f"CSV: {', '.join(str(item) for item in csv_files)}")
        if historico:
            print(f"Historico acumulado: {historico}")
        return 0 if not errors else 1
    except KeyboardInterrupt:
        print("Coleta interrompida pelo usuario.", file=sys.stderr)
        return 130
    except PriceCollectorError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Erro de arquivo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
