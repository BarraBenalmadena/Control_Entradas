"""Control de Entradas 0.6 - largo variable y corte con autocalibración alternativa.

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

VERSION = "0.7.0"
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
            CREATE TABLE IF NOT EXISTS ticket_design (
                event_id TEXT PRIMARY KEY REFERENCES events(id),
                data TEXT NOT NULL
            );
        """)


def iso_now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def create_event(name: str, start_time: str, mode: str, capacity: int, rows_count: int = 0, seats_per_row: int = 0):
    name = name.strip()
    if not name or len(name) > 120:
        raise ValueError("Indica un nombre de 1 a 120 caracteres.")
    datetime.fromisoformat(start_time)
    if mode not in ("libre", "numerada"):
        raise ValueError("Modalidad inválida.")
    if mode == "numerada":
        if rows_count < 1 or seats_per_row < 1:
            raise ValueError("Indica filas y butacas por fila.")
        capacity = rows_count * seats_per_row
    if capacity < 1 or capacity > 5000:
        raise ValueError("El aforo debe estar entre 1 y 5000.")
    event_id = uuid.uuid4().hex
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (event_id, name, start_time, mode, capacity, rows_count, seats_per_row, iso_now()))
        for n in range(1, capacity + 1):
            ticket_id = uuid.uuid4().hex
            seat = None
            if mode == "numerada":
                row = (n - 1) // seats_per_row + 1
                seat_number = (n - 1) % seats_per_row + 1
                seat = f"Fila {row:02d} · Butaca {seat_number:02d}"
            payload = json.dumps({"v": 1, "id": ticket_id, "e": event_id, "n": n, "s": seat}, ensure_ascii=False, separators=(",", ":"))
            payload64 = b64u(payload.encode("utf-8"))
            signed = PRIVATE_KEY.sign(payload64.encode("ascii"), ec.ECDSA(hashes.SHA256()))
            qr = "CE1." + payload64 + "." + b64u(signed)
            conn.execute("INSERT INTO tickets(id, event_id, number, seat_label, qr) VALUES (?,?,?,?,?)", (ticket_id, event_id, n, seat, qr))
        conn.commit()
    return event_id


def list_events():
    with connect() as conn:
        rows = conn.execute("""SELECT e.*, (SELECT COUNT(*) FROM tickets t WHERE t.event_id=e.id AND t.used_at IS NOT NULL) AS used,
                         (SELECT COUNT(*) FROM tickets t WHERE t.event_id=e.id) AS issued
                         FROM events e ORDER BY e.start_time DESC""").fetchall()
        return [dict(x) for x in rows]


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
            conn.execute('DELETE FROM ticket_design WHERE event_id=?', (event_id,))
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
    try:
        payload = parse_qr(qr)
    except (InvalidSignature, ValueError, TypeError, UnicodeError, json.JSONDecodeError, KeyError):
        return {"status": "invalid", "message": "QR NO VÁLIDO"}
    if payload["e"] != event_id:
        return {"status": "wrong_event", "message": "ENTRADA DE OTRA FUNCIÓN"}
    with connect() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            ticket = conn.execute("SELECT number, seat_label, qr, used_at FROM tickets WHERE id=? AND event_id=?", (payload["id"], event_id)).fetchone()
            if not ticket or ticket["qr"] != qr:
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
    root.title("Control de Entradas · v0.5")
    root.geometry("1050x740")
    root.minsize(820, 550)
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg="#eef3f8")
    style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=(13, 9))
    style.configure("Other.TButton", font=("Segoe UI", 10), padding=(10, 8))

    container = ttk.Frame(root, padding=(16, 12))
    container.pack(fill="both", expand=True)
    ttk.Label(container, text="CONTROL DE ENTRADAS", font=("Segoe UI", 20, "bold")).pack(anchor="w")
    ttk.Label(container, text="Escuela Municipal de Música y Danza · Prototipo 0.7", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 8))

    net_frame = ttk.LabelFrame(container, text="Conexión de lectores Android", padding=(10, 7))
    net_frame.pack(fill="x")
    urls = "   ·   ".join("http://" + ip + ":" + str(PORT) for ip in lan_ips()) or "Consulta la dirección IPv4 del ordenador (ipconfig)"
    ttk.Label(net_frame, text="Servidor: " + urls, wraplength=900).pack(anchor="w")
    ttk.Label(net_frame, text="PIN de conexión: " + ACCESS_PIN, font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(net_frame, text="El ordenador debe permanecer encendido; los móviles deben conectarse a la misma red local.").pack(anchor="w")

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

    # These controls deliberately appear BEFORE the expandable table.
    toolbar = ttk.Frame(container)
    toolbar.pack(fill="x", pady=(12, 6))
    create_btn = ttk.Button(toolbar, text="1 · Crear y guardar función", style="Action.TButton")
    create_btn.pack(side="left", padx=(0, 7))
    preview_btn = ttk.Button(toolbar, text="2 · Vista previa", style="Other.TButton")
    save_btn = ttk.Button(toolbar, text="3 · Guardar PDF", style="Other.TButton")
    print_btn = ttk.Button(toolbar, text="4 · Imprimir...", style="Other.TButton")

    helptext = tk.StringVar(value="Primero guarda una función. Después selecciónala en la tabla para ver, guardar o imprimir sus entradas.")
    ttk.Label(container, textvariable=helptext, foreground="#214f73", wraplength=940).pack(anchor="w", pady=(0, 5))

    zywell_btn = ttk.Button(container, text="2 · DISEÑAR / PREVISUALIZAR / IMPRIMIR TICKETS ZYWELL", style="Action.TButton")
    zywell_btn.pack(fill="x", pady=(0, 8))
    ttk.Label(container,text='Ticket de referencia: logo + imagen del espectáculo + número + QR pequeño. Papel 80/58 mm, corte opcional.',
              foreground='#225778').pack(anchor='w', pady=(0,6))

    list_frame = ttk.LabelFrame(container, text="Funciones guardadas (selecciona una)", padding=9)
    list_frame.pack(fill="both", expand=True)
    cols = ("nombre", "fecha", "tipo", "aforo", "accesos")
    tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=5, selectmode="browse")
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
        for button in (preview_btn, save_btn, print_btn, delete_btn, zywell_btn):
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

    def create():
        try:
            stamp = datetime.strptime(date.get().strip(), "%d/%m/%Y %H:%M").isoformat(timespec="minutes")
            event_id = create_event(name.get(), stamp, mode.get(), int(capacity.get()), int(rows.get()), int(seats.get()))
            refresh()
            tree.selection_set(event_id)
            tree.see(event_id)
            update_buttons()
            helptext.set("Función guardada. Pulsa 'Vista previa' para ver las entradas, 'Guardar PDF' para exportarlas o 'Imprimir...' para elegir impresora.")
            messagebox.showinfo("Guardado correctamente", "Función y entradas guardadas automáticamente.\n\nAhora puedes pulsar '2 · Vista previa' para verlas antes de imprimir.")
        except Exception as ex:
            messagebox.showerror("No se pudo guardar", str(ex))

    def selected_event():
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Selecciona una función", "Haz clic sobre una función de la tabla antes de continuar.")
            return None
        return selected[0]

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
            messagebox.showinfo("Elegir impresora", "Se abrirá el PDF con las entradas.\n\nPulsa Ctrl + P en el visor para elegir tu impresora de Windows, las páginas y el número de copias.")
            try:
                open_file(result[0])
                helptext.set("Pulsa Ctrl + P en la vista previa del PDF para imprimir con tu impresora.")
            except Exception as ex:
                messagebox.showerror("No se pudo abrir la impresión", f"PDF generado en:\n{result[0]}\n\n{ex}")

    def open_thermal_ticket():
        event_id = selected_event()
        if not event_id:
            return
        import shutil
        import ticket_printer
        from PIL import Image, ImageTk

        event = next((item for item in list_events() if item['id'] == event_id), None)
        if event is None:
            messagebox.showerror('Función inexistente', 'La función seleccionada ya no existe.')
            return
        win=tk.Toplevel(root)
        win.title('Diseñador de 6 tickets · ZYWELL · v0.7')
        win.geometry('940x755')
        win.minsize(800,645)
        win.transient(root)
        outer=ttk.Frame(win,padding=12)
        outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='TICKETS HORIZONTALES · 6 DISEÑOS',font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(outer,text=f"{event['name']}  ·  {event['capacity']} entradas  ·  {event['mode']}").pack(anchor='w',pady=(0,8))

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
        feed=tk.StringVar(value=str(prefs.get('avance_corte','120')))
        cut_mode=tk.StringVar(value=prefs.get('modo_corte',ticket_printer.CUT_MODES[0]))
        length=tk.StringVar(value=str(prefs.get('largo_ticket','135' if str(prefs.get('ancho','80'))=='80' else '90')))
        chosen=config.get('plantilla')
        if chosen not in ticket_printer.TEMPLATES:
            chosen=ticket_printer.TEMPLATES[3 if config.get('poster_mode')=='fondo' else 0]
        variables={
            'plantilla':tk.StringVar(value=chosen),
            'ajuste_imagen':tk.StringVar(value=config.get('ajuste_imagen','Rellenar y recortar')),
            'tamano_logos':tk.StringVar(value=config.get('tamano_logos','Grandes')),
            'desplazamiento_mm':tk.StringVar(value=str(config.get('desplazamiento_mm','0'))),
            'cabecera':tk.StringVar(value=config.get('cabecera','Escuela Municipal de Música y Danza')),
            'subtitulo':tk.StringVar(value=config.get('subtitulo','Arroyo de la Miel')),
            'lugar':tk.StringVar(value=config.get('lugar','Casa de la Cultura · Arroyo de la Miel')),
            'poster':tk.StringVar(value=config.get('poster','')),
            'logo_ayto':tk.StringVar(value=config.get('logo_ayto','')),
            'logo_centro':tk.StringVar(value=config.get('logo_centro','')),
        }
        notebook=ttk.Notebook(outer)
        notebook.pack(fill='both',expand=True)
        page_print=ttk.Frame(notebook,padding=14)
        page_design=ttk.Frame(notebook,padding=14)
        notebook.add(page_print,text='  1 · Impresión por lotes  ')
        notebook.add(page_design,text='  2 · Diseñar entrada  ')
        ticket_group=ttk.LabelFrame(page_print,text='Intervalo de entradas',padding=12)
        ticket_group.pack(fill='x',pady=(0,9))
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
        printer_group=ttk.LabelFrame(page_print,text='Impresora ZYWELL y calibración',padding=12)
        printer_group.pack(fill='x',pady=(0,9))
        ttk.Label(printer_group,text='Impresora de Windows').grid(row=0,column=0,sticky='w',pady=6)
        ttk.Combobox(printer_group,textvariable=printer,values=printers,width=52,state='readonly').grid(row=0,column=1,columnspan=3,sticky='ew',padx=7)
        ttk.Label(printer_group,text='Rollo (mm)').grid(row=1,column=0,sticky='w',pady=7)
        ttk.Combobox(printer_group,textvariable=roll,values=('58','80'),width=9,state='readonly').grid(row=1,column=1,sticky='w',padx=7)
        ttk.Label(printer_group,text='Largo del ticket (mm)').grid(row=1,column=2,sticky='w')
        ttk.Combobox(printer_group,textvariable=length,values=('90','105','120','125','135','150','165','180'),width=8).grid(row=1,column=3,sticky='w',padx=7)
        ttk.Label(printer_group,text='Modo de corte').grid(row=2,column=0,sticky='w',pady=7)
        ttk.Combobox(printer_group,textvariable=cut_mode,values=ticket_printer.CUT_MODES,width=29,state='readonly').grid(row=2,column=1,sticky='w',padx=7)
        ttk.Label(printer_group,text='Avance manual (puntos)').grid(row=2,column=2,sticky='w')
        ttk.Combobox(printer_group,textvariable=feed,values=('0','48','64','80','96','104','112','120','128','144','160','184','200'),width=8).grid(row=2,column=3,sticky='w',padx=7)
        ttk.Checkbutton(printer_group,text='Cortar cada ticket (ESC/POS)',variable=cut).grid(row=3,column=0,columnspan=2,sticky='w',pady=6)
        ttk.Combobox(printer_group,textvariable=cut_type,values=('Completo','Parcial'),width=12,state='readonly').grid(row=3,column=2,columnspan=2,sticky='w',padx=7)
        printer_group.columnconfigure(1,weight=1)
        ttk.Label(page_print,text='80 mm de papel ≠ 80 mm imprimibles: habitualmente son 72 mm (576 puntos).\n'
                                  'Corte automático: GS V 65, si la ZYWELL lo admite. Corte manual: ajusta el avance antes de la cuchilla.\n'
                                  'Prueba primero 2 tickets; la distancia cabezal-cortador depende del modelo.\n'
                                  'El largo determina el papel REAL; ya no deforma los elementos del diseño.',
                  wraplength=780,justify='left').pack(anchor='w',pady=8)

        art=ttk.LabelFrame(page_design,text='Plantilla horizontal e imágenes',padding=10)
        art.pack(fill='x')
        labels={
            'plantilla':'Diseño (6 modelos)',
            'ajuste_imagen':'Ajuste de fotografía',
            'tamano_logos':'Tamaño de logotipos',
            'desplazamiento_mm':'Ajustar diseño al corte (mm)',
            'cabecera':'Cabecera',
            'subtitulo':'Subtítulo',
            'lugar':'Lugar',
            'poster':'Cartel del espectáculo (JPG/PNG)',
            'logo_ayto':'Logotipo Ayuntamiento',
            'logo_centro':'Logotipo escuela/centro',
        }
        for r,key in enumerate(labels):
            ttk.Label(art,text=labels[key]).grid(row=r,column=0,sticky='w',pady=5)
            if key in ('plantilla','ajuste_imagen','tamano_logos','desplazamiento_mm'):
                choices={'plantilla':ticket_printer.TEMPLATES,
                         'ajuste_imagen':ticket_printer.IMAGE_FITS,
                         'tamano_logos':ticket_printer.LOGO_SIZES,
                         'desplazamiento_mm':('-3','-2','-1','0','1','2','3')}[key]
                ttk.Combobox(art,textvariable=variables[key],values=choices,state='readonly',width=37).grid(row=r,column=1,sticky='w',padx=7)
            else:
                ttk.Entry(art,textvariable=variables[key],width=56).grid(row=r,column=1,sticky='ew',padx=7)
            if key in ('poster','logo_ayto','logo_centro'):
                def pick_image(k=key):
                    selected=filedialog.askopenfilename(parent=win,title=labels[k],filetypes=[('Imágenes','*.jpg *.jpeg *.png *.bmp *.webp')])
                    if selected:
                        variables[k].set(selected)
                ttk.Button(art,text='Elegir imagen...',command=pick_image).grid(row=r,column=2,padx=5)
        art.columnconfigure(1,weight=1)
        ttk.Label(page_design,text='«Rellenar y recortar» ocupa por completo la zona del cartel; «Mostrar completa» evita recortes, pero puede dejar bandas.\n'
                                    '«04 · Fondo suave» coloca el cartel aclarado detrás del texto. Los 6 modelos mantienen el QR verificable.\n'
                                    'El ajuste de -3 a +3 mm desplaza el diseño sin variar el largo de papel ni deformar el QR.',
                  wraplength=850,justify='left').pack(anchor='w',pady=10)

        note=tk.StringVar(value='Elige una plantilla y comprueba la vista previa. Se respetan los datos y las entradas existentes.')
        ttk.Label(outer,textvariable=note,wraplength=880,foreground='#1d5376').pack(anchor='w',pady=(7,5))
        actions=ttk.Frame(outer)
        actions.pack(fill='x')
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
                if not 0<=value<=255:
                    raise ValueError()
                return value
            except ValueError:
                raise ValueError('El avance antes del corte debe estar entre 0 y 255 puntos.')
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
                    'largo_ticket':ticket_length(),'modo_corte':cut_mode.get()},ensure_ascii=False),encoding='utf-8')
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
                image=ticket_printer.render_landscape_ticket(ev,tkdata,int(roll.get()),d,length_mm=ticket_length())
                popup=tk.Toplevel(win)
                popup.title(f'{d["plantilla"]} · Entrada {numbers[0]:04d}')
                popup.geometry('1150x715')
                fr=ttk.Frame(popup,padding=12);fr.pack(fill='both',expand=True)
                image.thumbnail((1110,575))
                photo=ImageTk.PhotoImage(image)
                label=ttk.Label(fr,image=photo)
                label.image=photo
                label.pack(anchor='center',pady=12)
                ttk.Label(fr,text='Vista previa en blanco y negro, tal como se envía a la ZYWELL.').pack()
                ttk.Button(fr,text='Cerrar',command=popup.destroy).pack(pady=8)
            except Exception as ex:
                messagebox.showerror('Vista previa',str(ex),parent=win)
        def gallery():
            try:
                numbers=valid_range()
                if not numbers:return
                d=current_design(save=True)
                ev,tkdata=get_ticket(event_id,numbers[0])
                gallery_win=tk.Toplevel(win)
                gallery_win.title('Elegir entre 6 modelos de ticket')
                gallery_win.geometry('1090x700')
                gallery_win.minsize(850,530)
                shell=ttk.Frame(gallery_win,padding=7);shell.pack(fill='both',expand=True)
                viewport=tk.Canvas(shell,highlightthickness=0)
                scrollbar=ttk.Scrollbar(shell,orient='vertical',command=viewport.yview)
                viewport.configure(yscrollcommand=scrollbar.set)
                viewport.pack(side='left',fill='both',expand=True)
                scrollbar.pack(side='right',fill='y')
                inner=ttk.Frame(viewport)
                wid=viewport.create_window((0,0),window=inner,anchor='nw')
                inner.bind('<Configure>',lambda *_:viewport.configure(scrollregion=viewport.bbox('all')))
                viewport.bind('<Configure>',lambda e:viewport.itemconfigure(wid,width=e.width))
                # Mismo bitmap que se envía a la impresora: miniatura centrada,
                # sin crops y sin cambiar la relación de aspecto.
                for i,template in enumerate(ticket_printer.TEMPLATES):
                    copy=dict(d);copy['plantilla']=template
                    pic=ticket_printer.render_landscape_ticket(ev,tkdata,int(roll.get()),copy,length_mm=ticket_length())
                    art_w,art_h=470,248
                    pic.thumbnail((art_w,art_h),Image.Resampling.LANCZOS)
                    paper=Image.new('RGB',(484,264),'#ececec')
                    x=(paper.width-pic.width)//2
                    y=(paper.height-pic.height)//2
                    paper.paste(pic,(x,y))
                    from PIL import ImageDraw
                    ImageDraw.Draw(paper).rectangle((x,y,x+pic.width-1,y+pic.height-1),outline='#333333',width=1)
                    photo=ImageTk.PhotoImage(paper)
                    box=ttk.LabelFrame(inner,text=template,padding=7)
                    box.grid(row=i//2,column=i%2,padx=6,pady=6,sticky='nsew')
                    thumb=ttk.Label(box,image=photo)
                    thumb.image=photo
                    thumb.pack(anchor='center')
                    ttk.Label(box,text=f'Papel: {roll.get()} mm  ·  Largo: {ticket_length()} mm  ·  Sin recortar',
                              foreground='#42586a').pack(anchor='center',pady=(2,0))
                    def choose(t=template):
                        variables['plantilla'].set(t)
                        notebook.select(page_design)
                        note.set(f'Diseño seleccionado: {t}. Puedes ajustar el cartel, tamaño de logos y guardar.')
                        gallery_win.destroy()
                    ttk.Button(box,text='Seleccionar este diseño',command=choose).pack(fill='x',pady=(6,0))
                inner.columnconfigure(0,weight=1);inner.columnconfigure(1,weight=1)
            except Exception as ex:
                messagebox.showerror('Galería de diseños',str(ex),parent=win)
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
                    def success():
                        if not win.winfo_exists():return
                        print_button.configure(state='normal')
                        note.set(f'{len(numbers)} entradas enviadas a Windows. Trabajo de impresión: {job}.')
                        messagebox.showinfo('Lote enviado',f'Windows ha aceptado el trabajo {job} con {len(numbers)} entradas. Comprueba físicamente los cortes.',parent=win)
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

        ttk.Button(actions,text='Guardar diseño',command=save_design).pack(side='left',padx=3)
        ttk.Button(actions,text='VER 6 DISEÑOS',command=gallery,style='Action.TButton').pack(side='left',padx=3)
        ttk.Button(actions,text='Vista previa',command=preview).pack(side='left',padx=3)
        ttk.Button(actions,text='PDF individual',command=pdf_single).pack(side='left',padx=3)
        ttk.Button(actions,text='Probar corte',command=cutter_test).pack(side='left',padx=3)
        print_button=ttk.Button(actions,text='IMPRIMIR LOTE',command=print_batch,style='Action.TButton')
        print_button.pack(side='right',padx=3)
        ttk.Label(outer,text='Para calibrar: prueba dos entradas, comprueba el corte y ajusta 8-16 puntos cada vez. No imprimas grandes lotes hasta verificar.',foreground='#7a4630').pack(anchor='w',pady=8)

    zywell_btn.configure(command=open_thermal_ticket)

    create_btn.configure(command=create)
    preview_btn.configure(command=preview)
    save_btn.configure(command=save_pdf)
    print_btn.configure(command=print_pdf)
    refresh_btn.configure(command=refresh)
    delete_btn.configure(command=delete_selected)
    tree.bind("<<TreeviewSelect>>", update_buttons)
    refresh()
    try:
        server = start_server()
    except OSError as ex:
        messagebox.showerror("Servidor no disponible", f"No se puede iniciar el servidor local en puerto {PORT}: {ex}")
        return

    def close():
        server.shutdown()
        server.server_close()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()


if __name__ == "__main__":
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