"""Editor asistido de planos de butacas. No realiza OCR ni detección automática de asientos.

El plano (JPG/PNG/PDF) es un fondo visual. Cada butaca se asocia a una entrada
numerada existente, y las coordenadas normalizadas permiten cambiar el zoom.
"""
from __future__ import annotations
import io
import json
from pathlib import Path
import shutil
import sqlite3
from PIL import Image, ImageOps, ImageTk


def _connection(db_path):
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def ensure_schema(db_path):
    with _connection(db_path) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS seat_plans (
                event_id TEXT PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
                image_path TEXT, modified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS seat_positions (
                ticket_id TEXT PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
                x REAL NOT NULL CHECK(x BETWEEN 0 AND 1),
                y REAL NOT NULL CHECK(y BETWEEN 0 AND 1),
                reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved IN (0,1)),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        ''')


def ensure_positions(db_path, event_id):
    """Generate a provisional grid; an imported plan is not machine-recognized."""
    with _connection(db_path) as db:
        event = db.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
        if not event or event['mode'] != 'numerada':
            raise ValueError('Selecciona una función con butacas numeradas.')
        seats = db.execute('SELECT id,number,seat_label,used_at FROM tickets WHERE event_id=? ORDER BY number',(event_id,)).fetchall()
        rows,cols=event['rows_count'],event['seats_per_row']
        for seat in seats:
            n=seat['number']-1
            x=.1+.8*((n%cols+.5)/cols)
            y=.11+.76*((n//cols+.5)/rows)
            db.execute('INSERT OR IGNORE INTO seat_positions(ticket_id,x,y) VALUES(?,?,?)',(seat['id'],x,y))


def seat_data(db_path,event_id):
    ensure_positions(db_path,event_id)
    with _connection(db_path) as db:
        plan=db.execute('SELECT image_path FROM seat_plans WHERE event_id=?',(event_id,)).fetchone()
        seats=db.execute('''SELECT t.id,t.number,t.seat_label,t.used_at,s.x,s.y,s.reserved
             FROM tickets t JOIN seat_positions s ON t.id=s.ticket_id
             WHERE t.event_id=? ORDER BY t.number''',(event_id,)).fetchall()
        return ([dict(s) for s in seats],plan['image_path'] if plan else None)


def update_position(db_path,ticket_id,x,y):
    x,y=float(x),float(y)
    if not (0<=x<=1 and 0<=y<=1):raise ValueError('Posición fuera del plano')
    with _connection(db_path) as db:
        c=db.execute('UPDATE seat_positions SET x=?,y=?,updated_at=CURRENT_TIMESTAMP WHERE ticket_id=?',(x,y,ticket_id))
        if not c.rowcount:raise ValueError('No existe esa butaca')


def toggle_reserved(db_path,ticket_id):
    with _connection(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT s.reserved,t.used_at FROM seat_positions s JOIN tickets t ON t.id=s.ticket_id WHERE s.ticket_id=?',(ticket_id,)).fetchone()
        if row is None:raise ValueError('La butaca no existe')
        if row['used_at']:raise ValueError('No se puede modificar una entrada ya utilizada')
        status=not bool(row['reserved'])
        db.execute('UPDATE seat_positions SET reserved=?,updated_at=CURRENT_TIMESTAMP WHERE ticket_id=?',(int(status),ticket_id))
        return status


def import_plan(db_path,event_id,source,data_dir):
    """Persist background inside DATA_DIR; PDF page one converted to PNG."""
    source=Path(source)
    if source.suffix.lower()=='.pdf':
        import fitz
        doc=fitz.open(str(source))
        if not doc.page_count:raise ValueError('PDF sin páginas')
        raw=doc[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).tobytes('png')
        doc.close()
        image=Image.open(io.BytesIO(raw))
    elif source.suffix.lower() in ('.png','.jpg','.jpeg','.webp'):
        image=Image.open(source)
    else:
        raise ValueError('Importa un JPG, PNG o PDF')
    image=ImageOps.exif_transpose(image).convert('RGB')
    image.thumbnail((2400,1600),Image.Resampling.LANCZOS)
    folder=Path(data_dir)/'planos';folder.mkdir(parents=True,exist_ok=True)
    target=folder/f'{event_id}.png'
    image.save(target,optimize=True)
    with _connection(db_path) as db:
        db.execute('INSERT INTO seat_plans(event_id,image_path) VALUES(?,?) ON CONFLICT(event_id) DO UPDATE SET image_path=excluded.image_path,modified_at=CURRENT_TIMESTAMP',(event_id,str(target)))
    return target


def open_editor(parent,event_id,db_path,data_dir,event_name):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from PIL import ImageDraw
    win=tk.Toplevel(parent)
    win.title('Plano de butacas · '+event_name)
    win.geometry('1120x790');win.minsize(740,520)
    top=ttk.Frame(win,padding=10);top.pack(fill='x')
    ttk.Label(top,text='PLANO DE BUTACAS',font=('Segoe UI',16,'bold')).pack(side='left')
    info=tk.StringVar(value='Pulsa en una butaca para reservarla. Activa Mover para ajustar sus posiciones sobre el plano.')
    ttk.Label(win,textvariable=info,foreground='#315d78',wraplength=1000).pack(fill='x',padx=14)
    controls=ttk.Frame(win,padding=8);controls.pack(fill='x')
    mode=tk.StringVar(value='reservar')
    ttk.Radiobutton(controls,text='Reservar / liberar',variable=mode,value='reservar').pack(side='left',padx=8)
    ttk.Radiobutton(controls,text='Mover butacas sobre el plano',variable=mode,value='mover').pack(side='left',padx=8)
    frame=ttk.Frame(win,padding=(12,4));frame.pack(fill='both',expand=True)
    canvas=tk.Canvas(frame,bg='#edf1f5',highlightthickness=1,highlightbackground='#9eaab4')
    canvas.pack(fill='both',expand=True)
    footer=ttk.Frame(win,padding=9);footer.pack(fill='x')
    legend=ttk.Label(win,text='Blanco = libre  ·  Naranja = reservada  ·  Verde = entrada validada  ·  Azul = butaca seleccionada')
    legend.pack(fill='x',padx=14,pady=(0,7))
    cache={'seats':[], 'image_path':None, 'photo':None, 'rect':(0,0,1,1), 'selected':None}

    def redraw(event=None):
        seats,path=seat_data(db_path,event_id)
        cache['seats']=seats;cache['image_path']=path
        w=max(500,canvas.winfo_width());h=max(300,canvas.winfo_height());canvas.delete('all')
        x0,y0,x1,y1=18,18,w-18,h-18
        canvas.create_rectangle(x0,y0,x1,y1,fill='white',outline='#778493')
        if path and Path(path).exists():
            im=Image.open(path)
            im.thumbnail((x1-x0,y1-y0),Image.Resampling.LANCZOS)
            xx=x0+((x1-x0)-im.width)//2;yy=y0+((y1-y0)-im.height)//2
            ph=ImageTk.PhotoImage(im);cache['photo']=ph
            canvas.create_image(xx,yy,anchor='nw',image=ph)
            cache['rect']=(xx,yy,xx+im.width,yy+im.height)
        else:
            cache['rect']=(x0,y0,x1,y1)
            canvas.create_text(w/2,34,text='PLANO PROVISIONAL · IMPORTA EL PLANO ESCANEADO',font=('Segoe UI',12,'bold'),fill='#62758a')
        xx,yy,X,Y=cache['rect'];cw=X-xx;ch=Y-yy
        radius=max(8,min(17,round(min(cw,ch)/42)))
        for s in seats:
            cx=xx+s['x']*cw;cy=yy+s['y']*ch
            fill='#76c293' if s['used_at'] else '#f2b04a' if s['reserved'] else '#fff'
            if s['id']==cache['selected']:fill='#b3d6ff'
            canvas.create_oval(cx-radius,cy-radius,cx+radius,cy+radius,fill=fill,outline='#193d60',width=2,tags=('seat',s['id']))
            canvas.create_text(cx,cy,text=str(s['number']),font=('Segoe UI',max(7,radius-3),'bold'),fill='#173147',tags=('seat',s['id']))
        info.set(f'{len(seats)} butacas · Reservadas: {sum(s["reserved"] for s in seats)} · Usadas: {sum(bool(s["used_at"]) for s in seats)} · Modo: {mode.get()}')

    def hit(event):
        xx,yy,X,Y=cache['rect'];w=X-xx;h=Y-yy
        if w<=0 or h<=0:return None
        best=None;bestd=10**10
        for s in cache['seats']:
            d=((event.x-(xx+s['x']*w))**2+(event.y-(yy+s['y']*h))**2)**.5
            if d<bestd:best=s;bestd=d
        return best if bestd<=max(15,min(23,round(min(w,h)/36))) else None

    def on_click(event):
        s=hit(event)
        if not s:return
        cache['selected']=s['id']
        if mode.get()=='reservar':
            try:toggle_reserved(db_path,s['id'])
            except ValueError as ex: messagebox.showerror('No disponible',str(ex),parent=win)
        redraw()

    def on_drag(event):
        if mode.get()!='mover' or not cache['selected']:return
        xx,yy,X,Y=cache['rect']
        if X-xx<1 or Y-yy<1:return
        try:update_position(db_path,cache['selected'],max(0,min(1,(event.x-xx)/(X-xx))),max(0,min(1,(event.y-yy)/(Y-yy))))
        except ValueError:return
        redraw()

    def choose_plan():
        path=filedialog.askopenfilename(parent=win,title='Importar plano',filetypes=[('Plano JPG, PNG o PDF','*.jpg *.jpeg *.png *.webp *.pdf')])
        if not path:return
        try:import_plan(db_path,event_id,path,data_dir);redraw()
        except Exception as ex:messagebox.showerror('Importar plano',str(ex),parent=win)

    def show_selected():
        t=next((x for x in cache['seats'] if x['id']==cache['selected']),None)
        if t:messagebox.showinfo('Butaca seleccionada',f'{t["seat_label"]}\nEntrada n.º {t["number"]:04d}\nReservada: {"Sí" if t["reserved"] else "No"}',parent=win)
        else:messagebox.showinfo('Butaca','Selecciona una butaca.',parent=win)

    ttk.Button(controls,text='Importar plano JPG / PNG / PDF',command=choose_plan).pack(side='right',padx=5)
    ttk.Button(controls,text='Datos de la butaca',command=show_selected).pack(side='right',padx=5)
    canvas.bind('<Button-1>',on_click);canvas.bind('<B1-Motion>',on_drag)
    canvas.bind('<Configure>',lambda e:redraw())
    redraw()
    return win
