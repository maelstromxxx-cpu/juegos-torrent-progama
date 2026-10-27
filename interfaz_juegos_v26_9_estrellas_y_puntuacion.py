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
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
except ImportError:
    Image = ImageTk = None  # PNG funciona sin Pillow; JPG requiere Pillow.
from urllib.request import Request, urlopen

CATALOG_ID = '1WP2cyZ3ovEHqs6S18bi49U41EkrG0Uld'
CATALOG_URL = f'https://drive.google.com/uc?export=download&id={CATALOG_ID}'
CATALOG_CACHE_NAME = 'catalogo_cache.txt'
BASE = Path(__file__).resolve().parent
CATALOG_CACHE = BASE / CATALOG_CACHE_NAME
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
            if second.lower() in ('torrent', 'directa', 'pagina', 'txt'):
                kind, value, guide = second.lower(), third, ''
            else:
                kind, value, guide = 'torrent', second, third
        elif len(parts) == 4:
            name, kind, value, guide = parts
            kind = kind.lower()
        else:
            continue
        if name and value and kind in ('torrent', 'directa', 'pagina', 'txt'):
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
                    'metacritic': 'metacritic'}
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


def load_scored_cover(path, score, max_width, max_height, master=None):
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Juegos Torrent 2.6.7')
        self.geometry('1280x800')
        try:
            self.state('zoomed')  # Maximizada en Windows, sin ocultar la barra de tareas.
        except tk.TclError:
            pass
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
        self.after(120, self.process_asset_events)
        self.games = []
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
        self.sort_mode = tk.StringVar(value='Incorporación (recientes)')
        self.game_metadata = {}
        self.search.trace_add('write', lambda *_: self.render_games())

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
        tk.Button(top, text='Actualizar catálogo', command=self.load_catalog, bg=CARD, fg=FG,
                  activebackground=PANEL, activeforeground=FG, relief='flat', padx=12, pady=8).pack(side='right')
        # Buscador: lupa dibujada en Tkinter y pista visual que no entra en la búsqueda.
        search_area = tk.Frame(top, bg=PANEL, height=39)
        search_area.pack(side='right', padx=15)
        search_area.pack_propagate(False)
        search_area.configure(width=325)
        search_icon = tk.Canvas(search_area, width=29, height=36, bg=PANEL,
                                highlightthickness=0, bd=0)
        search_icon.pack(side='left', padx=(8, 0))
        search_icon.create_oval(6, 9, 18, 21, outline=ACCENT, width=2)
        search_icon.create_line(17, 20, 24, 27, fill=ACCENT, width=2, capstyle='round')
        searchbox = tk.Entry(search_area, textvariable=self.search, font=('Segoe UI', 12),
                             bg=PANEL, fg=FG, insertbackground=FG, relief='flat', bd=0)
        searchbox.pack(side='left', fill='both', expand=True, padx=(5, 10), pady=8)
        hint = tk.Label(searchbox, text='Buscar juegos...', fg=MUTED, bg=PANEL,
                        font=('Segoe UI', 11), cursor='xterm')
        hint.place(x=2, rely=0.5, anchor='w')
        hint.bind('<Button-1>', lambda _: searchbox.focus_set())
        search_icon.bind('<Button-1>', lambda _: searchbox.focus_set())
        self.search.trace_add('write', lambda *_: hint.place_forget() if self.search.get() else hint.place(x=2, rely=0.5, anchor='w'))

        body = tk.PanedWindow(self, orient='horizontal', bg=BG, sashwidth=6, bd=0)
        body.pack(fill='both', expand=True, padx=18, pady=(0, 10))
        left = tk.Frame(body, bg=BG)
        right = tk.Frame(body, bg=PANEL, width=680)
        body.add(left, stretch='always', minsize=360)
        body.add(right, minsize=490)
        # Cinco tarjetas (~190 px cada una) cuando la pantalla lo permite.
        # Si falta ancho, se prioriza el mínimo del panel derecho y el grid se adapta.
        def set_initial_split():
            width = body.winfo_width()
            if width > 1100:
                left_width = min(980, width - 500)
                body.sash_place(0, max(370, left_width), 1)
        self.after(180, set_initial_split)

        # Selectores integrados, a la derecha y con la paleta de Juegos Torrent.
        filters = tk.Frame(left, bg=BG)
        filters.pack(fill='x', padx=(0, 9), pady=(0, 9))
        filter_style = ttk.Style(self)
        if 'clam' in filter_style.theme_names():
            filter_style.theme_use('clam')
        filter_style.configure('JuegosFiltro.TCombobox',
                               fieldbackground=CARD, background=CARD,
                               foreground=FG, arrowcolor=ACCENT,
                               bordercolor=ACCENT, lightcolor=CARD,
                               darkcolor=CARD, selectbackground=CARD,
                               selectforeground=FG, padding=(9, 7),
                               relief='flat', font=('Segoe UI', 10))
        filter_style.map('JuegosFiltro.TCombobox',
                         fieldbackground=[('readonly', CARD)],
                         foreground=[('readonly', FG)],
                         background=[('readonly', CARD), ('active', PANEL)],
                         arrowcolor=[('readonly', ACCENT), ('active', ACCENT)],
                         selectbackground=[('readonly', CARD)],
                         selectforeground=[('readonly', FG)])
        self.option_add('*TCombobox*Listbox.background', CARD)
        self.option_add('*TCombobox*Listbox.foreground', FG)
        self.option_add('*TCombobox*Listbox.selectBackground', ACCENT)
        self.option_add('*TCombobox*Listbox.selectForeground', BG)
        self.genre_display = tk.StringVar(value='Todos los géneros')
        self.sort_display = tk.StringVar(value='Incorporación (recientes)')
        sort_options = ['Nombre (A-Z)', 'Nombre (Z-A)', 'Año (más recientes)',
                        'Año (más antiguos)', 'Incorporación (recientes)',
                        'Incorporación (antiguos)', 'Tamaño (mayor)', 'Tamaño (menor)',
                        'Mejor puntuación']
        self.sort_combo = ttk.Combobox(filters, textvariable=self.sort_display,
                                       state='readonly', width=28,
                                       style='JuegosFiltro.TCombobox',
                                       values=sort_options)
        self.sort_combo.pack(side='right')
        self.sort_combo.bind('<<ComboboxSelected>>', self.on_sort_selected)
        self.genre_combo = ttk.Combobox(filters, textvariable=self.genre_display,
                                        state='readonly', width=25,
                                        style='JuegosFiltro.TCombobox',
                                        values=['Todos los géneros'])
        self.genre_combo.pack(side='right', padx=(0, 12))
        self.genre_combo.bind('<<ComboboxSelected>>', self.on_genre_selected)


        self.canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(left, orient='vertical', command=self.canvas.yview)
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
        detail_scroll = ttk.Scrollbar(right, orient='vertical', command=detail_canvas.yview)
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
        self.welcome_png_path = ASSETS / 'bienvenida_flyer.png'
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

        # Cabecera gráfica adaptable al ancho real del panel derecho.
        # Se mantiene el archivo PNG externo para intercambiar diseños libremente.
        self.ficha_header_path = ASSETS / 'ficha_titulo_gaming.png'
        self.ficha_header_original = None
        self.ficha_header_image = None
        if Image is not None and ImageTk is not None and self.ficha_header_path.is_file():
            try:
                with Image.open(self.ficha_header_path) as source:
                    self.ficha_header_original = source.convert('RGBA')
            except (OSError, ValueError):
                logging.exception('No se pudo abrir la imagen de cabecera')
        self.ficha_header = tk.Canvas(detail_frame, bg='#20372f', height=57,
                                      highlightthickness=0, bd=0)
        self.ficha_header.pack(fill='x', padx=0, pady=(0, 15))
        self.ficha_header.bind('<Configure>', self.redraw_ficha_header)
        self.detail_title = tk.Label(detail_frame, text='', fg=FG, bg=PANEL,
                                     wraplength=630, justify='center', font=('Segoe UI', 16, 'bold'))
        self.detail_title.pack(fill='x', padx=18, pady=(0, 6))
        self.detail_type = tk.Label(detail_frame, text='', fg=MUTED, bg=PANEL,
                                    wraplength=630, justify='center', font=('Segoe UI', 10))
        self.detail_type.pack(anchor='center', padx=18, pady=(0, 12))

        # Una sola fila: carátula a la izquierda, capturas a la derecha.
        # Este contenedor permanece en el mismo lugar aunque cambiemos de juego.
        self.media_row = tk.Frame(detail_frame, bg=PANEL)
        self.media_row.pack(fill='x', padx=18, pady=(0, 12))
        self.cover_area = tk.Frame(self.media_row, bg=PANEL, width=235, height=325)
        self.cover_area.pack(side='left', anchor='n', padx=(0, 14))
        self.cover_area.pack_propagate(False)
        self.detail_cover = tk.Label(self.cover_area, text='Seleccioná una carátula',
                                     fg=MUTED, bg=CARD, font=('Segoe UI', 11), cursor='hand2')
        self.detail_cover.pack(expand=True)
        self.detail_cover.bind('<Button-1>', lambda _: self.open_cover_preview())

        self.screenshots_column = tk.Frame(self.media_row, bg=PANEL)
        self.screenshots_column.pack(side='left', fill='both', expand=True, anchor='n')
        self.screenshots_title = tk.Label(self.screenshots_column, text='', fg=ACCENT, bg=PANEL,
                                          font=('Segoe UI', 11, 'bold'))
        self.screenshots_title.pack(anchor='w', pady=(0, 7))
        self.screenshots_frame = tk.Frame(self.screenshots_column, bg=PANEL)
        self.screenshots_frame.pack(fill='x')
        self.screenshots_column.bind('<Configure>', self.on_gallery_resize)
        # Barra opcional de datos rápidos, debajo de las capturas.
        self.info_bar = tk.Frame(self.screenshots_column, bg=CARD, padx=10, pady=9)
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


        # Sinopsis local: ocupa el ancho completo, debajo de las imágenes.
        # Se oculta por completo cuando el juego no tiene TXT.
        self.synopsis_area = tk.Frame(detail_frame, bg=PANEL)
        self.synopsis_heading = tk.Label(self.synopsis_area, text='SINOPSIS', fg=ACCENT,
                                         bg=PANEL, font=('Segoe UI', 11, 'bold'))
        self.synopsis_heading.pack(anchor='w', pady=(0, 7))
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

        # Estilo exclusivo de las pestañas: mantiene el tema oscuro de Juegos Torrent.
        # El tema clam permite personalizar los colores en Windows (vista suele ignorarlos).
        style = ttk.Style(self)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        style.configure('Juegos.TNotebook', background=PANEL, borderwidth=0,
                        relief='flat', tabmargins=(0, 4, 0, 0))
        style.configure('Juegos.TNotebook.Tab', background='#303d50', foreground=FG,
                        font=('Segoe UI', 11, 'bold'), padding=(16, 10),
                        borderwidth=0, relief='flat', focuscolor=PANEL)
        style.map('Juegos.TNotebook.Tab',
                  background=[('selected', ACCENT), ('active', '#40546b')],
                  foreground=[('selected', '#102018'), ('active', FG)],
                  padding=[('selected', (16, 10))])

        # El botón contextual se superpone a la derecha de la fila de pestañas.
        # No crea otra fila ni desplaza el Notebook hacia abajo.

        # Pestañas: las instrucciones y los enlaces TXT se leen dentro de JUEGOS.
        tabs = ttk.Notebook(detail_frame, style='Juegos.TNotebook')
        tabs.pack(fill='both', expand=True, padx=12, pady=(12, 16))
        self.tabs = tabs
        self.downloads_tab = tk.Frame(tabs, bg=PANEL)
        self.instructions_tab = tk.Frame(tabs, bg=PANEL)
        tabs.add(self.downloads_tab, text='Descargas')
        tabs.add(self.instructions_tab, text='Instrucciones / enlaces')
        # ttk.Notebook cambia de pestaña con la rueda por defecto en algunos temas.
        # Aquí la rueda desplaza la ficha, y solo un clic cambia de pestaña.
        tabs.bind('<MouseWheel>', self.scroll_over_tabs)

        # Botón de descarga discreto: fondo oscuro, icono verde y texto claro.
        # Conserva self.download_button para no alterar la lógica existente.
        download_surface = tk.Frame(self.downloads_tab, bg=CARD, height=58, cursor='hand2')
        download_surface.pack(fill='x', padx=8, pady=(10, 12))
        download_surface.pack_propagate(False)
        download_content = tk.Frame(download_surface, bg=CARD)
        download_content.place(relx=0.5, rely=0.5, anchor='center')
        # Icono PNG transparente con flecha y bandeja (sin depender de fuentes).
        self.download_icon_photo = load_local_image(DOWNLOAD_ICON, 22, 22, master=self)
        if self.download_icon_photo is not None:
            download_icon = tk.Label(download_content, image=self.download_icon_photo,
                                     bg=CARD, bd=0, cursor='hand2')
        else:
            download_icon = tk.Label(download_content, text='↓', fg=ACCENT, bg=CARD,
                                     font=('Segoe UI', 17, 'bold'), cursor='hand2')
        download_icon.pack(side='left', padx=(0, 9))
        self.download_button = tk.Button(download_content, text='Descargar juego', state='normal',
                                         command=self.download_selected, bg=CARD, fg=FG,
                                         activebackground=CARD, activeforeground=FG,
                                         relief='flat', bd=0, highlightthickness=0, padx=0, pady=0,
                                         cursor='hand2', font=('Segoe UI', 11, 'bold'))
        self.download_button.pack(side='left')
        download_surface.bind('<Button-1>', lambda _: self.download_button.invoke())
        download_content.bind('<Button-1>', lambda _: self.download_button.invoke())
        download_icon.bind('<Button-1>', lambda _: self.download_button.invoke())
        self.guide_button = tk.Button(detail_frame, text='Ver instrucciones  →',
                                      command=self.open_selected_guide, bg=CARD, fg=FG,
                                      activebackground='#303d50', activeforeground=FG,
                                      relief='flat', padx=14, pady=7, cursor='hand2',
                                      font=('Segoe UI', 10, 'bold'))
        self.guide_button.place_forget()
        self.extras_title = tk.Label(self.downloads_tab, text='', fg=ACCENT, bg=PANEL,
                                     font=('Segoe UI', 12, 'bold'))
        self.extras_title.pack(anchor='w', padx=8, pady=(12, 4))
        self.extras_frame = tk.Frame(self.downloads_tab, bg=PANEL)
        self.extras_frame.pack(fill='x', padx=8, pady=(0, 20))

        self.text_heading = tk.Label(self.instructions_tab, text='Seleccioná un juego y sus instrucciones.',
                                     fg=ACCENT, bg=PANEL, anchor='w', justify='left', wraplength=280,
                                     font=('Segoe UI', 11, 'bold'))
        self.text_heading.pack(fill='x', padx=8, pady=(12, 8))
        text_container = tk.Frame(self.instructions_tab, bg=PANEL)
        text_container.pack(fill='both', expand=True, padx=8, pady=(0, 10))
        self.text_view = tk.Text(text_container, wrap='word', height=15, bg=BG, fg=FG,
                                 insertbackground=FG, relief='flat', padx=10, pady=10,
                                 font=('Consolas', 10), state='disabled')
        text_scroll = ttk.Scrollbar(text_container, orient='vertical', command=self.text_view.yview)
        self.text_view.configure(yscrollcommand=text_scroll.set)
        text_scroll.pack(side='right', fill='y')
        self.text_view.pack(side='left', fill='both', expand=True)
        tk.Button(self.instructions_tab, text='Copiar texto', command=self.copy_text,
                  bg=CARD, fg=FG, relief='flat', pady=7).pack(fill='x', padx=8, pady=(0, 10))

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
        self.sync_progress = ttk.Progressbar(self.sync_box, orient='horizontal',
                                             mode='determinate', maximum=100)
        self.sync_progress.pack(fill='x', pady=(3, 0))
        # Se muestra únicamente cuando hay archivos pendientes.
        tk.Label(status_bar, text='MaelstromxXx & ChatGPT', bg=BG, fg='#728296',
                 anchor='e', font=('Segoe UI', 8)).pack(side='right', padx=(12, 0))
        self.load_catalog()
        self.load_remote_manifest()

    def redraw_ficha_header(self, event=None):
        """Ajusta el PNG a todo el ancho de la ficha, también al mover el divisor."""
        canvas = self.ficha_header
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 2 or height < 2:
            return
        canvas.delete('all')
        if self.ficha_header_original is not None and ImageTk is not None:
            # Escalado independiente de ancho y alto: sin franjas laterales.
            # La altura es constante; el ancho sigue al panel automáticamente.
            resized = self.ficha_header_original.resize((width, height), Image.Resampling.LANCZOS)
            self.ficha_header_image = ImageTk.PhotoImage(resized, master=self)
            canvas.create_image(0, 0, image=self.ficha_header_image, anchor='nw')
        else:
            # Fallback nativo si Pillow no está instalado. Tkinter no admite
            # escalado arbitrario; se rellena el ancho con un fondo integrado.
            if self.ficha_header_path.is_file():
                try:
                    original = tk.PhotoImage(file=str(self.ficha_header_path), master=self)
                    # zoom/subsample permite aproximar la anchura sin Pillow.
                    from math import gcd
                    scale_gcd = gcd(width, original.width())
                    numerator = min(12, max(1, round(width / max(1, original.width()) * 6)))
                    scaled = original.zoom(numerator).subsample(6)
                    if scaled.width() > width:
                        scaled = scaled.subsample(max(1, (scaled.width() + width - 1) // width))
                    self.ficha_header_image = scaled
                    canvas.create_image(width // 2, height // 2, image=scaled, anchor='center')
                except tk.TclError:
                    canvas.create_text(width // 2, height // 2, text='FICHA DEL JUEGO',
                                       fill=ACCENT, font=('Impact', 19))
            else:
                canvas.create_text(width // 2, height // 2, text='FICHA DEL JUEGO',
                                   fill=ACCENT, font=('Impact', 19))
        canvas.create_line(0, height - 1, width, height - 1, fill=ACCENT, width=2)

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
        self.canvas.itemconfigure(self.canvas_window, width=event.width)
        columns = max(1, event.width // 180)
        if columns != self.last_columns:
            self.last_columns = columns
            self.render_games()

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
            for game_name, label in list(self.cover_cards.items()):
                if any(Path(p).stem in image_stems(game_name) for p in cover_paths):
                    score = game_score(self.game_metadata.get(game_name, {}))
                    photo = load_scored_cover(find_cover(game_name), score, 140, 185, master=self)
                    label.config(image=photo if photo is not None else '',
                                 text='' if photo else 'SIN\nCARÁTULA',
                                 width=0 if photo else 17,
                                 height=0 if photo else 10)
                    label.image = photo
        if any(p.startswith('datos/') and p.lower().endswith('.txt') for p in changed):
            self.render_games()
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
                self.show_game_data(game)
            if any(p.startswith('sinopsis/') and Path(p).stem in stems for p in changed):
                self.show_synopsis(game)

    def load_catalog(self):
        self.status.config(text='Consultando catálogo remoto de Google Drive...')

        def work():
            try:
                request = Request(CATALOG_URL, headers={'User-Agent': 'Mozilla/5.0'})
                with urlopen(request, timeout=18) as response:
                    content = response.read(5_000_001)
                if len(content) > 5_000_000:
                    raise ValueError('El catálogo supera el tamaño máximo permitido.')
                raw = content.decode('utf-8-sig')
                if re.search(r'<html|<!doctype', raw, re.I):
                    raise ValueError('Google Drive devolvió una página HTML en lugar del TXT.')
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
        self.games = group_catalog(games)
        self.selected = None
        self.download_button.config(state='disabled')
        self.guide_button.place_forget()
        self.show_text('Seleccioná un juego', 'Las instrucciones aparecerán aquí cuando las solicites.')
        summary = f'{len(self.games)} juegos y {len(games) - len(self.games)} complementos.'
        if offline:
            self.status.config(text='SIN CONEXIÓN · Catálogo local cargado: ' + summary)
        else:
            self.status.config(text='Catálogo actualizado desde Google Drive: ' + summary)
        self.render_games()
        self.schedule_remote_assets()

    def catalog_failed(self, msg):
        self.status.config(text='No se pudo cargar el catálogo. Probá con «Actualizar catálogo».')
        messagebox.showerror('JUEGOS - Error de conexión', msg)

    def load_cover(self, name, max_width, max_height):
        return load_local_image(find_cover(name), max_width, max_height, master=self)

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
        self.screenshots_title.config(text=f'CAPTURAS ({len(self.current_shots)})'
                                      if self.current_shots else 'SIN CAPTURAS')
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
        if any(data.get(key) for key in self.info_values):
            self.info_bar.pack(fill='x', pady=(12, 0))
        else:
            self.info_bar.pack_forget()

    def on_detail_resize(self, event):
        # El texto acompaña al ancho disponible al redimensionar la ventana.
        self.synopsis_label.config(wraplength=max(230, event.width - 52))
        self.detail_title.config(wraplength=max(230, event.width - 52))
        self.detail_type.config(wraplength=max(230, event.width - 52))

    def show_synopsis(self, game):
        self.synopsis_full = find_synopsis(game['name'])
        self.synopsis_expanded = False
        if not self.synopsis_full:
            self.synopsis_area.pack_forget()
            return
        self.synopsis_area.pack(fill='x', padx=18, pady=(2, 12), before=self.tabs)
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
        elif mode.startswith('Incorporación'):
            reverse = mode == 'Incorporación (recientes)'
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

    def render_games(self):
        if not hasattr(self, 'grid_frame'):
            return
        for widget in self.grid_frame.winfo_children():
            widget.destroy()
        self.images = []
        self.cover_cards = {}
        self.refresh_classification()
        text = self.search.get().strip().casefold()
        genre = self.genre_filter.get().casefold()
        filtered = [g for g in self.games
                    if (text in g['name'].casefold() or any(text in e['name'].casefold() for e in g['extras']))
                    and (genre == 'todos los géneros' or genre in
                         [x.casefold() for x in _genres(self.game_metadata.get(g['name'], {}).get('genero', ''))])]
        filtered = self.sort_games(filtered)
        cols = max(1, self.last_columns or 3)
        for i, game in enumerate(filtered):
            card = tk.Frame(self.grid_frame, bg=CARD, padx=8, pady=8, cursor='hand2')
            card.grid(row=i // cols, column=i % cols, padx=8, pady=8, sticky='n')
            score = game_score(self.game_metadata.get(game['name'], {}))
            photo = load_scored_cover(find_cover(game['name']), score, 140, 185, master=self)
            if photo:
                self.images.append(photo)
                cover = tk.Label(card, image=photo, bg=CARD, cursor='hand2')
            else:
                cover = tk.Label(card, text='SIN\nCARÁTULA', fg=MUTED, bg=PANEL,
                                 width=17, height=10, font=('Segoe UI', 11, 'bold'), cursor='hand2')
            cover.pack()
            self.cover_cards[game['name']] = cover
            title = tk.Label(card, text=split_game_title(game['name'])[0], fg=FG, bg=CARD,
                             wraplength=145, width=20, height=3,
                             font=('Segoe UI', 9), cursor='hand2')
            title.pack(pady=(7, 0))
            for widget in (card, cover, title):
                widget.bind('<Button-1>', lambda _, g=game: self.select_game(g))
        if not filtered:
            tk.Label(self.grid_frame, text='No se encontraron juegos.', fg=MUTED, bg=BG,
                     font=('Segoe UI', 12)).grid(padx=20, pady=30)
        self.status.config(text=f'Mostrando {len(filtered)} de {len(self.games)} juegos · {sum(len(g["extras"]) for g in self.games)} complementos agrupados')

    def select_game(self, game):
        # Primera selección: retiramos la bienvenida y dejamos la ficha intacta.
        if self.welcome.winfo_manager():
            self.welcome.place_forget()
        self.selected = game
        clean_title, extra_info = split_game_title(game['name'])
        self.detail_title.config(text=clean_title)
        self.download_button.config(state='disabled' if self.busy else 'normal',
                                    text=self.action_label(game, complement=False))
        self.guide_button.place_forget()
        self.text_request += 1
        self.show_text('Instrucciones / enlaces', 'Elegí «Ver instrucciones» o «Ver enlaces de descarga» para leer un TXT aquí.')
        self.tabs.select(self.downloads_tab)
        if game.get('guide'):
            # Alineado verticalmente con Descargas / Instrucciones.
            self.guide_button.place(in_=self.tabs, relx=1.0, x=-8, y=4, anchor='ne')
            self.guide_button.lift()
        self.detail_type.config(text=extra_info)
        if extra_info:
            self.detail_type.pack(anchor='center', padx=18, pady=(0, 12))
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
            tk.Label(self.extras_frame, text=extra['name'], fg=FG, bg=CARD,
                     wraplength=285, justify='left', anchor='w', padx=10, pady=7,
                     font=('Segoe UI', 10)).pack(fill='x', pady=(7, 0))
            tk.Button(self.extras_frame, text=self.action_label(extra, complement=True),
                      command=lambda e=extra: self.run_entry(e), state='disabled' if self.busy else 'normal',
                      bg=ACCENT, fg='#102018', relief='flat').pack(fill='x', pady=(0, 3))
            if extra.get('guide'):
                tk.Button(self.extras_frame, text='Abrir instrucciones',
                          command=lambda e=extra: self.run_guide(e),
                          bg=CARD, fg=FG, relief='flat').pack(fill='x', pady=(0, 3))


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

    def show_text(self, title, content):
        self.text_heading.config(text=title)
        self.text_view.config(state='normal')
        self.text_view.delete('1.0', 'end')
        self.text_view.insert('1.0', content)
        self.text_view.config(state='disabled')
        self.text_view.yview_moveto(0)

    def copy_text(self):
        content = self.text_view.get('1.0', 'end-1c')
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
                    raise ValueError('El TXT es demasiado grande para mostrarlo.')
                raw = data.decode('utf-8-sig', errors='replace')
                if re.search(r'(?is)^\s*(?:<!doctype\s+html|<html|<head|<body)', raw):
                    raise ValueError('Google Drive devolvió una página HTML en lugar del TXT.')
                self.after(0, lambda: self.text_loaded(request_id, title, raw))
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda: self.text_failed(request_id, title, msg))
        threading.Thread(target=work, daemon=True).start()

    def text_loaded(self, request_id, title, raw):
        if request_id == self.text_request:
            self.show_text(title, raw)
            self.status.config(text='Texto cargado: ' + title)

    def text_failed(self, request_id, title, msg):
        if request_id == self.text_request:
            self.show_text(title, 'No se pudo cargar el TXT.\n\n' + msg)
            self.status.config(text='Error al cargar el TXT.')

    def run_entry(self, entry):
        if self.busy:
            messagebox.showinfo('JUEGOS', 'Esperá a que termine la descarga actual.')
            return
        kind = entry['type']
        if kind == 'txt':
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
        self.busy = True
        self.download_button.config(state='disabled')
        for child in self.extras_frame.winfo_children():
            if isinstance(child, tk.Button):
                child.config(state='disabled')
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


if __name__ == '__main__':
    App().mainloop()
