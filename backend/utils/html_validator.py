import re
from bs4 import BeautifulSoup

def sanitize_for_iframe(html_str: str) -> str:
    """
    Strips executable scripts and inline event handlers to ensure safe preview.
    """
    soup = BeautifulSoup(html_str, "lxml")
    
    # Remove script tags
    for script in soup.find_all("script"):
        script.decompose()

    # Remove inline event handlers (onclick, onhover, etc.)
    for tag in soup.find_all(True):
        attrs = list(tag.attrs.keys())
        for attr in attrs:
            if attr.startswith("on"):
                del tag[attr]
            if attr == "href" and tag["href"].strip().lower().startswith("javascript:"):
                tag["href"] = "#"

    # Remove iframe blockers like x-frame-options meta tags
    for meta in soup.find_all("meta"):
        if meta.get("http-equiv") and meta["http-equiv"].lower() in ["x-frame-options", "content-security-policy"]:
            meta.decompose()

    return str(soup)
