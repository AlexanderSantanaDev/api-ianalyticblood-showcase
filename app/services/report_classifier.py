import re

# Lista de términos frecuentes en un informe de sangre
KEYWORDS = [
    "hemograma", "hematíes", "hemoglobina", "hematocrito",
    "leucocitos", "glucosa", "colesterol", "triglicéridos",
    "tsh", "gpt", "ast", "gtt", "plaquetas"
]

def is_blood_report(text: str, threshold: int = 3) -> bool:
    """
    Comprueba si en `text` aparecen al menos `threshold` keywords
    relacionadas con análisis de sangre.
    """
    text_low = text.lower()
    matches = sum(1 for kw in KEYWORDS if re.search(r"\b" + re.escape(kw) + r"\b", text_low))
    return matches >= threshold