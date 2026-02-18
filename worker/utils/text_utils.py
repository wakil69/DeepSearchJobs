import re 
import hashlib 

from bs4 import BeautifulSoup, Tag
from worker.types.worker_types import Job
from typing import List, Optional
from worker.utils.url_utils import normalize_url

def get_emails(text: str) -> set[str]:
    """Extracts and filters valid emails from the given text."""
    email_regex = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    possible_emails = set(re.findall(email_regex, text))
    valid_tlds = {
        "com",
        "org",
        "net",
        "edu",
        "gov",
        "eu",
        "br",
        "fr",
        "de",
        "es",
        "pl",
        "it",
        "uk",
        "ru",
        "in",
        "ch",
    }
    invalid_extensions = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "svg", "tiff"}

    valid_emails = set()

    for email in possible_emails:
        domain_parts = email.split(".")
        tld = domain_parts[-1].lower()

        if tld not in invalid_extensions:
            valid_emails.add(email)

    return valid_emails

def extract_structured_text(
    soup: BeautifulSoup,
    url: str,
    job_offers: List[Job] = [],
    skip_existing_jobs: bool = True,
) -> str:
    """
    Extracts structured text content (headings, paragraphs, lists, tables, links)
    with associated hyperlinks.

    Args:
        soup (BeautifulSoup): Parsed HTML soup of the page.
        url (str): Current page URL for resolving relative links.
        skip_existing_jobs (bool): If True, skip links already in self.job_offers.

    Returns:
        str: A structured text representation (markdown-like), capped at 128k chars.
    """

    structured_content = []
    seen_links = set()

    verified_existing_jobs = [job["job_url"] for job in job_offers]

    def handle_link(link: Optional[str], text: str):
        """Decide whether to include a link based on known jobs."""
        if not link:
            return None
        if skip_existing_jobs and link in verified_existing_jobs:
            return None
        return text

    def get_associated_link(element):
        """Finds the nearest anchor link within or related to the element."""
        link = element.find("a", href=True)
        if link:
            link = normalize_url(url, link["href"])
            seen_links.add(link)
            return link
        return ""

    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        link = get_associated_link(heading)
        if link:
            text = f"\n### {heading.get_text(strip=True)} ({link}) ###"
            result = handle_link(link, text)
            if result:
                structured_content.append(result)

    for paragraph in soup.find_all("p"):
        link = get_associated_link(paragraph)
        if link:
            text = f"- {paragraph.get_text(strip=True)} ({link})"
            result = handle_link(link, text)
            if result:
                structured_content.append(result)

    for ul in soup.find_all("ul"):
        if not isinstance(ul, Tag):
            continue
        items = []
        for li in ul.find_all("li"):
            if not isinstance(li, Tag):
                continue
            link = li.find("a", href=True)
            if isinstance(link, Tag) and link.has_attr("href"):
                link = normalize_url(url, str(link["href"]))
                seen_links.add(link)
                text = f"  • {li.get_text(strip=True)} ({link})"
                result = handle_link(link, text)
                if result:
                    items.append(result)
        if items:
            structured_content.append("\n".join(items))

    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        table_data = []
        for row in table.find_all("tr"):
            if not isinstance(row, Tag):
                continue
            cells = []
            for td in row.find_all(["td", "th"]):
                if not isinstance(td, Tag):
                    continue
                link = td.find("a", href=True)
                if isinstance(link, Tag) and link.has_attr("href"):
                    link = normalize_url(url, str(link["href"]))
                    seen_links.add(link)
                    text = f"{td.get_text(strip=True)} ({link})"
                    result = handle_link(link, text)
                    if result:
                        cells.append(result)
            if cells:
                table_data.append(" | ".join(cells))
        if table_data:
            structured_content.append("\n".join(table_data))

    links = []
    for a in soup.find_all("a", href=True):
        if not isinstance(a, Tag):
            continue
        href = a.get("href")
        if not isinstance(href, str):
            continue
        if href.startswith("mailto:"):
            continue
        link = normalize_url(url, href)
        if (
            not a.find_parent(
                ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "li", "table"]
            )
            and link not in seen_links
        ):
            text = f"- [{a.get_text(strip=True)}]({link})"
            result = handle_link(link, text)
            if result:
                links.append(result)
    if links:
        structured_content.append("\n### Links ###\n" + "\n".join(links))

    return "\n".join(structured_content)[:128000]

def extract_structured_text_chunks(
        soup: BeautifulSoup, url: str, job_offers
    ) -> List[str]:
        """
        Extracts structured text from single-page or 'load more'-style career pages
        and splits it into LLM-friendly chunks for job extraction or analysis.

        Args:
            soup (BeautifulSoup): Parsed HTML content of the career page.
            url (str): Base URL used to resolve relative links.

        Returns:
            List[str]: List of formatted text chunks (~2000 chars each),
            preserving document hierarchy and readability for LLM input.
        """

        structured_content = []
        seen_links = set()
        verified_existing_jobs = [job["job_url"] for job in job_offers]

        MAX_ITEMS_PER_BLOCK = 15

        def get_associated_link(element):
            """Finds the nearest anchor link within or related to the element."""
            link = element.find("a", href=True)
            if link:
                link = normalize_url(url, link["href"])
                seen_links.add(link)
                return link
            return ""

        def handle_link(link: Optional[str], text: str):
            """Decide whether to include in structured_content or verified_existing_jobs."""
            if link in verified_existing_jobs:
                return None
            return text

        # --- Headings (batch individually, each heading is its own block) ---
        headings = []
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            link = get_associated_link(heading)
            text = (
                f"### {heading.get_text(strip=True)}{f' ({link})' if link else ''} ###"
            )
            result = handle_link(link, text)
            if result:
                headings.append(result)
        for i in range(0, len(headings), MAX_ITEMS_PER_BLOCK):
            structured_content.append("\n".join(headings[i : i + MAX_ITEMS_PER_BLOCK]))

        # --- Paragraphs ---
        paragraphs = []
        for paragraph in soup.find_all("p"):
            link = get_associated_link(paragraph)
            text = f"- {paragraph.get_text(strip=True)}{f' ({link})' if link else ''}"
            result = handle_link(link, text)
            if result:
                paragraphs.append(result)
        for i in range(0, len(paragraphs), MAX_ITEMS_PER_BLOCK):
            structured_content.append(
                "\n".join(paragraphs[i : i + MAX_ITEMS_PER_BLOCK])
            )

        # --- Lists (UL/LI) ---
        for ul in soup.find_all("ul"):
            if not isinstance(ul, Tag):
                continue
            items = []
            for li in ul.find_all("li"):
                if not isinstance(li, Tag):
                    continue
                link_el = li.find("a", href=True)
                if isinstance(link_el, Tag) and link_el.has_attr("href"):
                    link = normalize_url(url, str(link_el["href"]))
                    seen_links.add(link)
                    text = f"  • {li.get_text(strip=True)} ({link})"
                    result = handle_link(link, text)
                    if result:
                        items.append(result)
            for i in range(0, len(items), MAX_ITEMS_PER_BLOCK):
                structured_content.append("\n".join(items[i : i + MAX_ITEMS_PER_BLOCK]))

        # --- Tables ---
        table_rows = []
        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue
            for row in table.find_all("tr"):
                if not isinstance(row, Tag):
                    continue
                cells = []
                for td in row.find_all(["td", "th"]):
                    if not isinstance(td, Tag):
                        continue
                    link_el = td.find("a", href=True)
                    if isinstance(link_el, Tag) and link_el.has_attr("href"):
                        link = normalize_url(url, str(link_el["href"]))
                        seen_links.add(link)
                        text = f"{td.get_text(strip=True)} ({link})"
                        result = handle_link(link, text)
                        if result:
                            cells.append(result)
                if cells:
                    table_rows.append(" | ".join(cells))
        for i in range(0, len(table_rows), MAX_ITEMS_PER_BLOCK):
            structured_content.append(
                "\n".join(table_rows[i : i + MAX_ITEMS_PER_BLOCK])
            )

        # --- Orphan links ---
        links = []
        for a in soup.find_all("a", href=True):
            if isinstance(a, Tag):
                href = str(a.get("href"))
                if href.startswith("mailto:"):
                    continue
                link = normalize_url(url, href)
                if (
                    not a.find_parent(
                        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "ul", "li", "table"]
                    )
                    and link not in seen_links
                ):
                    text = f"- [{a.get_text(strip=True)}]({link})"
                    result = handle_link(link, text)
                    if result:
                        links.append(result)
        for i in range(0, len(links), MAX_ITEMS_PER_BLOCK):
            link_block = links[i : i + MAX_ITEMS_PER_BLOCK]
            structured_content.append("\n### Links ###\n" + "\n".join(link_block))

        # --- Chunking by character length (still applied globally) ---
        chunks = []
        current_chunk: list[str] = []
        current_len = 0
        MAX_CHUNK_SIZE = 2000

        for block in structured_content:
            block_len = len(block) + 1
            if current_len + block_len > MAX_CHUNK_SIZE and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [block]
                current_len = block_len
            else:
                current_chunk.append(block)
                current_len += block_len

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

def hash_page_content(text_content: str) -> str:
    """Creates a hash of the page content to detect duplicates."""
    return hashlib.md5(text_content.encode()).hexdigest()

def extract_visible_text(html: str) -> str:
    
    soup = BeautifulSoup(html, "html.parser")
    
    for script in soup(["script", "style", "meta", "noscript", "svg"]):
    
        script.decompose()
    
    return soup.get_text(separator=" ")
