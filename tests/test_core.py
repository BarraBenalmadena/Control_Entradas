"""Pruebas del servidor, QR, doble uso, modo numerado y exportación PDF."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest

TEMP = tempfile.TemporaryDirectory()
os.environ["CONTROL_ENTRADAS_DATA"] = TEMP.name
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))
import control_entradas as app
import ticket_printer


def assert_qr_not_deformed(testcase, img, raw_qr, paper_mm, design=None):
    """Comprueba el QR sin interpolación en la nueva geometría de impresión."""
    import numpy as np
    g=ticket_printer.geometry(paper_mm,img.width//8,design)
    s=img.height/576.0
    left=g['divider']+round(8*s)
    right=img.width-g['right_limit']-round(4*s)
    y=g['T']+round(182*g['sx'])
    qr=ticket_printer._qr_image(raw_qr,right-left-round(4*s),g['T']+round(420*g['sx'])-y)
    x=(left+right-qr.width)//2
    cropped=np.asarray(img)[y:y+qr.height,x:x+qr.width]
    testcase.assertTrue(np.array_equal(cropped,np.asarray(qr)),'El QR ha sido deformado')


class ControlEntradasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()
    def test_free_and_duplicates(self):
        e = app.create_event("Concierto libre", "2027-03-01T19:00", "libre", 3)
        with app.connect() as conn:
            ticket = conn.execute("SELECT * FROM tickets WHERE event_id=? ORDER BY number LIMIT 1",(e,)).fetchone()
        self.assertIsNone(ticket["seat_label"])
        self.assertEqual(app.validate(ticket["qr"],e,"movil1")["status"], "valid")
        self.assertEqual(app.validate(ticket["qr"],e,"movil2")["status"], "used")
        self.assertEqual(app.validate(ticket["qr"]+"z",e,"movil2")["status"], "invalid")
    def test_code128_fallback_and_double_use(self):
        e=app.create_event("Acceso alternativo","2027-04-12T19:00","libre",2)
        event,ticket=app.get_ticket(e,1)
        barcode=ticket_printer.barcode_ticket_value(ticket["id"])
        self.assertEqual(len(barcode),16)
        self.assertTrue(barcode.isdigit())
        rendered=ticket_printer.render_landscape_ticket(
            event,ticket,80,{"plantilla":ticket_printer.TEMPLATES[19],"estilo_avisos":"Clásico"})
        self.assertEqual(rendered.height,576)
        self.assertGreater(ticket_printer._code128_image(barcode,700,42).width,450)
        for paper_width in (58,80):
            picture=ticket_printer.render_landscape_ticket(
                event,ticket,paper_width,{"plantilla":ticket_printer.TEMPLATES[19],"estilo_avisos":"Clásico"})
            g=ticket_printer.geometry(paper_width,None,{})
            body_left=g["L"]+round(g["usable"]*0.034)
            body_right=g["L"]+round(g["usable"]*0.966)
            bar_y=g["T"]+round(531*g["sx"])
            bar_h=max(18,round(567*g["sx"])-round(531*g["sx"]))
            code=ticket_printer._code128_image(barcode,body_right-body_left,bar_h)
            self.assertGreaterEqual(code.width,250)
            exact_x=(body_left+body_right-code.width)//2
            from PIL import Image
            self.assertEqual(picture.crop((exact_x,bar_y,exact_x+code.width,bar_y+code.height)).tobytes(),code.tobytes())
        self.assertEqual(app.validate(barcode,e,"reader-A")["status"],"valid")
        self.assertEqual(app.validate(ticket["qr"],e,"reader-B")["status"],"used")
        self.assertEqual(app.validate("0000000000000000",e,"reader-B")["status"],"invalid")

    def test_notices_B_D_in_all_designs(self):
        e=app.create_event("Avisos visibles","2027-04-12T19:00","libre",1)
        event,ticket=app.get_ticket(e,1)
        for model in (0,2,3,19,23,34,35):
            for style in ("B · Recuadro","D · Separadores"):
                options={"plantilla":ticket_printer.TEMPLATES[model],
                         "estilo_avisos":style}
                picture=ticket_printer.render_landscape_ticket(event,ticket,80,options)
                g=ticket_printer.geometry(80,None,options)
                bar_y=g["T"]+round(499*g["sx"])
                bar_h=max(18,round(566*g["sx"])-round(499*g["sx"]))
                barcode=ticket_printer.barcode_ticket_value(ticket["id"])
                left=g["L"]+round(g["usable"]*.034)
                right=g["L"]+round(g["usable"]*.966)
                actual=ticket_printer._code128_image(barcode,right-left,bar_h)
                at=(left+right-actual.width)//2
                self.assertEqual(picture.crop((at,bar_y,at+actual.width,
                                               bar_y+bar_h)).tobytes(),actual.tobytes(),
                                 "No se debe deformar el Code128 en "+style)

    def test_gray_models_prominent_event_date_and_barcode(self):
        event_id=app.create_event("Concierto de Navidad","2027-04-12T19:00","libre",1)
        event,ticket=app.get_ticket(event_id,1)
        for model in (23,24,25,29):
            for style in ("B · Recuadro","D · Separadores"):
                design={"plantilla":ticket_printer.TEMPLATES[model],
                        "estilo_avisos":style}
                ticket_image=ticket_printer.render_landscape_ticket(event,ticket,80,design)
                g=ticket_printer.geometry(80,None,design)
                first=g["L"]+round(g["usable"]*.034)
                last=g["L"]+round(g["usable"]*.966)
                barcode=ticket_printer.barcode_ticket_value(ticket["id"])
                bar_top=g["T"]+round(499*g["sx"])
                bar_height=max(18,round(566*g["sx"])-round(499*g["sx"]))
                expected=ticket_printer._code128_image(barcode,last-first,bar_height)
                x=(first+last-expected.width)//2
                self.assertEqual(ticket_image.crop((x,bar_top,x+expected.width,
                              bar_top+expected.height)).tobytes(),expected.tobytes())
                # Numbers must be visible on gray background even with notices.
                left=g["L"]+round(g["usable"]*.018)
                right=g["L"]+round(g["usable"]*.30)
                top=g["T"]+round(155*g["sx"])
                bottom=g["T"]+round(326*g["sx"])
                region=ticket_image.crop((left,top,right,bottom)).convert("L")
                self.assertLess(region.getextrema()[0],55)

    def test_geometric_models_logo_aspect_and_poster_pan(self):
        from modern_catalog import MODELS
        from unittest.mock import patch
        from PIL import Image, ImageDraw
        from pathlib import Path
        import tempfile
        eid=app.create_event("Festival pruebas","2027-12-11T17:00","libre",1)
        event,ticket=app.get_ticket(eid,1)
        with tempfile.TemporaryDirectory() as tmp:
            art=Image.new("RGB",(260,500),"white")
            d=ImageDraw.Draw(art)
            d.rectangle((0,0,130,500),fill=(250,30,30))
            d.rectangle((130,0,260,500),fill=(25,65,220))
            poster=Path(tmp)/"portrait.png"
            art.save(poster)
            wide=Image.new("RGBA",(1800,440),(0,0,0,0))
            wd=ImageDraw.Draw(wide)
            wd.rounded_rectangle((80,80,1700,350),radius=35,fill=(0,108,215,255))
            logo=Path(tmp)/"education.png";wide.save(logo)
            p={"plantilla":MODELS[0],"poster":str(poster),
               "logo_ayto":str(logo),"foto_zoom_pct":"150",
               "foto_centro_x_pct":"0","foto_centro_y_pct":"50"}
            with patch("modern_catalog.art_path",return_value=poster):
                left=ticket_printer.render_landscape_ticket(event,ticket,80,p,
                                                            color_preview=True)
                p["foto_centro_x_pct"]="100"
                right=ticket_printer.render_landscape_ticket(event,ticket,80,p,
                                                             color_preview=True)
            self.assertNotEqual(left.crop((30,60,220,480)).tobytes(),
                                right.crop((30,60,220,480)).tobytes())
            # The photo may move, but the authenticated QR is identical.
            self.assertEqual(left.crop((830,175,1050,396)).tobytes(),
                             right.crop((830,175,1050,396)).tobytes())
            self.assertGreater(sum(1 for x in range(290,795,20)
                                     if left.getpixel((x,65))[2]>120),4)

    def test_thirty_native_styles_and_unique_secure_qr_barcode(self):
        from modern_catalog import MODELS
        from unittest.mock import patch
        from PIL import Image
        import tempfile
        self.assertEqual(len(MODELS),30)
        self.assertEqual(len(set(MODELS)),30)
        eid=app.create_event("Concierto de invierno","2027-12-10T20:15","libre",2)
        event,first=app.get_ticket(eid,1)
        _,second=app.get_ticket(eid,2)
        with tempfile.TemporaryDirectory() as tmp:
            artwork=Path(tmp)/"art_01.jpg"
            Image.new("RGB",(140,207),(170,58,46)).save(artwork)
            with patch("modern_catalog.art_path",return_value=artwork):
                for model in MODELS:
                    design={"plantilla":model}
                    img=ticket_printer.render_landscape_ticket(
                            event,first,80,design,color_preview=True)
                    self.assertEqual(img.size,(1080,576))
                    self.assertEqual(img.crop((30,70,205,360)).getpixel((0,0))[0]>0,True)
                design={"plantilla":MODELS[0]}
                a=ticket_printer.render_landscape_ticket(
                    event,first,80,design,color_preview=True)
                b=ticket_printer.render_landscape_ticket(
                    event,second,80,design,color_preview=True)
                self.assertNotEqual(a.crop((850,175,1050,400)).tobytes(),
                                    b.crop((850,175,1050,400)).tobytes())
                self.assertNotEqual(a.crop((290,493,800,560)).tobytes(),
                                    b.crop((290,493,800,560)).tobytes())
                mini=ticket_printer.render_landscape_ticket(
                    event,first,58,design,color_preview=True)
                self.assertGreater(mini.width,500)
                p=Path(tmp)/"A4.pdf"
                ticket_printer.export_catalog_pdf(event,first,p,design,
                    templates=MODELS[:4],width_mm=80,length_mm=135)
                self.assertTrue(p.read_bytes().startswith(b"%PDF-"))

    def test_primary_catalog_entries_and_a4_two_column_export(self):
        from catalog_models import CATALOG_NAMES, CATALOG_INDEX
        self.assertEqual(len(CATALOG_NAMES),25)
        self.assertEqual(len(set(CATALOG_NAMES)),25)
        self.assertEqual(len(CATALOG_INDEX),25)
        eid=app.create_event("Catálogo en papel","2027-05-01T19:00","libre",1)
        event,ticket=app.get_ticket(eid,1)
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            destination=Path(tmp)/'catalogo.pdf'
            ticket_printer.export_catalog_pdf(event,ticket,destination,
                                              {"estilo_avisos":"B · Recuadro"},
                                              templates=ticket_printer.TEMPLATES[:3],
                                              width_mm=80,length_mm=135)
            self.assertTrue(destination.read_bytes().startswith(b'%PDF-'))
            self.assertGreater(destination.stat().st_size,10000)

    def test_exact_jpg_template_keeps_reference_and_replaces_sample_codes(self):
        from unittest.mock import patch
        from PIL import Image, ImageDraw
        from pathlib import Path
        import tempfile
        from catalog_models import CATALOG_NAMES
        eid=app.create_event("FESTIVAL DE NAVIDAD","2026-11-16T19:00","libre",2)
        event,ticket=app.get_ticket(eid,1)
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/"reference.jpg"
            background=Image.new("RGB",(372,158),"white")
            painter=ImageDraw.Draw(background)
            painter.rectangle((0,0,90,157),fill=(174,20,90))
            painter.rectangle((235,0,256,50),fill=(255,215,0))
            background.save(src,quality=95)
            design={"plantilla":CATALOG_NAMES[0]}
            with patch("ticket_printer.catalog_asset",return_value=src):
                color=ticket_printer.render_landscape_ticket(event,ticket,80,design,color_preview=True)
                thermal=ticket_printer.render_landscape_ticket(event,ticket,80,design)
            self.assertEqual(color.size,thermal.size)
            self.assertLess(abs(color.getpixel((30,100))[0]-174),7)
            self.assertLessEqual(thermal.getpixel((30,100))[0],255)
            # Live QR and barcode must be freshly encoded and visible,
            # not inherited from the original JPG.
            self.assertEqual(color.crop((round(color.width*.81),round(color.height*.34),round(color.width*.94),round(color.height*.68))).convert("L").getextrema()[0],0)
            self.assertEqual(thermal.mode,"RGB")
            custom_poster=Path(folder)/"custom_poster.png"
            Image.new('RGB',(480,680),(0,205,52)).save(custom_poster)
            changed_event=dict(event)
            changed_event["name"]="DANZA DE INVIERNO"
            changed_event["start_time"]="2027-01-17T18:30"
            custom_spec={"plantilla":CATALOG_NAMES[0],
                         "poster":str(custom_poster),
                         "lugar":"Auditorio municipal"}
            with patch("ticket_printer.catalog_asset",return_value=src):
                updated=ticket_printer.render_landscape_ticket(
                    changed_event,ticket,80,custom_spec,color_preview=True)
            self.assertGreater(updated.getpixel((30,110))[1],175,
                               "Uploaded poster must replace reference image")
            self.assertNotEqual(updated.crop((360,190,700,380)).tobytes(),
                                color.crop((360,190,700,380)).tobytes(),
                                "Changing title/date/venue must update ticket")
            self.assertNotEqual(updated.crop((round(updated.width*.81),
                     round(updated.height*.40),round(updated.width*.94),
                     round(updated.height*.62))).convert('L').getextrema()[0],255)


    def test_numbered_and_other_show(self):
        e = app.create_event("Danza", "2027-03-02T19:00", "numerada", 1, 2, 3)
        self.assertEqual([x for x in app.list_events() if x["id"] == e][0]["capacity"],6)
        with app.connect() as conn:
            ticket = conn.execute("SELECT * FROM tickets WHERE event_id=? AND number=5",(e,)).fetchone()
        self.assertEqual(ticket["seat_label"], "Fila 02 · Butaca 02")
        self.assertEqual(app.validate(ticket["qr"], "otro-evento", "movil2")["status"],"wrong_event")
        pdf = Path(TEMP.name)/"salida.pdf"
        self.assertEqual(app.export_pdf(e,pdf),6)
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
    def test_thermal_single_ticket_both_widths(self):
        e = app.create_event("Teatro prueba", "2027-03-04T18:00", "libre", 2)
        event, ticket = app.get_ticket(e, 1)
        app.save_ticket_design(e, {"cabecera": "Escuela Municipal", "subtitulo": "Arroyo de la Miel"})
        self.assertEqual(app.get_ticket_design(e)["cabecera"], "Escuela Municipal")
        for width, pixels in [(58, 384), (80, 576)]:
            image = ticket_printer.render_ticket(event, ticket, width, app.get_ticket_design(e))
            self.assertEqual(image.width, pixels)
            landscape = ticket_printer.render_landscape_ticket(event,ticket,width,app.get_ticket_design(e))
            self.assertGreater(landscape.width,landscape.height)
            self.assertEqual(landscape.height,pixels)
            pdf = Path(TEMP.name)/f"ticket_{width}.pdf"
            ticket_printer.export_single_pdf(event, ticket, pdf, width, app.get_ticket_design(e))
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))
            command = ticket_printer._escpos_bytes(image, cut=False)
            self.assertTrue(command.startswith(b"\x1b\x40"))
            self.assertFalse(command.endswith(b"\x1d\x56\x42\x00"))

    def test_delete_event_removes_all_tickets(self):
        e = app.create_event('Borrable','2027-06-01T19:00','libre',2)
        app.save_ticket_design(e,{'poster_mode':'lateral'})
        res = app.delete_event(e)
        self.assertEqual(res['issued'],2)
        self.assertFalse(any(x['id']==e for x in app.list_events()))
        with self.assertRaises(ValueError):
            app.get_ticket(e,1)
        self.assertEqual(app.get_ticket_design(e),{})

    def test_landscape_qr_is_readable_after_print_rotation(self):
        import cv2
        import numpy as np
        e = app.create_event('Semana Santa 2026','2026-03-27T18:00','libre',1)
        event,ticket=app.get_ticket(e,1)
        for width in (58,80):
            im=ticket_printer.render_landscape_ticket(event,ticket,width,{'cabecera':'Escuela Municipal de Música y Danza'})
            # Comprobar que el QR ESC/POS miniatura se lee, sin interpolación.
            gray=cv2.cvtColor(np.array(im),cv2.COLOR_RGB2GRAY)
            if width==58:  # detector en baja resolución; el móvil puede enfocar más de cerca.
                gray=cv2.resize(gray,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST)
            decoded,_,_=cv2.QRCodeDetector().detectAndDecode(gray)
            assert_qr_not_deformed(self,im,ticket['qr'],width)

    def test_concurrent_double_scan(self):
        e=app.create_event("Simultáneo", "2027-03-03T19:00", "libre", 1)
        with app.connect() as conn:
            qr=conn.execute("SELECT qr FROM tickets WHERE event_id=?",(e,)).fetchone()["qr"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            result=list(pool.map(lambda i: app.validate(qr,e,str(i))["status"], range(8)))
        self.assertEqual(result.count("valid"),1)
        self.assertEqual(result.count("used"),7)

if __name__ == "__main__":
    unittest.main()

class SixDesignsAndBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()

    def test_ten_horizontal_templates_scannable_at_58_and_80(self):
        import cv2
        import numpy as np
        from PIL import Image, ImageDraw
        image_path = Path(TEMP.name)/'cartel.jpg'
        poster=Image.new('RGB',(230,640),'white')
        draw=ImageDraw.Draw(poster)
        draw.rectangle((0,0,228,638),fill='#555555')
        draw.ellipse((25,140,205,320),fill='#dddddd')
        poster.save(image_path)
        e=app.create_event('Festival municipal de danza', '2027-07-01T20:30','libre',2)
        event,ticket=app.get_ticket(e,1)
        for width in (58,80):
            for template in ticket_printer.TEMPLATES:
                with self.subTest(width=width,template=template):
                    design={'plantilla':template,'poster':str(image_path),'ajuste_imagen':'Rellenar y recortar','tamano_logos':'Grandes'}
                    im=ticket_printer.render_landscape_ticket(event,ticket,width,design)
                    self.assertEqual(im.height,ticket_printer.PRINTABLE_DOTS[width])
                    self.assertGreater(im.width,im.height)
                    gray=cv2.cvtColor(np.asarray(im),cv2.COLOR_RGB2GRAY)
                    if width==58:
                        gray=cv2.resize(gray,None,fx=2,fy=2,interpolation=cv2.INTER_NEAREST)
                    decoded,_,_=cv2.QRCodeDetector().detectAndDecode(gray)
                    assert_qr_not_deformed(self,im,ticket['qr'],width)

    def test_multi_print_one_job_three_separate_cuts(self):
        from unittest.mock import patch
        e=app.create_event('Concierto', '2027-11-20T19:00', 'libre', 3)
        pairs=[app.get_ticket(e,n) for n in (1,2,3)]
        with patch.object(ticket_printer,'send_raw',return_value=101) as send:
            job=ticket_printer.print_windows_escpos_batch(pairs,'ZYWELL test',80,
                        {'plantilla':ticket_printer.TEMPLATES[1]},True,feed_dots=48)
            self.assertEqual(job,101)
            self.assertEqual(send.call_count,1)
            raw=send.call_args.args[1]
            self.assertEqual(raw.count(b'\x1d\x56\x00'),3)
            self.assertEqual(raw.count(b'\x1b\x4a\x30\x1d\x56\x00'),3)
            self.assertEqual(raw.count(b'\x1b\x40'),1)  # un reset por lote

    def test_original_soft_background_preserved(self):
        e=app.create_event('Concierto', '2027-11-20T19:00', 'libre', 1)
        event,ticket=app.get_ticket(e,1)
        legacy=ticket_printer.render_landscape_ticket(event,ticket,80,{'poster_mode':'fondo'})
        explicit=ticket_printer.render_landscape_ticket(event,ticket,80,{'plantilla':ticket_printer.TEMPLATES[3]})
        self.assertEqual(legacy.tobytes(),explicit.tobytes())

class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()

    def test_largo_seleccionable_qr_se_mantiene_legible(self):
        import cv2
        import numpy as np
        e=app.create_event('Ensayo de longitud','2027-10-15T20:00','libre',1)
        event,ticket=app.get_ticket(e,1)
        for paper in (58,80):
            for length in ((90,105,120) if paper == 58 else (120,135,165)):
                with self.subTest(paper=paper,length=length):
                    img=ticket_printer.render_landscape_ticket(event,ticket,paper,{},length_mm=length)
                    self.assertEqual(img.size,(length*8,ticket_printer.PRINTABLE_DOTS[paper]))
                    # El QR tiene siempre píxeles nativos (sin interpolación),
                    # pero el talón cambia su origen cuando cambia la longitud.
                    scale=img.height / 576
                    px=lambda x:round(x*scale)
                    g=ticket_printer.geometry(paper,length,{})
                    divider=g['divider']
                    stub_left=divider+px(8)
                    stub_right=img.width-g['right_limit']-px(4)
                    y=g['T']+round(182*g['sx'])
                    qr_image=ticket_printer._qr_image(ticket['qr'],stub_right-stub_left-px(4),g['T']+round(424*g['sx'])-y)
                    x=(stub_left+stub_right-qr_image.width)//2
                    roi=np.asarray(img)[y-3:y+qr_image.height+3,
                                       x-3:x+qr_image.width+3]
                    gray=cv2.cvtColor(roi,cv2.COLOR_RGB2GRAY)
                    decoded,_,_=cv2.QRCodeDetector().detectAndDecode(gray)
                    assert_qr_not_deformed(self,img,ticket['qr'],paper)

    def test_corte_automatico_escpos(self):
        from PIL import Image
        image=Image.new('RGB',(576,120),'white')
        manual=ticket_printer._escpos_bytes(image,cut=True,feed_dots=120,
                                            cut_mode=ticket_printer.CUT_MODES[0])
        automatic=ticket_printer._escpos_bytes(image,cut=True,feed_dots=120,
                                               cut_mode=ticket_printer.CUT_MODES[1])
        self.assertTrue(manual.endswith(b'\x1b\x4ax\x1d\x56\x00'))
        self.assertTrue(automatic.endswith(b'\x1d\x56\x41\x00'))
        self.assertNotIn(b'\x1b\x4ax',automatic)
        with self.assertRaises(ValueError):
            ticket_printer._escpos_bytes(image,cut=True,cut_mode='desconocido')


class LayoutRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()

    def test_longitudes_y_galeria_exactas_sin_escalar_contenido(self):
        from PIL import Image
        e=app.create_event('Gala cultural 2027','2027-09-11T20:00','libre',1)
        ev,t=app.get_ticket(e,1)
        for width, lengths in ((58,(90,120)),(80,(120,135,165))):
            for length in lengths:
                for template in ticket_printer.TEMPLATES:
                    with self.subTest(width=width,length=length,template=template):
                        design={'plantilla':template,'desplazamiento_mm':'0'}
                        img=ticket_printer.render_landscape_ticket(ev,t,width,design,length_mm=length)
                        self.assertEqual(img.size,(length*8,ticket_printer.PRINTABLE_DOTS[width]))
                        raw=ticket_printer.render_ticket(ev,t,width,design,length_mm=length)
                        self.assertEqual(raw.size,(ticket_printer.PRINTABLE_DOTS[width],length*8))
                        # Las franjas finales son blancas para que el cortador
                        # no atraviese la numeración, el QR ni el contorno.
                        self.assertEqual(img.crop((0,0,5,img.height)).getextrema(),((255,255),)*3)
                        self.assertEqual(img.crop((img.width-5,0,img.width,img.height)).getextrema(),((255,255),)*3)

    def test_desplazar_arte_sin_alterar_largo_ni_qr(self):
        e=app.create_event('Prueba offset','2027-09-12T20:00','libre',1)
        ev,t=app.get_ticket(e,1)
        results=[]
        for offset in ('-3','0','3'):
            design={'plantilla':ticket_printer.TEMPLATES[2],'desplazamiento_mm':offset}
            im=ticket_printer.render_landscape_ticket(ev,t,80,design,length_mm=135)
            self.assertEqual(im.size,(1080,576))
            results.append(im.tobytes())
        self.assertNotEqual(results[0],results[1])
        self.assertNotEqual(results[1],results[2])
        with self.assertRaises(ValueError):
            ticket_printer.render_landscape_ticket(ev,t,80,{'desplazamiento_mm':'20'})

    def test_corte_automatico_por_ticket_y_un_reset_por_lote(self):
        from unittest.mock import patch
        e=app.create_event('Prueba lotes','2027-10-12T20:00','libre',3)
        pairs=[app.get_ticket(e,n) for n in (1,2,3)]
        with patch.object(ticket_printer,'send_raw',return_value=123) as mocked:
            ticket_printer.print_windows_escpos_batch(pairs,'ZYWELL',80,{},True,
                full_cut=True,feed_dots=0,cut_mode=ticket_printer.CUT_MODES[1],length_mm=135)
            raw=mocked.call_args.args[1]
            self.assertEqual(raw.count(b'\x1d\x56\x41\x00'),3)
            self.assertEqual(raw.count(b'\x1b\x40'),1)


class ZywellFirmwareCompatibilityTests(unittest.TestCase):
    """Pruebas sin hardware: bytes RAW y secuenciación de cortes."""
    def test_command_zywell_documentado_despues_de_todas_las_franjas(self):
        from PIL import Image
        img=Image.new('RGB',(576,525),'white')
        raw=ticket_printer._escpos_bytes(img,cut=True,
                     cut_mode=ticket_printer.CUT_MODES[2],feed_dots=240)
        self.assertTrue(raw.endswith(b'\x1d\x56\x42\x00'))
        self.assertFalse(raw.endswith(b'\x1d\x56\x41\x00'))
        self.assertEqual(raw.count(b'\x1d\x76\x30\x00'),3)
        pos=raw.rfind(b'\x1d\x76\x30\x00')
        # última franja de 45 filas, 576/8 bytes por fila, 8 bytes cabecera
        self.assertEqual(pos+8+45*72, len(raw)-4)

    def test_avance_grande_se_fragmenta_sin_desbordamiento(self):
        from PIL import Image
        raw=ticket_printer._escpos_bytes(Image.new('RGB',(576,10),'white'),
                cut=True, cut_mode=ticket_printer.CUT_MODES[0],feed_dots=520)
        self.assertTrue(raw.endswith(b'\x1b\x4a\xff\x1b\x4a\xff\x1b\x4a\x0a\x1d\x56\x00'))
        with self.assertRaises(ValueError):
            ticket_printer._escpos_bytes(Image.new('RGB',(576,10),'white'),feed_dots=801)

    def test_calibracion_corta_despues_de_imprimir_sin_usar_entradas(self):
        from unittest.mock import patch
        with patch.object(ticket_printer,'send_raw',return_value=77) as send:
            self.assertEqual(ticket_printer.print_cut_calibration('TEST',80),77)
            raw=send.call_args.args[1]
            self.assertTrue(raw.endswith(b'\x1d\x56\x42\x00'))
            self.assertEqual(raw.count(b'\x1d\x76\x30\x00'),2)
            self.assertEqual(send.call_args.args[2],'Prueba ZYWELL - NO ES ENTRADA')

class TenDesignsAndMarginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.init_db()

    def test_ten_templates_and_six_logo_positions(self):
        from PIL import Image, ImageDraw
        poster_path=Path(TEMP.name)/'test_poster_v09.png'
        logo1=Path(TEMP.name)/'test_logo1_v09.png'
        logo2=Path(TEMP.name)/'test_logo2_v09.png'
        poster=Image.new('RGB',(480,350),'white')
        d=ImageDraw.Draw(poster)
        d.rectangle((10,10,470,340),fill='#888888')
        d.ellipse((100,50,350,300),fill='#111111')
        poster.save(poster_path)
        for path,fill in ((logo1,'black'),(logo2,'#444444')):
            im=Image.new('RGB',(120,120),'white')
            ImageDraw.Draw(im).ellipse((6,6,114,114),fill=fill)
            im.save(path)
        e=app.create_event('Gala de Danza de la Escuela Municipal','2027-12-20T19:00','libre',1)
        event,ticket=app.get_ticket(e,1)
        images=[]
        self.assertEqual(len(ticket_printer.TEMPLATES),36)
        for template in ticket_printer.TEMPLATES:
            for position in ticket_printer.LOGO_POSITIONS:
                with self.subTest(template=template,logos=position):
                    design={'plantilla':template,'posicion_logos':position,
                            'poster':str(poster_path),'logo_ayto':str(logo1),'logo_centro':str(logo2),
                            'margen_izquierdo_mm':'2','margen_derecho_mm':'3',
                            'margen_superior_mm':'1','margen_inferior_mm':'2'}
                    img=ticket_printer.render_landscape_ticket(event,ticket,80,design,length_mm=135)
                    self.assertEqual(img.size,(1080,576))
                    assert_qr_not_deformed(self,img,ticket['qr'],80,design)
                    if position=='Según plantilla': images.append(img.tobytes())
        self.assertEqual(len(set(images)),36,'Las treinta y seis plantillas deben ser composiciones distintas')

    def test_margins_change_physical_whitespace_and_keep_ticket_length(self):
        e=app.create_event('Ensayo de márgenes','2027-10-24T19:00','libre',1)
        event,ticket=app.get_ticket(e,1)
        small={'margen_izquierdo_mm':'1','margen_derecho_mm':'1'}
        large={'margen_izquierdo_mm':'12','margen_derecho_mm':'12'}
        a=ticket_printer.render_landscape_ticket(event,ticket,80,small,length_mm=150)
        b=ticket_printer.render_landscape_ticket(event,ticket,80,large,length_mm=150)
        self.assertEqual(a.size,b.size)
        self.assertNotEqual(a.tobytes(),b.tobytes())
        self.assertEqual(b.crop((0,0,90,b.height)).getextrema(),((255,255),)*3)
        self.assertEqual(b.crop((b.width-90,0,b.width,b.height)).getextrema(),((255,255),)*3)
        assert_qr_not_deformed(self,b,ticket['qr'],80,large)
        with self.assertRaises(ValueError):
            ticket_printer.geometry(80,120,{'margen_izquierdo_mm':'19'})
        with self.assertRaises(ValueError):
            ticket_printer.geometry(80,120,{'margen_superior_mm':'50'})

    def test_custom_fonts_and_vertical_margins(self):
        e=app.create_event('Gala','2027-10-24T19:00','libre',1)
        ev,t=app.get_ticket(e,1)
        custom={'margen_superior_mm':'5','margen_inferior_mm':'4',
                'tamano_letra_pct':'130','tamano_cabecera_pct':'90','tamano_fecha_pct':'120'}
        img=ticket_printer.render_landscape_ticket(ev,t,80,custom,length_mm=145)
        self.assertEqual(img.crop((0,0,img.width,24)).getextrema(),((255,255),)*3)
        assert_qr_not_deformed(self,img,t['qr'],80,custom)
        with self.assertRaises(ValueError):
            ticket_printer.render_landscape_ticket(ev,t,80,{'tamano_fecha_pct':'200'})

if __name__ == '__main__':
    unittest.main()


class TestQrThermalReadability(unittest.TestCase):
    def test_80mm_qr_uses_at_least_three_printer_dots_per_module(self):
        e=app.create_event("Lectura QR tamaño mejorado", "2027-05-01T20:00", "libre", 1)
        ev,t=app.get_ticket(e,1)
        import qrcode
        q=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=1,border=4)
        q.add_data(t['qr']);q.make(fit=True)
        im=ticket_printer.render_landscape_ticket(ev,t,80,{},length_mm=135)
        g=ticket_printer.geometry(80,135,{})
        cell=(g['stub']-12)//(q.modules_count+8)
        self.assertGreaterEqual(cell,3)
        assert_qr_not_deformed(self,im,t['qr'],80)