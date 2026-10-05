"""Tamaño de imágenes PNG/JPEG leyendo sólo la cabecera (sin dependencias externas)."""

from __future__ import annotations

import struct
from pathlib import Path


def image_info(path: Path) -> tuple[str, int, int] | None:
    """Devuelve (formato, ancho, alto) o None si no es PNG/JPEG legible."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return "png", w, h
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            # SOF0..SOF15 salvo DHT (C4), JPG (C8) y DAC (CC)
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpg", w, h
            i += 2 + length
    return None


def png_has_alpha(path: Path) -> bool:
    """True si el PNG tiene canal alfa (tipo de color 4/6) o transparencia tRNS."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 26:
        return False
    if data[25] in (4, 6):
        return True
    return b"tRNS" in data[:4096]
