"""Integration tests for v1.0: numbered seating and signed JSON export."""
import sys, tempfile, json, unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'desktop'))
import control_entradas as app
import seat_plan
import ticket_printer


class V1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):app.init_db()

    def test_signed_json_and_tamper_rejection(self):
        eid=app.create_event('Concierto offline','2027-03-01T20:00','libre',4)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'funcion.json'
            self.assertEqual(app.export_offline_event(eid,target),4)
            package=json.loads(target.read_text('utf-8'))
            self.assertNotIn('PRIVATE',target.read_text('utf-8'))
            data=app.verify_offline_file(target)
            self.assertEqual(data['event']['id'],eid)
            self.assertEqual(len(data['tickets']),4)
            package['payload']=package['payload']+'x'
            target.write_text(json.dumps(package),'utf-8')
            with self.assertRaises(Exception):app.verify_offline_file(target)

    def test_plan_reserve_move_and_import(self):
        eid=app.create_event('Plano numerado','2027-04-01T20:00','numerada',1,3,4)
        seats,_=seat_plan.seat_data(app.DB_PATH,eid)
        self.assertEqual(len(seats),12)
        key=seats[0]['id'];self.assertFalse(seats[0]['reserved'])
        self.assertTrue(seat_plan.toggle_reserved(app.DB_PATH,key))
        self.assertFalse(seat_plan.toggle_reserved(app.DB_PATH,key))
        seat_plan.update_position(app.DB_PATH,key,.62,.48)
        seats,_=seat_plan.seat_data(app.DB_PATH,eid)
        self.assertAlmostEqual(seats[0]['x'],.62)
        with tempfile.TemporaryDirectory() as folder:
            img=Path(folder)/'plano.png';Image.new('RGB',(900,600),'white').save(img)
            imported=seat_plan.import_plan(app.DB_PATH,eid,img,folder)
            self.assertTrue(imported.exists())
            _,stored=seat_plan.seat_data(app.DB_PATH,eid)
            self.assertEqual(stored,str(imported))
            seat_plan.toggle_reserved(app.DB_PATH,key)
            target=Path(folder)/'evento.json'
            app.export_offline_event(eid,target)
            item=app.verify_offline_file(target)['tickets'][0]
            self.assertTrue(item['reserved'])
            self.assertIn('Fila 01',item['seat'])

    def test_sixteen_templates_and_qr(self):
        self.assertEqual(len(ticket_printer.TEMPLATES),24)
        eid=app.create_event('Gala','2027-03-12T19:00','libre',1)
        ev,t=app.get_ticket(eid,1)
        for label in ticket_printer.TEMPLATES:
            with self.subTest(template=label):
                im=ticket_printer.render_landscape_ticket(ev,t,80,{'plantilla':label})
                self.assertEqual(im.size,(1080,576))

    def test_plan_rejects_free_access(self):
        eid=app.create_event('Libre','2027-05-04T19:00','libre',2)
        with self.assertRaises(ValueError):seat_plan.seat_data(app.DB_PATH,eid)

if __name__=='__main__':unittest.main()
