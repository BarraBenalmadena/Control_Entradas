"""Control de Entradas 0.9: entradas HORIZONTALES en rollo termico de 58/80 mm.

El ticket terminado se lee en horizontal. En la ZYWELL se transmite girado 90º:
la anchura fisica de papel es 58/80 mm, y el largo avanza hasta el corte.
La vista previa y el PDF muestran la misma entrada en horizontal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import io
import math

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps, ImageFilter
import qrcode
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.graphics.barcode.code128 import Code128
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from catalog_models import CATALOG_NAMES, CATALOG_INDEX, catalog_asset

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


def _qr_image(value: str, max_width: int = 240, max_height: int = 240) -> Image.Image:
    """Priorizar módulos de 3/4 puntos cuando el formato físico lo permita.

    La firma ECDSA de los códigos CE1 obliga a codificar muchos módulos. Con
    dos puntos a 203 ppp el módulo mide apenas 0,25 mm, ilegible en térmica
    cuando el lector se separa un poco. Nunca se interpola un QR renderizado.
    """
    if max_width < 60 or max_height < 60:
        raise ValueError('Área demasiado pequeña para imprimir un QR legible.')
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=4)
    qr.add_data(value)
    qr.make(fit=True)
    cells = qr.modules_count + 8  # cuatro módulos blancos en cada lado
    box = min(4, max_width // cells, max_height // cells)
    if box < 2:
        raise ValueError('El QR no cabe: aumenta la longitud del ticket o utiliza papel de 80 mm.')
    qr.box_size = box
    return qr.make_image(fill_color='black',back_color='white').convert('RGB')


def barcode_ticket_value(ticket_id: str) -> str:
    """16-digit bearer identifier derived from 52 random bits of the ticket UUID.

    The original signed JSON/Windows event is still authoritative; a barcode
    doesn't grant access without matching an issued, enrolled ticket.
    """
    return f"{int(str(ticket_id)[:13],16):016d}"


def _code128_image(value: str, max_width: int, height: int) -> Image.Image:
    """Render Code128C in integer pixels, with white quiet zones."""
    code=Code128(value,barWidth=1,barHeight=height,humanReadable=False,quiet=False)
    code.validate()
    code.encode()
    code.decompose()
    units=sum(ord(c.lower())-96 for c in code.decomposed)
    # Code128 exige al menos diez módulos blancos por lado: no reducir
    # las quiet zones ni interpolar la trama.
    module=min(5,max_width//(units+20))
    if module < 1: raise ValueError("Sin espacio suficiente para código de barras.")
    quiet=module*10
    width=units*module+quiet*2
    im=Image.new('RGB',(width,height),'white')
    d=ImageDraw.Draw(im)
    cursor=quiet
    for c in code.decomposed:
        size=(ord(c.lower())-96)*module
        if c.isupper():d.rectangle((cursor,0,cursor+size-1,height-1),fill='black')
        cursor+=size
    return im


TEMPLATES = (
    '01 · Clásico',
    '02 · Cartel protagonista',
    '03 · Panorámico',
    '04 · Fondo suave',
    '05 · Editorial',
    '06 · Mosaico',
    '07 · Institucional',
    '08 · Escenario',
    '09 · Tríptico',
    '10 · Minimalista',
    '11 · Institucional formal',
    '12 · Ayuntamiento',
    '13 · Auditorio clásico',
    '14 · Programa cultural',
    '15 · Elegancia minimal',
    '16 · Institucional limpio',
    '23 · Clásico tipográfico',
    '24 · Danza con banda negra',
    '25 · Concierto con laureles',
    '26 · Teatro en columnas',
    '27 · Cine de estreno',
    '28 · Gala acceso general',
    '29 · Ornamental clásico',
    '30 · Diagonal moderna',
    '31 · Escenario moderno',
    '32 · Diagonal con cartel',
    '33 · Columna elegante',
    '34 · Banda panorámica',
    '35 · Escenario en contraste',
    '36 · Geometría cultural',
    '37 · Columnas blancas',
    '38 · Diagonal blanca',
    '39 · Escenario claro',
    '40 · Cartel editorial blanco',
    '41 · Avisos en recuadro (B)',
    '42 · Avisos con divisores (D)',
)
IMAGE_FITS = ('Rellenar y recortar', 'Mostrar completa')
LOGO_SIZES = ('Pequeños', 'Medianos', 'Grandes')
LOGO_POSITIONS = (
    'Según plantilla', 'Extremos', 'Juntos a la izquierda', 'Juntos a la derecha',
    'Apilados a la izquierda', 'Apilados a la derecha', 'Centrados',
)
# La selección por plantilla ofrece composiciones distintas incluso antes de ajustar los logos.
DEFAULT_LOGO_POSITIONS = (
    'Extremos', 'Juntos a la izquierda', 'Extremos', 'Centrados',
    'Juntos a la derecha', 'Extremos', 'Juntos a la izquierda',
    'Apilados a la derecha', 'Juntos a la derecha', 'Centrados',
    'Extremos', 'Juntos a la izquierda', 'Extremos',
    'Juntos a la derecha', 'Centrados', 'Apilados a la izquierda',
    'Extremos', 'Juntos a la izquierda', 'Extremos', 'Juntos a la derecha',
    'Extremos', 'Centrados', 'Extremos', 'Apilados a la izquierda',
    'Extremos', 'Extremos', 'Extremos', 'Extremos', 'Extremos', 'Extremos',
    'Extremos', 'Extremos', 'Extremos', 'Extremos',
    'Extremos', 'Extremos',
)



def _fitted(im: Image.Image, source: Image.Image | None, rect, method='Rellenar y recortar', soften=0.0, economy=False):
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
    if economy:
        gray=ImageOps.autocontrast(ImageOps.grayscale(cropped))
        edges=ImageOps.invert(gray.filter(ImageFilter.FIND_EDGES))
        cropped=edges.point(lambda p: 0 if p < 105 else 255).convert('RGB')
    im.paste(cropped,target)


def _setting_number(design: dict, field: str, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(str(design.get(field, default) or default).replace(',', '.'))
    except (ValueError, TypeError) as exc:
        raise ValueError(f'El valor de {field} debe ser numérico.') from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f'{field}: elige un valor entre {minimum:g} y {maximum:g}.')
    return number


def geometry(width_mm: int, length_mm: int | None, design: dict | None = None) -> dict:
    """Geometría compartida por vista previa, PDF y trama ESC/POS (8 puntos/mm).

    Los márgenes izquierdo y derecho siguen el sentido de avance del papel
    en una entrada horizontal; superior e inferior son los márgenes del ancho útil.
    """
    design = design or {}
    if width_mm not in PRINTABLE_DOTS:
        raise ValueError('Selecciona papel de 58 u 80 mm.')
    if length_mm is not None and (not isinstance(length_mm, int) or not 85 <= length_mm <= 190):
        raise ValueError('Largo del ticket: 85–190 mm.')
    W = (length_mm if length_mm is not None else (135 if width_mm == 80 else 90))*8
    H = PRINTABLE_DOTS[width_mm]
    margin_left = _setting_number(design,'margen_izquierdo_mm',2.0,0,18)
    margin_right = _setting_number(design,'margen_derecho_mm',2.0,0,18)
    margin_top = _setting_number(design,'margen_superior_mm',1.0,0,12)
    margin_bottom = _setting_number(design,'margen_inferior_mm',1.0,0,12)
    shift = _setting_number(design,'desplazamiento_mm',0,-3,3)
    L = max(8, round((margin_left+shift)*8))
    right_limit = max(8, round((margin_right-shift)*8))
    T = max(3,round(margin_top*8))
    B = max(3,round(margin_bottom*8))
    if H-T-B<205:
        raise ValueError('Márgenes superior e inferior demasiado grandes para el QR.')
    sx = (H-T-B)/576
    stub = round(302 * H/576)  # v1.2: más anchura reservada para QR ópticamente legible
    divider = W-right_limit-stub
    R = divider-round(8*H/576)
    usable = R-L
    if usable < round(550*H/576):
        raise ValueError('No cabe el contenido: reduce márgenes o aumenta el largo del ticket.')
    return dict(W=W,H=H,L=L,R=R,T=T,B=B,divider=divider,right_limit=right_limit,
                sx=sx,usable=usable,stub=stub)



def render_reference_jpg_ticket(event: dict, ticket: dict, width_mm: int,
                                design: dict, length_mm: int | None,
                                *, color_preview: bool=False) -> Image.Image:
    """Image-based catalog, with clean independent LIVE fields.

    A reference JPG is a flattened picture, not an editable file. Keep its
    decoration and photography; replace the entire barcode/QR/number areas
    rather than drawing little boxes on top of old printed sample codes.
    """
    source=catalog_asset(str(design['plantilla']))
    g=geometry(width_mm,length_mm,design)
    W,H=g['W'],g['H']
    with Image.open(source) as src:
        im=src.convert('RGB').resize((W,H),Image.Resampling.LANCZOS)

    rx=lambda f:round(f*W)
    ry=lambda f:round(f*H)
    paint=ImageDraw.Draw(im)
    def rectangle(coords,fill='white',outline=None,width=1):
        box=(rx(coords[0]),ry(coords[1]),rx(coords[2]),ry(coords[3]))
        paint.rectangle(box,fill=fill,outline=outline,width=width)
    def title(value,coords,size=34,fg='#09264c',lines=2):
        box=(rx(coords[0]),ry(coords[1]),rx(coords[2]),ry(coords[3]))
        _center(paint,str(value),box,max(12,round(size*H/576)),
                bold=True,lines=lines,min_size=max(10,round(14*H/576)),fill=fg)

    # When the designer supplies a poster JPG/PNG, display it INSIDE the
    # template's photograph panel, not as an ignored preference.
    poster=_open_image(design.get('poster'))
    if poster is not None:
        region=(rx(.018),ry(.045),rx(.275),ry(.955))
        fitted=ImageOps.fit(poster.convert('RGB'),
                            (region[2]-region[0],region[3]-region[1]),
                            method=Image.Resampling.LANCZOS,centering=(.5,.5))
        mask=Image.new('L',im.size,0)
        mask_draw=ImageDraw.Draw(mask)
        # Most supplied references have the art/photo to the left of a
        # diagonal/curved boundary. Limit the new poster to that region.
        mask_draw.polygon([(rx(.022),ry(.045)),(rx(.261),ry(.045)),
                           (rx(.222),ry(.950)),(rx(.022),ry(.950))],fill=255)
        poster_layer=Image.new('RGB',im.size,'white')
        poster_layer.paste(fitted,region[:2])
        im.paste(poster_layer,(0,0),mask)
        paint=ImageDraw.Draw(im)

    number=int(ticket['number'])
    date=datetime.fromisoformat(str(event['start_time']))
    day=date.strftime('%d/%m/%Y')
    when=date.strftime('%H:%M H')
    event_title=str(event['name']).strip()
    place=str(design.get('lugar') or 'Casa de la Cultura · Arroyo de la Miel').strip()
    header=str(design.get('cabecera') or 'Escuela Municipal de Música y Danza').strip()
    subheader=str(design.get('subtitulo') or 'Arroyo de la Miel').strip()
    accent='#0d2448'

    # Source JPGs contain DEMONSTRATION lettering. They cannot be edited
    # letter by letter: if event fields differ from the sample, replace the
    # complete information panel, leaving art and ticket border visible.
    sample_event=(event_title.upper()=='FESTIVAL DE NAVIDAD'
                  and day=='16/11/2026' and when=='19:00 H'
                  and place=='Casa de la Cultura · Arroyo de la Miel'
                  and event.get('mode')=='libre')
    if not sample_event:
        rectangle((.283,.292,.777,.828),'white')
        paint.rounded_rectangle((rx(.297),ry(.305),rx(.765),ry(.811)),
                 radius=max(3,round(.018*H)),
                 fill='white',outline='#a7b1c0',width=max(1,H//320))
        title(event_title,(.307,.318,.751,.464),40,accent)
        title(day+'     '+when,(.305,.478,.751,.570),27,accent)
        title(place,(.305,.580,.750,.655),23,accent)
        if event.get('mode')=='libre':
            notes=['SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA',
                   'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA']
        else:
            notes=['RESPETE SU FILA Y BUTACA ASIGNADAS',
                   'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA']
        title(notes[0],(.301,.668,.751,.730),16,accent)
        title(notes[1],(.301,.733,.751,.798),15,accent)
    if (header!='Escuela Municipal de Música y Danza'
            or subheader!='Arroyo de la Miel'):
        rectangle((.309,.05,.773,.27),'white')
        title(header,(.320,.060,.766,.172),29,accent)
        title(subheader,(.320,.173,.764,.253),20,accent)

    # IMPORTANT: remove the WHOLE demonstration right-hand strip, including
    # pre-printed false QR, captions, border and N.º 0001, before rendering
    # real ticket credentials. This prevents the double-code screenshot issue.
    rectangle((.784,.030,.979,.972),'white')
    paint.rounded_rectangle((rx(.798),ry(.053),rx(.965),ry(.148)),
                            radius=max(4,ry(.014)),fill='#132d53')
    title('CONTROL DE ACCESO',(.800,.065,.963,.140),22,'white')
    paint.rounded_rectangle((rx(.800),ry(.166),rx(.963),ry(.281)),
                            radius=max(4,ry(.012)),outline='#8294aa',
                            width=max(1,H//240),fill='#f9fafb')
    title(f"N.º {number:04d}",(.805,.173,.959,.272),29,accent)

    # The QR and Code128 are generated from CURRENT signed data, not from
    # the user's static reference photograph. Never scale after encoding.
    qr_box=(rx(.793),ry(.302),rx(.975),ry(.700))
    qr=_qr_image(str(ticket['qr']),
                 qr_box[2]-qr_box[0],qr_box[3]-qr_box[1])
    rectangle((.791,.300,.978,.705),'white')
    im.paste(qr,(qr_box[0]+(qr_box[2]-qr_box[0]-qr.width)//2,
                 qr_box[1]+(qr_box[3]-qr_box[1]-qr.height)//2))
    paint=ImageDraw.Draw(im)
    title('ESCANEAR QR',(.805,.710,.963,.767),17,accent)
    paint.line([(rx(.806),ry(.783)),(rx(.963),ry(.783))],
               fill='#adb8c8',width=max(1,H//330))
    seat=str(ticket.get('seat_label') or '').strip()
    title(seat if seat else '1 PERSONA',(.806,.793,.962,.901),26,accent)
    title('PROHIBIDA SU VENTA',(.807,.922,.960,.955),12,accent)

    # Entire bottom code strip is cleared. It must not show the previous JPG
    # barcode through empty gaps, or be covered by the admission notes.
    rectangle((.206,.834,.772,.979),'white')
    max_width=rx(.751)-rx(.225)
    code=_code128_image(barcode_ticket_value(ticket['id']),
                        max_width,max(20,ry(.956)-ry(.859)))
    im.paste(code,((rx(.206)+rx(.772)-code.width)//2,ry(.856)))

    if color_preview:return im
    return im.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG).convert('RGB')



def render_landscape_ticket(event: dict, ticket: dict, width_mm: int = 80,
                            design: dict | None = None, *, length_mm: int | None = None,
                            color_preview: bool=False) -> Image.Image:
    """Render idéntico para PDF y RAW ESC/POS. QR preservado a píxeles nativos."""
    design = design or {}
    blanco = design.get('modo_impresion', 'Normal') == 'Blanco económico'
    g = geometry(width_mm,length_mm,design)
    W,H,L,R,T,B = (g[x] for x in ('W','H','L','R','T','B'))
    divider,usable = g['divider'],g['usable']
    scale = g['sx']
    xunit = H/576.0
    sz = lambda n: max(1,round(n*scale))
    xu = lambda n: round(n*xunit)
    y = lambda n: T+round(n*scale)
    chosen=str(design.get('plantilla') or '')
    if chosen in CATALOG_INDEX:
        return render_reference_jpg_ticket(event,ticket,width_mm,design,
                                           length_mm,color_preview=color_preview)
    if chosen not in TEMPLATES:
        chosen = TEMPLATES[3] if design.get('poster_mode') == 'fondo' else TEMPLATES[0]
    kind=TEMPLATES.index(chosen)
    fit=design.get('ajuste_imagen',IMAGE_FITS[0])
    if fit not in IMAGE_FITS: fit=IMAGE_FITS[0]
    poster=_open_image(design.get('poster'))
    ayto=_open_image(design.get('logo_ayto'))
    centro=_open_image(design.get('logo_centro'))
    im=Image.new('RGB',(W,H),'white')
    draw=ImageDraw.Draw(im)
    stroke=max(1,sz(2))
    font_factor=_setting_number(design,'tamano_letra_pct',100,70,140)/100
    header_factor=_setting_number(design,'tamano_cabecera_pct',100,70,140)/100
    date_factor=_setting_number(design,'tamano_fecha_pct',100,70,140)/100
    def br(x0,y0,x1,y1):
        return (L+round(usable*x0/1000),y(y0),L+round(usable*x1/1000),y(y1))
    def text_box(txt,rect,size=33,*,bold=True,lines=2,min_size=11,color='black',factor=None):
        f=font_factor if factor is None else factor
        _center(ImageDraw.Draw(im),str(txt),rect,max(8,round(size*scale*f)),
                bold=bold,lines=lines,min_size=max(8,round(min_size*scale)),fill=color)
    def bodytext(txt,rect,size=33,*,lines=2,min_size=11,bold=True,color='black',factor=None):
        text_box(txt,br(*rect),size,bold=bold,lines=lines,min_size=min_size,color=color,factor=factor)
    def photo(rect,*,soften=0.0,frame=False):
        box=br(*rect)
        if poster is not None: _fitted(im,poster,box,fit,0.0 if blanco else soften,economy=blanco)
        if frame and poster is not None:
            draw.rectangle((box[0],box[1],box[2]-1,box[3]-1),outline='black',width=stroke)
    def hline(yy,xstart=0,xend=1000):
        draw.line((br(xstart,yy,xend,yy)[0],y(yy),br(xstart,yy,xend,yy)[2],y(yy)),fill='black',width=stroke)

    # La zona de seguridad queda blanca: no afecta a la distancia real hasta la cuchilla.
    draw.rectangle((L,y(6),W-g['right_limit'],y(569)),outline='black',width=stroke)
    draw.line((divider,y(9),divider,y(566)),fill='black',width=stroke)
    hline(117)

    # Posiciones de logos con áreas reservadas. Cada plantilla tiene una disposición inicial.
    requested = design.get('posicion_logos','Según plantilla')
    logo_pos = (DEFAULT_LOGO_POSITIONS[kind] if requested=='Según plantilla' else requested)
    # Evitar escudos diminutos encima de la cabecera en la vista por defecto.
    if requested=='Según plantilla' and logo_pos=='Centrados':
        logo_pos='Extremos'
    if logo_pos not in LOGO_POSITIONS:
        raise ValueError('Posición de logotipos no reconocida.')
    logo_setting=design.get('tamano_logos','Grandes')
    logo_w={'Pequeños':155,'Medianos':165,'Grandes':185}.get(logo_setting,185)
    # Coordenadas de encabezado en medidas relativas a su ancho, y en altura 0..117.
    def hx(rel): return L+round(usable*rel/1000)
    def logo_at(src,a,b,c,d):
        if src is not None:
            # Never let a logo invade the decorative frame (or overlap the cut zone).
            a=max(15,min(985,a));c=max(a+1,min(985,c))
            b=max(11,min(90,b));d=max(b+1,min(109,d))
            gray=ImageOps.grayscale(src)
            bounds=gray.point(lambda v: 255 if v<145 else 0).getbbox()
            artwork=src.crop(bounds) if bounds else src
            artwork=ImageOps.autocontrast(artwork,cutoff=1)
            _fitted(im,artwork,(hx(a),y(b),hx(c),y(d)),'Mostrar completa')
    title_box=(140,15,860,80)
    subtitle_box=(140,79,860,110)
    lw=min(185,max(80,round(logo_w*1000/max(usable,1)*xunit)))
    # ancho de logo expresado como fracción de encabezado; evita solapes en 58 mm
    lw=min(round(lw*1.16),225)
    if logo_pos=='Extremos':
        logo_at(ayto,24,11,24+lw,108)
        logo_at(centro,976-lw,11,976,108)
        title_box=(32+lw,14,967-lw,79)
        subtitle_box=(32+lw,78,967-lw,110)
    elif logo_pos=='Juntos a la izquierda':
        logo_at(ayto,10,5,10+lw,114)
        logo_at(centro,17+lw,12,17+lw*2,105)
        title_box=(35+lw*2,14,987,79)
        subtitle_box=(35+lw*2,78,987,110)
    elif logo_pos=='Juntos a la derecha':
        logo_at(ayto,983-lw*2,12,983-lw,105)
        logo_at(centro,990-lw,5,990,114)
        title_box=(13,14,962-lw*2,79)
        subtitle_box=(13,78,962-lw*2,110)
    elif logo_pos=='Apilados a la izquierda':
        logo_at(ayto,12,5,12+lw,57)
        logo_at(centro,12,60,12+lw,112)
        title_box=(27+lw,14,985,79)
        subtitle_box=(27+lw,78,985,110)
    elif logo_pos=='Apilados a la derecha':
        logo_at(ayto,988-lw,5,988,57)
        logo_at(centro,988-lw,60,988,112)
        title_box=(13,14,973-lw,79)
        subtitle_box=(13,78,973-lw,110)
    elif logo_pos=='Centrados':
        logo_at(ayto,330,5,485,61)
        logo_at(centro,515,5,670,61)
        title_box=(25,65,975,92)
        subtitle_box=(25,93,975,112)
    # Si no se facilitan logos no se reserva artificialmente espacio para su ancho.
    if ayto is None and centro is None:
        title_box=(12,14,988,79)
        subtitle_box=(12,78,988,110)
    text_box(design.get('cabecera') or 'Escuela Municipal de Música y Danza',
             br(*title_box),33,lines=2,min_size=12,factor=header_factor)
    text_box(design.get('subtitulo') or 'Arroyo de la Miel',
             br(*subtitle_box),22,lines=1,min_size=10,factor=header_factor)

    date=datetime.fromisoformat(str(event['start_time']))
    day=date.strftime('%d/%m/%Y')
    when=date.strftime('%H:%M H')
    label=str(event['name'])
    place=str(design.get('lugar') or 'Casa de la Cultura · Arroyo de la Miel')
    def event_text(x0,x1,*,title_y=(141,258),day_y=(266,336),time_y=(340,420),place_y=(423,482),title_sz=45):
        bodytext(label,(x0,title_y[0],x1,title_y[1]),title_sz,lines=3,min_size=14)
        bodytext(day,(x0,day_y[0],x1,day_y[1]),37,lines=1,min_size=14,factor=date_factor)
        bodytext(when,(x0,time_y[0],x1,time_y[1]),54,lines=1,min_size=17,factor=date_factor)
        bodytext(place,(x0,place_y[0],x1,place_y[1]),24,lines=2,min_size=10)
    selected_avisos=str(design.get('estilo_avisos','Según modelo'))
    avisos_compact=(selected_avisos in ('Según modelo','B · Recuadro','D · Separadores'))
    # Cuatro composiciones grises con foto y tipografía diseñadas a tamaño final.
    # En los estilos B/D no se achica el contenido después de dibujarlo.
    if kind==0:  # Clásico
        photo((5,127,384,481),frame=True)
        event_text(397 if poster else 12,991)
    elif kind==1:  # Cartel protagonista
        photo((5,126,530,481),frame=True)
        event_text(543 if poster else 12,991,title_sz=42)
    elif kind==2:  # Panorámico
        photo((6,125,994,315),frame=True)
        bodytext(label,(15,320,989,375),42,lines=2,min_size=15)
        bodytext(f'{day}   {when}',(15,378,988,434),37,lines=1,min_size=13,factor=date_factor)
        bodytext(place,(15,434,989,482),25,lines=2,min_size=11)
    elif kind==3:  # Fondo suave
        photo((6,124,994,484),soften=.84)
        bodytext(label,(30,140,970,273),50,lines=2,min_size=19)
        bodytext(day,(28,275,975,350),44,lines=1,min_size=18,factor=date_factor)
        bodytext(when,(28,348,975,421),58,lines=1,min_size=20,factor=date_factor)
        bar=br(36,437,965,482)
        draw.rectangle(bar,fill='white' if blanco else (207,207,207))
        text_box(place,bar,23,lines=1,min_size=11,color='black')
    elif kind==4:  # Editorial
        photo((604,126,995,481),frame=True)
        draw.rectangle(br(8,132,22,474),fill='white' if blanco else (207,207,207))
        event_text(37,588 if poster else 980,title_sz=47)
    elif kind==5:  # Mosaico
        photo((5,126,259,480),frame=True)
        photo((741,126,995,480),frame=True)
        event_text(266,733,title_sz=39)
    elif kind==6:  # Institucional: banda fotográfica inferior
        bodytext(label,(35,138,965,247),53,lines=2,min_size=17)
        bodytext(f'{day}   {when}',(45,250,955,308),38,lines=1,min_size=15,factor=date_factor)
        photo((25,312,975,442),frame=True)
        bodytext(place,(27,443,975,481),22,lines=1,min_size=12)
    elif kind==7:  # Escenario: fotografía a toda anchura con placa blanca para legibilidad
        photo((6,125,995,481),frame=False)
        box=br(270,150,975,463)
        draw.rectangle(box,fill='white',outline='black',width=stroke)
        event_text(290,955,title_y=(162,260),day_y=(263,322),time_y=(323,386),place_y=(388,449),title_sz=39)
    elif kind==8:  # Tríptico: tres cuadros y divisor
        photo((8,125,336,483),frame=True)
        draw.line((br(341,136,341,470)[0],y(136),br(341,136,341,470)[0],y(470)),fill='white' if blanco else (207,207,207),width=stroke)
        event_text(351,982,title_y=(131,239),day_y=(249,306),time_y=(313,399),place_y=(404,474),title_sz=47)
    elif kind==9:  # Minimalista
        photo((8,129,204,477))
        if poster:
            draw.line((br(215,134,215,470)[0],y(134),br(215,134,215,470)[0],y(470)),fill='white' if blanco else (207,207,207),width=stroke)
        event_text(225 if poster else 35,979,title_y=(152,257),day_y=(267,326),time_y=(337,411),place_y=(422,474),title_sz=51)
    elif kind==10:  # Institucional formal: imagen opcional fina a la izquierda
        photo((10,130,254,477))
        event_text(270 if poster else 32,968,title_y=(140,258),day_y=(267,326),time_y=(327,412),place_y=(419,470),title_sz=46)
        hline(130,260,987)
    elif kind==11:  # Ayuntamiento: fecha en una columna y cartel a la derecha
        bodytext(label,(28,140,990,234),53,lines=2,min_size=18)
        photo((612,235,991,472),frame=bool(poster))
        bodytext(day,(25,245,595,322),41,lines=1,factor=date_factor)
        bodytext(when,(25,332,595,405),51,lines=1,factor=date_factor)
        bodytext(place,(25,407,605,477),22,lines=2)
    elif kind==12:  # Auditorio clásico: formal sin cartel dominante
        draw.line((br(48,141,950,141)[0],y(141),br(48,141,950,141)[2],y(141)),fill='white' if blanco else (207,207,207),width=stroke)
        bodytext(label,(50,160,950,294),56,lines=3,min_size=19)
        bodytext(day+'     '+when,(55,310,945,380),37,lines=1,factor=date_factor)
        bodytext(place,(55,395,945,474),28,lines=2)
    elif kind==13:  # Programa cultural: poster alto y texto a la izquierda
        photo((672,135,981,475),frame=bool(poster))
        event_text(24,660,title_y=(155,263),day_y=(269,326),time_y=(334,401),place_y=(411,473),title_sz=46)
        draw.line((br(665,134,665,476)[0],y(134),br(665,134,665,476)[0],y(476)),fill='white' if blanco else (207,207,207),width=stroke)
    elif kind==14:  # Elegancia minimal: poster horizontal discreto
        photo((12,136,988,274))
        bodytext(label,(25,277,975,357),44,lines=2)
        bodytext(day+'   '+when,(25,361,975,424),40,lines=1,factor=date_factor)
        bodytext(place,(25,427,975,479),23,lines=2)
    elif kind==15:  # Plantilla 16: antes aparecía en blanco
        draw.rectangle(br(14,138,982,471),outline='black',width=stroke)
        if poster:
            photo((25,149,454,460),frame=True)
            event_text(473,965,title_sz=43)
        else:
            event_text(29,969,title_sz=51)
    elif kind==16:  # 23: Clásico tipográfico
        photo((10,135,987,472),soften=.94)
        hline(148,45,955)
        bodytext(label,(30,170,970,298),64,lines=2,min_size=18)
        hline(301,70,930)
        bodytext(day+'   |   '+when,(32,317,970,388),38,lines=1,factor=date_factor)
        bodytext(place,(45,400,956,474),27,lines=2)
    elif kind==17:  # 24: Danza, cabecera negra y composición en dos columnas
        draw.rectangle(br(5,125,995,173),fill='white' if blanco else (207,207,207))
        bodytext('DANZA', (35,127,965,172),32,color='black',lines=1)
        photo((8,179,438,475),soften=.44)
        if poster is None:
            # Movimiento de bailarinas representado mediante curvas y círculos
            for cx in (155,299):
                xx,yy=br(cx,236,cx,236)[:2]
                rr=sz(18)
                draw.ellipse((xx-rr,yy-rr,xx+rr,yy+rr),fill='white' if blanco else (207,207,207))
                draw.line((xx,yy+rr,xx-sz(18),y(371)),fill='white' if blanco else (207,207,207),width=sz(10))
                draw.line((xx-sz(18),y(371),xx-sz(80),y(436)),fill='white' if blanco else (207,207,207),width=sz(8))
                draw.line((xx-sz(18),y(371),xx+sz(60),y(418)),fill='white' if blanco else (207,207,207),width=sz(8))
                draw.line((xx,y(287),xx+sz(79),y(237)),fill='white' if blanco else (207,207,207),width=sz(6))
        draw.line((br(447,181,447,471)[0],y(181),br(447,181,447,471)[0],y(471)),fill='white' if blanco else (207,207,207),width=stroke)
        event_text(460,979,title_y=(184,290),day_y=(298,356),time_y=(355,416),place_y=(413,472),title_sz=49)
    elif kind==18:  # 25: fotografía principal y datos
        if poster:
            photo((12,133,480,475),frame=True)
            event_text(500,980,title_y=(142,275),day_y=(280,338),
                       time_y=(340,410),place_y=(414,474),title_sz=44)
        else:
            draw.rectangle(br(20,140,982,472),outline='black',width=stroke)
            event_text(35,970,title_sz=53)
    elif kind==19:  # 26: columnas limpias, sin círculos ni texto inventado
        for yy in (251,352):
            hline(yy,16,382)
        bodytext(day,(19,163,379,242),37,lines=1,factor=date_factor)
        bodytext(when,(19,267,379,345),51,lines=1,factor=date_factor)
        bodytext(place,(20,367,379,477),23,lines=3)
        draw.line((br(425,132,425,132)[0],y(132),
                   br(391,475,391,475)[0],y(475)),fill='white' if blanco else (207,207,207),width=sz(6))
        if poster:
            photo((447,135,980,298),frame=True)
            bodytext(label,(445,308,975,468),50,lines=3,min_size=16)
        else:
            bodytext(label,(450,162,973,447),55,lines=3,min_size=17)
    elif kind==20:  # 27: cartel y tipografía, sin puntos decorativos
        if poster:
            photo((18,133,980,333),frame=True)
            bodytext(label,(28,337,970,404),41,lines=2)
            bodytext(day+' · '+when,(30,407,970,446),30,lines=1,factor=date_factor)
            bodytext(place,(35,451,967,481),20,lines=1)
        else:
            draw.rectangle(br(65,155,930,311),outline='black',width=sz(4))
            bodytext(label,(80,170,912,294),55,lines=2)
            bodytext(day+' · '+when,(100,342,895,412),39,lines=1,factor=date_factor)
            bodytext(place,(110,418,889,470),26,lines=2)
    elif kind==21:  # 28: bloque lateral, foto visible
        draw.rectangle(br(12,138,311,470),fill='white' if blanco else (207,207,207))
        bodytext('ACCESO LIBRE' if event['mode']=='libre' else 'BUTACA ASIGNADA',
                 (25,194,295,344),31,lines=3,color='black')
        if poster:
            photo((335,134,982,298),frame=True)
            bodytext(label,(347,305,973,384),42,lines=2)
            bodytext(day+' · '+when,(347,390,974,438),28,lines=1,factor=date_factor)
            bodytext(place,(350,443,970,478),20,lines=1)
        else:
            event_text(340,974,title_sz=50)
    elif kind==22:  # 29: ornamental limpio
        draw.rectangle(br(17,137,979,475),outline='black',width=sz(3))
        if poster:
            photo((28,147,423,466),frame=True)
            event_text(441,970,title_sz=43)
        else:
            bodytext(label,(65,173,946,286),56,lines=2)
            hline(302,120,873)
            bodytext(day+' · '+when,(102,318,900,401),36,lines=1,factor=date_factor)
            bodytext(place,(105,408,895,467),25,lines=2)
    elif kind==23:  # 30: diagonal gris, fecha/hora en tamaño grande
        floor=347 if avisos_compact else 475
        draw.polygon([br(9,130,9,130)[:2],br(347,130,347,130)[:2],
                      br(279,floor,279,floor)[:2],br(9,floor,9,floor)[:2]],
                     fill='white' if blanco else (207,207,207))
        bodytext(day,(18,158,298,230),43,lines=1,factor=date_factor)
        bodytext(when,(18,235,283,326),56,lines=1,factor=date_factor)
        if poster:
            photo((359,134,985,266 if avisos_compact else 323),frame=True)
        bodytext(label,(364,269 if avisos_compact else 328,976,
                        315 if avisos_compact else 411),47,lines=2,min_size=15)
        bodytext(place,(363,315 if avisos_compact else 419,976,
                        346 if avisos_compact else 468),21,lines=2,min_size=11)
    elif kind==24:  # 31: bloque de fecha visible y cartel protagonista
        floor=347 if avisos_compact else 473
        draw.rectangle(br(13,137,309,floor),
                       fill='white' if blanco else (207,207,207))
        bodytext(day,(21,154,302,225),44,lines=1,factor=date_factor)
        bodytext(when,(20,232,302,323),57,lines=1,factor=date_factor)
        if poster:
            photo((327,136,983,270 if avisos_compact else 322),frame=True)
        bodytext(label,(333,274 if avisos_compact else 328,978,
                        317 if avisos_compact else 408),49,lines=2,min_size=15)
        bodytext(place,(333,319 if avisos_compact else 414,978,
                        345 if avisos_compact else 470),23,lines=2,min_size=11)
    elif kind==25:  # 32: diagonal, texto importante y cartel más ancho
        floor=347 if avisos_compact else 473
        draw.polygon([br(11,131,11,131)[:2],br(415,131,415,131)[:2],
                      br(317,floor,317,floor)[:2],br(11,floor,11,floor)[:2]],
                     fill='white' if blanco else (207,207,207))
        bodytext(day,(25,154,330,226),43,lines=1,factor=date_factor)
        bodytext(when,(21,233,318,322),55,lines=1,factor=date_factor)
        if poster:
            photo((425,134,983,267 if avisos_compact else 325),frame=True)
        bodytext(label,(431,270 if avisos_compact else 330,978,
                        316 if avisos_compact else 411),46,lines=2,min_size=14)
        bodytext(place,(433,317 if avisos_compact else 415,975,
                        345 if avisos_compact else 470),22,lines=2,min_size=10)
    elif kind==26:  # 33: columna con cartel protagonista
        if poster:
            photo((14,134,557,474),frame=True)
            event_text(573,976,title_sz=44)
        else:
            draw.rectangle(br(17,140,980,472),outline='black',width=stroke)
            event_text(23,975,title_sz=51)
    elif kind==27:  # 34: foto panorámica
        if poster:
            photo((14,137,983,324),frame=True)
        else:
            draw.rectangle(br(14,137,983,324),outline='black',width=stroke)
            bodytext(label,(35,157,955,304),55,lines=2)
        bodytext(label,(23,332,971,388),36,lines=2)
        bodytext(day+' · '+when,(24,394,969,442),31,lines=1,factor=date_factor)
        bodytext(place,(28,447,963,479),21,lines=1)
    elif kind==28:  # 35: lateral negro y cartel
        draw.rectangle(br(13,139,317,472),fill='white' if blanco else (207,207,207))
        bodytext('CONTROL DE ACCESO',(22,173,300,291),28,color='black',lines=3)
        bodytext(when,(23,344,299,440),42,color='black',lines=1,factor=date_factor)
        if poster:
            photo((339,134,984,303),frame=True)
            bodytext(label,(349,310,973,405),44,lines=2)
            bodytext(day+' · '+place,(348,413,975,472),23,lines=2)
        else:
            event_text(340,980,title_sz=47)
    elif kind==29:  # 36: geometría gris, fecha y hora destacadas
        floor=347 if avisos_compact else 473
        draw.polygon([br(12,130,12,130)[:2],br(355,130,355,130)[:2],
                      br(280,floor,280,floor)[:2],br(12,floor,12,floor)[:2]],
                     fill='white' if blanco else (207,207,207))
        bodytext(day,(20,156,305,225),42,lines=1,factor=date_factor)
        bodytext(when,(19,229,291,324),55,lines=1,factor=date_factor)
        if poster:
            photo((364,134,983,270 if avisos_compact else 326),frame=True)
        bodytext(label,(371,274 if avisos_compact else 330,977,
                        317 if avisos_compact else 408),48,lines=2,min_size=15)
        bodytext(place,(372,320 if avisos_compact else 414,975,
                        345 if avisos_compact else 471),22,lines=2,min_size=10)
    elif kind==30:  # 37: Columnas completamente blancas
        hline(255,12,385); hline(359,12,385)
        bodytext(day,(20,158,379,246),37,lines=1,factor=date_factor)
        bodytext(when,(20,271,379,353),53,lines=1,factor=date_factor)
        bodytext(place,(20,373,380,471),25,lines=3)
        draw.line((br(416,136,416,136)[0],y(136),br(397,470,397,470)[0],y(470)),fill=(160,160,160),width=sz(3))
        if poster:
            photo((439,140,979,294),frame=True)
            bodytext(label,(442,304,972,466),49,lines=3)
        else: bodytext(label,(440,160,972,453),55,lines=3)
    elif kind==31:  # 38: Diagonal de contorno, no bloque negro
        draw.line((br(360,133,360,133)[0],y(133),br(260,471,260,471)[0],y(471)),fill=(160,160,160),width=sz(4))
        bodytext(day,(21,165,301,246),34,lines=1,factor=date_factor)
        bodytext(when,(19,274,270,365),48,lines=1,factor=date_factor)
        if poster:
            photo((380,138,979,302),frame=True)
            bodytext(label,(383,308,970,408),44,lines=2)
            bodytext(place,(385,419,968,472),23,lines=2)
        else: event_text(365,975,title_sz=47)
    elif kind==32:  # 39: Cartel claro con columnas
        if poster: photo((17,137,454,464),frame=True)
        else: draw.rectangle(br(17,137,454,464),outline='black',width=stroke)
        hline(134,470,980)
        event_text(480,972,title_sz=46)
    elif kind==33:  # 40: Editorial blanco, cartel panorámico
        if poster: photo((18,136,981,306),frame=True)
        else: draw.rectangle(br(18,136,981,306),outline='black',width=stroke)
        bodytext(label,(25,317,970,380),46,lines=2)
        bodytext(day+'  ·  '+when,(24,386,973,440),33,lines=1,factor=date_factor)
        bodytext(place,(29,445,969,473),21,lines=1)
    elif kind==34:  # 41: Propuesta B, sin adorno que tape el texto
        bodytext(label,(25,141,974,236),51,lines=2,min_size=16)
        bodytext(day+'  ·  '+when,(25,242,972,292),40,lines=1,factor=date_factor)
        bodytext(place,(28,301,970,343),25,lines=2)
    elif kind==35:  # 42: Propuesta D, jerarquía sencilla
        bodytext(label,(24,141,975,233),53,lines=2,min_size=16)
        bodytext(day+'   '+when,(28,245,970,295),40,lines=1,factor=date_factor)
        bodytext(place,(28,305,970,345),25,lines=2)
    # Posición de los avisos independiente del diseño gráfico elegido:
    # se aplica a las 36 plantillas sin tapar textos, fotografías ni QR.
    setting=str(design.get('estilo_avisos','Según modelo'))
    if setting not in ('Según modelo','B · Recuadro','D · Separadores','Clásico'):
        setting='Según modelo'
    if setting=='Según modelo':
        avisos='D' if kind==35 else 'B'
    elif setting.startswith('B ·'):
        avisos='B'
    elif setting.startswith('D ·'):
        avisos='D'
    else:
        avisos='Clásico'
    if avisos in ('B','D') and kind not in (23,24,25,29,34,35):
        # Se comprime únicamente la composición del espectáculo. El encabezado,
        # el talón QR y el Code128 conservan sus dimensiones y píxeles.
        x0,x1=L+sz(3),divider-sz(4)
        old_top,old_bottom=y(125),y(486)
        new_bottom=y(347)
        artwork=im.crop((x0,old_top,x1,old_bottom))
        artwork=artwork.resize((x1-x0,new_bottom-old_top),Image.Resampling.LANCZOS)
        draw.rectangle((x0,old_top,x1-1,y(487)),fill='white')
        im.paste(artwork,(x0,old_top))
        draw.line((L+sz(5),y(350),divider-sz(6),y(350)),
                  fill=(185,185,185),width=stroke)
    if avisos=='Clásico':
        hline(490)
    if event['mode']=='libre':
        notes=('SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    else:
        notes=('RESPETE SU FILA Y BUTACA ASIGNADAS',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    if avisos=='B':  # Propuesta B en cualquier modelo
        border=br(15,353,984,476)
        draw.rounded_rectangle(border,radius=sz(9),outline=(125,125,125),width=stroke)
        draw.line((br(30,410,970,410)[0],y(410),br(30,410,970,410)[2],y(410)),
                  fill=(175,175,175),width=stroke)
        bodytext(notes[0],(28,360,972,406),22,lines=2,min_size=13)
        bodytext(notes[1],(30,414,969,471),20,lines=2,min_size=12)
    elif avisos=='D':  # Propuesta D en cualquier modelo
        for yy in (354,408,476): hline(yy,20,980)
        bodytext(notes[0],(35,361,961,403),22,lines=2,min_size=13)
        bodytext(notes[1],(35,414,961,471),20,lines=2,min_size=12)
    else:
        bodytext(notes[0],(15,489,985,505),16,lines=1,min_size=8)
        bodytext(notes[1],(15,507,985,523),15,lines=1,min_size=8)
    # Code128 ocupa una franja ancha del CUERPO PRINCIPAL, no el talón
    # estrecho del QR. La versión anterior comprimía cada barra a 1 píxel.
    # Aquí las barras son de 3-5 píxeles y permanecen sin interpolar.
    area_left,area_right=br(34,519,966,568)[0],br(34,519,966,568)[2]
    barcode_top=499 if avisos in ('B','D') else 531
    barcode_bottom=566 if avisos in ('B','D') else 567
    barcode=_code128_image(barcode_ticket_value(ticket['id']),
                           area_right-area_left,max(18,y(barcode_bottom)-y(barcode_top)))
    bar_x=(area_left+area_right-barcode.width)//2
    im.paste(barcode,(bar_x,y(barcode_top)))

    # Talón del QR inalterado; nunca interpolar el código.
    stub_left, stub_right = divider+xu(8), W-g['right_limit']-xu(4)
    _dash_line(ImageDraw.Draw(im),(stub_left,y(120),stub_right,y(172)),width=stroke,dash=max(4,xu(10)))
    text_box('CONTROL DE ACCESO',
             (stub_left+2,y(39),stub_right-2,y(100)),23,lines=2,min_size=11)
    text_box(f"N.º {int(ticket['number']):04d}",
             (stub_left+2,y(124),stub_right-2,y(168)),30,lines=1,min_size=12)
    # Priorizar módulos grandes incluso en papel térmico. Calcular el límite
    # teniendo en cuenta la caja real: nunca redimensionar una matriz QR.
    qy=y(182)
    qr_limit=y(420)-qy
    qr=_qr_image(ticket['qr'],stub_right-stub_left-xu(4),qr_limit)
    qx=(stub_left+stub_right-qr.width)//2
    im.paste(qr,(qx,qy))
    caption_y=qy+qr.height+sz(4)
    text_box('ESCANEAR QR',(stub_left,y(423),stub_right,y(443)),14,lines=1,min_size=9)
    text_box(ticket.get('seat_label') or 'ENTRADA LIBRE',
             (stub_left,y(451),stub_right,y(481)),16,lines=2,min_size=9)
    text_box('1 PERSONA',(stub_left,y(492),stub_right,y(531)),26,lines=1,min_size=13)
    text_box('PROHIBIDA SU VENTA',(stub_left,y(540),stub_right,y(563)),14,lines=1,min_size=9)
    return im.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG).convert('RGB')



def export_catalog_pdf(event: dict, ticket: dict, target: Path,
                       design: dict | None=None, templates=None,
                       *, width_mm: int=80, length_mm: int=135) -> Path:
    """A4, two actual ticket examples per row, model title and page numbering.

    Uses exactly the same ticket renderer as Windows printing, hence the same
    per-event QR/Code128 and no fake reference codes.
    """
    design=design or {}
    templates=tuple(templates if templates is not None else CATALOG_NAMES)
    if not templates:
        raise ValueError('Selecciona al menos un diseño del catálogo.')
    dest=Path(target)
    dest.parent.mkdir(parents=True,exist_ok=True)
    pdf=Canvas(str(dest),pagesize=A4)
    page_w,page_h=A4
    columns=2
    card_w=(page_w-64)/columns
    thumb_w=card_w-14
    thumb_h=thumb_w * 80/135
    card_h=thumb_h+32
    rows_per_page=max(1,int((page_h-80)//card_h))
    per_page=columns*rows_per_page
    pages=(len(templates)+per_page-1)//per_page
    for i,template in enumerate(templates):
        if i and i%per_page==0:
            pdf.showPage()
        pos=i%per_page
        row=pos//columns
        col=pos%columns
        x=29+col*card_w
        y=page_h-65-(row+1)*card_h
        if row==0:
            pdf.setFont('Helvetica-Bold',13)
            pdf.drawString(30,page_h-29,'CATALOGO DE ENTRADAS - MUESTRAS DE IMPRESION')
            pdf.setFont('Helvetica',9)
            pdf.drawRightString(page_w-30,page_h-29,
                                f'Pagina {i//per_page+1} de {pages}')
        spec=dict(design)
        spec['plantilla']=template
        im=render_landscape_ticket(event,ticket,width_mm,spec,
                                   length_mm=length_mm,color_preview=True)
        pdf.setFont('Helvetica-Bold',9)
        safe=template.encode('latin-1','replace').decode('latin-1')
        pdf.drawString(x+2,y+thumb_h+9,safe[:56])
        pdf.drawImage(ImageReader(im),x+2,y,
                      width=thumb_w,height=thumb_h,
                      preserveAspectRatio=True,anchor='c')
        pdf.setStrokeColorRGB(.78,.78,.78)
        pdf.rect(x,y-2,thumb_w+4,thumb_h+4,stroke=1,fill=0)
    pdf.save()
    return dest

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


CUT_MODES=('Manual (avance ajustable)', 'Automático genérico (GS V 65)', 'ZYWELL compatible (GS V 66)')


def _escpos_bytes(im: Image.Image, cut: bool=False, *, full_cut: bool=True,
                   feed_dots: int=240, cut_mode: str = CUT_MODES[0], reset: bool=True) -> bytes:
    '''Convierte la imagen a raster ESC/POS, y corta SOLO despues de emitir toda la imagen.

    No usar GS V 65 como supuesto universal: el manual de la serie ZYWELL
    POS-80XX documenta GS V 66 0 (corte parcial con avance a la cuchilla),
    pero no GS V 65. Otros modelos pueden diferir.
    '''
    if not (0 <= int(feed_dots) <= 800):
        raise ValueError('Avance entre 0 y 800 puntos.')
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
    if cut and cut_mode == CUT_MODES[2]:
        # Modo documentado por ZYWELL POS-80XX; corte parcial,
        # independientemente del flag de corte completo del driver.
        stream += b'\x1d\x56\x42\x00'
    elif cut and cut_mode == CUT_MODES[1]:
        # GS V 65/66 n=0: la impresora avanza hasta su propia posición
        # de corte y corta, si esta variante del firmware está soportada.
        stream += b'\x1d\x56' + (b'\x41' if full_cut else b'\x42') + b'\x00'
    else:
        # ESC J n admite n<=255; dividir para avances grandes con seguridad.
        remaining = int(feed_dots)
        while remaining:
            step = min(remaining, 255)
            stream += b'\x1b\x4a' + bytes([step])
            remaining -= step
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
                         cut: bool=True, *, full_cut=True, feed_dots: int=240,
                         cut_mode: str = CUT_MODES[0], length_mm: int|None=None):
    image=render_ticket(event,ticket,width_mm,design,length_mm=length_mm)
    raw=_escpos_bytes(image,cut=cut,full_cut=full_cut,feed_dots=feed_dots,cut_mode=cut_mode)
    return send_raw(printer_name,raw,f'Entrada {int(ticket["number"]):04d} - {event["name"][:25]}')



def print_cut_calibration(printer_name: str, paper_mm: int=80,
                          *, cut_mode: str=CUT_MODES[2], feed_dots: int=240):
    """Imprime una tira de calibración SIN QR ni números de entrada.

    Cinco bandas espaciadas en la dirección de avance permiten observar si
    el controlador o la cuchilla están ignorando el final del raster. Se usa
    una única secuencia RAW, sin reinicios intermedios.
    """
    if paper_mm not in PRINTABLE_DOTS:
        raise ValueError('Rollo 58 u 80 mm.')
    w = PRINTABLE_DOTS[paper_mm]
    h = 400
    img = Image.new('RGB', (w, h), 'white')
    d = ImageDraw.Draw(img)
    for y in (12, 100, 188, 276, 364):
        d.line((20, y, w-21, y), fill='black', width=3)
        d.text((23, y+7), f'CALIBRACION {y} puntos',font=font(20, True),fill='black')
    d.rectangle((9, 5, w-10, h-8),outline='black',width=2)
    raw = _escpos_bytes(img, cut=True, cut_mode=cut_mode,
                        feed_dots=feed_dots, full_cut=False)
    return send_raw(printer_name, raw, 'Prueba ZYWELL - NO ES ENTRADA')


def test_cutter(printer_name: str, *, full_cut: bool=True):
    """Prueba separada y confirmada desde la UI. No imprime ningun QR."""
    from PIL import Image
    # Unos 12 mm de avance y comando cutter; no imprimir para reducir residuos.
    raw=b'\x1b\x40\x1b\x4a\x60\x1d\x56'+(b'\x00' if full_cut else b'\x01')
    return send_raw(printer_name,raw,'TEST cortador ESC/POS')


def print_windows_escpos_batch(pairs, printer_name: str, width_mm: int=80, design: dict|None=None,
                              cut: bool=True, *, full_cut: bool=True, feed_dots: int=240,
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