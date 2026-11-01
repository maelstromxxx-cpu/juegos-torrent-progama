import json
import re
import shutil
import os
import tempfile
import subprocess
import shutil as shutil_browser
import threading
import urllib.parse
import urllib.request
import html
from html.parser import HTMLParser
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
PLANTILLA_DATOS = ('Año:\nGénero:\nTamaño:\nModo: Singleplayer\nIdioma: MULTI\n'
                  'Fecha de incorporación: {fecha}\nPuntuación:\nMetacritic:\nRepacker: FitGirl\n')

FORMATOS = ('.jpg', '.jpeg', '.png', '.webp')

USER_AGENT = 'Mozilla/5.0 (compatible; KalakasSoftSteam/1.0)'

class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.skip += 1
        elif not self.skip and tag in ('p', 'br', 'li', 'div', 'h2', 'h3', 'ul'):
            self.parts.append('\n')
        if tag == 'li' and not self.skip:
            self.parts.append('• ')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in ('p', 'li', 'div', 'h2', 'h3'):
            self.parts.append('\n')
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

def clean_html(value):
    parser = HTMLText()
    parser.feed(value or '')
    text = html.unescape(''.join(parser.parts)).replace('\xa0', ' ')
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()

def fetch_json(url, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(url + '?' + query, headers={
        'User-Agent': USER_AGENT, 'Accept': 'application/json',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.7'
    })
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)

def fetch_bytes(url):
    if not url.startswith('https://'):
        raise ValueError('Solo se admiten imágenes HTTPS.')
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read(15 * 1024 * 1024 + 1)
        if len(data) > 15 * 1024 * 1024:
            raise ValueError('La imagen supera el límite de 15 MB.')
        return data

def find_appid(text):
    match = re.search(r'(?:store\.steampowered\.com/app/)?(\d{3,12})', text.strip())
    return int(match.group(1)) if match and (text.strip().isdigit() or 'steampowered.com/app/' in text) else None

def obtener_porcentaje_pagina_steam(appid):
    """Lee SOLO la fila 'Todas las reseñas' del HTML público de Steam.

    No confunde la fila de reseñas recientes con la histórica. Si Steam
    bloquea la página o cambia su estructura, devuelve un error diagnosticable.
    """
    url = f'https://store.steampowered.com/app/{appid}/?l=english&cc=us'
    req = urllib.request.Request(url, headers={
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/131.0.0.0 Safari/537.36'),
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=20) as respuesta:
        pagina = respuesta.read(3 * 1024 * 1024).decode('utf-8', errors='replace')

    # El identificador review_summary corresponde a 'All Reviews'.
    # review_summary_recent corresponde a los últimos 30 días y se ignora.
    fila = re.search(r'<[^>]+\bid=[\"\']review_summary[\"\'][^>]*>', pagina, re.I)
    if not fila:
        raise ValueError('La página no contiene la fila de reseñas generales (quizás bloqueo, edad o cambio de HTML).')
    fragmento = pagina[fila.end():fila.end() + 4500]
    # El tooltip de Steam suele decir: '92% of the 123 user reviews ... are positive.'
    for etiqueta in re.findall(r'<[^>]+>', fragmento):
        if 'data-tooltip-html' not in etiqueta.lower():
            continue
        match = re.search(r'data-tooltip-html\s*=\s*([\"\'])(.*?)\1', etiqueta, re.I | re.S)
        if not match:
            continue
        tooltip = html.unescape(match.group(2))
        porcentaje = re.search(r'(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*%', tooltip)
        if porcentaje:
            valor = float(porcentaje.group(1).replace(',', '.'))
            if 0 <= valor <= 100:
                return valor, f'Fuente: página pública de Steam, TODAS las reseñas ({valor:g} % positivas).'
    raise ValueError('Se encontró la fila histórica, pero no su porcentaje de reseñas positivas.')


def encontrar_navegador():
    """Chrome/Edge/Chromium; no requiere instalar paquetes Python."""
    candidatos = []
    for nombre in ('msedge', 'chrome', 'chromium', 'chromium-browser', 'google-chrome'):
        ruta = shutil_browser.which(nombre)
        if ruta:
            candidatos.append(ruta)
    if os.name == 'nt':
        for variable in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA'):
            raiz = os.environ.get(variable)
            if raiz:
                for relativo in ('Microsoft/Edge/Application/msedge.exe',
                                 'Google/Chrome/Application/chrome.exe'):
                    candidatos.append(str(Path(raiz) / relativo))
    return next((ruta for ruta in candidatos if Path(ruta).is_file()), None)


def extraer_porcentaje_historico(html_pagina):
    """Extrae exclusivamente el porcentaje del bloque All Reviews."""
    # El atributo ID es propio del resumen histórico, no review_summary_recent.
    patron = re.search(r'<[^>]+\bid=["\']review_summary["\'][^>]*>', html_pagina, re.I)
    if not patron:
        raise ValueError('El navegador no entregó el bloque de reseñas generales.')
    bloque = html_pagina[patron.end():patron.end() + 6000]
    # El tooltip suele contener "XX% of the ... user reviews ... are positive".
    for etiqueta in re.findall(r'<[^>]+>', bloque):
        if 'data-tooltip-html' not in etiqueta.lower():
            continue
        match = re.search(r'data-tooltip-html\s*=\s*(["\'])(.*?)\1', etiqueta, re.I | re.S)
        if match:
            texto = html.unescape(match.group(2))
            porcentaje = re.search(r'(?<!\d)(\d{1,3}(?:[.,]\d+)?)\s*%', texto)
            if porcentaje:
                valor = float(porcentaje.group(1).replace(',', '.'))
                if 0 <= valor <= 100:
                    return valor
    raise ValueError('Se encontró el resumen general, pero no el porcentaje.')


def obtener_porcentaje_navegador(appid):
    """Prueba navegador real en modo sin interfaz; no altera perfil del usuario."""
    ejecutable = encontrar_navegador()
    if not ejecutable:
        raise RuntimeError('No se encontró Chrome, Edge o Chromium instalado.')
    url = f'https://store.steampowered.com/app/{int(appid)}/?l=english&cc=us'
    with tempfile.TemporaryDirectory(prefix='kalaka_steam_browser_') as perfil:
        comando = [ejecutable, '--headless', '--disable-gpu', '--no-first-run',
                   '--no-default-browser-check', '--disable-extensions',
                   '--disable-background-networking', '--disable-sync',
                   '--user-data-dir=' + perfil, '--virtual-time-budget=8000',
                   '--dump-dom', url]
        resultado = subprocess.run(comando, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=25,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if not resultado.stdout.strip():
            raise RuntimeError(f'El navegador no entregó HTML (código {resultado.returncode}).')
        valor = extraer_porcentaje_historico(resultado.stdout)
        return valor, f'Fuente: navegador ({Path(ejecutable).name}), TODAS las reseñas ({valor:g} % positivas).'


def obtener_valoracion_steam(appid):
    """Nota histórica (todas las reseñas), usando la nueva Web API de Steam.

    GetAppReviews reemplazó /appreviews en octubre de 2026. El resumen de
    la primera página incluye total_positive/total_reviews para TODA la
    vida del juego; el filtro Recent solo ordena los resultados individuales.
    """
    problemas = []
    try:
        parametros = {
            'appid': int(appid),
            'filter': 1,              # Orden reciente, NO limitar a 30 días.
            'languages': ['all'],     # Reseñas en todos los idiomas.
            'review_type': 0,         # Todas: positivas y negativas.
            'purchase_type': 1,       # Compras dentro y fuera de Steam.
            'num_per_page': 1,        # Solo necesitamos el resumen.
            'cursor': '*',
        }
        datos = fetch_json(
            'https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/',
            {'input_json': json.dumps(parametros, separators=(',', ':'))}
        )
        respuesta = datos.get('response') or {}
        resumen = respuesta.get('query_summary') or {}
        positivos = resumen.get('total_positive')
        total = resumen.get('total_reviews')
        if (isinstance(positivos, int) and isinstance(total, int)
                and total > 0 and 0 <= positivos <= total):
            porcentaje = round(100 * positivos / total, 1)
            return porcentaje, (
                f'Fuente: Steam Web API oficial (GetAppReviews).\n'
                f'Reseñas GENERALES de todos los tiempos: {positivos:,} '
                f'positivas / {total:,} totales ({porcentaje:g} %).\n'
                'No se utilizan las reseñas de los últimos 30 días.'
            )
        problemas.append('Steam Web API: sin totales históricos válidos en query_summary.')
    except Exception as exc:
        problemas.append(f'Steam Web API: {type(exc).__name__}: {exc}')

    # Respaldo: SteamSpy (puede tener cobertura incompleta o datos estimados).
    try:
        datos = fetch_json('https://steamspy.com/api.php', {
            'request': 'appdetails', 'appid': appid
        })
        positivos = datos.get('positive')
        negativos = datos.get('negative')
        if (isinstance(positivos, int) and isinstance(negativos, int)
                and positivos >= 0 and negativos >= 0 and positivos + negativos > 0):
            total = positivos + negativos
            porcentaje = round(100 * positivos / total, 1)
            return porcentaje, (
                f'Fuente alternativa: SteamSpy (estadísticas acumuladas aproximadas). '
                f'{positivos:,} positivas / {total:,} reseñas.\n' + '\n'.join(problemas)
            )
        problemas.append('SteamSpy: sin estadísticas de reseñas suficientes.')
    except Exception as exc:
        problemas.append(f'SteamSpy: {type(exc).__name__}: {exc}')
    return None, '\n'.join(problemas)


def obtener_metacritic(info):
    """Metacritic es opcional en la ficha de Steam."""
    dato = info.get('metacritic') or {}
    nota = dato.get('score') if isinstance(dato, dict) else None
    return nota if isinstance(nota, int) and 0 <= nota <= 100 else None


def to_data(info, tamano='', repacker='FitGirl', review_percent=None):
    """Construye la ficha sin inventar notas ni el tamaño del repack."""
    genres = ' / '.join(g.get('description', '').strip() for g in info.get('genres', [])
                        if g.get('description', '').strip())
    categories = [x.get('description', '').lower() for x in info.get('categories', [])]
    single = any('single-player' in x or 'un jugador' in x for x in categories)
    multi = any('multi-player' in x or 'multijugador' in x or 'co-op' in x or 'cooperativo' in x
                for x in categories)
    modo = 'Singleplayer / Multiplayer' if single and multi else ('Multiplayer' if multi else 'Singleplayer')
    release = info.get('release_date') or {}
    fecha = release.get('date', '')
    year = re.search(r'\b(?:19|20)\d{2}\b', fecha)
    metacritic = obtener_metacritic(info)
    metacritic = '' if metacritic is None else metacritic
    puntuacion = ''
    if isinstance(review_percent, (int, float)) and 0 <= review_percent <= 100:
        puntuacion = f'{review_percent / 10:.1f}'.replace('.', ',')
    return (f'Año: {year.group(0) if year else ""}\n'
            f'Género: {genres}\n'
            f'Tamaño: {tamano.strip()}\n'
            f'Modo: {modo}\n'
            f'Idioma: MULTI\n'
            f'Fecha de incorporación: {date.today():%d/%m/%Y}\n'
            f'Puntuación: {puntuacion}\n'
            f'Metacritic: {metacritic}\n'
            f'Repacker: {repacker.strip() or "FitGirl"}\n')


class Generador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Generador de TXT/MD, portadas, capturas y torrents - v13.5.9 SteamGridDB')
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
        self._steam_temporales = set()
        self.portada = None
        self.steam_appid = None
        self.sgdb_key = tk.StringVar(value=self.configuracion.get('STEAMGRIDDB_KEY', ''))
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
        ttk.Button(fotos, text='Buscar portada en SteamGridDB', command=self.abrir_portadas_steamgrid).grid(row=0, column=2, padx=8, sticky='w')
        self.lbl_portada = ttk.Label(fotos, text='Sin portada seleccionada', wraplength=350)
        self.lbl_portada.grid(row=1, column=0, columnspan=2, sticky='w', pady=6)
        self.vista_portada = ttk.Label(fotos)
        self.vista_portada.grid(row=2, column=0, columnspan=2, sticky='w')
        ttk.Label(fotos, text='Carpeta de destino de la portada:').grid(row=3, column=0, columnspan=2, sticky='w', pady=(7, 0))
        self.selector_carpeta(fotos, self.ruta_portadas, 4, span=2)
        ttk.Label(fotos, text='Se guardará como Nombre del juego.webp (con procesamiento activado).', wraplength=360).grid(row=5, column=0, columnspan=2, sticky='w', pady=(5, 0))

        capturas = ttk.LabelFrame(principal, text='  CAPTURAS  ', padding=10)
        capturas.grid(row=1, column=1, columnspan=2, sticky='nsew', padx=5, pady=(10, 0))
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
        torrent_panel.grid(row=1, column=3, sticky='nsew', padx=5, pady=(10, 0))
        torrent_panel.columnconfigure(0, weight=1)
        botones_torrent = ttk.Frame(torrent_panel)
        botones_torrent.grid(row=0, column=0, sticky='w')
        ttk.Button(botones_torrent, text='Examinar torrent...', command=self.elegir_torrent).pack(side='left', padx=(0, 8))
        ttk.Button(botones_torrent, text='Quitar torrent', command=self.quitar_torrent).pack(side='left')
        self.lbl_torrent = ttk.Label(torrent_panel, text='Ningún torrent seleccionado')
        self.lbl_torrent.grid(row=1, column=0, sticky='w', pady=(5, 8))
        ttk.Label(torrent_panel, text='Carpeta de destino (Google Drive o local):').grid(row=2, column=0, sticky='w')
        self.selector_carpeta(torrent_panel, self.ruta_torrents, 3)
        ttk.Label(torrent_panel, text='El .torrent conserva su nombre original.', wraplength=310).grid(row=4, column=0, sticky='w', pady=(5, 0))

        ttk.Checkbutton(self, text='Convertir a WEBP (calidad 75) y reducir a 600 px de ancho sin deformar', variable=self.redimensionar).pack(pady=(8, 0))
        acciones = ttk.Frame(self)
        acciones.pack(pady=12)
        ttk.Button(acciones, text='GUARDAR TODOS', command=self.guardar).pack(side='left', padx=8, ipadx=30, ipady=7)
        ttk.Button(acciones, text='LIMPIAR TODO', command=self.confirmar_limpieza).pack(side='left', padx=8, ipadx=20, ipady=7)
        ttk.Button(acciones, text='GENERADOR DE ID', command=self.abrir_generador_ids).pack(side='left', padx=8, ipadx=18, ipady=7)
        ttk.Button(acciones, text='BUSCAR EN STEAM', command=self.abrir_steam).pack(side='left', padx=8, ipadx=18, ipady=7)
        self.protocol('WM_DELETE_WINDOW', self.cerrar)

    def abrir_steam(self):
        """Buscador opcional. Nunca modifica archivos hasta GUARDAR TODOS."""
        ventana = tk.Toplevel(self)
        ventana.title('Kalaka’s Soft · Importar metadatos de Steam')
        ventana.geometry('980x690')
        ventana.minsize(720, 500)
        ventana.transient(self)
        estado = tk.StringVar(value='Buscá un juego por nombre, AppID o URL de Steam.')
        busqueda = tk.StringVar(value=self.nombre_juego.get().strip() or 'Far Cry 5')
        opciones = ttk.Frame(ventana, padding=(10, 3))
        opciones.pack(fill='x')
        ttk.Label(opciones, text='Tamaño del repack:').pack(side='left')
        tamano_steam = tk.StringVar()
        ttk.Entry(opciones, textvariable=tamano_steam, width=15).pack(side='left', padx=(5, 16))
        ttk.Label(opciones, text='Repacker:').pack(side='left')
        repacker_steam = tk.StringVar(value='FitGirl')
        ttk.Entry(opciones, textvariable=repacker_steam, width=18).pack(side='left', padx=5)
        ttk.Label(opciones, text='Idioma: MULTI · Fecha: hoy', foreground='#39734c').pack(side='left', padx=12)
        resultados = []
        detalles = {'data': None, 'images': [], 'review_percent': None, 'diagnostico': '', 'manual': False}
        en_curso = {'value': False}
        cabecera = ttk.Frame(ventana, padding=10)
        cabecera.pack(fill='x')
        ttk.Label(cabecera, text='Juego:').pack(side='left')
        campo = ttk.Entry(cabecera, textvariable=busqueda)
        campo.pack(side='left', fill='x', expand=True, padx=8)
        buscar_btn = ttk.Button(cabecera, text='Buscar')
        buscar_btn.pack(side='left')
        ttk.Label(ventana, text='Los datos se importan solo cuando vos confirmás. La portada sigue siendo manual.', foreground='#39734c').pack(anchor='w', padx=12)
        panel = ttk.Panedwindow(ventana, orient='horizontal')
        panel.pack(fill='both', expand=True, padx=10, pady=8)
        izquierda = ttk.Frame(panel)
        derecha = ttk.Frame(panel)
        panel.add(izquierda, weight=1)
        panel.add(derecha, weight=3)
        ttk.Label(izquierda, text='Resultados (doble clic para cargar):').pack(anchor='w')
        lista = tk.Listbox(izquierda, exportselection=False)
        lista.pack(fill='both', expand=True, pady=5)
        cargar_btn = ttk.Button(izquierda, text='Cargar seleccionado')
        cargar_btn.pack(fill='x')
        pestanas = ttk.Notebook(derecha)
        pestanas.pack(fill='both', expand=True)
        cuadros = {}
        for nombre in ('DATOS', 'SINOPSIS'):
            tab = ttk.Frame(pestanas, padding=5)
            pestanas.add(tab, text=nombre)
            caja = tk.Text(tab, wrap='word', undo=True, font=('Segoe UI', 10))
            scroll = ttk.Scrollbar(tab, orient='vertical', command=caja.yview)
            caja.configure(yscrollcommand=scroll.set)
            caja.pack(side='left', fill='both', expand=True)
            scroll.pack(side='right', fill='y')
            cuadros[nombre] = caja
        tab_img = ttk.Frame(pestanas, padding=8)
        pestanas.add(tab_img, text='CAPTURAS')
        ttk.Label(tab_img, text='Elegí las capturas que quieras agregar al generador (Ctrl + clic).', wraplength=550).pack(anchor='w')
        lista_img = tk.Listbox(tab_img, selectmode='extended', exportselection=False)
        lista_img.pack(fill='both', expand=True, pady=6)
        ttk.Label(tab_img, text='Se descargarán al importar. Luego GUARDAR TODOS las procesa normalmente.', wraplength=550).pack(anchor='w')
        pie = ttk.Frame(ventana, padding=10)
        pie.pack(fill='x')
        actualizar_btn = ttk.Button(pie, text='ACTUALIZAR FICHA', state='disabled')
        actualizar_btn.pack(side='left', padx=4)
        importar_btn = ttk.Button(pie, text='IMPORTAR DATOS Y SINOPSIS', state='disabled')
        importar_btn.pack(side='left', padx=4)
        fotos_btn = ttk.Button(pie, text='AGREGAR CAPTURAS SELECCIONADAS', state='disabled')
        fotos_btn.pack(side='left', padx=4)
        def ver_diagnostico():
            if not detalles['data']:
                messagebox.showinfo('Valoraciones', 'Primero cargá un juego.', parent=ventana)
                return
            nota = obtener_metacritic(detalles['data'])
            texto = ('Puntuación (reseñas GENERALES/históricas; Steam Web API, SteamSpy o entrada manual):\n'
                     + detalles['diagnostico'] + '\n\n'
                     + 'Metacritic: ' + (str(nota) if nota is not None else
                       'No incluido en los metadatos de Steam para este juego. Se deja vacío.')
                     + '\n\nSi no hay valoraciones, podés completarlas manualmente en DATOS.')
            messagebox.showinfo('Diagnóstico de valoraciones', texto, parent=ventana)
        ttk.Button(pie, text='VER ESTADO DE NOTAS', command=ver_diagnostico).pack(side='left', padx=4)
        fila_nota = ttk.Frame(ventana, padding=(12, 2))
        fila_nota.pack(fill='x')
        ttk.Label(fila_nota, text='Reseñas GENERALES de Steam (% positivas):').pack(side='left')
        porcentaje_manual = tk.StringVar()
        ttk.Entry(fila_nota, textvariable=porcentaje_manual, width=9).pack(side='left', padx=7)
        def aplicar_nota_historica():
            if not detalles['data']:
                messagebox.showinfo('Valoración histórica', 'Primero cargá un juego.', parent=ventana)
                return
            texto = porcentaje_manual.get().strip().replace('%', '').replace(',', '.')
            try:
                valor = float(texto)
                if not 0 <= valor <= 100:
                    raise ValueError()
            except ValueError:
                messagebox.showerror('Porcentaje inválido', 'Ingresá un porcentaje entre 0 y 100. Ejemplo: 86 o 86,5.', parent=ventana)
                return
            detalles['review_percent'] = valor
            detalles['manual'] = True
            detalles['diagnostico'] = (f'Fuente: porcentaje de reseñas GENERALES de Steam ingresado manualmente ({valor:g} %). '
                                      'No corresponde a reseñas recientes. Nota calculada: '
                                      f'{valor / 10:.1f}/10.')
            actualizar_ficha()
            estado.set(f'Nota histórica aplicada: {valor:g} % positivas = {valor / 10:.1f}/10. '
                       'Revisá DATOS y luego importá.')
        ttk.Button(fila_nota, text='APLICAR NOTA HISTÓRICA', command=aplicar_nota_historica).pack(side='left', padx=5)
        ttk.Label(fila_nota, text='Usar "Todas las reseñas", NO "Recientes".', foreground='#39734c').pack(side='left', padx=8)
        ttk.Label(ventana, textvariable=estado, wraplength=920).pack(fill='x', padx=12, pady=(0, 8))

        def tarea(func, listo):
            if en_curso['value']:
                return
            en_curso['value'] = True
            buscar_btn.configure(state='disabled')
            cargar_btn.configure(state='disabled')
            fotos_btn.configure(state='disabled')
            estado.set('Consultando / descargando...')
            def terminar(resultado=None, error=None):
                if not ventana.winfo_exists():
                    return
                en_curso['value'] = False
                buscar_btn.configure(state='normal')
                cargar_btn.configure(state='normal')
                fotos_btn.configure(state='normal' if detalles['images'] else 'disabled')
                if error:
                    estado.set('Error: ' + error)
                    messagebox.showerror('Steam', error, parent=ventana)
                else:
                    listo(resultado)
            def ejecutar():
                try:
                    valor = func()
                    self.after(0, lambda: terminar(valor))
                except Exception as exc:
                    mensaje = str(exc)
                    self.after(0, lambda: terminar(error=mensaje))
            threading.Thread(target=ejecutar, daemon=True).start()

        def buscar():
            texto = busqueda.get().strip()
            if not texto:
                return
            appid = find_appid(texto)
            if appid:
                establecer_resultados([{'id': appid, 'name': f'AppID {appid}'}])
                lista.selection_set(0)
                cargar()
                return
            tarea(lambda: fetch_json('https://store.steampowered.com/api/storesearch/',
                                     {'term': texto, 'l': 'spanish', 'cc': 'ar'}).get('items', []), establecer_resultados)

        def establecer_resultados(items):
            resultados[:] = items
            lista.delete(0, 'end')
            for item in items:
                lista.insert('end', f'{item.get("name", "Sin nombre")} [{item.get("id")}]')
            estado.set(f'{len(items)} resultados. Seleccioná el juego y cargalo.')

        def cargar():
            seleccion = lista.curselection()
            if not seleccion or en_curso['value']:
                return
            appid = resultados[seleccion[0]]['id']
            def obtener():
                respuesta = fetch_json('https://store.steampowered.com/api/appdetails',
                                      {'appids': appid, 'l': 'spanish', 'cc': 'ar'})
                registro = respuesta.get(str(appid), {})
                if not registro.get('success') or not registro.get('data'):
                    raise ValueError('Steam no devolvió datos para este juego.')
                info = registro['data']
                review_percent, diagnostico = obtener_valoracion_steam(appid)
                return info, review_percent, diagnostico
            def mostrar(resultado):
                info, review_percent, diagnostico = resultado
                detalles['data'] = info
                self.steam_appid = appid
                detalles['review_percent'] = review_percent
                detalles['manual'] = False
                porcentaje_manual.set('')
                detalles['diagnostico'] = diagnostico
                for nombre, valor in (('DATOS', to_data(info, tamano_steam.get(), repacker_steam.get(), review_percent)),
                                      ('SINOPSIS', clean_html(info.get('detailed_description') or info.get('about_the_game') or info.get('short_description') or ''))):
                    cuadros[nombre].delete('1.0', 'end')
                    cuadros[nombre].insert('1.0', valor)
                detalles['images'] = [(f'Captura {i:02}', item['path_full']) for i, item in enumerate(info.get('screenshots', []), 1)
                                       if isinstance(item.get('path_full'), str) and item['path_full'].startswith('https://')]
                lista_img.delete(0, 'end')
                for nombre, url in detalles['images']:
                    lista_img.insert('end', nombre + ' — ' + url)
                importar_btn.configure(state='normal')
                actualizar_btn.configure(state='normal')
                fotos_btn.configure(state='normal' if detalles['images'] else 'disabled')
                nota_mc = obtener_metacritic(info)
                estado.set(f'{info.get("name", "Juego")} · {len(detalles["images"])} capturas · '
                           f'Reseñas históricas: {review_percent if review_percent is not None else "sin nota"} % · '
                           f'Metacritic: {nota_mc if nota_mc is not None else "no informado"}.')
                pestanas.select(0)
            tarea(obtener, mostrar)

        def importar():
            info = detalles['data']
            if not info:
                return
            nuevos = {nombre: cuadros[nombre].get('1.0', 'end-1c') for nombre in ('DATOS', 'SINOPSIS')}
            actuales = {nombre: caja.get('1.0', 'end-1c') for nombre, caja, _ in self.paneles if nombre in nuevos}
            # Nunca pisar un texto que el usuario ya trabajó sin pedir permiso.
            if any(actuales[n].strip() and actuales[n].strip() != PLANTILLA_DATOS.format(fecha=date.today().strftime('%d/%m/%Y')).strip() for n in nuevos):
                if not messagebox.askyesno('Reemplazar textos', 'Ya hay contenido en Datos o Sinopsis. ¿Querés reemplazarlo por lo importado de Steam?', parent=ventana):
                    return
            self.nombre_juego.set(info.get('name', self.nombre_juego.get()))
            for nombre, caja, _ in self.paneles:
                if nombre in nuevos:
                    caja.delete('1.0', 'end')
                    caja.insert('1.0', nuevos[nombre])
            estado.set('Datos y Sinopsis importados al generador. Podés editarlos antes de guardar.')
            messagebox.showinfo('Importación lista', 'Datos y Sinopsis copiados al generador. Instrucciones y Updates no se modificaron.', parent=ventana)

        def descargar_capturas():
            seleccion = lista_img.curselection()
            if not seleccion:
                messagebox.showinfo('Capturas', 'Seleccioná una o más capturas.', parent=ventana)
                return
            elegidas = [detalles['images'][i] for i in seleccion]
            def bajar():
                descargadas = []
                fallos = []
                for nombre, url in elegidas:
                    try:
                        datos = fetch_bytes(url)
                        extension = Path(urllib.parse.urlsplit(url).path).suffix.lower()
                        if extension not in FORMATOS:
                            extension = '.jpg'
                        with tempfile.NamedTemporaryFile(prefix='kalaka_steam_', suffix=extension, delete=False) as archivo:
                            archivo.write(datos)
                            descargadas.append(Path(archivo.name))
                    except Exception as exc:
                        fallos.append(f'{nombre}: {exc}')
                return descargadas, fallos
            def listo(resultado):
                descargadas, fallos = resultado
                for ruta in descargadas:
                    self._steam_temporales.add(ruta)
                    if ruta not in self.imagenes_capturas:
                        self.imagenes_capturas.append(ruta)
                self.actualizar_lista()
                estado.set(f'{len(descargadas)} capturas agregadas al generador. {len(fallos)} errores.')
                messagebox.showinfo('Capturas', f'Agregadas: {len(descargadas)}\nErrores: {len(fallos)}\nSe procesarán al pulsar GUARDAR TODOS.', parent=ventana)
            tarea(bajar, listo)

        def actualizar_ficha():
            if not detalles['data']:
                return
            texto = to_data(detalles['data'], tamano_steam.get(), repacker_steam.get(),
                            detalles['review_percent'])
            cuadros['DATOS'].delete('1.0', 'end')
            cuadros['DATOS'].insert('1.0', texto)
            estado.set('Ficha actualizada con tamaño y repacker. Revisá antes de importar.')

        actualizar_btn.configure(command=actualizar_ficha)
        buscar_btn.configure(command=buscar)
        cargar_btn.configure(command=cargar)
        importar_btn.configure(command=importar)
        fotos_btn.configure(command=descargar_capturas)
        lista.bind('<Double-1>', lambda e: cargar())
        campo.bind('<Return>', lambda e: buscar())
        ventana.after(100, buscar)

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
        if getattr(self, 'ventana_ids', None) and self.ventana_ids.winfo_exists():
            self.ventana_ids.lift()
            return
        ventana = tk.Toplevel(self)
        self.ventana_ids = ventana
        ventana.title('Generador de ID y editor de catálogo')
        ventana.geometry('1320x700')
        ventana.minsize(980, 530)
        ventana.transient(self)
        cuerpo = ttk.Frame(ventana, padding=12)
        cuerpo.pack(fill='both', expand=True)
        cuerpo.columnconfigure(0, weight=2)
        cuerpo.columnconfigure(1, weight=3)
        cuerpo.rowconfigure(0, weight=1)
        izquierda = ttk.LabelFrame(cuerpo, text=' GENERADOR DE REGISTROS ', padding=12)
        derecha = ttk.LabelFrame(cuerpo, text=' EDITOR DE CATALOGO.TXT ', padding=12)
        izquierda.grid(row=0, column=0, sticky='nsew', padx=(0, 7))
        derecha.grid(row=0, column=1, sticky='nsew', padx=(7, 0))
        izquierda.columnconfigure(0, weight=1)
        derecha.columnconfigure(0, weight=1)
        derecha.rowconfigure(2, weight=1)
        titulo = tk.StringVar(value=getattr(self, 'ultimo_juego_guardado', '') or self.nombre_juego.get().strip())
        torrent = tk.StringVar()
        instrucciones = tk.StringVar()
        update = tk.StringVar()
        modo = tk.StringVar(value='completo')
        resultado = tk.StringVar()
        ruta_catalogo = tk.StringVar(value=self.configuracion.get('CATALOGO', ''))
        estado = ttk.Label(izquierda, text='', wraplength=410)
        for fila, (etiqueta, variable) in enumerate((('Título del juego:', titulo), ('Enlace Drive del TORRENT:', torrent), ('Enlace Drive de INSTRUCCIONES:', instrucciones), ('Enlace Drive del UPDATE (opcional):', update))):
            ttk.Label(izquierda, text=etiqueta).grid(row=fila * 2, column=0, sticky='w', pady=(7, 0))
            entrada = ttk.Entry(izquierda, textvariable=variable)
            entrada.grid(row=fila * 2 + 1, column=0, sticky='ew', pady=(2, 5))
            self.menu_contextual(entrada)
        modos = ttk.Frame(izquierda)
        modos.grid(row=8, column=0, sticky='w', pady=(9, 5))
        ttk.Radiobutton(modos, text='Juego completo', variable=modo, value='completo').pack(side='left', padx=(0, 14))
        ttk.Radiobutton(modos, text='Solo update', variable=modo, value='update').pack(side='left')
        ttk.Label(izquierda, text='Resultado generado:').grid(row=9, column=0, sticky='w', pady=(8, 2))
        salida = tk.Text(izquierda, height=4, wrap='none', undo=False, font=('Consolas', 10))
        salida.grid(row=10, column=0, sticky='ew')
        self.menu_contextual(salida)
        botones = ttk.Frame(izquierda)
        botones.grid(row=11, column=0, sticky='w', pady=(12, 6))
        estado.grid(row=12, column=0, sticky='w', pady=(5, 0))
        ttk.Label(izquierda, text='El catálogo se guarda únicamente al pulsar GUARDAR CATÁLOGO.', wraplength=410).grid(row=13, column=0, sticky='w', pady=(15, 0))

        herramientas = ttk.Frame(derecha)
        herramientas.grid(row=0, column=0, sticky='ew', pady=(0, 6))
        herramientas.columnconfigure(0, weight=1)
        ruta_label = ttk.Label(derecha, textvariable=ruta_catalogo, wraplength=650)
        ruta_label.grid(row=1, column=0, sticky='w', pady=(0, 6))
        marco_texto = ttk.Frame(derecha)
        marco_texto.grid(row=2, column=0, sticky='nsew')
        marco_texto.columnconfigure(0, weight=1)
        marco_texto.rowconfigure(0, weight=1)
        editor = tk.Text(marco_texto, wrap='none', undo=True, font=('Consolas', 10))
        editor.grid(row=0, column=0, sticky='nsew')
        scroll_y = ttk.Scrollbar(marco_texto, orient='vertical', command=editor.yview)
        scroll_y.grid(row=0, column=1, sticky='ns')
        scroll_x = ttk.Scrollbar(marco_texto, orient='horizontal', command=editor.xview)
        scroll_x.grid(row=1, column=0, sticky='ew')
        editor.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self.menu_contextual(editor)
        estado_catalogo = ttk.Label(derecha, text='')
        estado_catalogo.grid(row=3, column=0, sticky='w', pady=(7, 0))
        ruta_actual = [None]
        cargando = [False]

        def cambio_editor(event=None):
            if editor.edit_modified():
                if not cargando[0]:
                    estado_catalogo.configure(text='● Cambios sin guardar')
                editor.edit_modified(False)
        editor.bind('<<Modified>>', cambio_editor)

        def abrir_archivo(ruta):
            ruta = Path(ruta)
            if not ruta.is_file():
                messagebox.showerror('Catálogo no encontrado', f'No existe el archivo:\n{ruta}', parent=ventana)
                return
            if ruta_actual[0] and editor.get('1.0', 'end-1c') != contenido_guardado[0]:
                if not messagebox.askyesno('Cambios sin guardar', 'Hay cambios sin guardar. ¿Descartarlos y abrir otro archivo?', parent=ventana):
                    return
            try:
                texto = ruta.read_text(encoding='utf-8-sig')
            except (OSError, UnicodeError) as error:
                messagebox.showerror('Error al abrir', str(error), parent=ventana)
                return
            cargando[0] = True
            editor.delete('1.0', 'end')
            editor.insert('1.0', texto)
            editor.edit_reset()
            editor.edit_modified(False)
            cargando[0] = False
            contenido_guardado[0] = texto
            ruta_actual[0] = ruta
            ruta_catalogo.set(str(ruta))
            self.configuracion['CATALOGO'] = str(ruta)
            self.guardar_configuracion()
            estado_catalogo.configure(text=f'Abierto: {ruta.name}')

        contenido_guardado = ['']

        def elegir_archivo():
            elegido = filedialog.askopenfilename(parent=ventana, title='Abrir catalogo.txt', initialdir=str(ruta_actual[0].parent) if ruta_actual[0] else str(Path.home()), filetypes=[('Archivos de texto', '*.txt'), ('Todos los archivos', '*.*')])
            if elegido:
                abrir_archivo(elegido)

        def guardar_catalogo():
            ruta = ruta_actual[0]
            if ruta is None:
                elegido = filedialog.asksaveasfilename(parent=ventana, title='Guardar catálogo', defaultextension='.txt', initialfile='catalogo.txt', filetypes=[('Archivos de texto', '*.txt')])
                if not elegido:
                    return False
                ruta = Path(elegido)
            texto = editor.get('1.0', 'end-1c')
            try:
                # Reemplazo atómico: evita truncar el catálogo ante fallos de escritura.
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=ruta.parent, prefix='.catalogo_', suffix='.tmp', delete=False) as temporal:
                    temporal.write(texto)
                    nombre_temporal = temporal.name
                try:
                    os.replace(nombre_temporal, ruta)
                finally:
                    if os.path.exists(nombre_temporal):
                        os.unlink(nombre_temporal)
            except OSError as error:
                messagebox.showerror('Error al guardar catálogo', str(error), parent=ventana)
                return False
            ruta_actual[0] = ruta
            ruta_catalogo.set(str(ruta))
            self.configuracion['CATALOGO'] = str(ruta)
            self.guardar_configuracion()
            contenido_guardado[0] = texto
            estado_catalogo.configure(text='✓ Catálogo guardado correctamente')
            return True

        ttk.Button(herramientas, text='ABRIR CATÁLOGO', command=elegir_archivo).pack(side='left', padx=(0, 8))
        ttk.Button(herramientas, text='GUARDAR CATÁLOGO', command=guardar_catalogo).pack(side='left')

        def generar():
            nombre = titulo.get().strip()
            if not nombre or '|' in nombre or '\n' in nombre or '\r' in nombre:
                messagebox.showwarning('Título inválido', 'Ingresá un título válido, sin barras |.', parent=ventana)
                return
            try:
                id_torrent = self.obtener_id_drive(torrent.get()) if torrent.get().strip() else ''
                id_instrucciones = self.obtener_id_drive(instrucciones.get()) if instrucciones.get().strip() else ''
                id_update = self.obtener_id_drive(update.get()) if update.get().strip() else ''
            except ValueError as error:
                messagebox.showerror('Enlace inválido', str(error), parent=ventana)
                return
            if modo.get() == 'update':
                if not id_update:
                    messagebox.showwarning('Falta update', 'Para «Solo update», pegá el enlace del update.', parent=ventana)
                    return
                lineas = [f'---{nombre}|md|{id_update}']
            else:
                if not id_torrent and not id_instrucciones:
                    messagebox.showwarning('Faltan enlaces', 'Pegá el enlace del torrent o de las instrucciones.', parent=ventana)
                    return
                principal = f'{nombre}|{id_torrent}'
                if id_instrucciones:
                    principal += f'|{id_instrucciones}'
                lineas = [principal]
                if id_update:
                    lineas.append(f'---{nombre}|md|{id_update}')
            texto = '\n'.join(lineas)
            salida.delete('1.0', 'end')
            salida.insert('1.0', texto)
            if modo.get() == 'update':
                lineas_editor = editor.get('1.0', 'end-1c').splitlines(keepends=True)
                coincidencias = [i for i, linea in enumerate(lineas_editor) if not linea.startswith('---') and linea.split('|', 1)[0].strip().casefold() == nombre.casefold()]
                if len(coincidencias) > 1:
                    seleccion = tk.Toplevel(ventana)
                    seleccion.title('Elegir versión del juego')
                    seleccion.geometry('780x340')
                    seleccion.transient(ventana)
                    ttk.Label(seleccion, text='Hay varias entradas con ese título. Elegí debajo de cuál insertar el update:', padding=10).pack(anchor='w')
                    lista = tk.Listbox(seleccion, exportselection=False, font=('Consolas', 10))
                    lista.pack(fill='both', expand=True, padx=10)
                    for i in coincidencias:
                        lista.insert('end', f'Línea {i + 1}: {lineas_editor[i].strip()}')
                    lista.selection_set(0)
                    def elegir():
                        sel = lista.curselection()
                        if sel:
                            insertar_update(coincidencias[sel[0]])
                            seleccion.destroy()
                    ttk.Button(seleccion, text='INSERTAR EN LA SELECCIONADA', command=elegir).pack(pady=10)
                    return
                if len(coincidencias) == 1:
                    insertar_update(coincidencias[0])
                else:
                    estado.configure(text='Juego no encontrado. Resultado generado; podés copiarlo y pegarlo manualmente.')
            else:
                editor.insert('1.0', texto + '\n')
                editor.see('1.0')
                estado.configure(text='Registro insertado al comienzo del editor. Falta guardar el catálogo.')

        def insertar_update(indice):
            lineas = editor.get('1.0', 'end-1c').splitlines(keepends=True)
            posicion = indice + 1
            while posicion < len(lineas) and lineas[posicion].startswith('---'):
                posicion += 1
            if posicion == len(lineas) and lineas and not lineas[-1].endswith('\n'):
                editor.insert('end-1c', '\n')
            editor.insert(f'{posicion + 1}.0', salida.get('1.0', 'end-1c') + '\n')
            editor.see(f'{posicion + 1}.0')
            estado.configure(text='Update insertado debajo del juego elegido. Falta guardar el catálogo.')

        def copiar():
            texto = salida.get('1.0', 'end-1c')
            if not texto:
                messagebox.showwarning('Sin resultado', 'Primero generá un registro.', parent=ventana)
                return
            self.clipboard_clear()
            self.clipboard_append(texto)
            estado.configure(text='Resultado copiado al portapapeles.')

        ttk.Button(botones, text='GENERAR E INSERTAR', command=generar).pack(side='left', padx=(0, 8))
        ttk.Button(botones, text='COPIAR RESULTADO', command=copiar).pack(side='left')

        def cerrar_ventana():
            if editor.get('1.0', 'end-1c') != contenido_guardado[0]:
                respuesta = messagebox.askyesnocancel('Cambios sin guardar', '¿Querés guardar los cambios del catálogo antes de cerrar?', parent=ventana)
                if respuesta is None:
                    return
                if respuesta and not guardar_catalogo():
                    return
            ventana.destroy()
        ventana.protocol('WM_DELETE_WINDOW', cerrar_ventana)
        if ruta_catalogo.get():
            ruta = Path(ruta_catalogo.get())
            if ruta.is_file():
                abrir_archivo(ruta)
            else:
                estado_catalogo.configure(text='No se encontró el catálogo anterior. Elegí ABRIR CATÁLOGO.')
        else:
            estado_catalogo.configure(text='Seleccioná catalogo.txt la primera vez; luego se abrirá automáticamente.')
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

    def abrir_portadas_steamgrid(self):
        """Busca grids verticales con AppID de Steam, sin abrir páginas externas."""
        ventana = tk.Toplevel(self)
        ventana.title('Kalaka’s Soft · Portadas SteamGridDB')
        ventana.geometry('740x610')
        ventana.transient(self)
        barra = ttk.Frame(ventana, padding=10)
        barra.pack(fill='x')
        ttk.Label(barra, text='API Key:').pack(side='left')
        ttk.Entry(barra, textvariable=self.sgdb_key, show='*', width=37).pack(side='left', padx=5)
        ttk.Button(barra, text='Guardar clave', command=self.guardar_configuracion).pack(side='left')
        filtro = ttk.Frame(ventana, padding=(10, 0))
        filtro.pack(fill='x')
        ttk.Label(filtro, text='AppID Steam:').pack(side='left')
        appid = tk.StringVar(value=str(self.steam_appid or ''))
        ttk.Entry(filtro, textvariable=appid, width=16).pack(side='left', padx=6)
        ttk.Label(filtro, text='(Se completa al cargar un juego desde Steam)').pack(side='left')
        estado = tk.StringVar(value='Ingresá la clave una sola vez y buscá portadas.')
        ttk.Label(ventana, textvariable=estado, wraplength=690).pack(fill='x', padx=10, pady=7)
        cuerpo = ttk.Frame(ventana, padding=10)
        cuerpo.pack(fill='both', expand=True)
        listado = tk.Listbox(cuerpo, width=54, exportselection=False)
        listado.pack(side='left', fill='both', expand=True)
        lateral = ttk.Frame(cuerpo, padding=(12, 0))
        lateral.pack(side='left', fill='y')
        preview = ttk.Label(lateral, text='Seleccioná una portada', anchor='center')
        preview.pack(fill='both', expand=True)
        opciones = []
        seleccion = {'index': None, 'image': None, 'url': None}
        ocupado = {'value': False}

        def sgdb_get(path):
            key = self.sgdb_key.get().strip()
            if not key:
                raise ValueError('Primero ingresá tu API Key de SteamGridDB.')
            url = 'https://www.steamgriddb.com/api/v2' + path
            req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key,
                'User-Agent': USER_AGENT, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as response:
                obj = json.load(response)
            if not obj.get('success'):
                raise ValueError('SteamGridDB no devolvió una respuesta válida.')
            return obj.get('data') or []

        def tarea(func, listo):
            if ocupado['value']:
                return
            ocupado['value'] = True
            buscar_btn.configure(state='disabled')
            usar_btn.configure(state='disabled')
            estado.set('Consultando SteamGridDB...')
            def worker():
                try:
                    resultado = func()
                    self.after(0, lambda: terminar(resultado, None))
                except Exception as exc:
                    msg = str(exc)
                    self.after(0, lambda: terminar(None, msg))
            def terminar(resultado, error):
                if not ventana.winfo_exists():
                    return
                ocupado['value'] = False
                buscar_btn.configure(state='normal')
                if error:
                    estado.set('Error: ' + error)
                else:
                    listo(resultado)
            threading.Thread(target=worker, daemon=True).start()

        def buscar():
            numero = appid.get().strip()
            if not numero.isdigit():
                messagebox.showinfo('AppID', 'Primero cargá un juego desde Steam o ingresá su AppID.', parent=ventana)
                return
            def obtener():
                # Grids verticales, preferentemente 600x900; otras dimensiones como respaldo.
                encontrados = sgdb_get('/grids/steam/' + numero + '?dimensions=600x900')
                if not encontrados:
                    encontrados = sgdb_get('/grids/steam/' + numero)
                return [x for x in encontrados if x.get('url') and x.get('width', 0) < x.get('height', 0)][:40]
            def mostrar(items):
                opciones[:] = items
                listado.delete(0, 'end')
                seleccion.update(index=None, image=None, url=None)
                preview.configure(image='', text='Seleccioná una portada')
                preview.image = None
                for i, item in enumerate(items, 1):
                    listado.insert('end', f'{i:02d} · {item.get("width", "?")} × {item.get("height", "?")} · {item.get("style", "Portada")}')
                estado.set(f'{len(items)} portadas verticales encontradas. Elegí una para verla.')
            tarea(obtener, mostrar)

        def ver(event=None):
            if not listado.curselection() or ocupado['value']:
                return
            idx = listado.curselection()[0]
            item = opciones[idx]
            url = item.get('url')
            if not url or not url.startswith('https://'):
                return
            def obtener():
                return fetch_bytes(url)
            def mostrar(data):
                seleccion.update(index=idx, image=data, url=url)
                if Image is not None:
                    import io
                    try:
                        img = Image.open(io.BytesIO(data))
                        img.thumbnail((245, 355))
                        foto = ImageTk.PhotoImage(img)
                        preview.configure(image=foto, text='')
                        preview.image = foto
                    except Exception:
                        preview.configure(image='', text='Vista previa no disponible')
                else:
                    preview.configure(text='Portada lista (Pillow no instalado)')
                usar_btn.configure(state='normal')
                estado.set('Portada descargada para vista previa. Presioná USAR PORTADA.')
            tarea(obtener, mostrar)

        def usar():
            data = seleccion['image']
            if not data:
                return
            url = seleccion['url']
            extension = Path(urllib.parse.urlsplit(url).path).suffix.lower()
            if extension not in FORMATOS:
                extension = '.png'
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension, prefix='kalakas_grid_') as archivo:
                archivo.write(data)
                ruta = Path(archivo.name)
            self._steam_temporales.add(ruta)
            self.portada = ruta
            self.lbl_portada.configure(text='SteamGridDB · ' + (self.nombre_juego.get() or 'Portada'))
            self.miniatura(ruta, self.vista_portada, (180, 190))
            estado.set('¡Portada incorporada! Se guardará al pulsar GUARDAR TODOS.')
            messagebox.showinfo('Portada lista', 'La portada quedó seleccionada en el generador.', parent=ventana)

        botones = ttk.Frame(ventana, padding=10)
        botones.pack(fill='x')
        buscar_btn = ttk.Button(botones, text='BUSCAR PORTADAS', command=buscar)
        buscar_btn.pack(side='left')
        usar_btn = ttk.Button(botones, text='USAR PORTADA', command=usar, state='disabled')
        usar_btn.pack(side='left', padx=10)
        listado.bind('<<ListboxSelect>>', ver)
        if appid.get().isdigit() and self.sgdb_key.get().strip():
            ventana.after(100, buscar)

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
        datos['STEAMGRIDDB_KEY'] = self.sgdb_key.get().strip()
        datos['TORRENTS'] = self.ruta_torrents.get().strip()
        datos['CATALOGO'] = self.configuracion.get('CATALOGO', '')
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
        if nombre.lower().endswith(('.txt', '.md')):
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
                # Instrucciones y updates pueden compartir la misma carpeta de Drive.
                sufijos = {'INSTRUCCIONES': '_inst', 'UPDATES': '_upd'}
                extension = '.md' if seccion in ('INSTRUCCIONES', 'UPDATES') else '.txt'
                archivo_texto = nombre + sufijos.get(seccion, '') + extension
                trabajos.append((carpeta / archivo_texto, contenido, None))
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
        txt = sum(1 for destino, contenido, _ in trabajos if contenido is not None and destino.suffix.lower() == '.txt')
        md = sum(1 for destino, contenido, _ in trabajos if contenido is not None and destino.suffix.lower() == '.md')
        mensaje = f'¡Listo!\n\nTXT: {txt}\nMarkdown (.md): {md}\nPortada: {1 if self.portada else 0}\nCapturas: {len(self.imagenes_capturas)}\nTorrent copiado: {1 if self.archivo_torrent else 0}'
        if carpeta_capturas:
            mensaje += f'\n\nCarpeta de capturas: {carpeta_capturas}'
        self.ultimo_juego_guardado = nombre
        self.limpiar_formulario()
        messagebox.showinfo('Guardado completo', mensaje)
        self.abrir_generador_ids()

    def cerrar(self):
        self.guardar_configuracion()
        for ruta in self._steam_temporales:
            try:
                ruta.unlink(missing_ok=True)
            except OSError:
                pass
        self.destroy()

if __name__ == '__main__':
    Generador().mainloop()
