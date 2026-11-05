# Juegos Torrent 2.6 - Biblioteca remota con bienvenida PC Gaming. No modifica catalogo.ps1.
import re
import random
import os
import math
import tempfile
import json
import hashlib
import time
from urllib.parse import urlparse, quote
import webbrowser
from urllib.error import HTTPError, URLError
import threading
import queue
import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk, font as tkfont

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
except ImportError:
    Image = ImageTk = None  # PNG funciona sin Pillow; JPG requiere Pillow.
from urllib.request import Request, urlopen

CATALOG_ID = '1WP2cyZ3ovEHqs6S18bi49U41EkrG0Uld'
CATALOG_URL = f'https://drive.google.com/uc?export=download&id={CATALOG_ID}'
# Pegá aquí la URL /exec de tu implementación de Google Apps Script.
REPORTES_URL = 'https://script.google.com/macros/s/AKfycbyu29o0sIc8NCqKLThksldrT1k-4glYP9_XCZMBuUzGi-Lf3XbSylMtgNE2HfnW4l4Mqw/exec'
REPORTES_MOTIVOS = (
    'Falta el Torrent / Torrent incorrecto',
    'Torrent sin seeds',
    'Enlace caducado / Enlace incorrecto (update, pack, fix, etc.)',
    'Error al descargar el juego',
    'Archivo dañado / Error al descomprimir',
    'El juego no funciona',
    'Problema con la instalación',
    'Instrucciones incorrectas o incompletas',
    'Otro problema',
)
CATALOG_CACHE_NAME = 'catalogo_cache.txt'
BASE = Path(__file__).resolve().parent
CATALOG_CACHE = BASE / CATALOG_CACHE_NAME
OWNED_FILE = Path(os.environ.get('LOCALAPPDATA', str(BASE))) / 'Juegos Torrents' / 'mis_juegos.json'
LOG_FILE = BASE / 'sincronizacion.log'
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
IMAGES = BASE / 'imagenes'
IMAGES.mkdir(exist_ok=True)
SCREENSHOTS = BASE / 'capturas'
SCREENSHOTS.mkdir(exist_ok=True)
SYNOPSES = BASE / 'sinopsis'
SYNOPSES.mkdir(exist_ok=True)
DATA = BASE / 'datos'
DATA.mkdir(exist_ok=True)
ASSETS = BASE / 'recursos'
LOGOS = (ASSETS / 'logo_joystick.png', ASSETS / 'logo_pc.png')
DOWNLOAD_ICON = ASSETS / 'icono_descarga.png'
INFO_ICONS = ASSETS / 'iconos'
IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp')
DOWNLOADS = Path(os.environ.get('LOCALAPPDATA', str(BASE))) / 'Juegos Torrents' / 'torrents_descargados'
GUIDES = DOWNLOADS / 'fichas'
GUIDES.mkdir(parents=True, exist_ok=True)

BG = '#10151d'
PANEL = '#1b2330'
CARD = '#242f3f'
FG = '#f0f3f8'
MUTED = '#a7b5c8'
ACCENT = '#53d68a'

# Archivo opcional. Hasta configurarlo, el programa funciona 100% como la 1.7.
REMOTE_CONFIG = BASE / 'biblioteca_remota.json'
MAX_MANIFEST_BYTES = 2_000_000
MAX_ASSET_BYTES = 12_000_000



class BarraDesplazamiento(tk.Canvas):
    """Barra vertical oscura y delgada con soporte de arrastre."""
    def __init__(self, parent, command, bg=BG):
        super().__init__(parent, width=11, bg=bg, bd=0, highlightthickness=0, cursor='hand2')
        self.command = command
        self.first, self.last = 0.0, 1.0
        self.drag_origin = None
        self.bind('<Configure>', lambda e: self._paint())
        self.bind('<Button-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<ButtonRelease-1>', lambda e: setattr(self, 'drag_origin', None))

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self._paint()

    def _geometry(self):
        h = max(1, self.winfo_height())
        track = max(1, h - 8)
        span = max(0, min(1, self.last - self.first))
        size = min(track, max(28, track * span))
        travel = max(0, track - size)
        pos = 4 + (self.first / max(0.000001, 1-span)) * travel if travel else 4
        return pos, size, travel, span

    def _paint(self):
        self.delete('all')
        if self.last - self.first >= .999 or self.winfo_height() < 10:
            return
        pos, size, _, _ = self._geometry()
        SelectorElegante._rounded(self, self, 2, pos, 9, pos + size, 3, '#516779')

    def _press(self, event):
        pos, size, travel, span = self._geometry()
        if not (pos <= event.y <= pos + size) and travel:
            fraction = max(0, min(1, (event.y - 4 - size/2) / travel))
            self.command('moveto', fraction * (1-span))
        self.drag_origin = event.y
        self.drag_first = self.first

    def _drag(self, event):
        if self.drag_origin is None:
            return
        _, _, travel, span = self._geometry()
        if travel:
            new_first = self.drag_first + (event.y-self.drag_origin) / travel * (1-span)
            self.command('moveto', max(0, min(1-span, new_first)))


def cargar_icono_ui(nombre, tamano, master):
    """Carga PNG externo y lo ajusta al tamaño indicado; permite reemplazarlo sin editar código."""
    ruta = ASSETS / nombre
    if not ruta.is_file():
        return None
    try:
        if Image is not None and ImageTk is not None:
            with Image.open(ruta) as original:
                icono = original.convert('RGBA')
                icono.thumbnail((tamano, tamano), Image.Resampling.LANCZOS)
                lienzo = Image.new('RGBA', (tamano, tamano), (0, 0, 0, 0))
                lienzo.alpha_composite(icono, ((tamano-icono.width)//2, (tamano-icono.height)//2))
            return ImageTk.PhotoImage(lienzo, master=master)
        # Si Pillow no está instalado, Tk puede cargar PNG, aunque sin reescalado fino.
        return tk.PhotoImage(file=str(ruta), master=master)
    except Exception as exc:
        logging.warning('No se pudo cargar el icono %s: %s', ruta, exc)
        return None


class BotonElegante(tk.Canvas):
    """Botón compacto con iconos PNG suavizados, borde y estados interactivos."""
    def __init__(self, parent, text, command, width=157, height=34, icon=None):
        super().__init__(parent, width=width, height=height, bg=BG,
                         highlightthickness=0, bd=0, cursor='hand2', takefocus=1)
        self.label = text
        self.command = command
        self.icon = icon
        self.icon_images = {}
        if icon:
            self.icon_images["normal"] = cargar_icono_ui(f"icono_{icon}.png", 18, self)
        self.hover = False
        self.pressed = False
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Return>', lambda _: self.command())
        self.bind('<space>', lambda _: self.command())
        self.bind('<Configure>', lambda _: self._paint())
        self._paint()

    def _enter(self, _event):
        self.hover = True
        self._paint()

    def _leave(self, _event):
        self.hover = False
        self.pressed = False
        self._paint()

    def _press(self, _event):
        self.focus_set()
        self.pressed = True
        self._paint()

    def _release(self, event):
        was_pressed = self.pressed
        self.pressed = False
        self._paint()
        if was_pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.command()

    def _draw_icon(self, x, y, color):
        # Imágenes PNG reales, suavizadas a 14 px; Tkinter no dibuja sus curvas.
        image = self.icon_images.get('normal')
        if image is not None:
            self.create_image(round(x), round(y), image=image, anchor='center')

    def _paint(self):
        self.delete('all')
        w = max(self.winfo_width(), int(self.cget('width')))
        h = max(self.winfo_height(), int(self.cget('height')))
        if self.pressed:
            fill, border = '#1C3440', ACCENT
        elif self.hover:
            fill, border = '#304457', ACCENT
        else:
            fill, border = '#29384A', '#50627B'
        SelectorElegante._rounded(self, self, 1, 1, w-1, h-1, 9, border)
        SelectorElegante._rounded(self, self, 2, 2, w-2, h-2, 8, fill)
        font = tkfont.Font(family='Segoe UI', size=9, weight='bold')
        text_width = font.measure(self.label)
        icon_width = 18 if self.icon_images.get('normal') is not None else 0
        gap = 6 if icon_width else 0
        group_width = icon_width + gap + text_width
        start = (w-group_width)/2
        center_y = h/2 + (1 if self.pressed else 0)
        if icon_width:
            self._draw_icon(start+icon_width/2, center_y, '#B9F5CE' if self.hover else '#D4E8FF')
        self.create_text(start+icon_width+gap, center_y, text=self.label,
                         anchor='w', fill=FG, font=font)


class SelectorElegante(tk.Frame):
    """Selector compacto con esquinas redondeadas y menú oscuro (sin temas externos)."""
    def __init__(self, parent, variable, values, width=155, command=None):
        super().__init__(parent, bg=BG, width=width, height=27)
        self.pack_propagate(False)
        self.variable = variable
        self.values = list(values)
        self.command = command
        self.popup = None
        self._hover = False
        self.surface = tk.Canvas(self, width=width, height=27, bg=BG,
                                 highlightthickness=0, bd=0, cursor='hand2')
        self.surface.pack(fill='both', expand=True)
        self.surface.bind('<Configure>', lambda _: self._draw())
        self.surface.bind('<Button-1>', self._toggle)
        self.surface.bind('<Enter>', self._enter)
        self.surface.bind('<Leave>', self._leave)
        self.variable.trace_add('write', lambda *_: self._draw())
        self._draw()

    def _rounded(self, c, x1, y1, x2, y2, radius, color, outline=''):
        points = [x1+radius,y1, x2-radius,y1, x2,y1, x2,y1+radius,
                  x2,y2-radius, x2,y2, x2-radius,y2, x1+radius,y2,
                  x1,y2, x1,y2-radius, x1,y1+radius, x1,y1]
        c.create_polygon(points, smooth=True, splinesteps=12,
                         fill=color, outline=outline)

    def _draw(self):
        c = self.surface
        c.delete('all')
        w = max(c.winfo_width(), int(c.cget('width')))
        h = max(c.winfo_height(), 27)
        self._rounded(c, 1, 1, w-1, h-1, 7, PANEL if self._hover else CARD)
        label = self.variable.get()
        # Recortar con medición real para no invadir la flecha.
        from tkinter import font as tkfont
        font = tkfont.Font(family='Segoe UI', size=9)
        while label and font.measure(label) > w-48:
            label = label[:-1]
        if label != self.variable.get():
            label = label.rstrip() + '…'
        c.create_text(12, h//2, text=label, anchor='w', fill=FG,
                      font=('Segoe UI', 9))
        x, y = w-17, h//2
        c.create_line(x-4, y-2, x, y+2, x+4, y-2, fill=ACCENT,
                      width=2, capstyle='round', joinstyle='round')

    def _enter(self, _event):
        self._hover = True
        self._draw()

    def _leave(self, _event):
        self._hover = False
        self._draw()

    def configure(self, cnf=None, **kwargs):
        if 'values' in kwargs:
            self.values = list(kwargs.pop('values'))
        if cnf is not None or kwargs:
            return super().configure(cnf, **kwargs)

    config = configure

    def _toggle(self, _event=None):
        if self.popup is not None:
            self._close()
            return
        if not self.values:
            return
        popup = tk.Toplevel(self)
        self.popup = popup
        popup.withdraw()
        popup.overrideredirect(True)
        popup.configure(bg=PANEL)
        from tkinter import font as tkfont
        menu_font = tkfont.Font(family='Segoe UI', size=9)
        width = max(self.winfo_width(), max(menu_font.measure(v) for v in self.values) + 38)
        rows = min(len(self.values), 11)
        row_height = 30
        height = rows * row_height + 12
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 4
        if y + height > self.winfo_screenheight():
            y = self.winfo_rooty() - height - 4
        popup.geometry(f'{width}x{height}+{x}+{y}')

        # Menú dibujado, sin el Listbox nativo de Windows.
        menu = tk.Canvas(popup, width=width, height=height, bg=PANEL,
                         highlightthickness=0, bd=0, cursor='hand2')
        menu.pack(fill='both', expand=True)
        selected = self.values.index(self.variable.get()) if self.variable.get() in self.values else 0
        state = {'hover': selected, 'offset': max(0, min(selected - rows + 1, len(self.values) - rows))}

        def paint():
            menu.delete('all')
            w, h = width, height
            self._rounded(menu, 1, 1, w-1, h-1, 9, CARD)
            for row in range(rows):
                index = state['offset'] + row
                if index >= len(self.values):
                    break
                top = 6 + row * row_height
                if index == state['hover']:
                    self._rounded(menu, 5, top, w-5, top+row_height-1,
                                  6, '#344b58')
                if index == selected:
                    menu.create_rectangle(7, top+7, 9, top+row_height-8,
                                          fill=ACCENT, outline='')
                menu.create_text(17, top + row_height//2,
                                 text=self.values[index], anchor='w',
                                 font=('Segoe UI', 9), fill=FG)
            if len(self.values) > rows:
                # Indicador de desplazamiento discreto.
                track_h = rows * row_height - 12
                thumb_h = max(20, track_h * rows / len(self.values))
                thumb_y = 12 + (track_h-thumb_h) * state['offset'] / (len(self.values)-rows)
                self._rounded(menu, w-6, thumb_y, w-3, thumb_y+thumb_h,
                              2, ACCENT)

        def index_at(event):
            row = (event.y - 6) // row_height
            if 0 <= row < rows:
                return state['offset'] + row
            return None

        def hover(event):
            index = index_at(event)
            if index is not None and index < len(self.values) and index != state['hover']:
                state['hover'] = index
                paint()

        def choose(event):
            index = index_at(event)
            if index is not None and index < len(self.values):
                self.variable.set(self.values[index])
                self._close()
                if self.command:
                    self.command()

        def wheel(event):
            if len(self.values) <= rows:
                return 'break'
            direction = -1 if (getattr(event, 'delta', 0) > 0 or getattr(event, 'num', 0) == 4) else 1
            state['offset'] = max(0, min(len(self.values)-rows, state['offset']+direction))
            state['hover'] = max(state['offset'], min(state['hover'], state['offset']+rows-1))
            paint()
            return 'break'

        def key(event):
            if event.keysym == 'Escape':
                self._close()
                return 'break'
            if event.keysym in ('Up', 'Down'):
                step = -1 if event.keysym == 'Up' else 1
                state['hover'] = max(0, min(len(self.values)-1, state['hover']+step))
                if state['hover'] < state['offset']:
                    state['offset'] = state['hover']
                if state['hover'] >= state['offset']+rows:
                    state['offset'] = state['hover']-rows+1
                paint()
                return 'break'
            if event.keysym in ('Return', 'space'):
                self.variable.set(self.values[state['hover']])
                self._close()
                if self.command:
                    self.command()
                return 'break'

        menu.bind('<Motion>', hover)
        menu.bind('<Button-1>', choose)
        menu.bind('<MouseWheel>', wheel)
        menu.bind('<Button-4>', wheel)
        menu.bind('<Button-5>', wheel)
        menu.bind('<KeyPress>', key)
        popup.bind('<FocusOut>', lambda _: self.after(100, self._close_if_unfocused))
        paint()
        popup.deiconify()
        popup.lift()
        menu.focus_set()

    def _close_if_unfocused(self):
        if self.popup is not None:
            try:
                focused = self.popup.focus_get()
                if focused is None or not str(focused).startswith(str(self.popup)):
                    self._close()
            except tk.TclError:
                self._close()

    def _select(self, listbox):
        chosen = listbox.curselection()
        if chosen:
            self.variable.set(self.values[chosen[0]])
            self._close()
            if self.command:
                self.command()
        else:
            self._close()

    def _close(self):
        popup, self.popup = self.popup, None
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass

def read_remote_config():
    try:
        config = json.loads(REMOTE_CONFIG.read_text(encoding='utf-8'))
        url = str(config.get('manifest_url', '')).strip()
        if url.startswith('https://'):
            return url
    except (OSError, ValueError, TypeError):
        pass
    return ''


def validate_remote_manifest(data):
    """Manifiesto v1: rutas relativas, SHA256 y tamaño, sin rutas arbitrarias."""
    if not isinstance(data, dict) or data.get('schema') != 1:
        raise ValueError('Formato de biblioteca remota no compatible.')
    files = data.get('files')
    if not isinstance(files, list) or len(files) > 15000:
        raise ValueError('Lista de archivos de biblioteca inválida.')
    valid = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError('Entrada inválida en el manifiesto.')
        path, digest, size = entry.get('path'), entry.get('sha256'), entry.get('size')
        if not isinstance(path, str) or not isinstance(digest, str) or not isinstance(size, int):
            raise ValueError('Datos incompletos en el manifiesto.')
        parts = Path(path.replace('\\', '/')).parts
        if (not parts or parts[0] not in ('imagenes', 'capturas', 'sinopsis', 'datos')
                or len(parts) < 2 or any(x in ('', '.', '..') for x in parts)
                or ':' in path or '\\' in path or path.startswith('/')
                or not re.fullmatch('[0-9a-f]{64}', digest)
                or not 0 < size <= MAX_ASSET_BYTES):
            raise ValueError('Ruta, hash o tamaño no permitido en el manifiesto.')
        if parts[0] == 'imagenes' and Path(path).suffix.lower() not in IMAGE_EXTS:
            raise ValueError('Extensión de portada inválida.')
        if parts[0] == 'capturas' and Path(path).suffix.lower() not in IMAGE_EXTS:
            raise ValueError('Extensión de captura inválida.')
        if parts[0] in ('sinopsis', 'datos') and Path(path).suffix.lower() != '.txt':
            raise ValueError('Extensión de sinopsis inválida.')
        valid[path] = (digest, size)
    return valid


def fetch_bytes(url, limit):
    request = Request(url, headers={'User-Agent': 'JuegosTorrent/2.0'})
    with urlopen(request, timeout=20) as response:
        if urlparse(response.geturl()).scheme != 'https':
            raise ValueError('Redirección a una dirección insegura.')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('El archivo remoto excede el límite permitido.')
    return raw


def local_asset_matches(destination, expected_hash, expected_size):
    """Valida también los archivos ya guardados; nunca confiar solo en su existencia."""
    try:
        if not destination.is_file() or destination.stat().st_size != expected_size:
            return False
        h = hashlib.sha256()
        with destination.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest() == expected_hash
    except OSError:
        return False


def download_library_asset(base_url, relative, expected_hash, expected_size):
    destination = BASE.joinpath(*relative.split('/'))
    destination.parent.mkdir(parents=True, exist_ok=True)
    if local_asset_matches(destination, expected_hash, expected_size):
        return False
    url = base_url + '/'.join(quote(part, safe='') for part in relative.split('/'))
    # GitHub Raw puede servir temporalmente una versión anterior tras un push.
    # Reintentos con consulta única para evitar reutilizar la respuesta en caché.
    raw = None
    for attempt in range(3):
        unique_url = url + ('&' if '?' in url else '?') + f'jt_refresh={time.time_ns()}_{attempt}'
        raw = fetch_bytes(unique_url, MAX_ASSET_BYTES)
        if len(raw) == expected_size and hashlib.sha256(raw).hexdigest() == expected_hash:
            break
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    else:
        raise ValueError('El archivo remoto no coincide con su hash SHA256 tras 3 intentos; se conserva la copia local.')
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.jt-', delete=False) as f:
        temp = Path(f.name)
        f.write(raw)
    try:
        # Sustitución atómica SOLO después de comprobar el archivo nuevo.
        os.replace(temp, destination)
        return True
    finally:
        temp.unlink(missing_ok=True)



def parse_catalog(raw):
    games = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [x.strip() for x in line.split('|', 3)]
        if len(parts) == 2:
            name, value = parts
            kind, guide = 'torrent', ''
        elif len(parts) == 3:
            name, second, third = parts
            if second.lower() in ('torrent', 'directa', 'pagina', 'txt', 'md'):
                kind, value, guide = second.lower(), third, ''
            else:
                kind, value, guide = 'torrent', second, third
        elif len(parts) == 4:
            name, kind, value, guide = parts
            kind = kind.lower()
        else:
            continue
        if name and value and kind in ('torrent', 'directa', 'pagina', 'txt', 'md'):
            if kind in ('directa', 'pagina') and not value.lower().startswith(('https://', 'http://')):
                continue
            games.append({'name': name, 'type': kind, 'value': value, 'guide': guide})
    return games


def group_catalog(entries):
    """Las entradas con --- se adjuntan al último juego principal."""
    games = []
    for entry in entries:
        if entry['name'].startswith('---'):
            if games:
                extra = entry.copy()
                extra['name'] = entry['name'][3:].strip()
                games[-1]['extras'].append(extra)
            # Si no hay juego principal anterior, se omite el complemento huérfano.
        else:
            game = entry.copy()
            game['extras'] = []
            games.append(game)
    return games


def split_game_title(name):
    """Separa solo los bloques [...] para mostrar un título limpio.

    No modifica el nombre original, que sigue usándose para archivos,
    búsqueda, descargas y sincronización.
    """
    details = [part.strip() for part in re.findall(r'\[([^\[\]]*)\]', name) if part.strip()]
    clean_title = re.sub(r'\s*\[[^\[\]]*\]', '', name).strip()
    return clean_title or name.strip(), ' · '.join(details)


def identify_repacker(game, metadata=None):
    """Detecta solo nombres explícitos en la ficha o en el título del catálogo."""
    metadata = metadata or {}
    explicit = str(metadata.get('repacker', '')).strip()
    # Primero un campo explícito; luego etiquetas del título, sin inferir por el enlace.
    sources = [explicit] if explicit else []
    sources.append(game.get('name', ''))
    # Algunos catálogos identifican al repacker en un complemento.
    sources.extend(extra.get('name', '') for extra in game.get('extras', []))
    patterns = (
        ('FitGirl', r'(?<![\w])fit[ ._-]*girl(?![\w])'),
        ('ElAmigos', r'(?<![\w])el[ ._-]*amigos(?![\w])'),
        ('DODI', r'(?<![\w])dodi(?![\w])'),
        ('KaOs', r'(?<![\w])kaos(?![\w])'),
        ('Rohankar', r'(?<![\w])rohankar(?![\w])'),
    )
    for source in sources:
        for label, pattern in patterns:
            if re.search(pattern, source, flags=re.I):
                return label
    return None


def image_stems(name):
    """Acepta nombre exacto o nombre sin datos entre corchetes."""
    def clean(text):
        return re.sub(r'[\\/:*?"<>|]', '_', text).strip().rstrip(' .')
    exact = clean(name)
    short = clean(re.sub(r'\s*\[[^]]*\]', '', name))
    return list(dict.fromkeys([exact, short]))


def find_cover(name):
    for stem in image_stems(name):
        for ext in IMAGE_EXTS:
            candidate = IMAGES / (stem + ext)
            if candidate.is_file():
                return candidate
    return None


def find_screenshots(name):
    """capturas/NOMBRE DEL JUEGO/01.png, 02.jpg, etc."""
    for stem in image_stems(name):
        folder = SCREENSHOTS / stem
        if folder.is_dir():
            return sorted((p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS and p.is_file()),
                          key=lambda p: p.name.casefold())[:12]
    return []



def find_synopsis(name):
    """Busca un TXT por nombre exacto o sin los datos entre corchetes."""
    for stem in image_stems(name):
        candidate = SYNOPSES / (stem + '.txt')
        if candidate.is_file():
            try:
                return candidate.read_text(encoding='utf-8-sig').strip()
            except (OSError, UnicodeError):
                return ''
    return ''


def find_game_data(name):
    """Datos opcionales por juego; no altera el título del catálogo."""
    for stem in image_stems(name):
        candidate = DATA / (stem + '.txt')
        if candidate.is_file():
            try:
                raw = candidate.read_text(encoding='utf-8-sig')
            except (OSError, UnicodeError):
                return {}
            result = {}
            keys = {'año': 'anio', 'ano': 'anio', 'género': 'genero',
                    'genero': 'genero', 'tamaño': 'tamano', 'tamano': 'tamano',
                    'modo': 'modo', 'idioma': 'idioma',
                    'incorporación': 'incorporacion', 'incorporacion': 'incorporacion',
                    'fecha de incorporación': 'incorporacion', 'fecha de incorporacion': 'incorporacion',
                    'puntuación': 'puntuacion', 'puntuacion': 'puntuacion',
                    'metacritic': 'metacritic',
                    'repacker': 'repacker', 'repack': 'repacker',
                    'repackeador': 'repacker', 'port': 'port', 'crack': 'crack'}
            for line in raw.splitlines():
                key, sep, value = line.partition(':')
                if sep and key.strip().casefold() in keys:
                    normalized = keys[key.strip().casefold()]
                    if value.strip():
                        clean_value = value.strip() if normalized == 'genero' else value.strip()[:80]
                        if normalized == 'idioma':
                            aliases = {'español': 'Español', 'espanol': 'Español',
                                       'ingles': 'Ingles', 'inglés': 'Ingles', 'multi': 'MULTI'}
                            clean_value = aliases.get(clean_value.casefold(), '')
                        if clean_value:
                            result[normalized] = clean_value
            return result
    return {}



def game_score(data):
    """Devuelve una nota de 0 a 10, o None si no hay nota válida.

    Puntuación/Puntuacion tiene prioridad. Metacritic (0-100) es respaldo.
    """
    for field, divisor in (('puntuacion', 1), ('metacritic', 10)):
        raw = str(data.get(field, '')).strip().replace(',', '.')
        if not raw:
            continue
        try:
            value = float(raw) / divisor
        except ValueError:
            continue
        if 0 <= value <= 10:
            return round(value, 1)
    return None


def score_color(score):
    if score >= 9:
        return '#188c50'
    if score >= 8:
        return '#277d51'
    if score >= 7:
        return '#b39728'
    if score >= 6:
        return '#b96a2e'
    return '#b43d43'


def is_hypervisor(data):
    """Detecta el indicador Crack: Hypervisor sin importar mayúsculas."""
    return 'hypervisor' in str(data.get('crack', '')).casefold()


def draw_hypervisor_badge(picture):
    """Sello H rojo sobre la esquina superior derecha de la carátula."""
    draw = ImageDraw.Draw(picture)
    size = max(18, min(33, round(picture.width * 0.23)))
    margin = max(3, round(size * .13))
    x1, y1 = picture.width - size - margin, margin
    x2, y2 = picture.width - margin, margin + size
    draw.rounded_rectangle((x1, y1, x2, y2), radius=max(4, size//5),
                           fill='#c4141e', outline='#fff4f4', width=2)
    try:
        font = ImageFont.truetype('arialbd.ttf', round(size * .76))
    except OSError:
        try:
            font = ImageFont.truetype('DejaVuSans-Bold.ttf', round(size * .73))
        except OSError:
            font = ImageFont.load_default()
    bounds = draw.textbbox((0, 0), 'H', font=font)
    tx = (x1+x2-(bounds[2]-bounds[0]))/2-bounds[0]
    ty = (y1+y2-(bounds[3]-bounds[1]))/2-bounds[1]
    draw.text((tx, ty), 'H', font=font, fill='white')


def load_scored_cover(path, score, max_width, max_height, master=None, owned=False, hypervisor=False):
    """Compone la puntuación en la miniatura, evitando widgets superpuestos que parpadean."""
    if not path or Image is None or ImageTk is None:
        return load_local_image(path, max_width, max_height, master=master)
    try:
        with Image.open(path) as source:
            picture = source.convert('RGBA')
        picture.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        if score is not None:
            draw = ImageDraw.Draw(picture)
            try:
                font = ImageFont.truetype('arialbd.ttf', 14)
            except OSError:
                try:
                    font = ImageFont.truetype('DejaVuSans-Bold.ttf', 13)
                except OSError:
                    font = ImageFont.load_default()
            # Dibujamos la estrella como geometría: funciona incluso si la fuente
            # de Windows no incluye el carácter Unicode ★.
            label = f'{score:.1f}'
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad_x, pad_y, margin = 6, 4, 4
            star_size, gap = 14, 4
            width = tw + 2 * pad_x + star_size + gap
            height = max(th, star_size) + 2 * pad_y
            right, bottom = picture.size[0] - margin, picture.size[1] - margin
            left, top = right - width, bottom - height
            draw.rounded_rectangle((left, top, right, bottom), radius=4,
                                   fill=score_color(score), outline='#15202a', width=1)
            cx = left + pad_x + star_size / 2
            cy = top + height / 2
            points = []
            for i in range(10):
                angle = math.radians(-90 + i * 36)
                radius = star_size / 2 if i % 2 == 0 else star_size / 4.3
                points.append((cx + radius * math.cos(angle),
                               cy + radius * math.sin(angle)))
            draw.polygon(points, fill='#ffe18b')
            text_left = left + pad_x + star_size + gap
            text_top = top + (height - th) / 2
            draw.text((text_left - bbox[0], text_top - bbox[1]),
                      label, font=font, fill='white')
        if owned:
            draw = ImageDraw.Draw(picture)
            draw.rounded_rectangle((4, 4, 23, 23), radius=5,
                                   fill='#176b46', outline='#8df0b5', width=1)
            draw.line([(8, 14), (12, 18), (19, 9)], fill='white', width=2, joint='curve')
        if hypervisor:
            draw_hypervisor_badge(picture)
        return ImageTk.PhotoImage(picture, master=master)
    except Exception:
        return load_local_image(path, max_width, max_height, master=master)


def load_local_image(path, max_width, max_height, master=None):
    if not path:
        return None
    try:
        if Image is not None:
            with Image.open(path) as original:
                picture = original.copy()
            picture.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(picture, master=master)
        if path.suffix.lower() != '.png':
            return None
        picture = tk.PhotoImage(file=str(path), master=master)
        factor = max(1, (picture.width() + max_width - 1) // max_width,
                     (picture.height() + max_height - 1) // max_height)
        return picture.subsample(factor, factor)
    except (OSError, ValueError, tk.TclError):
        return None


def safe_filename(name):
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip().rstrip(' .') or 'archivo'


def is_html_file(path):
    with open(path, 'rb') as f:
        head = f.read(512).decode('utf-8-sig', errors='replace').lstrip().lower()
    return head.startswith(('<!doctype html', '<html', '<head', '<body'))


def drive_url(file_id):
    from urllib.parse import urlencode
    return 'https://drive.google.com/uc?' + urlencode({'export': 'download', 'id': file_id})


def download_file(url, destination, on_progress):
    """Descarga a archivo temporal y publica solo después de verificarlo."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix='juegos_', suffix='.part', dir=destination.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(request, timeout=35) as response:
                total = int(response.headers.get('Content-Length') or 0)
                downloaded = 0
                while True:
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    temp.write(chunk)
                    downloaded += len(chunk)
                    on_progress(downloaded, total)
        if not temp_path.stat().st_size:
            raise ValueError('El servidor devolvió un archivo vacío.')
        if is_html_file(temp_path):
            raise ValueError('El servidor devolvió una página HTML en lugar del archivo.')
        if destination.suffix.lower() == '.torrent':
            with open(temp_path, 'rb') as f:
                if f.read(1) != b'd':
                    raise ValueError('El archivo descargado no parece un torrent válido.')
        os.replace(temp_path, destination)
        temp_path = None
        return destination
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _number_size_gb(raw):
    """Convierte tamaños de texto como '55,4 GB', '900 MB' o '1.2 TB'."""
    match = re.search(r'(\d+(?:[.,]\d+)?)\s*(TB|GB|MB|KB|GIB|MIB|TIB)\b', raw, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(',', '.'))
    unit = match.group(2).upper()
    return value * {'TB': 1024, 'TIB': 1024, 'GB': 1, 'GIB': 1,
                    'MB': 1/1024, 'MIB': 1/1024, 'KB': 1/1048576}[unit]


def _year(raw):
    match = re.search(r'\b(?:19|20)\d{2}\b', raw)
    return int(match.group()) if match else None


def _date(raw):
    """Acepta YYYY-MM-DD y DD/MM/YYYY."""
    from datetime import datetime
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(raw.strip(), fmt).date().toordinal()
        except ValueError:
            pass
    return None


def _genres(raw):
    return [part.strip() for part in re.split(r'[,;/|]+', raw) if part.strip()]



PORT_FILTERS = {f'PS{n} Port': f'PS{n}' for n in range(1, 6)}

def centered_popup(window, width, desired_height=1100):
    screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
    height = min(desired_height, max(480, screen_h - 75))
    width = min(width, max(600, screen_w - 40))
    x, y = max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 2)
    window.geometry(f'{width}x{height}+{x}+{y}')

def is_markdown_text(text):
    return bool(re.search(r'^\s*#{1,6}\s+|\*\*[^*\n]+\*\*', text, re.M))

def render_markdown(widget, value, font_size=11):
    widget.configure(state='normal')
    widget.delete('1.0', 'end')
    widget.tag_configure('bold', font=('Segoe UI', font_size, 'bold'))
    widget.tag_configure('italic', font=('Segoe UI', font_size, 'italic'))
    widget.tag_configure('bolditalic', font=('Segoe UI', font_size, 'bold italic'))
    widget.tag_configure('underline', underline=True)
    widget.tag_configure('code', font=('Consolas', max(9, font_size-1)),
                              background='#eef1f3', foreground='#263a4b')
    widget.tag_configure('link', foreground='#1266ae', underline=True)
    widget.tag_configure('heading', font=('Segoe UI', 16, 'bold'),
                              foreground='#16643e', spacing1=12, spacing3=9)
    widget.tag_configure('subheading', font=('Segoe UI', 13, 'bold'),
                              foreground='#16643e', spacing1=9, spacing3=6)
    widget.tag_configure('rule', foreground='#a4b1ad')
    if True:
        # Renderizar Markdown habitual sin dependencias externas.
        inline = re.compile(
            r'(\[([^\]]+)\]\((https?://[^)]+)\)'  # enlaces
            r'|<u>.*?</u>'                         # subrayado
            r'|\*\*\*.+?\*\*\*'              # negrita+cursiva
            r'|\*\*.+?\*\*|__.+?__'              # negrita
            r'|(?<!\*)\*[^*\n]+?\*(?!\*)'       # cursiva
            r'|(?<!_)_[^_\n]+?_(?!_)'             # cursiva
            r'|`[^`\n]+`)', re.I)
        for line in value.splitlines(keepends=True):
            # Dos espacios al final significan salto de línea en Markdown.
            line = line.rstrip(' ') if not line.endswith('\n') else line.rstrip(' \n') + '\n'
            stripped = line.strip()
            if re.fullmatch(r'(?:-{3,}|\*{3,}|_{3,})', stripped):
                widget.insert('end', '────────────────────────\n', ('rule',))
                continue
            heading = re.match(r'^\s*(#{1,6})\s+(.*)', line)
            if heading:
                level = len(heading.group(1))
                line = heading.group(2)
                if not line.endswith('\n'):
                    line += '\n'
                heading_tag = 'heading' if level == 1 else 'subheading'
            else:
                heading_tag = None
                bullet = re.match(r'^(\s*)[-*+]\s+(.*)', line)
                ordered = re.match(r'^(\s*)(\d+)\.\s+(.*)', line)
                if bullet:
                    line = bullet.group(1) + '• ' + bullet.group(2)
                elif ordered:
                    line = ordered.group(1) + ordered.group(2) + '. ' + ordered.group(3)
            pos = 0
            for match in inline.finditer(line):
                if match.start() > pos:
                    widget.insert('end', line[pos:match.start()],
                                       (heading_tag,) if heading_tag else ())
                token = match.group(0)
                if match.group(2) is not None:
                    widget.insert('end', match.group(2), ('link',))
                elif token.lower().startswith('<u>'):
                    widget.insert('end', token[3:-4], ('underline',))
                elif token.startswith('***'):
                    widget.insert('end', token[3:-3], ('bolditalic',))
                elif token.startswith('**') or token.startswith('__'):
                    widget.insert('end', token[2:-2], ('bold',))
                elif token.startswith('`'):
                    widget.insert('end', token[1:-1], ('code',))
                else:
                    widget.insert('end', token[1:-1], ('italic',))
                pos = match.end()
            if pos < len(line):
                widget.insert('end', line[pos:],
                                   (heading_tag,) if heading_tag else ())

    widget.configure(state='disabled')
    widget.yview_moveto(0)

class BarraProgresoVerde(tk.Canvas):
    """Indicador de progreso verde, independiente del tema de Windows."""
    def __init__(self, master):
        super().__init__(master, height=16, bg='#273342',
                         bd=0, highlightthickness=0)
        self.porcentaje = 0.0
        self.bind('<Configure>', lambda event: self._dibujar())

    def __setitem__(self, key, value):
        if key == 'value':
            self.porcentaje = max(0.0, min(100.0, float(value)))
            self._dibujar()
        else:
            super().__setitem__(key, value)

    def _dibujar(self):
        self.delete('progreso')
        ancho = self.winfo_width()
        alto = self.winfo_height()
        if ancho > 1 and alto > 1 and self.porcentaje > 0:
            self.create_rectangle(0, 0, ancho * self.porcentaje / 100, alto,
                                  fill='#62e69a', outline='', tags='progreso')


class PestañasModernas(tk.Frame):
    """Pestañas planas sin bordes nativos; conserva add/select del Notebook."""
    def __init__(self, master):
        super().__init__(master, bg=PANEL)
        self.nav = tk.Frame(self, bg=PANEL, height=43)
        self.nav.pack(fill='x')
        self.nav.pack_propagate(False)
        self.content = tk.Frame(self, bg=PANEL)
        self.content.pack(fill='both', expand=True)
        self.pages = []
        self.active = None

    def add(self, page, text):
        item = tk.Frame(self.nav, bg=PANEL, cursor='hand2')
        item.pack(side='left', padx=(5, 23), fill='y')
        label = tk.Label(item, text=text.upper(), bg=PANEL, fg=MUTED,
                         font=('Segoe UI', 10, 'bold'), cursor='hand2')
        label.pack(padx=5, pady=(8, 7))
        underline = tk.Frame(item, bg=PANEL, height=3)
        underline.pack(fill='x')
        for widget in (item, label, underline):
            widget.bind('<Button-1>', lambda event, p=page: self.select(p))
        self.pages.append((page, label, underline))
        if self.active is None:
            self.select(page)

    def select(self, page=None):
        if page is None:
            return str(self.active) if self.active else ''
        if page is self.active:
            return
        if self.active is not None:
            self.active.pack_forget()
        self.active = page
        page.pack(in_=self.content, fill='both', expand=True)
        for candidate, label, underline in self.pages:
            selected = candidate is page
            label.config(fg=ACCENT if selected else MUTED)
            underline.config(bg=ACCENT if selected else PANEL)


class BotonDescargaModerno(tk.Canvas):
    """Botón redondeado con la interfaz config/invoke usada por la app."""
    def __init__(self, master, command, text='Descargar juego'):
        super().__init__(master, bg=PANEL, height=54, highlightthickness=0,
                         bd=0, cursor='hand2')
        self.command = command
        self.caption = text
        self.button_state = 'normal'
        self.hover = False
        self.bind('<Configure>', lambda _: self._draw())
        self.bind('<Enter>', lambda _: self._hover(True))
        self.bind('<Leave>', lambda _: self._hover(False))
        self.bind('<Button-1>', lambda _: self.invoke())
        self._draw()

    def _hover(self, value):
        self.hover = value
        self._draw()

    def config(self, cnf=None, **kwargs):
        if 'text' in kwargs:
            self.caption = kwargs.pop('text')
        if 'state' in kwargs:
            self.button_state = kwargs.pop('state')
        if cnf is not None or kwargs:
            super().config(cnf, **kwargs)
        self.configure(cursor='arrow' if self.button_state == 'disabled' else 'hand2')
        self._draw()

    configure_button = config

    def invoke(self):
        if self.button_state != 'disabled':
            self.command()

    def _draw(self):
        self.delete('all')
        w, h = max(1, self.winfo_width()), max(1, self.winfo_height())
        disabled = self.button_state == 'disabled'
        fill = '#303c46' if disabled else '#246a4c' if self.hover else '#20583f'
        edge = '#46545e' if disabled else '#60d79a' if self.hover else '#398c65'
        SelectorElegante._rounded(self, self, 2, 2, w-2, h-2, 12, fill, edge)
        self.create_text(w/2, h/2, text='↓   ' + self.caption.upper(),
                         fill='#96a3ae' if disabled else '#e9fff2',
                         font=('Segoe UI', 11, 'bold'))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Juegos Torrent 2.7.64')
        self.withdraw()  # La biblioteca se muestra al terminar la carga inicial.
        self._initial_splash = True
        self._startup_split_job = None
        self._startup_split_done = False
        self.bind('<Map>', self._on_window_mapped, add='+')
        self.geometry('1280x800')
        # Biblioteca oculta hasta terminar el splash.
        self.minsize(760, 500)
        self.configure(bg=BG)
        self.remote_manifest = {}
        self.remote_base_url = ''
        self.remote_pending = set()
        self.remote_lock = threading.Lock()
        self.asset_events = queue.Queue()
        self.sync_batches = {}
        self.sync_batch_serial = 0
        self.sync_hide_job = None
        self.cover_cards = {}
        self.card_widgets = {}  # Tarjetas reutilizables: no destruir al cambiar columnas.
        self.card_parts = {}
        self.hovered_card = None
        self.hypervisor_tip = None
        self.hypervisor_tip_job = None
        self.hypervisor_tip_widget = None
        self.cover_photo_cache = {}  # Miniaturas compuestas reutilizadas por archivo/estado.
        self.resize_layout_job = None
        self.visible_game_names = []
        self.owned_games = self.load_owned_games()
        self.after(120, self.process_asset_events)
        self.games = []
        self.catalog_loading = True
        self.catalog_error = False
        self.images = []
        self.screenshot_images = []
        self.current_shots = []
        self.gallery_layout = None
        self.gallery_resize_job = None
        self.selected = None
        self.synopsis_full = ''
        self.synopsis_expanded = False
        self.busy = False
        self.text_request = 0
        self.search = tk.StringVar()
        self.genre_filter = tk.StringVar(value='Todos los géneros')
        self.sort_mode = tk.StringVar(value='Recientes')
        self.game_metadata = {}
        # Evita reconstruir cientos de tarjetas por cada tecla pulsada.
        self.search_render_job = None
        self.search.trace_add('write', lambda *_: self.schedule_search_render())

        top = tk.Frame(self, bg=BG)
        top.pack(fill='x', padx=22, pady=(18, 12))
        # Elige uno de los dos logos UNA sola vez al iniciar el programa.
        # Los archivos se mantienen externos para no modificar el código al cambiarlos.
        self.header_logo = None
        logo_path = random.choice(LOGOS)
        if logo_path.is_file() and Image is not None:
            self.header_logo = load_local_image(logo_path, 420, 140, master=self)
        if self.header_logo is not None:
            tk.Label(top, image=self.header_logo, bg=BG, bd=0).pack(side='left')
        else:
            tk.Label(top, text='Juegos Torrent', fg=ACCENT, bg=BG,
                     font=('Segoe UI', 24, 'bold')).pack(side='left')
        BotonElegante(top, 'Actualizar catálogo', self.load_catalog,
                      width=180, height=34, icon='refresh').pack(side='right')
        BotonElegante(top, 'Guías', self.open_help_center,
                      width=112, height=34, icon='book').pack(side='right', padx=(0, 10))
        # Buscador con contorno redondeado, a juego con los selectores.
        search_area = tk.Frame(top, bg=BG, width=290, height=30)
        search_area.pack(side='right', padx=12)
        search_area.pack_propagate(False)
        search_bg = tk.Canvas(search_area, width=290, height=30, bg=BG,
                              highlightthickness=0, bd=0)
        search_bg.place(x=0, y=0, relwidth=1, relheight=1)

        def paint_search(_event=None):
            search_bg.delete('all')
            w = max(290, search_bg.winfo_width())
            h = max(30, search_bg.winfo_height())
            SelectorElegante._rounded(self, search_bg, 1, 1, w-1, h-1,
                                      8, PANEL)
            if self.icono_busqueda is not None:
                search_bg.create_image(20, h/2, image=self.icono_busqueda, anchor='center')
            else:
                search_bg.create_oval(15, 10, 22, 17, outline=ACCENT, width=1.5)
                search_bg.create_line(21, 17, 25, 21, fill=ACCENT,
                                      width=1.5, capstyle='round')

        self.icono_busqueda = cargar_icono_ui('icono_buscar.png', 18, self)
        search_bg.bind('<Configure>', paint_search)
        paint_search()
        searchbox = tk.Entry(search_area, textvariable=self.search,
                             font=('Segoe UI', 10), bg=PANEL, fg=FG,
                             insertbackground=FG, relief='flat', bd=0,
                             highlightthickness=0)
        searchbox.place(x=34, rely=0.5, anchor='w', relwidth=1, width=-73, height=21)
        clear_search = tk.Label(search_area, text='✕', fg=MUTED, bg=PANEL,
                                font=('Segoe UI', 10, 'bold'), cursor='hand2')
        clear_search.place(relx=1, x=-17, rely=0.5, anchor='center')
        clear_search.bind('<Button-1>', lambda _: (self.search.set(''), searchbox.focus_set()))
        clear_search.bind('<Enter>', lambda _: clear_search.config(fg=ACCENT))
        clear_search.bind('<Leave>', lambda _: clear_search.config(fg=MUTED))
        clear_search.place_forget()
        self.search.trace_add('write', lambda *_: clear_search.place(relx=1, x=-17, rely=0.5, anchor='center')
                              if self.search.get() else clear_search.place_forget())
        hint = tk.Label(search_area, text='Buscar juegos...', fg=MUTED, bg=PANEL,
                        font=('Segoe UI', 10), cursor='xterm')
        hint.place(x=36, rely=0.5, anchor='w')
        hint.bind('<Button-1>', lambda _: searchbox.focus_set())
        search_bg.bind('<Button-1>', lambda _: searchbox.focus_set())
        self.search.trace_add('write', lambda *_: hint.place_forget() if self.search.get()
                              else hint.place(x=36, rely=0.5, anchor='w'))

        body = tk.PanedWindow(self, orient='horizontal', bg=BG, sashwidth=6, bd=0)
        body.pack(fill='both', expand=True, padx=18, pady=(0, 10))
        left = tk.Frame(body, bg=BG)
        right = tk.Frame(body, bg=PANEL, width=680)
        body.add(left, stretch='always', minsize=360)
        body.add(right, minsize=490)
        # Conservar el panel de ficha en un ancho estable durante el arranque.
        # La geometría real se conoce al mapear la ventana, no tras 350 ms fijos.
        self.main_paned = body
        self.after_idle(self._schedule_startup_split)

        # Selectores compactos personalizados: bordes suaves y menú oscuro.
        filters = tk.Frame(left, bg=BG, height=34)
        # La cabecera no ocupa todo el ancho del panel: termina exactamente
        # donde termina la última tarjeta de la primera fila.
        filters.pack(anchor='w', padx=(9, 0), pady=(0, 9))
        filters.pack_propagate(False)
        self.filters = filters
        filters.configure(width=860)
        self.genre_display = tk.StringVar(value='Todos los géneros')
        self.sort_display = tk.StringVar(value='Recientes')
        sort_options = ['Nombre (A-Z)', 'Nombre (Z-A)', 'Año (más recientes)',
                        'Año (más antiguos)', 'Recientes',
                        'Antiguos', 'Tamaño (mayor)', 'Tamaño (menor)',
                         'Mejor puntuación', 'En Colección',
                        'PS1 Port', 'PS2 Port', 'PS3 Port', 'PS4 Port', 'PS5 Port']
        self.sort_combo = SelectorElegante(filters, self.sort_display, sort_options,
                                           width=155, command=self.on_sort_selected)
        self.sort_combo.pack(side='right')
        self.genre_combo = SelectorElegante(filters, self.genre_display,
                                            ['Todos los géneros'], width=151,
                                            command=self.on_genre_selected)
        self.genre_combo.pack(side='right', padx=(0, 9))

        self.canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        bar = BarraDesplazamiento(left, command=self.canvas.yview, bg=BG)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.grid_frame = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor='nw')
        self.grid_frame.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', self.on_resize)
        self.canvas.bind_all('<MouseWheel>', self.on_mousewheel)
        self.last_columns = 0

        # Ficha desplazable para que quepan todos los complementos.
        detail_canvas = tk.Canvas(right, bg=PANEL, highlightthickness=0)
        detail_scroll = BarraDesplazamiento(right, command=detail_canvas.yview, bg=PANEL)
        detail_canvas.configure(yscrollcommand=detail_scroll.set)
        detail_scroll.pack(side='right', fill='y')
        detail_canvas.pack(side='left', fill='both', expand=True)
        detail_frame = tk.Frame(detail_canvas, bg=PANEL)
        detail_window = detail_canvas.create_window((0, 0), window=detail_frame, anchor='nw')
        detail_frame.bind('<Configure>', lambda _: detail_canvas.configure(scrollregion=detail_canvas.bbox('all')))
        detail_canvas.bind('<Configure>', lambda event: detail_canvas.itemconfigure(detail_window, width=event.width))
        self.detail_canvas = detail_canvas
        # Bienvenida 2.5: flyer completo, con tipografia y logo integrados.
        # La ficha del juego no se altera: la bienvenida se oculta al seleccionar.
        self.welcome = tk.Frame(right, bg=PANEL, bd=0)
        self.welcome_photo = None
        self.welcome_banner_original = None
        # Elegir al azar una bienvenida por inicio (no cambia durante la sesión).
        # Acepta bienvenida_flyer.png, bienvenida_flyer_2.png, _3.png, etc.
        welcome_candidates = sorted(
            path for path in ASSETS.glob('bienvenida_flyer*.png') if path.is_file()
        )
        self.welcome_png_path = (random.choice(welcome_candidates)
                                 if welcome_candidates else ASSETS / 'bienvenida_flyer.png')
        if Image is not None and ImageTk is not None and self.welcome_png_path.is_file():
            try:
                self.welcome_banner_original = Image.open(self.welcome_png_path).convert('RGB')
            except (OSError, ValueError):
                logging.exception('No se pudo cargar el flyer de bienvenida')
        self.welcome_hero = tk.Canvas(self.welcome, bg=PANEL, bd=0, highlightthickness=0)
        self.welcome_hero.pack(fill='both', expand=True)
        self.welcome_hero.bind('<Configure>', self.redraw_welcome_hero)
        self.welcome.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.welcome.lift()

        # Encabezado integrado: dibujado en Canvas, sin imagen externa.
        # Conserva la identidad verde solo como acento sobre azul grafito.
        self.ficha_header = tk.Canvas(detail_frame, bg=CARD, height=57,
                                      highlightthickness=0, bd=0)
        self.ficha_header.pack(fill='x', padx=0, pady=(0, 15))
        self.ficha_header.bind('<Configure>', self.redraw_ficha_header)
        self.current_repacker = None
        self.detail_title = tk.Label(detail_frame, text='', fg=FG, bg=PANEL,
                                     wraplength=630, justify='center', font=('Segoe UI', 16, 'bold'))
        self.detail_title.pack(fill='x', padx=18, pady=(0, 6))
        self.detail_type = tk.Label(detail_frame, text='', fg=MUTED, bg=PANEL,
                                    wraplength=630, justify='center', font=('Segoe UI', 10))
        self.detail_type.pack(anchor='center', padx=18, pady=(0, 12))

        # Insignias horizontales: integradas al Canvas de la cabecera.
        # No ocupan espacio del título ni del subtítulo.
        self.repacker_badge_photos = {}
        for repacker_name, filename in (
                ('FitGirl', 'fitgirl_banner.png'),
                ('ElAmigos', 'elamigos_banner.png'),
                ('DODI', 'dodi_banner.png'),
                ('KaOs', 'kaos_banner.png'),
                ('Rohankar', 'rohankar_banner.png')):
            badge_path = ASSETS / filename
            if Image is not None and ImageTk is not None and badge_path.is_file():
                try:
                    with Image.open(badge_path) as badge_img:
                        badge_img = badge_img.convert('RGBA')
                        badge_img = badge_img.resize((125, 52), Image.Resampling.LANCZOS)
                        self.repacker_badge_photos[repacker_name] = ImageTk.PhotoImage(
                            badge_img, master=self)
                except (OSError, ValueError):
                    logging.exception('No se pudo cargar la insignia %s', repacker_name)
        self.repacker_tooltip = None
        self.repacker_tooltip_job = None
        self.ficha_header.bind('<Motion>', self.on_header_badge_motion)
        self.ficha_header.bind('<Leave>', self.hide_repacker_tooltip)

        # Una sola fila: carátula a la izquierda, capturas a la derecha.
        # Este contenedor permanece en el mismo lugar aunque cambiemos de juego.
        self.media_row = tk.Frame(detail_frame, bg=PANEL)
        self.media_row.pack(fill='x', padx=18, pady=(0, 12))
        self.cover_area = tk.Frame(self.media_row, bg=PANEL, width=235, height=320)
        self.cover_area.pack(side='left', anchor='n', padx=(0, 14))
        self.cover_area.pack_propagate(False)
        self.detail_cover = tk.Label(self.cover_area, text='Seleccioná una carátula',
                                     fg=MUTED, bg=CARD, font=('Segoe UI', 11), cursor='hand2')
        self.detail_cover.pack(pady=(0, 0))
        self.detail_cover.bind('<Button-1>', lambda _: self.open_cover_preview())
        self.detail_cover.bind('<Enter>', lambda event: self.schedule_hypervisor_tip(event.widget, self.selected['name'] if self.selected else None))
        self.detail_cover.bind('<Leave>', self.hide_hypervisor_tip)
        self.screenshots_column = tk.Frame(self.media_row, bg=PANEL)
        self.screenshots_column.pack(side='left', fill='both', expand=True, anchor='n')
        self.screenshots_title = tk.Label(self.screenshots_column, text='', fg=ACCENT, bg=PANEL,
                                          font=('Segoe UI', 11, 'bold'))
        # Sin encabezado: las miniaturas se identifican visualmente.
        self.screenshots_frame = tk.Frame(self.screenshots_column, bg=PANEL)
        self.screenshots_frame.pack(fill='x')
        self.screenshots_column.bind('<Configure>', self.on_gallery_resize)
        self.screenshots_column.bind('<Configure>',
            lambda event: self.synopsis_label.config(wraplength=max(230, event.width - 12)), add='+')
        # Barra opcional de datos rápidos, debajo de las capturas.
        self.info_bar = tk.Frame(detail_frame, bg=CARD, padx=10, pady=7)
        self.info_icons = {}
        self.info_values = {}
        for key, icon, fallback in (
                ('anio', 'anio.png', 'Año'),
                ('genero', 'genero.png', 'Género'),
                ('tamano', 'tamano.png', 'Tamaño'),
                ('modo', 'modo.png', 'Modo'),
                ('idioma', 'idioma.png', 'Idioma')):
            slot = tk.Frame(self.info_bar, bg=CARD)
            slot.pack(side='left', padx=(0, 12))
            path = INFO_ICONS / icon
            photo = load_local_image(path, 20, 20, master=self) if path.is_file() else None
            self.info_icons[key] = photo
            tk.Label(slot, image=photo, text='' if photo else fallback,
                     compound='left', fg=MUTED, bg=CARD,
                     font=('Segoe UI', 9)).pack(side='left', padx=(0, 5))
            label = tk.Label(slot, text='', fg=FG, bg=CARD,
                             font=('Segoe UI', 9, 'bold'))
            label.pack(side='left')
            self.info_values[key] = (slot, label)

        # Botón de colección dibujado en Canvas para tener esquinas redondeadas.
        self.owned_button = tk.Canvas(self.info_bar, width=156, height=38,
                                      bg=CARD, bd=0, highlightthickness=0,
                                      cursor='hand2')
        self.owned_button.pack(side='right', padx=(8, 0))
        self.owned_button.bind('<Enter>', lambda _: self._hover_owned_button(True))
        self.owned_button.bind('<Leave>', lambda _: self._hover_owned_button(False))
        self.owned_button.bind('<Button-1>', lambda _: self.toggle_owned_selected())

        # Sinopsis justo debajo de las capturas, dentro de la columna derecha.
        # La barra de información permanece debajo de toda la fila multimedia.
        self.synopsis_area = tk.Frame(self.screenshots_column, bg=PANEL)
        self.synopsis_heading = tk.Label(self.synopsis_area, text='SINOPSIS', fg=ACCENT,
                                         bg=PANEL, font=('Segoe UI', 11, 'bold'))
        # Se omite el encabezado SINOPSIS para aprovechar el espacio.
        self.synopsis_label = tk.Label(self.synopsis_area, text='', fg=FG, bg=PANEL,
                                       justify='left', anchor='nw', font=('Segoe UI', 10),
                                       wraplength=610)
        self.synopsis_label.pack(fill='x', anchor='w')
        self.synopsis_button = tk.Button(self.synopsis_area, text='Leer más',
                                         command=self.toggle_synopsis, fg=ACCENT, bg=PANEL,
                                         activeforeground=FG, activebackground=PANEL,
                                         relief='flat', bd=0, cursor='hand2',
                                         font=('Segoe UI', 10, 'underline'))
        detail_canvas.bind('<Configure>', self.on_detail_resize, add='+')

        # Navegación plana propia: sin contorno blanco ni pestañas clásicas.
        tabs = PestañasModernas(detail_frame)
        tabs.pack(fill='both', expand=True, padx=12, pady=(12, 16))
        self.tabs = tabs
        self.downloads_tab = tk.Frame(tabs.content, bg=PANEL)
        self.instructions_tab = tk.Frame(tabs.content, bg=PANEL)
        tabs.add(self.downloads_tab, text='Descargas')
        tabs.add(self.instructions_tab, text='Instrucciones / enlaces')
        tabs.bind('<MouseWheel>', self.scroll_over_tabs)

        # Acción principal redondeada, sin el aspecto de botón nativo.
        self.download_icon_photo = None
        self.download_button = BotonDescargaModerno(
            self.downloads_tab, command=self.download_selected)
        self.download_button.pack(fill='x', padx=8, pady=(10, 12))
        self.guide_button = tk.Button(detail_frame, text='Ver instrucciones  →',
                                      command=self.open_selected_guide, bg=CARD, fg=FG,
                                      activebackground='#303d50', activeforeground=FG,
                                      relief='flat', padx=14, pady=7, cursor='hand2',
                                      font=('Segoe UI', 10, 'bold'))
        self.guide_button.place_forget()
        self.report_button = tk.Button(
            self.downloads_tab, text='🚩  Reportar problema',
            command=self.open_report_dialog, state='disabled',
            bg=CARD, fg='#ffcf91', activebackground='#34445a',
            activeforeground='#ffffff', relief='flat', bd=0,
            cursor='hand2', font=('Segoe UI', 10, 'bold'), padx=14, pady=9)
        self.report_button.pack(anchor='e', padx=8, pady=(0, 6))
        self.extras_title = tk.Label(self.downloads_tab, text='', fg=ACCENT, bg=PANEL,
                                     font=('Segoe UI', 12, 'bold'))
        self.extras_title.pack(anchor='w', padx=8, pady=(12, 4))
        self.extras_frame = tk.Frame(self.downloads_tab, bg=PANEL)
        self.extras_frame.pack(fill='x', padx=8, pady=(0, 20))

        self.text_heading = tk.Label(self.instructions_tab, text='Seleccioná un juego y sus instrucciones.',
                                     fg=ACCENT, bg=PANEL, anchor='w', justify='left',
                                     font=('Segoe UI', 11, 'bold'))
        self.text_heading.pack(fill='x', padx=8, pady=(12, 8))
        # El encabezado ocupa siempre una sola línea; el visor conserva el título completo.
        self._full_text_heading = 'Seleccioná un juego y sus instrucciones.'
        self.instructions_tab.bind('<Configure>', self._fit_text_heading, add='+')

        text_container = tk.Frame(self.instructions_tab, bg=PANEL)
        text_container.pack(fill='both', expand=True, padx=8, pady=(0, 10))
        self.text_view = tk.Text(text_container, wrap='word', height=15, bg=BG, fg=FG,
                                 insertbackground=FG, relief='flat', padx=10, pady=10,
                                 font=('Segoe UI', 11), spacing1=3, spacing3=4, state='disabled')
        text_scroll = ttk.Scrollbar(text_container, orient='vertical', command=self.text_view.yview)
        self.text_view.configure(yscrollcommand=text_scroll.set)
        text_scroll.pack(side='right', fill='y')
        self.text_view.pack(side='left', fill='both', expand=True)
        text_actions = tk.Frame(self.instructions_tab, bg=PANEL)
        text_actions.pack(fill='x', padx=8, pady=(0, 10))
        tk.Button(text_actions, text='VER EN GRANDE  ↗', command=self.open_text_viewer,
                  bg=ACCENT, fg=BG, activebackground='#7de9a7',
                  activeforeground=BG, relief='flat', bd=0, cursor='hand2',
                  font=('Segoe UI', 10, 'bold'), pady=9).pack(
                      side='left', fill='x', expand=True, padx=(0, 5))
        tk.Button(text_actions, text='COPIAR TEXTO', command=self.copy_text,
                  bg=CARD, fg=FG, activebackground='#34445a',
                  activeforeground=FG, relief='flat', bd=0, cursor='hand2',
                  font=('Segoe UI', 10, 'bold'), pady=9).pack(
                      side='left', fill='x', expand=True, padx=(5, 0))

        # Barra inferior persistente: estado a la izquierda, créditos discretos a la derecha.
        status_bar = tk.Frame(self, bg=BG)
        status_bar.pack(fill='x', padx=22, pady=(0, 12))
        self.status = tk.Label(status_bar, text='Preparando biblioteca...', bg=BG, fg=MUTED,
                               anchor='w', font=('Segoe UI', 10))
        self.status.pack(side='left', fill='x', expand=True)
        # Indicador independiente: no interfiere con los mensajes de la barra de estado.
        self.sync_box = tk.Frame(self, bg=BG)
        self.sync_text = tk.Label(self.sync_box, bg=BG, fg=ACCENT,
                                  font=('Segoe UI', 9), anchor='w')
        self.sync_text.pack(fill='x')
        # Canvas propio: el verde se ve igual en Windows con cualquier tema.
        self.sync_progress = BarraProgresoVerde(self.sync_box)
        self.sync_progress.pack(fill='x', pady=(3, 0))
        # Se muestra únicamente cuando hay archivos pendientes.
        tk.Label(status_bar, text='MaelstromxXx & ChatGPT', bg=BG, fg='#728296',
                 anchor='e', font=('Segoe UI', 8)).pack(side='right', padx=(12, 0))
        # Splash integrado: cubre la ventana completa mientras se prepara el catálogo.
        self._build_startup_splash()
        # Dejar que Tk dibuje el splash ANTES de iniciar tareas de red.
        self.after(120, self._start_initial_loading)

    def _start_initial_loading(self):
        self.load_catalog()
        self.load_remote_manifest()

    def _build_startup_splash(self):
        """Ventana de bienvenida independiente, centrada y con imagen aleatoria."""
        self.splash = tk.Toplevel(self)
        self.splash.title("Kalaka's Soft | Juegos Torrent")
        self.splash.configure(bg='#0c1118')
        self.splash.resizable(False, False)
        self.splash.overrideredirect(True)
        self.splash.attributes('-topmost', True)
        self._splash_started_at = __import__('time').monotonic()
        width, height = 850, 565
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2)
        self.splash.geometry(f'{width}x{height}+{x}+{y}')
        self.splash_canvas = tk.Canvas(self.splash, width=width, height=height,
                                       bg='#0c1118', highlightthickness=0)
        self.splash_canvas.pack(fill='both', expand=True)
        self.splash_photo = None
        self.splash_source = None
        # Buscar todas las opciones disponibles, sin excluir nombres por número.
        # Para las ilustraciones antiguas 1 y 2, utilizar las versiones limpias
        # (sin barra estática) cuando estén presentes.
        choices = []
        for path in sorted(ASSETS.glob('splash_opcion_*.png')):
            suffix = path.stem.removeprefix('splash_opcion_')
            clean_version = ASSETS / f'splash_fondo_limpio_{suffix}.png'
            choices.append(clean_version if clean_version.is_file() else path)
        # También reconocer imágenes limpias si no existe su splash_opcion_N.
        for clean_version in sorted(ASSETS.glob('splash_fondo_limpio_*.png')):
            suffix = clean_version.stem.removeprefix('splash_fondo_limpio_')
            if not (ASSETS / f'splash_opcion_{suffix}.png').is_file():
                choices.append(clean_version)
        if not choices and (ASSETS / 'splash_juegos_torrent.png').is_file():
            choices = [ASSETS / 'splash_juegos_torrent.png']
        if choices and Image is not None and ImageTk is not None:
            try:
                chosen = random.choice(choices)
                with Image.open(chosen) as picture:
                    original = picture.convert('RGB')
                self.splash_source = original
                # UNA imagen de fondo, sin cortar, pegar ni duplicar franjas.
                clean = original.resize((width, height), Image.Resampling.LANCZOS)
                self.splash_photo = ImageTk.PhotoImage(clean, master=self.splash)
            except Exception:
                logging.exception('No se pudo abrir el splash')
        self.splash_message = 'Conectando con Servidor...'
        self._splash_progress = 8
        self._splash_target = 24
        self._splash_job = None
        self._redraw_splash()
        self.splash.lift()
        self.splash.update_idletasks()
        self._animate_splash()

    def _redraw_splash(self):
        if not getattr(self, 'splash', None) or not self.splash.winfo_exists():
            return
        canvas = self.splash_canvas
        canvas.delete('all')
        w, h = 850, 565
        if self.splash_photo:
            canvas.create_image(0, 0, image=self.splash_photo, anchor='nw')
        else:
            canvas.create_text(w//2, h//2-65, text="KALAKA'S SOFT",
                               fill=ACCENT, font=('Segoe UI', 25, 'bold'))
            canvas.create_text(w//2, h//2-15, text='JUEGOS TORRENT',
                               fill=FG, font=('Segoe UI', 35, 'bold'))
        # Texto y barra transparentes: se dibujan sobre la imagen, sin panel opaco.
        canvas.create_text(w//2, 369, text=self.splash_message,
                           fill='#f0f3f8', font=('Segoe UI', 12, 'bold'))
        x1, x2, y1, y2 = 160, w-160, 392, 407
        # Dibujar cada cápsula como UNA línea con extremos ROUND.
        # Evita uniones irregulares entre óvalos y rectángulos.
        cy = (y1 + y2) / 2
        radius = (y2 - y1) / 2
        left_center, right_center = x1 + radius, x2 - radius
        canvas.create_line(left_center, cy, right_center, cy,
                           fill='#438d69', width=15, capstyle=tk.ROUND)
        canvas.create_line(left_center, cy, right_center, cy,
                           fill='#25323b', width=13, capstyle=tk.ROUND)
        progress = max(0, min(100, self._splash_progress)) / 100
        if progress > 0:
            # El relleno también es un solo trazo, sin piezas superpuestas.
            fill_left = x1 + 5
            fill_right = x2 - 5
            length = (fill_right - fill_left) * progress
            fill_radius = 4.5
            start = fill_left + fill_radius
            end = max(start, fill_left + length - fill_radius)
            canvas.create_line(start, cy, end, cy,
                               fill='#4cdb8d', width=9, capstyle=tk.ROUND)
        canvas.create_text(w//2, 423, text=f'{int(self._splash_progress)}%',
                           fill='#9eddb8', font=('Segoe UI', 9, 'bold'))

    def _animate_splash(self):
        self._splash_job = None
        if not getattr(self, 'splash', None) or not self.splash.winfo_exists():
            return
        if self._splash_progress < self._splash_target:
            self._splash_progress = min(self._splash_target, self._splash_progress + 1)
            self._redraw_splash()
        self._splash_job = self.after(75, self._animate_splash)

    def show_catalog_loading(self):
        """Al refrescar, usar estado de la biblioteca sin taparla con un splash."""
        if self._initial_splash and self.splash.winfo_exists():
            self.splash_message = 'Conectando con Servidor...'
            self._splash_target = max(self._splash_target, 35)
            self._redraw_splash()

    def hide_catalog_loading(self):
        """Abrir la biblioteca maximizada cuando terminó de crear las tarjetas."""
        if self._initial_splash:
            self._initial_splash = False
            if self._splash_job is not None:
                self.after_cancel(self._splash_job)
                self._splash_job = None
            if self.splash.winfo_exists():
                self.splash.destroy()
            self.deiconify()
            try:
                self.state('zoomed')
            except tk.TclError:
                pass
            self.after_idle(self._schedule_startup_split)

    def _on_window_mapped(self, event):
        """El HWND de Windows ya existe al recibir Map."""
        if event.widget is not self:
            return
        self._schedule_startup_split()

    def _schedule_startup_split(self):
        if self._startup_split_done or not hasattr(self, 'main_paned'):
            return
        if self._startup_split_job is not None:
            self.after_cancel(self._startup_split_job)
        self._startup_split_job = self.after(160, self._set_startup_split)

    def _set_startup_split(self):
        """Fijar el divisor cuando la ventana ya tiene dimensiones utilizables."""
        self._startup_split_job = None
        if self._startup_split_done:
            return
        body = self.main_paned
        width = body.winfo_width()
        if width < 860 or not body.winfo_ismapped():
            self._schedule_startup_split()
            return
        # Preferir cinco columnas a la izquierda si entra; respetar la ficha.
        min_left, min_right, sash = 360, 490, 6
        left_width = min(950, width - min_right - sash)
        left_width = max(min_left, left_width)
        try:
            body.sash_place(0, left_width, 1)
            # Segunda pasada: algunos widgets todavía solicitan tamaño en
            # el primer ciclo de geometría y pueden desplazar el divisor.
            self.after(220, self._verify_startup_split)
        except tk.TclError:
            self._schedule_startup_split()

    def _verify_startup_split(self):
        if self._startup_split_done:
            return
        body = self.main_paned
        width = body.winfo_width()
        if width < 860 or not body.winfo_ismapped():
            self._schedule_startup_split()
            return
        target = max(360, min(950, width - 490 - 6))
        try:
            current = body.sash_coord(0)[0]
            if abs(current - target) > 12:
                body.sash_place(0, target, 1)
        except tk.TclError:
            pass
        self._startup_split_done = True

    def redraw_ficha_header(self, event=None):
        """Cabecera azul grafito adaptable, sin escalado de archivos externos."""
        canvas = self.ficha_header
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 2 or height < 2:
            return
        canvas.delete('all')

        # Degradado horizontal azul grafito -> petróleo apagado.
        left, right = (36, 47, 63), (26, 49, 62)
        bands = min(100, max(1, width // 5))
        for i in range(bands):
            t = i / max(1, bands - 1)
            rgb = tuple(round(c1 + (c2 - c1) * t) for c1, c2 in zip(left, right))
            color = '#{:02x}{:02x}{:02x}'.format(*rgb)
            x1 = round(width * i / bands)
            x2 = round(width * (i + 1) / bands) + 1
            canvas.create_rectangle(x1, 0, x2, height, fill=color, outline=color)

        # Marca lateral, título y filete inferior de acento.
        canvas.create_rectangle(0, 11, 3, height - 12, fill=ACCENT, outline='')
        canvas.create_text(20, height // 2, text='FICHA DEL JUEGO', anchor='w',
                           fill=FG, font=('Segoe UI', 13, 'bold'))
        canvas.create_line(0, height - 1, width, height - 1,
                           fill='#365b59', width=1)
        canvas.create_line(0, height - 1, min(100, width), height - 1,
                           fill=ACCENT, width=2)

        # Insignia rectangular alineada a la derecha, dentro del encabezado.
        repacker = getattr(self, 'current_repacker', None)
        badge_photo = self.repacker_badge_photos.get(repacker)
        if badge_photo is not None and width >= 355:
            canvas.create_image(width - 12, height // 2, image=badge_photo,
                                anchor='e', tags=('repacker_banner',))
        if repacker and width >= 355 and badge_photo is None:
            colors = {
                'FitGirl': ('#294c4b', '#8de0c5'),
                'ElAmigos': ('#344d69', '#a9d1ff'),
                'DODI': ('#55415f', '#e3baf7'),
                'KaOs': ('#61483d', '#ffd2a8'),
                'Rohankar': ('#28435c', '#c4e8ff'),
            }
            fill, foreground = colors[repacker]
            x1, x2 = width - 136, width - 14
            SelectorElegante._rounded(canvas, canvas, x1, 13, x2, height - 13,
                                      9, fill)
            canvas.create_text((x1+x2)/2, height/2, text=repacker,
                               fill=foreground, font=('Segoe UI', 10, 'bold'))

    def redraw_welcome_hero(self, event=None):
        """Muestra el flyer completo, sin recortar logo, letras ni boton."""
        width = self.welcome_hero.winfo_width()
        height = self.welcome_hero.winfo_height()
        if width < 2 or height < 2:
            return
        self.welcome_hero.delete('all')
        if self.welcome_banner_original is not None and ImageTk is not None:
            original = self.welcome_banner_original
            scale = min(width / original.width, height / original.height)
            nw, nh = max(1, round(original.width * scale)), max(1, round(original.height * scale))
            resized = original.resize((nw, nh), Image.Resampling.LANCZOS)
            self.welcome_photo = ImageTk.PhotoImage(resized, master=self)
        else:
            # Fallback sin Pillow: Tkinter puede abrir PNG de forma nativa.
            try:
                if not hasattr(self, '_welcome_png_original'):
                    self._welcome_png_original = tk.PhotoImage(file=str(self.welcome_png_path))
                original = self._welcome_png_original
                factor = max(1, (original.width() + width - 1) // width,
                             (original.height() + height - 1) // height)
                self.welcome_photo = original.subsample(factor)
            except tk.TclError:
                logging.exception('No se pudo cargar el flyer PNG de bienvenida')
                return
        self.welcome_hero.create_image(width // 2, height // 2,
                                       image=self.welcome_photo, anchor='center')

    def scroll_over_tabs(self, event):
        self.detail_canvas.yview_scroll(-1 * int(event.delta / 120), 'units')
        return 'break'  # Evita que el control Notebook interprete la rueda.

    def on_mousewheel(self, event):
        hovered = self.winfo_containing(event.x_root, event.y_root)
        widget = hovered
        while widget is not None:
            if widget is self.canvas or widget is self.grid_frame:
                self.canvas.yview_scroll(-1 * int(event.delta / 120), 'units')
                return
            if widget is self.detail_canvas:
                self.detail_canvas.yview_scroll(-1 * int(event.delta / 120), 'units')
                return
            widget = getattr(widget, 'master', None)

    def on_resize(self, event):
        # Cambiar el ancho del canvas es barato; no reconstruir las tarjetas.
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        columns = min(5, max(1, (event.width - 16) // 172))
        if columns != self.last_columns:
            self.last_columns = columns
            if self.resize_layout_job is not None:
                self.after_cancel(self.resize_layout_job)
            # Agrupar eventos de arrastre/maximizar/restaurar.
            self.resize_layout_job = self.after(90, self.relayout_cards)
        else:
            self.after_idle(self.alinear_filtros_con_caratulas)

    def relayout_cards(self):
        """Reubica las tarjetas existentes sin reabrir carátulas ni crear widgets."""
        self.resize_layout_job = None
        cols = max(1, self.last_columns or 3)
        for i, name in enumerate(self.visible_game_names):
            card = self.card_widgets.get(name)
            if card is not None:
                card.grid_configure(row=i // cols, column=i % cols)
        self.after_idle(self.alinear_filtros_con_caratulas)

    def cached_card_photo(self, name):
        """Caché por ruta, fecha de modificación, puntuación y marca personal."""
        path = find_cover(name)
        if path is None:
            return None
        try:
            stamp = (path.stat().st_mtime_ns, path.stat().st_size)
        except OSError:
            return None
        score = game_score(self.game_metadata.get(name, {}))
        hypervisor = is_hypervisor(self.game_metadata.get(name, {}))
        key = (str(path), stamp, score, name in self.owned_games, hypervisor)
        photo = self.cover_photo_cache.get(key)
        if photo is None:
            photo = load_scored_cover(path, score, 140, 185, master=self,
                                      owned=name in self.owned_games, hypervisor=hypervisor)
            if photo is not None:
                self.cover_photo_cache[key] = photo
        return photo

    def update_card_cover(self, name):
        label = self.cover_cards.get(name)
        if label is None:
            return
        photo = self.cached_card_photo(name)
        label.config(image=photo if photo is not None else '',
                     text='' if photo else ('✓ DESCARGADO\nSIN CARÁTULA' if name in self.owned_games else 'SIN\nCARÁTULA'),
                     width=0 if photo else 17, height=0 if photo else 10)
        label.image = photo

    def load_remote_manifest(self):
        manifest_url = read_remote_config()
        if not manifest_url:
            return  # Sin URL configurada: se mantienen los recursos locales.

        def worker():
            try:
                separator = '&' if '?' in manifest_url else '?'
                fresh_url = f'{manifest_url}{separator}jt_refresh={time.time_ns()}'
                raw = fetch_bytes(fresh_url, MAX_MANIFEST_BYTES)
                logging.info('Manifiesto SHA256 recibido: %s', hashlib.sha256(raw).hexdigest())
                manifest = validate_remote_manifest(json.loads(raw.decode('utf-8-sig')))
                base_url = manifest_url.rsplit('/', 1)[0] + '/'
                self.after(0, lambda: self.remote_manifest_loaded(manifest, base_url))
            except Exception as exc:
                logging.exception('No se pudo consultar el manifiesto remoto')
                msg = str(exc)
                self.after(0, lambda: self.status.config(text='Biblioteca remota no disponible; usando archivos locales. ' + msg[:100]))
        threading.Thread(target=worker, daemon=True).start()

    def remote_manifest_loaded(self, manifest, base_url):
        self.remote_manifest = manifest
        self.remote_base_url = base_url
        logging.info('Manifiesto remoto cargado: %s archivos', len(manifest))
        self.schedule_remote_assets()

    def schedule_remote_assets(self, selected_only=False):
        if not self.remote_manifest or not self.games:
            return
        names = ([self.selected['name']] if self.selected else []) if selected_only else [g['name'] for g in self.games]
        manifest = dict(self.remote_manifest)
        base_url = self.remote_base_url
        # La comparación SHA256 local corre fuera del hilo de Tkinter.
        threading.Thread(target=self._scan_remote_assets,
                         args=(names, manifest, base_url), daemon=True).start()

    def _scan_remote_assets(self, names, manifest, base_url):
        index = {}
        for path in manifest:
            index.setdefault(path.casefold(), []).append(path)
        wanted = []
        for name in names:
            stems = image_stems(name)
            for category in ('imagenes', 'capturas', 'sinopsis', 'datos'):
                for stem in stems:
                    prefix = f'{category}/{stem}'
                    if category == 'capturas':
                        matches = [p for p in manifest
                                   if p.casefold().startswith((prefix + '/').casefold())]
                        matches.sort(key=lambda p: p.casefold())
                    elif category in ('sinopsis', 'datos'):
                        matches = index.get((prefix + '.txt').casefold(), [])
                    else:
                        matches = [p for ext in IMAGE_EXTS
                                   for p in index.get((prefix + ext).casefold(), [])]
                    if matches:
                        for relative in matches[:12] if category == 'capturas' else matches[:1]:
                            digest, size = manifest[relative]
                            destination = BASE.joinpath(*relative.split('/'))
                            if not local_asset_matches(destination, digest, size):
                                wanted.append(relative)
                        break
        with self.remote_lock:
            new = [p for p in dict.fromkeys(wanted) if p not in self.remote_pending]
            self.remote_pending.update(new)
        if new:
            logging.info('Archivos nuevos o modificados: %s', ', '.join(new))
            with self.remote_lock:
                self.sync_batch_serial += 1
                batch_id = self.sync_batch_serial
            self.asset_events.put(('sync_start', batch_id, len(new)))
            self.download_remote_batch(new, manifest, base_url, batch_id)

    def download_remote_batch(self, paths, manifest=None, base_url=None, batch_id=None):
        manifest = manifest if manifest is not None else dict(self.remote_manifest)
        base_url = base_url if base_url is not None else self.remote_base_url
        try:
            for relative in paths:
                success = False
                try:
                    digest, size = manifest[relative]
                    downloaded = download_library_asset(base_url, relative, digest, size)
                    success = bool(downloaded)
                    if downloaded:
                        logging.info('Actualizado/descargado: %s', relative)
                        # Avisar a la interfaz por cada archivo, no al terminar todo el lote.
                        # Queue evita invocar Tkinter desde los hilos de descarga.
                        self.asset_events.put(relative)
                except Exception:
                    logging.exception('No se pudo actualizar %s; se conserva el archivo local', relative)
                finally:
                    if batch_id is not None:
                        self.asset_events.put(('sync_step', batch_id, success))
        finally:
            with self.remote_lock:
                self.remote_pending.difference_update(paths)
            if batch_id is not None:
                self.asset_events.put(('sync_end', batch_id))

    def _hide_sync_indicator(self):
        self.sync_hide_job = None
        if not self.sync_batches:
            self.sync_box.pack_forget()

    def _update_sync_indicator(self):
        if self.sync_hide_job is not None:
            self.after_cancel(self.sync_hide_job)
            self.sync_hide_job = None
        if not self.sync_box.winfo_manager():
            # Debajo de la barra de estado; sin alterar el diseño de las tarjetas.
            self.sync_box.pack(fill='x', padx=22, pady=(0, 8))
        if self.sync_batches:
            total = sum(b['total'] for b in self.sync_batches.values())
            done = sum(b['done'] for b in self.sync_batches.values())
            errors = sum(b['errors'] for b in self.sync_batches.values())
            pct = 100 * done / max(total, 1)
            self.sync_text.config(text=f'🔄 Actualizando biblioteca: {done} de {total} archivos ({pct:.1f} %)' +
                                       (f' · {errors} errores' if errors else ''))
            self.sync_progress['value'] = pct
        else:
            self.sync_progress['value'] = 100
            self.sync_text.config(text='✓ Biblioteca actualizada' if not getattr(self, '_sync_last_errors', 0)
                                  else f'⚠ Sincronización terminada: {self._sync_last_errors} archivos con errores')
            self.sync_hide_job = self.after(5000, self._hide_sync_indicator)

    def process_asset_events(self):
        """Procesa descargas y avance en el hilo Tk, sin bloquear la interfaz."""
        changed = set()
        progress_changed = False
        try:
            while True:
                event = self.asset_events.get_nowait()
                if isinstance(event, tuple):
                    kind = event[0]
                    batch_id = event[1]
                    value = event[2] if len(event) > 2 else None
                    if kind == 'sync_start':
                        self.sync_batches[batch_id] = {'total': value, 'done': 0, 'errors': 0}
                        progress_changed = True
                    elif kind == 'sync_step':
                        batch = self.sync_batches.get(batch_id)
                        if batch is not None:
                            batch['done'] += 1
                            if not value:
                                batch['errors'] += 1
                            progress_changed = True
                    elif kind == 'sync_end':
                        batch = self.sync_batches.pop(batch_id, None)
                        if batch is not None:
                            self._sync_last_errors = batch['errors']
                        progress_changed = True
                else:
                    changed.add(event)
        except queue.Empty:
            pass
        if progress_changed:
            self._update_sync_indicator()
        if changed:
            try:
                self.refresh_remote_assets(changed)
            except Exception:
                logging.exception('No se pudo refrescar la interfaz tras sincronizar')
        self.after(120, self.process_asset_events)

    def refresh_remote_assets(self, changed=None):
        """Actualiza solamente tarjetas y ficha afectadas por los archivos recibidos."""
        if changed is None:
            changed = set()
        cover_paths = [p for p in changed if p.startswith('imagenes/')]
        if cover_paths:
            for game_name in list(self.cover_cards):
                if any(Path(p).stem in image_stems(game_name) for p in cover_paths):
                    # Evita usar una miniatura antigua incluso si el sistema conserva timestamps.
                    stems = set(image_stems(game_name))
                    self.cover_photo_cache = {k: v for k, v in self.cover_photo_cache.items()
                                              if Path(k[0]).stem not in stems}
                    self.update_card_cover(game_name)
        if any(p.startswith('datos/') and p.lower().endswith('.txt') for p in changed):
            self.render_games()
            for game_name in list(self.cover_cards):
                if any(p.startswith('datos/') and Path(p).stem in image_stems(game_name) for p in changed):
                    self.update_card_cover(game_name)
        if self.selected:
            game = self.selected
            stems = set(image_stems(game['name']))
            if any(p.startswith('imagenes/') and Path(p).stem in stems for p in changed):
                photo = self.load_cover(game['name'], 225, 315)
                self.detail_cover.config(image=photo if photo is not None else '',
                                         text='' if photo else 'SIN CARÁTULA')
                self.detail_cover.image = photo
            if any(p.startswith('capturas/') and len(Path(p).parts) > 2
                   and Path(p).parts[1] in stems for p in changed):
                self.render_screenshots(game)
            if any(p.startswith('datos/') and Path(p).stem in stems for p in changed):
                photo = self.load_cover(game['name'], 225, 315)
                self.detail_cover.config(image=photo if photo is not None else '',
                                         text='' if photo else 'SIN CARÁTULA')
                self.detail_cover.image = photo
                self.show_game_data(game)
            if any(p.startswith('sinopsis/') and Path(p).stem in stems for p in changed):
                self.show_synopsis(game)

    def load_catalog(self):
        self.catalog_loading = True
        self.catalog_error = False
        self.show_catalog_loading()
        self.status.config(text='Consultando catálogo remoto de Google Drive...')
        if not self.games:
            self.render_games()

        def work():
            try:
                request = Request(CATALOG_URL, headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(request, timeout=18) as response:
                    content = response.read(5_000_001)
                if len(content) > 5_000_000:
                    raise ValueError('El catálogo supera el tamaño máximo permitido.')
                raw = content.decode('utf-8-sig')
                if re.search(r'<html|<!doctype', raw, re.I):
                    raise ValueError('Google Drive devolvió una página HTML en lugar del texto.')
                games = parse_catalog(raw)
                if not games:
                    raise ValueError('El catálogo no contiene entradas válidas.')
                # Primero validamos el TXT. Luego guardamos una copia atómica para
                # que una descarga incompleta no destruya la última versión útil.
                try:
                    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                            dir=BASE, prefix='.catalogo-', suffix='.tmp',
                            delete=False) as stream:
                        temporary = Path(stream.name)
                        stream.write(raw)
                    try:
                        temporary.replace(CATALOG_CACHE)
                    finally:
                        temporary.unlink(missing_ok=True)
                except OSError:
                    # Si el directorio no es escribible, seguimos usando el catálogo
                    # online. El siguiente arranque sin red necesitará una caché previa.
                    pass
                self.after(0, lambda: self.catalog_loaded(games, offline=False))
            except Exception as exc:
                remote_error = str(exc)
                try:
                    raw = CATALOG_CACHE.read_text(encoding='utf-8-sig')
                    games = parse_catalog(raw)
                    if not games:
                        raise ValueError('La copia local está vacía o no es válida.')
                    self.after(0, lambda: self.catalog_loaded(games, offline=True))
                except (OSError, UnicodeError, ValueError) as cache_exc:
                    message = (f'No se pudo consultar Google Drive: {remote_error}\n\n'
                               f'Tampoco hay un catálogo local válido: {cache_exc}\n\n'
                               'Conectate a Internet al menos una vez para guardar la primera copia.')
                    self.after(0, lambda: self.catalog_failed(message))

        threading.Thread(target=work, daemon=True).start()

    def catalog_loaded(self, games, offline=False):
        if hasattr(self, 'splash'):
            self.splash_message = 'Preparando carátulas y biblioteca...'
            self._splash_target = 90
            self._redraw_splash()
        self.catalog_loading = False
        self.catalog_error = False
        self.games = group_catalog(games)
        # El catálogo remoto puede cambiar: recrear tarjetas solo al actualizarlo.
        for card in self.card_widgets.values():
            card.destroy()
        self.card_widgets.clear()
        self.card_parts.clear()
        self.hovered_card = None
        self.cover_photo_cache.clear()
        self.cover_cards.clear()
        self.visible_game_names = []
        self.selected = None
        self.hide_repacker_tooltip()
        self.current_repacker = None
        self.redraw_ficha_header()
        self.download_button.config(state='disabled')
        self.report_button.config(state='disabled')
        self.guide_button.place_forget()
        self.show_text('Seleccioná un juego', 'Las instrucciones aparecerán aquí cuando las solicites.')
        summary = f'{len(self.games)} juegos y {len(games) - len(self.games)} complementos.'
        if offline:
            self.status.config(text='SIN CONEXIÓN · Catálogo local cargado: ' + summary)
        else:
            self.status.config(text='Catálogo actualizado desde Google Drive: ' + summary)
        self.render_games()
        self.schedule_remote_assets()
        # Mostrar la biblioteca únicamente cuando se crearon las tarjetas.
        if self._initial_splash:
            self._splash_progress = 100
            self._redraw_splash()
            elapsed_ms = int((__import__('time').monotonic() - self._splash_started_at) * 1000)
            self.after(max(250, 1800 - elapsed_ms), self.hide_catalog_loading)
        else:
            self.after_idle(self.hide_catalog_loading)

    def catalog_failed(self, msg):
        self.hide_catalog_loading()
        self.catalog_loading = False
        self.catalog_error = True
        if not self.games:
            self.render_games()
        self.status.config(text='No se pudo cargar el catálogo. Probá con «Actualizar catálogo».')
        messagebox.showerror('JUEGOS - Error de conexión', msg)

    def load_cover(self, name, max_width, max_height):
        return load_scored_cover(find_cover(name), None, max_width, max_height, master=self,
                                 hypervisor=is_hypervisor(find_game_data(name)))

    def open_cover_preview(self):
        if self.selected:
            path = find_cover(self.selected['name'])
            if path:
                self.preview_image(path)

    def preview_image(self, path):
        """Ventana aparte para ver la imagen sin alterar la ficha."""
        window = tk.Toplevel(self)
        window.title(path.name)
        window.configure(bg=BG)
        window.geometry('850x610')
        image = load_local_image(path, 800, 540, master=window)
        if image:
            label = tk.Label(window, image=image, bg=BG)
            label.image = image
            label.pack(fill='both', expand=True, padx=12, pady=12)
        else:
            tk.Label(window, text='No se pudo abrir la imagen. Para JPG/WebP instalá Pillow.',
                     bg=BG, fg=FG, wraplength=600).pack(expand=True)
        tk.Button(window, text='Cerrar', command=window.destroy, bg=CARD, fg=FG,
                  relief='flat', pady=8).pack(fill='x', padx=18, pady=(0, 12))

    def open_screenshot_gallery(self, paths, start_index=0):
        """Galería independiente; no modifica las miniaturas ni la ficha."""
        paths = list(paths)
        if not paths:
            return
        window = tk.Toplevel(self)
        window.title('Galería de capturas - Juegos Torrent')
        window.configure(bg=BG)
        window.geometry('1050x740')
        window.minsize(460, 330)
        window.transient(self)

        state = {'index': start_index % len(paths), 'photo': None, 'job': None}
        header = tk.Frame(window, bg=BG)
        header.pack(fill='x', padx=18, pady=(12, 4))
        title = tk.Label(header, text=self.selected['name'] if self.selected else 'Capturas',
                         fg=FG, bg=BG, font=('Segoe UI', 12, 'bold'), anchor='w')
        title.pack(side='left', fill='x', expand=True)
        counter = tk.Label(header, text='', fg=ACCENT, bg=BG, font=('Segoe UI', 11, 'bold'))
        counter.pack(side='right')

        center = tk.Frame(window, bg=BG)
        center.pack(fill='both', expand=True, padx=12, pady=5)
        center.grid_columnconfigure(1, weight=1)
        center.grid_rowconfigure(0, weight=1)
        picture_area = tk.Frame(center, bg=BG)
        picture_area.grid(row=0, column=1, sticky='nsew')
        picture = tk.Label(picture_area, bg=BG, fg=FG, text='Cargando imagen…')
        picture.pack(fill='both', expand=True)

        def display():
            state['job'] = None
            if not window.winfo_exists():
                return
            path = paths[state['index']]
            width = max(100, picture_area.winfo_width() - 18)
            height = max(100, picture_area.winfo_height() - 18)
            photo = load_local_image(path, width, height, master=window)
            state['photo'] = photo  # Mantener referencia para evitar pyimage inexistente.
            picture.config(image=photo if photo is not None else '',
                           text='' if photo is not None else 'No se pudo abrir esta captura.')
            counter.config(text=f'{state["index"] + 1} de {len(paths)}')
            filename.config(text=path.name)

        def schedule_display(_event=None):
            if state['job'] is not None:
                window.after_cancel(state['job'])
            state['job'] = window.after(90, display)

        def move(step):
            state['index'] = (state['index'] + step) % len(paths)
            schedule_display()

        prev = tk.Button(center, text='❮', command=lambda: move(-1), bg=CARD, fg=ACCENT,
                         activebackground=PANEL, activeforeground=FG, relief='flat',
                         font=('Segoe UI', 20, 'bold'), width=3, cursor='hand2')
        prev.grid(row=0, column=0, sticky='ns', padx=(0, 8))
        nxt = tk.Button(center, text='❯', command=lambda: move(1), bg=CARD, fg=ACCENT,
                        activebackground=PANEL, activeforeground=FG, relief='flat',
                        font=('Segoe UI', 20, 'bold'), width=3, cursor='hand2')
        nxt.grid(row=0, column=2, sticky='ns', padx=(8, 0))
        footer = tk.Frame(window, bg=BG)
        footer.pack(fill='x', padx=18, pady=(4, 12))
        filename = tk.Label(footer, text='', fg=MUTED, bg=BG, anchor='w')
        filename.pack(side='left', fill='x', expand=True)
        tk.Label(footer, text='← Anterior  ·  Siguiente →  ·  Esc para cerrar',
                 fg=MUTED, bg=BG).pack(side='right')

        window.bind('<Left>', lambda _: move(-1))
        window.bind('<Right>', lambda _: move(1))
        window.bind('<Escape>', lambda _: window.destroy())
        picture_area.bind('<Configure>', schedule_display)
        window.after(120, display)
        window.focus_set()

    def on_gallery_resize(self, event):
        """Reorganiza las miniaturas al cambiar el ancho del panel, sin parpadeos."""
        if self.gallery_resize_job is not None:
            self.after_cancel(self.gallery_resize_job)
        self.gallery_resize_job = self.after(100, self.layout_screenshots)

    def layout_screenshots(self):
        self.gallery_resize_job = None
        shots = self.current_shots
        available = self.screenshots_column.winfo_width()
        if available <= 1:
            return  # Tkinter todavía está calculando la geometría inicial.

        # Pocas imágenes: hasta dos columnas grandes. Muchas: hasta cuatro.
        desired = 1 if len(shots) == 1 else 2 if len(shots) <= 4 else 3 if len(shots) <= 6 else 4
        # Cada columna necesita al menos unos 120 px, incluidos sus márgenes.
        columns = min(desired, max(1, (available - 4) // 124))
        # No agrandamos indefinidamente las capturas en monitores anchos.
        thumb_width = max(60, min(185, (available - 8 * columns) // columns))
        thumb_height = max(35, round(thumb_width * 9 / 16))
        layout = (tuple(shots), columns, thumb_width, thumb_height)
        if layout == self.gallery_layout:
            return
        self.gallery_layout = layout

        for child in self.screenshots_frame.winfo_children():
            child.destroy()
        self.screenshot_images = []
        for i, path in enumerate(shots):
            photo = load_local_image(path, thumb_width, thumb_height, master=self)
            if photo is None:
                continue
            self.screenshot_images.append(photo)
            button = tk.Button(self.screenshots_frame, image=photo,
                               command=lambda idx=i, files=tuple(shots): self.open_screenshot_gallery(files, idx),
                               bg=CARD, activebackground=CARD, relief='flat',
                               cursor='hand2', bd=1)
            button.grid(row=i // columns, column=i % columns, padx=3, pady=3, sticky='nw')

    def render_screenshots(self, game):
        self.current_shots = find_screenshots(game['name'])
        # No se muestra título para las capturas; evita altura innecesaria.
        self.gallery_layout = None
        if self.gallery_resize_job is not None:
            self.after_cancel(self.gallery_resize_job)
        self.gallery_resize_job = self.after(50, self.layout_screenshots)

    def show_game_data(self, game):
        data = find_game_data(game['name'])
        for key, (slot, label) in self.info_values.items():
            value = data.get(key)
            if value:
                if key == 'genero':
                    # Los filtros usan todos los géneros; la barra rápida muestra
                    # solamente 2 o 3 para mantener su diseño compacto.
                    genres = _genres(value)
                    first_three = ' / '.join(genres[:3])
                    value = first_three if len(first_three) <= 36 else ' / '.join(genres[:2])
                label.config(text=value)
                slot.pack(side='left', padx=(0, 12))
            else:
                slot.pack_forget()
        # Siempre visible: el botón de marcado también funciona sin ficha de datos.
        self.info_bar.pack(fill='x', padx=18, pady=(2, 8), before=self.tabs)

    def on_detail_resize(self, event):
        # El texto acompaña al ancho disponible al redimensionar la ventana.
        self.synopsis_label.config(wraplength=max(230, self.screenshots_column.winfo_width() - 12))
        self.detail_title.config(wraplength=max(230, event.width - 52))
        self.detail_type.config(wraplength=max(230, event.width - 52))

    def show_synopsis(self, game):
        self.synopsis_full = find_synopsis(game['name'])
        self.synopsis_expanded = False
        if not self.synopsis_full:
            self.synopsis_area.pack_forget()
            return
        self.synopsis_area.pack(fill='x', padx=(2, 0), pady=(9, 4))
        self.update_synopsis_text()

    def toggle_synopsis(self):
        self.synopsis_expanded = not self.synopsis_expanded
        self.update_synopsis_text()

    def update_synopsis_text(self):
        text = self.synopsis_full
        # Recorte por palabras: aproximadamente 5-8 líneas en una ficha normal.
        limit = 430
        if not self.synopsis_expanded and len(text) > limit:
            excerpt = text[:limit].rsplit(' ', 1)[0].rstrip(' \n\r.,;:')
            self.synopsis_label.config(text=excerpt + '…')
            self.synopsis_button.config(text='Leer más')
            self.synopsis_button.pack(anchor='w', pady=(5, 0))
        else:
            self.synopsis_label.config(text=text)
            if len(text) > limit:
                self.synopsis_button.config(text='Leer menos')
                self.synopsis_button.pack(anchor='w', pady=(5, 0))
            else:
                self.synopsis_button.pack_forget()

    def on_genre_selected(self, _event=None):
        chosen = self.genre_display.get()
        self.genre_filter.set(chosen)
        self.genre_display.set(chosen)
        self.render_games()

    def on_sort_selected(self, _event=None):
        chosen = self.sort_display.get()
        self.sort_mode.set(chosen)
        self.sort_display.set(chosen)
        self.render_games()

    def refresh_classification(self):
        # Se consulta desde disco: los TXT descargados por la sincronización
        # se reflejan en los filtros sin reiniciar el programa.
        self.game_metadata = {g['name']: find_game_data(g['name']) for g in self.games}
        genres = {}
        for data in self.game_metadata.values():
            for genre in _genres(data.get('genero', '')):
                genres.setdefault(genre.casefold(), genre)
        choices = ['Todos los géneros'] + sorted(genres.values(), key=str.casefold)
        self.genre_combo.configure(values=choices)
        if self.genre_filter.get() not in choices:
            self.genre_filter.set('Todos los géneros')
        self.genre_display.set(self.genre_filter.get())

    def sort_games(self, games):
        mode = self.sort_mode.get()
        if mode == 'En Colección' or mode in PORT_FILTERS:
            return sorted(games, key=lambda g: g['name'].casefold())
        if mode == 'Mejor puntuación':
            return sorted(games, key=lambda g: (
                game_score(self.game_metadata.get(g['name'], {})) is None,
                -(game_score(self.game_metadata.get(g['name'], {})) or 0),
                g['name'].casefold()))
        if mode == 'Nombre (Z-A)':
            return sorted(games, key=lambda g: g['name'].casefold(), reverse=True)
        if mode == 'Nombre (A-Z)':
            return sorted(games, key=lambda g: g['name'].casefold())
        if mode.startswith('Año'):
            reverse = mode == 'Año (más recientes)'
            getter = lambda d: _year(d.get('anio', ''))
        elif mode in ('Recientes', 'Antiguos'):
            reverse = mode == 'Recientes'
            getter = lambda d: _date(d.get('incorporacion', ''))
        else:
            reverse = mode == 'Tamaño (mayor)'
            getter = lambda d: _number_size_gb(d.get('tamano', ''))
        # Los juegos sin el dato se muestran siempre al final.
        return sorted(games, key=lambda g: (
            getter(self.game_metadata.get(g['name'], {})) is None,
            -(getter(self.game_metadata.get(g['name'], {})) or 0) if reverse
            else (getter(self.game_metadata.get(g['name'], {})) or 0),
            g['name'].casefold()))

    @staticmethod
    def load_owned_games():
        try:
            data = json.loads(OWNED_FILE.read_text(encoding='utf-8'))
            if isinstance(data, list):
                return {name for name in data if isinstance(name, str)}
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            logging.exception('No se pudo leer mis_juegos.json')
        return set()

    def save_owned_games(self):
        try:
            OWNED_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = OWNED_FILE.with_suffix('.tmp')
            temporary.write_text(json.dumps(sorted(self.owned_games), ensure_ascii=False, indent=2),
                                 encoding='utf-8')
            temporary.replace(OWNED_FILE)
            return True
        except OSError as exc:
            messagebox.showerror('Mis juegos', f'No se pudo guardar la lista personal:\n{exc}')
            return False

    def set_owned(self, name, owned):
        previous = name in self.owned_games
        if owned:
            self.owned_games.add(name)
        else:
            self.owned_games.discard(name)
        if not self.save_owned_games():
            if previous:
                self.owned_games.add(name)
            else:
                self.owned_games.discard(name)
            return
        if self.sort_mode.get() == 'En Colección':
            self.render_games()
        else:
            self.refresh_owned_card(name)
        if self.selected and self.selected['name'] == name:
            self.update_owned_button()

    def toggle_owned_selected(self):
        if self.selected:
            name = self.selected['name']
            self.set_owned(name, name not in self.owned_games)

    def _hover_owned_button(self, hovering):
        self._owned_button_hover = hovering
        self.update_owned_button()

    def update_owned_button(self):
        """Muestra la ACCIÓN disponible, no el estado actual del juego."""
        canvas = self.owned_button
        canvas.delete('all')
        selected = bool(self.selected)
        owned = selected and self.selected['name'] in self.owned_games
        hovering = getattr(self, '_owned_button_hover', False) and selected

        if not selected:
            label, bg, border, fg = 'Lo tengo', '#303a47', '#536173', '#8e9aaa'
        elif owned:
            # Ya está en la colección: el botón permite quitarlo.
            label = '✕  No lo tengo'
            bg = '#823D42' if not hovering else '#A34B50'
            border, fg = '#D66B70', '#FFE5E5'
        else:
            # Todavía no está: el botón permite agregarlo.
            label = '✓  Lo tengo'
            bg = '#24523f' if not hovering else '#306b50'
            border, fg = '#55bd86', '#d3ffe4'

        w, h, r = 156, 38, 10
        canvas.configure(cursor='hand2' if selected else 'arrow')
        # Polígono suavizado: esquinas redondeadas sin relieve de Windows.
        coords = [r, 1, w-r, 1, w-1, 1, w-1, r,
                  w-1, h-r, w-1, h-1, w-r, h-1,
                  r, h-1, 1, h-1, 1, h-r, 1, r, 1, 1]
        canvas.create_polygon(coords, smooth=True, splinesteps=16,
                              fill=bg, outline=border, width=1.5)
        canvas.create_text(w//2, h//2, text=label, fill=fg,
                           font=('Segoe UI', 10, 'bold'))

    def refresh_owned_card(self, name):
        self.update_card_cover(name)

    def schedule_search_render(self):
        """Espera 300 ms desde la última tecla antes de filtrar el catálogo."""
        if self.search_render_job is not None:
            self.after_cancel(self.search_render_job)
        self.search_render_job = self.after(300, self._run_search_render)

    def _run_search_render(self):
        self.search_render_job = None
        self.render_games()
        # Recalcular el area visible tras filtrar y volver al inicio.
        self.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.canvas.yview_moveto(0)

    def render_games(self):
        if not hasattr(self, 'grid_frame'):
            return
        self.refresh_classification()
        text = self.search.get().strip().casefold()
        genre = self.genre_filter.get().casefold()
        filtered = [g for g in self.games
                    if (text in g['name'].casefold() or any(text in e['name'].casefold() for e in g['extras']))
                    and (genre == 'todos los géneros' or genre in
                         [x.casefold() for x in _genres(self.game_metadata.get(g['name'], {}).get('genero', ''))])]
        if self.sort_mode.get() == 'En Colección':
            filtered = [g for g in filtered if g['name'] in self.owned_games]
        if self.sort_mode.get() in PORT_FILTERS:
            expected = PORT_FILTERS[self.sort_mode.get()]
            filtered = [g for g in filtered if re.search(r'(?i)\b' + expected + r'\b',
                        self.game_metadata.get(g['name'], {}).get('port', ''))]
        filtered = self.sort_games(filtered)
        visible = [g['name'] for g in filtered]
        wanted = set(visible)
        # Las tarjetas filtradas se ocultan, no se destruyen. Se reutilizan al buscar.
        for name, card in self.card_widgets.items():
            if name not in wanted:
                card.grid_remove()
        cols = max(1, self.last_columns or 3)
        for i, game in enumerate(filtered):
            name = game['name']
            card = self.card_widgets.get(name)
            if card is None:
                card = tk.Frame(self.grid_frame, bg=CARD, padx=8, pady=8, cursor='hand2')
                photo = self.cached_card_photo(name)
                if photo:
                    cover = tk.Label(card, image=photo, bg=CARD, cursor='hand2')
                else:
                    cover = tk.Label(card, text='✓ DESCARGADO\nSIN CARÁTULA' if name in self.owned_games else 'SIN\nCARÁTULA',
                                     fg=MUTED, bg=PANEL, width=17, height=10,
                                     font=('Segoe UI', 11, 'bold'), cursor='hand2')
                cover.image = photo
                cover.pack()
                self.cover_cards[name] = cover
                title = tk.Label(card, text=split_game_title(name)[0], fg=FG, bg=CARD,
                                 wraplength=145, width=20, height=3,
                                 font=('Segoe UI', 9), cursor='hand2')
                title.pack(pady=(7, 0))
                for widget in (card, cover, title):
                    widget.bind('<Button-1>', lambda _, g=game: self.select_game(g))
                    widget.bind('<Enter>', lambda _, n=name: self.set_card_hover(n, True))
                    widget.bind('<Leave>', lambda event, n=name: self.card_pointer_leave(n, event))
                cover.bind('<Enter>', lambda event, n=name: self.schedule_hypervisor_tip(event.widget, n), add='+')
                cover.bind('<Leave>', self.hide_hypervisor_tip, add='+')
                self.card_widgets[name] = card
                self.card_parts[name] = (cover, title)
                self.paint_card(name)
            card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky='n')
        self.visible_game_names = visible
        if self.selected:
            self.paint_card(self.selected['name'])
        # Un solo indicador reutilizable en lugar de crear uno por cada búsqueda.
        if not hasattr(self, 'empty_catalog_label'):
            self.empty_catalog_label = tk.Label(self.grid_frame, fg=MUTED, bg=BG,
                                                font=('Segoe UI', 12))
        if not filtered and self.catalog_loading:
            self.empty_catalog_label.grid_remove()
        elif not filtered:
            empty_message = ('Cargando juegos...' if self.catalog_loading and not self.games
                             else 'No se pudo cargar el catálogo.' if self.catalog_error and not self.games
                             else 'No hay juegos en tu colección.' if self.sort_mode.get() == 'En Colección'
                             and not self.search.get().strip() and self.genre_filter.get() == 'Todos los géneros'
                             else 'No se encontraron juegos.')
            self.empty_catalog_label.config(text=empty_message)
            self.empty_catalog_label.grid(row=0, column=0, padx=20, pady=30)
        else:
            self.empty_catalog_label.grid_remove()
        if not self.catalog_loading and not self.catalog_error:
            count = f'{len(filtered)} coincidencias de {len(self.games)} juegos' if text else f'Mostrando {len(filtered)} de {len(self.games)} juegos'
            self.status.config(text=f'{count} · {sum(len(g["extras"]) for g in self.games)} complementos agrupados')
        self.after_idle(self.alinear_filtros_con_caratulas)

    def paint_card(self, name):
        card = self.card_widgets.get(name)
        parts = self.card_parts.get(name)
        if card is None or parts is None:
            return
        selected = self.selected is not None and self.selected['name'] == name
        hovered = self.hovered_card == name
        color = '#315b4d' if selected else '#314758' if hovered else CARD
        card.config(bg=color)
        for widget in parts:
            # Conservar el fondo de las carátulas sin imagen.
            if widget is parts[1] or getattr(widget, 'image', None) is not None:
                widget.config(bg=color)

    def set_card_hover(self, name, active):
        old = self.hovered_card
        self.hovered_card = name if active else None
        if old and old != name:
            self.paint_card(old)
        self.paint_card(name)

    def card_pointer_leave(self, name, event):
        card = self.card_widgets.get(name)
        if card is None:
            return
        x, y = card.winfo_pointerxy()
        if 0 <= x - card.winfo_rootx() < card.winfo_width() and 0 <= y - card.winfo_rooty() < card.winfo_height():
            return
        if self.hovered_card == name:
            self.set_card_hover(name, False)

    def alinear_filtros_con_caratulas(self):
        """Alinea el selector derecho con el borde real de la última tarjeta."""
        if not self.filters.winfo_exists():
            return
        # Medimos las columnas reales, pero no usamos las posiciones de
        # tarjetas durante un repintado parcial (pueden ser transitorias).
        columnas = max(1, self.last_columns or 1)
        tarjetas = [w for w in self.grid_frame.winfo_children()
                    if isinstance(w, tk.Frame) and w.grid_info().get('row') == 0]
        if len(tarjetas) < columnas:
            return
        self.grid_frame.update_idletasks()
        ultima = max(tarjetas, key=lambda w: int(w.grid_info()['column']))
        # El marco de filtros está desplazado 9 px respecto del lienzo.
        # Su ancho termina exactamente en el borde de la última tarjeta.
        ancho = max(325, ultima.winfo_x() + ultima.winfo_width() - 9)
        if self.filters.winfo_width() != ancho:
            self.filters.configure(width=ancho)

    def on_header_badge_motion(self, event):
        """Tooltip únicamente cuando el puntero está sobre la insignia."""
        badge = self.repacker_badge_photos.get(self.current_repacker)
        if badge is None or event.x < self.ficha_header.winfo_width() - 12 - badge.width() or event.x > self.ficha_header.winfo_width() - 12:
            self.hide_repacker_tooltip()
            return
        if abs(event.y - self.ficha_header.winfo_height() / 2) <= badge.height() / 2:
            if self.repacker_tooltip is None and self.repacker_tooltip_job is None:
                self.schedule_repacker_tooltip()
        else:
            self.hide_repacker_tooltip()

    def schedule_repacker_tooltip(self, event=None):
        """Muestra el nombre completo tras una breve pausa sobre la insignia."""
        self.hide_repacker_tooltip()
        if self.current_repacker in self.repacker_badge_photos:
            self.repacker_tooltip_job = self.after(450, self.show_repacker_tooltip)

    def show_repacker_tooltip(self):
        self.repacker_tooltip_job = None
        names = {'FitGirl': 'FitGirl Repacks', 'ElAmigos': 'ElAmigos Repacks',
                 'DODI': 'DODI Repacks', 'KaOs': 'KaOs Krew Repacks',
                 'Rohankar': 'Rohankar Repacks'}
        name = names.get(self.current_repacker)
        if not name or not self.ficha_header.winfo_ismapped():
            return
        tip = tk.Toplevel(self)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.configure(bg='#40546b')
        label = tk.Label(tip, text=name, bg='#253344', fg=FG,
                         font=('Segoe UI', 10), padx=10, pady=6,
                         bd=1, relief='solid')
        label.pack()
        tip.update_idletasks()
        x = min(self.winfo_pointerx() + 12,
                self.winfo_screenwidth() - tip.winfo_reqwidth() - 8)
        y = min(self.winfo_pointery() + 18,
                self.winfo_screenheight() - tip.winfo_reqheight() - 8)
        tip.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.repacker_tooltip = tip
        tip.deiconify()

    def hide_repacker_tooltip(self, event=None):
        if self.repacker_tooltip_job is not None:
            self.after_cancel(self.repacker_tooltip_job)
            self.repacker_tooltip_job = None
        if self.repacker_tooltip is not None:
            self.repacker_tooltip.destroy()
            self.repacker_tooltip = None

    def schedule_hypervisor_tip(self, widget, name):
        """Tooltip discreto al pasar por una carátula con Crack: Hypervisor."""
        self.hide_hypervisor_tip()
        if not name:
            return
        data = self.game_metadata.get(name, {})
        if not is_hypervisor(data):
            data = find_game_data(name)
        if not is_hypervisor(data):
            return
        self.hypervisor_tip_widget = widget
        self.hypervisor_tip_job = self.after(450, lambda w=widget: self.show_hypervisor_tip(w))

    def show_hypervisor_tip(self, widget):
        self.hypervisor_tip_job = None
        if not widget.winfo_exists() or not widget.winfo_ismapped():
            return
        tip = tk.Toplevel(self)
        tip.withdraw()
        tip.overrideredirect(True)
        tip.configure(bg='#a92323')
        tk.Label(tip, text='Usa Hypervisor', bg='#a92323', fg='white',
                 font=('Segoe UI', 10, 'bold'), padx=10, pady=5).pack(padx=1, pady=1)
        tip.update_idletasks()
        x = min(self.winfo_pointerx() + 14, self.winfo_screenwidth() - tip.winfo_reqwidth() - 8)
        y = min(self.winfo_pointery() + 18, self.winfo_screenheight() - tip.winfo_reqheight() - 8)
        tip.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.hypervisor_tip = tip
        tip.deiconify()

    def hide_hypervisor_tip(self, event=None):
        if self.hypervisor_tip_job is not None:
            self.after_cancel(self.hypervisor_tip_job)
            self.hypervisor_tip_job = None
        if self.hypervisor_tip is not None:
            self.hypervisor_tip.destroy()
            self.hypervisor_tip = None
        self.hypervisor_tip_widget = None

    def select_game(self, game):
        self.hide_hypervisor_tip()
        # Primera selección: retiramos la bienvenida y dejamos la ficha intacta.
        if self.welcome.winfo_manager():
            self.welcome.place_forget()
        previous = self.selected['name'] if self.selected else None
        self.selected = game
        if previous:
            self.paint_card(previous)
        self.paint_card(game['name'])
        self.hide_repacker_tooltip()
        self.current_repacker = identify_repacker(game, find_game_data(game['name']))
        self.redraw_ficha_header()
        self.update_owned_button()
        clean_title, extra_info = split_game_title(game['name'])
        # El sello ya no invade esta zona: título y subtítulo siempre centrados.
        self.detail_title.pack_configure(padx=18, pady=(0, 6))
        self.detail_title.config(text=clean_title)
        self.download_button.config(state='disabled' if self.busy else 'normal',
                                    text=self.action_label(game, complement=False))
        self.report_button.config(state='normal')
        self.guide_button.place_forget()
        self.text_request += 1
        self.show_text('Instrucciones / enlaces', 'Elegí «Ver instrucciones» o «Ver enlaces de descarga» para leer un TXT aquí.')
        self.tabs.select(self.downloads_tab)
        if game.get('guide'):
            # Alineado verticalmente con Descargas / Instrucciones.
            self.guide_button.place(in_=self.tabs.nav, relx=1.0, x=-8, y=4, anchor='ne')
            self.guide_button.lift()
        self.detail_type.config(text=extra_info)
        if extra_info:
            self.detail_type.pack(before=self.media_row, anchor='center', padx=18, pady=(0, 12))
        else:
            self.detail_type.pack_forget()
        photo = self.load_cover(game['name'], 225, 315)
        self.detail_cover.config(image=photo if photo is not None else '',
                                 text='' if photo else 'SIN CARÁTULA')
        self.detail_cover.image = photo
        self.render_screenshots(game)
        self.show_game_data(game)
        self.show_synopsis(game)
        self.schedule_remote_assets(selected_only=True)
        for widget in self.extras_frame.winfo_children():
            widget.destroy()
        extras = game['extras']
        self.extras_title.config(text=f'COMPLEMENTOS ({len(extras)})' if extras else '')
        for extra in extras:
            row = tk.Frame(self.extras_frame, bg=CARD, padx=10, pady=9)
            row.pack(fill='x', pady=(5, 3))
            name_label = tk.Label(row, text=extra['name'], fg=FG, bg=CARD,
                                  wraplength=240, justify='left', anchor='w',
                                  font=('Segoe UI', 10))
            name_label.pack(side='left', fill='x', expand=True)
            actions = tk.Frame(row, bg=CARD)
            actions.pack(side='right', padx=(8, 0))
            btn = tk.Button(actions, text='↓  ' + self.action_label(extra, complement=True),
                            command=lambda e=extra: self.run_entry(e),
                            state='disabled' if self.busy else 'normal',
                            bg='#20583f', fg='#e9fff2', activebackground='#307e59',
                            activeforeground='white', relief='flat', bd=0,
                            padx=10, pady=6, cursor='hand2', font=('Segoe UI', 9, 'bold'))
            btn.pack(side='top', fill='x')
            if extra.get('guide'):
                tk.Button(actions, text='Ver instrucciones →',
                          command=lambda e=extra: self.run_guide(e),
                          bg=CARD, fg=MUTED, activebackground=CARD,
                          activeforeground=ACCENT, relief='flat', bd=0,
                          cursor='hand2', font=('Segoe UI', 9)).pack(side='top', pady=(5, 0))


    def open_report_dialog(self):
        """Formulario de reportes de la ficha seleccionada (sin abrir navegador)."""
        if not self.selected:
            return
        game_name = self.selected['name']
        popup = tk.Toplevel(self)
        popup.title('Juegos Torrent | Reportar problema')
        popup.configure(bg=BG)
        centered_popup(popup, 620, 650)
        popup.minsize(480, 480)
        popup.transient(self)
        popup.grab_set()
        popup.bind('<Escape>', lambda _event: popup.destroy())

        body = tk.Frame(popup, bg=BG, padx=22, pady=18)
        body.pack(fill='both', expand=True)
        tk.Label(body, text='REPORTAR UN PROBLEMA', fg=ACCENT, bg=BG,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        tk.Label(body, text=game_name, fg=FG, bg=BG, wraplength=550,
                 justify='left', font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(8, 15))
        tk.Label(body, text='Seleccioná el motivo:', fg=MUTED, bg=BG,
                 font=('Segoe UI', 10)).pack(anchor='w', pady=(0, 6))
        reason = tk.StringVar(value=REPORTES_MOTIVOS[0])
        combo = ttk.Combobox(body, textvariable=reason, values=REPORTES_MOTIVOS,
                             state='readonly', font=('Segoe UI', 10))
        combo.pack(fill='x', pady=(0, 16))
        tk.Label(body, text='Comentario adicional (opcional, hasta 500 caracteres):',
                 fg=MUTED, bg=BG, font=('Segoe UI', 10)).pack(anchor='w', pady=(0, 6))
        comment = tk.Text(body, height=7, wrap='word', bg='#ffffff', fg='#1c2530',
                          relief='flat', padx=10, pady=9, font=('Segoe UI', 10))
        comment.pack(fill='both', expand=True)
        tk.Label(body, text='Si es un update, pack o fix, indicá cuál falla.',
                 fg=MUTED, bg=BG, font=('Segoe UI', 9)).pack(anchor='w', pady=(7, 10))
        status = tk.Label(body, text='', fg=MUTED, bg=BG, anchor='w',
                          font=('Segoe UI', 9))
        status.pack(fill='x', pady=(0, 8))
        actions = tk.Frame(body, bg=BG)
        actions.pack(fill='x')
        submit = tk.Button(actions, text='Enviar reporte', bg='#20583f', fg=FG,
                           activebackground='#307e59', activeforeground=FG,
                           relief='flat', bd=0, cursor='hand2', padx=17, pady=10,
                           font=('Segoe UI', 10, 'bold'))
        submit.pack(side='right')
        tk.Button(actions, text='Cancelar', command=popup.destroy,
                  bg=CARD, fg=FG, relief='flat', bd=0, cursor='hand2',
                  padx=15, pady=10).pack(side='right', padx=(0, 9))

        def send():
            url = REPORTES_URL.strip()
            if not url.startswith('https://script.google.com/') or not url.endswith('/exec'):
                messagebox.showwarning('Reportes sin configurar',
                    'Primero configurá REPORTES_URL con la URL /exec de Google Apps Script.',
                    parent=popup)
                return
            message = comment.get('1.0', 'end-1c').strip()
            if len(message) > 500:
                messagebox.showwarning('Comentario demasiado largo',
                    'El comentario puede tener hasta 500 caracteres.', parent=popup)
                return
            payload = {'juego': game_name, 'problema': reason.get(),
                       'comentario': message, 'id_juego': game_name}
            submit.config(state='disabled')
            status.config(text='Enviando reporte...')

            def finish(ok, error=''):
                if not popup.winfo_exists():
                    return
                if ok:
                    popup.destroy()
                    messagebox.showinfo('Reporte enviado',
                        '¡Reporte enviado! Gracias por ayudarnos a mejorar el catálogo.',
                        parent=self)
                else:
                    submit.config(state='normal')
                    status.config(text='No se pudo enviar. Podés volver a intentarlo.')
                    messagebox.showerror('Error al enviar', error, parent=popup)

            def work():
                try:
                    request = Request(url,
                        data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                        headers={'Content-Type': 'text/plain; charset=utf-8'},
                        method='POST')
                    with urlopen(request, timeout=30) as response:
                        raw = response.read(16384).decode('utf-8')
                    result = json.loads(raw)
                    if result.get('ok') is not True:
                        raise ValueError(result.get('error', 'El servidor rechazó el reporte.'))
                    self.after(0, lambda: finish(True))
                except Exception as exc:
                    error = str(exc)
                    self.after(0, lambda: finish(False, error))
            threading.Thread(target=work, daemon=True).start()
        submit.config(command=send)
        combo.focus_set()

    def download_selected(self):
        if self.selected:
            self.run_entry(self.selected)

    def open_selected_guide(self):
        if self.selected:
            self.run_guide(self.selected)

    def run_guide(self, entry):
        if not entry.get('guide'):
            messagebox.showinfo('JUEGOS', 'Este juego no tiene ficha de instalación.')
            return
        guide_entry = {'name': entry['name'], 'type': 'txt', 'value': entry['guide']}
        self.show_remote_text(guide_entry, title='Instrucciones: ' + entry['name'])

    def action_label(self, entry, complement=False):
        if entry['type'] == 'pagina':
            return 'Abrir página'
        if entry['type'] == 'txt':
            return 'Ver enlaces de descarga'
        return 'Descargar complemento' if complement else 'Descargar juego'

    def _fit_text_heading(self, event=None):
        if not hasattr(self, 'text_heading'):
            return
        title = getattr(self, '_full_text_heading', self.text_heading.cget('text'))
        width = max(80, self.instructions_tab.winfo_width() - 32)
        font = tkfont.Font(family='Segoe UI', size=11, weight='bold')
        # Priorizar la línea única y la legibilidad.
        for size in range(11, 8, -1):
            font.configure(size=size)
            if font.measure(title) <= width:
                self.text_heading.config(text=title, font=('Segoe UI', size, 'bold'))
                return
        font.configure(size=9)
        shortened = title
        while shortened and font.measure(shortened + '…') > width:
            shortened = shortened[:-1]
        self.text_heading.config(text=shortened.rstrip() + '…',
                                 font=('Segoe UI', 9, 'bold'))

    def show_text(self, title, content, markdown=False):
        self._full_text_heading = title
        self._raw_instruction_text = content
        self._text_is_markdown = markdown or is_markdown_text(content)
        self._fit_text_heading()
        self.text_view.config(state='normal')
        self.text_view.delete('1.0', 'end')
        if self._text_is_markdown:
            render_markdown(self.text_view, content)
        else:
            self.text_view.insert('1.0', content)
            self.text_view.config(state='disabled')
        self.text_view.yview_moveto(0)

    def open_help_center(self, parent=None):
        """Centro de ayuda local, con índice JSON y documentos externos opcionales."""
        directory = BASE / 'tutoriales'
        index_path = directory / 'guias.json'
        try:
            with index_path.open('r', encoding='utf-8-sig') as handle:
                index = json.load(handle)
            if not isinstance(index, list):
                raise ValueError('guias.json debe contener una lista de guías.')
            entries = [item for item in index
                       if isinstance(item, dict) and item.get('titulo')]
        except FileNotFoundError:
            entries = []
        except (OSError, ValueError, UnicodeError) as exc:
            messagebox.showerror('Centro de ayuda',
                                 f'No se pudo leer tutoriales/guias.json:\n{exc}')
            return

        window = tk.Toplevel(self)
        window.title('Juegos Torrent | Centro de ayuda')
        window.configure(bg=BG)
        centered_popup(window, 1040, 1100)
        window.minsize(700, 430)
        window.transient(parent if parent is not None and parent.winfo_exists() else self)
        window.bind('<Escape>', lambda _: window.destroy())

        header = tk.Frame(window, bg=PANEL, padx=20, pady=15)
        header.pack(fill='x')
        tk.Label(header, text='CENTRO DE AYUDA  ·  GUÍAS Y TUTORIALES',
                 bg=PANEL, fg=ACCENT, font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        tk.Label(header, text='Descargas, instalación, lanzadores y soluciones frecuentes',
                 bg=PANEL, fg=MUTED, font=('Segoe UI', 10)).pack(anchor='w', pady=(4, 0))

        main = tk.Frame(window, bg=BG)
        main.pack(fill='both', expand=True, padx=16, pady=14)
        sidebar = tk.Frame(main, bg=PANEL, width=280)
        sidebar.pack(side='left', fill='y', padx=(0, 12))
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text='CATEGORÍAS', bg=PANEL, fg=ACCENT,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=14, pady=(15, 8))
        categories = ['Todas las guías'] + list(dict.fromkeys(
            str(item.get('categoria') or 'General') for item in entries))
        cat_list = tk.Listbox(sidebar, bg=PANEL, fg=FG, selectbackground='#20583f',
                              selectforeground=FG, relief='flat', bd=0,
                              highlightthickness=0, font=('Segoe UI', 11),
                              exportselection=False, activestyle='none')
        cat_list.pack(fill='x', padx=9, pady=(0, 16))
        for category in categories:
            cat_list.insert('end', category)

        right = tk.Frame(main, bg=PANEL)
        right.pack(side='left', fill='both', expand=True)
        tk.Label(right, text='TUTORIALES DISPONIBLES', bg=PANEL, fg=ACCENT,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', padx=18, pady=(16, 7))
        guide_list = tk.Listbox(right, bg=CARD, fg=FG, selectbackground='#20583f',
                                selectforeground=FG, relief='flat', bd=0,
                                highlightthickness=0, font=('Segoe UI', 11),
                                exportselection=False, activestyle='none', height=7)
        guide_list.pack(fill='x', padx=18, pady=(0, 12))
        description = tk.Text(right, bg='#ffffff', fg='#1c2530', wrap='word', relief='flat',
                              bd=0, padx=16, pady=14, font=('Segoe UI', 11),
                              spacing1=3, spacing3=6, state='disabled',
                              selectbackground='#b9d9c6', selectforeground='#17251e')
        actions = tk.Frame(right, bg=PANEL)
        actions.pack(side='bottom', fill='x', padx=18, pady=(4, 16))
        description.pack(fill='both', expand=True, padx=18, pady=(0, 12))
        visible = []
        current = [None]

        def set_description(value, markdown=False):
            if markdown:
                render_markdown(description, value)
            else:
                description.configure(state='normal')
                description.delete('1.0', 'end')
                description.insert('1.0', value)
                description.configure(state='disabled')
                description.yview_moveto(0)

        def select_guide(_event=None):
            indices = guide_list.curselection()
            current[0] = visible[indices[0]] if indices else None
            entry = current[0]
            if entry is None:
                set_description('Seleccioná una guía para ver su contenido.')
                return
            text = str(entry.get('descripcion') or '')
            filename = entry.get('archivo')
            is_markdown = False
            if filename:
                relative = Path(str(filename))
                path = (directory / relative).resolve()
                # Los archivos siempre deben permanecer dentro de tutoriales.
                if not path.is_relative_to(directory.resolve()):
                    text += '\n\nArchivo no permitido: ruta fuera de tutoriales.'
                elif path.suffix.lower() in ('.txt', '.md') and path.is_file():
                    try:
                        text += ('\n\n' if text else '') + path.read_text(encoding='utf-8-sig')
                        is_markdown = path.suffix.lower() == '.md'
                    except (OSError, UnicodeError) as exc:
                        text += f'\n\nNo se pudo leer el archivo: {exc}'
                elif not path.is_file():
                    text += '\n\nEl archivo todavía no está disponible.'
                else:
                    text += '\n\nPresioná ABRIR ARCHIVO para consultar el documento.'
            set_description(text or 'Esta guía todavía no tiene contenido.',
                            markdown=is_markdown)

        def refresh(_event=None):
            chosen = categories[cat_list.curselection()[0]] if cat_list.curselection() else categories[0]
            visible[:] = [item for item in entries if chosen == 'Todas las guías'
                          or str(item.get('categoria') or 'General') == chosen]
            guide_list.delete(0, 'end')
            for entry in visible:
                guide_list.insert('end', entry['titulo'])
            if visible:
                guide_list.selection_set(0)
            select_guide()

        def open_document():
            entry = current[0]
            if not entry or not entry.get('archivo'):
                messagebox.showinfo('Centro de ayuda', 'Esta guía no tiene un archivo asociado.',
                                    parent=window)
                return
            path = (directory / str(entry['archivo'])).resolve()
            if not path.is_relative_to(directory.resolve()) or path.suffix.lower() not in ('.pdf', '.txt', '.md'):
                messagebox.showwarning('Centro de ayuda', 'Tipo de archivo o ruta no permitidos.',
                                       parent=window)
                return
            if not path.is_file():
                messagebox.showwarning('Centro de ayuda', 'Todavía no existe ese archivo.',
                                       parent=window)
                return
            try:
                if os.name == 'nt':
                    os.startfile(str(path))
                else:
                    webbrowser.open(path.as_uri())
            except (OSError, ValueError) as exc:
                messagebox.showerror('Centro de ayuda', str(exc), parent=window)

        tk.Button(actions, text='📄 ABRIR PDF / ARCHIVO', command=open_document,
                  bg='#20583f', fg=FG, activebackground='#307e59',
                  activeforeground=FG, relief='flat', bd=0, cursor='hand2',
                  font=('Segoe UI', 10, 'bold'), padx=15, pady=9).pack(side='left')
        tk.Button(actions, text='CERRAR', command=window.destroy,
                  bg=CARD, fg=FG, relief='flat', bd=0, cursor='hand2',
                  font=('Segoe UI', 10, 'bold'), padx=15, pady=9).pack(side='right')
        cat_list.bind('<<ListboxSelect>>', refresh)
        guide_list.bind('<<ListboxSelect>>', select_guide)
        guide_list.bind('<Double-Button-1>', lambda _e: open_document())
        if entries:
            cat_list.selection_set(0)
            refresh()
        else:
            set_description('Todavía no hay tutoriales. Agregá guías en tutoriales/guias.json.')
        window.focus_set()

    def open_text_viewer(self):
        """Visor independiente y cómodo para instrucciones y enlaces."""
        title = getattr(self, '_full_text_heading', self.text_heading.cget('text'))
        content = getattr(self, '_raw_instruction_text', self.text_view.get('1.0', 'end-1c'))
        viewer = tk.Toplevel(self)
        viewer.title('Juegos Torrent | ' + title)
        viewer.configure(bg=BG)
        centered_popup(viewer, 900, 1100)
        viewer.minsize(540, 360)
        viewer.transient(self)

        header = tk.Frame(viewer, bg=PANEL, padx=22, pady=16)
        header.pack(fill='x')
        tk.Label(header, text=title, bg=PANEL, fg=ACCENT,
                 font=('Segoe UI', 15, 'bold'), anchor='w',
                 wraplength=790, justify='left').pack(fill='x')

        toolbar = tk.Frame(viewer, bg=BG, padx=22, pady=12)
        toolbar.pack(fill='x')
        size = [12]
        size_label = tk.Label(toolbar, text='12 pt', bg=BG, fg=MUTED,
                              font=('Segoe UI', 10))
        def zoom(delta):
            size[0] = max(9, min(24, size[0] + delta))
            reader.configure(font=('Segoe UI', size[0]))
            size_label.configure(text=f'{size[0]} pt')

        tk.Label(toolbar, text='Tamaño de letra', bg=BG, fg=MUTED,
                 font=('Segoe UI', 10)).pack(side='left', padx=(0, 12))
        for caption, delta in [('A−', -1), ('A+', 1)]:
            tk.Button(toolbar, text=caption, command=lambda d=delta: zoom(d),
                      bg=CARD, fg=FG, activebackground='#34445a',
                      activeforeground=FG, relief='flat', bd=0,
                      cursor='hand2', padx=12, pady=5,
                      font=('Segoe UI', 11, 'bold')).pack(side='left', padx=(0, 6))
        size_label.pack(side='left', padx=(4, 0))

        def copy_viewer():
            if content.strip():
                viewer.clipboard_clear()
                viewer.clipboard_append(content)
                self.status.config(text='Texto copiado al portapapeles.')

        tk.Button(toolbar, text='📖 Ver guías', command=lambda: self.open_help_center(viewer),
                  bg='#20583f', fg=FG, activebackground='#307e59',
                  activeforeground=FG, relief='flat', bd=0, cursor='hand2',
                  font=('Segoe UI', 10, 'bold'), padx=14, pady=7).pack(side='right', padx=(0, 8))

        tk.Button(toolbar, text='Copiar todo', command=copy_viewer,
                  bg=CARD, fg=FG, activebackground='#34445a',
                  activeforeground=FG, relief='flat', bd=0, cursor='hand2',
                  font=('Segoe UI', 10, 'bold'), padx=14, pady=7).pack(side='right')

        body = tk.Frame(viewer, bg=BG, padx=22, pady=0)
        body.pack(fill='both', expand=True)
        reader = tk.Text(body, wrap='word', bg='#ffffff', fg='#1c2530',
                         selectbackground='#b9d9c6', selectforeground='#17251e',
                         relief='flat', bd=0, padx=22, pady=20,
                         font=('Segoe UI', size[0]), spacing1=4,
                         spacing2=2, spacing3=7, cursor='xterm')
        scroll = ttk.Scrollbar(body, orient='vertical', command=reader.yview)
        reader.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        reader.pack(side='left', fill='both', expand=True)
        if getattr(self, '_text_is_markdown', False):
            render_markdown(reader, content, font_size=size[0])
        else:
            reader.insert('1.0', content)
            reader.configure(state='disabled')
        reader.bind('<Control-plus>', lambda e: (zoom(1), 'break')[1])
        reader.bind('<Control-minus>', lambda e: (zoom(-1), 'break')[1])
        viewer.bind('<Escape>', lambda e: viewer.destroy())
        reader.focus_set()

        footer = tk.Frame(viewer, bg=BG, padx=22, pady=12)
        footer.pack(fill='x')
        tk.Label(footer, text='Ctrl+C para copiar selección  ·  Esc para cerrar',
                 bg=BG, fg=MUTED, font=('Segoe UI', 9)).pack(side='left')
        tk.Button(footer, text='Cerrar', command=viewer.destroy,
                  bg=CARD, fg=FG, activebackground='#34445a',
                  activeforeground=FG, relief='flat', bd=0,
                  cursor='hand2', padx=18, pady=7).pack(side='right')

    def copy_text(self):
        content = getattr(self, '_raw_instruction_text', self.text_view.get('1.0', 'end-1c'))
        if content.strip():
            self.clipboard_clear()
            self.clipboard_append(content)
            self.status.config(text='Texto copiado al portapapeles.')

    def show_remote_text(self, entry, title=None):
        if self.busy:
            messagebox.showinfo('JUEGOS', 'Esperá a que termine la descarga actual.')
            return
        self.text_request += 1
        request_id = self.text_request
        title = title or ('Enlaces de descarga: ' + entry['name'])
        self.tabs.select(self.instructions_tab)
        self.show_text(title, 'Cargando texto desde Google Drive...')
        def work():
            try:
                request = Request(drive_url(entry['value']), headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(request, timeout=35) as response:
                    data = response.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024:
                    raise ValueError('El archivo de texto es demasiado grande para mostrarlo.')
                raw = data.decode('utf-8-sig', errors='replace')
                if re.search(r'(?is)^\s*(?:<!doctype\s+html|<html|<head|<body)', raw):
                    raise ValueError('Google Drive devolvió una página HTML en lugar del texto.')
                self.after(0, lambda: self.text_loaded(request_id, title, raw, entry.get('type') == 'md'))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: self.text_failed(request_id, title, msg))
        threading.Thread(target=work, daemon=True).start()

    def text_loaded(self, request_id, title, raw, markdown=False):
        if request_id == self.text_request:
            self.show_text(title, raw, markdown=markdown)
            self.status.config(text='Texto cargado: ' + title)

    def text_failed(self, request_id, title, msg):
        if request_id == self.text_request:
            self.show_text(title, 'No se pudo cargar el texto.\n\n' + msg)
            self.status.config(text='Error al cargar el texto.')

    def run_entry(self, entry):
        if self.busy:
            messagebox.showinfo('JUEGOS', 'Esperá a que termine la descarga actual.')
            return
        kind = entry['type']
        if kind in ('txt', 'md'):
            self.show_remote_text(entry)
            return
        if kind == 'pagina':
            webbrowser.open(entry['value'])
            self.status.config(text='Página abierta en el navegador: ' + entry['name'])
            return
        if kind not in ('torrent', 'directa', 'txt'):
            messagebox.showerror('JUEGOS', 'Tipo de descarga no reconocido: ' + kind)
            return
        name = safe_filename(entry['name'])
        if kind == 'torrent':
            dest = DOWNLOADS / (name + '.torrent')
            url = drive_url(entry['value'])
        elif kind == 'txt':
            dest = GUIDES / (name + '.txt')
            url = drive_url(entry['value'])
        else:
            # Compatibilidad con el script original: descargas directas como RAR.
            dest = DOWNLOADS / (name + '.rar')
            url = entry['value']
        if kind == 'directa' and dest.exists():
            if not messagebox.askyesno('Archivo existente',
                                       'El archivo ya existe. ¿Querés descargarlo otra vez?'):
                return
        self.download_game_name = self.selected['name'] if self.selected else entry['name']
        self.busy = True
        self.download_button.config(state='disabled')
        for row in self.extras_frame.winfo_children():
            for child in row.winfo_children():
                for button in child.winfo_children():
                    if isinstance(button, tk.Button):
                        button.config(state='disabled')
        self.status.config(text='Descargando: ' + entry['name'])

        def progress(done, total):
            mb = done / 1048576
            label = (f'{mb:.1f} / {total / 1048576:.1f} MB' if total else f'{mb:.1f} MB')
            self.after(0, lambda: self.status.config(text=f'Descargando {entry["name"]}: {label}'))

        def work():
            try:
                result = download_file(url, dest, progress)
                self.after(0, lambda: self.download_done(kind, result))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: self.download_failed(msg))
        threading.Thread(target=work, daemon=True).start()

    def finish_download(self):
        self.busy = False
        if self.selected:
            self.select_game(self.selected)

    def download_done(self, kind, path):
        self.finish_download()
        try:
            if kind == 'torrent':
                os.startfile(str(path))
                self.status.config(text='Torrent abierto con el cliente asociado: ' + path.name)
                if getattr(self, 'download_game_name', None) and self.download_game_name not in self.owned_games:
                    name = self.download_game_name
                    if messagebox.askyesno('Mis juegos',
                                           f'¿Querés marcar «{name}» como descargado?\n\n'
                                           'Esto es una marca personal: no verifica que el juego '
                                           'haya terminado de descargarse.'):
                        self.set_owned(name, True)
            elif kind == 'txt':
                os.startfile(str(path))
                self.status.config(text='Ficha abierta: ' + path.name)
            else:
                self.status.config(text='Descarga terminada: ' + str(path))
                messagebox.showinfo('JUEGOS', 'Descarga terminada.\n\n' + str(path))
        except OSError as exc:
            messagebox.showerror('JUEGOS', 'Archivo descargado, pero no se pudo abrir:\n' + str(exc))

    def download_failed(self, msg):
        self.finish_download()
        self.status.config(text='Error durante la descarga.')
        messagebox.showerror('JUEGOS - Error de descarga', msg)


def ejecutar_instancia_unica():
    """Evita que un doble clic accidental lance dos sincronizadores en Windows."""
    if os.name != 'nt':
        App().mainloop()
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    mutex = kernel32.CreateMutexW(None, False, r'Local\KalakasSoft_JuegosTorrent')
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())

    ya_abierto = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    try:
        if ya_abierto:
            ctypes.windll.user32.MessageBoxW(
                None,
                'Juegos Torrent ya está abierto.\\n\\n'
                'Usá la ventana que está en ejecución para evitar '
                'dos sincronizaciones simultáneas.',
                'Juegos Torrent',
                0x40
            )
            return
        App().mainloop()
    finally:
        kernel32.CloseHandle(mutex)


if __name__ == '__main__':
    ejecutar_instancia_unica()
