import time
import unittest

from copercitrus_price_collector.browser import BrowserRpa
from copercitrus_price_collector.settings import Settings


def _settings(**overrides):
    base = {
        "headless": False,
        "browser_channel": None,
        "browser_user_data_dir": None,
        "browser_cdp_url": None,
        "browser_timeout_seconds": 45.0,
        "slow_mo_ms": 0,
        "request_delay_seconds": 0.0,
        "result_limit": 5,
        "manual_verification_seconds": 30.0,
        "debug_dump_dir": None,
        "storage_state_path": None,
        "cookies_path": None,
        "lojas_preferidas": ("mercado livre", "shopee"),
        "somente_exatos": True,
        "somente_lojas_preferidas": False,
        "apify_token": None,
        "similaridade_minima": 80.0,
    }
    base.update(overrides)
    return Settings(**base)


class FakeBody:
    def __init__(self, page):
        self.page = page

    def inner_text(self, timeout=0):
        return self.page.text


class FakePage:
    """Pagina que sai do bloqueio depois de N verificacoes."""

    def __init__(self, clears_after=2):
        self.url = "https://www.google.com/sorry/index"
        self.text = "Nossos sistemas detectaram tráfego incomum"
        self.clears_after = clears_after
        self.waits = 0

    def locator(self, selector):
        return FakeBody(self)

    def wait_for_timeout(self, milliseconds):
        # O Playwright realmente bloqueia aqui; sem dormir, o laco de espera
        # giraria milhares de vezes dentro do orcamento de tempo do teste.
        time.sleep(0.01)
        self.waits += 1
        if self.waits >= self.clears_after:
            self.url = "https://www.google.com/search?tbm=shop&q=lavadora"
            self.text = "Resultados da pesquisa"


class ManualVerificationTest(unittest.TestCase):
    def test_resumes_when_the_person_clears_the_challenge(self):
        rpa = BrowserRpa(_settings())
        page = FakePage(clears_after=2)

        self.assertTrue(rpa._wait_until_unblocked(page, "Google Shopping"))
        self.assertEqual(2, page.waits)

    def test_gives_up_when_the_challenge_stays(self):
        rpa = BrowserRpa(_settings(manual_verification_seconds=0.05))
        page = FakePage(clears_after=999)

        self.assertFalse(rpa._wait_until_unblocked(page, "Google Shopping"))

    def test_zero_timeout_disables_waiting(self):
        rpa = BrowserRpa(_settings(manual_verification_seconds=0))
        page = FakePage(clears_after=1)

        self.assertFalse(rpa._wait_until_unblocked(page, "Google Shopping"))
        self.assertEqual(0, page.waits)

    def test_headless_without_cdp_cannot_ask_a_person(self):
        """Sem janela visivel nao ha onde alguem resolver o desafio."""
        rpa = BrowserRpa(_settings(headless=True))
        page = FakePage(clears_after=1)

        self.assertFalse(rpa._request_manual_verification(page, "Google Shopping"))


if __name__ == "__main__":
    unittest.main()
