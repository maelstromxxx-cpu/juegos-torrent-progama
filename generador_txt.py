import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

CONFIG = Path.home() / '.generador_txt_config.json'
SECCIONES = ('DATOS', 'SINOPSIS', 'INSTRUCCIONES')

class Generador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Generador de archivos TXT')
        self.geometry('1350x650')
        self.minsize(900, 470)
        self.configure(bg='#edf1f5')
        try:
            self.configuracion = json.loads(CONFIG.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.configuracion = {}
        self.paneles = []
        ttk.Style(self).configure('TButton', padding=7)
        contenedor = ttk.Frame(self, padding=16)
        contenedor.pack(fill='both', expand=True)
        for columna, nombre in enumerate(SECCIONES):
            contenedor.columnconfigure(columna, weight=1, uniform='paneles')
            panel = ttk.LabelFrame(contenedor, text=f'  {nombre}  ', padding=12)
            panel.grid(row=0, column=columna, sticky='nsew', padx=6)
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(3, weight=1)
            ttk.Label(panel, text='Nombre del archivo:').grid(row=0, column=0, sticky='w')
            titulo = ttk.Entry(panel)
            titulo.insert(0, nombre.lower())
            titulo.grid(row=1, column=0, sticky='ew', pady=(4, 12))
            ttk.Label(panel, text='Contenido:').grid(row=2, column=0, sticky='w')
            caja = tk.Text(panel, wrap='word', undo=True, font=('Segoe UI', 10))
            caja.grid(row=3, column=0, sticky='nsew', pady=(4, 12))
            ttk.Label(panel, text='Carpeta de destino:').grid(row=4, column=0, sticky='w')
            fila = ttk.Frame(panel)
            fila.grid(row=5, column=0, sticky='ew', pady=(4, 0))
            fila.columnconfigure(0, weight=1)
            ruta = tk.StringVar(value=self.configuracion.get(nombre, ''))
            ttk.Entry(fila, textvariable=ruta).grid(row=0, column=0, sticky='ew', padx=(0, 6))
            ttk.Button(fila, text='Examinar...', command=lambda v=ruta: self.elegir_carpeta(v)).grid(row=0, column=1)
            self.paneles.append((nombre, titulo, caja, ruta))
        contenedor.rowconfigure(0, weight=1)
        ttk.Button(self, text='GUARDAR TODOS', command=self.guardar).pack(pady=(0, 18), ipadx=32, ipady=7)
        self.protocol('WM_DELETE_WINDOW', self.cerrar)

    def elegir_carpeta(self, variable):
        carpeta = filedialog.askdirectory(initialdir=variable.get() if Path(variable.get()).is_dir() else str(Path.home()))
        if carpeta:
            variable.set(carpeta)
            self.guardar_configuracion()

    def guardar_configuracion(self):
        datos = {nombre: ruta.get().strip() for nombre, _, _, ruta in self.paneles}
        try:
            CONFIG.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass

    def guardar(self):
        pendientes = []
        for nombre, titulo, caja, ruta in self.paneles:
            contenido = caja.get('1.0', 'end-1c')
            if not contenido.strip():
                continue
            archivo = titulo.get().strip()
            carpeta = Path(ruta.get().strip())
            if not archivo:
                messagebox.showerror('Falta el nombre', f'Indicá el nombre del archivo de {nombre}.')
                return
            if archivo.lower().endswith('.txt'):
                archivo = archivo[:-4]
            if not archivo or archivo in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', archivo) or archivo.endswith((' ', '.')):
                messagebox.showerror('Nombre inválido', f'El nombre de {nombre} contiene caracteres no permitidos.')
                return
            if not ruta.get().strip() or not carpeta.is_dir():
                messagebox.showerror('Carpeta inválida', f'Seleccioná una carpeta existente para {nombre}.')
                return
            pendientes.append((nombre, carpeta / (archivo + '.txt'), contenido))
        if not pendientes:
            messagebox.showinfo('Sin contenido', 'Escribí contenido en al menos uno de los paneles.')
            return
        destinos = [str(p.resolve()).casefold() for _, p, _ in pendientes]
        if len(destinos) != len(set(destinos)):
            messagebox.showerror('Archivos repetidos', 'Dos paneles apuntan al mismo archivo. Cambiá el nombre o la carpeta.')
            return
        existentes = [str(p) for _, p, _ in pendientes if p.exists()]
        if existentes and not messagebox.askyesno('Sobrescribir archivos', 'Estos archivos ya existen:\n\n' + '\n'.join(existentes) + '\n\n¿Querés reemplazarlos?'):
            return
        guardados = []
        try:
            for _, destino, contenido in pendientes:
                destino.write_text(contenido, encoding='utf-8')
                guardados.append(destino)
        except OSError as error:
            messagebox.showerror('Error al guardar', f'Se guardaron {len(guardados)} archivo(s) antes del error:\n{error}')
            return
        self.guardar_configuracion()
        messagebox.showinfo('¡Listo!', f'Se guardaron {len(guardados)} archivo(s) correctamente.\n\n' + '\n'.join(str(p) for p in guardados))

    def cerrar(self):
        self.guardar_configuracion()
        self.destroy()

if __name__ == '__main__':
    Generador().mainloop()
