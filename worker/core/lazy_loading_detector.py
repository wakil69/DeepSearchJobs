import random

from dataclasses import dataclass
from typing import Any
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Page

@dataclass
class LazyLoadingPageDetector:
    session_logger: Any
    timeout: int = 20000

    async def auto_scroll_page(self, page: Page) -> None:
        """
        Scrolls down the page until no more content is loaded.
        No max scroll limit. Stops when page height stabilizes.
        """
        
        last_height = await page.evaluate("document.body.scrollHeight")

        while True:
            try: 
                
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                
                await page.wait_for_timeout(random.uniform(3000, 5000))

                new_height = await page.evaluate("document.body.scrollHeight")

                if new_height == last_height:
                    self.session_logger.info("Page height stable — finished scrolling.")
                    break

                last_height = new_height
                
                self.session_logger.info(f"Scrolled → new height {new_height}")
            
            except PlaywrightTimeoutError as e:
                
                self.session_logger.error(f"❌ Timeout during auto-scrolling: {e}")
                                
                break
