import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

CONFIG = Path.home() / '.generador_txt_config.json'
SECCIONES = ('DATOS', 'SINOPSIS', 'INSTRUCCIONES')
PLANTILLA_DATOS = 'Año:\nGénero:\nTamaño:\nModo:\nIdioma:\n'


class Generador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Generador de archivos TXT y carpeta de capturas')
        self.geometry('1370x720')
        self.minsize(960, 560)
        self.configure(bg='#edf1f5')
        try:
            self.configuracion = json.loads(CONFIG.read_text(encoding='utf-8'))
            if not isinstance(self.configuracion, dict):
                self.configuracion = {}
        except (OSError, ValueError):
            self.configuracion = {}

        self.nombre_juego = tk.StringVar()
        self.paneles = []
        ttk.Style(self).configure('TButton', padding=7)
        contenedor = ttk.Frame(self, padding=16)
        contenedor.pack(fill='both', expand=True)
        contenedor.rowconfigure(0, weight=1)

        for columna, nombre in enumerate(SECCIONES):
            contenedor.columnconfigure(columna, weight=1, uniform='paneles')
            panel = ttk.LabelFrame(contenedor, text=f'  {nombre}  ', padding=12)
            panel.grid(row=0, column=columna, sticky='nsew', padx=6)
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(3, weight=1)
            ttk.Label(panel, text='Nombre del juego / archivo:').grid(row=0, column=0, sticky='w')
            titulo = ttk.Entry(panel, textvariable=self.nombre_juego)
            titulo.grid(row=1, column=0, sticky='ew', pady=(4, 12))
            self.menu_contextual(titulo)
            ttk.Label(panel, text='Contenido:').grid(row=2, column=0, sticky='w')
            caja = tk.Text(panel, wrap='word', undo=True, font=('Segoe UI', 10))
            caja.grid(row=3, column=0, sticky='nsew', pady=(4, 12))
            if nombre == 'DATOS':
                caja.insert('1.0', PLANTILLA_DATOS)
                caja.edit_reset()
            self.menu_contextual(caja)
            ttk.Label(panel, text='Carpeta de destino:').grid(row=4, column=0, sticky='w')
            ruta = tk.StringVar(value=self.configuracion.get(nombre, ''))
            self.selector_carpeta(panel, ruta, fila=5)
            self.paneles.append((nombre, caja, ruta))

        capturas = ttk.LabelFrame(contenedor, text='  CARPETA DE CAPTURAS  ', padding=12)
        capturas.grid(row=1, column=0, columnspan=3, sticky='ew', padx=6, pady=(14, 0))
        capturas.columnconfigure(0, weight=1)
        ttk.Label(capturas, text='Seleccioná la carpeta principal donde se creará la subcarpeta con el nombre del juego:').grid(row=0, column=0, sticky='w')
        self.ruta_capturas = tk.StringVar(value=self.configuracion.get('CAPTURAS', ''))
        self.selector_carpeta(capturas, self.ruta_capturas, fila=1)
        ttk.Label(capturas, text='La subcarpeta se creará automáticamente al guardar (si ya existe, se conservará).').grid(row=2, column=0, sticky='w', pady=(6, 0))

        ttk.Button(self, text='GUARDAR TODOS', command=self.guardar).pack(pady=(0, 18), ipadx=32, ipady=7)
        self.protocol('WM_DELETE_WINDOW', self.cerrar)

    def menu_contextual(self, widget):
        menu = tk.Menu(widget, tearoff=False)
        acciones = [('Deshacer', '<<Undo>>'), ('Rehacer', '<<Redo>>'), None,
                    ('Cortar', '<<Cut>>'), ('Copiar', '<<Copy>>'),
                    ('Pegar', '<<Paste>>'), ('Seleccionar todo', '<<SelectAll>>')]
        for accion in acciones:
            if accion is None:
                menu.add_separator()
            else:
                texto, evento = accion
                menu.add_command(label=texto, command=lambda e=evento, w=widget: w.event_generate(e))

        def mostrar(event):
            widget.focus_set()
            try:
                if isinstance(widget, tk.Text):
                    if not widget.tag_ranges('sel'):
                        widget.mark_set('insert', f'@{event.x},{event.y}')
                elif not widget.selection_present():
                    widget.icursor(widget.index(f'@{event.x}'))
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        widget.bind('<Button-3>', mostrar)

    def selector_carpeta(self, padre, variable, fila):
        marco = ttk.Frame(padre)
        marco.grid(row=fila, column=0, sticky='ew', pady=(4, 0))
        marco.columnconfigure(0, weight=1)
        entrada = ttk.Entry(marco, textvariable=variable)
        entrada.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        self.menu_contextual(entrada)
        ttk.Button(marco, text='Examinar...', command=lambda: self.elegir_carpeta(variable)).grid(row=0, column=1)

    def elegir_carpeta(self, variable):
        actual = variable.get().strip()
        inicial = actual if actual and Path(actual).is_dir() else str(Path.home())
        carpeta = filedialog.askdirectory(initialdir=inicial)
        if carpeta:
            variable.set(carpeta)
            self.guardar_configuracion()

    def guardar_configuracion(self):
        datos = {nombre: ruta.get().strip() for nombre, _, ruta in self.paneles}
        datos['CAPTURAS'] = self.ruta_capturas.get().strip()
        try:
            CONFIG.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass

    def guardar(self):
        nombre = self.nombre_juego.get().strip()
        if nombre.lower().endswith('.txt'):
            nombre = nombre[:-4]
        if (not nombre or nombre in ('.', '..') or
                re.search(r'[<>:"/\\|?*\x00-\x1f]', nombre) or nombre.endswith((' ', '.')) or
                re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', nombre)):
            messagebox.showerror('Nombre inválido', 'Escribí un nombre de juego válido, sin caracteres prohibidos por Windows.')
            return

        pendientes = []
        for seccion, caja, ruta in self.paneles:
            contenido = caja.get('1.0', 'end-1c')
            if not contenido.strip():
                continue
            carpeta_texto = ruta.get().strip()
            if not carpeta_texto or not Path(carpeta_texto).is_dir():
                messagebox.showerror('Carpeta inválida', f'Seleccioná una carpeta existente para {seccion}.')
                return
            pendientes.append((Path(carpeta_texto) / (nombre + '.txt'), contenido))

        ruta_capturas = self.ruta_capturas.get().strip()
        if ruta_capturas and not Path(ruta_capturas).is_dir():
            messagebox.showerror('Carpeta inválida', 'La carpeta de destino de CAPTURAS no existe.')
            return
        destino_capturas = Path(ruta_capturas) / nombre if ruta_capturas else None
        if not pendientes and destino_capturas is None:
            messagebox.showinfo('Nada que guardar', 'Completá algún texto o seleccioná la carpeta de capturas.')
            return

        destinos = [str(p.resolve()).casefold() for p, _ in pendientes]
        if len(destinos) != len(set(destinos)):
            messagebox.showerror('Archivos repetidos', 'Dos paneles apuntan al mismo TXT. Elegí carpetas diferentes.')
            return
        existentes = [str(p) for p, _ in pendientes if p.exists()]
        if existentes and not messagebox.askyesno('Sobrescribir archivos', 'Estos TXT ya existen:\n\n' + '\n'.join(existentes) + '\n\n¿Querés reemplazarlos?'):
            return

        guardados = []
        try:
            for destino, contenido in pendientes:
                destino.write_text(contenido, encoding='utf-8')
                guardados.append(destino)
            if destino_capturas is not None:
                destino_capturas.mkdir(exist_ok=True)
        except OSError as error:
            messagebox.showerror('Error al guardar', f'Se guardaron {len(guardados)} TXT antes del error:\n{error}')
            return
        self.guardar_configuracion()
        resumen = f'Se guardaron {len(guardados)} archivo(s) TXT.'
        if destino_capturas is not None:
            resumen += '\nCarpeta de capturas lista.'
        rutas = [str(p) for p in guardados]
        if destino_capturas is not None:
            rutas.append(str(destino_capturas))
        messagebox.showinfo('¡Listo!', resumen + '\n\n' + '\n'.join(rutas))

    def cerrar(self):
        self.guardar_configuracion()
        self.destroy()


if __name__ == '__main__':
    Generador().mainloop()
