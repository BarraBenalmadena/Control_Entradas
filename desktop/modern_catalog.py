"""Thirty native, editable ticket designs based on the supplied visual proposals.
Each entry's QR/Code128 is generated from its own signed unique ticket data.
Only decorative art is image-based; text, number and optical codes are layers.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import sys
import os
import io
from zipfile import ZipFile
from PIL import Image, ImageDraw, ImageOps, ImageColor

NAMES=["Violín navideño","Bola de Navidad","Clave dorada","Telón teatral","Ballet acuarela","Elegancia musical","Micrófono dorado","Fachada iluminada","Música en acuarela","Danza azul","Ballet rosado","Gala con telón","Concierto en escena","Coro infantil","Geometría azul","Navidad dorada","Pueblo nevado","Árbol institucional","Danza moderna","Piano clásico","Belén estrellado","Violín de concierto","Bastón navideño","Municipal bicolor","Farol de invierno","Coral azul","Máscaras de teatro","Arquitectura azul","Flor de Pascua","Sinfonía dorada"]
COLORS=["#81301f","#ba2430","#69417e","#592521","#9d487c","#9e7b3a","#823533","#1e577b","#ac3c88","#0967ac","#a24c93","#9c2437","#2b5795","#a72c37","#2764a0","#98713f","#2b538b","#1f6541","#9f347d","#80552c","#1d355e","#9d5730","#b22935","#173f76","#9a6a34","#256797","#8d293b","#3c81b2","#9d2a35","#96732d"]
MODELS=tuple(f"{i:02d} · {NAMES[i-1]}" for i in range(1,31))
INDEX={name:i for i,name in enumerate(MODELS,1)}

def asset_dir():
    """El catálogo importado persiste en Documentos, fuera del EXE."""
    root=Path(os.environ.get('CONTROL_ENTRADAS_DATA') or
              Path.home()/'Documents'/'ControlEntradas')
    places=(root/'catalogo_nuevo',
            Path(sys.executable).resolve().parent/'catalogo_nuevo',
            Path(__file__).resolve().parent/'catalogo_nuevo')
    return next((p for p in places if p.is_dir()),places[0])


def art_path(i):
    folder=asset_dir()
    p=folder/f'art_{i:02d}.jpg'
    if p.is_file():return p
    # Ocho fotografías originales importadas, repartidas entre 30
    # composiciones gráficas distintas sin duplicar archivos.
    if i>8:
        shared=folder/f'art_{(i-1)%8+1:02d}.jpg'
        if shared.is_file():return shared
    raise FileNotFoundError(
        f'Falta art_{i:02d}.jpg. Pulsa «IMPORTAR IMÁGENES DEL WORD» en la galería.')


def install_reference_docx(filename):
    """Importa solo el motivo artístico izquierdo de las 8 muestras Word.

    Descarta expresamente el QR, código de barras, número y texto impresos
    en la muestra; el generador crea códigos válidos nuevos para cada entrada.
    """
    filename=Path(filename)
    if filename.suffix.lower()!='.docx':
        raise ValueError('Selecciona el documento Word de ocho diseños (.docx).')
    destination=Path(os.environ.get('CONTROL_ENTRADAS_DATA') or
                     Path.home()/'Documents'/'ControlEntradas')/'catalogo_nuevo'
    # Orden artístico visual para los primeros ocho modelos del catálogo.
    samples=(4,3,1,6,2,5,8,7)
    illustrations=[]
    municipal_crest=None
    with ZipFile(filename) as word:
        for index,source_num in enumerate(samples,1):
            member=f'word/media/image{source_num}.png'
            try:
                raw=word.read(member)
            except KeyError as exc:
                raise ValueError(f'El documento no contiene {member}.') from exc
            if len(raw)>12_000_000:
                raise ValueError('La imagen del Word supera el tamaño permitido.')
            with Image.open(io.BytesIO(raw)) as source:
                photo=ImageOps.exif_transpose(source).convert('RGB')
            w,h=photo.size
            if source_num==4:
                # Escudo municipal sin la inscripción lateral: referencia
                # aportada por el usuario en el encabezado del diseño 4.
                municipal_crest=photo.crop(
                    (round(w*.316),round(h*.045),
                     round(w*.372),round(h*.251)))
            # Las cuatro muestras superiores son entradas completas; las
            # cuatro siguientes tienen margen alrededor del ticket.
            top=.035 if source_num<=4 else .15
            bottom=.94 if source_num<=4 else .88
            right=.24 if source_num<=4 else .26
            region=photo.crop((round(w*.016),round(h*top),
                               round(w*right),round(h*bottom)))
            # Mantener aspecto original: el lienzo del modelo lo adapta
            # únicamente al panel fotográfico, nunca al texto ni al QR.
            illustrations.append(region)
    destination.mkdir(parents=True,exist_ok=True)
    for index,region in enumerate(illustrations,1):
        path=destination/f'art_{index:02d}.jpg'
        region.save(path,'JPEG',quality=92,optimize=True)
    if municipal_crest is not None:
        municipal_crest.save(destination/'escudo_benalmadena.png','PNG')
    return len(illustrations)


def _fallback_poster(idx, color):
    """Ilustración vectorial de seguridad cuando no se distribuyó un JPG.

    Nunca utiliza un QR, título ni número de ejemplo: solo decoración.
    El cartel real cargado por el usuario siempre tiene prioridad.
    """
    rgb = ImageColor.getrgb(color)
    image = Image.new('RGB', (340, 700), '#172b40')
    artist = ImageDraw.Draw(image)
    for y in range(image.height):
        blend = y / max(1, image.height - 1)
        artist.line((0, y, image.width, y),
            fill=tuple(min(255, int(v*(.67 + .2*blend) + 25)) for v in rgb))
    for i in range(4):
        offset = (idx*23 + i*41) % 100
        artist.arc((-170+offset, -90+i*135, 370+offset, 510+i*135),
            start=200, end=345, fill=(235,221,190), width=4)
    for i in range(5):
        y = 160 + i*26
        artist.line((45, y, 315, y), fill=(235,221,190), width=2)
    for i in range(3):
        cx, cy = (85+i*84, 340+(idx+i*47)%140)
        artist.ellipse((cx-17,cy-11,cx+17,cy+11),fill='#fff3d5')
        artist.line((cx+17,cy,cx+17,cy-104),fill='#fff3d5',width=8)
        if i%2==0:
            artist.arc((cx+12,cy-145,cx+90,cy-95),0,145,fill='#fff3d5',width=8)
    return image


def render(event,ticket,width_mm,design,length_mm,color_preview=False):
    import ticket_printer as tp
    idx=INDEX[str(design['plantilla'])]
    color=COLORS[idx-1]
    g=tp.geometry(width_mm,length_mm,design)
    W,H=g['W'],g['H']
    sx=W/1080.0
    sy=H/576.0
    X=lambda n:round(n*sx)
    Y=lambda n:round(n*sy)
    im=Image.new('RGB',(W,H),'white')
    dr=ImageDraw.Draw(im)
    dark=(idx-1)%8 in (3,6)
    # True original-inspired identity: 30 distinct illustration panels and
    # decorative palettes, WITHOUT the sample JPG's fake serial/QR/text.
    dr.rectangle((X(6),Y(6),W-X(7),H-Y(7)),outline=color,width=max(1,Y(4)))
    dr.rectangle((X(12),Y(12),X(267),H-Y(13)),fill='#eeeeee')
    poster=tp._open_image(design.get('poster'))
    if poster is None:
        try:
            with Image.open(art_path(idx)) as f:
                poster=f.convert('RGB')
        except (OSError, ValueError, FileNotFoundError):
            # La galería y la exportación PDF deben funcionar aun sin
            # la carpeta externa catalogo_nuevo en el EXE.
            poster=_fallback_poster(idx, color)
    # Art is independently pannable; all transformations stay inside its
    # allocated slot and never touch the independently encoded QR/Code128.
    zoom=tp._setting_number(design,'foto_zoom_pct',100,60,250)/100.
    fx=tp._setting_number(design,'foto_centro_x_pct',50,0,100)/100.
    fy=tp._setting_number(design,'foto_centro_y_pct',50,0,100)/100.
    fit=str(design.get('ajuste_imagen','Rellenar y recortar'))
    art_w,art_h=X(258),H-Y(26)
    if fit=='Mostrar completa':
        foundation=ImageOps.contain(poster,(max(1,int(art_w*zoom)),
                                            max(1,int(art_h*zoom))),
                                     method=Image.Resampling.LANCZOS)
        canvas=Image.new('RGB',(art_w,art_h),'white')
        posx=round((art_w-foundation.width)*fx)
        posy=round((art_h-foundation.height)*fy)
        canvas.paste(foundation,(posx,posy))
        artwork=canvas
    else:
        desired_w=max(1,round(art_w*zoom))
        desired_h=max(1,round(art_h*zoom))
        if zoom>=1:
            enlarged=ImageOps.fit(poster,(desired_w,desired_h),
                  method=Image.Resampling.LANCZOS,centering=(fx,fy))
            left=round((desired_w-art_w)*fx)
            top=round((desired_h-art_h)*fy)
            artwork=enlarged.crop((left,top,left+art_w,top+art_h))
        else:
            small=ImageOps.fit(poster,(desired_w,desired_h),
                  method=Image.Resampling.LANCZOS,centering=(fx,fy))
            artwork=Image.new('RGB',(art_w,art_h),'white')
            artwork.paste(small,(round((art_w-desired_w)*fx),
                                 round((art_h-desired_h)*fy)))
    # Eight original composition masks, matching diagonal, triangular, curved and theatre reference styles.
    # The image panel is separately masked; the design decoration remains.
    mask=Image.new('L',(art_w,art_h),0)
    md=ImageDraw.Draw(mask)
    variant=(idx-1)%8
    if variant==0:  # diagonal
        md.polygon([(0,0),(art_w,0),(round(.82*art_w),art_h),
                    (0,art_h)],fill=255)
    elif variant==1:  # curved edge
        md.ellipse((-art_w,round(-.13*art_h),
                    round(1.73*art_w),round(1.2*art_h)),fill=255)
    elif variant==2:  # stepped geometric
        md.polygon([(0,0),(art_w,0),(round(.88*art_w),round(.32*art_h)),
                    (art_w,round(.58*art_h)),(round(.66*art_w),art_h),
                    (0,art_h)],fill=255)
    elif variant==3:  # theatrical arc
        md.polygon([(0,0),(art_w,0),(round(.68*art_w),round(.16*art_h)),
                    (round(.87*art_w),round(.48*art_h)),
                    (round(.7*art_w),round(.84*art_h)),
                    (art_w,art_h),(0,art_h)],fill=255)
    elif variant==4:  # rounded angled frame
        md.rounded_rectangle((0,0,art_w-2,art_h-2),
                             radius=Y(68),fill=255)
    elif variant==5:  # double-angle
        md.polygon([(0,0),(round(.83*art_w),0),(art_w,round(.46*art_h)),
                    (round(.77*art_w),art_h),(0,art_h)],fill=255)
    elif variant==6:  # large triangular corner
        md.polygon([(0,0),(art_w,0),(round(.61*art_w),round(.44*art_h)),
                    (round(.82*art_w),art_h),(0,art_h)],fill=255)
    else:  # wide theatrical curved cutout
        md.polygon([(0,0),(art_w,0),(round(.84*art_w),round(.20*art_h)),
                    (round(.96*art_w),round(.51*art_h)),
                    (round(.68*art_w),round(.79*art_h)),
                    (art_w,art_h),(0,art_h)],fill=255)
    im.paste(artwork,(X(13),Y(13)),mask)
    dr=ImageDraw.Draw(im)
    borders=[((247,15),(224,558)),((258,16),(234,554)),
             ((252,18),(234,207),(261,341),(216,555)),
             ((265,17),(193,105),(254,286),(192,458),(251,555)),
             ((224,15),(257,95),(254,455),(224,557)),
             ((223,17),(267,276),(213,557)),
             ((268,16),(176,265),(239,556)),
             ((225,16),(264,99),(226,280),(249,430),(208,556))]
    dr.line([(X(a),Y(b)) for a,b in borders[variant]],
            fill=color,width=max(2,Y(4)),joint='curve')
    # Ocho familias visuales del ejemplo Word, no treinta cambios de color
    # sobre un mismo rectángulo. El texto permanece editable.
    title_fill=color if dark else '#ffffff'
    dr.rounded_rectangle((X(286),Y(124),X(796),Y(243)),
        radius=Y(11),fill=title_fill,outline=color,width=max(1,Y(2)))
    if variant==0:  # violin: dos líneas finas y esquina diagonal
        dr.line((X(300),Y(130),X(780),Y(130)),fill=color,width=max(1,Y(3)))
    elif variant==1:  # navidad dorada: marco doble
        dr.rounded_rectangle((X(293),Y(130),X(789),Y(237)),
            radius=Y(8),outline=color,width=max(1,Y(2)))
    elif variant==2:  # curva azul bajo el titular
        dr.arc((X(299),Y(197),X(788),Y(260)),0,180,
            fill=color,width=max(1,Y(3)))
    elif variant==3:  # panel teatral intenso
        dr.line((X(308),Y(134),X(776),Y(134)),fill='#ffe5ae',width=max(1,Y(3)))
        dr.line((X(308),Y(234),X(776),Y(234)),fill='#ffe5ae',width=max(1,Y(3)))
    elif variant==4:  # pentagrama sutil
        for yy in (131,137,143):
            dr.line((X(306),Y(yy),X(778),Y(yy)),fill='#d7dce3',width=1)
    elif variant==5:  # marco dorado doble
        dr.line((X(303),Y(133),X(777),Y(133)),fill=color,width=max(1,Y(4)))
        dr.line((X(303),Y(234),X(777),Y(234)),fill=color,width=max(1,Y(4)))
    elif variant==6:  # gran cartela de gala
        dr.rounded_rectangle((X(295),Y(133),X(787),Y(234)),
            radius=Y(9),outline='#eed9a2',width=max(2,Y(3)))
    else:  # esquina gráfica
        dr.polygon([(X(287),Y(124)),(X(337),Y(124)),(X(287),Y(174))],
            fill=color)
        dr.polygon([(X(796),Y(193)),(X(796),Y(243)),(X(746),Y(243))],
            fill=color)
    font_factor=tp._setting_number(design,'tamano_letra_pct',100,70,140)/100.
    header_factor=tp._setting_number(design,'tamano_cabecera_pct',100,70,140)/100.
    date_factor=tp._setting_number(design,'tamano_fecha_pct',100,70,140)/100.
    def center(t,rect,size=29,fg='#14273d',lines=2,bold=True,mini=12,factor=None):
        actual_factor=font_factor if factor is None else factor
        tp._center(ImageDraw.Draw(im),str(t),
            (X(rect[0]),Y(rect[1]),X(rect[2]),Y(rect[3])),
            size=max(8,Y(size*actual_factor)),bold=bold,lines=lines,
            min_size=max(7,Y(mini)),fill=fg)
    def open_logo(path):
        if not path:return None
        try:
            with Image.open(path) as src:
                # Crucial: preserve PNG alpha. Converting to RGB first makes
                # transparent user logos render as black rectangular stickers.
                return ImageOps.exif_transpose(src).convert('RGBA')
        except (OSError,ValueError):
            return None
    ayto=open_logo(design.get('logo_ayto'))
    centro=open_logo(design.get('logo_centro'))
    def draw_logo(source,coords):
        # Crop excess transparent/pale margins before fitting a horizontal
        # Education logo; preserve color and aspect, never distort.
        img=source.convert('RGBA')
        a=img.getchannel('A')
        bounds=a.point(lambda v:255 if v>15 else 0).getbbox()
        if bounds is not None:img=img.crop(bounds)
        desired=(max(1,X(coords[2]-coords[0])),
                 max(1,Y(coords[3]-coords[1])))
        contained=ImageOps.contain(img,desired,Image.Resampling.LANCZOS)
        px=X(coords[0])+(desired[0]-contained.width)//2
        py=Y(coords[1])+(desired[1]-contained.height)//2
        im.paste(contained,(px,py),contained)
    header=str(design.get('cabecera') or 'Escuela Municipal de Música y Danza')
    subtitle=str(design.get('subtitulo') or 'Arroyo de la Miel')
    logo_position=str(design.get('posicion_logos','Según plantilla'))
    logo_setting=str(design.get('tamano_logos','Pequeños'))
    crest_w={'Pequeños':52,'Medianos':62,'Grandes':72}.get(logo_setting,52)
    crest_mode=str(design.get('estilo_escudo','Solo escudo'))
    text_left=283+crest_w+12
    if ayto is not None:
        wide=ayto.width>ayto.height*1.6
        if crest_mode=='Logo completo' and wide:
            # Alternativa explícita: mantener el logo panorámico entero.
            draw_logo(ayto,(283,17,522,108))
            text_left=533
        else:
            emblem=ayto
            # Los logos horizontales suelen llevar escudo + leyenda;
            # el modo predeterminado usa solo el motivo del escudo.
            if wide:
                emblem=emblem.crop((0,0,max(1,round(emblem.width*.28)),emblem.height))
            draw_logo(emblem,(283,17,283+crest_w,108))
    else:
        center('AYTO.',(281,46,281+crest_w,84),17,color,1,mini=10)
    right=792
    if centro is not None:
        right=746
        draw_logo(centro,(750,20,795,105))
    # La anchura libre se dedica a texto, nunca a un hueco vacío de logo.
    center(header,(text_left,18,right,78),29,'#152b47',
           lines=2,mini=15,factor=header_factor)
    center(subtitle,(text_left,80,right,111),20,color,
           lines=1,mini=12,factor=header_factor)
    d=datetime.fromisoformat(str(event['start_time']))
    center(str(event['name']),(296,137,791,235),57,
           '#ffffff' if dark else color,lines=2,mini=21)
    date=d.strftime('%d/%m/%Y')
    time=d.strftime('%H:%M H')
    dr=ImageDraw.Draw(im)
    dr.rounded_rectangle((X(296),Y(255),X(778),Y(322)),
        radius=Y(9),fill='#f1f4fa',outline=color,width=max(1,Y(2)))
    dr.line((X(538),Y(263),X(538),Y(314)),
            fill=color,width=max(1,Y(2)))
    center(date,(303,265,531,315),37,'#132840',1,mini=18,factor=date_factor)
    center(time,(545,265,770,315),38,'#132840',1,mini=18,factor=date_factor)
    place=str(design.get('lugar') or 'Casa de la Cultura · Arroyo de la Miel')
    dr.rounded_rectangle((X(295),Y(336),X(780),Y(378)),
                         radius=Y(10),fill=color)
    center(place,(301,337,779,379),26,'white',lines=2,mini=12)
    no_seats=event.get('mode')=='libre'
    first=('SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA'
           if no_seats else 'RESPETE SU FILA Y BUTACA ASIGNADAS')
    second='SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA'
    dr.rounded_rectangle((X(291),Y(391),X(785),Y(474)),
                         radius=Y(8),fill='white',outline=color,
                         width=max(1,Y(2)))
    dr.line((X(305),Y(433),X(773),Y(433)),
            fill='#c9cdd4',width=max(1,Y(1)))
    center(first,(302,395,775,429),19,'#172943',lines=2,mini=9)
    center(second,(302,438,775,471),16,'#172943',lines=2,mini=9)
    # Live, authenticated Code128. Preserve native module pixels.
    code=tp._code128_image(tp.barcode_ticket_value(ticket['id']),
                           X(506),max(22,Y(63)))
    dx=(X(291)+X(784)-code.width)//2
    im.paste(code,(dx,Y(493)))
    # Separate right access stub: opaque white and independent of artwork.
    dr=ImageDraw.Draw(im)
    dr.rectangle((X(810),Y(14),W-X(15),H-Y(14)),fill='white')
    dr.line((X(810),Y(18),X(810),H-Y(18)),
            fill=color,width=max(1,Y(3)))
    dr.rounded_rectangle((X(828),Y(27),X(1054),Y(82)),
                         radius=Y(8),fill=color)
    center('CONTROL DE ACCESO',(835,34,1046,77),23,'white',lines=2,mini=11)
    dr.rounded_rectangle((X(840),Y(100),X(1044),Y(160)),
                         radius=Y(7),outline=color,
                         width=max(1,Y(2)),fill='white')
    center(f"N.º {int(ticket['number']):04d}",(846,108,1038,154),
           29,color,lines=1,mini=15)
    qr_box=(X(834),Y(175),X(1051),Y(396))
    qr=tp._qr_image(str(ticket['qr']),
                     qr_box[2]-qr_box[0],qr_box[3]-qr_box[1])
    # Deliberate white quiet zone, no other artwork/text enters it.
    im.paste(qr,(qr_box[0]+(qr_box[2]-qr_box[0]-qr.width)//2,
                 qr_box[1]+(qr_box[3]-qr_box[1]-qr.height)//2))
    center('ESCANEAR QR',(843,407,1035,441),19,color,lines=1,mini=12)
    dr=ImageDraw.Draw(im)
    dr.line((X(844),Y(450),X(1041),Y(450)),
            fill=color,width=max(1,Y(2)))
    seat=str(ticket.get('seat_label') or '').strip()
    center(seat if seat else '1 PERSONA',(839,473,1046,532),
           27,color,lines=2,mini=12)
    if color_preview:return im
    return im.convert('L').convert('1',dither=Image.Dither.FLOYDSTEINBERG).convert('RGB')
