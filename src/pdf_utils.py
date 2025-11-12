# -*- coding: utf-8 -*-
"""
Генерація PDF з Markdown (PDF-only).
(v3.2 - Взято у товариша)
Черга спроб:
  A) pdfkit + wkhtmltopdf (рекомендовано; шлях можна задати через env WKHTMLTOPDF_CMD)
  B) xhtml2pdf (pisa) — працює без зовнішніх бінарників (CSS дещо скромніший)

Якщо жоден варіант недоступний — піднімається виняток із чіткою інструкцією, що встановити.
"""

import logging
import os
from typing import Optional

import markdown2

logger = logging.getLogger("pdf_utils")
logger.setLevel(logging.INFO)

# --- Ліниві імпорти, щоб не падати, якщо пакетів немає ---
def _try_import_pdfkit():
    try:
        import pdfkit  # type: ignore
        return pdfkit
    except Exception:
        return None

def _try_import_xhtml2pdf():
    try:
        from xhtml2pdf import pisa  # type: ignore
        return pisa
    except Exception:
        return None

# --- Стилі, наближені до нашої v2.8 (чисті шрифти, охайні таблиці) ---
PDF_CSS_STYLE = """
<style>
    @page { size: A4; margin: 20mm 17mm 22mm 17mm; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif,
                     "Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol";
        font-size: 11pt;
        line-height: 1.5;
        color: #333;
    }
    h1, h2, h3, h4 {
        font-family: "Georgia", serif;
        color: #111;
        font-weight: 600;
        margin-top: 25px;
        margin-bottom: 10px;
    }
    h1 { font-size: 24pt; border-bottom: 2px solid #eee; padding-bottom: 5px; }
    h2 { font-size: 18pt; }
    h3 { font-size: 14pt; border-bottom: 1px solid #eee; padding-bottom: 3px; }
    code, pre {
        font-family: "Menlo", "Consolas", monospace;
        background-color: #f5f5f5;
        border-radius: 4px;
        padding: 2px 4px;
        font-size: 90%;
    }
    pre { padding: 10px 15px; overflow-x: auto; }
    table {
        width: 100%;
        border-collapse: collapse;
        margin-bottom: 15px;
        border-spacing: 0;
    }
    th, td {
        border: 1px solid #ddd;
        padding: 10px;
        text-align: left;
        vertical-align: top;
    }
    th { background-color: #f9f9f9; font-weight: bold; }
    /* Стиль для першої колонки (Питання) в DPIA */
    table td:first-child { 
        font-weight: bold; 
        background-color: #fdfdfd; 
        width: 30%; 
    }
    blockquote { border-left: 4px solid #eee; padding-left: 15px; color: #555; font-style: italic; }
    /* Спеціально для xhtml2pdf, щоб <br> працював у таблицях */
    br { display: block; content: ""; margin-bottom: 0.5em; } 
</style>
"""

def _md_to_html(md_content: str) -> str:
    """Конвертує Markdown (з нашими шаблонами v2.8) в HTML."""
    html_body = markdown2.markdown(
        md_content,
        extras=["tables", "fenced-code-blocks", "strike", "cuddled-lists", "break-on-newline"]
    )
    return f"<html><head><meta charset='UTF-8'>{PDF_CSS_STYLE}</head><body>{html_body}</body></html>"

def _generate_with_pdfkit(html_full: str, output_filename: str) -> bool:
    """Спроба 1: Генерація через pdfkit (wkhtmltopdf)."""
    pdfkit = _try_import_pdfkit()
    if not pdfkit:
        logger.warning("Бібліотека 'pdfkit' не встановлена. Пропускаю...")
        return False

    try:
        # Шукаємо wkhtmltopdf
        wkhtmltopdf_path_env = os.getenv("WKHTMLTOPDF_CMD")
        config = None
        if wkhtmltopdf_path_env and os.path.exists(wkhtmltopdf_path_env):
            logger.info(f"Використовую wkhtmltopdf з WKHTMLTOPDF_CMD: {wkhtmltopdf_path_env}")
            config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path_env)
        
        options = {
            'encoding': "UTF-8",
            'page-size': 'A4',
            'margin-top': '20mm',
            'margin-bottom': '22mm',
            'margin-left': '17mm',
            'margin-right': '17mm',
            'quiet': ''
        }
        
        pdfkit.from_string(html_full, output_filename, options=options, configuration=config)
        return True
    
    except IOError as e:
        if "No wkhtmltopdf executable found" in str(e):
            logger.warning("wkhtmltopdf не знайдено у PATH. Спроба 2: xhtml2pdf...")
        else:
            logger.error(f"pdfkit впав з помилкою вводу-виводу: {e}")
        return False
    except Exception as e:
        logger.error(f"pdfkit впав з невідомою помилкою: {e}")
        return False

def _generate_with_xhtml2pdf(html_full: str, output_filename: str) -> bool:
    """Спроба 2: Генерація через xhtml2pdf (чистий Python)."""
    pisa = _try_import_xhtml2pdf()
    if not pisa:
        logger.warning("Бібліотека 'xhtml2pdf' не встановлена. Пропускаю...")
        return False
    
    try:
        with open(output_filename, "w+b") as result_file:
            # Конвертуємо HTML в PDF
            pisa_status = pisa.CreatePDF(
                html_full,                # HTML-вміст
                dest=result_file,         # Файл
                encoding='utf-8'
            )
        
        if not pisa_status.err:
            logger.info("PDF успішно створено через xhtml2pdf.")
            return True
        else:
            logger.error(f"xhtml2pdf впав з помилкою: {pisa_status.err}")
            return False
            
    except Exception as e:
        logger.warning(f"xhtml2pdf впав: {e}")
        return False

def create_pdf_from_markdown(content: str, is_html: bool, output_filename: str) -> str:
    """
    (ОНОВЛЕНО v2.9)
    Генерує *PDF-файл* з Markdown.
    Повертає шлях до PDF (output_filename). Якщо PDF створити не вийшло — піднімає виняток з інструкцією.
    """
    logger.info(f"Старт генерації PDF (v2.9 Гібрид): {output_filename}")
    # is_html ігнорується, ми завжди передаємо Markdown з v2.8
    html_full = _md_to_html(content)

    # A) wkhtmltopdf (краща якість)
    if _generate_with_pdfkit(html_full, output_filename):
        logger.info(f"PDF створено через wkhtmltopdf: {output_filename}")
        return output_filename

    # B) xhtml2pdf (без зовнішніх бінарників)
    if _generate_with_xhtml2pdf(html_full, output_filename):
        logger.info(f"PDF створено через xhtml2pdf: {output_filename}")
        return output_filename

    # Обидва варіанти недоступні → пояснюємо, що встановити
    raise Exception(
        "Не вдалося створити PDF.\n\n"
        "**Варіант A (рекомендовано):** Встановіть `wkhtmltopdf` у вашій системі (напр., `sudo apt install wkhtmltopdf`).\n"
        "**Варіант B (запасний):** Встановіть `xhtml2pdf` (`pip install xhtml2pdf`)."
    )

def clear_temp_file(filepath: str):
    """Видаляє тимчасовий PDF-файл після надсилання."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Тимчасовий файл видалено: {filepath}")
        else:
            logger.warning(f"TІMЧАСОВИЙ ФАЙЛ НЕ ЗНАЙДЕНО для видалення: {filepath}")
    except Exception as e:
        logger.error(f"Помилка під час видалення тимчасового файлу {filepath}: {e}")