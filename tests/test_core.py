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
            self.assertEqual(decoded,ticket['qr'])

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
