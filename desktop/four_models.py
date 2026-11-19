"""Cuatro modelos principales basados en los prototipos aprobados.
Foto JPG opcional por función, QR y Code128 propios de cada entrada.
Los 30 modelos anteriores y los históricos siguen disponibles en el motor
como respaldo, pero no se muestran en la galería principal.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import os
import sys
import math
from PIL import Image, ImageDraw, ImageOps, ImageFilter

MODELS = (
    "A · Violín y escudo",
    "B · Cascanueces y logotipo",
    "C · Navidad con diagonal",
    "D · Escenario y doble cabecera",
)
INDEX = {name: i for i, name in enumerate(MODELS)}
ART_NAMES = (
    "A_Violin.jpg", "B_Cascanueces.jpg",
    "C_Adornos_musicales.jpg", "D_Violin_escenario.jpg",
)
INK = ("#891d2a", "#103763", "#94600b", "#0c4785")
NAVY = "#142943"


def _find_asset(*parts):
    root = Path(os.environ.get("CONTROL_ENTRADAS_DATA") or
                Path.home() / "Documents" / "ControlEntradas")
    bases = (root, Path(sys.executable).resolve().parent,
             Path(__file__).resolve().parent)
    for base in bases:
        path = base.joinpath(*parts)
        if path.is_file():
            return path
    return None


def _art(tp, index, design):
    supplied = str(design.get("poster") or "").strip()
    if supplied:
        img = tp._open_image(supplied)
        if img is None:
            raise FileNotFoundError(
                "La fotografía JPG seleccionada no se puede abrir: " + supplied)
        return img
    preset = _find_asset("catalogo_aprobado", ART_NAMES[index])
    if preset:
        img = tp._open_image(str(preset))
        if img is not None:
            return img
    # Respaldo de los motivos entregados anteriormente.
    try:
        from modern_catalog import art_path
        img = tp._open_image(str(art_path(index + 1)))
        if img is not None:
            return img
    except (OSError, ValueError):
        pass
    img = Image.new("RGB", (330, 650), "#243b54")
    painter = ImageDraw.Draw(img)
    for y in range(25, 630, 19):
        painter.arc((10, y-100, 355, y+100),
                    210, 337, fill="#f5dfa7", width=3)
    return img


def render(event, ticket, width_mm, design, length_mm, color_preview=False):
    """Una sola ruta para galería, PDF, impresión térmica y prueba A4."""
    import ticket_printer as tp
    variant = INDEX[str(design["plantilla"])]
    ink = INK[variant]
    geom = tp.geometry(width_mm, length_mm, design)
    W, H = geom["W"], geom["H"]
    # QR a la derecha con tamaño estable, independientemente de la foto.
    X = lambda value: round(value * W / 1080)
    Y = lambda value: round(value * H / 576)
    ui = lambda rect: (X(rect[0]), Y(rect[1]), X(rect[2]), Y(rect[3]))
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    thickness = max(1, Y(3))
    font_factor = tp._setting_number(design,"tamano_letra_pct",100,70,140)/100
    head_factor = tp._setting_number(design,"tamano_cabecera_pct",100,70,140)/100
    date_factor = tp._setting_number(design,"tamano_fecha_pct",100,70,140)/100

    def text(value, region, size=22, color=NAVY, lines=1,
             minimum=10, factor=None, bold=True):
        multiplier=font_factor if factor is None else factor
        tp._center(ImageDraw.Draw(img), str(value), ui(region),
                   max(8,Y(size*multiplier)), lines=lines,
                   min_size=max(8,Y(minimum)), fill=color, bold=bold)

    def rule(points, color=ink, width=2):
        ImageDraw.Draw(img).line([(X(x),Y(y)) for x,y in points],
                                fill=color,width=max(1,Y(width)))

    def star(cx,cy,r,color):
        # Motivos dibujados como geometría: no dependen de fuentes que
        # muestran cuadrados vacíos en algunas impresoras Windows.
        coords=[]
        for n in range(10):
            angle=-math.pi/2+n*math.pi/5
            radius=r if n%2==0 else r*.44
            coords.append((X(cx+math.cos(angle)*radius),
                           Y(cy+math.sin(angle)*radius)))
        ImageDraw.Draw(img).polygon(coords,fill=color)

    def snowflake(cx,cy,r,color):
        painter=ImageDraw.Draw(img)
        for direction in range(6):
            a=direction*math.pi/3
            ax,ay=(X(cx+math.cos(a)*r),Y(cy+math.sin(a)*r))
            painter.line((X(cx),Y(cy),ax,ay),
                         fill=color,width=max(1,Y(3)))

    # 1. Panel fotográfico, JPG de la función con prioridad absoluta.
    photo = _art(tp, variant, design)
    bounds = (X(12), Y(12), X(268 if variant==2 else 260), Y(562))
    w,h = bounds[2]-bounds[0], bounds[3]-bounds[1]
    fx = tp._setting_number(design,"foto_centro_x_pct",50,0,100)/100
    fy = tp._setting_number(design,"foto_centro_y_pct",50,0,100)/100
    zoom = tp._setting_number(design,"foto_zoom_pct",100,60,250)/100
    fit = str(design.get("ajuste_imagen") or "Rellenar y recortar")
    # Nunca deformar el JPG ni dejar una franja blanca en el panel.
    background = ImageOps.fit(photo, (w,h), centering=(fx,fy),
                              method=Image.Resampling.LANCZOS)
    if fit == "Mostrar completa":
        background = background.filter(ImageFilter.GaussianBlur(max(1,Y(11))))
        full = ImageOps.contain(photo,
               (max(1,round(w*.97*min(1,zoom))),
                max(1,round(h*.97*min(1,zoom)))),
                method=Image.Resampling.LANCZOS)
        background.paste(full, ((w-full.width)//2,(h-full.height)//2))
    elif zoom != 1:
        scaled = ImageOps.fit(photo,(max(w,round(w*zoom)),
             max(h,round(h*zoom))),centering=(fx,fy),
             method=Image.Resampling.LANCZOS)
        if scaled.size != (w,h):
            px=round((scaled.width-w)*fx)
            py=round((scaled.height-h)*fy)
            background=scaled.crop((px,py,px+w,py+h))
        else:
            background=scaled

    alpha = Image.new("L",(w,h),0)
    mask = ImageDraw.Draw(alpha)
    if variant==0:
        mask.polygon([(0,0),(w,0),(round(w*.86),h),(0,h)],fill=255)
    elif variant==1:
        mask.rounded_rectangle((0,0,w-1,h-1),radius=Y(19),fill=255)
        mask.polygon([(w-28,0),(w,0),(w-7,h),(w-28,h)],fill=0)
    elif variant==2:
        mask.polygon([(0,0),(w,0),(round(w*.73),round(h*.42)),
                      (round(w*.88),h),(0,h)],fill=255)
    else:
        mask.polygon([(0,0),(round(w*.96),0),
                      (round(w*.89),round(h*.60)),(w,h),(0,h)],fill=255)
    img.paste(background, (bounds[0],bounds[1]), alpha)
    if variant==0:
        rule([(251,13),(224,561)],width=4)
    elif variant==1:
        rule([(263,13),(240,560)],color="#e1a52b",width=5)
    elif variant==2:
        rule([(270,13),(211,245),(245,562)],color="#d19b29",width=5)
    else:
        rule([(251,13),(238,440),(267,562)],color="#58a4d9",width=5)

    # 2. Escudo corto arriba. Logotipo ancho, si se proporciona, en un
    # lugar propio; nunca se recorta ni se esconde debajo del texto.
    crest = _find_asset("catalogo_nuevo","escudo_benalmadena.png")
    logo_path = str(design.get("logo_ayto") or "").strip()
    chosen_logo = tp._open_image(logo_path) if logo_path else None
    if logo_path and chosen_logo is None:
        raise FileNotFoundError("No se encuentra el escudo/logotipo: "+logo_path)
    if chosen_logo is not None and chosen_logo.width <= chosen_logo.height*1.65:
        emblem = chosen_logo
        wide_logo = None
    else:
        emblem = tp._open_image(str(crest)) if crest else None
        wide_logo = chosen_logo

    def put_logo(source, region):
        if source is None: return
        target=ui(region)
        # PNG con transparencia sin fondo oscuro espurio.
        rgba=ImageOps.exif_transpose(source).convert("RGBA")
        bbox=rgba.getchannel("A").getbbox()
        if bbox: rgba=rgba.crop(bbox)
        maxw,maxh=target[2]-target[0],target[3]-target[1]
        fitted=ImageOps.contain(rgba,(maxw,maxh),Image.Resampling.LANCZOS)
        xx=target[0]+(maxw-fitted.width)//2
        yy=target[1]+(maxh-fitted.height)//2
        img.paste(fitted,(xx,yy),fitted)

    if variant in (0,2,3):
        put_logo(emblem,(279,20,335,106))
    if variant==0:
        text(design.get("cabecera") or "Escuela Municipal de Música y Danza",
             (335,20,753,74),29,lines=2,minimum=14,factor=head_factor)
        text(design.get("subtitulo") or "Arroyo de la Miel",
             (344,74,741,107),19,ink,factor=head_factor)
    elif variant==1:
        # B dedica toda la banda superior al nombre/logo alargado.
        if wide_logo is not None:
            put_logo(wide_logo,(285,16,764,88))
        else:
            text(design.get("cabecera") or "Escuela Municipal de Música y Danza",
                 (282,18,766,77),31,lines=2,minimum=15,factor=head_factor)
        text(design.get("subtitulo") or "Arroyo de la Miel",
             (286,79,762,111),19,ink,factor=head_factor)
        rule([(286,118),(765,118)],color="#d4a232",width=4)
    elif variant==2:
        text(design.get("cabecera") or "Escuela Municipal de Música y Danza",
             (339,18,757,77),28,lines=2,minimum=14,factor=head_factor)
        text(design.get("subtitulo") or "Arroyo de la Miel",
             (340,78,751,107),19,ink,factor=head_factor)
    else:
        text(design.get("cabecera") or "Escuela Municipal de Música y Danza",
             (339,20,562,90),25,lines=3,minimum=13,factor=head_factor)
        rule([(562,20),(562,105)],color=ink,width=2)
        if wide_logo is not None:
            put_logo(wide_logo,(577,19,758,104))
        else:
            text("Benalmádena", (574,32,763,63),24,lines=1,minimum=12)
            text("Ayuntamiento", (574,65,763,97),18,lines=1,minimum=11)
    if wide_logo is not None and variant in (0,2):
        # Segundo logo en banda propia; no reduce la letra de la escuela.
        put_logo(wide_logo,(325,109,748,140))

    # 3. Título central: cuatro formas realmente distintas.
    title = str(event.get("name") or "Espectáculo")
    draw = ImageDraw.Draw(img)
    if variant==0:
        draw.rounded_rectangle(ui((282,151,765,248)),radius=Y(12),
                              outline=ink,width=thickness+1,fill="white")
        text(title,(291,158,756,229),47,ink,lines=2,minimum=20)
        rule([(419,236),(491,236)],color="#d6a62b",width=2)
        star(522,237,12,"#d6a62b")
        rule([(554,236),(639,236)],color="#d6a62b",width=2)
    elif variant==1:
        text(title,(282,143,771,241),48,NAVY,lines=2,minimum=20)
        rule([(330,249),(713,249)],color="#dda52a",width=3)
        star(304,248,12,"#dda52a")
        star(737,248,12,"#dda52a")
    elif variant==2:
        draw.rounded_rectangle(ui((278,149,766,259)),radius=Y(16),
                              outline="#d0a240",width=max(3,Y(5)),fill="#7e1422")
        text(title,(297,159,743,251),44,"white",lines=2,minimum=19)
    else:
        draw.rounded_rectangle(ui((280,146,768,251)),radius=Y(22),
                              fill="#e8f6fc",outline="#2484c7",width=thickness)
        text(title,(291,158,757,233),48,NAVY,lines=2,minimum=19)
        snowflake(522,253,15,"#1785c5")
        snowflake(424,254,8,"#58a4d9")
        snowflake(629,254,8,"#58a4d9")

    # 4. Fecha y hora de la función, zona legible.
    start = datetime.fromisoformat(str(event["start_time"]))
    day = start.strftime("%d/%m/%Y")
    hour = start.strftime("%H:%M H")
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(ui((281,273,765,334)),radius=Y(8),
                          fill="#f2f7fc",outline=ink,width=max(1,Y(2)))
    rule([(513,279),(513,328)],color=ink,width=2)
    text(day,(290,280,503,329),36,NAVY,minimum=16,factor=date_factor)
    text(hour,(522,280,754,329),38,NAVY,minimum=16,factor=date_factor)

    place = str(design.get("lugar") or
                "Casa de la Cultura · Arroyo de la Miel")
    draw.rounded_rectangle(ui((281,347,765,389)),radius=Y(12),fill=ink)
    text(place,(289,349,757,385),25,"white",lines=2,minimum=11)

    no_seats = str(event.get("mode") or "libre")=="libre"
    first=("SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA"
           if no_seats else "RESPETE SU FILA Y BUTACA ASIGNADAS")
    second=("SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN "
            "NO SE GARANTIZA BUTACA")
    rule([(291,395),(759,395)],color=ink,width=1)
    text(first,(291,402,759,433),17,NAVY,lines=2,minimum=9)
    text(second,(291,435,759,483),16,NAVY,lines=2,minimum=9)
    rule([(291,489),(759,489)],color=ink,width=1)

    code=tp._code128_image(tp.barcode_ticket_value(ticket["id"]),
                           X(470),max(Y(44),20))
    xcode=(X(291)+X(759)-code.width)//2
    img.paste(code,(xcode,Y(501)))

    # 5. Espacio de control a la derecha, aislado de la fotografía.
    draw=ImageDraw.Draw(img)
    draw.rectangle(ui((778,13,1066,563)),fill="white")
    rule([(776,17),(776,561)],color=ink,width=3)
    draw.rounded_rectangle(ui((798,26,1050,82)),radius=Y(9),fill=ink)
    text("CONTROL DE ACCESO",(806,35,1042,75),22,"white",minimum=11)
    draw.rounded_rectangle(ui((814,98,1035,156)),radius=Y(8),
                          outline=ink,width=max(1,Y(2)),fill="white")
    text(f"N.º {int(ticket['number']):04d}",
         (821,105,1028,149),29,ink,minimum=15)
    qr_region=ui((811,173,1040,400))
    qr=tp._qr_image(str(ticket["qr"]),
                     qr_region[2]-qr_region[0],qr_region[3]-qr_region[1])
    img.paste(qr,(qr_region[0]+(qr_region[2]-qr_region[0]-qr.width)//2,
                  qr_region[1]+(qr_region[3]-qr_region[1]-qr.height)//2))
    text("ESCANEAR QR",(820,414,1030,448),21,ink,minimum=12)
    rule([(821,456),(1029,456)],color=ink,width=2)
    seat=str(ticket.get("seat_label") or "").strip()
    text(seat if seat else "1 PERSONA",
         (818,475,1036,537),28,ink,lines=2,minimum=13)
    draw.rectangle((X(5),Y(5),W-X(5),H-Y(5)),
                   outline=ink,width=max(1,Y(3)))
    if color_preview:
        return img
    # ESC/POS de una ZYWELL es monocromático aunque la galería sea a color.
    return img.convert("L").convert("1",
                 dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
