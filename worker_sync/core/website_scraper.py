import time
import random 
import time 

from typing import Optional
from worker_sync.base_scraper import BaseScraper
from playwright.sync_api import Browser, TimeoutError as PlaywrightTimeoutError
from pika.adapters.blocking_connection import BlockingChannel
from urllib.parse import quote


class WebsiteScraper(BaseScraper):
    """Scraper that finds the company's official website via DuckDuckGo search."""

    def __init__(
        self,
        company_id: int,
        company_name: str,
        logger,
        browser: Browser,
        ch: BlockingChannel,
    ):
        super().__init__(company_id, company_name, logger, browser, ch)

    def __call__(self) -> Optional[str]:
        """
        Searches DuckDuckGo for the company's official website and returns the first organic (non-ad) result URL.
        """
        query = f"{self.company_name} official company website"
        search_url = f"https://duckduckgo.com/?q={quote(query)}&t=h_&ia=web"
        self.logger.info(f"[{self.company_id}] Searching DuckDuckGo: {query}")

        try:
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
            
            time.sleep(random.uniform(1.5, 3.0))

            self.page.wait_for_selector("ol.react-results--main li[data-layout='organic']", timeout=10000)
            results = self.page.query_selector_all("ol.react-results--main li[data-layout='organic']")
            self.logger.info(f"Found {len(results)} results.")

            for _ in range(random.randint(1, 3)):
                self.page.mouse.wheel(0, random.randint(200, 600))
                time.sleep(random.uniform(0.2, 0.6))

            for res in results:
                self.logger.info(res)
                link_element = res.query_selector("a[data-testid='result-extras-url-link']")
                if link_element:
                    href = link_element.get_attribute("href")
                    if href and "duckduckgo.com" not in href:
                        self.logger.info(f"[{self.company_id}] Found organic result: {query} -> {href}")
                        return href

            self.logger.warning(f"[{self.company_id}] No organic results found for {self.company_name}")
            return None


        except PlaywrightTimeoutError:
            self.logger.warning(f"[{self.company_id}] Timeout while searching DuckDuckGo")
            return None
        except Exception as e:
            self.logger.error(f"[{self.company_id}] Unexpected error: {e}")
            self.page.screenshot(path="error_search.png", full_page=True)
            return None
        finally:
            time.sleep(random.uniform(1, 2))
            try:
                self.clean_contexts_playwright()
            except Exception:
                pass