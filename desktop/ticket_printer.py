"""Control de Entradas 0.7: entradas HORIZONTALES en rollo termico de 58/80 mm.

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


TEMPLATES = (
    '01 · Clásico',
    '02 · Cartel protagonista',
    '03 · Panorámico',
    '04 · Fondo suave',
    '05 · Editorial',
    '06 · Mosaico',
)
IMAGE_FITS = ('Rellenar y recortar', 'Mostrar completa')
LOGO_SIZES = ('Pequeños', 'Medianos', 'Grandes')


def _fitted(im: Image.Image, source: Image.Image | None, rect, method='Rellenar y recortar', soften=0.0):
    '''Imagen llena su zona (cover) o se muestra completa (contain).'''
    if source is None:
        return
    x0,y0,x1,y1 = map(int,rect)
    w,h=x1-x0,y1-y0
    if w < 3 or h < 3:
        return
    if method == 'Mostrar completa':
        cropped=ImageOps.contain(source,(w,h),method=Image.Resampling.LANCZOS)
        target=(x0+(w-cropped.width)//2,y0+(h-cropped.height)//2)
    else:
        cropped=ImageOps.fit(source,(w,h),method=Image.Resampling.LANCZOS,centering=(0.5,0.5))
        target=(x0,y0)
    if soften:
        cropped=Image.blend(cropped.convert('RGB'),Image.new('RGB',cropped.size,'white'),max(0.0,min(0.95,soften)))
    im.paste(cropped,target)


def render_landscape_ticket(event: dict, ticket: dict, width_mm: int = 80,
                            design: dict | None = None, *, length_mm: int | None = None) -> Image.Image:
    """Renderiza en coordenadas del papel FINAL; no redimensiona textos ni QR.

    X es la dirección de avance de la impresora después del giro de 90 grados.
    Se reserva un margen blanco en ambos extremos para tolerancias de corte.
    La altura coincide con el ancho imprimible real (576/384 puntos).
    """
    if width_mm not in PRINTABLE_DOTS:
        raise ValueError('Selecciona un rollo de 58 u 80 mm.')
    if length_mm is not None and (not isinstance(length_mm, int) or not 85 <= length_mm <= 190):
        raise ValueError('Longitud permitida: 85 a 190 mm.')
    design = design or {}
    H = PRINTABLE_DOTS[width_mm]
    W = int((length_mm or (135 if width_mm == 80 else 90)) * 8)
    s = H / 576.0
    v = lambda n: int(round(n*s))
    safe = max(13, v(30))    # Bordes blancos ~2.5-4 mm; no enmarcar sobre la cuchilla.
    try:
        shift_mm = float(design.get('desplazamiento_mm', 0) or 0)
    except (ValueError, TypeError) as exc:
        raise ValueError('El desplazamiento del diseño debe ser un número.') from exc
    if not -3 <= shift_mm <= 3:
        raise ValueError('El desplazamiento permitido es entre -3 y +3 mm.')
    shift = round(shift_mm * 8)
    left_safe, right_safe = safe + shift, safe - shift
    qrstub = v(224)
    divider = W - right_safe - qrstub
    L, R = left_safe, divider-v(8)
    usable = R - L
    if usable < v(590):
        min_length = math.ceil((v(590)+v(224)+2*safe+v(8))/8)
        raise ValueError(f'El ticket de {width_mm} mm necesita un largo de al menos {min_length} mm para mantener el QR y el texto legibles.')
    if R <= L:
        raise ValueError('No queda espacio para el cuerpo de la entrada.')

    chosen = str(design.get('plantilla') or '')
    if chosen not in TEMPLATES:
        chosen = TEMPLATES[3] if design.get('poster_mode') == 'fondo' else TEMPLATES[0]
    kind = TEMPLATES.index(chosen)
    fit = design.get('ajuste_imagen', IMAGE_FITS[0])
    if fit not in IMAGE_FITS:
        fit = IMAGE_FITS[0]
    poster = _open_image(design.get('poster'))
    ayto = _open_image(design.get('logo_ayto'))
    centro = _open_image(design.get('logo_centro'))
    im = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(im)
    stroke = max(1, v(2))
    # Geometry: body width flexible, QR stub fixed in printer dots.
    def br(x0, y0, x1, y1):
        return (L + round(usable*x0/1000), v(y0), L + round(usable*x1/1000), v(y1))
    def sr(x0, y0, x1, y1):
        return (divider + v(x0), v(y0), divider + v(x1), v(y1))
    def text_box(txt, box, size=33, *, bold=True, lines=2, min_size=11, color='black'):
        _center(ImageDraw.Draw(im), str(txt), box, v(size), bold=bold, lines=lines,
                min_size=max(8, v(min_size)), fill=color)
    def bodytext(txt, box, size=33, *, lines=2, min_size=11, bold=True, color='black'):
        text_box(txt, br(*box), size, bold=bold, lines=lines, min_size=min_size, color=color)
    def photo(box, *, soften=0.0, frame=False):
        x0,y0,x1,y1 = br(*box)
        if poster is not None:
            _fitted(im, poster, (x0,y0,x1,y1), fit, soften)
        if frame and poster is not None:
            ImageDraw.Draw(im).rectangle((x0,y0,x1-1,y1-1), outline='black', width=stroke)
    def line(x0,y0,x1,y1):
        ImageDraw.Draw(im).line((x0,y0,x1,y1),fill='black',width=stroke)

    # Marco interior con zona segura longitudinal para el cortador.
    draw.rectangle((L, v(7), W-right_safe, H-v(8)), outline='black', width=stroke)
    line(divider, v(12), divider, H-v(12))
    line(L+v(4), v(117), divider-v(4), v(117))

    logo_size = design.get('tamano_logos', 'Grandes')
    logo_width = {'Pequeños': v(90), 'Medianos': v(113), 'Grandes': v(147)}.get(logo_size, v(147))
    if ayto:
        _fitted(im, ayto, (L+v(8),v(13),L+v(8)+logo_width,v(104)), 'Mostrar completa')
    if centro:
        _fitted(im, centro, (R-v(8)-logo_width,v(13),R-v(8),v(104)), 'Mostrar completa')
    header_left = L + (logo_width+v(14) if ayto else v(13))
    header_right = R - (logo_width+v(14) if centro else v(13))
    text_box(design.get('cabecera') or 'Escuela Municipal de Música y Danza',
             (header_left,v(14),header_right,v(79)), 33, lines=2, min_size=12)
    text_box(design.get('subtitulo') or 'Arroyo de la Miel',
             (header_left,v(78),header_right,v(108)), 22, lines=1, min_size=10)

    date = datetime.fromisoformat(str(event['start_time']))
    day = date.strftime('%d/%m/%Y')
    when = date.strftime('%H:%M H')
    label = str(event['name'])
    place = str(design.get('lugar') or 'Casa de la Cultura · Arroyo de la Miel')
    if kind == 0:
        photo((5,127,383,474),frame=True)
        off = 397 if poster else 12
        bodytext(label,(off,143,989,250),45,lines=2,min_size=17)
        bodytext(day,(off,248,989,317),44,lines=1,min_size=17)
        bodytext(when,(off,324,989,399),59,lines=1,min_size=20)
        bodytext(place,(off,405,989,475),26,lines=2,min_size=12)
    elif kind == 1:
        photo((5,127,520,481),frame=True)
        off = 535 if poster else 15
        bodytext(label,(off,135,988,264),42,lines=3,min_size=15)
        bodytext(day,(off,280,988,343),35,lines=1,min_size=14)
        bodytext(when,(off,344,988,417),50,lines=1,min_size=18)
        bodytext(place,(off,416,988,483),24,lines=2,min_size=11)
    elif kind == 2:
        photo((5,125,995,314),frame=True)
        bodytext(label,(11,320,991,377),42,lines=2,min_size=16)
        bodytext(f'{day}   {when}',(11,381,991,435),39,lines=1,min_size=16)
        bodytext(place,(11,437,991,481),24,lines=2,min_size=10)
    elif kind == 3:
        photo((5,124,995,483),soften=0.84)
        bodytext(label,(35,140,970,272),50,lines=2,min_size=18)
        bodytext(day,(25,273,977,347),47,lines=1,min_size=19)
        bodytext(when,(25,348,977,423),58,lines=1,min_size=22)
        pbox = br(33,437,968,483)
        ImageDraw.Draw(im).rounded_rectangle(pbox,radius=v(7),fill='black')
        text_box('CASA DE LA CULTURA · '+place.split('·')[-1].strip(),pbox,22,min_size=10,color='white',lines=1)
    elif kind == 4:
        photo((604,124,995,483),frame=True)
        ImageDraw.Draw(im).rectangle(br(8,127,19,477),fill='black')
        pos = 590 if poster else 984
        bodytext(label,(35,136,pos,268),49,lines=3,min_size=17)
        bodytext(day,(30,272,pos,346),36,lines=1,min_size=14)
        bodytext(when,(30,343,pos,420),56,lines=1,min_size=18)
        bodytext(place,(30,418,pos,483),25,lines=2,min_size=10)
    else:
        photo((5,126,258,481),frame=True)
        photo((738,126,995,481),frame=True)
        bodytext(label,(268,145,729,273),38,lines=3,min_size=14)
        bodytext(day,(265,274,733,341),31,lines=1,min_size=12)
        bodytext(when,(266,338,730,421),49,lines=1,min_size=16)
        bodytext(place,(262,422,734,480),21,lines=2,min_size=9)

    line(L+v(4),v(490),R,v(490))
    if event['mode'] == 'libre':
        notes=('SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    else:
        notes=('RESPETE SU FILA Y BUTACA ASIGNADAS',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    bodytext(notes[0],(10,496,990,526),17,lines=1,min_size=9)
    bodytext(notes[1],(10,526,990,557),16,lines=1,min_size=9)

    # Talón derecho de anchura fija: el QR jamás sufre estiramiento ni interpolación.
    stub_left,stub_right = divider+v(8),W-right_safe-v(4)
    _dash_line(ImageDraw.Draw(im),(stub_left,v(125),stub_right,v(201)),
               width=stroke,dash=max(5,v(10)))
    text_box(f"N.º {int(ticket['number']):04d}",
             (stub_left+v(1),v(130),stub_right-v(1),v(192)), 30,lines=1,min_size=12)
    qr = _qr_image(ticket['qr'])
    qw,qh = qr.size
    if qw > stub_right-stub_left-v(2):
        raise ValueError('El QR firmado no cabe sin reducir su resolución; usa un rollo mayor.')
    qx=(stub_left+stub_right-qw)//2
    qy=v(211)
    if qy+qh > v(448):
        raise ValueError('QR demasiado grande para este papel.')
    im.paste(qr,(qx,qy))
    y = qy + qh + v(4)
    text_box('ESCANEAR QR',(stub_left,y,stub_right,y+v(27)),17,lines=1,min_size=9)
    y += v(27)
    text_box(ticket.get('seat_label') or 'ENTRADA LIBRE',
             (stub_left,y,stub_right,y+v(37)),16,lines=2,min_size=9)
    y += v(38)
    text_box('1 PERSONA',(stub_left,y,stub_right,y+v(43)),25,lines=1,min_size=13)
    text_box('PROHIBIDA SU VENTA',
             (stub_left,H-v(75),stub_right,H-v(18)),15,lines=1,min_size=9)
    return im.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG).convert('RGB')

def render_ticket(event: dict, ticket: dict, width_mm: int=80, design: dict | None=None, *, length_mm: int|None=None) -> Image.Image:
    """Para RAW ESC/POS: ancho de 576/384 puntos, girado 90 grados."""
    img = render_landscape_ticket(event,ticket,width_mm,design,length_mm=length_mm)
    return img.transpose(Image.Transpose.ROTATE_90)


def export_single_pdf(event: dict, ticket: dict, path: Path, width_mm: int=80, design: dict|None=None, *, length_mm: int|None=None) -> Path:
    image = render_landscape_ticket(event,ticket,width_mm,design,length_mm=length_mm)
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


CUT_MODES=('Manual (avance ajustable)', 'Automático (GS V 65)')


def _escpos_bytes(im: Image.Image, cut: bool=False, *, full_cut: bool=True,
                  feed_dots: int=120, cut_mode: str = CUT_MODES[0], reset: bool=True) -> bytes:
    '''Convertir a datos ESC/POS. Corte manual con avance, o corte automático del firmware.

    IMPORTANTE: GS V 65/66 depende del soporte del modelo. No hay manera de
    calibrar físicamente el cabezal y la cuchilla sin conocer esa distancia.
    '''
    if not (0 <= int(feed_dots) <= 255):
        raise ValueError('Avance entre 0 y 255 puntos.')
    if cut_mode not in CUT_MODES:
        raise ValueError('Modo de corte no reconocido.')
    mono=im.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG)
    w,h=mono.size
    if w%8 or not (0<w<=2048):
        raise ValueError('Anchura raster no compatible.')
    stride=w//8
    stream=bytearray((b'\x1b\x40' if reset else b'') + b'\x1b\x61\x01')
    for top in range(0,h,240):
        stripe=mono.crop((0,top,w,min(h,top+240)))
        rows=stripe.height
        raw=bytes(b^0xff for b in stripe.tobytes())
        stream+=b'\x1d\x76\x30\x00'+bytes((stride&255,stride>>8,rows&255,rows>>8))+raw
    if cut and cut_mode == CUT_MODES[1]:
        # GS V 65/66 n=0: la impresora avanza hasta su propia posición
        # de corte y corta, si esta variante del firmware está soportada.
        stream += b'\x1d\x56' + (b'\x41' if full_cut else b'\x42') + b'\x00'
    else:
        if feed_dots:
            stream += b'\x1b\x4a' + bytes([int(feed_dots)])
        if cut:
            stream += b'\x1d\x56' + (b'\x00' if full_cut else b'\x01')
    return bytes(stream)

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
                         cut: bool=True, *, full_cut=True, feed_dots: int=120,
                         cut_mode: str = CUT_MODES[0], length_mm: int|None=None):
    image=render_ticket(event,ticket,width_mm,design,length_mm=length_mm)
    raw=_escpos_bytes(image,cut=cut,full_cut=full_cut,feed_dots=feed_dots,cut_mode=cut_mode)
    return send_raw(printer_name,raw,f'Entrada {int(ticket["number"]):04d} - {event["name"][:25]}')


def test_cutter(printer_name: str, *, full_cut: bool=True):
    """Prueba separada y confirmada desde la UI. No imprime ningun QR."""
    from PIL import Image
    # Unos 12 mm de avance y comando cutter; no imprimir para reducir residuos.
    raw=b'\x1b\x40\x1b\x4a\x60\x1d\x56'+(b'\x00' if full_cut else b'\x01')
    return send_raw(printer_name,raw,'TEST cortador ESC/POS')


def print_windows_escpos_batch(pairs, printer_name: str, width_mm: int=80, design: dict|None=None,
                              cut: bool=True, *, full_cut: bool=True, feed_dots: int=120,
                              cut_mode: str = CUT_MODES[0], length_mm: int|None=None):
    """Un único trabajo RAW para una secuencia numerada, con corte entre tickets.

    No se marcan las entradas como utilizadas: imprimir y validar son operaciones distintas.
    """
    pairs=list(pairs)
    if not pairs:
        raise ValueError('No hay entradas que imprimir.')
    if len(pairs)>500:
        raise ValueError('Máximo 500 tickets por lote; divide el trabajo.')
    if not printer_name:
        raise ValueError('Selecciona la impresora.')
    payload=bytearray()
    for idx,(event,ticket) in enumerate(pairs):
        image=render_ticket(event,ticket,width_mm,design,length_mm=length_mm)
        payload.extend(_escpos_bytes(image,cut=cut,full_cut=full_cut,
                                     feed_dots=feed_dots,cut_mode=cut_mode,
                                     reset=(idx == 0)))
    first,last=pairs[0][1]['number'],pairs[-1][1]['number']
    return send_raw(printer_name,bytes(payload),f'Entradas {first:04d}-{last:04d}')