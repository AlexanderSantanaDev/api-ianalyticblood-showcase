import logging, cv2, numpy as np, pdfplumber, pytesseract
from pdf2image import convert_from_path
from app.services.image_preproc import enhance_for_ocr   

logger = logging.getLogger("app.pdf_service")

CUSTOM_TESS_CONFIG = r"--oem 3 --psm 6 -c preserve_interword_spaces=1"

def _ocr_page(pil_img) -> str:
    """
    Recibe una página PIL, la convierte a BGR, le aplica
    upscale + denoising y extrae texto con Tesseract.
    """
    cv_img   = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    cv_clean = enhance_for_ocr(cv_img)                    
    return pytesseract.image_to_string(
        cv_clean,
        lang="spa+eng",
        config=CUSTOM_TESS_CONFIG
    )

def extract_text_from_pdf(pdf_path: str) -> str:
    """
    1. Extrae texto “nativo” con pdfplumber.
    2. Si no hay texto, convierte las páginas a imagen y aplica OCR mejorado.
    """
    #logger.info(f"Iniciando extracción de texto del PDF: {pdf_path}")

    # Intento rápido con texto embebido
    with pdfplumber.open(pdf_path) as pdf:
        text = "".join(p.extract_text() or "" for p in pdf.pages)

    if text.strip():
        logger.info("Texto PDF nativo encontrado ✔️")
        return text

    # Fallback OCR para PDFs escaneados
    #logger.info("PDF parece escaneado, activando OCR…")
    pages    = convert_from_path(pdf_path, dpi=300)      
    ocr_text = "\n".join(_ocr_page(p) for p in pages)

    #logger.info(ocr_text)
    logger.info("OCR del PDF completado")
    return ocr_text
