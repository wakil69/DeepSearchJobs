import re 

from urllib.parse import urlparse, urlunparse, urljoin
from typing import List, Optional

def same_domain(url1: str, url2: str):
    """Compare two URLs ignoring www and case."""
    n1 = urlparse(url1).netloc.lower().replace("www.", "")
    n2 = urlparse(url2).netloc.lower().replace("www.", "")
    return n1 == n2

def deduplicate_by_base_url(urls: List[str]) -> List[str]:
    """
    Deduplicate URLs by their base (path + domain), ignoring query strings and fragments.

    This ensures that URLs like:
        https://example.com/jobs?page=1
        https://example.com/jobs?page=2
    are treated as the same base and only the shortest version is kept:
        https://example.com/jobs

    Args:
        urls (List[str]): List of absolute URLs (may include queries/fragments)

    Returns:
        List[str]: Deduplicated URLs with clean, minimal base paths.
    """
    seen: dict[str, str] = {}
    for url in urls:
        parsed = urlparse(url)
        # --- Build a normalized base URL (remove query + fragment)
        base_url = urlunparse(parsed._replace(query="", fragment="")).rstrip("/")

        # --- If we've seen this base before, keep the shortest version
        if base_url not in seen or len(url) < len(seen[base_url]):
            seen[base_url] = url
    return list(seen.values())

def keep_only_roots(urls: set[str]) -> set[str]:
    """
    Keep only the shortest, root-level URLs per domain.

    Removes deeper duplicates so only the highest-level "root" URL
    for each domain remains. Useful to avoid redundant crawling
    (e.g., pagination or nested job pages).

    Example:
        Input:
            [
                "https://partner.com/jobs",
                "https://partner.com/jobs/page/2",
                "https://partner.com/jobs/details/123",
                "https://another.com/careers",
                "https://another.com/careers/openings"
            ]
        Output:
            [
                "https://partner.com/jobs",
                "https://another.com/careers"
            ]

    Args:
        urls (List[str]): List of full URLs.

    Returns:
        List[str]: Deduplicated root-level URLs.
    """
    cleaned = []
    for url in urls:
        parsed = urlparse(url)
        normalized = urlunparse(parsed._replace(query="", fragment="")).rstrip("/")
        if not normalized:  # Guard for empty or invalid URLs
            continue
        cleaned.append(normalized)

    # --- Deduplicate and sort by domain + path length
    cleaned = sorted(
        set(cleaned), key=lambda u: (urlparse(u).netloc, len(urlparse(u).path))
    )

    # --- Keep only the shortest (root) URL per domain
    roots: set[str] = set()
    for url in cleaned:
        parsed = urlparse(url)
        # Check if already covered by an existing root
        if not any(
            parsed.netloc == urlparse(root).netloc and url.startswith(root + "/")
            for root in roots
        ):
            roots.add(url)

    return roots

def normalize_url(base: str, href: str, keep_query=False) -> Optional[str]:
    """Safely join href with base, correctly handling ../, mailto:, tel:, etc."""

    if not href:
        return None

    href = href.strip()
    if not href:
        return None

    if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return href

    parsed = urlparse(base)
    path = parsed.path or "/"

    if not path.endswith("/") and "." not in path.split("/")[-1]:
        path += "/"

    clean_base = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    if href.startswith("//"):
        href = parsed.scheme + ":" + href

    href = re.sub(r"^(\./|//)+", "", href)

    # for single page app like google jobs careers
    # Example: base='/jobs/results/' + href='jobs/results/123' → remove the repeated 'jobs/results'
    base_parts = [p for p in path.strip("/").split("/") if p]
    href_parts = [p for p in href.strip("/").split("/") if p]

    for i in range(len(base_parts)):
        subpath = "/".join(base_parts[i:])
        if href.startswith(subpath + "/") or href == subpath:
            href = href[len(subpath) :].lstrip("/")
            break

    result = urljoin(clean_base, href)

    if keep_query and parsed.query and result:
        if "?" in result:
            result += "&" + parsed.query
        else:
            result += "?" + parsed.query

    if result and result != "/":
        result = result.rstrip("/")

    return result

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