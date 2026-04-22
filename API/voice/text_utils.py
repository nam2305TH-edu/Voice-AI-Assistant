
from collections import Counter


def is_valid_text(text: str) -> bool:
    """Lọc bỏ hallucination của Whisper"""
    if not text or len(text.strip()) < 2:
        return False
    
    cleaned = text.strip()
    special_chars = set('!?.,-;:\'"()[]{}*#@&%$^~`|\\/<>=')
    if all(c in special_chars or c.isspace() for c in cleaned):
        return False
    
    if len(cleaned) > 3:
        char_counts = Counter(cleaned.replace(' ', ''))
        if char_counts:
            most_common_char, count = char_counts.most_common(1)[0]
            if count / len(cleaned.replace(' ', '')) > 0.5:
                return False
    
    return True
