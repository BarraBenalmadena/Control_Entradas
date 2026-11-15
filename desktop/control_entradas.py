"""Control de Entradas 0.1 - Servidor Windows y generador de PDF.

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

VERSION = "0.2.0"
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
    root.title("Control de Entradas · v0.2")
    root.geometry("1000x675")
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
    ttk.Label(container, text="Escuela Municipal de Música y Danza · Prototipo 0.2", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 8))

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
    create_btn = ttk.Button(toolbar, text="1 · Guardar función y generar entradas", style="Action.TButton")
    create_btn.pack(side="left", padx=(0, 7))
    preview_btn = ttk.Button(toolbar, text="2 · Vista previa", style="Other.TButton")
    preview_btn.pack(side="left", padx=(0, 7))
    save_btn = ttk.Button(toolbar, text="3 · Guardar PDF", style="Other.TButton")
    save_btn.pack(side="left", padx=(0, 7))
    print_btn = ttk.Button(toolbar, text="4 · Imprimir...", style="Other.TButton")
    print_btn.pack(side="left")

    helptext = tk.StringVar(value="Primero guarda una función. Después selecciónala en la tabla para ver, guardar o imprimir sus entradas.")
    ttk.Label(container, textvariable=helptext, foreground="#214f73", wraplength=940).pack(anchor="w", pady=(0, 5))

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

    def update_buttons(*_):
        state = "normal" if tree.selection() else "disabled"
        for button in (preview_btn, save_btn, print_btn):
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

    create_btn.configure(command=create)
    preview_btn.configure(command=preview)
    save_btn.configure(command=save_pdf)
    print_btn.configure(command=print_pdf)
    refresh_btn.configure(command=refresh)
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