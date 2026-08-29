"""Camada de automacao RPA baseada em Playwright e Chromium."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from .cookies import load_cookie_file
from .errors import BrowserBlockedError, ConfigurationError, ProviderError
from .product_analysis import normalize_text
from .settings import Settings


# Somente frases que so aparecem em pagina de bloqueio. Termos genericos como
# "tente novamente" e "try again" existem em pagina de resultado normal e
# geravam falso positivo, derrubando coleta valida.
BLOCK_MARKERS = (
    "acesso negado",
    "access denied",
    "checking your browser",
    "complete a verificacao",
    "detectamos trafego incomum",
    "nossos sistemas detectaram trafego incomum",
    "resolva o captcha",
    "robot check",
    "too many requests",
    "unusual traffic",
    "verify you are human",
    "verifique para continuar",
    "verifique se voce e humano",
    "verifique se voce e um robo",
)
# Bloqueio que nao adianta esperar: a fonte declara que a verificacao falhou
# e manda voltar depois. Nenhuma acao de quem esta na frente da tela libera a
# pagina, entao o RPA registra o erro e segue o lote em vez de esperar a toa.
TERMINAL_BLOCK_MARKERS = (
    "a verificacao falhou",
    "tente novamente mais tarde",
    "try again later",
    "verification failed",
)
# Paginas de bloqueio identificadas pela URL final apos o redirecionamento.
BLOCKED_URL_MARKERS = (
    "/sorry/",
    "/verify/traffic",
    "account-verification",
    "/captcha",
    "challenge",
)


@dataclass(frozen=True, slots=True)
class SiteSelectors:
    cards: tuple[str, ...]
    titles: tuple[str, ...]
    prices: tuple[str, ...]
    links: tuple[str, ...]
    descriptions: tuple[str, ...] = ()
    sellers: tuple[str, ...] = ()
    images: tuple[str, ...] = ("img",)
    # Fontes que truncam o titulo visivel guardam o texto completo no
    # atributo title; quando informado, ele tem prioridade sobre o texto.
    title_attributes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BrowserProductCard:
    title: str
    price_text: str | None
    purchase_url: str
    description: str | None = None
    seller: str | None = None
    image_url: str | None = None
    raw_text: str | None = None


class BrowserRpa:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._connected_over_cdp = False
        self._persistent = False

    def __enter__(self) -> BrowserRpa:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(self) -> None:
        if self._context is not None:
            return
        try:
            self._playwright = sync_playwright().start()
            launch_options: dict[str, Any] = {
                "headless": self.settings.headless,
                "slow_mo": self.settings.slow_mo_ms,
            }
            if self.settings.browser_channel:
                launch_options["channel"] = self.settings.browser_channel
            if self.settings.browser_cdp_url:
                self._browser = self._playwright.chromium.connect_over_cdp(
                    self.settings.browser_cdp_url
                )
                self._connected_over_cdp = True
                contexts = self._browser.contexts
                if not contexts:
                    raise ConfigurationError("Nenhum contexto encontrado no Chrome")
                self._context = contexts[0]
                return
            context_options: dict[str, Any] = {
                "locale": "pt-BR",
                "timezone_id": "America/Sao_Paulo",
                "viewport": {"width": 1440, "height": 1000},
            }
            state = self._storage_state_file()
            if state is not None and state.is_file():
                # Cookies de login e de verificacao ja concedidos pela pessoa.
                context_options["storage_state"] = str(state)
            if self.settings.browser_user_data_dir:
                user_data_dir = Path(self.settings.browser_user_data_dir).expanduser()
                self._context = self._playwright.chromium.launch_persistent_context(
                    str(user_data_dir), **launch_options, **context_options
                )
                self._persistent = True
                # A aba inicial nao pode ser fechada: e a unica janela do
                # perfil persistente, e o Chromium encerra junto com ela.
                # Ela e reaproveitada como aba de trabalho.
                for extra in self._context.pages[1:]:
                    if extra.url == "about:blank":
                        extra.close()
            else:
                self._browser = self._playwright.chromium.launch(**launch_options)
                self._context = self._browser.new_context(**context_options)
            self._apply_cookie_file()
        except Exception as exc:
            self.close()
            if self.settings.browser_cdp_url:
                raise ConfigurationError(
                    f"Nao foi possivel conectar ao Chrome em "
                    f"{self.settings.browser_cdp_url}. Feche todas as janelas "
                    "do Chrome e inicie uma instancia com "
                    "--remote-debugging-port=9222 e um --user-data-dir "
                    "dedicado; depois confirme a porta 9222 e tente novamente."
                ) from exc
            raise ConfigurationError(
                "Nao foi possivel iniciar o Chromium. Execute: "
                "python -m playwright install chromium"
            ) from exc

    def _apply_cookie_file(self) -> None:
        """Carrega cookies exportados do navegador (ex.: Cookie-Editor)."""
        if not self.settings.cookies_path or self._context is None:
            return
        cookies = load_cookie_file(self.settings.cookies_path)
        self._context.add_cookies(cookies)
        print(f"{len(cookies)} cookies carregados da sessao exportada", flush=True)

    def _storage_state_file(self) -> Path | None:
        path = self.settings.storage_state_path
        return Path(path).expanduser() if path else None

    def save_storage_state(self) -> None:
        """Grava cookies e sessao para a proxima execucao nao repetir login."""
        state = self._storage_state_file()
        if state is None or self._context is None:
            return
        try:
            state.parent.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(state))
            print(f"Sessao salva em {state}", flush=True)
        except Exception as exc:
            print(f"Nao foi possivel salvar a sessao: {exc}", flush=True)

    def close(self) -> None:
        self.save_storage_state()
        if self._context is not None and not self._connected_over_cdp:
            self._context.close()
            self._context = None
        elif self._connected_over_cdp:
            self._context = None
        if self._browser is not None and not self._connected_over_cdp:
            self._browser.close()
            self._browser = None
        elif self._browser is not None:
            self._browser = None
            self._connected_over_cdp = False
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._persistent = False

    def authenticate(self, url: str, wait_seconds: float) -> bool:
        """Abre a pagina de login e espera a pessoa entrar na propria conta.

        O RPA nao digita, nao le e nao guarda credencial: ele so observa a
        navegacao sair da tela de login e entao grava os cookies da sessao.
        """
        if self._context is None:
            raise ConfigurationError("Browser RPA nao foi iniciado")
        page = self._context.pages[0] if self._context.pages else self._context.new_page()
        timeout_ms = int(self.settings.browser_timeout_seconds * 1000)
        page.set_default_timeout(timeout_ms)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            page.bring_to_front()
        except Exception:
            pass
        print(
            f"Faca login na janela aberta ({url}). "
            f"O RPA aguarda ate {int(wait_seconds)}s e salva a sessao sozinho.",
            flush=True,
        )
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            page.wait_for_timeout(3000)
            current = (page.url or "").casefold()
            if "login" not in current and "signin" not in current:
                print(f"Login concluido em {page.url.split('?')[0]}", flush=True)
                self.save_storage_state()
                return True
        print("Tempo de login esgotado; nada foi salvo.", flush=True)
        return False

    def fetch_json(self, provider_name: str, page_url: str, api_path: str) -> dict:
        """Le a API JSON publica da propria fonte, de dentro da pagina dela.

        A chamada sai da propria origem, com a sessao que o navegador ja tem.
        E mais estavel que raspar HTML: nao existe seletor para quebrar quando
        o site muda de layout, e a resposta ja traz faixa de preco.
        """
        if self._context is None:
            raise ConfigurationError("Browser RPA nao foi iniciado")
        try:
            page = (
                self._context.pages[0]
                if self._context.pages
                else self._context.new_page()
            )
        except Exception as exc:
            raise ProviderError(
                f"{provider_name}: o navegador foi fechado; mantenha a janela "
                "aberta durante a coleta"
            ) from exc
        timeout_ms = int(self.settings.browser_timeout_seconds * 1000)
        page.set_default_timeout(timeout_ms)
        try:
            if not page.url.startswith(page_url.rstrip("/")):
                page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(4000)
            try:
                self._raise_if_blocked(page, provider_name)
            except BrowserBlockedError:
                if not self._request_manual_verification(page, provider_name):
                    raise
                page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(3000)
                self._raise_if_blocked(page, provider_name)
            payload = page.evaluate(
                """
                async (path) => {
                    try {
                        const response = await fetch(path, {
                            credentials: 'include',
                            headers: {
                                'Accept': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest'
                            }
                        });
                        const body = await response.json();
                        return {status: response.status, body: body};
                    } catch (error) {
                        return {status: 0, error: error.toString()};
                    }
                }
                """,
                api_path,
            )
            status = payload.get("status")
            if status != 200:
                detail = payload.get("error") or f"HTTP {status}"
                raise ProviderError(
                    f"{provider_name}: a API respondeu {detail} em {api_path[:80]}"
                )
            return payload.get("body") or {}
        except (BrowserBlockedError, ProviderError):
            raise
        except PlaywrightTimeoutError as exc:
            raise ProviderError(
                f"{provider_name}: a pagina nao carregou dentro do tempo limite"
            ) from exc
        except Exception as exc:
            detail = str(exc).strip().splitlines()
            raise ProviderError(
                f"{provider_name}: falha ao consultar a API "
                f"({type(exc).__name__}: {detail[0] if detail else 'sem mensagem'})"
            ) from exc

    def collect_cards(
        self,
        provider_name: str,
        url: str,
        selectors: SiteSelectors,
        limit: int,
    ) -> list[BrowserProductCard]:
        """Coleta os cards visiveis, com uma segunda tentativa.

        Falha de navegacao isolada acontece e derrubava a linha inteira do
        lote. Bloqueio e CAPTCHA nao sao retentados: repetir e insistir na
        protecao.
        """
        try:
            return self._collect_once(provider_name, url, selectors, limit)
        except BrowserBlockedError:
            raise
        except ProviderError:
            return self._collect_once(provider_name, url, selectors, limit)

    def _collect_once(
        self,
        provider_name: str,
        url: str,
        selectors: SiteSelectors,
        limit: int,
    ) -> list[BrowserProductCard]:
        if self._context is None:
            raise ConfigurationError("Browser RPA nao foi iniciado")
        reuse_page = (
            self._connected_over_cdp or self._persistent
        ) and bool(self._context.pages)
        page = self._context.pages[0] if reuse_page else self._context.new_page()
        timeout_ms = int(self.settings.browser_timeout_seconds * 1000)
        page.set_default_timeout(timeout_ms)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.locator("body").wait_for(state="visible", timeout=timeout_ms)
            # Os comparadores montam os cards por scroll; sem isso a lista
            # fica vazia mesmo com a pagina carregada.
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(1500)
            self._dismiss_cookie_banner(page)
            try:
                self._raise_if_blocked(page, provider_name)
            except BrowserBlockedError:
                if not self._request_manual_verification(page, provider_name):
                    raise
                # Resolver a verificacao devolve a busca generica, nao a URL
                # de compras pedida. Sem recarregar, a leitura seguinte era
                # feita na pagina errada.
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1500)
                self._raise_if_blocked(page, provider_name)
            cards = self._find_cards(page, selectors.cards, timeout_ms)
            results: list[BrowserProductCard] = []
            seen: set[str] = set()
            for index in range(min(cards.count(), max(limit * 3, limit))):
                card = cards.nth(index)
                title = self._first_attribute(
                    card, selectors.title_attributes, "title"
                ) or self._first_text(card, selectors.titles)
                link = self._first_attribute(card, selectors.links, "href")
                if not title or not link:
                    continue
                purchase_url = urljoin(page.url, link)
                identity = f"{title.casefold()}|{purchase_url}"
                if identity in seen:
                    continue
                seen.add(identity)
                raw_text = self._safe_text(card)
                price_text = self._first_text(card, selectors.prices)
                if not price_text:
                    price_text = self._price_from_text(raw_text)
                results.append(
                    BrowserProductCard(
                        title=title,
                        price_text=price_text,
                        purchase_url=purchase_url,
                        description=self._first_text(card, selectors.descriptions),
                        seller=self._first_text(card, selectors.sellers),
                        image_url=self._absolute_attribute(
                            page, card, selectors.images, "src"
                        ),
                        raw_text=raw_text,
                    )
                )
                if len(results) >= limit:
                    break
            if not results:
                # A Shopee redireciona para a verificacao depois da checagem
                # inicial; sem reavaliar aqui, bloqueio virava "sem resultado".
                self._raise_if_blocked(page, provider_name)
                self._dump_page(page, provider_name)
            return results
        except BrowserBlockedError:
            raise
        except PlaywrightTimeoutError as exc:
            raise ProviderError(
                f"{provider_name}: a pagina nao carregou dentro do tempo limite"
            ) from exc
        except ProviderError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if "Target page, context or browser has been closed" in str(exc):
                raise ProviderError(
                    f"{provider_name}: o navegador foi fechado durante a coleta"
                ) from exc
            raise ProviderError(f"{provider_name}: falha durante a navegacao RPA") from exc
        finally:
            if not reuse_page:
                page.close()

    @staticmethod
    def _dismiss_cookie_banner(page: Page) -> None:
        for label in ("Aceitar tudo", "Aceitar todos", "Concordo", "Accept all"):
            button = page.get_by_role("button", name=label, exact=True)
            try:
                if button.count() and button.first.is_visible():
                    button.first.click(timeout=1500)
                    return
            except PlaywrightTimeoutError:
                continue

    @staticmethod
    def _raise_if_blocked(page: Page, provider_name: str) -> None:
        current_url = (page.url or "").casefold()
        if any(marker in current_url for marker in BLOCKED_URL_MARKERS):
            raise BrowserBlockedError(
                f"{provider_name}: a fonte redirecionou para uma pagina de "
                f"verificacao ({page.url.split('?')[0]}); o RPA nao tenta "
                "contornar a protecao"
            )
        body = BrowserRpa._safe_text(page.locator("body"))
        # normalize_text remove acentos: sem isso "trafego" nunca casa com
        # "trafego" acentuado devolvido pelo Google e o bloqueio passava batido.
        normalized = normalize_text(body)
        if any(normalize_text(marker) in normalized for marker in BLOCK_MARKERS):
            raise BrowserBlockedError(
                f"{provider_name}: bloqueio ou CAPTCHA detectado; "
                "o RPA nao tenta contornar a protecao"
            )

    @staticmethod
    def _is_terminal_block(page: Page) -> bool:
        body = normalize_text(BrowserRpa._safe_text(page.locator("body")))
        return any(
            normalize_text(marker) in body for marker in TERMINAL_BLOCK_MARKERS
        )

    def _request_manual_verification(self, page: Page, provider_name: str) -> bool:
        """Espera um humano concluir a verificacao da propria fonte.

        O RPA nao resolve nem contorna o desafio: ele apenas percebe que a
        pagina deixou de ser de bloqueio e retoma a coleta. Quem decide se ha
        espera e `manual_verification_seconds`; detectar terminal interativo
        nao serve, porque um stdin herdado pode se dizer TTY e devolver EOF na
        primeira leitura, abortando a espera sem ninguem ver nada.
        """
        if self.settings.headless and not self.settings.browser_cdp_url:
            return False
        if self._is_terminal_block(page):
            print(
                f"{provider_name}: a fonte recusou a verificacao e pediu para "
                "tentar mais tarde. Recarregando uma vez para ver se aparece "
                "um desafio que possa ser resolvido na tela.",
                flush=True,
            )
            try:
                page.bring_to_front()
                page.wait_for_timeout(5000)
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
            except Exception:
                return False
            if self._is_terminal_block(page):
                print(
                    f"{provider_name}: recusa mantida; seguindo o lote sem "
                    "insistir na protecao.",
                    flush=True,
                )
                return False
        return self._wait_until_unblocked(page, provider_name)

    def _wait_until_unblocked(self, page: Page, provider_name: str) -> bool:
        limit = self.settings.manual_verification_seconds
        if limit <= 0:
            return False
        print(
            f"{provider_name}: bloqueio/CAPTCHA detectado. Resolva na janela do "
            f"navegador; o RPA retoma sozinho quando a pagina liberar "
            f"(ate {int(limit)}s de espera).",
            flush=True,
        )
        try:
            page.bring_to_front()
        except Exception:
            pass
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            try:
                page.wait_for_timeout(3000)
            except Exception:
                # A janela foi fechada enquanto se esperava a verificacao.
                print(
                    f"{provider_name}: a janela do navegador foi fechada "
                    "durante a verificacao.",
                    flush=True,
                )
                return False
            if not self._is_blocked(page):
                print(f"{provider_name}: verificacao concluida, retomando.", flush=True)
                # Guardar agora: uma falha adiante nao pode custar a
                # verificacao que a pessoa acabou de fazer.
                self.save_storage_state()
                return True
        print(f"{provider_name}: tempo de verificacao esgotado.", flush=True)
        return False

    def _is_blocked(self, page: Page) -> bool:
        try:
            self._raise_if_blocked(page, "")
        except BrowserBlockedError:
            return True
        except Exception:
            # Pagina inacessivel conta como bloqueada: quem chama decide.
            return True
        return False

    @staticmethod
    def _find_cards(page: Page, selectors: tuple[str, ...], timeout_ms: int) -> Locator:
        """Devolve o primeiro seletor de card que realmente casa na pagina.

        Combinar todos os seletores com os genericos fazia o locator casar
        centenas de `a[href]` do cabecalho antes do primeiro card real, e o
        limite de leitura se esgotava em links sem titulo nem preco.
        """
        if selectors:
            primary = page.locator(", ".join(selectors))
            try:
                primary.first.wait_for(state="visible", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                pass
            if primary.count():
                return primary
        for selector in ("div[role='listitem']", "[data-docid]", "li", "article"):
            fallback = page.locator(selector)
            if fallback.count():
                return fallback
        return page.locator(", ".join(selectors) if selectors else "a[href]")

    def _dump_page(self, page: Page, provider_name: str) -> None:
        """Salva a pagina quando nenhum card e reconhecido.

        Sem isso, "sem resultado" e indistinguivel entre pagina vazia de
        verdade e seletor desatualizado.
        """
        if not self.settings.debug_dump_dir:
            return
        folder = Path(self.settings.debug_dump_dir).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "-", provider_name.casefold()).strip("-")
        base = folder / f"{slug}-{stamp}"
        try:
            base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
            base.with_suffix(".url.txt").write_text(page.url, encoding="utf-8")
            page.screenshot(path=str(base.with_suffix(".png")), full_page=False)
            print(f"        pagina salva em {base}.html", flush=True)
        except Exception as exc:
            print(f"        nao foi possivel salvar a pagina: {exc}", flush=True)

    @staticmethod
    def _first_text(root: Locator, selectors: tuple[str, ...]) -> str | None:
        for selector in selectors:
            locator = root.locator(selector).first
            try:
                if locator.count() and locator.is_visible():
                    text = locator.inner_text(timeout=1000).strip()
                    if text:
                        return text
            except PlaywrightTimeoutError:
                continue
        return None

    @staticmethod
    def _first_attribute(root: Locator, selectors: tuple[str, ...], name: str) -> str | None:
        for selector in selectors:
            locator = root.locator(selector).first
            try:
                if locator.count():
                    value = locator.get_attribute(name, timeout=1000)
                    if value:
                        return value.strip()
            except PlaywrightTimeoutError:
                continue
        return None

    @staticmethod
    def _absolute_attribute(
        page: Page, root: Locator, selectors: tuple[str, ...], name: str
    ) -> str | None:
        value = BrowserRpa._first_attribute(root, selectors, name)
        return urljoin(page.url, value) if value else None

    @staticmethod
    def _safe_text(locator: Locator) -> str:
        try:
            return locator.inner_text(timeout=3000).strip()
        except PlaywrightTimeoutError:
            return ""

    @staticmethod
    def _price_from_text(text: str) -> str | None:
        match = re.search(r"R\$\s*\d[\d.\s]*(?:,\d{1,2})?", text)
        return match.group(0) if match else None
