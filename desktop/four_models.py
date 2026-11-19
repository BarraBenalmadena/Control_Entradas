"""Cuatro plantillas de entradas municipales, construidas con capas reales.

El programa no incorpora escudos ni marcas dibujadas: solamente representa
los JPG/PNG que el usuario ha seleccionado. Todos los textos y códigos
se dibujan con los datos de la función, tanto para PDF como para ESC/POS.
Los modelos anteriores se mantienen en los módulos de archivo.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps, ImageChops
import math
import os
import sys

from alternative_models import MODELS as ADDITIONAL_MODELS

MODELS = (
    "A · Violín y escudo",
    "B · Cascanueces y logotipo",
    "C · Navidad con diagonal",
    "D · Escenario y doble cabecera",
) + ADDITIONAL_MODELS
INDEX = {name: index for index, name in enumerate(MODELS)}
ART_NAMES = (
    "A_Violin.jpg", "B_Cascanueces.jpg",
    "C_Adornos_musicales.jpg", "D_Violin_escenario.jpg",
)
ACCENT = ("#a31129", "#0c3e78", "#a77505", "#0b5592")
NAVY = "#0c2147"
GOLD = "#e6a823"


def _find_asset(*parts):
    home = Path(os.environ.get("CONTROL_ENTRADAS_DATA") or
                Path.home() / "Documents" / "ControlEntradas")
    for base in (home, Path(sys.executable).resolve().parent,
                 Path(__file__).resolve().parent):
        candidate = base.joinpath(*parts)
        if candidate.is_file():
            return candidate
    return None


def _photo(tp, index, design):
    source = str(design.get("poster") or "").strip()
    if source:
        photo = tp._open_image(source)
        if photo is None:
            raise FileNotFoundError(
                "No se encuentra el cartel JPG seleccionado: " + source)
        return photo
    default = _find_asset("catalogo_aprobado", ART_NAMES[index])
    if default:
        photo = tp._open_image(str(default))
        if photo is not None:
            return photo
    # Si falta el paquete de ejemplos, informar de forma visible.
    # No generar ilustraciones falsas ni insertar un cartel diminuto.
    raise FileNotFoundError(
        "Falta la foto de ejemplo del modelo. Adjunta un JPG propio o "
        "extrae el ZIP completo con la carpeta catalogo_aprobado.")


def _logo(tp, design, key):
    """Preserva el JPG/PNG original y limpia solo márgenes realmente vacíos.

    A diferencia del cargador de carteles, aquí se conserva el alfa de PNG.
    Nunca se recorta una fracción del escudo ni se inventa un logo alternativo.
    """
    source = str(design.get(key) or "").strip()
    if not source:
        return None
    try:
        with Image.open(source) as original:
            adjusted=ImageOps.exif_transpose(original)
            rgba=adjusted.convert("RGBA")
            if "A" in adjusted.getbands() or "transparency" in adjusted.info:
                bounds=rgba.getchannel("A").point(
                    lambda v: 255 if v>10 else 0).getbbox()
            else:
                rgb=adjusted.convert("RGB")
                white=Image.new("RGB",rgb.size,(255,255,255))
                diff=ImageChops.difference(rgb,white).convert("L")
                bounds=diff.point(lambda v: 255 if v>17 else 0).getbbox()
            if bounds:
                # Solo se quita espacio vacío, conservando íntegro el dibujo.
                pad=max(1,round(min(rgba.size)*.014))
                bounds=(max(0,bounds[0]-pad),max(0,bounds[1]-pad),
                        min(rgba.width,bounds[2]+pad),
                        min(rgba.height,bounds[3]+pad))
                rgba=rgba.crop(bounds)
            return rgba
    except (OSError,ValueError) as exc:
        raise FileNotFoundError(
            f"El archivo de {key} no se puede abrir: {source}. "
            "Vuelve a seleccionar el JPG/PNG original.") from exc


def render(event, ticket, width_mm, design, length_mm, color_preview=False):
    """Motor único A-D: geometría, JPG, logos, texto y acceso independientes."""
    import ticket_printer as tp

    variant = INDEX[str(design["plantilla"])]
    if variant >= 4:
        from alternative_models import render as render_alternative
        return render_alternative(
            event,ticket,width_mm,design,length_mm,
            color_preview=color_preview)
    accent = ACCENT[variant]
    geom = tp.geometry(width_mm, length_mm, design)
    W, H = geom["W"], geom["H"]
    X = lambda v: round(float(v) * W / 1080)
    Y = lambda v: round(float(v) * H / 576)
    box = lambda xy: tuple(X(a) if i % 2 == 0 else Y(a)
                            for i, a in enumerate(xy))
    art = Image.new("RGB", (W, H), "white")
    pen = ImageDraw.Draw(art)
    line_width = max(1, Y(2))
    font_size = tp._setting_number(design, "tamano_letra_pct",
                                    100,70,140) / 100
    title_size = tp._setting_number(design, "tamano_cabecera_pct",
                                     100,70,140) / 100
    date_size = tp._setting_number(design, "tamano_fecha_pct",
                                    100,70,140) / 100

    def fit_text(content, region, size, color=NAVY, lines=1,
                 small=10, factor=None):
        factor = font_size if factor is None else factor
        tp._center(ImageDraw.Draw(art), str(content), box(region),
                   max(8, Y(size*factor)), bold=True, lines=lines,
                   min_size=max(7,Y(small)), fill=color)

    def draw_rule(points, color=accent, weight=2):
        ImageDraw.Draw(art).line(
            [(X(x), Y(y)) for x, y in points],
            fill=color, width=max(1,Y(weight)), joint="curve")

    def curve(points, color=accent, weight=3):
        """Quadratic Bezier segments; no diagonal line across other fields."""
        if len(points) < 3: return
        path = []
        for i in range(33):
            t = i/32
            xx = (1-t)*(1-t)*points[0][0] + 2*(1-t)*t*points[1][0] + t*t*points[2][0]
            yy = (1-t)*(1-t)*points[0][1] + 2*(1-t)*t*points[1][1] + t*t*points[2][1]
            path.append((xx, yy))
        draw_rule(path, color, weight)

    def star(cx,cy,r,color=GOLD):
        vertices = []
        for i in range(10):
            a = -math.pi/2 + i*math.pi/5
            rr = r if i%2==0 else r*.45
            vertices.append((X(cx+math.cos(a)*rr),
                             Y(cy+math.sin(a)*rr)))
        ImageDraw.Draw(art).polygon(vertices,fill=color)

    def snowflake(cx,cy,r,color="#318bc1"):
        for i in range(6):
            a=i*math.pi/3
            tip=(cx+math.cos(a)*r, cy+math.sin(a)*r)
            draw_rule([(cx,cy),tip],color,3)
            for sign in (-1,1):
                side=a+sign*.53
                h=(cx+math.cos(a)*r*.61,cy+math.sin(a)*r*.61)
                arm=(h[0]-math.cos(side)*r*.30,h[1]-math.sin(side)*r*.30)
                draw_rule([h,arm],color,2)

    def calendar(cx,cy):
        d=ImageDraw.Draw(art)
        d.rounded_rectangle(box((cx,cy,cx+33,cy+34)),
            radius=max(1,Y(3)),outline=NAVY,width=max(1,Y(3)))
        draw_rule([(cx+3,cy+11),(cx+30,cy+11)],NAVY,2)
        for xx in (cx+8,cx+17,cx+26):
            for yy in (cy+18,cy+26):
                d.ellipse(box((xx-1,yy-1,xx+2,yy+2)),fill=NAVY)
        draw_rule([(cx+9,cy-3),(cx+9,cy+5)],NAVY,3)
        draw_rule([(cx+25,cy-3),(cx+25,cy+5)],NAVY,3)

    def clock(cx,cy):
        d=ImageDraw.Draw(art)
        d.ellipse(box((cx-17,cy-17,cx+17,cy+17)),
                  outline=NAVY,width=max(1,Y(3)))
        draw_rule([(cx,cy-11),(cx,cy),(cx+11,cy+5)],NAVY,3)

    def pin(cx,cy):
        d=ImageDraw.Draw(art)
        d.ellipse(box((cx-11,cy-17,cx+11,cy+5)),fill="white")
        d.polygon([(X(cx-9),Y(cy+2)),(X(cx+9),Y(cy+2)),
                   (X(cx),Y(cy+17))],fill="white")
        d.ellipse(box((cx-3.5,cy-9,cx+3.5,cy-2)),fill=accent)

    def info(cx,cy):
        d=ImageDraw.Draw(art)
        d.ellipse(box((cx-15,cy-15,cx+15,cy+15)),
            outline=NAVY,width=max(1,Y(2)))
        fit_text("i",(cx-8,cy-13,cx+8,cy+13),22,NAVY,small=12)

    def paint_logo(source, region):
        """Usar los píxeles REALES del archivo: nunca pintar un escudo ficticio."""
        if source is None:
            return
        rgba = source.convert("RGBA")
        if rgba.width <= 0 or rgba.height <= 0:
            raise ValueError("El logotipo está vacío.")
        # Quitar margen solo si el fichero tiene transparencia explícita.
        if "A" in source.getbands():
            bound = rgba.getchannel("A").getbbox()
            if bound:
                rgba=rgba.crop(bound)
        x0,y0,x1,y1=box(region)
        tw,th=max(1,x1-x0),max(1,y1-y0)
        placed=ImageOps.contain(rgba,(tw,th),
                               method=Image.Resampling.LANCZOS)
        at=(x0+(tw-placed.width)//2,y0+(th-placed.height)//2)
        art.paste(placed,at,placed)

    # FOTO: un solo JPG real recortado por una máscara propia de cada diseño.
    # Nunca se vuelve a dibujar el mismo cartel pequeño sobre uno difuminado.
    photograph = _photo(tp, variant, design)
    cx = tp._setting_number(design,"foto_centro_x_pct",50,0,100)/100
    cy = tp._setting_number(design,"foto_centro_y_pct",50,0,100)/100
    zoom = max(1., tp._setting_number(design,"foto_zoom_pct",100,60,250)/100)
    edge = (
        lambda yy: 253 - 37*math.sin(math.pi*yy/576) if variant==0
        else 249 - 36*yy/576 if variant==1
        else 312 - 135*yy/576 if variant==2
        else 248 - 51*math.sin(math.pi*yy/576) + 12*yy/576
    )
    panel_left=11
    panel_right=320 if variant==2 else 270
    dest=(X(panel_left),Y(13),X(panel_right),Y(562))
    pw,ph=dest[2]-dest[0],dest[3]-dest[1]
    cover=ImageOps.fit(photograph,(max(1,round(pw*zoom)),
                                   max(1,round(ph*zoom))),
                       method=Image.Resampling.LANCZOS,centering=(cx,cy))
    left=round((cover.width-pw)*cx)
    top=round((cover.height-ph)*cy)
    cover=cover.crop((left,top,left+pw,top+ph))
    contour=[(X(panel_left),Y(13)),(X(edge(13)),Y(13))]
    contour += [(X(edge(yy)),Y(yy)) for yy in range(18,559,5)]
    contour += [(X(edge(561)),Y(562)),(X(panel_left),Y(562))]
    mask=Image.new("L",(pw,ph),0)
    local=[(x-dest[0],y-dest[1]) for x,y in contour]
    ImageDraw.Draw(mask).polygon(local,fill=255)
    rounding=Image.new("L",(pw,ph),0)
    ImageDraw.Draw(rounding).rounded_rectangle(
        (0,0,pw-1,ph-1),radius=max(1,Y(12)),fill=255)
    mask=ImageChops.multiply(mask,rounding)
    art.paste(cover,(dest[0],dest[1]),mask)
    draw_rule([(edge(yy),yy) for yy in range(13,563,3)],
              ("#ab1438","#daa018","#d9a11c","#268ec2")[variant],4)

    # Encabezado: el archivo elegido por el usuario es siempre la única fuente
    # de escudo o logotipo. No hay escudo generado ni logos por defecto.
    council = _logo(tp,design,"logo_ayto")
    school = _logo(tp,design,"logo_centro")
    short_council = council is not None and \
        council.width <= council.height*1.65
    header_start = (277,265,328,276)[variant]
    if short_council:
        paint_logo(council,(header_start,18,header_start+70,129))
        name_left=header_start+76
        name_right=616 if school is not None else 829
        if school is not None:
            paint_logo(school,(624,25,828,107))
    elif council is not None:
        # JPG municipal panorámico completo: zona superior derecha independiente.
        paint_logo(council,(569,22,833,121))
        if school is not None:
            paint_logo(school,(header_start,31,header_start+70,105))
            name_left=header_start+77
        else:
            name_left=header_start+5
        name_right=561
    elif school is not None:
        paint_logo(school,(header_start,22,header_start+85,119))
        name_left=header_start+93
        name_right=829
    else:
        name_left=header_start+5
        name_right=829
    fit_text(design.get("cabecera") or "Escuela Municipal de Música y Danza",
             (name_left,17,name_right,82),36,NAVY,
             lines=2,small=15,factor=title_size)
    fit_text(design.get("subtitulo") or "Arroyo de la Miel",
             (name_left,84,name_right,128),23,
             ("#972038","#0a3a70","#8d1328","#13395f")[variant],
             small=13,factor=title_size)
    # Los motivos bajo el encabezado nunca cruzan logos ni letras.
    if variant==1:
        curve([(name_left,132),(548,142),(822,125)],GOLD,3)
    if variant==2:
        draw_rule([(name_left+10,134),(824,134)],GOLD,2)

    # Título del evento con cuatro geometrías realmente distintas.
    body_start=(266,259,294,265)[variant]
    body_right=832
    event_name=str(event.get("name") or "ESPECTÁCULO")
    d=ImageDraw.Draw(art)
    if variant==0:
        d.rounded_rectangle(box((body_start,146,body_right,252)),
            radius=max(1,Y(12)),outline="#99152b",
            width=max(2,Y(4)),fill="white")
        d.rounded_rectangle(box((body_start+6,152,body_right-6,246)),
            radius=max(1,Y(9)),outline="#a32639",width=max(1,Y(2)))
        fit_text(event_name,(body_start+13,161,body_right-13,224),
                 63,"#99152b",2,23)
        draw_rule([(body_start+167,234),(body_start+236,234)],GOLD,2)
        star((body_start+body_right)/2,234,10)
        draw_rule([(body_start+311,234),(body_start+385,234)],GOLD,2)
    elif variant==1:
        fit_text(event_name,(body_start+5,145,body_right-5,231),
                 66,NAVY,2,25)
        star(body_start+47,251,12)
        curve([(body_start+93,250),(540,271),(body_right-85,250)],
              GOLD,4)
        star(body_right-45,251,12)
    elif variant==2:
        d.rounded_rectangle(box((body_start,148,body_right,267)),
            radius=max(1,Y(15)),fill="#8f1026",
            outline=GOLD,width=max(3,Y(5)))
        fit_text(event_name,(body_start+38,163,body_right-38,257),
                 56,"white",2,21)
        star(body_start+24,205,13,GOLD)
        star(body_right-23,205,13,GOLD)
    else:
        d.rounded_rectangle(box((body_start,148,body_right,243)),
            radius=max(1,Y(16)),fill="#e6f4fd",
            outline="#2988c5",width=max(2,Y(3)))
        fit_text(event_name,(body_start+10,159,body_right-10,231),
                 66,NAVY,2,24)
        curve([(body_start+9,250),(548,284),(body_right-9,250)],
              "#3b9cdd",3)
        for px,r in ((body_start+113,8),((body_start+body_right)/2,17),
                     (body_right-112,8)):
            snowflake(px,260,r)

    # Fecha y hora: columna con iconos vectoriales, sin líneas sobre las letras.
    date_top = 278 if variant in (0,1,2) else 285
    date_bottom=date_top+58
    calendar(body_start+21,date_top+10)
    clock(body_start+348,date_top+29)
    fit_text(datetime.fromisoformat(str(event["start_time"])).strftime("%d/%m/%Y"),
             (body_start+66,date_top,body_start+289,date_bottom),
             38,NAVY,small=19,factor=date_size)
    draw_rule([(body_start+313,date_top+7),
               (body_start+313,date_bottom-7)],NAVY,2)
    fit_text(datetime.fromisoformat(str(event["start_time"])).strftime("%H:%M H"),
             (body_start+380,date_top,body_right-3,date_bottom),
             38,NAVY,small=19,factor=date_size)

    # Lugar, información y código de barras, con separación fija entre cajas.
    place_top=date_bottom+8
    place_bottom=place_top+43
    d=ImageDraw.Draw(art)
    d.rounded_rectangle(box((body_start,place_top,body_right,place_bottom)),
                        radius=max(2,Y(11)),fill=accent)
    pin(body_start+30,place_top+22)
    fit_text(design.get("lugar") or
             "Casa de la Cultura · Arroyo de la Miel",
             (body_start+56,place_top+2,body_right-8,place_bottom-2),
             29,"white",2,13)

    note_top=place_bottom+11
    no_seats=str(event.get("mode") or "libre")=="libre"
    first=("SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA"
           if no_seats else "RESPETE SU FILA Y BUTACA ASIGNADAS")
    second=("SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN "
            "NO SE GARANTIZA BUTACA")
    info(body_start+21,note_top+25)
    fit_text(first,(body_start+49,note_top,body_right-3,note_top+26),
             19,NAVY,2,10)
    draw_rule([(body_start+52,note_top+29),
               (body_right-5,note_top+29)],NAVY,1)
    fit_text(second,(body_start+49,note_top+33,body_right-3,note_top+70),
             18,NAVY,2,9)
    bar_top=max(498,note_top+82)
    draw_rule([(body_start+4,bar_top-8),(body_right-3,bar_top-8)],
              accent,1)
    barcode=tp._code128_image(tp.barcode_ticket_value(ticket["id"]),
               X(body_right-body_start-52),max(20,Y(44)))
    barcode_x=(X(body_start+22)+X(body_right-22)-barcode.width)//2
    art.paste(barcode,(barcode_x,Y(bar_top)))

    # Franja de acceso exclusiva: nunca puede quedar cubierta por cartel/logos.
    stub_left=850
    stub_right=1071
    d=ImageDraw.Draw(art)
    d.rectangle(box((stub_left,12,stub_right,562)),fill="white")
    draw_rule([(841,18),(841,557)],accent,3)
    d.rounded_rectangle(box((stub_left+6,26,stub_right-6,84)),
        radius=max(1,Y(9)),fill=accent)
    fit_text("CONTROL DE ACCESO",
             (stub_left+9,31,stub_right-9,78),24,"white",2,11)
    d.rounded_rectangle(box((stub_left+15,100,stub_right-13,160)),
        radius=max(1,Y(8)),outline=accent,
        width=max(1,Y(2)),fill="white")
    fit_text(f"N.º {int(ticket['number']):04d}",
             (stub_left+20,110,stub_right-18,150),31,NAVY,1,14)
    qr_region=box((stub_left+10,174,stub_right-8,397))
    qr=tp._qr_image(str(ticket["qr"]),
                    qr_region[2]-qr_region[0],
                    qr_region[3]-qr_region[1])
    art.paste(qr,(qr_region[0]+(qr_region[2]-qr_region[0]-qr.width)//2,
                  qr_region[1]+(qr_region[3]-qr_region[1]-qr.height)//2))
    fit_text("ESCANEAR QR",(stub_left+10,409,stub_right-8,447),
             23,accent,1,12)
    draw_rule([(stub_left+18,452),(stub_right-17,452)],accent,2)
    label=str(ticket.get("seat_label") or "").strip() or "1 PERSONA"
    fit_text(label,(stub_left+6,475,stub_right-5,538),
             35,accent,2,13)
    if variant==3:
        # Onda azul en la esquina inferior, sin tocar barra ni QR.
        curve([(15,553),(98,531),(245,563)],"#91d8f7",4)
        curve([(854,554),(976,527),(1063,557)],"#a5e1f9",3)

    # Perfil de ticket, nunca recuadro de lotería dentro de la fotografía.
    d=ImageDraw.Draw(art)
    d.rounded_rectangle(box((5,5,1076,570)),
        radius=max(2,Y(13)),outline=accent,width=max(2,Y(4)))
    if color_preview:
        return art
    return art.convert("L").convert(
        "1",dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
