import re
import random

from html import unescape
from lxml import etree, html
from worker_async.worker_types import (
    ContainerIdentifier,
    PaginationButtons,
)
from bs4.element import PageElement
from typing import List, Tuple, Optional, cast, Any, Callable, Awaitable
from worker_async.core.prompts import (
    PROMPT_IDENTIFY_PAGINATION_CONTAINER,
)
from bs4 import BeautifulSoup, Tag
from worker_async.core.llm_utils import call_llm_structured
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Page
from urllib.parse import urlparse
from dataclasses import dataclass


@dataclass
class PaginationDetector:
    logger: Any
    page: Optional[Page]
    llm_client: Any
    llm_model: str
    containers_html: dict[str, set[str]]
    process_page_job_listing_with_pagination: Callable[[str, str, bool], Awaitable[None]]
    restart_context: Callable
    normalize_url: Callable
    timeout: int = 20000

    @staticmethod
    def share_base_and_path_level(url1: str, url2: str) -> bool:
        """Check if two URLs are in the same listing scope with at most one extra path level."""
        parsed1 = urlparse(url1)
        parsed2 = urlparse(url2)

        domain1 = parsed1.netloc.lower().replace("www.", "")
        domain2 = parsed2.netloc.lower().replace("www.", "")
        if domain1 != domain2:
            return False  # Different domains

        path1 = [p for p in parsed1.path.split("/") if p]
        path2 = [p for p in parsed2.path.split("/") if p]

        if not path1[: len(path2)] == path2:
            return False

        if len(path1) > len(path2) + 1:
            return False

        return True

    async def extract_xpaths_from_container(
        self, container_html: str, soup: BeautifulSoup
    ) -> PaginationButtons:
        """
        Extracts valid full-page XPath selectors for clickable elements that match
        the provided container structure (useful for detecting pagination buttons).
        """
        # --- Parse the provided container HTML snippet ---
        try:
            container_root = html.fromstring(container_html)
        except Exception as e:
            self.logger.warning(f"Failed to parse container HTML: {e}")
            return {"pagination_buttons": []}

        # --- Parse the full page HTML (from BeautifulSoup) into lxml for XPath operations ---
        try:
            full_root = etree.HTML(str(soup))
            full_tree = etree.ElementTree(full_root)
        except Exception as e:
            self.logger.warning(f"Failed to parse soup into lxml: {e}")
            return {"pagination_buttons": []}

        # --- Identify the container tag and its attributes for matching ---
        tag = container_root.tag
        el_attrib = container_root.attrib

        # --- Find all elements with the same tag in the full DOM ---
        candidates = cast(list[etree._Element], full_tree.xpath(f".//{tag}"))
        matching_containers = []

        # --- Keep containers whose attributes closely match the original container ---
        for c in candidates:
            try:
                if all(
                    c.get(k) == v
                    for k, v in el_attrib.items()
                    if k
                    not in [
                        "style",
                        "data-ps",
                        "au-target-id",
                        "v-phw-setting",
                    ]  # change across page loads or are used internally by frameworks
                ):
                    matching_containers.append(c)
            except Exception as e:
                self.logger.warning(f"Error comparing candidate <{tag}>: {e}")

        # --- Stop if no matching containers found in the full DOM ---
        if not matching_containers:
            self.logger.warning(
                f"No matching containers found in full DOM for <{tag} {el_attrib}>"
            )
            return {"pagination_buttons": []}

        pagination_xpaths = set()

        # --- For each matching container, look for clickable elements inside it ---
        for matched in matching_containers:
            try:

                clickable_elements = cast(
                    list[etree._Element],
                    matched.xpath(
                        ".//a | .//button | .//input[@type='submit' or @type='button'] | .//*[@onclick] | .//*[@role='button']"
                    ),
                )

                # --- Generate XPaths for each clickable element ---
                for el in clickable_elements:
                    try:
                        xpath = full_tree.getpath(el)
                        href = el.get("href")

                        # Add href filter if available (more precise locator)
                        xpath_with_href = (
                            f"{xpath}[@href='{unescape(href.strip())}']"
                            if href
                            else xpath
                        )

                        # --- Verify visibility in the actual page using Playwright ---
                        try:
                            assert self.page is not None, "Page not initialized"
                            locator = self.page.locator(
                                f"xpath={xpath_with_href}"
                            ).first
                            if await locator.count() > 0:
                                pagination_xpaths.add(xpath_with_href)
                            else:
                                self.logger.info(f"Not visible: {xpath_with_href}")
                        except Exception as e:
                            self.logger.info(
                                f"Visibility check failed for {xpath_with_href}: {e}"
                            )

                    except Exception as e:
                        self.logger.warning(f"Error processing element XPath: {e}")
            except Exception as e:
                self.logger.warning(f"Error processing container: {e}")

        return {"pagination_buttons": list(pagination_xpaths)}

    async def identify_pagination_container(
        self, soup: BeautifulSoup, base_url: str
    ) -> Optional[Tuple[str, str]]:
        """
        Use heuristics + LLM confirmation to identify the pagination container
        (the HTML element containing next/previous page buttons or links).
        """

        if not soup.body:
            self.logger.warning("No <body> found in the soup!")
            return None

        # --- Collect base candidates (nav/div/ul), reversed so footer comes first ---
        pagination_candidates = list(reversed(soup.body.find_all(["nav", "div", "ul"])))

        # --- Keywords often associated with pagination ---
        PAGINATION_KEYWORDS = [
            "pagination",
            "pager",
            "page",
            "nav",
            "pagenav",
            "paginate",
            "pag",
        ]

        # --- Step 1: Filter by attribute names and values ---
        def matches_keywords(tag: Tag) -> bool:
            def attr_text(t: PageElement, attr: str) -> str:
                if not isinstance(t, Tag):
                    return ""
                val = t.get(attr)
                if isinstance(val, list):
                    return " ".join(val).lower()
                return (val or "").lower()

            for attr in ("id", "class", "aria-label"):
                if any(kw in attr_text(tag, attr) for kw in PAGINATION_KEYWORDS):
                    return True

            # Also check children
            for child in tag.find_all(True):
                for attr in ("id", "class", "aria-label"):
                    if any(kw in attr_text(child, attr) for kw in PAGINATION_KEYWORDS):
                        return True
            return False

        pagination_candidates = [
            t
            for t in pagination_candidates
            if isinstance(t, Tag) and matches_keywords(t)
        ]

        # --- Step 2: Filter by pagination-related visible text ---
        TEXT_KEYWORDS = [
            "next",
            "prev",
            "previous",
            "page",
            "pagination",
            "pager",
            "first",
            "last",
            "nav",
            "pagenav",
            "paginate",
            "pg",
            "pgn",
            "step",
            "pag",
            "weiter",
            "suivant",
            "siguiente",
            "nächste",
            "volgende",
            "التالي",
            "다음",
            "次へ",
            "下一页",
            ">>",
            ">",
            "<",
            "<<",
            "→",
            "←",
            "⇒",
            "⇐",
            "➜",
            "➝",
            "➞",
            "➡",
            "⬅",
            "⏩",
            "⏪",
        ] + [str(i) for i in range(200)]

        def contains_text_keyword(tag: Tag) -> bool:
            """Check whether the tag or its children contain pagination-related keywords."""

            def safe_attr_text(t: Tag, attr: str) -> str:
                """Safely return lowercase text for an attribute (handles str, list, None)."""
                val = t.get(attr)
                if isinstance(val, list):
                    return " ".join(val).lower()
                return (val or "").lower()

            combined_text = (
                tag.get_text(" ", strip=True).lower()
                + " "
                + " ".join(
                    safe_attr_text(tag, attr) for attr in ("aria-label", "title")
                )
                + " "
                + " ".join(
                    child.get_text(" ", strip=True).lower()
                    + " "
                    + " ".join(
                        safe_attr_text(child, attr) for attr in ("aria-label", "title")
                    )
                    for child in tag.find_all(True)
                    if isinstance(child, Tag)
                )
            )

            return any(kw in combined_text for kw in TEXT_KEYWORDS)

        pagination_candidates = [
            t
            for t in pagination_candidates
            if isinstance(t, Tag) and contains_text_keyword(t)
        ]

        # --- Step 3: Must contain clickable elements ---
        def has_clickable(tag):
            return any(
                el.name in ["a", "button"]
                or (el.name == "input" and el.get("type") in ["submit", "button"])
                or el.has_attr("onclick")
                or el.get("role", "").lower() == "button"
                for el in tag.find_all(True)
            )

        pagination_candidates = [t for t in pagination_candidates if has_clickable(t)]

        # --- Step 4: Deduplicate nested containers ---
        unique_candidates: list[Tag] = []
        for tag in pagination_candidates[:15]:
            if not isinstance(tag, Tag):
                continue
            if not any(
                isinstance(parent, Tag) and tag in parent.descendants
                for parent in unique_candidates
            ):
                unique_candidates.append(tag)

        # --- Step 5: Rank by number of same-domain hrefs ---
        def count_base_links(tag: Tag) -> int:
            if not base_url:
                return 0
            hrefs = [a.get("href", "") for a in tag.find_all("a") if isinstance(a, Tag)]

            return sum(
                base_url in (href if isinstance(href, str) else " ".join(href or []))
                for href in hrefs
            )

        unique_candidates.sort(key=count_base_links, reverse=True)

        max_retries = 2
        retry_delay = 2

        for index, tag in enumerate(unique_candidates):
            html_snippet = tag.prettify()[:3000]  # limit input token size

            messages = [
                {"role": "system", "content": PROMPT_IDENTIFY_PAGINATION_CONTAINER},
                {
                    "role": "user",
                    "content": f"### **Pagination Candidate {index + 1} (nav, div, or ul)**: {str(html_snippet)}",
                },
            ]

            for _ in range(max_retries):

                try:
                    result_structured = call_llm_structured(
                        llm_client=self.llm_client,
                        model=self.llm_model,
                        messages=messages,
                        logger=self.logger,
                        max_tokens=8192,
                        temperature=0.0,
                        retry=True,
                        pydantic_model=ContainerIdentifier,
                    )

                    if not result_structured:
                        self.logger.warning(f"No valid JSON response from LLM")
                        continue

                    try:
                        validated = ContainerIdentifier.model_validate(
                            result_structured
                        )
                    except Exception as e:
                        self.logger.error(f"Validation failed: {e}")
                        break

                    container_identifier = (
                        (validated.container_identifier or "").strip().lower()
                    )

                    if not container_identifier or container_identifier == "none":
                        self.logger.info(
                            f"No valid pagination container found for candidate {index + 1}. Skipping..."
                        )
                        break

                    # --- Extract clickable XPaths from container ---
                    xpaths_info = await self.extract_xpaths_from_container(
                        str(tag.prettify()), soup
                    )
                    pagination_xpaths = xpaths_info.get("pagination_buttons", [])

                    # --- Verify if any clickable element is visible on the page ---
                    any_visible = False
                    for xpath in pagination_xpaths:
                        try:
                            assert self.page is not None, "Page not initialized"
                            locator = self.page.locator(f"xpath={xpath}").first
                            if await locator.count() > 0:
                                any_visible = True
                                break
                        except Exception as e:
                            self.logger.info(
                                f"Could not check visibility for XPath: {xpath} ({e})"
                            )

                    if not any_visible:
                        self.logger.info(
                            "Pagination container has no visible clickable elements. Skipping..."
                        )
                        continue

                    self.logger.info(
                        f"Pagination container found: {container_identifier}"
                    )

                    return container_identifier, str(tag.prettify())

                except Exception as e:
                    self.logger.info(
                        f"LLM Error in container identification for candidate {index + 1}: {e}"
                    )

        self.logger.info("No valid pagination container identified.")

        return None

    async def extract_pagination_buttons(
        self, soup: BeautifulSoup, base_url: str
    ) -> PaginationButtons:
        """
        Two-step process to extract pagination buttons using LLM assistance.

        Step 1: Try any previously identified pagination containers from memory (`self.containers_html`) or database.
        Step 2: If none work, use the LLM to detect a new pagination container from the page.
        """

        # --- Ensure the base_url has an entry in the cache ---
        self.containers_html.setdefault(base_url, set())

        # --- Step 1: Try known containers first (cached from previous pages or from database) ---
        known_containers = self.containers_html.get(base_url, set())
        if known_containers:
            self.logger.info(
                f"Trying known containers from self.containers_html... {base_url}"
            )

            for container_html in self.containers_html[base_url]:
                pagination_data = await self.extract_xpaths_from_container(
                    container_html, soup
                )
                if pagination_data["pagination_buttons"]:
                    self.containers_html[base_url].add(container_html)
                    self.logger.info("Found working container from set.")
                    return pagination_data

            self.logger.info("None of the containers worked. Falling back to LLM.")

        # --- Step 2: Fallback — ask LLM to identify a new pagination container ---
        container_identified = await self.identify_pagination_container(soup, base_url)

        if not container_identified:

            self.logger.info("No valid container found.")

            return {"pagination_buttons": []}

        _, container_html = container_identified

        # --- Cache the newly discovered container ---
        self.containers_html[base_url].add(container_html)

        # --- Extract pagination XPaths from the identified container ---
        pagination_data = await self.extract_xpaths_from_container(container_html, soup)

        return pagination_data

    async def check_if_pagination_buttons(self, url: str, retries=1) -> List[str]:
        """
        Loads a given URL using Playwright and attempts to detect pagination buttons.

        Args:
            url: The webpage URL to inspect.
            retries: Number of retry attempts if a Playwright timeout occurs.

        Returns:
            A list of XPath strings corresponding to detected pagination buttons.
        """
        try:
            assert self.page is not None, "Page not initialized"

            await self.page.goto(url, timeout=self.timeout, wait_until="load")

            await self.page.wait_for_timeout(random.uniform(1000, 3000))

            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            html_content = await self.page.content()

            soup = BeautifulSoup(html_content, "html.parser")

            for tag in soup(["script", "style", "meta", "noscript", "svg"]):
                tag.decompose()

            result_pagination_buttons = await self.extract_pagination_buttons(soup, url)

            pagination_buttons = result_pagination_buttons.get("pagination_buttons", [])

            return pagination_buttons

        except PlaywrightTimeoutError as e:
            self.logger.warning(f"Playwright error at {url}: {e}")
            if retries > 0:
                self.logger.info("Restarting browser and retrying once...")
                self.restart_context()
                return await self.check_if_pagination_buttons(url, retries=retries - 1)
            else:
                self.logger.error("Retry failed, skipping.")
                return []

        except Exception as e:
            self.logger.error(f"Unexpected error on {url}: {e}")
            return []

    async def handle_dynamic_pagination(
        self, button_xpath: str, url: str, base_url: str
    ) -> None:
        """Handle JavaScript-based pagination via clickable buttons."""
        self.logger.info(f"Dynamic pagination detected → clicking {button_xpath}")
        try:
            assert self.page is not None, "Page not initialized"
            locator = self.page.locator(f"xpath={button_xpath}").first
            await locator.wait_for(state="visible", timeout=self.timeout)
            await locator.scroll_into_view_if_needed()

            element_handle = await locator.element_handle()
            if element_handle:
                await self.page.evaluate("(el) => el.click()", element_handle)
                await self.page.wait_for_timeout(random.uniform(2000, 5000))
            else:
                self.logger.warning(f"No element handle found for {button_xpath}")
                return

            await self.process_page_job_listing_with_pagination(
                url, base_url, True
            )

        except PlaywrightTimeoutError:
            self.logger.warning(
                f"Timeout: Button not clickable in time: {button_xpath}"
            )
        except Exception as e:
            self.logger.warning(
                f"Error clicking button {button_xpath}: {type(e).__name__}: {e}"
            )

    async def handle_standard_pagination(
        self, button_xpath: str, url: str, base_url: str
    ) -> None:
        """Follow standard (href-based) pagination links."""
        match = re.search(r"\[@href=['\"]([^'\"]+)['\"]\]", button_xpath)
        if not match:
            self.logger.info(f"Could not extract href from XPath: {button_xpath}")
            return

        href = match.group(1)
        new_url = (
            href
            if href.startswith(("http://", "https://"))
            else self.normalize_url(url, href, False)
        )

        if new_url and not self.share_base_and_path_level(new_url, base_url):
            self.logger.info(f"Skipping {new_url} (outside base URL).")
            return

        self.logger.info(f"Following pagination link → {new_url}")
        
        await self.process_page_job_listing_with_pagination(
            new_url, base_url, False
        )
