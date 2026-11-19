"""Modelos E–H de entradas: capas propias, no reorganización de una imagen.

El JPG de la función y el JPG/PNG municipal seleccionado son los únicos
orígenes de fotografías y escudos. QR y Code128 se generan por entrada.
El mismo renderizado sirve al catálogo, PDF y flujo monocromo ESC/POS.
"""
from __future__ import annotations

from datetime import datetime
from PIL import Image, ImageDraw, ImageOps, ImageChops
import math

MODELS = (
    "E · Fotografía derecha y control izquierda",
    "F · Fotografía central derecha",
    "G · Minimalista con diagonal",
    "H · Invierno y fotografía derecha",
)
ACCENTS=("#a51129","#0a4079","#a57816","#0a5b9a")
NAVY="#10274e"
GOLD="#d6a21d"


def render(event,ticket,width_mm,design,length_mm,color_preview=False):
    import ticket_printer as tp
    from four_models import _photo,_logo
    index=MODELS.index(design["plantilla"])
    accent=ACCENTS[index]
    geo=tp.geometry(width_mm,length_mm,design)
    W,H=geo["W"],geo["H"]
    X=lambda n:round(n*W/1080)
    Y=lambda n:round(n*H/576)
    rect=lambda x0,y0,x1,y1:(X(x0),Y(y0),X(x1),Y(y1))
    im=Image.new("RGB",(W,H),"white")
    ink=ImageDraw.Draw(im)
    sz=tp._setting_number(design,"tamano_letra_pct",100,70,140)/100
    hs=tp._setting_number(design,"tamano_cabecera_pct",100,70,140)/100
    ds=tp._setting_number(design,"tamano_fecha_pct",100,70,140)/100

    def txt(value,r,size=22,fill=NAVY,lines=1,small=10,factor=None):
        factor=sz if factor is None else factor
        tp._center(ImageDraw.Draw(im),str(value),
                   rect(*r),max(8,Y(size*factor)),
                   lines=lines,min_size=max(7,Y(small)),bold=True,fill=fill)

    def stroke(coords,color=accent,width=2):
        ImageDraw.Draw(im).line([(X(x),Y(y)) for x,y in coords],
            fill=color,width=max(1,Y(width)),joint="curve")

    def smooth(a,b,c,color=accent,width=2):
        coords=[]
        for i in range(33):
            t=i/32
            coords.append((
                (1-t)**2*a[0]+2*(1-t)*t*b[0]+t*t*c[0],
                (1-t)**2*a[1]+2*(1-t)*t*b[1]+t*t*c[1]))
        stroke(coords,color,width)

    def star(cx,cy,r,color=GOLD):
        polygon=[]
        for i in range(10):
            angle=-math.pi/2+i*math.pi/5
            radius=r if i%2==0 else r*.44
            polygon.append((X(cx+math.cos(angle)*radius),
                            Y(cy+math.sin(angle)*radius)))
        ImageDraw.Draw(im).polygon(polygon,fill=color)

    def snow(cx,cy,r):
        for a in range(6):
            theta=a*math.pi/3
            ex=cx+math.cos(theta)*r
            ey=cy+math.sin(theta)*r
            stroke([(cx,cy),(ex,ey)],"#3b98d2",2)

    def icon_calendar(x,y):
        d=ImageDraw.Draw(im)
        d.rounded_rectangle(rect(x,y,x+30,y+32),radius=max(1,Y(2)),
                            outline=NAVY,width=max(1,Y(2)))
        stroke([(x+2,y+10),(x+28,y+10)],NAVY,2)
        for xx in (x+8,x+16,x+24):
            for yy in (y+18,y+25):
                d.ellipse(rect(xx-1,yy-1,xx+2,yy+2),fill=NAVY)

    def icon_clock(cx,cy):
        d=ImageDraw.Draw(im)
        d.ellipse(rect(cx-16,cy-16,cx+16,cy+16),
                  outline=NAVY,width=max(1,Y(2)))
        stroke([(cx,cy-11),(cx,cy),(cx+10,cy+4)],NAVY,2)

    def icon_pin(cx,cy):
        d=ImageDraw.Draw(im)
        d.ellipse(rect(cx-10,cy-15,cx+10,cy+5),fill="white")
        d.polygon([(X(cx-9),Y(cy+2)),(X(cx+9),Y(cy+2)),(X(cx),Y(cy+15))],
                  fill="white")
        d.ellipse(rect(cx-3,cy-8,cx+3,cy-2),fill=accent)

    def draw_logo(real, bbox):
        if real is None:return
        source=real.convert("RGBA")
        if "A" in real.getbands():
            nonblank=source.getchannel("A").getbbox()
            if nonblank:source=source.crop(nonblank)
        x0,y0,x1,y1=rect(*bbox)
        fitted=ImageOps.contain(source,(max(1,x1-x0),max(1,y1-y0)),
                                method=Image.Resampling.LANCZOS)
        im.paste(fitted,(x0+(x1-x0-fitted.width)//2,
                         y0+(y1-y0-fitted.height)//2),fitted)

    # Zonas independientes E/F/G/H: (información, fotografía, control)
    if index==0:
        body=(239,808); photo_box=(810,13,1070,561); stub=(8,227)
    elif index==1:
        body=(17,611); photo_box=(618,13,839,560); stub=(845,1072)
    elif index==2:
        body=(227,831); photo_box=(11,13,218,560); stub=(841,1072)
    else:
        body=(16,613); photo_box=(620,13,837,560); stub=(844,1072)

    # Foto: la misma seleccionada por el usuario, una sola vez y SIN reflejarla
    photo=_photo(tp,index,design)
    fx=tp._setting_number(design,"foto_centro_x_pct",50,0,100)/100
    fy=tp._setting_number(design,"foto_centro_y_pct",50,0,100)/100
    zoom=max(1,tp._setting_number(design,"foto_zoom_pct",100,60,250)/100)
    x0,y0,x1,y1=photo_box
    bx0,by0,bx1,by1=rect(*photo_box)
    pw,ph=bx1-bx0,by1-by0
    full=ImageOps.fit(photo,(max(1,round(pw*zoom)),
                             max(1,round(ph*zoom))),
                      method=Image.Resampling.LANCZOS,centering=(fx,fy))
    ox=round((full.width-pw)*fx)
    oy=round((full.height-ph)*fy)
    cropped=full.crop((ox,oy,ox+pw,oy+ph))
    mask=Image.new("L",(pw,ph),0)
    md=ImageDraw.Draw(mask)
    if index==0: # foto derecha, borde interior curvo
        at=[(X(x1)-bx0,0),(X(x1)-bx0,ph),
             *[(X(836+24*math.sin(math.pi*y/576))-bx0,Y(y)-by0)
               for y in range(y1,y0-1,-4)]]
        md.polygon(at,fill=255)
    elif index==1: # foto redondeada, derecha central
        md.rounded_rectangle((2,2,pw-3,ph-3),radius=max(2,Y(18)),fill=255)
    elif index==2: # foto izquierda cortada en diagonal
        md.polygon([(0,0),(pw,0),(round(pw*.78),round(ph*.40)),
                    (round(pw*.34),ph),(0,ph)],fill=255)
    else: # foto central con borde ondulado
        at=[(pw,0),(pw,ph),*[
            (X(638+27*math.sin(math.pi*y/576))-bx0,Y(y)-by0)
            for y in range(y1,y0-1,-4)]]
        md.polygon(at,fill=255)
    im.paste(cropped,(bx0,by0),mask)
    if index==0:
        stroke([(836+24*math.sin(math.pi*y/576),y)
                for y in range(13,561,4)],"#dda320",4)
    elif index==1:
        ImageDraw.Draw(im).rounded_rectangle(rect(*photo_box),
                        radius=max(1,Y(18)),outline=GOLD,width=max(2,Y(4)))
    elif index==2:
        stroke([(x1,y0),(x0+round((x1-x0)*.78),y0+(y1-y0)*.4),
                (x0+round((x1-x0)*.34),y1)],GOLD,4)
    else:
        stroke([(638+27*math.sin(math.pi*y/576),y)
                for y in range(13,561,4)],"#47a4d8",4)
        smooth((body[0],138),(body[0]+250,123),(body[1]-10,133),
               "#8ed2f5",3)

    # Logos: NUNCA imágenes generadas, solo archivos seleccionados.
    crest=_logo(tp,design,"logo_ayto")
    school=_logo(tp,design,"logo_centro")
    short=crest is not None and crest.width <= crest.height*1.65
    L,R=body
    if short:
        draw_logo(crest,(L+5,17,L+75,122))
        if school is not None:
            draw_logo(school,(R-165,18,R-4,116))
            header_left=L+82
            header_right=R-173
        else:
            header_left=L+84
            header_right=R-5
    elif crest is not None:
        draw_logo(crest,(R-203,21,R-6,118))
        if school is not None:
            draw_logo(school,(L+3,18,L+67,112))
            header_left=L+73
        else:
            header_left=L+5
        header_right=R-211
    elif school is not None:
        draw_logo(school,(L+3,17,L+82,116))
        header_left=L+86
        header_right=R-4
    else:
        header_left=L+5
        header_right=R-4
    txt(design.get("cabecera") or "Escuela Municipal de Música y Danza",
        (header_left,18,header_right,82),31,NAVY,2,14,hs)
    txt(design.get("subtitulo") or "Arroyo de la Miel",
        (header_left,83,header_right,125),20,accent,1,12,hs)
    if index in (0,1):
        smooth((L+9,133),((L+R)/2,142),(R-9,128),GOLD,3)
    elif index==2:
        stroke([(L+8,134),(R-8,134)],GOLD,2)

    event_name=str(event.get("name") or "ESPECTÁCULO")
    d=ImageDraw.Draw(im)
    if index==0: # texto rojo clásico en dos líneas
        txt(event_name,(L+42,158,R-42,260),55,"#9f1126",2,22)
        star(L+18,220,10)
        star(R-19,220,10)
    elif index==1: # banderín
        d.polygon([(X(L+7),Y(151)),(X(R-7),Y(151)),
                   (X(R-19),Y(202)),(X(R-7),Y(251)),
                   (X(L+7),Y(251)),(X(L+20),Y(202))],
                   fill=NAVY)
        d.line([(X(L+22),Y(159)),(X(R-22),Y(159))],
               fill=GOLD,width=max(1,Y(3)))
        txt(event_name,(L+45,163,R-45,240),49,"white",2,18)
        star(L+28,201,9)
        star(R-29,201,9)
    elif index==2: # elegante / minimalista
        star(L+22,165,13,GOLD)
        txt(event_name,(L+65,156,R-35,254),56,NAVY,2,21)
        for k in range(6):
            y=190+k*9
            smooth((L+10,y),(L+18+(k%2)*8,y+6),(L+37,y+15),
                   GOLD,2)
    else: # gala blanca azul con copos
        snow(L+25,196,12)
        snow(R-23,196,12)
        txt(event_name,(L+50,149,R-48,257),56,NAVY,2,20)
        smooth((L+6,263),((L+R)/2,277),(R-8,262),
               "#7ac2eb",3)

    start=datetime.fromisoformat(str(event["start_time"]))
    mid=(L+R)/2
    date_top=282
    date_bottom=344
    date_width=(R-L)*.43
    divider=mid-4
    icon_calendar(L+8,date_top+12)
    txt(start.strftime("%d/%m/%Y"),
        (L+44,date_top,divider-15,date_bottom),33,NAVY,1,14,ds)
    stroke([(divider,date_top+11),(divider,date_bottom-12)],NAVY,2)
    icon_clock(divider+26,date_top+32)
    txt(start.strftime("%H:%M H"),
        (divider+47,date_top,R-2,date_bottom),32,NAVY,1,14,ds)

    d.rounded_rectangle(rect(L+4,354,R-4,397),
        radius=max(1,Y(13)),fill=accent)
    icon_pin(L+27,375)
    txt(design.get("lugar") or "Casa de la Cultura · Arroyo de la Miel",
        (L+49,357,R-9,392),24,"white",2,10)
    first=("SIN RESERVA DE ASIENTOS · ACCESO POR ORDEN DE LLEGADA"
           if str(event.get("mode") or "libre")=="libre"
           else "RESPETE SU FILA Y BUTACA ASIGNADAS")
    txt(first,(L+8,407,R-6,435),17,NAVY,2,9)
    stroke([(L+13,439),(R-13,439)],NAVY,1)
    txt("SE RECOMIENDA PUNTUALIDAD · INICIADA LA FUNCIÓN NO SE GARANTIZA BUTACA",
        (L+9,442,R-8,484),16,NAVY,2,8)
    stroke([(L+8,491),(R-8,491)],accent,2)
    barcode=tp._code128_image(tp.barcode_ticket_value(ticket["id"]),
                     X(R-L-60),max(20,Y(44)))
    im.paste(barcode,(X(L)+(X(R-L)-barcode.width)//2,Y(506)))

    # Control separado, a la izquierda E; a la derecha F/G/H.
    S,T=stub
    if index==0:
        stroke([(232,16),(232,560)],accent,3)
    else:
        stroke([(838,16),(838,559)],accent,3)
    d=ImageDraw.Draw(im)
    d.rounded_rectangle(rect(S+7,26,T-7,84),
        radius=max(1,Y(10)),fill=accent)
    txt("CONTROL DE ACCESO",(S+11,33,T-12,78),21,"white",2,11)
    d.rounded_rectangle(rect(S+16,99,T-15,160),
        radius=max(1,Y(9)),outline=accent,width=max(1,Y(2)))
    txt(f"N.º {int(ticket['number']):04d}",
        (S+22,108,T-21,151),29,NAVY,1,13)
    qr_area=rect(S+10,173,T-10,396)
    qr=tp._qr_image(str(ticket["qr"]),
           qr_area[2]-qr_area[0],qr_area[3]-qr_area[1])
    im.paste(qr,(qr_area[0]+(qr_area[2]-qr_area[0]-qr.width)//2,
                 qr_area[1]+(qr_area[3]-qr_area[1]-qr.height)//2))
    txt("ESCANEAR QR",(S+9,405,T-9,448),21,accent,1,11)
    stroke([(S+18,455),(T-18,455)],accent,2)
    txt(str(ticket.get("seat_label") or "").strip() or "1 PERSONA",
        (S+10,473,T-9,534),32,accent,2,13)
    if index==3:
        smooth((L+4,554),((L+R)/2,534),(R-7,557),"#94d3f8",3)
    d.rounded_rectangle(rect(5,5,1075,571),radius=max(2,Y(14)),
                        outline=accent,width=max(2,Y(3)))
    if color_preview:return im
    return im.convert("L").convert(
        "1",dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
