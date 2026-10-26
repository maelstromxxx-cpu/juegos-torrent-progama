import json
import re
import shutil
import os
import tempfile
import tkinter as tk
from pathlib import Path
from datetime import date
from urllib.parse import urlparse, parse_qs, unquote
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None

CONFIG = Path.home() / '.generador_txt_config.json'
SECCIONES = ('DATOS', 'SINOPSIS', 'INSTRUCCIONES', 'UPDATES')
PLANTILLA_DATOS = 'Año:\nGénero:\nTamaño:\nModo:\nIdioma:\nFecha de incorporación: {fecha}\n'
FORMATOS = ('.jpg', '.jpeg', '.png', '.webp')

class Generador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Generador de TXT, portadas, capturas y torrents - v12')
        self.geometry('1750x900')
        self.minsize(1100, 680)
        try:
            self.configuracion = json.loads(CONFIG.read_text(encoding='utf-8'))
            if not isinstance(self.configuracion, dict): self.configuracion = {}
        except (OSError, ValueError):
            self.configuracion = {}
        self.nombre_juego = tk.StringVar()
        self.paneles = []
        self.imagenes_capturas = []
        self.portada = None
        self.redimensionar = tk.BooleanVar(value=True)
        self.previews = []
        self.ruta_capturas = tk.StringVar(value=self.configuracion.get('CAPTURAS', ''))
        self.ruta_portadas = tk.StringVar(value=self.configuracion.get('PORTADAS', ''))
        self.ruta_torrents = tk.StringVar(value=self.configuracion.get('TORRENTS', ''))
        self.archivo_torrent = None
        ttk.Style(self).configure('TButton', padding=5)

        exterior = ttk.Frame(self)
        exterior.pack(fill='both', expand=True)
        lienzo = tk.Canvas(exterior, highlightthickness=0)
        barra = ttk.Scrollbar(exterior, orient='vertical', command=lienzo.yview)
        lienzo.configure(yscrollcommand=barra.set)
        barra.pack(side='right', fill='y')
        lienzo.pack(side='left', fill='both', expand=True)
        principal = ttk.Frame(lienzo, padding=12)
        ventana = lienzo.create_window((0, 0), window=principal, anchor='nw')
        principal.bind('<Configure>', lambda e: lienzo.configure(scrollregion=lienzo.bbox('all')))
        lienzo.bind('<Configure>', lambda e: lienzo.itemconfigure(ventana, width=e.width))
        lienzo.bind_all('<MouseWheel>', lambda e: lienzo.yview_scroll(int(-e.delta / 120), 'units'))

        for i, seccion in enumerate(SECCIONES):
            principal.columnconfigure(i, weight=1, uniform='panel')
            panel = ttk.LabelFrame(principal, text='  ' + seccion + '  ', padding=9)
            panel.grid(row=0, column=i, sticky='nsew', padx=5)
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(3, weight=1)
            ttk.Label(panel, text='Nombre del juego / archivo:').grid(row=0, column=0, sticky='w')
            titulo = ttk.Entry(panel, textvariable=self.nombre_juego)
            titulo.grid(row=1, column=0, sticky='ew', pady=(3, 8))
            self.menu_contextual(titulo)
            ttk.Label(panel, text='Contenido:').grid(row=2, column=0, sticky='w')
            caja = tk.Text(panel, wrap='word', undo=True, font=('Segoe UI', 10), height=13)
            caja.grid(row=3, column=0, sticky='nsew', pady=(3, 8))
            if seccion == 'DATOS':
                caja.insert('1.0', PLANTILLA_DATOS.format(fecha=date.today().strftime('%d/%m/%Y')))
                caja.edit_reset()
            self.menu_contextual(caja)
            ttk.Label(panel, text='Carpeta de destino:').grid(row=4, column=0, sticky='w')
            ruta = tk.StringVar(value=self.configuracion.get(seccion, ''))
            self.selector_carpeta(panel, ruta, 5)
            self.paneles.append((seccion, caja, ruta))
        principal.rowconfigure(0, weight=1)

        fotos = ttk.LabelFrame(principal, text='  PORTADA  ', padding=10)
        fotos.grid(row=1, column=0, sticky='nsew', padx=5, pady=(10, 0))
        fotos.columnconfigure(0, weight=1)
        ttk.Button(fotos, text='Examinar portada...', command=self.elegir_portada).grid(row=0, column=0, sticky='w')
        ttk.Button(fotos, text='Quitar portada', command=self.quitar_portada).grid(row=0, column=1, sticky='e')
        self.lbl_portada = ttk.Label(fotos, text='Sin portada seleccionada', wraplength=350)
        self.lbl_portada.grid(row=1, column=0, columnspan=2, sticky='w', pady=6)
        self.vista_portada = ttk.Label(fotos)
        self.vista_portada.grid(row=2, column=0, columnspan=2, sticky='w')
        ttk.Label(fotos, text='Carpeta de destino de la portada:').grid(row=3, column=0, columnspan=2, sticky='w', pady=(7, 0))
        self.selector_carpeta(fotos, self.ruta_portadas, 4, span=2)
        ttk.Label(fotos, text='Se guardará como Nombre del juego.webp (con procesamiento activado).', wraplength=360).grid(row=5, column=0, columnspan=2, sticky='w', pady=(5, 0))

        capturas = ttk.LabelFrame(principal, text='  CAPTURAS  ', padding=10)
        capturas.grid(row=1, column=1, columnspan=3, sticky='nsew', padx=5, pady=(10, 0))
        capturas.columnconfigure(0, weight=1)
        botones = ttk.Frame(capturas)
        botones.grid(row=0, column=0, sticky='ew')
        ttk.Button(botones, text='Agregar imágenes...', command=self.agregar_capturas).pack(side='left', padx=(0, 7))
        ttk.Button(botones, text='Quitar seleccionadas', command=self.quitar_capturas).pack(side='left', padx=(0, 7))
        ttk.Button(botones, text='Vaciar lista', command=self.vaciar_capturas).pack(side='left')
        lista_frame = ttk.Frame(capturas)
        lista_frame.grid(row=1, column=0, sticky='nsew', pady=6)
        lista_frame.columnconfigure(0, weight=1)
        lista_frame.rowconfigure(0, weight=1)
        self.lista = tk.Listbox(lista_frame, height=5, selectmode='extended', exportselection=False)
        self.lista.grid(row=0, column=0, sticky='nsew')
        ttk.Scrollbar(lista_frame, orient='vertical', command=self.lista.yview).grid(row=0, column=1, sticky='ns')
        self.lista.configure(yscrollcommand=lambda a,b: None)
        self.lista.bind('<<ListboxSelect>>', lambda e: self.mostrar_captura())
        self.vista_captura = ttk.Label(capturas, text='Seleccioná una imagen de la lista para ver su miniatura.')
        self.vista_captura.grid(row=2, column=0, sticky='w')
        ttk.Label(capturas, text='Carpeta principal de destino (se creará una subcarpeta con el nombre del juego):').grid(row=3, column=0, sticky='w', pady=(8, 0))
        self.selector_carpeta(capturas, self.ruta_capturas, 4)
        ttk.Label(capturas, text='Capturas: 1.webp, 2.webp, etc. Los originales no se modifican.').grid(row=5, column=0, sticky='w', pady=(5, 0))

        torrent_panel = ttk.LabelFrame(principal, text='  TORRENT (COPIA A GOOGLE DRIVE O CARPETA LOCAL)  ', padding=10)
        torrent_panel.grid(row=2, column=0, columnspan=4, sticky='ew', padx=5, pady=(10, 0))
        torrent_panel.columnconfigure(0, weight=1)
        botones_torrent = ttk.Frame(torrent_panel)
        botones_torrent.grid(row=0, column=0, sticky='w')
        ttk.Button(botones_torrent, text='Examinar torrent...', command=self.elegir_torrent).pack(side='left', padx=(0, 8))
        ttk.Button(botones_torrent, text='Quitar torrent', command=self.quitar_torrent).pack(side='left')
        self.lbl_torrent = ttk.Label(torrent_panel, text='Ningún torrent seleccionado')
        self.lbl_torrent.grid(row=1, column=0, sticky='w', pady=(5, 8))
        ttk.Label(torrent_panel, text='Carpeta de destino (podés seleccionar la unidad de Google Drive):').grid(row=2, column=0, sticky='w')
        self.selector_carpeta(torrent_panel, self.ruta_torrents, 3)
        ttk.Label(torrent_panel, text='El archivo .torrent conserva su nombre original. Google Drive para escritorio se encarga de sincronizarlo.').grid(row=4, column=0, sticky='w', pady=(5, 0))

        ttk.Checkbutton(self, text='Convertir a WEBP (calidad 75) y reducir a 600 px de ancho sin deformar', variable=self.redimensionar).pack(pady=(8, 0))
        acciones = ttk.Frame(self)
        acciones.pack(pady=12)
        ttk.Button(acciones, text='GUARDAR TODOS', command=self.guardar).pack(side='left', padx=8, ipadx=30, ipady=7)
        ttk.Button(acciones, text='LIMPIAR TODO', command=self.confirmar_limpieza).pack(side='left', padx=8, ipadx=20, ipady=7)
        ttk.Button(acciones, text='GENERADOR DE ID', command=self.abrir_generador_ids).pack(side='left', padx=8, ipadx=18, ipady=7)
        self.protocol('WM_DELETE_WINDOW', self.cerrar)

    @staticmethod
    def obtener_id_drive(enlace):
        enlace = enlace.strip()
        if not enlace:
            raise ValueError('Falta pegar uno de los enlaces de Google Drive.')
        url = urlparse(enlace)
        if (url.hostname or '').lower() not in ('drive.google.com', 'docs.google.com'):
            raise ValueError('El enlace no pertenece a Google Drive.')
        identificador = parse_qs(url.query).get('id', [''])[0]
        if not identificador:
            partes = [unquote(x) for x in url.path.split('/') if x]
            for i, parte in enumerate(partes[:-1]):
                if parte in ('d', 'folders'):
                    identificador = partes[i + 1]
                    break
        if not re.fullmatch(r'[A-Za-z0-9_-]{10,}', identificador):
            raise ValueError('No se encontró un ID válido en el enlace.')
        return identificador

    def abrir_generador_ids(self):
        # Una ventana por vez; no bloquea el uso del resto de Windows.
        if getattr(self, 'ventana_ids', None) and self.ventana_ids.winfo_exists():
            self.ventana_ids.lift()
            self.ventana_ids.focus_force()
            return
        ventana = tk.Toplevel(self)
        self.ventana_ids = ventana
        ventana.title('Generador de ID - Google Drive')
        ventana.geometry('770x315')
        ventana.minsize(580, 290)
        ventana.transient(self)
        ventana.columnconfigure(0, weight=1)
        cuerpo = ttk.Frame(ventana, padding=18)
        cuerpo.pack(fill='both', expand=True)
        cuerpo.columnconfigure(0, weight=1)
        torrent = tk.StringVar()
        instrucciones = tk.StringVar()
        resultado = tk.StringVar()
        ttk.Label(cuerpo, text='Enlace de Drive del TORRENT:').grid(row=0, column=0, sticky='w')
        campo_torrent = ttk.Entry(cuerpo, textvariable=torrent)
        campo_torrent.grid(row=1, column=0, sticky='ew', pady=(3, 12))
        self.menu_contextual(campo_torrent)
        ttk.Label(cuerpo, text='Enlace de Drive de las INSTRUCCIONES:').grid(row=2, column=0, sticky='w')
        campo_instrucciones = ttk.Entry(cuerpo, textvariable=instrucciones)
        campo_instrucciones.grid(row=3, column=0, sticky='ew', pady=(3, 12))
        self.menu_contextual(campo_instrucciones)
        ttk.Label(cuerpo, text='Resultado (uno o dos ID, separados por | si corresponde):').grid(row=5, column=0, sticky='w', pady=(9, 0))
        salida = ttk.Entry(cuerpo, textvariable=resultado, state='readonly')
        salida.grid(row=6, column=0, sticky='ew', pady=(4, 12))
        self.menu_contextual(salida)

        def generar():
            resultado.set('')
            enlace_torrent = torrent.get().strip()
            enlace_instrucciones = instrucciones.get().strip()
            if not enlace_torrent and not enlace_instrucciones:
                messagebox.showwarning('Faltan enlaces', 'Pegá al menos un enlace de Google Drive.', parent=ventana)
                return
            try:
                id_torrent = self.obtener_id_drive(enlace_torrent) if enlace_torrent else ''
                id_instrucciones = self.obtener_id_drive(enlace_instrucciones) if enlace_instrucciones else ''
                resultado.set(f'{id_torrent}|{id_instrucciones}' if id_torrent and id_instrucciones else (id_torrent or id_instrucciones))
            except ValueError as error:
                messagebox.showerror('Enlace inválido', str(error), parent=ventana)

        def copiar():
            if not resultado.get():
                messagebox.showwarning('Sin resultado', 'Primero generá al menos un ID.', parent=ventana)
                return
            self.clipboard_clear()
            self.clipboard_append(resultado.get())
            self.update_idletasks()
            estado.configure(text='¡Resultado copiado al portapapeles!')

        ttk.Button(cuerpo, text='GENERAR ID', command=generar).grid(row=4, column=0, pady=(0, 1))
        acciones_ids = ttk.Frame(cuerpo)
        acciones_ids.grid(row=7, column=0)
        ttk.Button(acciones_ids, text='COPIAR RESULTADO', command=copiar).pack(side='left', padx=8)
        ttk.Button(acciones_ids, text='CERRAR', command=ventana.destroy).pack(side='left', padx=8)
        estado = ttk.Label(cuerpo, text='')
        estado.grid(row=8, column=0, pady=(6, 0))
        campo_torrent.bind('<Return>', lambda e: campo_instrucciones.focus_set())
        campo_instrucciones.bind('<Return>', lambda e: generar())
        campo_torrent.focus_set()
        ventana.lift()

    def menu_contextual(self, widget):
        menu = tk.Menu(widget, tearoff=False)
        for texto, evento in [('Deshacer', '<<Undo>>'), ('Rehacer', '<<Redo>>'), ('Cortar', '<<Cut>>'), ('Copiar', '<<Copy>>'), ('Pegar', '<<Paste>>'), ('Seleccionar todo', '<<SelectAll>>')]:
            menu.add_command(label=texto, command=lambda e=evento, w=widget: w.event_generate(e))
        def mostrar(e):
            widget.focus_set()
            try:
                menu.tk_popup(e.x_root, e.y_root)
            finally:
                menu.grab_release()
        widget.bind('<Button-3>', mostrar)

    def selector_carpeta(self, padre, variable, fila, span=1):
        marco = ttk.Frame(padre)
        marco.grid(row=fila, column=0, columnspan=span, sticky='ew', pady=(3, 0))
        marco.columnconfigure(0, weight=1)
        entrada = ttk.Entry(marco, textvariable=variable)
        entrada.grid(row=0, column=0, sticky='ew', padx=(0, 5))
        self.menu_contextual(entrada)
        ttk.Button(marco, text='Examinar...', command=lambda: self.elegir_carpeta(variable)).grid(row=0, column=1)

    def elegir_carpeta(self, variable):
        actual = variable.get().strip()
        carpeta = filedialog.askdirectory(initialdir=actual if Path(actual).is_dir() else str(Path.home()))
        if carpeta:
            variable.set(carpeta)
            self.guardar_configuracion()

    def elegir_torrent(self):
        ruta = filedialog.askopenfilename(title='Seleccionar archivo torrent', filetypes=[('Archivos torrent', '*.torrent')])
        if ruta:
            self.archivo_torrent = Path(ruta)
            self.lbl_torrent.configure(text=self.archivo_torrent.name)

    def quitar_torrent(self):
        self.archivo_torrent = None
        self.lbl_torrent.configure(text='Ningún torrent seleccionado')

    def elegir_portada(self):
        ruta = filedialog.askopenfilename(title='Seleccionar portada', filetypes=[('Imágenes', '*.jpg *.jpeg *.png *.webp'), ('Todos', '*.*')])
        if ruta:
            self.portada = Path(ruta)
            self.lbl_portada.configure(text=self.portada.name)
            self.miniatura(self.portada, self.vista_portada, (180, 190))

    def quitar_portada(self):
        self.portada = None
        self.lbl_portada.configure(text='Sin portada seleccionada')
        self.vista_portada.configure(image='', text='')

    def agregar_capturas(self):
        rutas = filedialog.askopenfilenames(title='Seleccionar capturas', filetypes=[('Imágenes', '*.jpg *.jpeg *.png *.webp'), ('Todos', '*.*')])
        for ruta in rutas:
            p = Path(ruta)
            if p.suffix.lower() in FORMATOS and p not in self.imagenes_capturas:
                self.imagenes_capturas.append(p)
        self.actualizar_lista()

    def actualizar_lista(self):
        self.lista.delete(0, 'end')
        for i, p in enumerate(self.imagenes_capturas, 1):
            self.lista.insert('end', f'{i}. {p.name}')
        self.vista_captura.configure(image='', text=f'{len(self.imagenes_capturas)} captura(s) seleccionada(s)')

    def quitar_capturas(self):
        for i in reversed(self.lista.curselection()):
            del self.imagenes_capturas[i]
        self.actualizar_lista()

    def vaciar_capturas(self):
        self.imagenes_capturas.clear()
        self.actualizar_lista()

    def mostrar_captura(self):
        sel = self.lista.curselection()
        if sel:
            self.miniatura(self.imagenes_capturas[sel[0]], self.vista_captura, (300, 130))

    def miniatura(self, ruta, etiqueta, tamano):
        if Image is None:
            etiqueta.configure(image='', text='Miniaturas: instalá Pillow (pip install pillow).')
            return
        try:
            with Image.open(ruta) as img:
                img.thumbnail(tamano)
                foto = ImageTk.PhotoImage(img.copy())
            etiqueta.configure(image=foto, text='')
            etiqueta.image = foto
        except Exception:
            etiqueta.configure(image='', text='No se pudo mostrar la miniatura.')

    def guardar_configuracion(self):
        datos = {nombre: ruta.get().strip() for nombre, _, ruta in self.paneles}
        datos['CAPTURAS'] = self.ruta_capturas.get().strip()
        datos['PORTADAS'] = self.ruta_portadas.get().strip()
        datos['TORRENTS'] = self.ruta_torrents.get().strip()
        try:
            CONFIG.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass

    def procesar_imagen(self, origen, destino):
        """Procesa sin tocar la fuente, incluso cuando fuente y destino coinciden."""
        if not self.redimensionar.get():
            if origen.resolve() != destino.resolve():
                shutil.copy2(origen, destino)
            return
        with Image.open(origen) as imagen:
            imagen.load()
            if imagen.width > 600:
                altura = max(1, round(imagen.height * 600 / imagen.width))
                imagen = imagen.resize((600, altura), Image.Resampling.LANCZOS)
            # WebP admite RGB y RGBA. Convertir otros modos de manera segura.
            if imagen.mode not in ('RGB', 'RGBA'):
                imagen = imagen.convert('RGBA' if 'A' in imagen.getbands() or 'transparency' in imagen.info else 'RGB')
            fd, temporal = tempfile.mkstemp(prefix='.imagen_', suffix='.webp', dir=destino.parent)
            os.close(fd)
            try:
                imagen.save(temporal, format='WEBP', quality=75, method=6)
                os.replace(temporal, destino)
            finally:
                if os.path.exists(temporal):
                    os.unlink(temporal)

    def limpiar_formulario(self):
        """Limpia la ficha sin cambiar rutas ni borrar archivos."""
        self.nombre_juego.set('')
        for seccion, caja, _ in self.paneles:
            caja.delete('1.0', 'end')
            if seccion == 'DATOS':
                caja.insert('1.0', PLANTILLA_DATOS.format(fecha=date.today().strftime('%d/%m/%Y')))
            caja.edit_reset()
            caja.edit_modified(False)
        self.quitar_portada()
        self.vaciar_capturas()
        self.quitar_torrent()
        self.paneles[0][1].focus_set()

    def confirmar_limpieza(self):
        if messagebox.askyesno('Limpiar formulario',
                               '¿Querés limpiar todos los campos y comenzar un juego nuevo?\n\n'
                               'Se conservarán las carpetas de destino.\n'
                               'No se borrará ningún archivo guardado.'):
            self.limpiar_formulario()

    def guardar(self):
        nombre = self.nombre_juego.get().strip()
        if nombre.lower().endswith('.txt'):
            nombre = nombre[:-4]
        if (not nombre or nombre in ('.', '..') or re.search(r'[<>:"/\\|?*\x00-\x1f]', nombre)
            or nombre.endswith((' ', '.')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', nombre)):
            messagebox.showerror('Nombre inválido', 'Escribí un nombre válido para el juego.')
            return
        if self.redimensionar.get() and Image is None and (self.portada or self.imagenes_capturas):
            messagebox.showerror('Falta Pillow', 'Para convertir y redimensionar imágenes instalá Pillow:\n\npython -m pip install pillow')
            return
        trabajos = []
        for seccion, caja, ruta in self.paneles:
            contenido = caja.get('1.0', 'end-1c')
            if contenido.strip():
                carpeta = Path(ruta.get().strip()) if ruta.get().strip() else None
                if carpeta is None or not carpeta.is_dir():
                    messagebox.showerror('Carpeta inválida', f'Seleccioná una carpeta existente para {seccion}.')
                    return
                trabajos.append((carpeta / (nombre + '.txt'), contenido, None))
        if self.portada:
            destino = Path(self.ruta_portadas.get().strip()) if self.ruta_portadas.get().strip() else None
            if destino is None or not destino.is_dir():
                messagebox.showerror('Carpeta inválida', 'Seleccioná una carpeta existente para PORTADAS.')
                return
            trabajos.append((destino / (nombre + ('.webp' if self.redimensionar.get() else self.portada.suffix.lower())), None, self.portada))
        if self.archivo_torrent:
            if self.archivo_torrent.suffix.lower() != '.torrent':
                messagebox.showerror('Archivo inválido', 'Seleccioná un archivo .torrent válido.')
                return
            carpeta_torrent = Path(self.ruta_torrents.get().strip()) if self.ruta_torrents.get().strip() else None
            if carpeta_torrent is None or not carpeta_torrent.is_dir():
                messagebox.showerror('Carpeta inválida', 'Seleccioná una carpeta existente para TORRENTS (por ejemplo, la unidad de Drive).')
                return
            trabajos.append((carpeta_torrent / self.archivo_torrent.name, None, self.archivo_torrent))
        base = Path(self.ruta_capturas.get().strip()) if self.ruta_capturas.get().strip() else None
        if base is not None and not base.is_dir():
            messagebox.showerror('Carpeta inválida', 'La carpeta principal de CAPTURAS no existe.')
            return
        if self.imagenes_capturas and base is None:
            messagebox.showerror('Carpeta inválida', 'Seleccioná la carpeta principal de CAPTURAS.')
            return
        carpeta_capturas = base / nombre if base else None
        if carpeta_capturas:
            for i, origen in enumerate(self.imagenes_capturas, 1):
                trabajos.append((carpeta_capturas / (str(i) + ('.webp' if self.redimensionar.get() else origen.suffix.lower())), None, origen))
        if not trabajos and carpeta_capturas is None:
            messagebox.showinfo('Nada que guardar', 'Completá un texto, elegí una portada o seleccioná capturas.')
            return
        destinos = [str(p.absolute()).casefold() for p, _, _ in trabajos]
        if len(destinos) != len(set(destinos)):
            messagebox.showerror('Destinos repetidos', 'Hay dos archivos con el mismo destino. Revisá las carpetas.')
            return
        for _, _, origen in trabajos:
            if origen is not None and not origen.is_file():
                messagebox.showerror('Archivo no encontrado', f'No existe la imagen: {origen}')
                return
        existentes = [str(p) for p, _, _ in trabajos if p.exists()]
        if existentes and not messagebox.askyesno('Archivos existentes', f'{len(existentes)} archivo(s) ya existen y serán reemplazados.\n\n' + '\n'.join(existentes[:12]) + ('\n...' if len(existentes)>12 else '') + '\n\n¿Continuar?'):
            return
        guardados = 0
        try:
            if carpeta_capturas:
                carpeta_capturas.mkdir(exist_ok=True)
            for destino, contenido, origen in trabajos:
                if origen is None:
                    destino.write_text(contenido, encoding='utf-8')
                elif origen.suffix.lower() == '.torrent':
                    if origen.resolve() != destino.resolve():
                        shutil.copy2(origen, destino)
                else:
                    self.procesar_imagen(origen, destino)
                guardados += 1
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror('Error al guardar', f'Se procesaron {guardados} archivo(s) antes del error:\n{error}')
            return
        self.guardar_configuracion()
        txt = sum(1 for _, contenido, _ in trabajos if contenido is not None)
        mensaje = f'¡Listo!\n\nTXT: {txt}\nPortada: {1 if self.portada else 0}\nCapturas: {len(self.imagenes_capturas)}\nTorrent copiado: {1 if self.archivo_torrent else 0}'
        if carpeta_capturas:
            mensaje += f'\n\nCarpeta de capturas: {carpeta_capturas}'
        self.limpiar_formulario()
        messagebox.showinfo('Guardado completo', mensaje)
        self.abrir_generador_ids()

    def cerrar(self):
        self.guardar_configuracion()
        self.destroy()

if __name__ == '__main__':
    Generador().mainloop()
