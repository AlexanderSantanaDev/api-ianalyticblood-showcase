import cv2
import logging

logger = logging.getLogger("app.image_preproc")

# Límite de resolución máxima antes del upscale.
# Render Free Tier tiene 512MB RAM. Una foto iPhone 12MP expandida y
# escalada al doble supera los 400MB y causa OOM.
# Limitamos el lado más largo a MAX_SIDE px antes de procesar.
# Para OCR de texto en informes de sangre, 1500px es más que suficiente.
MAX_SIDE = 1500

def enhance_for_ocr(img_bgr):
    """
    Recibe una imagen BGR (NumPy) y la deja lista para OCR:
    · Redimensiona si supera MAX_SIDE para proteger memoria en Render Free
    · re‑escala al doble (solo si la imagen no es demasiado grande)
    · denoising a color (fastNlMeansDenoisingColored)
    Devuelve la imagen mejorada.
    """
    h, w = img_bgr.shape[:2]
    longest = max(h, w)

    # Downscale preventivo si la imagen supera el límite seguro.
    # Esto evita el OOM en Render (512MB) con fotos de iPhone/Android de alta resolución.
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        new_w = int(w * scale)
        new_h = int(h * scale)
        logger.info(
            f"[image_preproc] Imagen reducida de {w}x{h} → {new_w}x{new_h} "
            f"(ratio: {scale:.2f}) para proteger memoria en producción."
        )
        img_bgr = cv2.resize(img_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        h, w = new_h, new_w

    # Solo hacemos upscale x2 si la imagen resultante
    # no va a superar los 1000px en su lado más largo (imágenes pequeñas de análisis).
    # Imágenes ya grandes no se escalan — la resolución es suficiente para OCR.
    if max(h, w) < 800:
        upscaled = cv2.resize(img_bgr, None, fx=2.0, fy=2.0,
                              interpolation=cv2.INTER_CUBIC)
    else:
        upscaled = img_bgr  # ya tiene suficiente resolución

    denoised = cv2.fastNlMeansDenoisingColored(
        upscaled, None,
        h=10, hColor=10,
        templateWindowSize=7,
        searchWindowSize=21
    )
    return denoised

