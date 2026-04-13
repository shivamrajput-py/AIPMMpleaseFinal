from bs4 import BeautifulSoup
from graph.state import ChangeRecord
from typing import List

def generate_change_summary(original_html: str, enhanced_html: str) -> List[ChangeRecord]:
    """
    Roughly compares elements to surface what was changed. Used for the UI display.
    """
    try:
        orig = BeautifulSoup(original_html, "lxml")
        enh = BeautifulSoup(enhanced_html, "lxml")

        changes = []
        
        orig_h1 = orig.find("h1")
        enh_h1 = enh.find("h1")

        if orig_h1 and enh_h1 and orig_h1.get_text() != enh_h1.get_text():
            changes.append(ChangeRecord(
                element="h1 Headline",
                original=orig_h1.get_text().strip(),
                updated=enh_h1.get_text().strip()
            ))

        # Ad banner addition
        banner = enh.find("div", class_="ad-personalizer-banner")
        if banner:
            changes.append(ChangeRecord(
                element="Offer Banner",
                original=None,
                updated=banner.get_text().strip()
            ))

        # Can be expanded for buttons, paragraphs, etc.
        return changes
    except Exception:
        return []
