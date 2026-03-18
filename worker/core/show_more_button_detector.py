import random
import asyncio

from bs4 import BeautifulSoup
from worker.constants.prompts import PROMPT_IDENTIFY_SHOW_MORE_BUTTON_TEXT
from worker.utils.llm_utils import call_llm_structured
from worker.types.worker_types import (
    ButtonLoadMoreIdentifier,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Page
from typing import List, Tuple, Optional, Callable, Any
from collections import defaultdict
from urllib.parse import urlparse
from playwright.async_api import Page
from worker.dependencies import llm_client, LLM_MODEL
from worker.utils.text_utils import hash_page_content, extract_visible_text
from worker.utils.xpath_utils import find_first_existing_xpath
from worker.core.page_processing.page_processing import PageProcessing

class ShowMoreButtonDetector:
    def __init__(self, session_logger: Any, timeout: int = 20000):
        """Initialize ShowMoreButtonDetector with a session logger and Playwright timeout."""
        self.session_logger = session_logger
        self.timeout = timeout

        self.page_processing = PageProcessing(
            session_logger=session_logger,
        )

    @staticmethod
    def extract_all_text_with_xpath(
        soup: BeautifulSoup,
    ) -> Tuple[List[str], dict[str, List[str]]]:
        """
        Extract all visible text from the page.
        Returns:
            texts: list of unique text strings
            mapping: dict {text: [list of xpath(s)]}
        """

        def get_xpath(element) -> str:
            """Build a unique XPath for the given element."""
            components = []
            child = element
            for parent in element.parents:
                if parent.name is None:
                    break
                siblings = parent.find_all(child.name, recursive=False)
                if len(siblings) > 1:
                    index = siblings.index(child) + 1
                    components.append(f"{child.name}[{index}]")
                else:
                    components.append(child.name)
                child = parent
            return "/" + "/".join(reversed(components))

        texts = []
        mapping = defaultdict(list)
        seen = set()

        for element in soup.find_all(True):
            text = element.get_text(" ", strip=True)
            if text:
                xpath = get_xpath(element)

                # store mapping (multiple elements can share same text)
                mapping[text].append(xpath)

                # add to texts list only once
                if text not in seen:
                    texts.append(text)
                    seen.add(text)

        return texts, mapping

    async def extract_show_more_button(
        self, page: Page, soup: BeautifulSoup, url: str
    ) -> Optional[Tuple[str, str]]:
        """
        Uses an LLM to identify a 'Show More' (load more) button on the given page.
        It matches the detected button text to candidate XPaths extracted from the page.

        Returns:
            A tuple (xpath, button_text), both empty if no valid match is found.
        """
        try:
            texts, mapping = self.extract_all_text_with_xpath(soup)
            n = len(texts)
            if n < 50:
                page_text = "\n".join(texts)
            else:
                page_text = "\n".join(texts[n // 2 :])

            messages = [
                {
                    "role": "system",
                    "content": PROMPT_IDENTIFY_SHOW_MORE_BUTTON_TEXT,
                },
                {
                    "role": "user",
                    "content": f"URL: {url}\n\nPAGE TEXT:\n{page_text}",
                },
            ]

            result_structured = await call_llm_structured(
                llm_client=llm_client,
                model=LLM_MODEL,
                messages=messages,
                logger=self.session_logger,
                max_tokens=1024,
                temperature=0.0,
                retry=True,
                pydantic_model=ButtonLoadMoreIdentifier,
            )

            try:
                validated = ButtonLoadMoreIdentifier.model_validate(result_structured)
            except Exception as e:
                self.session_logger.error(
                    f"Validation failed for LLM output {result_structured}: {e}"
                )
                return None

            button_text = validated.button_text.strip() if validated.button_text else ""
            if not button_text:
                self.session_logger.info("No 'Show More' button text detected.")
                return None

            self.session_logger.info(f"Button text candidate: {button_text}")

            candidate_xpaths = mapping.get(button_text, [])
            if not candidate_xpaths:
                self.session_logger.warning(f"No XPath mapping found for text '{button_text}'")
                return None

            xpath = find_first_existing_xpath(soup, candidate_xpaths)

            if xpath:
                return xpath, button_text

            self.session_logger.warning(
                f"Text '{button_text}' found, but no matching XPath in page."
            )

            return None

        except Exception as e:
            self.session_logger.error(f"Unexpected error in extract_show_more_button: {e}")
            return None

    async def check_if_show_more_pagination_button(
        self, page: Page, url: str, retries=1
    ) -> Optional[Tuple[str, str]]:
        """
        Loads a webpage and checks for a 'Show More' (load more) pagination button.

        Args:
            url: The target webpage URL to inspect.
            retries: Number of retry attempts in case of Playwright timeouts.

        Returns:
            A tuple (xpath, button_text) if a valid 'Show More' button is found,
            otherwise None.
        """
        try:

            _, soup = await self.page_processing.return_soup(page)

            show_more_button = await self.extract_show_more_button(page, soup, url)

            return show_more_button

        except PlaywrightTimeoutError as e:
            self.session_logger.warning(f"Playwright error at {url}: {e}")
            if retries > 0:
                self.session_logger.info("Restarting browser and retrying once...")

                return await self.check_if_show_more_pagination_button(
                    page, url, retries=retries - 1
                )
            else:
                self.session_logger.error("Retry failed, skipping.")
                return None

        except Exception as e:
            self.session_logger.error(f"Unexpected error on {url}: {e}")
            return None

    async def get_page_content(self, page: Page):
        """Return the cleaned visible text of the current page with noise tags removed."""
        html_content = await page.content()

        soup = BeautifulSoup(html_content, "html.parser")

        for tag in soup(["script", "style", "meta", "noscript", "svg"]):
            tag.decompose()

        text = soup.get_text(" ", strip=True)

        return text

    async def click_button_load_more(self, page: Page, button_text: str):
        """
        Try clicking from the last child upwards for the element(s) that match button_text.
        Always re-extracts XPaths from the current DOM so it's up-to-date.
        """

        try:

            html_content = await page.content()
            soup = BeautifulSoup(html_content, "html.parser")

            for tag in soup(["script", "style", "meta", "noscript", "svg"]):
                tag.decompose()

            _, mapping = self.extract_all_text_with_xpath(soup)

            candidate_xpaths = mapping.get(button_text, [])

            if not candidate_xpaths:
                self.session_logger.warning(
                    f"[BUTTON_SHOW_MORE] No candidate XPaths found for text '{button_text}'"
                )
                return False

            # I have to handle shadow root, but for show more button, it is very rare cases...
            for xpath in candidate_xpaths:
                try:
                    locator = page.locator(f"xpath={xpath}").first

                    await locator.wait_for(state="attached", timeout=self.timeout)

                    child_locator = locator.locator("xpath=.//*")

                    count = await child_locator.count()

                    targets = [child_locator.nth(i) for i in range(count - 1, -1, -1)]

                    targets.append(locator)

                    for i, target in enumerate(targets):

                        try:

                            handle = await target.element_handle()

                            if handle:
                                await page.evaluate(
                                    "(el) => el.scrollIntoView({block: 'center'})",
                                    handle,
                                )

                                await page.wait_for_timeout(1000)

                                await page.evaluate("(el) => el.click()", handle)

                                self.session_logger.info(
                                    f"[BUTTON_SHOW_MORE] JS click succeeded"
                                )

                                return True

                        except Exception as e:
                            self.session_logger.warning(
                                f"[BUTTON_SHOW_MORE] Failed click on target #{i} of {xpath}: {e}"
                            )
                            continue

                except Exception as e:
                    self.session_logger.warning(
                        f"[BUTTON_SHOW_MORE] XPath candidate {xpath} not valid in live DOM: {e}"
                    )
                    continue

            self.session_logger.warning(
                f"[BUTTON_SHOW_MORE] Could not click any candidate for text '{button_text}'"
            )
            return False

        except Exception as e:
            self.session_logger.error(
                f"[BUTTON_SHOW_MORE] Error in click_last_child for text='{button_text}': {e}"
            )
            return False

    async def process_page_with_show_more_button(
        self, page: Page, url: str, show_more_button: Tuple[str, str]
    ) -> None:
        """
        Handles pages where pagination is driven by a 'Show More' button.

        The function repeatedly clicks the 'Show More' button, waits for new
        content to load, and stops when:
        - The URL path changes (navigated away),
        - No more 'Show More' button is found, or
        - The page content fingerprint repeats (no new content loaded).
        """

        _, button_text = show_more_button

        self.session_logger.info(
            f"Pagination of type 'Show more' found! That is the button text: {button_text}"
        )

        parsed_initial = urlparse(url)
        fingerprints: set[str] = set()

        # Store the first page fingerprint
        page_content = await self.get_page_content(page)
        prev_fingerprint = hash_page_content(page_content)
        fingerprints.add(prev_fingerprint)

        while True:
            try:

                current_url = page.url

                parsed_current = urlparse(current_url)

                if parsed_current.path != parsed_initial.path:
                    self.session_logger.warning(
                        f"URL path changed from {parsed_initial.path} → {parsed_current.path}, stopping loop."
                    )
                    break

                if not await self.click_button_load_more(page, button_text):
                    self.session_logger.info(
                        "No more 'Show More' button found — stopping pagination loop."
                    )
                    break

                await page.wait_for_load_state("networkidle", timeout=self.timeout)

                await page.wait_for_timeout(random.uniform(3000, 5000))

                page_content = await self.get_page_content(page)

                new_fingerprint = hash_page_content(page_content)

                if new_fingerprint in fingerprints:
                    self.session_logger.info("Fingerprint already seen → stopping loop.")
                    break

                fingerprints.add(new_fingerprint)

            except Exception as e:
                self.session_logger.warning(f"Error in pagination loop: {e}")
                break