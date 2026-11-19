"""Thirty native, editable ticket designs based on the supplied visual proposals.
Each entry's QR/Code128 is generated from its own signed unique ticket data.
Only decorative art is image-based; text, number and optical codes are layers.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageOps

NAMES=["Violín navideño","Bola de Navidad","Clave dorada","Telón teatral","Ballet acuarela","Elegancia musical","Micrófono dorado","Fachada iluminada","Música en acuarela","Danza azul","Ballet rosado","Gala con telón","Concierto en escena","Coro infantil","Geometría azul","Navidad dorada","Pueblo nevado","Árbol institucional","Danza moderna","Piano clásico","Belén estrellado","Violín de concierto","Bastón navideño","Municipal bicolor","Farol de invierno","Coral azul","Máscaras de teatro","Arquitectura azul","Flor de Pascua","Sinfonía dorada"]
COLORS=["#81301f","#ba2430","#69417e","#592521","#9d487c","#9e7b3a","#823533","#1e577b","#ac3c88","#0967ac","#a24c93","#9c2437","#2b5795","#a72c37","#2764a0","#98713f","#2b538b","#1f6541","#9f347d","#80552c","#1d355e","#9d5730","#b22935","#173f76","#9a6a34","#256797","#8d293b","#3c81b2","#9d2a35","#96732d"]
MODELS=tuple(f"{i:02d} · {NAMES[i-1]}" for i in range(1,31))
INDEX={name:i for i,name in enumerate(MODELS,1)}

def asset_dir():
    from pathlib import Path
    places=(Path(sys.executable).resolve().parent/'catalogo_nuevo',
            Path(__file__).resolve().parent/'catalogo_nuevo')
    return next((p for p in places if p.is_dir()),places[0])

def art_path(i):
    p=asset_dir()/f'art_{i:02d}.jpg'
    if not p.is_file():
        raise FileNotFoundError(
            f'Falta {p.name}. Extrae el ZIP completo, incluida catalogo_nuevo, junto al EXE.'
        )
    return p

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
    dark=idx in (4,18)
    # True original-inspired identity: 30 distinct illustration panels and
    # decorative palettes, WITHOUT the sample JPG's fake serial/QR/text.
    dr.rectangle((X(6),Y(6),W-X(7),H-Y(7)),outline=color,width=max(1,Y(4)))
    dr.rectangle((X(12),Y(12),X(267),H-Y(13)),fill='#eeeeee')
    poster=tp._open_image(design.get('poster'))
    if poster is None:
        with Image.open(art_path(idx)) as f: poster=f.convert('RGB')
    artwork=ImageOps.fit(poster,(X(258),H-Y(26)),method=Image.Resampling.LANCZOS)
    im.paste(artwork,(X(13),Y(13)))
    dr=ImageDraw.Draw(im)
    # Dedicated diagonal/curve separator, never covers content or codes.
    dr.polygon([(X(245),Y(13)),(X(272),Y(13)),(X(254),H-Y(13)),
                (X(223),H-Y(13))],fill='#ffffff')
    dr.line([(X(247),Y(13)),(X(227),H-Y(15))],
            fill=color,width=max(1,Y(4)))
    # Main content remains fully parametric and optically clean.
    dr.rounded_rectangle((X(286),Y(124),X(790),Y(243)),
                         radius=Y(11),fill=('#173c51' if dark else '#ffffff'),
                         outline=color,width=max(1,Y(2)))
    if idx in (3,6,16,20,30):
        dr.line([(X(298),Y(133)),(X(774),Y(133))],
                fill=color,width=max(1,Y(3)))
    def center(t,rect,size=29,fg='#14273d',lines=2,bold=True,mini=12):
        tp._center(ImageDraw.Draw(im),str(t),
            (X(rect[0]),Y(rect[1]),X(rect[2]),Y(rect[3])),
            size=max(8,Y(size)),bold=bold,lines=lines,
            min_size=max(7,Y(mini)),fill=fg)
    ayto=tp._open_image(design.get('logo_ayto'))
    if ayto is not None:
        tp._fitted(im,ayto,(X(285),Y(26),X(347),Y(102)),'Mostrar completa')
    else:
        center('BENALMÁDENA',(280,45,357,95),14,color,2,mini=8)
    centro=tp._open_image(design.get('logo_centro'))
    if centro is not None:
        tp._fitted(im,centro,(X(740),Y(29),X(796),Y(98)),'Mostrar completa')
    header=str(design.get('cabecera') or 'Escuela Municipal de Música y Danza')
    subtitle=str(design.get('subtitulo') or 'Arroyo de la Miel')
    center(header,(355,22,746,74),27,'#152b47',2,mini=14)
    center(subtitle,(357,74,744,108),20,color,1,mini=11)
    d=datetime.fromisoformat(str(event['start_time']))
    center(str(event['name']),(300,146,778,222),43,
           '#ffffff' if dark else color,lines=2,mini=17)
    date=d.strftime('%d/%m/%Y')
    time=d.strftime('%H:%M H')
    dr=ImageDraw.Draw(im)
    dr.rounded_rectangle((X(296),Y(255),X(778),Y(322)),
        radius=Y(9),fill='#f1f4fa',outline=color,width=max(1,Y(2)))
    dr.line((X(538),Y(263),X(538),Y(314)),
            fill=color,width=max(1,Y(2)))
    center(date,(303,266,531,310),30,'#132840',1,mini=14)
    center(time,(545,266,766,310),32,'#132840',1,mini=14)
    place=str(design.get('lugar') or 'Casa de la Cultura · Arroyo de la Miel')
    dr.rounded_rectangle((X(295),Y(336),X(780),Y(378)),
                         radius=Y(10),fill=color)
    center(place,(306,340,769,374),21,'white',lines=2,mini=11)
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
    center('CONTROL DE ACCESO',(835,34,1046,77),21,'white',lines=2,mini=11)
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
