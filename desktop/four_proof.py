"""Genera una prueba gráfica real de los cuatro modelos del motor.

Se ejecuta en CI con datos de demostración; los QR no corresponden a entradas
de clientes. La foto de prueba ocupa el lateral completo para verificar el JPG.
"""
import os
import tempfile
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

if True:
    # Windows mantiene temporalmente abierta la base SQLite; el runner
    # elimina los archivos al finalizar, sin forzar limpieza prematura.
    folder=tempfile.mkdtemp(prefix='control_proof_')
    os.environ['CONTROL_ENTRADAS_DATA']=folder
    import control_entradas as app
    import ticket_printer
    from four_models import MODELS
    app.init_db()
    event_id=app.create_event("FESTIVAL DE NAVIDAD",
                              "2026-12-16T19:00","libre",1)
    event,ticket=app.get_ticket(event_id,1)
    art=Image.new('RGB',(600,900),'#351c44')
    artist=ImageDraw.Draw(art)
    for y in range(900):
        artist.line((0,y,600,y),
            fill=(min(255,68+y//6),25+y//45,72+y//25))
    for pos in range(10):
        y=pos*100+40
        artist.ellipse((100,y,520,y+80),outline='#ffd790',width=9)
    artist.rectangle((95,260,500,670),fill='#76263f',outline='#fff7db',width=6)
    artist.text((122,350),"CARTEL JPG",fill='white')
    artist.text((132,400),"DEL USUARIO",fill='white')
    path=Path(folder)/'mi_cartel.jpg'
    art.save(path,quality=93)

    destination=Path(__file__).resolve().parent.parent/'dist-prototipos'
    destination.mkdir(parents=True,exist_ok=True)
    design={'poster':str(path),'logo_ayto':'',
            'cabecera':'Escuela Municipal de Música y Danza',
            'subtitulo':'Arroyo de la Miel',
            'lugar':'Casa de la Cultura · Arroyo de la Miel'}
    for n,model in enumerate(MODELS):
        spec=dict(design,plantilla=model)
        color=ticket_printer.render_landscape_ticket(
            event,ticket,80,spec,color_preview=True)
        mono=ticket_printer.render_landscape_ticket(
            event,ticket,80,spec,color_preview=False)
        color.save(destination/f'Modelo_{n+1}_color.png')
        mono.save(destination/f'Modelo_{n+1}_BN.png')
    ticket_printer.export_catalog_pdf(
        event,ticket,destination/'Ocho_modelos_A4.pdf',design,
        templates=MODELS,width_mm=80,length_mm=135)
    print("Ocho modelos A-H generados desde el mismo renderizador del EXE.")
