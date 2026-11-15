"""Impresión de UNA entrada por operación, orientada a impresoras térmicas ZYWELL.

El trabajo RAW se dirige a ESC/POS mediante la cola de impresión de Windows.
El PDF es una alternativa compatible con controladores no ESC/POS, con tamaño de página 58/80 mm.
Las imágenes son opcionales y se imprimen en escala de grises.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import io
import math

from PIL import Image, ImageDraw, ImageFont, ImageOps
import qrcode
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm

PRINTABLE_DOTS = {58: 384, 80: 576}
PAPER_MARGIN_MM = {58: 5, 80: 4}


def font(size: int, bold: bool = False):
    windows = Path('C:/Windows/Fonts')
    paths = ([windows/'arialbd.ttf', windows/'segoeuib.ttf',
              Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
             if bold else [windows/'arial.ttf', windows/'segoeui.ttf',
                           Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')])
    for path in paths:
        try:
            if path.exists():
                return ImageFont.truetype(str(path), size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def _fit_text(text: str, draw: ImageDraw.ImageDraw, max_width: int, size: int, bold: bool = False, min_size: int = 11):
    while size > min_size and draw.textbbox((0, 0), text, font=font(size, bold))[2] > max_width:
        size -= 1
    return font(size, bold)


def _lines(draw: ImageDraw.ImageDraw, text: str, fnt, max_width: int):
    result = []
    for paragraph in str(text).split('\n'):
        words = paragraph.split()
        if not words:
            result.append('')
            continue
        line = words[0]
        for word in words[1:]:
            next_line = f'{line} {word}'
            if draw.textbbox((0, 0), next_line, font=fnt)[2] <= max_width:
                line = next_line
            else:
                result.append(line)
                line = word
        result.append(line)
    return result


def _open_image(path: str | None):
    if not path:
        return None
    try:
        with Image.open(path) as source:
            source.verify()
        with Image.open(path) as source:
            return ImageOps.exif_transpose(source).convert('RGB')
    except (OSError, ValueError):
        return None


def render_ticket(event: dict, ticket: dict, width_mm: int = 80, design: dict | None = None) -> Image.Image:
    """Construye una imagen en píxeles exactos de la zona imprimible del rollo."""
    if width_mm not in PRINTABLE_DOTS:
        raise ValueError('Ancho de rollo: 58 u 80 mm.')
    design = design or {}
    w = PRINTABLE_DOTS[width_mm]
    pad = 14 if width_mm == 58 else 20
    text_w = w - 2 * pad
    im = Image.new('RGB', (w, 3900), 'white')
    draw = ImageDraw.Draw(im)
    y = 24

    def centered(text, size=20, bold=False, space=7):
        nonlocal y
        f = font(size, bold)
        for line in _lines(draw, text, f, text_w):
            fw = draw.textbbox((0, 0), line, font=f)[2]
            draw.text((max(0, (w - fw)//2), y), line, fill='black', font=f)
            y += int(size*1.35) if f != ImageFont.load_default() else max(16, size)
        y += space

    def divider():
        nonlocal y
        draw.line((pad, y, w-pad, y), fill='black', width=2)
        y += 13

    logo_items = [_open_image(design.get('logo_ayto')), _open_image(design.get('logo_centro'))]
    logos = [p for p in logo_items if p is not None]
    if logos:
        h = 85 if width_mm == 80 else 66
        region = w // max(1, len(logos))
        for index, logo in enumerate(logos):
            logo.thumbnail((region - 28, h), Image.Resampling.LANCZOS)
            x = index*region + (region-logo.width)//2
            im.paste(logo, (x, y+(h-logo.height)//2))
        y += h+11

    centered(design.get('cabecera') or 'ESCUELA MUNICIPAL DE MÚSICA Y DANZA',
             size=22 if width_mm == 80 else 18, bold=True, space=5)
    centered(design.get('subtitulo') or 'Arroyo de la Miel', size=17 if width_mm == 80 else 15)
    divider()
    centered(str(event['name']), size=27 if width_mm == 80 else 22, bold=True)

    poster = _open_image(design.get('poster'))
    if poster:
        boxw = min(text_w, 410 if width_mm == 80 else 284)
        boxh = 270 if width_mm == 80 else 220
        poster.thumbnail((boxw, boxh), Image.Resampling.LANCZOS)
        im.paste(poster, ((w-poster.width)//2, y))
        y += poster.height + 16

    date = datetime.fromisoformat(str(event['start_time']))
    centered(date.strftime('%d/%m/%Y'), size=26 if width_mm == 80 else 23, bold=True)
    centered(date.strftime('%H:%M H'), size=30 if width_mm == 80 else 25, bold=True)
    centered(design.get('lugar') or 'Casa de la Cultura - Arroyo de la Miel',
             size=19 if width_mm == 80 else 16, bold=True, space=14)
    divider()
    centered(f"ENTRADA N.º {int(ticket['number']):04d}", size=26 if width_mm == 80 else 22, bold=True)
    if ticket.get('seat_label'):
        centered(ticket['seat_label'], size=19 if width_mm == 80 else 16, bold=True)
    else:
        centered('ENTRADA LIBRE - SIN BUTACA ASIGNADA', size=16 if width_mm == 80 else 13, bold=True)
    centered('1 PERSONA - PROHIBIDA SU VENTA', size=16 if width_mm == 80 else 13)
    divider()
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=5 if width_mm == 80 else 4, border=4)
    qr.add_data(ticket['qr'])
    qr.make(fit=True)
    qr_image = qr.make_image(fill_color='black', back_color='white').convert('RGB')
    # QR nunca se reduce con antialias: el contraste y los módulos deben mantenerse nítidos.
    if qr_image.width > text_w:
        raise ValueError('QR demasiado grande para el rollo elegido.')
    im.paste(qr_image, ((w - qr_image.width)//2, y))
    y += qr_image.height + 10
    centered('PRESENTAR ESTE QR EN EL ACCESO', size=16 if width_mm == 80 else 13, bold=True, space=14)
    divider()
    notices = [
        'Se recomienda máxima puntualidad.',
        'Una vez comenzado el espectáculo, no se garantiza el acceso al asiento.',
    ]
    if event['mode'] == 'libre':
        notices += ['No se pueden reservar asientos.',
                    'Orden de acceso por llegada a la fila exterior.']
    else:
        notices += ['Debe ocupar la fila y butaca asignadas.']
    notices += ['Conserve esta entrada hasta finalizar la función.']
    fsmall = font(14 if width_mm == 80 else 12)
    for notice in notices:
        for line in _lines(draw, notice, fsmall, text_w):
            draw.text((pad, y), line, fill='black', font=fsmall)
            y += 22 if width_mm == 80 else 19
        y += 5
    y += 21
    if y > im.height:
        raise ValueError('Entrada demasiado larga para el ticket.')
    return im.crop((0, 0, w, y))


def export_single_pdf(event: dict, ticket: dict, path: Path, width_mm: int = 80,
                      design: dict | None = None) -> Path:
    im = render_ticket(event, ticket, width_mm, design)
    # 8 puntos por mm (203 dpi aprox.), más márgenes definidos del rollo.
    left = PAPER_MARGIN_MM[width_mm]
    height_mm = math.ceil(im.height / 8) + 7
    pdf = Canvas(str(path), pagesize=(width_mm*mm, height_mm*mm))
    pdf.setTitle(f"Entrada {int(ticket['number']):04d} - {event['name']}")
    pdf.drawImage(ImageReader(im), left*mm, 4*mm,
                  width=(im.width/8)*mm, height=(im.height/8)*mm)
    pdf.save()
    return path


def list_windows_printers() -> list[str]:
    try:
        import win32print
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        return sorted(set(p[2] for p in printers))
    except ImportError:
        return []


def _escpos_bytes(im: Image.Image, cut: bool = False) -> bytes:
    """ESC/POS GS v 0: imagen monocroma raster, sin reescalar el código QR."""
    mono = im.convert('L').convert('1', dither=Image.Dither.FLOYDSTEINBERG)
    w, h = mono.size
    if w % 8:
        raise ValueError('El ancho de impresión debe ser múltiplo de 8 píxeles.')
    stride = w // 8
    if h > 65535 or stride > 65535:
        raise ValueError('Tamaño de ticket no compatible con ESC/POS.')
    data = mono.tobytes()  # Pillow modo 1: bit 1 = blanco. ESC/POS 1 = negro.
    data = bytes(b ^ 255 for b in data)
    command = b'\x1b\x40'  # initialize
    command += b'\x1b\x61\x01'  # center
    command += b'\x1d\x76\x30\x00' + bytes([stride & 255, stride >> 8, h & 255, h >> 8])
    command += data + b'\n\n\n'
    if cut:
        command += b'\x1d\x56\x42\x00'  # GS V partial cut, subject to model capabilities
    return command


def print_windows_escpos(event: dict, ticket: dict, printer_name: str,
                         width_mm: int = 80, design: dict | None = None,
                         cut: bool = False):
    """Envía UNA sola entrada a la cola RAW seleccionada. Solo para modelos ESC/POS."""
    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError('Falta el módulo de impresión de Windows (pywin32).') from exc
    if not printer_name or printer_name not in list_windows_printers():
        raise ValueError('Selecciona una impresora instalada en Windows.')
    raw = _escpos_bytes(render_ticket(event, ticket, width_mm, design), cut=cut)
    handle = win32print.OpenPrinter(printer_name)
    job_id = None
    try:
        job_id = win32print.StartDocPrinter(handle, 1, (f'Entrada {ticket["number"]}', None, 'RAW'))
        try:
            win32print.StartPagePrinter(handle)
            try:
                written = win32print.WritePrinter(handle, raw)
                if written != len(raw):
                    raise OSError('La impresora no recibió el ticket completo.')
            finally:
                win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)
    return job_id
