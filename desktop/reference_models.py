"""Diseños I–L, entradas municipales inspiradas en los cuatro ejemplos del usuario.

No se usa la imagen de la entrada entera: la fotografía es una capa independiente,
los logos son los JPG/PNG elegidos, los textos se ajustan y los códigos se generan
de nuevo para cada entrada. Talón de control siempre aislado en un panel blanco.
"""
from __future__ import annotations
from datetime import datetime
from PIL import Image, ImageDraw, ImageOps, ImageChops
import math

MODELS = (
    "I · Clave de sol navideña",
    "J · Concierto azul y pentagrama",
    "K · Teatro y banda burdeos",
    "L · Cascanueces azul y oro",
)
ACCENTS = ("#ab1230", "#0f5295", "#9b1726", "#c39830")
NAVY = "#102648"
GOLD = "#dca927"
ART = (
    "I_Clave_navidad.jpg", "J_Violin_escenario.jpg",
    "K_Teatro_navidad.jpg", "L_Cascanueces_gala.jpg",
)


def render(event,ticket,width_mm,design,length_mm,color_preview=False):
    import ticket_printer as tp
    from four_models import _find_asset, _photo, _logo

    variant=MODELS.index(design["plantilla"])
    color=ACCENTS[variant]
    g=tp.geometry(width_mm,length_mm,design)
    W,H=g["W"],g["H"]
    X=lambda n:round(float(n)*W/1080)
    Y=lambda n:round(float(n)*H/576)
    b=lambda coords:(X(coords[0]),Y(coords[1]),X(coords[2]),Y(coords[3]))
    img=Image.new("RGB",(W,H),"white")
    font_pct=tp._setting_number(design,"tamano_letra_pct",100,70,140)/100
    head_pct=tp._setting_number(design,"tamano_cabecera_pct",100,70,140)/100
    date_pct=tp._setting_number(design,"tamano_fecha_pct",100,70,140)/100

    def txt(value,coords,size=24,shade=NAVY,lines=1,small=10,factor=None):
        ff=font_pct if factor is None else factor
        tp._center(ImageDraw.Draw(img),str(value),b(coords),
            max(8,Y(size*ff)),bold=True,lines=lines,
            min_size=max(7,Y(small)),fill=shade)
    def line(points,shade=color,width=2):
        ImageDraw.Draw(img).line([(X(x),Y(y)) for x,y in points],
            fill=shade,width=max(1,Y(width)),joint="curve")
    def curve(a,c,z,shade=color,width=3):
        points=[]
        for i in range(32):
            t=i/31
            points.append(((1-t)**2*a[0]+2*t*(1-t)*c[0]+t*t*z[0],
                          (1-t)**2*a[1]+2*t*(1-t)*c[1]+t*t*z[1]))
        line(points,shade,width)
    def star(cx,cy,r,shade=GOLD):
        vertices=[]
        for j in range(10):
            phi=-math.pi/2+j*math.pi/5
            rad=r if j%2==0 else r*.47
            vertices.append((X(cx+math.cos(phi)*rad),
                             Y(cy+math.sin(phi)*rad)))
        ImageDraw.Draw(img).polygon(vertices,fill=shade)
    def snow(cx,cy,r,shade="#59acde"):
        for j in range(6):
            phi=j*math.pi/3
            line([(cx,cy),(cx+r*math.cos(phi),cy+r*math.sin(phi))],shade,2)
    def real_logo(source,coords):
        if source is None: return
        rgba=source.convert("RGBA")
        dest=b(coords)
        actual=ImageOps.contain(rgba,(
             max(1,dest[2]-dest[0]),max(1,dest[3]-dest[1])),
             Image.Resampling.LANCZOS)
        img.paste(actual,(dest[0]+(dest[2]-dest[0]-actual.width)//2,
                          dest[1]+(dest[3]-dest[1]-actual.height)//2),actual)
    def calendar(cx,cy):
        d=ImageDraw.Draw(img)
        d.rounded_rectangle(b((cx,cy,cx+29,cy+31)),radius=max(1,Y(3)),
            outline=NAVY,width=max(1,Y(2)))
        line([(cx+2,cy+11),(cx+27,cy+11)],NAVY,2)
        for xx in (cx+8,cx+16,cx+24):
            for yy in (cy+18,cy+25):
                d.ellipse(b((xx-1,yy-1,xx+2,yy+2)),fill=NAVY)
    def clock(cx,cy):
        ImageDraw.Draw(img).ellipse(b((cx-16,cy-16,cx+16,cy+16)),
            outline=NAVY,width=max(1,Y(2)))
        line([(cx,cy-10),(cx,cy),(cx+9,cy+4)],NAVY,2)
    def location(cx,cy):
        d=ImageDraw.Draw(img)
        d.ellipse(b((cx-10,cy-15,cx+10,cy+6)),fill="white")
        d.polygon([(X(cx-9),Y(cy+3)),(X(cx+9),Y(cy+3)),
            (X(cx),Y(cy+16))],fill="white")
        d.ellipse(b((cx-3,cy-9,cx+3,cy-2)),fill=color)

    # Panel fotográfico izquierdo: cada ejemplo tiene corte propio.
    source=str(design.get("poster") or "").strip()
    if source:
        photo=_photo(tp,0,design)
    else:
        demo=_find_asset("catalogo_aprobado",ART[variant])
        loaded=tp._open_image(str(demo)) if demo else None
        photo=loaded if loaded is not None else _photo(tp,(2,3,0,1)[variant],design)
    fx=tp._setting_number(design,"foto_centro_x_pct",50,0,100)/100
    fy=tp._setting_number(design,"foto_centro_y_pct",50,0,100)/100
    zoom=max(1.,tp._setting_number(design,"foto_zoom_pct",100,60,250)/100)
    photo_box=(10,13,327,562)
    px0,py0,px1,py1=b(photo_box)
    pw,ph=px1-px0,py1-py0
    fitted=ImageOps.fit(photo,(max(1,round(pw*zoom)),max(1,round(ph*zoom))),
                        Image.Resampling.LANCZOS,centering=(fx,fy))
    dx=round((fitted.width-pw)*fx);dy=round((fitted.height-ph)*fy)
    crop=fitted.crop((dx,dy,dx+pw,dy+ph))
    # Edge function changes the actual silhouette, not just accent color.
    if variant==0:
        edge=lambda y:112+155*max(0,math.sin(math.pi*y/576))**1.3
    elif variant==1:
        edge=lambda y:135+116*max(0,math.sin(math.pi*y/576))
    elif variant==2:
        edge=lambda y:180+120*y/576
    else:
        edge=lambda y:147+120*y/576
    mask=Image.new("L",(pw,ph),0)
    shape=[(0,0)]+[
      (X(edge(y))-px0,Y(y)-py0) for y in range(13,563,3)
    ]+[(0,ph)]
    ImageDraw.Draw(mask).polygon(shape,fill=255)
    img.paste(crop,(px0,py0),mask)
    line([(edge(y),y) for y in range(13,563,3)],
         ("#d6a132","#2c91c9","#bc9430","#d9ad49")[variant],4)

    # Zonas válidas: el encabezado no cruza la fotografía y termina antes del QR.
    d=ImageDraw.Draw(img)
    municipal=_logo(tp,design,"logo_ayto")
    educational=_logo(tp,design,"logo_centro")
    begin=258 if variant!=2 else 301
    is_short=municipal is not None and municipal.width <= municipal.height*1.65
    if is_short:
        real_logo(municipal,(begin,16,begin+78,132))
        left=begin+82
        right=816 if educational is None else 665
        if educational is not None:
            real_logo(educational,(669,23,816,109))
    elif municipal is not None:
        real_logo(municipal,(640,21,815,118))
        left=begin+8
        right=635
        if educational is not None:
            real_logo(educational,(begin,26,begin+70,116))
            left=begin+76
    elif educational is not None:
        real_logo(educational,(begin,21,begin+79,120))
        left=begin+84;right=816
    else:
        left=begin+6;right=816
    txt(design.get("cabecera") or "Escuela Municipal de Música y Danza",
        (left,18,right,81),31,NAVY,2,14,head_pct)
    txt(design.get("subtitulo") or "Arroyo de la Miel",
        (left,84,right,119),21,NAVY,1,12,head_pct)
    line([(begin+20,134),(816,134)],GOLD,2)

    name=str(event.get("name") or "ESPECTÁCULO")
    L=(315 if variant==2 else 281)
    R=817
    if variant==0:
        # Título navideño bicolor; textos libres siguen siendo editables.
        words=name.upper()
        if "NAVIDAD" in words and words.replace("NAVIDAD","").strip():
            top=words.split("NAVIDAD")[0].strip()
            txt(top,(L,153,R,205),53,NAVY,1,18)
            txt("NAVIDAD",(L,203,R,276),75,"#ad112a",1,24)
        else:
            txt(name,(L,152,R,275),59,NAVY,2,21)
        for xx in (L+33,R-30):
            star(xx,226,12,GOLD)
        curve((L+110,280),((L+R)/2,269),(R-108,280),GOLD,3)
    elif variant==1:
        # Título y fecha en banda azul separada.
        for i in range(5):
            yy=154+i*12
            curve((L+8,yy),(L+80,yy-26),(R-7,yy+3),"#a8daf4",1)
        for xx in (L+103,R-105):
            snow(xx,184,10)
        txt(name,(L+7,183,R-8,260),57,NAVY,2,22)
    elif variant==2:
        # Panel burdeos bajo la cabecera, fotografía diagonal.
        d.rounded_rectangle(b((L-8,156,R,276)),
             radius=max(2,Y(12)),fill="#8d1026",outline=GOLD,
             width=max(2,Y(3)))
        txt(name,(L+22,166,R-22,267),58,"white",2,20)
        for xx in (L+9,R-9):
            star(xx,206,11,GOLD)
    else:
        # Estilo clásico de gala con filetes dorados y talón azul.
        for xx in (L+28,R-29):
            star(xx,173,12,GOLD)
        curve((L+16,154),((L+R)/2,170),(R-14,154),GOLD,3)
        txt(name,(L+15,185,R-15,274),58,NAVY,2,21)

    start=datetime.fromisoformat(str(event["start_time"]))
    date_value=start.strftime("%d/%m/%Y")
    hour_value=start.strftime("%H:%M H")
    if variant==1:
        # Fecha destacada en cinta, hora separada debajo.
        d.polygon([(X(L+64),Y(277)),(X(R-64),Y(277)),
          (X(R-81),Y(313)),(X(R-64),Y(345)),
          (X(L+64),Y(345)),(X(L+82),Y(313))],fill="#145ea5")
        txt(date_value,(L+95,282,R-95,339),45,"white",1,19,date_pct)
        txt(hour_value,(L+142,348,R-142,397),42,NAVY,1,19,date_pct)
        place_top=400; place_bottom=432
        notes_top=438
    else:
        calendar(L+13,289)
        txt(date_value,(L+50,281,L+242,339),35,NAVY,1,17,date_pct)
        line([(L+251,291),(L+251,327)],GOLD,2)
        clock(L+286,308)
        txt(hour_value,(L+313,282,R-4,338),34,NAVY,1,17,date_pct)
        place_top=354; place_bottom=398
        notes_top=407

    # Avisos contenidos siempre en su zona, no encima de QR o código barras.
    d.rounded_rectangle(b((L+1,place_top,R-2,place_bottom)),
         radius=max(2,Y(11)),fill=("#0c3267","#0a477d","#092e66","#102c54")[variant])
    location(L+24,(place_top+place_bottom)/2)
    txt(design.get("lugar") or "Casa de la Cultura · Arroyo de la Miel",
        (L+47,place_top+2,R-10,place_bottom-2),24,"white",2,11)
    has_seats=str(event.get("mode") or "libre")!="libre"
    first=("RESPETE SU FILA Y BUTACA ASIGNADAS" if has_seats else
           "SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA")
    second="SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA"
    if variant in (0,2):
        d.rectangle(b((L+1,notes_top,R-2,notes_top+75)),fill="#9f1328")
        txt(first,(L+7,notes_top+3,R-9,notes_top+34),17,"white",2,9)
        txt(second,(L+7,notes_top+37,R-8,notes_top+72),16,"white",2,9)
    else:
        txt(first,(L+5,notes_top+3,R-5,notes_top+32),17,NAVY,2,9)
        line([(L+12,notes_top+37),(R-14,notes_top+37)],color,1)
        txt(second,(L+6,notes_top+41,R-5,notes_top+76),16,NAVY,2,9)
    bar_top=max(511,notes_top+83)
    line([(L+10,bar_top-7),(R-12,bar_top-7)],GOLD,2)
    code=tp._code128_image(tp.barcode_ticket_value(ticket["id"]),
                           X(R-L-45),max(18,Y(40)))
    barcode_left=(X(L+16)+X(R-14)-code.width)//2
    img.paste(code,(barcode_left,Y(bar_top)))

    # QR propio del evento y de la entrada. Pintar el panel opaco AL FINAL
    # elimina cualquier invasión procedente de fotos o adornos contiguos.
    stub_left,stub_right=825,1075
    d=ImageDraw.Draw(img)
    dark=variant==3
    d.rectangle(b((stub_left,11,stub_right,563)),
                 fill="#112c50" if dark else "white")
    line([(820,11),(820,562)],GOLD if dark else NAVY,3)
    d.rounded_rectangle(b((stub_left+7,26,stub_right-7,83)),
        radius=max(1,Y(9)),fill=NAVY)
    txt("CONTROL DE ACCESO",(stub_left+10,30,stub_right-10,77),
        23,"white",2,11)
    d.rounded_rectangle(b((stub_left+14,100,stub_right-14,161)),
        radius=max(1,Y(8)),fill="white",
        outline=GOLD if dark else color,width=max(1,Y(2)))
    txt(f"N.º {int(ticket['number']):04d}",
        (stub_left+20,109,stub_right-20,152),31,NAVY,1,15)
    # Matriz cuadrada de máximo tamaño, idéntica en los doce modelos,
    # sobre blanco incluso cuando el talón del diseño es azul oscuro.
    qrbox=b((stub_left+6,164,stub_right-6,448))
    tp.draw_standard_access_qr(img,str(ticket["qr"]),qrbox)
    txt("ESCANEAR QR",(stub_left+12,452,stub_right-12,478),
        21,"white" if dark else NAVY,1,10)
    line([(stub_left+18,482),(stub_right-18,482)],GOLD if dark else color,2)
    label=str(ticket.get("seat_label") or "").strip() or "1 PERSONA"
    txt(label,(stub_left+10,488,stub_right-9,548),
        31,"white" if dark else NAVY,2,13)
    d.rounded_rectangle(b((5,5,1075,571)),radius=max(1,Y(9)),
        outline=GOLD if variant!=1 else NAVY,width=max(2,Y(4)))
    return img if color_preview else img.convert("L").convert(
        "1",dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
