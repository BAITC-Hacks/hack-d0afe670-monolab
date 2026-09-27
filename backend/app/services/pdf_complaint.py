from __future__ import annotations

import base64
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_FONT_NAME = "TalapCyrillic"


def _register_font() -> str:
    if _FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return _FONT_NAME
    candidates = [
        Path(__file__).resolve().parents[1] / "assets" / "DejaVuSans.ttf",
    ]
    from app.config import PDF_FONT_PATH

    if PDF_FONT_PATH:
        candidates.insert(0, Path(PDF_FONT_PATH))
    candidates.extend(
        [
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/Library/Fonts/Arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
    )
    for path in candidates:
        if path.is_file():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(path)))
            return _FONT_NAME
    return "Helvetica"


def _decode_photo(data: str) -> Optional[Image.Image]:
    raw = data.strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        img_bytes = base64.b64decode(raw, validate=False)
        return Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        return None


def _wrap_lines(text: str, max_chars: int = 92) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


def build_complaint_pdf(
    *,
    subject: str,
    document_body: str,
    address: str,
    lat: float,
    lng: float,
    photo_base64: Optional[str] = None,
) -> bytes:
    font = _register_font()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 18 * mm
    y = height - margin

    c.setFont(font, 14)
    c.drawString(margin, y, "Talap — Заявление в e-Otinish")
    y -= 8 * mm

    c.setFont(font, 10)
    c.drawString(margin, y, f"Тема: {subject[:120]}")
    y -= 6 * mm
    c.drawString(margin, y, f"Адрес: {address[:120]}")
    y -= 5 * mm
    c.drawString(margin, y, f"GPS: {lat:.6f}, {lng:.6f}")
    y -= 5 * mm
    c.drawString(
        margin,
        y,
        f"Сформировано: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')}",
    )
    y -= 10 * mm

    if photo_base64:
        img = _decode_photo(photo_base64)
        if img is not None:
            max_w = width - 2 * margin
            max_h = 70 * mm
            img.thumbnail((int(max_w), int(max_h)), Image.Resampling.LANCZOS)
            img_buf = io.BytesIO()
            img.save(img_buf, format="JPEG", quality=85)
            img_buf.seek(0)
            from reportlab.lib.utils import ImageReader

            c.drawImage(
                ImageReader(img_buf),
                margin,
                y - img.height,
                width=img.width,
                height=img.height,
                preserveAspectRatio=True,
            )
            y -= img.height + 8 * mm
            c.setFont(font, 9)
            c.drawString(margin, y, "Приложение: фотофиксация дефекта с GPS-меткой.")
            y -= 8 * mm

    c.setFont(font, 10)
    for line in _wrap_lines(document_body):
        if y < margin + 10 * mm:
            c.showPage()
            y = height - margin
            c.setFont(font, 10)
        if not line:
            y -= 4 * mm
            continue
        c.drawString(margin, y, line)
        y -= 4.5 * mm

    c.save()
    return buffer.getvalue()


def pdf_to_base64(pdf_bytes: bytes) -> str:
    return base64.b64encode(pdf_bytes).decode("ascii")
