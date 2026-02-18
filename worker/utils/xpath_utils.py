from bs4 import BeautifulSoup
from typing import Iterable
from typing import Optional
from lxml import html

def find_first_existing_xpath(
    soup: BeautifulSoup,
    xpath_candidates: Iterable[str],
) -> Optional[str]:
    """
    Given a BeautifulSoup document and candidate XPaths,
    return the first XPath that resolves to at least one element.
    """
    dom = html.fromstring(str(soup))

    for xpath in xpath_candidates:
        try:
            matches = dom.xpath(xpath)
            if matches:
                return xpath
        except Exception:
            continue

    return None