"""Control de Entradas 0.8 - largo variable y corte con autocalibración alternativa.

Software de demostración para validar el flujo de entrada libre y numerada.
Se usa ECDSA P-256 para verificar la autenticidad de los QR.
"""
from __future__ import annotations

import base64
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import io
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
import threading
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature

import ticket_printer  # Required by barcode validation in headless Windows server

VERSION = "2.24"
PORT = 8765
DATA_DIR = Path(os.environ.get("CONTROL_ENTRADAS_DATA", str(Path.home() / "Documents" / "ControlEntradas")))
DB_PATH = DATA_DIR / "entradas.sqlite3"
KEY_PATH = DATA_DIR / "clave_privada.pem"
PIN_PATH = DATA_DIR / "pin.txt"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64u(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def load_or_create_key():
    if KEY_PATH.exists():
        return serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
    key = ec.generate_private_key(ec.SECP256R1())
    KEY_PATH.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    try:
        KEY_PATH.chmod(0o600)
    except OSError:
        pass
    return key


PRIVATE_KEY = load_or_create_key()
PUBLIC_KEY_DER = PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
)
ACCESS_PIN = PIN_PATH.read_text(encoding="utf-8").strip() if PIN_PATH.exists() else ""
if not (len(ACCESS_PIN) == 6 and ACCESS_PIN.isdecimal()):
    ACCESS_PIN = f"{secrets.randbelow(1000000):06d}"
    PIN_PATH.write_text(ACCESS_PIN, encoding="utf-8")


def connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db():
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                start_time TEXT NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('libre','numerada')),
                capacity INTEGER NOT NULL CHECK (capacity > 0),
                rows_count INTEGER NOT NULL DEFAULT 0,
                seats_per_row INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL REFERENCES events(id),
                number INTEGER NOT NULL,
                seat_label TEXT,
                qr TEXT NOT NULL,
                used_at TEXT,
                used_by TEXT,
                UNIQUE(event_id, number)
            );
            CREATE INDEX IF NOT EXISTS idx_tickets_event ON tickets(event_id);
            CREATE TABLE IF NOT EXISTS ticket_print_log (
                ticket_id TEXT PRIMARY KEY,
                submitted_at TEXT NOT NULL,
                FOREIGN KEY(ticket_id) REFERENCES tickets(id)
            );
            CREATE TABLE IF NOT EXISTS event_last_print_batch (
                event_id TEXT PRIMARY KEY REFERENCES events(id),
                numbers_json TEXT NOT NULL,
                submitted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ticket_design (
                event_id TEXT PRIMARY KEY REFERENCES events(id),
                data TEXT NOT NULL
            );
        """)

    from seat_plan import ensure_schema
    ensure_schema(DB_PATH)

def iso_now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_event_fields(name: str, start_time: str, mode: str,
                          capacity: int, rows_count: int = 0,
                          seats_per_row: int = 0):
    """Validación compartida entre crear y modificar una función."""
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("Indica un nombre de 1 a 120 caracteres.")
    datetime.fromisoformat(start_time)
    if mode not in ("libre", "numerada"):
        raise ValueError("Modalidad inválida.")
    capacity = int(capacity)
    rows_count = int(rows_count)
    seats_per_row = int(seats_per_row)
    if mode == "numerada":
        if rows_count < 1 or seats_per_row < 1:
            raise ValueError("Indica filas y butacas por fila.")
        capacity = rows_count * seats_per_row
    if capacity < 1 or capacity > 5000:
        raise ValueError("El aforo debe estar entre 1 y 5000.")
    return name, start_time, mode, capacity, rows_count, seats_per_row


def _create_signed_ticket(conn, event_id: str, number: int,
                          mode: str, seats_per_row: int):
    ticket_id = uuid.uuid4().hex
    seat = None
    if mode == "numerada":
        row = (number - 1) // seats_per_row + 1
        seat_number = (number - 1) % seats_per_row + 1
        seat = f"Fila {row:02d} · Butaca {seat_number:02d}"
    payload = json.dumps(
        {"v": 1, "id": ticket_id, "e": event_id, "n": number, "s": seat},
        ensure_ascii=False, separators=(",", ":"))
    payload64 = b64u(payload.encode("utf-8"))
    signed = PRIVATE_KEY.sign(payload64.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    qr = "CE1." + payload64 + "." + b64u(signed)
    conn.execute("INSERT INTO tickets(id, event_id, number, seat_label, qr) "
                 "VALUES (?,?,?,?,?)", (ticket_id, event_id, number, seat, qr))


def create_event(name: str, start_time: str, mode: str, capacity: int,
                 rows_count: int = 0, seats_per_row: int = 0):
    name, start_time, mode, capacity, rows_count, seats_per_row = (
        validate_event_fields(name, start_time, mode, capacity,
                              rows_count, seats_per_row))
    event_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (event_id, name, start_time, mode, capacity, rows_count, seats_per_row, iso_now()))
        for n in range(1, capacity + 1):
            _create_signed_ticket(conn, event_id, n, mode, seats_per_row)
        conn.commit()
    return event_id



def update_event(event_id: str, name: str, start_time: str, mode: str,
                 capacity: int, rows_count: int = 0, seats_per_row: int = 0):
    """Corrige una función SIN crear otra ni invalidar sus códigos QR existentes.

    Nombre y fecha son editables siempre. Los cambios de aforo/modalidad se
    permiten antes de imprimir, registrar accesos o configurar butacas. Si el
    aforo libre cambia, se conservan los QR de los números que permanecen.
    """
    name, start_time, mode, capacity, rows_count, seats_per_row = (
        validate_event_fields(name, start_time, mode, capacity,
                              rows_count, seats_per_row))
    with connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT * FROM events WHERE id=?",
                               (event_id,)).fetchone()
            if old is None:
                raise ValueError("La función que deseas modificar ya no existe.")
            changed_structure = (
                old["mode"] != mode
                or old["capacity"] != capacity
                or (mode=="numerada" and
                    (old["rows_count"]!=rows_count or
                     old["seats_per_row"]!=seats_per_row)))
            if changed_structure:
                already_used = conn.execute(
                    "SELECT COUNT(*) FROM tickets WHERE event_id=? "
                    "AND used_at IS NOT NULL", (event_id,)).fetchone()[0]
                printed = conn.execute(
                    "SELECT COUNT(*) FROM ticket_print_log p "
                    "JOIN tickets t ON p.ticket_id=t.id WHERE t.event_id=?",
                    (event_id,)).fetchone()[0]
                batch = conn.execute(
                    "SELECT 1 FROM event_last_print_batch WHERE event_id=?",
                    (event_id,)).fetchone()
                positions = conn.execute(
                    "SELECT COUNT(*) FROM seat_positions sp JOIN tickets t "
                    "ON sp.ticket_id=t.id WHERE t.event_id=?",
                    (event_id,)).fetchone()[0]
                seatplan = conn.execute(
                    "SELECT 1 FROM seat_plans WHERE event_id=?",
                    (event_id,)).fetchone()
                if already_used or printed or batch or positions or seatplan:
                    raise ValueError(
                        "No se puede cambiar aforo, filas ni modalidad porque "
                        "ya existen accesos, entradas impresas o un plano de "
                        "butacas. Sí puedes corregir nombre, fecha y hora "
                        "sin modificar los códigos QR.")
                if mode == old["mode"] == "libre":
                    # Conservar ID y QR de todos los números existentes.
                    if capacity < old["capacity"]:
                        conn.execute("DELETE FROM tickets WHERE event_id=? "
                                     "AND number>?", (event_id, capacity))
                    elif capacity > old["capacity"]:
                        for n in range(old["capacity"]+1,capacity+1):
                            _create_signed_ticket(conn,event_id,n,mode,
                                                  seats_per_row)
                else:
                    # Cambio de modalidad/filas, aún sin códigos distribuidos:
                    # se genera una serie nueva con el MISMO ID de función.
                    conn.execute("DELETE FROM tickets WHERE event_id=?",
                                 (event_id,))
                    for n in range(1,capacity+1):
                        _create_signed_ticket(conn,event_id,n,mode,
                                              seats_per_row)
            conn.execute(
                "UPDATE events SET name=?,start_time=?,mode=?,capacity=?,"
                "rows_count=?,seats_per_row=? WHERE id=?",
                (name,start_time,mode,capacity,rows_count,seats_per_row,
                 event_id))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return event_id


def list_events():
    with connect() as conn:
        rows = conn.execute("""SELECT e.*, (SELECT COUNT(*) FROM tickets t WHERE t.event_id=e.id AND t.used_at IS NOT NULL) AS used,
                         (SELECT COUNT(*) FROM tickets t WHERE t.event_id=e.id) AS issued
                         FROM events e ORDER BY e.start_time DESC""").fetchall()
        return [dict(x) for x in rows]


def record_print_submission(event_id: str, numbers):
    """Registra entradas enviadas a la cola de la impresora (no confirma salida física)."""
    current=sorted({int(n) for n in numbers})
    if not current: raise ValueError('Lote de impresión vacío')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for number in current:
            row=db.execute('SELECT id FROM tickets WHERE event_id=? AND number=?',(event_id,number)).fetchone()
            if not row: raise ValueError(f'Entrada {number} inexistente')
            db.execute('INSERT OR REPLACE INTO ticket_print_log(ticket_id,submitted_at) VALUES (?,?)',
                       (row['id'],iso_now()))
        db.execute('INSERT OR REPLACE INTO event_last_print_batch(event_id,numbers_json,submitted_at) VALUES (?,?,?)',
                   (event_id,json.dumps(current),iso_now()))
        db.commit()


def export_offline_event(event_id: str, target: Path):
    """Signed offline snapshot. Private key never leaves Windows.

    Authoritative for one scanner only; for multiple phones coordinate via a
    common host or assign disjoint ticket-number ranges.
    """
    with connect() as db:
        event=db.execute('SELECT * FROM events WHERE id=?',(event_id,)).fetchone()
        if event is None:raise ValueError('La función no existe.')
        batch=db.execute('SELECT numbers_json FROM event_last_print_batch WHERE event_id=?',(event_id,)).fetchone()
        if not batch:
            raise ValueError('No hay último lote registrado. Imprime las entradas y después exporta el JSON.')
        numbers=json.loads(batch['numbers_json'])
        if not numbers: raise ValueError('El último lote de impresión está vacío.')
        placeholders=','.join('?' for _ in numbers)
        tickets=db.execute(f"SELECT t.id,t.number,t.seat_label,t.used_at, COALESCE(s.reserved,0) reserved, p.submitted_at printed_at FROM tickets t LEFT JOIN seat_positions s ON s.ticket_id=t.id LEFT JOIN ticket_print_log p ON p.ticket_id=t.id WHERE t.event_id=? AND t.number IN ({placeholders}) ORDER BY t.number",(event_id,*numbers)).fetchall()
    if not tickets: raise ValueError('No hay entradas enviadas a impresión. Imprime primero y luego exporta este JSON.')
    data={'version':1,'created_at':iso_now(),'event':dict(event),
          'tickets':[{'id':t['id'],'number':t['number'],'seat':t['seat_label'],
                      'used':bool(t['used_at']),'used_at':t['used_at'],'reserved':bool(t['reserved']),
                      'submitted_to_printer':bool(t['printed_at'])} for t in tickets]}
    data64=b64u(json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
    signature=PRIVATE_KEY.sign(data64.encode('ascii'),ec.ECDSA(hashes.SHA256()))
    package={'format':'CE-OFFLINE-1','public_key':base64.b64encode(PUBLIC_KEY_DER).decode('ascii'),
             'payload':data64,'signature':b64u(signature)}
    target=Path(target)
    target.write_text(json.dumps(package,ensure_ascii=False,indent=2),encoding='utf-8')
    return len(tickets)


def import_offline_access_log(path: Path):
    """Merge local Android approvals. The document is an administrative log, not a signed attestation."""
    report=json.loads(Path(path).read_text(encoding='utf-8'))
    if report.get('format')!='CE-ACCESS-1':raise ValueError('Formato de registro de accesos no reconocido.')
    event_id=str(report.get('event_id',''))
    tids=report.get('ticket_ids')
    if not isinstance(tids,list) or len(tids)>5000 or len(tids)!=len(set(tids)):
        raise ValueError('Lista de entradas inválida o repetida')
    if not all(isinstance(item,str) and len(item)==32 for item in tids):
        raise ValueError('Identificador de entrada inválido')
    device=str(report.get('device_id','desconocido'))[:80]
    added=0;already=0;unknown=0
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM events WHERE id=?',(event_id,)).fetchone():
            raise ValueError('No existe esta función en Windows')
        for tid in tids:
            row=db.execute('SELECT used_at FROM tickets WHERE id=? AND event_id=?',(tid,event_id)).fetchone()
            if row is None:unknown+=1
            elif row['used_at'] is not None:already+=1
            else:
                db.execute('UPDATE tickets SET used_at=?,used_by=? WHERE id=? AND event_id=? AND used_at IS NULL',(iso_now(),'offline:'+device,tid,event_id))
                added+=1
    return {'added':added,'already':already,'unknown':unknown,'total':len(tids)}


def verify_offline_file(path: Path):
    package=json.loads(Path(path).read_text('utf-8'))
    if package.get('format')!='CE-OFFLINE-1':raise ValueError('Formato de exportación incorrecto')
    pub=serialization.load_der_public_key(base64.b64decode(package['public_key']))
    pub.verify(unb64u(package['signature']),package['payload'].encode('ascii'),ec.ECDSA(hashes.SHA256()))
    return json.loads(unb64u(package['payload']))


def reset_event_accesses(event_id: str) -> int:
    """Restablece accesos del servidor Windows, sin tocar tickets ni números QR."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            count=db.execute('SELECT COUNT(*) FROM tickets WHERE event_id=? AND used_at IS NOT NULL',(event_id,)).fetchone()[0]
            db.execute('UPDATE tickets SET used_at=NULL, used_by=NULL WHERE event_id=?',(event_id,))
            db.commit()
            return count
        except Exception:
            db.rollback()
            raise


def delete_event(event_id: str) -> dict:
    """Eliminación transaccional irreversible de función y todos sus tickets.

    El cliente debe pedir confirmación explícita antes de llamar aquí.
    """
    with connect() as conn:
        try:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT id,name FROM events WHERE id=?', (event_id,)).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError('La función ya no existe.')
            used = conn.execute('SELECT COUNT(*) FROM tickets WHERE event_id=? AND used_at IS NOT NULL', (event_id,)).fetchone()[0]
            issued = conn.execute('SELECT COUNT(*) FROM tickets WHERE event_id=?', (event_id,)).fetchone()[0]
            conn.execute('DELETE FROM event_last_print_batch WHERE event_id=?', (event_id,))
            conn.execute('DELETE FROM ticket_design WHERE event_id=?', (event_id,))
            conn.execute('DELETE FROM ticket_print_log WHERE ticket_id IN (SELECT id FROM tickets WHERE event_id=?)', (event_id,))
            conn.execute('DELETE FROM tickets WHERE event_id=?', (event_id,))
            conn.execute('DELETE FROM events WHERE id=?', (event_id,))
            conn.commit()
            return {'name': row['name'], 'issued': issued, 'used': used}
        except Exception:
            conn.rollback()
            raise


def get_ticket_design(event_id: str) -> dict:
    with connect() as conn:
        row = conn.execute('SELECT data FROM ticket_design WHERE event_id=?', (event_id,)).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row['data'])
    except (ValueError, TypeError):
        return {}


def save_ticket_design(event_id: str, design: dict):
    with connect() as conn:
        conn.execute('INSERT OR REPLACE INTO ticket_design(event_id,data) VALUES (?,?)',
                     (event_id, json.dumps(design, ensure_ascii=False)))


def get_ticket(event_id: str, number: int) -> tuple[dict, dict]:
    with connect() as conn:
        event = conn.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        ticket = conn.execute('SELECT * FROM tickets WHERE event_id=? AND number=?', (event_id, number)).fetchone()
    if event is None or ticket is None:
        raise ValueError('No existe la entrada indicada para esa función.')
    return dict(event), dict(ticket)


def parse_qr(qr: str):
    parts = qr.split(".")
    if len(parts) != 3 or parts[0] != "CE1" or len(qr) > 1800:
        raise ValueError("Formato QR inválido")
    data, signature = parts[1], parts[2]
    PRIVATE_KEY.public_key().verify(unb64u(signature), data.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    payload = json.loads(unb64u(data))
    if payload.get("v") != 1 or not isinstance(payload.get("id"), str) or not isinstance(payload.get("e"), str):
        raise ValueError("Datos QR inválidos")
    return payload


def validate(qr: str, event_id: str, device_id: str) -> dict:
    if isinstance(qr,str) and len(qr)==16 and qr.isascii() and qr.isdigit():
        # Code128 is a bearer token; lookup is restricted to this event,
        # and uses the same single-use transaction as the signed QR.
        with connect() as conn:
            matches=conn.execute("SELECT id,number,seat_label,used_at FROM tickets WHERE event_id=?",(event_id,)).fetchall()
        target=[t for t in matches if ticket_printer.barcode_ticket_value(t["id"])==qr]
        if len(target)!=1:
            return {"status":"invalid","message":"CÓDIGO DE BARRAS DESCONOCIDO"}
        ticket_id=target[0]["id"]
        payload={"id":ticket_id,"e":event_id}
        # Barcode never bypasses event registration; verified by issued UUID.
        expected_qr=None
    else:
        try:
            payload = parse_qr(qr)
        except (InvalidSignature, ValueError, TypeError, UnicodeError, json.JSONDecodeError, KeyError):
            return {"status": "invalid", "message": "QR O BARRAS NO VÁLIDO"}
        expected_qr=qr
    if payload["e"] != event_id:
        return {"status": "wrong_event", "message": "ENTRADA DE OTRA FUNCIÓN"}
    with connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            ticket = conn.execute("SELECT number, seat_label, qr, used_at FROM tickets WHERE id=? AND event_id=?", (payload["id"], event_id)).fetchone()
            if not ticket or (expected_qr is not None and ticket["qr"] != expected_qr):
                conn.rollback()
                return {"status": "invalid", "message": "ENTRADA DESCONOCIDA"}
            if ticket["used_at"]:
                conn.rollback()
                return {"status": "used", "message": "ENTRADA YA UTILIZADA", "number": ticket["number"], "seat": ticket["seat_label"], "used_at": ticket["used_at"]}
            used_at = iso_now()
            result = conn.execute("UPDATE tickets SET used_at=?, used_by=? WHERE id=? AND used_at IS NULL", (used_at, str(device_id)[:120], payload["id"]))
            if result.rowcount != 1:
                conn.rollback()
                return {"status": "used", "message": "ENTRADA YA UTILIZADA"}
            conn.commit()
            return {"status": "valid", "message": "ACCESO PERMITIDO", "number": ticket["number"], "seat": ticket["seat_label"], "used_at": used_at}
        except Exception:
            conn.rollback()
            raise


class ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, payload: dict, status: int = 200):
        value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(value)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(value)

    def authorized(self):
        if not secrets.compare_digest(self.headers.get("X-Access-Pin", ""), ACCESS_PIN):
            self.send_json({"error": "PIN de acceso incorrecto"}, 401)
            return False
        return True

    def do_GET(self):
        if self.path != "/api/status":
            self.send_json({"error": "Ruta no encontrada"}, 404)
            return
        if not self.authorized():
            return
        self.send_json({"version": VERSION, "public_key": base64.b64encode(PUBLIC_KEY_DER).decode("ascii"), "events": list_events()})

    def do_POST(self):
        if self.path != "/api/validate":
            self.send_json({"error": "Ruta no encontrada"}, 404)
            return
        if not self.authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 4000:
                raise ValueError("Tamaño de petición inválido")
            body = json.loads(self.rfile.read(length))
            if not all(isinstance(body.get(x), str) for x in ("qr", "event_id", "device_id")):
                raise ValueError("Faltan datos")
            self.send_json(validate(body["qr"], body["event_id"], body["device_id"]))
        except (ValueError, TypeError, json.JSONDecodeError):
            self.send_json({"error": "Petición inválida"}, 400)
        except Exception:
            self.send_json({"error": "Error interno"}, 500)


def start_server():
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), ApiHandler)
    thread = threading.Thread(target=httpd.serve_forever, name="API de control", daemon=True)
    thread.start()
    return httpd


def lan_ips():
    ips = set()
    try:
        for v in socket.gethostbyname_ex(socket.gethostname())[2]:
            addr = ipaddress.ip_address(v)
            if addr.is_private and not addr.is_loopback:
                ips.add(v)
    except OSError:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("192.0.2.1", 9))
        addr = sock.getsockname()[0]
        if addr and not addr.startswith("127."):
            ips.add(addr)
        sock.close()
    except OSError:
        pass
    return sorted(ips)


def export_pdf(event_id: str, target: Path):
    import qrcode
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    with connect() as conn:
        e = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not e:
            raise ValueError("Función no encontrada")
        tickets = conn.execute("SELECT number, seat_label, qr FROM tickets WHERE event_id=? ORDER BY number", (event_id,)).fetchall()
    pdf = canvas.Canvas(str(target), pagesize=A4)
    W, H = A4
    margin, col_gap, row_gap = 28, 12, 12
    card_w = (W - 2*margin - col_gap) / 2
    card_h = (H - 2*margin - 2*row_gap) / 3
    for index, ticket in enumerate(tickets):
        slot = index % 6
        if slot == 0 and index:
            pdf.showPage()
        x = margin + (slot % 2) * (card_w + col_gap)
        y = H - margin - (slot // 2 + 1)*card_h - (slot//2)*row_gap
        pdf.setFillColor(colors.HexColor("#f5f8fc"))
        pdf.roundRect(x, y, card_w, card_h, 9, stroke=0, fill=1)
        pdf.setFillColor(colors.HexColor("#1768a8"))
        pdf.roundRect(x, y + card_h - 40, card_w, 40, 9, stroke=0, fill=1)
        pdf.rect(x, y+card_h-40, card_w, 20, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(x+12, y+card_h-19, "ESCUELA MUNICIPAL DE MÚSICA Y DANZA")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(x+12, y+card_h-32, "CONTROL DE ENTRADAS · CASA DE LA CULTURA")
        pdf.setFillColor(colors.HexColor("#102b43"))
        pdf.setFont("Helvetica-Bold", 13)
        event_name = e["name"][:37]
        pdf.drawString(x+12, y+card_h-59, event_name)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(x+12, y+card_h-78, f"Fecha: {datetime.fromisoformat(e['start_time']).strftime('%d/%m/%Y  %H:%M')}")
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(x+12, y+card_h-100, f"Entrada N.º {ticket['number']:04d}")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(x+12, y+card_h-115, ticket["seat_label"] or "Entrada libre · Sin butaca asignada")
        qr_image = qrcode.make(ticket["qr"])
        qr_buf = io.BytesIO()
        qr_image.save(qr_buf, format="PNG")
        qr_buf.seek(0)
        qr_size = 90
        pdf.drawImage(ImageReader(qr_buf), x + card_w - qr_size - 13, y+22, width=qr_size, height=qr_size)
        pdf.setFont("Helvetica", 7)
        notice = [
            "Se recomienda máxima puntualidad.",
            "Una vez iniciado el espectáculo, no se",
            "garantiza el acceso al asiento.",
        ]
        if e["mode"] == "libre":
            notice += ["Prohibido reservar asientos.", "Orden de acceso según llegada a la fila."]
        else:
            notice += ["Ocupar exclusivamente la butaca asignada."]
        for n, line in enumerate(notice):
            pdf.drawString(x+12, y+65-n*11, line)
    pdf.save()
    return len(tickets)


def launch_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    import subprocess

    root = tk.Tk()
    root.title(f"Control de Entradas · v{VERSION}")
    screen_w=root.winfo_screenwidth()
    screen_h=root.winfo_screenheight()
    root.geometry(f"{min(1150,max(790,screen_w-80))}x{min(910,max(560,screen_h-100))}")
    root.minsize(760, 510)
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg="#eef3f8")
    style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=(13, 9))
    style.configure("Other.TButton", font=("Segoe UI", 10), padding=(10, 8))

    # Scroll real de la ventana principal, además del que tiene la tabla.
    # El marco puede medir más que la pantalla; no se recortan acciones.
    page = ttk.Frame(root)
    page.pack(fill="both", expand=True)
    page_canvas = tk.Canvas(page, highlightthickness=0, background="#eef3f8")
    page_scroll = ttk.Scrollbar(page, orient="vertical", command=page_canvas.yview)
    page_canvas.configure(yscrollcommand=page_scroll.set)
    page_scroll.pack(side="right", fill="y")
    page_canvas.pack(side="left", fill="both", expand=True)
    container = ttk.Frame(page_canvas, padding=(16, 12))
    page_window = page_canvas.create_window((0,0),window=container,anchor="nw")
    container.bind("<Configure>",lambda *_: page_canvas.configure(
        scrollregion=page_canvas.bbox("all")))
    page_canvas.bind("<Configure>",lambda e: page_canvas.itemconfigure(
        page_window,width=e.width))
    def main_wheel(event):
        # No secuestrar la rueda en la tabla ni en controles con scroll propio.
        widget=event.widget
        if widget.winfo_toplevel() is not root:
            return
        cursor=widget
        while cursor is not root:
            if isinstance(cursor,(ttk.Treeview,ttk.Combobox,ttk.Scrollbar,
                                  tk.Text,tk.Listbox)):
                return
            cursor=cursor.master
            if cursor is None: return
        if event.num in (4,5):
            direction=-1 if event.num==4 else 1
        elif event.delta:
            direction=-1 if event.delta>0 else 1
        else:
            return
        page_canvas.yview_scroll(direction*3,"units")
        return "break"
    root.bind("<MouseWheel>",main_wheel,add="+")
    root.bind("<Button-4>",main_wheel,add="+")
    root.bind("<Button-5>",main_wheel,add="+")
    ttk.Label(container, text="CONTROL DE ENTRADAS", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(container, text="Escuela Municipal de Música y Danza · v2.24 · Gestión y validación", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 8))

    net_frame = ttk.LabelFrame(container, text="Conexión de lectores Android", padding=(10, 7))
    net_frame.pack(fill="x")
    urls = "   ·   ".join("http://" + ip + ":" + str(PORT) for ip in lan_ips()) or "Consulta la dirección IPv4 del ordenador (ipconfig)"
    ttk.Label(net_frame, text="Servidor: " + urls, wraplength=900).pack(anchor="w")
    ttk.Label(net_frame, text="PIN de conexión: " + ACCESS_PIN, font=("Segoe UI", 12, "bold")).pack(anchor="w")
    import hashlib
    fingerprint=hashlib.sha256(PUBLIC_KEY_DER).hexdigest().upper()[:16]
    ttk.Label(net_frame, text="Huella firma para JSON offline: " + fingerprint).pack(anchor="w")
    ttk.Label(net_frame, text="Con servidor Windows se usa Wi-Fi local. Para funcionar sin él, exporta un JSON firmado e impórtalo en la APK.").pack(anchor="w")

    net_frame.pack_forget()
    connection_button = ttk.Button(container, text="Mostrar conexión / PIN / huella de firma", style="Other.TButton")
    connection_button.pack(fill="x", pady=(0, 4))
    def toggle_connection():
        if net_frame.winfo_manager():
            net_frame.pack_forget()
            connection_button.configure(text="Mostrar conexión / PIN / huella de firma")
        else:
            net_frame.pack(before=form, fill="x")
            connection_button.configure(text="Ocultar datos de conexión")
    connection_button.configure(command=toggle_connection)

    form = ttk.LabelFrame(container, text="1. Crear y guardar una función", padding=(10, 7))
    form.pack(fill="x", pady=(9, 0))
    name = tk.StringVar()
    date = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y 19:00"))
    mode = tk.StringVar(value="libre")
    capacity = tk.StringVar(value="100")
    rows = tk.StringVar(value="10")
    seats = tk.StringVar(value="10")
    ttk.Label(form, text="Nombre").grid(row=0, column=0, sticky="w", pady=3)
    ttk.Entry(form, textvariable=name, width=38).grid(row=0, column=1, sticky="ew", padx=(5, 15))
    ttk.Label(form, text="Fecha y hora (dd/mm/aaaa hh:mm)").grid(row=0, column=2, sticky="w")
    ttk.Entry(form, textvariable=date, width=21).grid(row=0, column=3, sticky="ew", padx=(5, 0))
    ttk.Label(form, text="Modalidad").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Combobox(form, textvariable=mode, values=("libre", "numerada"), state="readonly", width=18).grid(row=1, column=1, sticky="w", padx=5)
    ttk.Label(form, text="Aforo libre").grid(row=1, column=2, sticky="w")
    capacity_entry = ttk.Entry(form, textvariable=capacity, width=9)
    capacity_entry.grid(row=1, column=3, sticky="w", padx=5)
    ttk.Label(form, text="Filas").grid(row=2, column=0, sticky="w")
    rows_entry = ttk.Entry(form, textvariable=rows, width=9)
    rows_entry.grid(row=2, column=1, sticky="w", padx=5)
    ttk.Label(form, text="Butacas por fila").grid(row=2, column=2, sticky="w")
    seats_entry = ttk.Entry(form, textvariable=seats, width=9)
    seats_entry.grid(row=2, column=3, sticky="w", padx=5)
    form.columnconfigure(1, weight=1)
    form.columnconfigure(3, weight=1)

    def toggle_mode(*_):
        is_free = mode.get() == "libre"
        capacity_entry.configure(state="normal" if is_free else "disabled")
        rows_entry.configure(state="disabled" if is_free else "normal")
        seats_entry.configure(state="disabled" if is_free else "normal")
    mode.trace_add("write", toggle_mode)
    toggle_mode()

    # Borrador local: cada edición de los seis campos se conserva para poder
    # recuperar el formulario tras cerrar Windows o pulsar otras opciones.
    draft_file=DATA_DIR/'borrador_funcion.json'
    fields={'name':name,'date':date,'mode':mode,'capacity':capacity,
            'rows':rows,'seats':seats}
    editing_id=[None]
    draft_timer=[None]
    loading_fields=[False]
    def persist_draft():
        draft_timer[0]=None
        payload={key:var.get() for key,var in fields.items()}
        payload['editing_event_id']=editing_id[0]
        temporary=draft_file.with_name(draft_file.name+'.tmp')
        try:
            temporary.write_text(
                json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(temporary,draft_file)
        except OSError as error:
            # Sin fingir que se ha guardado un borrador si el disco falla.
            print(f'No se pudo guardar el borrador: {error}',file=sys.stderr)
    def draft_changed(*_):
        if loading_fields[0]:return
        if draft_timer[0] is not None:
            try:root.after_cancel(draft_timer[0])
            except ValueError:pass
        draft_timer[0]=root.after(600,persist_draft)
    def load_into_form(values):
        loading_fields[0]=True
        try:
            for key,var in fields.items():
                if key in values:
                    var.set(str(values[key]))
        finally:
            loading_fields[0]=False
        draft_changed()
    if draft_file.is_file():
        try:
            prior=json.loads(draft_file.read_text(encoding='utf-8'))
            if isinstance(prior,dict):
                load_into_form(prior)
                remembered=prior.get('editing_event_id')
                if isinstance(remembered,str) and len(remembered)==32:
                    with connect() as db:
                        if db.execute("SELECT 1 FROM events WHERE id=?",
                                      (remembered,)).fetchone():
                            editing_id[0]=remembered
        except (OSError,ValueError,TypeError):
            pass
    for var in fields.values():
        var.trace_add('write',draft_changed)

    # These controls deliberately appear BEFORE the expandable table.
    toolbar = ttk.Frame(container)
    toolbar.pack(fill="x", pady=(12, 6))
    create_btn = ttk.Button(toolbar, text="GUARDAR NUEVA FUNCIÓN", style="Action.TButton")
    create_btn.pack(side="left", padx=(0, 7))
    edit_btn = ttk.Button(toolbar, text="EDITAR SELECCIONADA", style="Other.TButton")
    edit_btn.pack(side="left", padx=(0, 7))
    new_btn = ttk.Button(toolbar, text="NUEVA FUNCIÓN", style="Other.TButton")
    new_btn.pack(side="left", padx=(0, 7))
    draft_status=tk.StringVar(value="Formulario recuperable automáticamente en este equipo.")
    preview_btn = ttk.Button(toolbar, text="2 · Vista previa", style="Other.TButton")
    save_btn = ttk.Button(toolbar, text="3 · Guardar PDF", style="Other.TButton")
    print_btn = ttk.Button(toolbar, text="4 · Imprimir...", style="Other.TButton")

    helptext = tk.StringVar(value="Primero guarda una función. Después selecciónala en la tabla para ver, guardar o imprimir sus entradas.")
    ttk.Label(container, textvariable=helptext, foreground="#214f73", wraplength=940).pack(anchor="w", pady=(0, 5))
    ttk.Label(container,textvariable=draft_status,foreground="#356650",
              wraplength=930).pack(anchor="w",pady=(0,5))

    zywell_btn = ttk.Button(container, text="2 · DISEÑAR / PREVISUALIZAR / IMPRIMIR TICKETS ZYWELL", style="Action.TButton")
    zywell_btn.pack(fill="x", pady=(0, 8))


    other_actions=ttk.Frame(container)
    other_actions.pack(fill='x',pady=(0,7))
    plan_btn=ttk.Button(other_actions,text='PLANO DE BUTACAS · Clicar y reservar',style='Action.TButton')
    plan_btn.pack(side='left',fill='x',expand=True,padx=(0,6))
    offline_btn=ttk.Button(other_actions,text='EXPORTAR JSON PARA APK (SIN IP)',style='Action.TButton')
    offline_btn.pack(side='left',fill='x',expand=True,padx=(6,0))
    sync_btn=ttk.Button(container,text='IMPORTAR ACCESOS DE MÓVILES (JSON)',style='Other.TButton')
    sync_btn.pack(fill='x',pady=(0,7))

    list_frame = ttk.LabelFrame(container, text="Funciones guardadas (selecciona una)", padding=9)
    list_frame.pack(fill="both", expand=True)
    cols = ("nombre", "fecha", "tipo", "aforo", "accesos")
    tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=9, selectmode="browse")
    for col, label, width in zip(cols, ("Espectáculo", "Fecha y hora", "Modalidad", "Aforo", "Accesos"), (300, 160, 110, 75, 95)):
        tree.heading(col, text=label)
        tree.column(col, width=width, anchor="center" if col in ("aforo", "accesos") else "w")
    scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    footer = ttk.Frame(container)
    footer.pack(fill="x", pady=(6, 0))
    ttk.Label(footer, text=f"Guardado automático en: {DATA_DIR}", foreground="#446274").pack(side="left")
    refresh_btn = ttk.Button(footer, text="Actualizar accesos")
    refresh_btn.pack(side="right")
    delete_btn = ttk.Button(footer, text="Eliminar función seleccionada")
    delete_btn.pack(side="right", padx=(0,10))

    def update_buttons(*_):
        state = "normal" if tree.selection() else "disabled"
        for button in (edit_btn,preview_btn, save_btn, print_btn, delete_btn, zywell_btn, plan_btn, offline_btn, sync_btn):
            button.configure(state=state)

    def refresh():
        previous = tree.selection()
        for iid in tree.get_children():
            tree.delete(iid)
        for ev in list_events():
            tree.insert("", "end", iid=ev["id"], values=(ev["name"], datetime.fromisoformat(ev["start_time"]).strftime("%d/%m/%Y %H:%M"), ev["mode"], ev["capacity"], f"{ev['used']} / {ev['issued']}"))
        if previous and tree.exists(previous[0]):
            tree.selection_set(previous[0])
        update_buttons()

    def set_editing(event_id):
        editing_id[0]=event_id
        create_btn.configure(text=('GUARDAR CAMBIOS' if event_id
                                  else 'GUARDAR NUEVA FUNCIÓN'))
        draft_status.set(
            'Editando una función existente. GUARDAR CAMBIOS conserva sus '
            'entradas y códigos QR; el formulario se recupera al reiniciar.'
            if event_id else
            'Nueva función. Los datos introducidos se guardan automáticamente '
            'como borrador en este ordenador.')
        draft_changed()

    def create():
        try:
            stamp = datetime.strptime(date.get().strip(),
                                       "%d/%m/%Y %H:%M").isoformat(
                                           timespec="minutes")
            existing=editing_id[0]
            if existing:
                event_id=update_event(existing,name.get(),stamp,mode.get(),
                                      int(capacity.get()),int(rows.get()),
                                      int(seats.get()))
                action="modificada"
            else:
                event_id=create_event(name.get(),stamp,mode.get(),
                                      int(capacity.get()),int(rows.get()),
                                      int(seats.get()))
                action="creada"
            set_editing(event_id)
            persist_draft()
            refresh()
            tree.selection_set(event_id)
            tree.see(event_id)
            update_buttons()
            helptext.set(
                f'Función {action} correctamente. Para corregir algo, '
                'cambia el formulario y pulsa GUARDAR CAMBIOS. '
                'No se creará otra función con el mismo nombre.')
            messagebox.showinfo(
                "Datos guardados",f'Función {action} correctamente.\n\n'
                'Puedes seguir modificando estos datos y pulsar GUARDAR '
                'CAMBIOS, o elegir NUEVA FUNCIÓN para comenzar otra.',
                parent=root)
        except Exception as ex:
            messagebox.showerror("No se pudo guardar", str(ex),parent=root)

    def selected_event():
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Selecciona una función", "Haz clic sobre una función de la tabla antes de continuar.")
            return None
        return selected[0]

    def edit_selected():
        event_id=selected_event()
        if not event_id:return
        item=next((e for e in list_events() if e['id']==event_id),None)
        if item is None:
            messagebox.showerror("Editar función","La función ya no existe.",
                                 parent=root)
            return
        if editing_id[0]!=event_id and name.get().strip():
            if not messagebox.askyesno(
                "Cargar datos guardados",
                "Vas a cargar los datos de la función seleccionada en el "
                "formulario. El borrador actual será sustituido. "
                "¿Continuar?",parent=root):
                return
        set_editing(event_id)
        load_into_form({
            'name':item['name'],
            'date':datetime.fromisoformat(item['start_time']).strftime(
                "%d/%m/%Y %H:%M"),
            'mode':item['mode'],
            'capacity':str(item['capacity']),
            'rows':str(item['rows_count']),
            'seats':str(item['seats_per_row']),
        })
        persist_draft()
        helptext.set('Modifica los campos que quieras y pulsa GUARDAR CAMBIOS. '
                     'La función se actualizará sin duplicarse.')
        page_canvas.yview_moveto(0)

    def new_form():
        if name.get().strip() and not messagebox.askyesno(
            "Comenzar otra función",
            "Se reemplazará el formulario actual por uno nuevo. "
            "Los datos de la función ya guardada seguirán en la tabla. "
            "¿Continuar?",parent=root):
            return
        set_editing(None)
        load_into_form({
            'name':'',
            'date':datetime.now().strftime("%d/%m/%Y 19:00"),
            'mode':'libre','capacity':'100','rows':'10','seats':'10'
        })
        persist_draft()
        helptext.set('Introduce los datos de la nueva función. '
                     'Se guardan automáticamente como borrador.')
        page_canvas.yview_moveto(0)

    def delete_selected():
        event_id = selected_event()
        if not event_id:
            return
        e = next((ev for ev in list_events() if ev['id']==event_id), None)
        if e is None:
            refresh()
            return
        text = (f"Eliminar la función: {e['name']}\n\n"
                f"Se eliminarán {e['issued']} entradas, incluidos {e['used']} accesos registrados.\n"
                "La operación no se puede deshacer y sus códigos QR dejarán de ser válidos en el servidor.\n\n"
                "¿Confirmas la eliminación definitiva?")
        if not messagebox.askyesno('ELIMINAR FUNCIÓN',text,parent=root,icon='warning'):
            return
        try:
            import shutil
            delete_event(event_id)
            imgs = DATA_DIR / 'imagenes' / event_id
            if imgs.is_dir():
                shutil.rmtree(imgs)
            refresh()
            helptext.set('Función eliminada. Puedes crear una nueva desde el formulario.')
        except Exception as ex:
            messagebox.showerror('No se pudo eliminar',str(ex),parent=root)

    def open_file(path):
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def print_office_pdf(pdf_path,parent):
        # Selector explícito de impresora de oficina. Windows recibe páginas
        # gráficas a través de su driver; no se abre un visor ni se envía RAW.
        names=ticket_printer.office_printers()
        if not names:
            messagebox.showerror('Impresora A4',
                'No se ha detectado ninguna impresora de oficina en Windows. '
                'Instala o conecta una impresora A4 y pulsa de nuevo.',parent=parent)
            return
        last=DATA_DIR/'impresora_a4.txt'
        previous=last.read_text(encoding='utf-8').strip() if last.is_file() else ''
        selected=tk.StringVar(value=previous if previous in names else names[0])
        chooser=tk.Toplevel(parent)
        chooser.title('Enviar a impresora normal A4')
        chooser.geometry('530x205')
        chooser.transient(parent)
        chooser.grab_set()
        panel=ttk.Frame(chooser,padding=16)
        panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='Selecciona la impresora A4 de Windows',
                  font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(0,10))
        ttk.Combobox(panel,textvariable=selected,values=names,
                     state='readonly',width=56).pack(fill='x',pady=(0,10))
        ttk.Label(panel,text='Impresión directa por el controlador de Windows. '
                  'La impresora ZYWELL se utiliza en su apartado separado.',
                  wraplength=470).pack(anchor='w')
        buttons=ttk.Frame(panel)
        buttons.pack(fill='x',pady=(13,0))
        def send():
            name=selected.get()
            try:
                job,pages=ticket_printer.print_pdf_windows(Path(pdf_path),name)
                last.write_text(name,encoding='utf-8')
            except Exception as ex:
                messagebox.showerror('Impresión A4',str(ex),parent=chooser)
                return
            chooser.destroy()
            messagebox.showinfo('Enviado a Windows',
                f'{pages} página(s) enviadas a la cola de {name}. '
                f'Trabajo {job}. Comprueba la impresión física.',
                parent=parent)
        ttk.Button(buttons,text='Cancelar',command=chooser.destroy).pack(side='right',padx=4)
        ttk.Button(buttons,text='IMPRIMIR A4 AHORA',command=send,
                   style='Action.TButton').pack(side='right',padx=4)

    def preview_file():
        event_id = selected_event()
        if not event_id:
            return None
        try:
            preview_dir = DATA_DIR / "Vistas_previas"
            preview_dir.mkdir(exist_ok=True)
            path = preview_dir / f"Entradas_{event_id[:8]}.pdf"
            amount = export_pdf(event_id, path)
            return path, amount
        except Exception as ex:
            messagebox.showerror("Error al preparar el PDF", str(ex))
            return None

    def preview():
        result = preview_file()
        if result:
            try:
                open_file(result[0])
                helptext.set(f"Vista previa abierta ({result[1]} entradas). En el lector de PDF puedes ampliar y pasar páginas.")
            except Exception as ex:
                messagebox.showerror("No se pudo abrir", f"El PDF se guardó en:\n{result[0]}\n\nError: {ex}")

    def save_pdf():
        event_id = selected_event()
        if not event_id:
            return
        filename = "Entradas_" + event_id[:8] + ".pdf"
        target = filedialog.asksaveasfilename(title="Guardar entradas en PDF", initialdir=str(DATA_DIR), initialfile=filename,
                                              defaultextension=".pdf", filetypes=[("Documento PDF", "*.pdf")])
        if target:
            try:
                qty = export_pdf(event_id, Path(target))
                helptext.set(f"PDF guardado: {target} ({qty} entradas).")
                if messagebox.askyesno("PDF guardado", f"Se han guardado {qty} entradas en:\n{target}\n\n¿Quieres abrirlo para verlas?"):
                    open_file(Path(target))
            except Exception as ex:
                messagebox.showerror("No se pudo guardar el PDF", str(ex))

    def print_pdf():
        result = preview_file()
        if result:
            print_office_pdf(result[0],root)

    def open_thermal_ticket():
        event_id = selected_event()
        if not event_id:
            return
        import shutil
        import ticket_printer
        from catalog_models import CATALOG_NAMES
        from modern_catalog import MODELS as MODERN_MODELS
        from four_models import MODELS as FOUR_MODELS
        from PIL import Image, ImageTk

        event = next((item for item in list_events() if item['id'] == event_id), None)
        if event is None:
            messagebox.showerror('Función inexistente', 'La función seleccionada ya no existe.')
            return
        win=tk.Toplevel(root)
        win.title('Diseñador de entradas · v2.23')
        screen_w=win.winfo_screenwidth()
        screen_h=win.winfo_screenheight()
        window_w=min(1180,max(780,screen_w-70))
        window_h=min(840,max(580,screen_h-100))
        win.geometry(f'{window_w}x{window_h}+{max(0,(screen_w-window_w)//2)}+{max(0,(screen_h-window_h)//3)}')
        win.minsize(750,550)
        win.transient(root)
        outer=ttk.Frame(win,padding=12)
        outer.pack(fill='both',expand=True)
        outer.columnconfigure(0,weight=1)
        outer.rowconfigure(2,weight=1)
        ttk.Label(outer,text='12 MODELOS DE ENTRADAS · A–L',font=('Segoe UI',16,'bold')).grid(row=0,column=0,sticky='w')
        ttk.Label(outer,text=f"{event['name']}  ·  {event['capacity']} entradas  ·  {event['mode']}").grid(row=1,column=0,sticky='w',pady=(0,6))

        config=get_ticket_design(event_id)
        prefs_path=DATA_DIR/'impresora.json'
        try:
            prefs=json.loads(prefs_path.read_text(encoding='utf-8'))
        except (FileNotFoundError,ValueError):
            prefs={}
        start_num=tk.StringVar(value='1')
        qty=tk.StringVar(value='1')
        roll=tk.StringVar(value=str(prefs.get('ancho','80')))
        printers=ticket_printer.list_windows_printers()
        printer=tk.StringVar(value=prefs.get('impresora',''))
        if not printer.get() and printers:
            printer.set(next((n for n in printers if 'zywell' in n.lower() or 'pos-' in n.lower()),printers[0]))
        cut=tk.BooleanVar(value=bool(prefs.get('corte_v04',True)))
        cut_type=tk.StringVar(value=prefs.get('tipo_corte','Completo'))
        feed=tk.StringVar(value=str(prefs.get('avance_corte','240')))
        legacy_mode=prefs.get('modo_corte')
        # Perfiles anteriores probados sin exito: ofrecer compatibilidad ZYWELL
        # por defecto en esta nueva version (se puede elegir manualmente otro).
        if prefs.get('version_perfil_corte') not in ('0.8','0.9') or legacy_mode not in ticket_printer.CUT_MODES:
            legacy_mode=ticket_printer.CUT_MODES[2]
        cut_mode=tk.StringVar(value=legacy_mode)
        # La nueva geometría se configura una sola vez; nunca se pisa
        # una medida que el usuario haya elegido después de la migración.
        new_geometry=prefs.get('perfil_geometria')!='entrada_4_fiel_v1'
        default_length=('165' if roll.get()=='80' else '110')
        length=tk.StringVar(value=default_length if new_geometry else
                            str(prefs.get('largo_ticket',default_length)))
        chosen=config.get('plantilla')
        migrando_a_cuatro=chosen not in FOUR_MODELS
        if migrando_a_cuatro:
            # Resguardar selección anterior SIN borrar sus imágenes ni datos.
            if chosen in MODERN_MODELS+CATALOG_NAMES+ticket_printer.TEMPLATES:
                archive=DATA_DIR/'Respaldos_disenos'
                archive.mkdir(parents=True,exist_ok=True)
                file=archive/(event_id+'.json')
                if not file.exists():
                    file.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
            chosen=FOUR_MODELS[0]
        variables={
            'plantilla':tk.StringVar(value=chosen),
            'ajuste_imagen':tk.StringVar(value='Rellenar y recortar'),
            'foto_centro_x_pct':tk.StringVar(value=str(config.get('foto_centro_x_pct','50'))),
            'foto_centro_y_pct':tk.StringVar(value=str(config.get('foto_centro_y_pct','50'))),
            'foto_zoom_pct':tk.StringVar(value=str(config.get('foto_zoom_pct','100'))),
            'modo_impresion':tk.StringVar(value=config.get('modo_impresion','Normal')),
            'estilo_avisos':tk.StringVar(value=config.get('estilo_avisos','Según modelo')), 
            'tamano_logos':tk.StringVar(value=config.get('tamano_logos','Pequeños')),
            'tamano_logo_pct':tk.StringVar(value=str(config.get('tamano_logo_pct','150'))),
            'estilo_escudo':tk.StringVar(value=config.get('estilo_escudo','Solo escudo')),
            'posicion_logos':tk.StringVar(value=config.get('posicion_logos','Según plantilla')),
            'margen_izquierdo_mm':tk.StringVar(value=str(config.get('margen_izquierdo_mm','2'))),
            'margen_derecho_mm':tk.StringVar(value=str(config.get('margen_derecho_mm','2'))),
            'margen_superior_mm':tk.StringVar(value=str(config.get('margen_superior_mm','1'))),
            'margen_inferior_mm':tk.StringVar(value=str(config.get('margen_inferior_mm','1'))),
            'tamano_letra_pct':tk.StringVar(value=str(config.get('tamano_letra_pct','100'))),
            'tamano_cabecera_pct':tk.StringVar(value=str(config.get('tamano_cabecera_pct','100'))),
            'tamano_fecha_pct':tk.StringVar(value=str(config.get('tamano_fecha_pct','100'))),
            'desplazamiento_mm':tk.StringVar(value=str(config.get('desplazamiento_mm','0'))),
            'cabecera':tk.StringVar(value=config.get('cabecera','Escuela Municipal de Música y Danza')),
            'subtitulo':tk.StringVar(value=config.get('subtitulo','Arroyo de la Miel')),
            'lugar':tk.StringVar(value=config.get('lugar','Casa de la Cultura · Arroyo de la Miel')),
            'poster':tk.StringVar(value=config.get('poster','')),
            'logo_ayto':tk.StringVar(value=config.get('logo_ayto','')),
            'logo_centro':tk.StringVar(value=config.get('logo_centro','')),
        }
        notebook=ttk.Notebook(outer)
        notebook.grid(row=2,column=0,sticky='nsew')
        page_print=ttk.Frame(notebook,padding=5)
        page_design=ttk.Frame(notebook,padding=7)
        notebook.add(page_print,text='  1 · Impresión por lotes  ')
        notebook.add(page_design,text='  2 · Diseñar entrada  ')
        # El contenido de impresión se desplaza, pero la barra de acciones
        # generales permanece fija y visible en la ventana.
        print_canvas=tk.Canvas(page_print,highlightthickness=0)
        print_scroll=ttk.Scrollbar(page_print,orient='vertical',command=print_canvas.yview)
        print_canvas.configure(yscrollcommand=print_scroll.set)
        print_canvas.pack(side='left',fill='both',expand=True)
        print_scroll.pack(side='right',fill='y')
        print_body=ttk.Frame(print_canvas,padding=7)
        print_window=print_canvas.create_window((0,0),window=print_body,anchor='nw')
        print_body.bind('<Configure>',lambda *_:print_canvas.configure(scrollregion=print_canvas.bbox('all')))
        print_canvas.bind('<Configure>',lambda e:print_canvas.itemconfigure(print_window,width=e.width))
        ticket_group=ttk.LabelFrame(print_body,text='Intervalo de entradas',padding=9)
        ticket_group.pack(fill='x',pady=(0,6))
        # Las acciones de impresión deben estar siempre visibles, nunca en
        # la fila inferior que se desborda fuera de la ventana de 1000 px.
        print_actions=ttk.LabelFrame(print_body,text='ENVIAR ENTRADAS A LA IMPRESORA ZYWELL',padding=9)
        print_actions.pack(fill='x',pady=(0,8))
        ttk.Label(print_actions,text='Selecciona número inicial y cantidad; pulsa IMPRIMIR LOTE. Se pedirá confirmación.').pack(anchor='w',pady=(0,7))
        print_buttons=ttk.Frame(print_actions)
        print_buttons.pack(fill='x')
        ttk.Label(ticket_group,text='Desde número').grid(row=0,column=0,sticky='w',pady=4)
        tk.Spinbox(ticket_group,from_=1,to=event['capacity'],width=9,textvariable=start_num).grid(row=0,column=1,padx=(7,20),sticky='w')
        ttk.Label(ticket_group,text='Cantidad a imprimir').grid(row=0,column=2,sticky='w')
        tk.Spinbox(ticket_group,from_=1,to=event['capacity'],width=9,textvariable=qty).grid(row=0,column=3,padx=(7,15),sticky='w')
        range_label=ttk.Label(ticket_group,text='Última entrada: 0001',foreground='#214f73')
        range_label.grid(row=1,column=0,columnspan=4,sticky='w',pady=(5,0))
        def update_range(*_):
            try:
                first=int(start_num.get());count=int(qty.get())
                end=first+count-1
                if 1<=first<=event['capacity'] and 1<=count<=500 and end<=event['capacity']:
                    range_label.configure(text=f'Se imprimirán {count} entradas: {first:04d}–{end:04d}',foreground='#214f73')
                else:
                    range_label.configure(text='Comprueba el intervalo; no puede superar el aforo ni 500 por lote.',foreground='#a62820')
            except ValueError:
                range_label.configure(text='Introduce números válidos.',foreground='#a62820')
        start_num.trace_add('write',update_range)
        qty.trace_add('write',update_range)
        update_range()
        printer_group=ttk.LabelFrame(print_body,text='Impresora ZYWELL y calibración',padding=10)
        printer_group.pack(fill='x',pady=(0,9))
        ttk.Label(printer_group,text='Impresora de Windows').grid(row=0,column=0,sticky='w',pady=6)
        printer_combo=ttk.Combobox(printer_group,textvariable=printer,values=printers,width=44,state='readonly')
        printer_combo.grid(row=0,column=1,columnspan=2,sticky='ew',padx=7)
        def refresh_printers():
            found=ticket_printer.list_windows_printers()
            printer_combo.configure(values=found)
            if printer.get() not in found:
                printer.set(next((v for v in found if 'zywell' in v.lower() or 'pos-' in v.lower()),found[0] if found else ''))
            if not found:
                messagebox.showwarning('Impresoras','Windows no ha detectado impresoras instaladas o conectadas.',parent=win)
        ttk.Button(printer_group,text='Detectar de nuevo',command=refresh_printers).grid(row=0,column=3,sticky='ew',padx=5)
        ttk.Label(printer_group,text='Rollo (mm)').grid(row=1,column=0,sticky='w',pady=7)
        ttk.Combobox(printer_group,textvariable=roll,values=('58','80'),width=9,state='readonly').grid(row=1,column=1,sticky='w',padx=7)
        ttk.Label(printer_group,text='Largo del ticket (mm)').grid(row=1,column=2,sticky='w')
        ttk.Combobox(printer_group,textvariable=length,values=('90','105','120','125','135','150','165','180'),width=8).grid(row=1,column=3,sticky='w',padx=7)
        ttk.Label(printer_group,text='Modo de corte').grid(row=2,column=0,sticky='w',pady=7)
        ttk.Combobox(printer_group,textvariable=cut_mode,values=ticket_printer.CUT_MODES,width=34,state='readonly').grid(row=2,column=1,sticky='w',padx=7)
        ttk.Label(printer_group,text='Avance manual (puntos)').grid(row=2,column=2,sticky='w')
        ttk.Combobox(printer_group,textvariable=feed,values=('0','48','80','120','160','200','240','280','320','400'),width=8).grid(row=2,column=3,sticky='w',padx=7)
        ttk.Checkbutton(printer_group,text='Cortar cada ticket (ESC/POS)',variable=cut).grid(row=3,column=0,columnspan=2,sticky='w',pady=6)
        ttk.Combobox(printer_group,textvariable=cut_type,values=('Completo','Parcial'),width=12,state='readonly').grid(row=3,column=2,columnspan=2,sticky='w',padx=7)
        printer_group.columnconfigure(1,weight=1)
        qr_detail=tk.StringVar()
        def refresh_qr_detail(*_):
            try:
                paper=int(roll.get())
                mm=int(length.get())
                if paper not in ticket_printer.PRINTABLE_DOTS or not 85<=mm<=190:
                    qr_detail.set('Selecciona un tamaño de papel y un largo válido.')
                    return
                _,item=get_ticket(event_id,1)
                qr_image=ticket_printer._qr_image(
                    str(item['qr']),
                    round(230*(mm*8)/1080),
                    round(284*ticket_printer.PRINTABLE_DOTS[paper]/576))
                qr_detail.set(
                    f'QR uniforme en los 12 modelos: {qr_image.width/8:.1f} × '
                    f'{qr_image.height/8:.1f} mm. '
                    'Recomendado: 80 mm de rollo y largo 165 mm para el QR máximo.')
            except (ValueError,KeyError) as error:
                qr_detail.set('Comprueba el formato de papel: '+str(error))
        ttk.Button(printer_group,text='QR MÁS GRANDE · LARGO 165 mm',
                   command=lambda:length.set('165')).grid(
                       row=4,column=0,columnspan=2,sticky='w',padx=6,pady=(5,3))
        ttk.Label(printer_group,textvariable=qr_detail,
                  foreground='#174f76',wraplength=520).grid(
                      row=4,column=2,columnspan=2,sticky='w',padx=8,pady=(5,3))
        roll.trace_add('write',refresh_qr_detail)
        length.trace_add('write',refresh_qr_detail)
        refresh_qr_detail()
        ttk.Label(print_body,text='80 mm de papel ≠ 80 mm imprimibles: habitualmente son 72 mm (576 puntos).\n'
                                  'ZYWELL compatible: GS V 66 0, corte PARCIAL con avance, según manual POS-80XX.\n'
                                  'Primero usa Prueba de calibración; después imprime SOLO 2 tickets. El modelo importa.\n'
                                  'El largo determina el papel REAL; ya no deforma los elementos del diseño.',
                  wraplength=780,justify='left').pack(anchor='w',pady=8)

        # El diseñador crece de diez a dieciocho opciones: área desplazable real.
        designer_canvas=tk.Canvas(page_design,highlightthickness=0)
        designer_scroll=ttk.Scrollbar(page_design,orient='vertical',command=designer_canvas.yview)
        designer_canvas.configure(yscrollcommand=designer_scroll.set)
        designer_canvas.pack(side='left',fill='both',expand=True)
        designer_scroll.pack(side='right',fill='y')
        designer_body=ttk.Frame(designer_canvas,padding=4)
        designer_window=designer_canvas.create_window((0,0),window=designer_body,anchor='nw')
        designer_body.bind('<Configure>',lambda *_:designer_canvas.configure(scrollregion=designer_canvas.bbox('all')))
        designer_canvas.bind('<Configure>',lambda e:designer_canvas.itemconfigure(designer_window,width=e.width))
        art=ttk.LabelFrame(designer_body,text='Plantilla horizontal, logos, tipografía y márgenes',padding=10)
        art.pack(fill='x')
        labels={
            'plantilla':'Modelo principal (12 disponibles)',
            'foto_centro_x_pct':'Centrar foto horizontal (%) · 0 izquierda, 100 derecha',
            'foto_centro_y_pct':'Centrar foto vertical (%) · 0 arriba, 100 abajo',
            'foto_zoom_pct':'Ampliación de la foto (%) · 60–250',
            'margen_izquierdo_mm':'Margen izquierdo / inicio (mm)',
            'margen_derecho_mm':'Margen derecho / corte (mm)',
            'margen_superior_mm':'Margen superior (mm)',
            'margen_inferior_mm':'Margen inferior (mm)',
            'desplazamiento_mm':'Desplazamiento horizontal (mm)',
            'tamano_letra_pct':'Tamaño general de letras (%)',
            'tamano_cabecera_pct':'Tamaño de cabecera (%)',
            'tamano_fecha_pct':'Tamaño de fecha y hora (%)',
            'tamano_logo_pct':'Tamaño de escudo/logotipo municipal (%) · 150 recomendado',
            'cabecera':'Cabecera',
            'subtitulo':'Subtítulo',
            'lugar':'Lugar',
            'poster':'Fotografía lateral (JPG/PNG) · sustituye a la del modelo',
            'logo_ayto':'Escudo/logo municipal ORIGINAL (JPG/PNG)',
            'logo_centro':'Segundo logotipo ORIGINAL (opcional, JPG/PNG)',
        }
        margin_choices=('0','0.5','1','1.5','2','2.5','3','3.5','4','5','6','8','10','12','15','18')
        percent_choices=('70','80','90','100','110','120','130','140')
        combos={
            'plantilla':FOUR_MODELS,
            'posicion_logos':ticket_printer.LOGO_POSITIONS,
            'ajuste_imagen':ticket_printer.IMAGE_FITS,
            'foto_centro_x_pct':tuple(str(i) for i in range(0,101,10)),
            'foto_centro_y_pct':tuple(str(i) for i in range(0,101,10)),
            'foto_zoom_pct':('60','70','80','90','100','110','120','130','140','150','175','200','225','250'),
            'modo_impresion':('Normal','Blanco económico'),
            'estilo_avisos':('Según modelo','B · Recuadro','D · Separadores','Clásico'),
            'tamano_logos':ticket_printer.LOGO_SIZES,
            'estilo_escudo':('Solo escudo','Logo completo'),
            'margen_izquierdo_mm':margin_choices,
            'margen_derecho_mm':margin_choices,
            'margen_superior_mm':margin_choices,
            'margen_inferior_mm':margin_choices,
            'desplazamiento_mm':('-3','-2','-1','0','1','2','3'),
            'tamano_letra_pct':percent_choices,
            'tamano_cabecera_pct':percent_choices,
            'tamano_fecha_pct':percent_choices,
            'tamano_logo_pct':('100','115','125','135','145','150','160'),
        }
        for row,key in enumerate(labels):
            ttk.Label(art,text=labels[key]).grid(row=row,column=0,sticky='w',pady=4)
            if key in combos:
                ttk.Combobox(art,textvariable=variables[key],values=combos[key],
                             state=('normal' if key.startswith('margen_') else 'readonly'),width=36).grid(row=row,column=1,sticky='w',padx=7)
            else:
                ttk.Entry(art,textvariable=variables[key],width=56).grid(row=row,column=1,sticky='ew',padx=7)
            if key in ('poster','logo_ayto','logo_centro'):
                def pick_image(k=key):
                    selected=filedialog.askopenfilename(parent=win,title=labels[k],
                        filetypes=[('Imágenes','*.jpg *.jpeg *.png *.bmp *.webp')])
                    if selected:
                        variables[k].set(selected)
                        if k=='poster':
                            note.set('Fotografía JPG seleccionada: tendrá prioridad sobre la imagen del modelo. Pulsa Vista previa para comprobarla.')
                ttk.Button(art,text='Elegir imagen...',command=pick_image).grid(row=row,column=2,padx=5)
        art.columnconfigure(1,weight=1)
        ttk.Label(designer_body,
            text='El escudo se obtiene exclusivamente del JPG/PNG municipal que selecciones. '
                 'Si su formato es horizontal, se mostrará completo en la banda superior derecha, '
                 'sin recortarlo ni sustituirlo por otro. El cartel JPG siempre llena '
                 'el lateral y respeta el encuadre, sin repetirlo pequeño sobre un fondo. '
                 'Formato de referencia: ticket horizontal de 165 × 72 mm imprimibles '
                 'con rollo de 80 mm; el QR es único por entrada.',
            wraplength=890,justify='left').pack(anchor='w',pady=10)

        note=tk.StringVar(value='Elige una plantilla y comprueba la vista previa. Se respetan los datos y las entradas existentes.')
        ttk.Label(outer,textvariable=note,wraplength=1050,foreground='#1d5376').grid(
            row=3,column=0,sticky='ew',pady=(4,3))
        actions=ttk.Frame(outer)
        actions.grid(row=4,column=0,sticky='ew')
        actions_top=ttk.Frame(actions)
        actions_top.pack(fill='x')
        actions_bottom=ttk.Frame(actions)
        actions_bottom.pack(fill='x',pady=(3,0))
        def valid_range():
            try:
                first=int(start_num.get());count=int(qty.get())
                if first<1 or count<1 or count>500 or first+count-1>event['capacity']:
                    raise ValueError()
                return list(range(first,first+count))
            except ValueError:
                messagebox.showwarning('Intervalo incorrecto',f'Elige número inicial y cantidad (máximo {event["capacity"]} entradas y 500 por lote).',parent=win)
                return None
        def feed_amount():
            try:
                value=int(feed.get())
                if not 0<=value<=800:
                    raise ValueError()
                return value
            except ValueError:
                raise ValueError('El avance antes del corte debe estar entre 0 y 800 puntos.')
        def ticket_length():
            try:
                value=int(length.get())
                if not 85 <= value <= 190:
                    raise ValueError()
                return value
            except ValueError:
                raise ValueError('El largo del ticket debe estar entre 85 y 190 mm.')

        def current_design(save=False):
            d={k:v.get().strip() for k,v in variables.items()}
            d['poster_mode']='fondo' if d['plantilla']==ticket_printer.TEMPLATES[3] else 'lateral'
            if not -3 <= float(d.get('desplazamiento_mm') or '0') <= 3:
                raise ValueError('Desplazamiento permitido: -3 a +3 mm.')
            # Validar todos los ajustes antes de guardar, no al imprimir.
            ticket_printer.geometry(int(roll.get()),ticket_length(),d)
            ticket_printer._setting_number(d,'foto_centro_x_pct',50,0,100)
            ticket_printer._setting_number(d,'foto_centro_y_pct',50,0,100)
            ticket_printer._setting_number(d,'foto_zoom_pct',100,60,250)
            for field in ('tamano_letra_pct','tamano_cabecera_pct','tamano_fecha_pct'):
                ticket_printer._setting_number(d,field,100,70,140)
            if d['estilo_escudo'] not in ('Solo escudo','Logo completo'):
                raise ValueError('Elige Solo escudo o Logo completo.')
            if d['posicion_logos'] not in ticket_printer.LOGO_POSITIONS:
                raise ValueError('Posición de logos no reconocida.')
            if save:
                directory=DATA_DIR/'imagenes'/event_id
                directory.mkdir(parents=True,exist_ok=True)
                for key in ('poster','logo_ayto','logo_centro'):
                    source_name=d.get(key)
                    if not source_name:
                        continue
                    src=Path(source_name)
                    if not src.is_file() or src.suffix.lower() not in ('.jpg','.jpeg','.png','.bmp','.webp'):
                        raise ValueError(f'No se encuentra la imagen permitida: {src}')
                    destination=directory/(key+src.suffix.lower())
                    if src.resolve()!=destination.resolve():
                        shutil.copyfile(src,destination)
                    d[key]=str(destination)
                    variables[key].set(str(destination))
                save_ticket_design(event_id,d)
                prefs_path.write_text(json.dumps({'ancho':int(roll.get()),'impresora':printer.get(),
                    'corte_v04':cut.get(),'tipo_corte':cut_type.get(),'avance_corte':feed_amount(),
                    'largo_ticket':ticket_length(),'modo_corte':cut_mode.get(),
                    'version_perfil_corte':'0.9',
                    'perfil_geometria':'entrada_4_fiel_v1'},ensure_ascii=False),encoding='utf-8')
            return d
        def save_design():
            try:
                current_design(save=True)
                note.set('Diseño guardado para esta función, incluidas las imágenes y preferencias de impresora.')
                messagebox.showinfo('Guardado','Diseño e imágenes guardados correctamente.',parent=win)
            except Exception as ex:
                messagebox.showerror('No se pudo guardar',str(ex),parent=win)
        def preview():
            numbers=valid_range()
            if not numbers:return
            try:
                d=current_design(save=True)
                ev,tkdata=get_ticket(event_id,numbers[0])
                image=ticket_printer.render_landscape_ticket(ev,tkdata,int(roll.get()),d,
                                              length_mm=ticket_length(),color_preview=True)
                popup=tk.Toplevel(win)
                popup.title(f'{d["plantilla"]} · Entrada {numbers[0]:04d}')
                popup.geometry('1150x715')
                fr=ttk.Frame(popup,padding=12);fr.pack(fill='both',expand=True)
                image.thumbnail((1110,575))
                photo=ImageTk.PhotoImage(image)
                label=ttk.Label(fr,image=photo)
                label.image=photo
                label.pack(anchor='center',pady=12)
                ttk.Label(fr,text='Vista previa a color; la ZYWELL imprimirá en blanco y negro.').pack()
                ttk.Button(fr,text='Cerrar',command=popup.destroy).pack(pady=8)
            except Exception as ex:
                messagebox.showerror('Vista previa',str(ex),parent=win)
        def gallery(collection='catalogo'):
            """Galería de cuatro diseños por pantalla, sin arrastrar ventanas."""
            try:
                numbers=valid_range()
                if not numbers:return
                d=current_design(save=True)
                ev,tkdata=get_ticket(event_id,numbers[0])
                templates=FOUR_MODELS
                popup=tk.Toplevel(win)
                popup.title('Elegir diseño de entrada · 12 modelos')
                sw=popup.winfo_screenwidth()
                sh=popup.winfo_screenheight()
                gw=min(1150,max(760,sw-80))
                gh=min(800,max(590,sh-100))
                popup.geometry(f'{gw}x{gh}+{max(0,(sw-gw)//2)}+{max(0,(sh-gh)//3)}')
                popup.minsize(740,560)
                popup.transient(win)
                popup.grab_set()
                shell=ttk.Frame(popup,padding=8)
                shell.pack(fill='both',expand=True)
                header=ttk.Frame(shell)
                header.pack(fill='x',pady=(0,4))
                ttk.Label(header,text='12 MODELOS · A–L',
                    font=('Segoe UI',13,'bold')).pack(side='left')
                def catalog_pdf(print_now=False):
                    try:
                        spec=current_design(save=False)
                        if print_now:
                            target=DATA_DIR/'Catalogo_12_modelos_A4.pdf'
                        else:
                            name=filedialog.asksaveasfilename(
                                parent=popup,title='Guardar catálogo A4',
                                initialfile='Catalogo_12_modelos_A4.pdf',
                                defaultextension='.pdf',
                                filetypes=[('PDF','*.pdf')])
                            if not name:return
                            target=Path(name)
                        ticket_printer.export_catalog_pdf(
                            ev,tkdata,Path(target),spec,
                            templates,width_mm=int(roll.get()),
                            length_mm=ticket_length())
                        if print_now:
                            print_office_pdf(Path(target),popup)
                        else:
                            open_file(Path(target))
                    except Exception as error:
                        messagebox.showerror('Catálogo',str(error),parent=popup)
                ttk.Button(header,text='IMPRIMIR CATÁLOGO A4',
                    command=lambda:catalog_pdf(True)).pack(side='right',padx=4)
                ttk.Button(header,text='GUARDAR PDF A4',
                    command=lambda:catalog_pdf(False)).pack(side='right',padx=4)
                ttk.Label(shell,text='Los QR y códigos de barras se generan con datos reales. '
                    'Tu JPG ocupa el panel de fotografía correspondiente.',
                    wraplength=1050,foreground='#37566c').pack(anchor='w',pady=(0,5))
                body=ttk.Frame(shell)
                body.pack(fill='both',expand=True)
                body.columnconfigure(0,weight=1)
                body.columnconfigure(1,weight=1)
                body.rowconfigure(0,weight=1)
                body.rowconfigure(1,weight=1)
                nav=ttk.Frame(shell)
                nav.pack(fill='x',pady=(5,0))
                page=tk.IntVar(value=0)
                pages=(len(templates)+3)//4
                page_text=tk.StringVar()
                def choose(template):
                    variables['plantilla'].set(template)
                    notebook.select(page_design)
                    note.set('Diseño seleccionado: '+template+
                             '. Comprueba la vista previa y guarda el diseño.')
                    popup.destroy()
                def show_page():
                    for child in body.winfo_children():
                        child.destroy()
                    offset=page.get()*4
                    page_text.set(f'Página {page.get()+1} de {pages}')
                    previous.configure(state='normal' if page.get()>0 else 'disabled')
                    following.configure(state='normal' if page.get()<pages-1 else 'disabled')
                    thumb_width=min(480,max(315,(gw-65)//2))
                    thumb_height=min(206,max(118,(gh-265)//2-48))
                    for i,template in enumerate(templates[offset:offset+4]):
                        col=i%2
                        row=i//2
                        card=ttk.LabelFrame(body,text=template,padding=5)
                        card.grid(row=row,column=col,padx=5,pady=3,sticky='nsew')
                        current=dict(d,plantilla=template)
                        try:
                            picture=ticket_printer.render_landscape_ticket(
                                ev,tkdata,int(roll.get()),current,
                                length_mm=ticket_length(),color_preview=True)
                            picture.thumbnail((thumb_width,thumb_height),
                                              Image.Resampling.LANCZOS)
                            photo=ImageTk.PhotoImage(picture)
                            label=ttk.Label(card,image=photo)
                            label.image=photo
                            label.pack(anchor='center',pady=2)
                        except Exception as error:
                            ttk.Label(card,text='No se puede mostrar: '+str(error),
                                wraplength=thumb_width,foreground='#9b3333').pack(
                                    anchor='w',pady=12)
                        ttk.Label(card,text=f'Rollo {roll.get()} mm · Largo {ticket_length()} mm',
                                  foreground='#37576c').pack(pady=(2,1))
                        ttk.Button(card,text='SELECCIONAR ESTE DISEÑO',
                            command=lambda t=template:choose(t)).pack(
                                fill='x',pady=(3,1))
                def change_page(step):
                    page.set(max(0,min(pages-1,page.get()+step)))
                    show_page()
                previous=ttk.Button(nav,text='◀ ANTERIORES',
                                    command=lambda:change_page(-1))
                previous.pack(side='left',padx=5)
                ttk.Label(nav,textvariable=page_text,
                          font=('Segoe UI',11,'bold')).pack(side='left',padx=15)
                following=ttk.Button(nav,text='SIGUIENTES ▶',
                                     command=lambda:change_page(1))
                following.pack(side='left',padx=5)
                ttk.Button(nav,text='Cerrar',command=popup.destroy).pack(side='right',padx=5)
                show_page()
            except Exception as error:
                messagebox.showerror('Galería de diseños',str(error),parent=win)
        def pdf_single():
            numbers=valid_range()
            if not numbers:return
            try:
                d=current_design(save=True)
                ev,tkdata=get_ticket(event_id,numbers[0])
                target=filedialog.asksaveasfilename(parent=win,title='Guardar una entrada horizontal',
                     initialfile=f'Ticket_{numbers[0]:04d}_{roll.get()}mm.pdf',defaultextension='.pdf',filetypes=[('PDF','*.pdf')])
                if target:
                    ticket_printer.export_single_pdf(ev,tkdata,Path(target),int(roll.get()),d,length_mm=ticket_length())
                    note.set(f'PDF individual guardado: {target}')
            except Exception as ex:
                messagebox.showerror('Guardar PDF',str(ex),parent=win)
        def paper_a4_proof():
            # A4 printer at school/work: open a real PDF and let Windows show
            # its own printer chooser. Never send ESC/POS bytes to laser printers.
            numbers=valid_range()
            if not numbers:return
            try:
                spec=current_design(save=True)
                ev,item=get_ticket(event_id,numbers[0])
                dest=DATA_DIR/'Prueba_Entrada_A4.pdf'
                ticket_printer.export_catalog_pdf(ev,item,dest,spec,
                    templates=[spec['plantilla']],
                    width_mm=int(roll.get()),length_mm=ticket_length())
                print_office_pdf(dest,win)
                note.set('Prueba A4 preparada para envío directo a la impresora de oficina.')
            except Exception as ex:
                messagebox.showerror('Prueba A4',str(ex),parent=win)
        def calibration_test():
            if not printer.get():
                messagebox.showwarning('Impresora','Selecciona primero la ZYWELL.',parent=win); return
            if not messagebox.askyesno('Calibración ZYWELL',
                'Imprimir UNA tira con cinco líneas de referencia y después cortar.\n'
                'NO es una entrada real y no modifica las entradas guardadas.\n\n'
                '¿Enviar la prueba de calibración a la impresora?',parent=win):
                return
            try:
                job=ticket_printer.print_cut_calibration(printer.get(),int(roll.get()),
                    cut_mode=cut_mode.get(),feed_dots=feed_amount())
                note.set(f'Prueba de calibración enviada: trabajo {job}. Comprueba si la última línea está íntegra.')
            except Exception as ex:
                messagebox.showerror('Calibración',str(ex),parent=win)

        def cutter_test():
            if not printer.get():
                messagebox.showwarning('Impresora','Selecciona primero la ZYWELL.',parent=win);return
            if not messagebox.askyesno('Prueba de corte',
                '¿Enviar una orden de avance y corte SIN imprimir una entrada? Solo para impresoras ESC/POS con cortador.',parent=win):
                return
            try:
                job=ticket_printer.test_cutter(printer.get(),full_cut=cut_type.get()=='Completo')
                note.set(f'Orden enviada a la cola: {job}. Comprueba el corte físicamente.')
            except Exception as ex:
                messagebox.showerror('Cortador',str(ex),parent=win)
        def print_batch():
            numbers=valid_range()
            if not numbers:return
            if not printer.get():
                messagebox.showwarning('Impresora','Selecciona tu impresora ZYWELL instalada en Windows.',parent=win);return
            if not messagebox.askyesno('Confirmar impresión consecutiva',
                f'¿Imprimir {len(numbers)} ticket(s) consecutivos?\n'
                f'Del {numbers[0]:04d} al {numbers[-1]:04d}.\n'
                f'Impresora: {printer.get()}\n'
                f'Corte después de cada ticket: {"SÍ" if cut.get() else "NO"}.\n\n'
                'Se conservarán los QR originales. No se marcarán entradas como utilizadas.',parent=win):
                return
            try:
                d=current_design(save=True)
                w=int(roll.get());c=bool(cut.get());fc=cut_type.get()=='Completo';advance=feed_amount();mode=cut_mode.get();mm=ticket_length()
                selected=printer.get()
                pairs=[get_ticket(event_id,n) for n in numbers]
            except Exception as ex:
                messagebox.showerror('Preparar lote',str(ex),parent=win)
                return
            print_button.configure(state='disabled')
            note.set(f'Preparando {len(numbers)} entradas; no cierres este programa ni desconectes la impresora.')
            def worker():
                try:
                    job=ticket_printer.print_windows_escpos_batch(pairs,selected,w,d,c,full_cut=fc,feed_dots=advance,cut_mode=mode,length_mm=mm)
                    record_print_submission(event_id,numbers)
                    def success():
                        if not win.winfo_exists():return
                        print_button.configure(state='normal')
                        note.set(f'{len(numbers)} entradas enviadas. Exporta ahora el JSON firmado actualizado para la APK.')
                        messagebox.showinfo('Lote enviado',f'Windows ha aceptado el trabajo {job} con {len(numbers)} entradas. Comprueba físicamente los cortes. Después exporta el JSON firmado desde la pantalla principal para que la APK acepte estas entradas.',parent=win)
                    win.after(0,success)
                except Exception as ex:
                    info=str(ex)
                    def fail():
                        if not win.winfo_exists():return
                        print_button.configure(state='normal')
                        note.set('No se ha completado el envío de impresión.')
                        messagebox.showerror('Error de impresión',info,parent=win)
                    win.after(0,fail)
            threading.Thread(target=worker,daemon=True).start()

        def reset_confirmed():
            with connect() as db:
                used=db.execute('SELECT COUNT(*) FROM tickets WHERE event_id=? AND used_at IS NOT NULL',(event_id,)).fetchone()[0]
            if not messagebox.askyesno('Restablecer entradas validadas',
                f'Se van a restablecer {used} entradas utilizadas de esta función en Windows.\n'
                'Sus QR volverán a dar acceso en el servidor.\n\n'
                'IMPORTANTE: los móviles con JSON descargados previamente mantienen sus propios accesos '
                'y NO se restablecen automáticamente. Para pruebas, restablece cada móvil también.\n\n'
                '¿Quieres continuar?',parent=win):
                return
            try:
                total=reset_event_accesses(event_id)
                note.set(f'{total} accesos restablecidos en Windows. Se conservan las entradas impresas.')
                messagebox.showinfo('Accesos restablecidos',
                    f'{total} accesos restablecidos en Windows. Debes sincronizar o renovar el JSON de los móviles.',parent=win)
            except Exception as ex:messagebox.showerror('Restablecimiento',str(ex),parent=win)
        ttk.Button(ticket_group,text='RESTABLECER ACCESOS',command=reset_confirmed).grid(row=2,column=0,columnspan=4,sticky='w',pady=(8,2))
        ttk.Button(actions_top,text='Guardar diseño',command=save_design).pack(side='left',padx=3)
        ttk.Button(actions_top,text='VER 12 DISEÑOS',command=gallery,style='Action.TButton').pack(side='left',padx=3)
        ttk.Button(actions_top,text='Vista previa',command=preview).pack(side='left',padx=3)
        ttk.Button(actions_top,text='PDF individual',command=pdf_single).pack(side='left',padx=3)
        ttk.Button(actions_bottom,text='IMPRIMIR PRUEBA A4 (IMPRESORA NORMAL)',
                   command=paper_a4_proof).pack(side='left',padx=4)
        ttk.Button(print_buttons,text='CALIBRAR ZYWELL',command=calibration_test).pack(side='left',padx=4)
        ttk.Button(print_buttons,text='Cortar sin imprimir',command=cutter_test).pack(side='left',padx=4)
        def one_test_ticket():
            # Prints ONE genuine existing ticket with its own ID and QR.
            # This is not a dummy; the operator must export the signed JSON.
            qty.set('1')
            print_batch()
        ttk.Button(print_buttons,text='IMPRIMIR 1 ENTRADA (REAL)',
                   command=one_test_ticket).pack(side='left',padx=4)
        print_button=ttk.Button(print_buttons,text='IMPRIMIR LOTE EN ZYWELL',
                   command=print_batch,style='Action.TButton')
        print_button.pack(side='left',padx=4)
        ttk.Label(outer,text='Para imprimir tickets: pestaña 1 → IMPRESIÓN ZYWELL → IMPRIMIR LOTE. '
                  'Para impresora normal: botón A4 de esta barra.',
                  foreground='#7a4630',wraplength=1050).grid(
                      row=5,column=0,sticky='w',pady=(4,1))

    def open_seat_plan():
        eid=selected_event()
        if not eid:return
        ev=next((e for e in list_events() if e['id']==eid),None)
        if not ev or ev['mode']!='numerada':
            messagebox.showinfo('Plano de butacas','El editor de plano se utiliza con funciones numeradas. Crea una función en modalidad numerada.',parent=root)
            return
        try:
            import seat_plan
            seat_plan.open_editor(root,eid,DB_PATH,DATA_DIR,ev['name'])
        except Exception as ex:
            messagebox.showerror('Plano de butacas',str(ex),parent=root)

    def save_offline_package():
        eid=selected_event()
        if not eid:return
        ev=next((e for e in list_events() if e['id']==eid),None)
        if not ev:return
        path=filedialog.asksaveasfilename(title='Exportar función firmada para Android',
                   initialfile='Entradas_Impresas.json',defaultextension='.json',filetypes=[('Archivo JSON','*.json')])
        if not path:return
        try:
            total=export_offline_event(eid,Path(path))
            messagebox.showinfo('Archivo firmado exportado',
                f'Exportación terminada: {total} entradas enviadas a impresión.\n\nArchivo: {path}\n\n'
                'Importa este JSON en cada móvil mediante la APK.\n'
                'Si escaneas en varios móviles SIN conexión entre ellos, asigna rangos distintos: '
                'no pueden detectar duplicados entre dispositivos aislados.\n\n'
                'No compartas este archivo públicamente: contiene el inventario de entradas.',parent=root)
        except Exception as ex:
            messagebox.showerror('No se pudo exportar JSON',str(ex),parent=root)

    def merge_offline_accesses():
        path=filedialog.askopenfilename(title='Importar accesos registrados en Android',filetypes=[('Registro JSON','*.json')])
        if not path:return
        if not messagebox.askyesno('Fusionar accesos',
            'Esta operación añadirá al historial de Windows los accesos que figuren en el JSON.\n'
            'El registro procede del móvil y debe tratarse como un documento administrativo, no como prueba criptográfica.\n'
            'No borrará los accesos ya existentes. ¿Continuar?',parent=root):return
        try:
            summary=import_offline_access_log(Path(path))
            refresh()
            messagebox.showinfo('Registro fusionado',
                f'Nuevos accesos: {summary["added"]}\nYa registrados: {summary["already"]}\n'
                f'Identificadores desconocidos: {summary["unknown"]}',parent=root)
        except Exception as ex:messagebox.showerror('No se pudo importar',str(ex),parent=root)

    plan_btn.configure(command=open_seat_plan)
    offline_btn.configure(command=save_offline_package)
    sync_btn.configure(command=merge_offline_accesses)

    zywell_btn.configure(command=open_thermal_ticket)

    create_btn.configure(command=create)
    preview_btn.configure(command=preview)
    save_btn.configure(command=save_pdf)
    print_btn.configure(command=print_pdf)
    refresh_btn.configure(command=refresh)
    delete_btn.configure(command=delete_selected)
    tree.bind("<<TreeviewSelect>>", update_buttons)
    tree.bind("<Double-1>",lambda _event:root.after_idle(edit_selected))
    edit_btn.configure(command=edit_selected)
    new_btn.configure(command=new_form)
    set_editing(editing_id[0])
    refresh()
    if editing_id[0] and tree.exists(editing_id[0]):
        tree.selection_set(editing_id[0])
        tree.see(editing_id[0])
        update_buttons()
    try:
        server = start_server()
    except OSError as ex:
        messagebox.showerror("Servidor no disponible", f"No se puede iniciar el servidor local en puerto {PORT}: {ex}")
        return

    def close():
        if draft_timer[0] is not None:
            try:root.after_cancel(draft_timer[0])
            except ValueError:pass
        persist_draft()
        server.shutdown()
        server.server_close()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
    if "--check-package" in sys.argv:
        # Ejercita el mismo import dinámico que falló en el ejecutable v2.3.
        from reportlab.graphics.barcode import createBarcodeDrawing
        from reportlab.graphics.barcode.code128 import Code128
        code=Code128("0000000000000123",barWidth=1,barHeight=40)
        code.validate();code.encode();code.decompose()
        if not code.decomposed: raise RuntimeError("Code128 no disponible")
        createBarcodeDrawing("Code128",value="0000000000000123")
        print("EMPAQUETADO_OK",flush=True)
        raise SystemExit(0)
    init_db()
    if "--serve" in sys.argv:
        print(f"Control de Entradas v{VERSION} · http://0.0.0.0:{PORT} · PIN {ACCESS_PIN}")
        server = start_server()
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            server.shutdown()
    else:
        launch_gui()
