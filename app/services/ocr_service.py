# Lógica de OCR       
import cv2
import numpy as np
import pytesseract
from PIL import Image
from app.services.image_preproc import enhance_for_ocr
import logging

logger = logging.getLogger("app.ocr_service")

def preprocess_image_color(image_path: str):
    """
    1) Carga la imagen a color (BGR en OpenCV).
    2) La reescalamos para aumentar su tamaño.
    3) Aplicamos denoising a color con fastNlMeansDenoisingColored para reducir ruido.
    4) Guardamos una versión para debug, y devolvemos la imagen lista para el OCR.
    """
    img_color = cv2.imread(image_path)
    
    if img_color is None:
        raise ValueError(f"No se pudo cargar la imagen: {image_path}")

    # Redimensionar la imagen (por ejemplo, al doble de tamaño)
    #upscaled = cv2.resize(img_color, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    
    # Denoising a color (reducir ruido cromático)
    # h / hColor controlan cuánto “filtra” el luminance y el color. Ajustar si hace falta.
    #denoised = cv2.fastNlMeansDenoisingColored(upscaled, None, h=10, hColor=10, templateWindowSize=7, searchWindowSize=21)
    
    
    #return denoised
    return enhance_for_ocr(img_color) 

def extract_text_from_image(image_path: str) -> str:
    """
    Extrae texto usando OCR sin convertir manualmente a escala de grises.
    Pasamos la imagen en color tal cual (pero con denoising).
    """
    logger.info(f"Iniciando extracción de texto de la imagen: {image_path}")
    try:
        # Preprocesar la imagen a color
        processed_color_img = preprocess_image_color(image_path)
        
        # Configuración para Tesseract
        # - --oem 3: usa el motor LSTM
        # - --psm 6: bloque uniforme de texto
        # - tessedit_char_whitelist=...: (opcional) si se quiere restringir caracteres
        custom_config = r"--oem 3 --psm 6 -c preserve_interword_spaces=1"
        
        # ¡Ojo! Tesseract recibirá un array NumPy en BGR a color, lo convertirá internamente.
        text = pytesseract.image_to_string(
            processed_color_img,
            config=custom_config,
            lang="spa+eng"
        )
        
        logger.info("Extracción de OCR completada.")
        # 🛡️Eliminado logger.info del texto completo extraído — era PHI/PII en logs de producción
        # Antes: logger.info(f"Texto extraído:\n{text}") → exponía datos médicos del paciente
        return text
    except Exception as e:
        logger.error(f"Error durante la extracción OCR: {e}")
        raise e
