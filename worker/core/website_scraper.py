import random
import asyncio

from typing import Optional
from worker.base_scraper import BaseScraper
from playwright.async_api import Browser, TimeoutError as PlaywrightTimeoutError
from urllib.parse import quote


class WebsiteScraper(BaseScraper):
    """Scraper that finds the company's official website via DuckDuckGo search."""

    def __init__(
        self,
        company_id: int,
        company_name: str,
        session_logger,
        browser: Browser,
        language_region="ch-en",
        timeout=20000,
    ):
        super().__init__(company_id, company_name, session_logger, browser)
        self.language_region = language_region
        self.timeout = timeout

    async def __call__(self) -> Optional[str]:
        """
        Searches DuckDuckGo for the company's official website and returns the first organic (non-ad) result URL.
        """
        query = f"{self.company_name} official company website"
        search_url = f"https://duckduckgo.com/?q={quote(query)}&kl={self.language_region}&t=h_&ia=web"
        self.session_logger.info(f"[{self.company_id}] Searching DuckDuckGo: {query}")

        await self.create_context_with_proxy()

        assert self.page is not None, "Page not initialized"

        try:

            await self.page.goto(search_url, wait_until="load", timeout=self.timeout)

            await self.page.wait_for_timeout(random.uniform(1000, 3000))

            await self.page.wait_for_selector(
                "ol.react-results--main li[data-layout='organic']", timeout=10000
            )
            results = await self.page.query_selector_all(
                "ol.react-results--main li[data-layout='organic']"
            )
            self.session_logger.info(f"Found {len(results)} results.")

            for _ in range(random.randint(1, 3)):
                await self.page.mouse.wheel(0, random.randint(200, 600))
                await self.page.wait_for_timeout(random.uniform(1000, 5000))

            for res in results:
                self.session_logger.info(res)
                link_element = await res.query_selector(
                    "a[data-testid='result-extras-url-link']"
                )
                if link_element:
                    href = await link_element.get_attribute("href")
                    if href and "duckduckgo.com" not in href:
                        self.session_logger.info(
                            f"[{self.company_id}] Found organic result: {query} -> {href}"
                        )
                        return href

            self.session_logger.warning(
                f"[{self.company_id}] No organic results found for {self.company_name}"
            )
            return None

        except PlaywrightTimeoutError:
        
            self.session_logger.warning(
                f"[{self.company_id}] Timeout while searching DuckDuckGo"
            )
        
            await self.page.screenshot(path="error_search.png", full_page=True)
        
            return None
        
        except Exception as e:
            self.session_logger.error(f"[{self.company_id}] Unexpected error: {e}")
            await self.page.screenshot(path="error_search.png", full_page=True)
            return None
        
        finally:
            await asyncio.sleep(random.uniform(1, 2))
            try:
                await self.clean_contexts_playwright()
            except Exception:
                pass
