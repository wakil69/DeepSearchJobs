import random 
from bs4 import BeautifulSoup
from typing import Tuple, Any
from playwright.async_api import Page

class PageProcessing:
    def __init__(
        self,
        session_logger: Any,
    ):
        self.session_logger = session_logger
    
    @staticmethod
    async def wait_for_links_in_page_stable(page: Page, timeout=2000, step=200):
        """Wait until the number of anchor links on the page stops changing for two consecutive checks."""

        last_count = -1
        elapsed = 0
        stable_rounds = 0

        while elapsed < timeout:
            count = await page.evaluate(
                """
                () => Array.from(document.querySelectorAll('a'))
                    .map(a => a.getAttribute('href'))
                    .filter(href => href && href.trim().length > 0)
                    .length
                """
            )

            if count == last_count:
                stable_rounds += 1
                if stable_rounds >= 2:   # require stability twice
                    return
            else:
                stable_rounds = 0

            last_count = count
            await page.wait_for_timeout(step)
            elapsed += step
            
    async def go_to_page(
        self, page: Page, url: str, MAX_PAGE_RETRIES=0, timeout=30000
    ) -> bool:
        """Navigate to a URL with retries, waiting for the page and its links to stabilize."""

        attempt = 0
        success = False

        while attempt <= MAX_PAGE_RETRIES and not success:

            try:

                attempt += 1

                await page.goto(
                    url,
                    timeout=timeout,
                    wait_until="load", #load
                )
                
                await self.wait_for_links_in_page_stable(page, timeout=5000, step=500)
                
                await page.wait_for_timeout(random.uniform(2000, 4000))
                                        
                success = True

            except Exception as e:
                self.session_logger.warning(
                    f"[{url}] page.goto failed "
                    f"(attempt {attempt}/{MAX_PAGE_RETRIES + 1}): {e}"
                )

                if attempt > MAX_PAGE_RETRIES:
                    self.session_logger.error(f"[{url}] Skipping after {attempt} failures")
                    break

        return success
    
    async def return_soup(self, page: Page) -> Tuple[str, BeautifulSoup]:
        """Extract the page HTML and return a cleaned BeautifulSoup object with noise tags removed."""

        html = await page.content()
        
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "meta", "noscript", "svg"]):
            tag.decompose()

        return html, soup
    
