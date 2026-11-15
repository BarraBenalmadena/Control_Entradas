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
    '07 · Institucional',
    '08 · Escenario',
    '09 · Tríptico',
    '10 · Minimalista',
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
)



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
    stub = round(224 * H/576)
    divider = W-right_limit-stub
    R = divider-round(8*H/576)
    usable = R-L
    if usable < round(550*H/576):
        raise ValueError('No cabe el contenido: reduce márgenes o aumenta el largo del ticket.')
    return dict(W=W,H=H,L=L,R=R,T=T,B=B,divider=divider,right_limit=right_limit,
                sx=sx,usable=usable,stub=stub)


def render_landscape_ticket(event: dict, ticket: dict, width_mm: int = 80,
                            design: dict | None = None, *, length_mm: int | None = None) -> Image.Image:
    """Render idéntico para PDF y RAW ESC/POS. QR preservado a píxeles nativos."""
    design = design or {}
    g = geometry(width_mm,length_mm,design)
    W,H,L,R,T,B = (g[x] for x in ('W','H','L','R','T','B'))
    divider,usable = g['divider'],g['usable']
    scale = g['sx']
    xunit = H/576.0
    sz = lambda n: max(1,round(n*scale))
    xu = lambda n: round(n*xunit)
    y = lambda n: T+round(n*scale)
    chosen=str(design.get('plantilla') or '')
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
        if poster is not None: _fitted(im,poster,box,fit,soften)
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
    if logo_pos not in LOGO_POSITIONS:
        raise ValueError('Posición de logotipos no reconocida.')
    logo_setting=design.get('tamano_logos','Grandes')
    logo_w={'Pequeños':90,'Medianos':113,'Grandes':145}.get(logo_setting,113)
    # Coordenadas de encabezado en medidas relativas a su ancho, y en altura 0..117.
    def hx(rel): return L+round(usable*rel/1000)
    def logo_at(src,a,b,c,d):
        if src is not None:
            _fitted(im,src,(hx(a),y(b),hx(c),y(d)),'Mostrar completa')
    title_box=(140,15,860,80)
    subtitle_box=(140,79,860,110)
    lw=min(185,max(80,round(logo_w*1000/max(usable,1)*xunit)))
    # ancho de logo expresado como fracción de encabezado; evita solapes en 58 mm
    lw=min(lw,165)
    if logo_pos=='Extremos':
        logo_at(ayto,10,12,10+lw,105)
        logo_at(centro,990-lw,12,990,105)
        title_box=(20+lw,14,980-lw,79)
        subtitle_box=(20+lw,78,980-lw,110)
    elif logo_pos=='Juntos a la izquierda':
        logo_at(ayto,10,12,10+lw,105)
        logo_at(centro,17+lw,12,17+lw*2,105)
        title_box=(35+lw*2,14,987,79)
        subtitle_box=(35+lw*2,78,987,110)
    elif logo_pos=='Juntos a la derecha':
        logo_at(ayto,983-lw*2,12,983-lw,105)
        logo_at(centro,990-lw,12,990,105)
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
        title_box=(25,62,975,93)
        subtitle_box=(25,92,975,113)
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
        draw.rectangle(bar,fill='black')
        text_box(place,bar,23,lines=1,min_size=11,color='white')
    elif kind==4:  # Editorial
        photo((604,126,995,481),frame=True)
        draw.rectangle(br(8,132,22,474),fill='black')
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
        draw.line((br(341,136,341,470)[0],y(136),br(341,136,341,470)[0],y(470)),fill='black',width=stroke)
        event_text(351,982,title_y=(131,239),day_y=(249,306),time_y=(313,399),place_y=(404,474),title_sz=47)
    else:  # 10 Minimalista: imagen estrecha, texto amplio, líneas finas
        photo((8,129,204,477))
        if poster:
            draw.line((br(215,134,215,470)[0],y(134),br(215,134,215,470)[0],y(470)),fill='black',width=stroke)
        event_text(225 if poster else 35,979,title_y=(152,257),day_y=(267,326),time_y=(337,411),place_y=(422,474),title_sz=51)
    hline(490)
    if event['mode']=='libre':
        notes=('SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    else:
        notes=('RESPETE SU FILA Y BUTACA ASIGNADAS',
               'SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA')
    bodytext(notes[0],(10,495,990,524),17,lines=1,min_size=9)
    bodytext(notes[1],(10,525,990,558),16,lines=1,min_size=9)

    # Talón del QR inalterado; nunca interpolar el código.
    stub_left, stub_right = divider+xu(8), W-g['right_limit']-xu(4)
    _dash_line(ImageDraw.Draw(im),(stub_left,y(125),stub_right,y(201)),width=stroke,dash=max(4,xu(10)))
    text_box(f"N.º {int(ticket['number']):04d}",
             (stub_left+2,y(130),stub_right-2,y(190)),30,lines=1,min_size=12)
    qr=_qr_image(ticket['qr'])
    if qr.width > stub_right-stub_left-xu(2):
        raise ValueError('QR demasiado ancho. Prueba un rollo de 80 mm.')
    qx=(stub_left+stub_right-qr.width)//2
    qy=y(207)
    if qy+qr.height>y(452):
        raise ValueError('El QR no cabe con estos márgenes verticales; redúcelos.')
    im.paste(qr,(qx,qy))
    caption_y=qy+qr.height+sz(6)
    text_box('ESCANEAR QR',(stub_left,caption_y,stub_right,caption_y+sz(26)),17,lines=1,min_size=9)
    caption_y+=sz(27)
    text_box(ticket.get('seat_label') or 'ENTRADA LIBRE',
             (stub_left,caption_y,stub_right,caption_y+sz(43)),16,lines=2,min_size=9)
    text_box('1 PERSONA',(stub_left,y(473),stub_right,y(514)),25,lines=1,min_size=12)
    text_box('PROHIBIDA SU VENTA',(stub_left,y(534),stub_right,y(562)),15,lines=1,min_size=9)
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