"""Control de Entradas 0.4: entradas HORIZONTALES en rollo termico de 58/80 mm.

El ticket terminado se lee en horizontal. En la ZYWELL se transmite girado 90º:
la anchura fisica de papel es 58/80 mm, y el largo avanza hasta el corte.
La vista previa y el PDF muestran la misma entrada en horizontal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import io
import math

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps
import qrcode
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.units import mm

PRINTABLE_DOTS = {58: 384, 80: 576}
LANDSCAPE_SIZE = {58: (720, 384), 80: (1080, 576)}


def font(size: int, bold: bool = False):
    windows = Path('C:/Windows/Fonts')
    paths = ([windows/'arialbd.ttf', windows/'segoeuib.ttf',
              Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf')]
             if bold else [windows/'arial.ttf', windows/'segoeui.ttf',
                           Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')])
    for path in paths:
        try:
            if path.exists():
                return ImageFont.truetype(str(path), size=max(8, int(size)))
        except OSError:
            pass
    return ImageFont.load_default()


def _open_image(path: str | None):
    if not path:
        return None
    try:
        with Image.open(path) as src:
            return ImageOps.exif_transpose(src).convert('RGB')
    except (OSError, ValueError):
        return None


def _cover(im: Image.Image, source: Image.Image, rect, *, fit='cover'):
    x0, y0, x1, y1 = tuple(map(int, rect))
    box = (x1-x0, y1-y0)
    if min(box) < 1:
        return
    if fit == 'contain':
        copy = ImageOps.contain(source, box, method=Image.Resampling.LANCZOS)
        im.paste(copy, (x0+(box[0]-copy.width)//2, y0+(box[1]-copy.height)//2))
    else:
        copy = ImageOps.fit(source, box, method=Image.Resampling.LANCZOS)
        copy = ImageEnhance.Contrast(copy.convert('L')).enhance(1.15).convert('RGB')
        im.paste(copy, (x0, y0))


def _center(draw, text: str, rect, size: int, *, bold=False, lines=1, min_size=11, fill='black'):
    """Centrado con ajuste real a la caja; nunca trunca nombres por el lateral."""
    x0, y0, x1, y1 = rect
    text = ' '.join(str(text).strip().split())
    if not text:
        return
    max_w, max_h = x1-x0, y1-y0
    for pts in range(max(min_size, int(size)), min_size-1, -1):
        f = font(pts, bold)
        words = text.split()
        split = []
        line = ''
        for word in words:
            candidate = (line+' '+word).strip()
            if not line or draw.textbbox((0, 0), candidate, font=f)[2] <= max_w:
                line = candidate
            else:
                split.append(line)
                line = word
        if line:
            split.append(line)
        step = int(pts*1.29)
        if len(split) <= lines and len(split)*step <= max_h and all(draw.textbbox((0, 0), t, font=f)[2] <= max_w for t in split):
            y = y0 + max(0, (max_h-len(split)*step)//2)
            for line in split:
                box = draw.textbbox((0, 0), line, font=f)
                text_w = box[2]-box[0]
                draw.text((x0+(max_w-text_w)//2, y), line, font=f, fill=fill)
                y += step
            return
    # Smallest font still too long: trim safely rather than extending beyond ticket.
    f = font(min_size, bold)
    end = len(text)
    while end>1 and draw.textbbox((0, 0),text[:end]+'…',font=f)[2]>max_w:
        end-=1
    draw.text((x0+4, y0+4), text[:end]+'…', fill=fill, font=f)


def _dash_line(draw, bbox, width=3, dash=11):
    x0,y0,x1,y1 = tuple(map(int, bbox))
    for x in range(x0,x1,dash*2):
        draw.line((x,y0,min(x+dash,x1),y0),fill='black',width=width)
        draw.line((x,y1,min(x+dash,x1),y1),fill='black',width=width)
    for y in range(y0,y1,dash*2):
        draw.line((x0,y,x0,min(y+dash,y1)),fill='black',width=width)
        draw.line((x1,y,x1,min(y+dash,y1)),fill='black',width=width)


def _qr_image(value: str) -> Image.Image:
    """2 puntos por modulo minimo para que el QR compacto conserve detalle."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=2, border=4)
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color='black',back_color='white').convert('RGB')
    return image


def render_landscape_ticket(event: dict, ticket: dict, width_mm: int=80, design: dict | None=None) -> Image.Image:
    """Imagen final horizontal, una entrada y un QR (sin hacer antialias sobre el QR)."""
    if width_mm not in PRINTABLE_DOTS:
        raise ValueError('Ancho disponible: 58 u 80 mm.')
    design = design or {}
    W,H = LANDSCAPE_SIZE[width_mm]
    sc = H/576
    X = lambda n: int(round(n*sc))
    im = Image.new('RGB',(W,H),'white')
    poster = _open_image(design.get('poster'))
    background_mode = design.get('poster_mode') == 'fondo'
    if poster and background_mode:
        _cover(im,poster,(X(10),X(120),X(845),H-X(95)))
        overlay = Image.new('RGB', im.size,'white')
        im = Image.blend(im,overlay,0.81)  # fondo suave para contraste termico
    draw = ImageDraw.Draw(im)
    draw.rectangle((X(4),X(4),W-X(5),H-X(5)),outline='black',width=max(2,X(3)))
    draw.line((X(14),X(116),X(845),X(116)), fill='black',width=max(1,X(2)))
    draw.line((X(14),X(495),X(845),X(495)), fill='black',width=max(1,X(2)))
    draw.line((X(854),X(12),X(854),H-X(12)), fill='black',width=max(2,X(3)))

    ayto = _open_image(design.get('logo_ayto'))
    centro = _open_image(design.get('logo_centro'))
    if ayto: _cover(im,ayto,(X(16),X(18),X(110),X(102)),fit='contain')
    if centro: _cover(im,centro,(X(744),X(18),X(840),X(102)),fit='contain')
    header_left = 115 if ayto else 18
    header_right = 740 if centro else 840
    _center(draw, design.get('cabecera') or 'ESCUELA MUNICIPAL DE MÚSICA Y DANZA',
            (X(header_left),X(14),X(header_right),X(71)), X(33), bold=True,lines=2,min_size=X(17))
    _center(draw, design.get('subtitulo') or 'Arroyo de la Miel',
            (X(header_left),X(72),X(header_right),X(112)),X(24),bold=True,min_size=X(15))

    if poster and not background_mode:
        _cover(im, poster, (X(25),X(137),X(290),X(467)),fit='contain')
        draw.rectangle((X(24),X(136),X(291),X(468)),outline='black',width=max(1,X(1)))
        content_left = 312
    else:
        content_left = 26
    date = datetime.fromisoformat(str(event['start_time']))
    _center(draw, str(event['name']),
            (X(content_left),X(130),X(834),X(246)),X(44),bold=True,lines=2,min_size=X(21))
    _center(draw, date.strftime('%d/%m/%Y'),
            (X(content_left),X(251),X(834),X(320)),X(51),bold=True,min_size=X(24))
    _center(draw, date.strftime('%H:%M H'),
            (X(content_left),X(319),X(834),X(398)),X(66),bold=True,min_size=X(27))
    _center(draw, design.get('lugar') or 'Casa de la Cultura · Arroyo de la Miel',
            (X(content_left),X(401),X(834),X(476)),X(30),bold=True,lines=2,min_size=X(16))

    # Reglas compactas, bajo la linea principal: en entrada numerada cambian.
    if event['mode'] == 'libre':
        notice = ['SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA',
                  'PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA']
    else:
        notice = ['RESPETE LA FILA Y BUTACA ASIGNADAS',
                  'PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA']
    for i, line in enumerate(notice):
        _center(draw,line,(X(18),X(500+i*31),X(841),X(526+i*29)),X(17),bold=(i==0),min_size=X(10))

    # Talon derecho: numero grande, QR compacto, modalidad y 1 persona.
    _dash_line(draw,(X(871),X(135),W-X(18),X(221)),width=max(1,X(2)),dash=max(4,X(10)))
    _center(draw,f"N.º {int(ticket['number']):04d}",
            (X(876),X(146),W-X(20),X(207)),X(32),bold=True,min_size=X(17))

    qr = _qr_image(ticket['qr'])
    # No reducir con reescalado: si el QR no cabe, avisar para no entregar uno ilegible.
    side_x0, side_x1 = X(859), W-X(9)
    if qr.width > side_x1-side_x0-2:
        raise ValueError('El QR firmado no cabe en el ancho elegido sin perder legibilidad.')
    qrx = side_x0 + (side_x1-side_x0-qr.width)//2
    qry = X(225)
    if qry+qr.height > H-X(110):
        raise ValueError('QR demasiado alto para la zona reservada.')
    im.paste(qr,(qrx,qry))
    draw = ImageDraw.Draw(im)
    yq=qry+qr.height+X(4)
    _center(draw,'ESCANEAR QR', (X(861),yq,W-X(10),yq+X(25)),X(19),bold=True,min_size=max(8,X(12)))
    yq += X(25)
    _center(draw, ticket.get('seat_label') or 'ENTRADA LIBRE',
            (X(861),yq,W-X(10),yq+X(32)),X(18),bold=True,lines=2,min_size=max(8,X(10)))
    yq += X(32)
    _center(draw, '1 PERSONA', (X(861),yq,W-X(10),yq+X(45)),X(30),bold=True,min_size=max(9,X(17)))
    yq += X(45)
    _center(draw, 'PROHIBIDA SU VENTA', (X(861),yq,W-X(10),H-X(9)),X(16),bold=True,min_size=max(7,X(9)))
    # La ZYWELL es monocroma: la vista previa debe verse como saldrá de la impresora.
    return im.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG).convert('RGB')


def render_ticket(event: dict, ticket: dict, width_mm: int=80, design: dict | None=None) -> Image.Image:
    """Para el RAW ESC/POS: ancho de 576/384 puntos, contenido girado 90 grados."""
    img = render_landscape_ticket(event,ticket,width_mm,design)
    return img.transpose(Image.Transpose.ROTATE_90)


def export_single_pdf(event: dict, ticket: dict, path: Path, width_mm: int=80, design: dict|None=None) -> Path:
    image = render_landscape_ticket(event,ticket,width_mm,design)
    # 203 dpi aprox: 8 dots/mm. En preview se muestra horizontal.
    w_mm,h_mm = (image.width/8,image.height/8)
    path = Path(path)
    pdf = Canvas(str(path), pagesize=(w_mm*mm,h_mm*mm))
    pdf.setTitle(f"Entrada {int(ticket['number']):04d} - {event['name']}")
    pdf.drawImage(ImageReader(image),0,0,width=w_mm*mm,height=h_mm*mm)
    pdf.save()
    return path


def list_windows_printers() -> list[str]:
    try:
        import win32print
        printers=win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL|win32print.PRINTER_ENUM_CONNECTIONS)
        return sorted(set(p[2] for p in printers))
    except ImportError:
        return []


def _escpos_bytes(im: Image.Image, cut: bool=False, *, full_cut: bool=True) -> bytes:
    """ESC/POS raster tiras de 240 filas; avance ANTES del cortador.

    Impresora debe tener soporte ESC/POS, cola en Windows que acepte RAW
    y cortador fisico. Un PDF impreso con visor NO equivale al envio RAW.
    """
    mono=im.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG)
    w,h=mono.size
    if w%8 or not (0<w<=2048):
        raise ValueError('Anchura raster no compatible.')
    stride=w//8
    head=bytearray(b'\x1b\x40\x1b\x61\x01')
    for top in range(0,h,240):
        stripe=mono.crop((0,top,w,min(h,top+240)))
        rows=stripe.height
        raw=bytes(b^0xff for b in stripe.tobytes())
        head+=b'\x1d\x76\x30\x00'+bytes((stride&255,stride>>8,rows&255,rows>>8))+raw
    head+=b'\x1b\x4a\x50'  # 80 dots = unos 10 mm, avanzar fuera de la cuchilla
    if cut:
        head+=b'\x1d\x56'+(b'\x00' if full_cut else b'\x01')
    return bytes(head)


def send_raw(printer_name: str, payload: bytes, document='Control de Entradas'):
    try:
        import win32print
    except ImportError as exc:
        raise RuntimeError('Falta pywin32: control de impresoras de Windows.') from exc
    if printer_name not in list_windows_printers():
        raise ValueError('Selecciona una impresora que esté instalada en Windows.')
    handle=win32print.OpenPrinter(printer_name)
    try:
        job=win32print.StartDocPrinter(handle,1,(document,None,'RAW'))
        try:
            win32print.StartPagePrinter(handle)
            try:
                written=win32print.WritePrinter(handle,payload)
                if written!=len(payload):
                    raise OSError('La cola no ha aceptado todos los bytes del ticket.')
            finally:
                win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)
    return job


def print_windows_escpos(event: dict, ticket: dict, printer_name: str,
                         width_mm: int=80, design: dict|None=None,
                         cut: bool=True, *, full_cut=True):
    image=render_ticket(event,ticket,width_mm,design)
    raw=_escpos_bytes(image,cut=cut,full_cut=full_cut)
    return send_raw(printer_name,raw,f'Entrada {int(ticket["number"]):04d} - {event["name"][:25]}')


def test_cutter(printer_name: str, *, full_cut: bool=True):
    """Prueba separada y confirmada desde la UI. No imprime ningun QR."""
    from PIL import Image
    # Unos 12 mm de avance y comando cutter; no imprimir para reducir residuos.
    raw=b'\x1b\x40\x1b\x4a\x60\x1d\x56'+(b'\x00' if full_cut else b'\x01')
    return send_raw(printer_name,raw,'TEST cortador ESC/POS')
