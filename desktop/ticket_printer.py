"""Control de Entradas 0.6: entradas HORIZONTALES en rollo termico de 58/80 mm.

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


def render_landscape_ticket(event: dict, ticket: dict, width_mm: int=80, design: dict | None=None, *, length_mm: int | None = None) -> Image.Image:
    '''Render de seis plantillas horizontales. QR intacto y zona segura de corte.'''
    if width_mm not in PRINTABLE_DOTS:
        raise ValueError('Ancho disponible: 58 u 80 mm.')
    design=design or {}
    chosen=str(design.get('plantilla') or '')
    if chosen not in TEMPLATES:
        chosen = TEMPLATES[3] if design.get('poster_mode')=='fondo' else TEMPLATES[0]
    kind=TEMPLATES.index(chosen)
    fit=design.get('ajuste_imagen','Rellenar y recortar')
    if fit not in IMAGE_FITS:
        fit=IMAGE_FITS[0]
    poster=_open_image(design.get('poster'))
    ayto=_open_image(design.get('logo_ayto'))
    centro=_open_image(design.get('logo_centro'))
    W,H=LANDSCAPE_SIZE[width_mm]
    sc=H/576
    X=lambda a:int(round(a*sc))
    rect=lambda a,b,c,d:(X(a),X(b),X(c),X(d))
    im=Image.new('RGB',(W,H),'white')
    draw=ImageDraw.Draw(im)
    line_width=max(1,X(2))
    # Conservar márgenes mínimos para evitar cortes de bordes en papel térmico.
    draw.rectangle(rect(4,4,1075,571),outline='black',width=max(2,X(3)))
    draw.line((X(850),X(12),X(850),X(565)),fill='black',width=max(2,X(3)))

    size=design.get('tamano_logos','Grandes')
    widths={'Pequeños':90,'Medianos':117,'Grandes':155}
    logo_w=widths.get(size,155)
    if ayto:
        _fitted(im,ayto,rect(18,12,18+logo_w,108),'Mostrar completa')
    if centro:
        _fitted(im,centro,rect(829-logo_w,12,829,108),'Mostrar completa')
    draw=ImageDraw.Draw(im)
    left_text=25+logo_w if ayto else 18
    right_text=824-logo_w if centro else 832
    _center(draw,design.get('cabecera') or 'ESCUELA MUNICIPAL DE MÚSICA Y DANZA',
            rect(left_text,13,right_text,77),X(33),bold=True,lines=2,min_size=max(10,X(16)))
    _center(draw,design.get('subtitulo') or 'Arroyo de la Miel',
            rect(left_text,77,right_text,112),X(23),bold=True,min_size=max(9,X(13)))
    draw.line((X(12),X(116),X(846),X(116)),fill='black',width=line_width)

    label=str(event['name'])
    date=datetime.fromisoformat(str(event['start_time']))
    day=date.strftime('%d/%m/%Y')
    time=date.strftime('%H:%M H')
    place=design.get('lugar') or 'Casa de la Cultura · Arroyo de la Miel'
    def txt(value,box,fontsize=36,bold=True,lines=2,min_size=14,fill='black'):
        _center(ImageDraw.Draw(im),value,rect(*box),X(fontsize),bold=bold,lines=lines,
                min_size=max(8,X(min_size)),fill=fill)
    def photo(box,method=None,soften=0.0,framed=False):
        if poster:
            _fitted(im,poster,rect(*box),method or fit,soften)
        if framed:
            ImageDraw.Draw(im).rectangle(rect(*box),outline='black',width=line_width)
    def pill(box,text,fill='black',fg='white',fontsize=21):
        d=ImageDraw.Draw(im)
        d.rounded_rectangle(rect(*box),radius=X(7),fill=fill)
        txt(text,box,fontsize,bold=True,lines=1,min_size=11,fill=fg)

    if kind == 0:  # Referencia original, cartel a la izquierda y datos en el centro
        photo((14,125,333,481),framed=True)
        left=349 if poster else 22
        txt(label,(left,140,835,245),46,lines=2,min_size=19)
        txt(day,(left,250,835,319),47,lines=1,min_size=20)
        txt(time,(left,319,835,398),64,lines=1,min_size=25)
        txt(place,(left,401,835,479),27,lines=2,min_size=13)
    elif kind == 1:  # 45% de superficie para cartel a sangre
        photo((13,122,460,488),framed=True)
        txt(label,(474,130,838,260),43,lines=3,min_size=19)
        txt(day,(474,278,838,342),36,lines=1,min_size=17)
        txt(time,(474,341,838,416),51,lines=1,min_size=22)
        txt(place,(475,423,838,485),23,lines=2,min_size=13)
    elif kind == 2:  # Fotografía en banda panorámica, texto inferior
        photo((14,122,836,309),framed=True)
        txt(label,(20,313,836,375),40,lines=2,min_size=18)
        txt(f'{day}    {time}',(20,372,836,433),43,lines=1,min_size=18)
        txt(place,(20,433,836,486),26,lines=2,min_size=12)
    elif kind == 3:  # Fondo suave no oculto, estampado tenue detrás de la información
        photo((14,122,836,487),soften=0.83)
        txt(label,(38,147,811,268),53,lines=2,min_size=23)
        txt(day,(30,266,822,344),53,lines=1,min_size=22)
        txt(time,(30,348,822,424),62,lines=1,min_size=25)
        pill((46,435,810,484),'CASA DE LA CULTURA · '+str(place).split('·')[-1].strip(),fontsize=23)
    elif kind == 4:  # Editorial con jerarquía izquierda y foto a la derecha
        photo((512,123,836,485),framed=True)
        d=ImageDraw.Draw(im)
        d.rectangle(rect(16,124,26,483),fill='black')
        txt(label,(38,136,496,271),52,lines=3,min_size=20)
        txt(day,(38,280,496,341),35,lines=1,min_size=16)
        txt(time,(38,337,496,413),63,lines=1,min_size=22)
        txt(place,(36,421,500,486),24,lines=2,min_size=13)
    else:  # Mosaico: dos grandes recortes del mismo cartel, título central
        photo((15,123,244,484),framed=True)
        photo((605,123,836,484),framed=True)
        txt(label,(255,149,594,277),38,lines=3,min_size=17)
        txt(day,(255,279,594,341),32,lines=1,min_size=14)
        txt(time,(255,340,594,415),49,lines=1,min_size=18)
        txt(place,(252,416,598,484),20,lines=2,min_size=11)

    d=ImageDraw.Draw(im)
    d.line((X(13),X(493),X(844),X(493)),fill='black',width=line_width)
    if event['mode']=='libre':
        notes=('SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    else:
        notes=('RESPETE SU FILA Y BUTACA ASIGNADAS',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    txt(notes[0],(17,496,841,525),18,lines=1,min_size=9)
    txt(notes[1],(17,526,841,555),16,lines=1,min_size=9)

    # Talón derecho invariable para garantizar que el QR mantiene legibilidad.
    _dash_line(d,rect(869,135,1063,218),width=max(1,X(2)),dash=max(3,X(9)))
    txt(f"N.º {int(ticket['number']):04d}",(874,146,1060,210),30,lines=1,min_size=16)
    qr=_qr_image(ticket['qr'])
    x0,x1=X(856),W-X(9)
    if qr.width > x1-x0-2:
        raise ValueError('El QR firmado no cabe en el ancho elegido sin perder legibilidad.')
    qr_x=x0+(x1-x0-qr.width)//2
    qr_y=X(222)
    if qr_y+qr.height > H-X(113):
        raise ValueError('QR demasiado alto para la zona reservada.')
    im.paste(qr,(qr_x,qr_y))
    yq=qr_y+qr.height+X(3)
    _center(ImageDraw.Draw(im),'ESCANEAR QR',(X(857),yq,W-X(10),yq+X(26)),X(18),bold=True,min_size=max(8,X(11)))
    yq+=X(27)
    _center(ImageDraw.Draw(im),ticket.get('seat_label') or 'ENTRADA LIBRE',
            (X(858),yq,W-X(10),yq+X(34)),X(17),bold=True,lines=2,min_size=max(8,X(10)))
    yq+=X(35)
    _center(ImageDraw.Draw(im),'1 PERSONA',(X(858),yq,W-X(10),yq+X(44)),X(27),bold=True,min_size=max(9,X(15)))
    _center(ImageDraw.Draw(im),'PROHIBIDA SU VENTA',(X(857),H-X(75),W-X(10),H-X(12)),X(16),bold=True,min_size=max(8,X(9)))
    # Permitir un largo variable sin deformar el QR. Mantener íntegro el talón derecho
    # (incluido QR y número), y comprimir/expandir SOLO el cuerpo del ticket.
    if length_mm is not None:
        if not isinstance(length_mm, int) or not (85 <= length_mm <= 190):
            raise ValueError('Largo de ticket permitido: 85 a 190 mm.')
        target_width = int(length_mm * 8)  # Resolución de impresora: 203 dpi, ~8 puntos/mm
        stub_x = X(850)
        stub_width = W - stub_x
        if target_width < stub_width + X(480):
            raise ValueError('Ticket demasiado corto para los datos y el QR.')
        if target_width != W:
            main = im.crop((0, 0, stub_x, H))
            stub = im.crop((stub_x, 0, W, H))
            result = Image.new('RGB', (target_width, H), 'white')
            new_main_w = target_width - stub_width
            result.paste(main.resize((new_main_w, H), Image.Resampling.LANCZOS), (0, 0))
            result.paste(stub, (new_main_w, 0))
            im = result
    # Reducir ruido del JPG; aplicar tramado al tamaño FINAL, antes del RAW.
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
                  feed_dots: int=120, cut_mode: str = CUT_MODES[0]) -> bytes:
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
    stream=bytearray(b'\x1b\x40\x1b\x61\x01')
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
    for event,ticket in pairs:
        image=render_ticket(event,ticket,width_mm,design,length_mm=length_mm)
        payload.extend(_escpos_bytes(image,cut=cut,full_cut=full_cut,
                                     feed_dots=feed_dots,cut_mode=cut_mode))
    first,last=pairs[0][1]['number'],pairs[-1][1]['number']
    return send_raw(printer_name,bytes(payload),f'Entradas {first:04d}-{last:04d}')
