import json
import re
import shutil
import os
import tempfile
import subprocess
import sys
import shutil as shutil_browser
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import html
from html.parser import HTMLParser
import tkinter as tk
from pathlib import Path
from datetime import date
from urllib.parse import urlparse, parse_qs, unquote
from tkinter import filedialog, messagebox, ttk, simpledialog

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

def traducir_mymemory_directo(texto):
    """Consulta la API pública y verifica errores sin confundirlos con traducciones."""
    ultimo_error = None
    for idiomas in ('en|es', 'en-US|es-ES'):
        parametros = urllib.parse.urlencode({'q': texto, 'langpair': idiomas, 'mt': '1'})
        solicitud = urllib.request.Request(
            'https://api.mymemory.translated.net/get?' + parametros,
            headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(solicitud, timeout=22) as respuesta:
                datos = json.loads(respuesta.read().decode('utf-8'))
            codigo = int(datos.get('responseStatus') or 0)
            detalle = str(datos.get('responseDetails') or '').strip()
            traduccion = (datos.get('responseData') or {}).get('translatedText')
            if codigo == 200 and isinstance(traduccion, str) and traduccion.strip():
                # El servicio a veces devuelve mensajes de error en translatedText.
                if re.search(r'(language pair.*not supported|invalid language|too many requests|quota exceeded)', traduccion, re.I):
                    raise ValueError(traduccion)
                return html.unescape(traduccion)
            ultimo_error = detalle or f'MyMemory devolvió el estado {codigo}.'
            if not re.search(r'(language|idioma|langpair|not supported)', ultimo_error, re.I):
                break
        except Exception as exc:
            ultimo_error = str(exc)
            if not re.search(r'(language|idioma|langpair|not supported)', ultimo_error, re.I):
                break
    raise ValueError('MyMemory rechazó la solicitud: ' + str(ultimo_error))

def traducir_gemini(texto, api_key):
    """Traducción contextual con Gemini. No guarda ni registra la clave API."""
    # Consultar los modelos disponibles para ESTA clave, evitando nombres retirados.
    listado_url = 'https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000'
    listado_req = urllib.request.Request(listado_url, headers={
        'x-goog-api-key': api_key, 'Accept': 'application/json', 'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(listado_req, timeout=25) as respuesta:
            listado = json.load(respuesta)
    except urllib.error.HTTPError as exc:
        try:
            detalle = json.loads(exc.read().decode('utf-8')).get('error', {}).get('message', '')
        except Exception:
            detalle = ''
        raise ValueError(f'No se pudo consultar la lista de modelos (HTTP {exc.code}). {detalle}') from None
    disponibles = {m.get('name', '').removeprefix('models/') for m in listado.get('models', [])
                   if 'generateContent' in m.get('supportedGenerationMethods', [])}
    preferidos = ('gemini-3-flash', 'gemini-3-flash-preview', 'gemini-3.8-flash',
                  'gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.0-flash')
    modelo = next((m for m in preferidos if m in disponibles), None)
    if not modelo:
        raise ValueError('No se encontró un modelo Flash compatible con esta clave. '
                         'Modelos disponibles: ' + ', '.join(sorted(disponibles)[:20]))
    url = ('https://generativelanguage.googleapis.com/v1beta/models/'
           + modelo + ':generateContent')
    instrucciones = (
        'Traducí al español de Argentina el texto de una ficha de videojuego. '
        'Devolvé ÚNICAMENTE la traducción, sin comentarios, comillas ni Markdown adicional. '
        'Conservá exactamente los saltos de línea, párrafos, viñetas y estructura. '
        'No traduzcas nombres propios de videojuegos, DLC, ediciones, packs, grupos de cracks, '
        'repackers, versiones, rutas, archivos, comandos, URLs ni etiquetas técnicas. '
        'Conservá también cualquier marcador KALAKAPROTECT sin modificar. '
        'Si un fragmento ya está en español, mantenelo. '
        'Traducí por significado y contexto, no palabra por palabra. '
        'Las instrucciones de instalación suelen estar redactadas en inglés telegráfico: '
        'resolvé expresiones elípticas o poco naturales en español sin inventar pasos ni datos. '
        'Por ejemplo, cuando una lista de actualizaciones termina en «installed over», '
        'interpretá que esas actualizaciones ya fueron aplicadas a la instalación base; '
        'podés redactarlo como «Dos actualizaciones aplicadas: ...», en vez de dejar '
        'la frase incompleta «instaladas sobre». '
        'Conservá el sentido y el estado de las acciones (ya realizadas frente a instrucciones futuras). '
        'No agregues información que el original no afirma. '
        'Priorizá una traducción natural, precisa y fiel al contexto de videojuegos.'
    )
    payload = json.dumps({
        'systemInstruction': {'parts': [{'text': instrucciones}]},
        'contents': [{'role': 'user', 'parts': [{'text': texto}]}],
        'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 8192}
    }).encode('utf-8')
    solicitud = urllib.request.Request(url, data=payload, method='POST', headers={
        'Content-Type': 'application/json', 'x-goog-api-key': api_key,
        'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(solicitud, timeout=90) as respuesta:
            datos = json.loads(respuesta.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            detalle = json.loads(exc.read().decode('utf-8')).get('error', {}).get('message', '')
        except Exception:
            detalle = ''
        raise ValueError(f'Gemini devolvió HTTP {exc.code}. {detalle}') from None
    candidatos = datos.get('candidates') or []
    if not candidatos:
        raise ValueError('Gemini no devolvió ninguna traducción.')
    partes = (candidatos[0].get('content') or {}).get('parts') or []
    resultado = ''.join(parte.get('text', '') for parte in partes)
    if not resultado.strip():
        raise ValueError('Gemini devolvió una respuesta vacía.')
    if candidatos[0].get('finishReason') == 'MAX_TOKENS':
        raise ValueError('La respuesta de Gemini quedó incompleta por límite de tokens.')
    return resultado

# Sufijos comerciales que no suelen formar parte del nombre base en Steam.
# Solo se quitan del FINAL y nunca se altera el título del catálogo.
EDICIONES_STEAM = (
    'Premium Edition', 'Deluxe Edition', 'Ultimate Edition',
    'Complete Edition', 'Definitive Edition', 'Gold Edition',
    'Digital Deluxe Edition', 'Special Edition', 'Collector\'s Edition',
    'Game of the Year Edition', 'GOTY Edition', 'GOTY',
    'Enhanced Edition', 'Legendary Edition', 'Anniversary Edition',
    'Director\'s Cut', 'Remastered Edition',
)

def nombre_base_juego(titulo):
    """Nombre de recursos: omite los metadatos finales entre corchetes."""
    titulo = titulo.strip()
    return re.sub(r'\s+\[[^\]\r\n]*\]\s*$', '', titulo).strip()

def simplificar_titulo_steam(titulo):
    """Devuelve un nombre base para búsqueda de respaldo, sin alterar el original."""
    actual = titulo.strip()
    while True:
        anterior = actual
        for edicion in sorted(EDICIONES_STEAM, key=len, reverse=True):
            patron = r'(?i)(?:\s*[-–—:|]\s*|\s+)'+re.escape(edicion)+r'\s*$'
            actual = re.sub(patron, '', actual).strip(' -–—:|')
            if actual != anterior:
                break
        if actual == anterior:
            break
    return actual if actual and actual.casefold() != titulo.strip().casefold() else None

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

def extraer_updates_fitgirl(contenido_html):
    """Extrae enlaces de updates sin exigir extensión en el texto visible.

    El HTML puede mostrar títulos como 'Update 1.02', enlaces FileCrypt,
    mirrors o nombres de archivos. Se ignoran referencias a las fuentes.
    """
    encabezado = re.search(
        r'<h[2-4]\b[^>]*>\s*Game\s+Updates\s*(?:&#8211;|&#x2013;|&ndash;|–|-)\s*Direct\s+Links\s+only\s*</h[2-4]>',
        contenido_html, re.I)
    if not encabezado:
        raise ValueError('No se encontró la sección Game Updates – Direct Links only.')
    siguiente = re.search(r'<h[2-4]\b', contenido_html[encabezado.end():], re.I)
    segmento = contenido_html[encabezado.end():encabezado.end() + siguiente.start()] if siguiente else contenido_html[encabezado.end():]
    resultados, vistos = [], set()
    # FitGirl usa tanto listas <li> como enlaces sueltos separados por <br>.
    # Limitamos la lectura al primer contenedor de la sección para no recoger
    # enlaces de descargas del repack ni otras partes de la página.
    contenedor_html = re.search(r'<div\b[^>]*>(.*?)</div\s*>', segmento, re.I | re.S)
    bloque = contenedor_html.group(1) if contenedor_html else segmento
    items = re.findall(r'<li\b[^>]*>(.*?)(?=<li\b|</ol>|</ul>|$)', bloque, re.I | re.S)
    if not items:
        items = [bloque]  # Enlaces directos sin <li>, como Need for Speed Unbound.
    for item in items:
        # Eliminar únicamente la referencia Source (no el resto del bloque).
        item = re.sub(r'\(\s*Source\s*:\s*(?:<a\b[^>]*>.*?</a>|[^)]*)\s*\)',
                      '', item, flags=re.I | re.S)
        enlaces = re.findall(r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', item, re.I | re.S)
        for direccion, etiqueta in enlaces:
            url = html.unescape(direccion).strip()
            nombre = clean_html(etiqueta).strip()
            destino = urllib.parse.urlparse(url)
            if destino.scheme not in ('http', 'https') or not destino.netloc or not nombre:
                continue
            if re.search(r'^(?:source|scene|elamigos|website|homepage|cs\.rin\.ru)$', nombre, re.I):
                continue
            # Dentro del contenedor de actualizaciones, los enlaces de
            # descarga no necesitan llevar la palabra Update/Patch.
            if url not in vistos:
                vistos.add(url)
                resultados.append((nombre, url))
    if not resultados:
        raise ValueError('La sección existe, pero no contiene enlaces de actualizaciones reconocibles. Probá con HTML guardado para revisar el formato.')
    return resultados

def extraer_titulo_fitgirl(contenido_html):
    """Obtiene el título de la entrada, sin los datos técnicos del repack."""
    match = re.search(r'<h1\b[^>]*class=["\'][^"\']*\bentry-title\b[^"\']*["\'][^>]*>(.*?)</h1>', contenido_html, re.I | re.S)
    if match:
        titulo = clean_html(match.group(1))
    else:
        match = re.search(r'<meta\b[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)', contenido_html, re.I | re.S)
        titulo = html.unescape(match.group(1)) if match else ''
    titulo = re.sub(r'\s*[-–—]\s*FitGirl Repacks\s*$', '', titulo, flags=re.I)
    # El corte se hace solamente ante el inicio de datos técnicos,
    # para conservar subtítulos con guiones en el nombre del juego.
    titulo = re.split(r'\s+[-–—]\s+(?=(?:v\s*\d|build\s*\d|update\s*\d|all\s+dlcs|repack\b|\d{4}\s*\+))', titulo, maxsplit=1, flags=re.I)[0]
    return titulo.strip()


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


# Drive: solo lectura de metadatos. Nunca se suben, borran ni editan archivos.
DRIVE_SCOPE = ['https://www.googleapis.com/auth/drive.metadata.readonly']
DRIVE_TOKEN = Path.home() / '.kalakas_drive_token.json'


def conectar_drive(credenciales_json):
    """OAuth de escritorio; el JSON y el token permanecen en esta computadora."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request, AuthorizedSession
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise RuntimeError('Faltan bibliotecas de Google. Instalá con: py -m pip install google-auth google-auth-oauthlib requests') from exc
    credenciales = None
    if DRIVE_TOKEN.is_file():
        try:
            credenciales = Credentials.from_authorized_user_file(str(DRIVE_TOKEN), DRIVE_SCOPE)
        except Exception:
            credenciales = None
    if credenciales and credenciales.expired and credenciales.refresh_token:
        try:
            credenciales.refresh(Request())
        except Exception:
            credenciales = None
    if not credenciales or not credenciales.valid:
        archivo = Path(credenciales_json).expanduser()
        if not archivo.is_file():
            raise ValueError('Seleccioná el JSON de cliente OAuth descargado desde Google Cloud.')
        flow = InstalledAppFlow.from_client_secrets_file(str(archivo), DRIVE_SCOPE)
        credenciales = flow.run_local_server(port=0, open_browser=True, authorization_prompt_message='Abrí esta dirección si el navegador no se abrió: {url}', success_message='Kalaka\'s Soft: autorización completada. Podés cerrar esta pestaña.')
    DRIVE_TOKEN.write_text(credenciales.to_json(), encoding='utf-8')
    try:
        DRIVE_TOKEN.chmod(0o600)
    except OSError:
        pass
    return AuthorizedSession(credenciales)


def drive_listar(sesion, consulta, campos='nextPageToken,files(id,name,mimeType,parents,webViewLink,modifiedTime)', limite=200):
    """Busca sin descargar contenido; admite paginación."""
    encontrados = []
    pagina = None
    while True:
        parametros = {'q': consulta, 'fields': campos, 'page_size': min(limite, 1000), 'spaces': 'drive'}
        if pagina:
            parametros['page_token'] = pagina
        respuesta = sesion.get('https://www.googleapis.com/drive/v3/files', params=parametros, timeout=25)
        respuesta.raise_for_status()
        datos = respuesta.json()
        encontrados.extend(datos.get('files', []))
        pagina = datos.get('nextPageToken')
        if not pagina:
            return encontrados


def drive_escapar(valor):
    return valor.replace(chr(92), chr(92) * 2).replace("'", chr(92) + "'")


def drive_buscar_archivos(sesion, carpeta_id, nombres):
    """Devuelve candidatos exactos por nombre dentro de la carpeta elegida."""
    encontrados = []
    for nombre in dict.fromkeys(nombres):
        if not nombre:
            continue
        q = f"trashed = false and '{drive_escapar(carpeta_id)}' in parents and name = '{drive_escapar(nombre)}'"
        encontrados.extend(drive_listar(sesion, q))
    return list({archivo['id']: archivo for archivo in encontrados}.values())


def drive_buscar_carpeta(sesion, nombre):
    q = "trashed = false and mimeType = 'application/vnd.google-apps.folder' and name = '" + drive_escapar(nombre) + "'"
    return drive_listar(sesion, q)


def centrar_ventana(ventana, ancho, alto):
    """Ubica una ventana Tk/Toplevel en el centro de la pantalla."""
    ventana.update_idletasks()
    pantalla_ancho = ventana.winfo_screenwidth()
    pantalla_alto = ventana.winfo_screenheight()
    ancho = min(ancho, pantalla_ancho)
    alto = min(alto, pantalla_alto)
    x = max(0, (pantalla_ancho - ancho) // 2)
    y = max(0, (pantalla_alto - alto) // 2)
    ventana.geometry(f'{ancho}x{alto}+{x}+{y}')


class Generador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Kalaka’s Soft - Generador v13.5.26 · Traducción Gemini')
        centrar_ventana(self, 1750, 900)
        self.minsize(1100, 680)
        try:
            self.configuracion = json.loads(CONFIG.read_text(encoding='utf-8'))
            if not isinstance(self.configuracion, dict): self.configuracion = {}
        except (OSError, ValueError):
            self.configuracion = {}
        self._gemini_api_key = (os.environ.get('GEMINI_API_KEY') or self.configuracion.get('GEMINI_API_KEY', '')).strip()
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
        self.ultimo_torrent_guardado = ''
        self.drive_credenciales = self.configuracion.get('DRIVE_CREDENTIALS', '')
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
            if seccion in ('SINOPSIS', 'INSTRUCCIONES'):
                ttk.Button(panel, text='🌐 TRADUCIR AL ESPAÑOL',
                           command=lambda sec=seccion, widget=caja: self.traducir_seccion(sec, widget)).grid(
                               row=6, column=0, sticky='w', pady=(7, 0))
        # Herramienta de extracción para el panel UPDATES.
        panel_updates = principal.grid_slaves(row=0, column=3)[0]
        ttk.Label(panel_updates, text='URL de la publicación de FitGirl:').grid(row=6, column=0, sticky='w', pady=(7, 0))
        self.url_updates = tk.StringVar()
        campo_url = ttk.Entry(panel_updates, textvariable=self.url_updates)
        campo_url.grid(row=7, column=0, sticky='ew', pady=3)
        self.menu_contextual(campo_url)
        fila_updates = ttk.Frame(panel_updates)
        fila_updates.grid(row=8, column=0, sticky='ew', pady=(2, 0))
        self.boton_extraer_updates = ttk.Button(fila_updates, text='Extraer updates desde URL', command=self.extraer_updates_url)
        self.boton_extraer_updates.pack(side='left', padx=(0, 5))
        ttk.Button(fila_updates, text='Probar con HTML guardado...', command=self.extraer_updates_archivo).pack(side='left')
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
        ttk.Button(acciones, text='CAMBIAR CLAVE GEMINI', command=self.cambiar_clave_gemini).pack(side='left', padx=8, ipadx=12, ipady=7)
        self.protocol('WM_DELETE_WINDOW', self.cerrar)

    def cambiar_clave_gemini(self):
        """Permite reemplazar la clave sin modificar el resto de la configuración."""
        clave = simpledialog.askstring(
            'Cambiar clave API de Gemini',
            'Pegá la nueva clave API de Google AI Studio.\\n'
            'Se guardará en la configuración local y reemplazará la anterior.',
            parent=self, show='*')
        if clave is None:
            return
        clave = clave.strip()
        if not clave:
            messagebox.showwarning('Clave API de Gemini',
                                   'La clave no puede estar vacía. No se modificó la anterior.',
                                   parent=self)
            return
        self._gemini_api_key = clave
        self.guardar_configuracion()
        messagebox.showinfo('Clave API de Gemini',
                            'La nueva clave se guardó en la configuración local.',
                            parent=self)

    def traducir_seccion(self, seccion, cuadro):
        """Vista previa editable con Gemini, MyMemory y Google."""
        original = cuadro.get('1.0', 'end-1c')
        if not original.strip():
            messagebox.showinfo('Traductor', f'El cuadro {seccion} está vacío.', parent=self)
            return
        ventana = tk.Toplevel(self)
        ventana.title(f'Traducir {seccion} al español — vista previa')
        centrar_ventana(ventana, 850, 640)
        ventana.transient(self)
        ventana.columnconfigure(0, weight=1)
        ventana.rowconfigure(2, weight=1)
        ttk.Label(ventana, text='Revisá y corregí la traducción antes de aplicarla.',
                  padding=10).grid(row=0, column=0, sticky='w')
        estado = tk.StringVar(value='Preparando traducción...')
        ttk.Label(ventana, textvariable=estado, padding=(10, 0)).grid(row=1, column=0, sticky='w')
        marco = ttk.Frame(ventana, padding=10)
        marco.grid(row=2, column=0, sticky='nsew')
        marco.rowconfigure(0, weight=1)
        marco.columnconfigure(0, weight=1)
        vista = tk.Text(marco, wrap='word', undo=True, font=('Segoe UI', 10))
        vista.grid(row=0, column=0, sticky='nsew')
        barra = ttk.Scrollbar(marco, orient='vertical', command=vista.yview)
        barra.grid(row=0, column=1, sticky='ns')
        vista.configure(yscrollcommand=barra.set)
        self.menu_contextual(vista)
        botones = ttk.Frame(ventana, padding=10)
        botones.grid(row=3, column=0, sticky='e')
        aplicar = ttk.Button(botones, text='APLICAR TRADUCCIÓN', state='disabled')
        aplicar.pack(side='left', padx=5)
        con_gemini = ttk.Button(botones, text='TRADUCIR CON GEMINI')
        con_gemini.pack(side='left', padx=5)
        con_mymemory = ttk.Button(botones, text='MYMEMORY')
        con_mymemory.pack(side='left', padx=5)
        reintentar = ttk.Button(botones, text='GOOGLE CLÁSICO')
        reintentar.pack(side='left', padx=5)
        ttk.Button(botones, text='Cancelar', command=ventana.destroy).pack(side='left', padx=5)

        def confirmar():
            texto = vista.get('1.0', 'end-1c')
            if not texto.strip():
                messagebox.showwarning('Traductor', 'La traducción está vacía.', parent=ventana)
                return
            if cuadro.get('1.0', 'end-1c') != original:
                if not messagebox.askyesno('Texto modificado',
                        'El texto original cambió mientras traducíamos. ¿Querés reemplazarlo igualmente?', parent=ventana):
                    return
            cuadro.delete('1.0', 'end')
            cuadro.insert('1.0', texto)
            ventana.destroy()
        aplicar.configure(command=confirmar)

        def trabajo(motor):
            if motor == 'Google':
                try:
                    from deep_translator import GoogleTranslator
                except ImportError:
                    self.after(0, lambda: terminar(None, 'Falta instalar deep-translator. Ejecutá: py -m pip install deep-translator', motor))
                    return
            try:
                # Evitar que se traduzcan direcciones, rutas y nombres de archivos.
                patron = re.compile(
                    r'https?://[^\s<>\]\[)]+|www\.[^\s<>]+|'
                    r'[A-Za-z]:\\[^\s\n]+|(?:\.\.?[/\\])[^\s\n]+|'
                    r'\b[\w.()+-]+\.(?:exe|dll|ini|cfg|bat|cmd|ps1|zip|rar|7z|iso|txt|md|torrent|dat|bin)\b',
                    re.IGNORECASE)
                protegidos = []
                def proteger(m):
                    i = len(protegidos)
                    protegidos.append(m.group(0))
                    return f' KALAKAPROTECT{i}END '
                seguro = patron.sub(proteger, original)
                # MyMemory: API directa, comprobando respuesta y códigos de idioma.
                # Google queda disponible como respaldo manual.
                traductor = GoogleTranslator(source='auto', target='es') if motor == 'Google' else None
                if motor == 'Gemini':
                    resultado = traducir_gemini(seguro, self._gemini_api_key)
                else:
                    resultado = None
                partes = re.split(r'(\n+)', seguro) if motor != 'Gemini' else []
                traducidas = []
                limite = 450 if motor == 'MyMemory' else 3500
                for parte in partes:
                    if not parte.strip() or parte.startswith('\n'):
                        traducidas.append(parte)
                        continue
                    fragmentos = []
                    restante = parte
                    while restante:
                        if len(restante) <= limite:
                            fragmentos.append(restante)
                            break
                        corte = max(restante.rfind('. ', 0, limite), restante.rfind(' ', 0, limite))
                        corte = limite if corte < 60 else corte + 1
                        fragmentos.append(restante[:corte])
                        restante = restante[corte:]
                    traducidas.append(''.join(traducir_mymemory_directo(t) if motor == 'MyMemory' else (traductor.translate(t) or t) for t in fragmentos))
                if motor != 'Gemini':
                    resultado = ''.join(traducidas)
                if motor == 'Gemini' and resultado.count('\n') != original.count('\n'):
                    raise ValueError('Gemini modificó la cantidad de saltos de línea. No se aplicó la traducción; probá dividir el texto.')
                for i, valor in enumerate(protegidos):
                    marcador = r'KALAKAPROTECT\s*' + str(i) + r'\s*END'
                    if not re.search(marcador, resultado, flags=re.IGNORECASE):
                        raise ValueError('El traductor alteró una ruta, URL o nombre de archivo protegido. No se aplicó ningún cambio.')
                    resultado = re.sub(marcador, lambda m, v=valor: v, resultado, flags=re.IGNORECASE)
                self.after(0, lambda: terminar(resultado, None, motor))
            except Exception as exc:
                self.after(0, lambda msg=str(exc): terminar(None, msg, motor))

        def iniciar(motor):
            if not ventana.winfo_exists():
                return
            if motor == 'Gemini' and not self._gemini_api_key:
                clave = simpledialog.askstring('Clave API de Gemini',
                    'Pegá tu clave API de Google AI Studio.\nSe guardará en la configuración local para las próximas sesiones.',
                    parent=ventana, show='*')
                if not clave or not clave.strip():
                    return
                self._gemini_api_key = clave.strip()
                self.guardar_configuracion()
            estado.set(f'Traduciendo con {motor}... (requiere Internet)')
            for boton in (con_gemini, con_mymemory, reintentar):
                boton.configure(state='disabled')
            threading.Thread(target=trabajo, args=(motor,), daemon=True).start()

        def terminar(resultado, error, motor):
            if not ventana.winfo_exists():
                return
            for boton in (con_gemini, con_mymemory, reintentar):
                boton.configure(state='normal')
            if error:
                estado.set(f'{motor} no pudo traducir. El texto original sigue intacto.')
                if motor == 'MyMemory':
                    messagebox.showwarning('Traductor MyMemory',
                        f'{error}\n\nPodés probar con Gemini o Google.', parent=ventana)
                else:
                    messagebox.showerror('Traductor ' + motor, error, parent=ventana)
                return
            vista.delete('1.0', 'end')
            vista.insert('1.0', resultado)
            estado.set(f'Traducción terminada con {motor}. Podés corregirla antes de aplicarla.')
            aplicar.configure(state='normal')
        reintentar.configure(command=lambda: iniciar('Google'))
        con_mymemory.configure(command=lambda: iniciar('MyMemory'))
        con_gemini.configure(command=lambda: iniciar('Gemini'))
        estado.set('Elegí Gemini, MyMemory o Google para traducir.')

    def abrir_steam(self):
        """Buscador opcional. Nunca modifica archivos hasta GUARDAR TODOS."""
        ventana = tk.Toplevel(self)
        ventana.title('Kalaka’s Soft · Importar metadatos de Steam')
        centrar_ventana(ventana, 980, 690)
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
            def consultar_steam():
                url = 'https://store.steampowered.com/api/storesearch/'
                base = simplificar_titulo_steam(texto)
                # Buscar primero el juego base: suele mostrar tanto el juego como sus ediciones.
                termino = base or texto
                originales = fetch_json(url, {'term': termino, 'l': 'spanish', 'cc': 'ar'}).get('items', []) or []
                if originales:
                    return originales, termino, bool(base)
                if base:
                    alternativos = fetch_json(url, {'term': texto, 'l': 'spanish', 'cc': 'ar'}).get('items', []) or []
                    return alternativos, texto, False
                return [], texto, False
            def mostrar_resultados(respuesta):
                items, termino, simplificada = respuesta
                establecer_resultados(items)
                if simplificada:
                    estado.set(f'Búsqueda por título base: "{termino}". '
                               f'{len(items)} resultados; seleccioná el juego. El título del catálogo no cambia.')
            tarea(consultar_steam, mostrar_resultados)

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
                # Evitar importar silenciosamente la ficha de otro juego si Steam
                # devuelve datos incompatibles con el resultado elegido.
                review_percent, diagnostico = obtener_valoracion_steam(appid)
                return info, review_percent, diagnostico
            def mostrar(resultado):
                info, review_percent, diagnostico = resultado
                seleccionado = resultados[seleccion[0]].get('name', '')
                nombre_devuelto = info.get('name', '')
                def normalizar_nombre(valor):
                    return re.sub(r'[^a-z0-9]+', '', valor.casefold())
                if (seleccionado and nombre_devuelto and
                    normalizar_nombre(seleccionado) != normalizar_nombre(nombre_devuelto) and
                    normalizar_nombre(nombre_devuelto) not in normalizar_nombre(seleccionado) and
                    normalizar_nombre(seleccionado) not in normalizar_nombre(nombre_devuelto)):
                    if not messagebox.askyesno('Steam: ficha diferente',
                        f'Seleccionaste: {seleccionado} (ID {appid})\n\n'
                        f'Steam devolvió la ficha: {nombre_devuelto}\n\n'
                        'Podría tratarse de un paquete o de un resultado incorrecto. '
                        '¿Querés mostrar igualmente estos datos? No se importarán automáticamente.',
                        parent=ventana):
                        estado.set('Ficha descartada: el nombre devuelto no coincide con el seleccionado.')
                        return
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
            # Respetar el título que el usuario eligió en el generador principal.
            if not self.nombre_juego.get().strip():
                self.nombre_juego.set(info.get('name', ''))
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
        centrar_ventana(ventana, 1320, 700)
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
        drive_panel = ttk.LabelFrame(izquierda, text=' GOOGLE DRIVE API · SOLO METADATOS ', padding=8)
        drive_panel.grid(row=14, column=0, sticky='ew', pady=(10, 0))
        drive_panel.columnconfigure(0, weight=1)
        carpeta_drive = tk.StringVar(value=self.configuracion.get('DRIVE_FOLDER', 'MiCatalogoRemoto'))
        ttk.Label(drive_panel, text='Nombre de carpeta en Drive (o ID de carpeta):').grid(row=0, column=0, sticky='w')
        campo_carpeta = ttk.Entry(drive_panel, textvariable=carpeta_drive)
        campo_carpeta.grid(row=1, column=0, sticky='ew', pady=(2, 5))
        self.menu_contextual(campo_carpeta)
        estado_drive = tk.StringVar(value='Seleccioná tu JSON OAuth una vez y luego obtené los IDs.')
        ttk.Label(drive_panel, textvariable=estado_drive, wraplength=400).grid(row=3, column=0, sticky='w', pady=(5, 0))
        fila_drive = ttk.Frame(drive_panel)
        fila_drive.grid(row=2, column=0, sticky='w')
        def elegir_json():
            ruta = filedialog.askopenfilename(parent=ventana, title='Elegir JSON OAuth de Google Cloud', filetypes=[('Credenciales OAuth', '*.json')])
            if ruta:
                self.drive_credenciales = ruta
                self.configuracion['DRIVE_CREDENTIALS'] = ruta
                self.guardar_configuracion()
                estado_drive.set('Credenciales seleccionadas. Ya podés consultar Drive.')
        ttk.Button(fila_drive, text='ELEGIR JSON OAUTH', command=elegir_json).pack(side='left', padx=(0, 5))
        boton_drive = ttk.Button(fila_drive, text='OBTENER IDs DE DRIVE')
        boton_drive.pack(side='left')
        def elegir_candidato(tipo, candidatos):
            if len(candidatos) == 1:
                return candidatos[0]
            dialogo = tk.Toplevel(ventana)
            dialogo.title('Drive: elegir ' + tipo)
            centrar_ventana(dialogo, 760, 330)
            dialogo.transient(ventana)
            ttk.Label(dialogo, text='Hay varios resultados para ' + tipo + '. Elegí el correcto:', padding=10).pack(anchor='w')
            listado = tk.Listbox(dialogo, exportselection=False)
            listado.pack(fill='both', expand=True, padx=10)
            for item in candidatos:
                listado.insert('end', item['name'] + '   [' + item['id'] + ']')
            elegido = [None]
            def confirmar():
                sel = listado.curselection()
                if sel:
                    elegido[0] = candidatos[sel[0]]
                    dialogo.destroy()
            ttk.Button(dialogo, text='USAR SELECCIONADO', command=confirmar).pack(pady=8)
            dialogo.protocol('WM_DELETE_WINDOW', dialogo.destroy)
            dialogo.grab_set()
            ventana.wait_window(dialogo)
            return elegido[0]
        def buscar_ids():
            nombre = nombre_base_juego(titulo.get())
            if not nombre:
                messagebox.showwarning('Drive', 'Primero indicá el título del juego.', parent=ventana)
                return
            if not self.drive_credenciales:
                messagebox.showwarning('Drive', 'Primero seleccioná tu JSON OAuth.', parent=ventana)
                return
            carpeta = carpeta_drive.get().strip()
            if not carpeta:
                messagebox.showwarning('Drive', 'Indicá el nombre o ID de la carpeta.', parent=ventana)
                return
            torrent_nombre = self.ultimo_torrent_guardado or (self.archivo_torrent.name if self.archivo_torrent else '')
            if not torrent_nombre:
                torrent_nombre = simpledialog.askstring('Nombre del torrent', 'No hay torrent seleccionado/guardado en esta sesión. Escribí su nombre exacto (incluido .torrent), o cancelá para buscar solo los MD:', parent=ventana) or ''
            estado_drive.set('Conectando y consultando Drive... Se puede abrir el navegador.')
            boton_drive.configure(state='disabled')
            self.configuracion['DRIVE_FOLDER'] = carpeta
            self.guardar_configuracion()
            def trabajo():
                try:
                    sesion = conectar_drive(self.drive_credenciales)
                    if re.fullmatch(r'[A-Za-z0-9_-]{25,}', carpeta):
                        carpeta_id = carpeta
                        carpetas = []
                    else:
                        carpetas = drive_buscar_carpeta(sesion, carpeta)
                        carpeta_id = carpetas[0]['id'] if len(carpetas) == 1 else None
                    if not carpeta_id:
                        self.after(0, lambda: finalizar(None, carpetas, 'Carpeta no encontrada o hay varias con el mismo nombre. Pegá el ID de la carpeta en el campo para identificarla.'))
                        return
                    # El código original guarda INSTRUCCIONES con _inst.md, no _ins.md.
                    nombres = {'torrent': [torrent_nombre] if torrent_nombre else [],
                               'instrucciones': [nombre + '_inst.md', nombre + '_ins.md'],
                               'update': [nombre + '_upd.md']}
                    resultado = {}
                    for intento in range(4):
                        for tipo, archivos in nombres.items():
                            if tipo not in resultado or not resultado[tipo]:
                                resultado[tipo] = drive_buscar_archivos(sesion, carpeta_id, archivos)
                        if all(resultado[t] for t in nombres if nombres[t]):
                            break
                        if intento < 3:
                            time.sleep(2)
                    self.after(0, lambda: finalizar(resultado, None, None))
                except Exception as exc:
                    error = str(exc)
                    self.after(0, lambda: finalizar(None, None, error))
            def finalizar(resultado, carpetas, error):
                if not ventana.winfo_exists():
                    return
                boton_drive.configure(state='normal')
                if error:
                    estado_drive.set('No se pudieron recuperar los IDs.')
                    messagebox.showerror('Google Drive API', error, parent=ventana)
                    return
                variables = {'torrent': torrent, 'instrucciones': instrucciones, 'update': update}
                encontrados, pendientes = [], []
                for tipo, variable in variables.items():
                    candidatos = resultado.get(tipo, [])
                    if not candidatos:
                        pendientes.append(tipo)
                        continue
                    elegido = elegir_candidato(tipo, candidatos)
                    if elegido:
                        variable.set('https://drive.google.com/file/d/' + elegido['id'] + '/view')
                        encontrados.append(tipo)
                estado_drive.set('IDs obtenidos: ' + ', '.join(encontrados or ['ninguno']) + ('. Pendientes: ' + ', '.join(pendientes) if pendientes else '.'))
            threading.Thread(target=trabajo, daemon=True).start()
        boton_drive.configure(command=buscar_ids)


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
                coincidencias = [i for i, linea in enumerate(lineas_editor) if not linea.startswith('---') and nombre_base_juego(linea.split('|', 1)[0]).casefold() == nombre_base_juego(nombre).casefold()]
                if len(coincidencias) > 1:
                    seleccion = tk.Toplevel(ventana)
                    seleccion.title('Elegir versión del juego')
                    centrar_ventana(seleccion, 780, 340)
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
                # Evita publicaciones duplicadas sin impedir otras ediciones del juego.
                # Se consulta el contenido ACTUAL del editor, incluidos cambios sin guardar.
                def clave_juego(valor):
                    return ' '.join(nombre_base_juego(valor).casefold().split())

                clave_nueva = clave_juego(nombre)
                existentes = []
                for numero, linea in enumerate(editor.get('1.0', 'end-1c').splitlines(), 1):
                    if not linea.strip() or linea.lstrip().startswith('---'):
                        continue
                    titulo_existente = linea.split('|', 1)[0].strip()
                    if clave_juego(titulo_existente) == clave_nueva:
                        existentes.append((numero, titulo_existente))
                if existentes:
                    detalle = '\n'.join(f'Línea {n}: {t}' for n, t in existentes[:8])
                    if len(existentes) > 8:
                        detalle += f'\n... y {len(existentes) - 8} coincidencia(s) más.'
                    if not messagebox.askyesno(
                        'Posible juego duplicado',
                        f'¡Atención! «{nombre}» ya figura en el catálogo '
                        f'({len(existentes)} coincidencia(s)).\n\n'
                        f'{detalle}\n\n'
                        '¿Querés insertarlo de todas formas?\n'
                        'Elegí NO para evitar un registro duplicado.',
                        parent=ventana,
                        default='no',
                    ):
                        estado.configure(text='No se insertó: el juego ya figura en el catálogo.')
                        return
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
        centrar_ventana(ventana, 850, 820)
        ventana.minsize(740, 690)
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
        ttk.Label(filtro, text='(independiente de la ficha Steam)').pack(side='left')
        filtro_nombre = ttk.Frame(ventana, padding=(10, 5))
        filtro_nombre.pack(fill='x')
        ttk.Label(filtro_nombre, text='Buscar juego por nombre:').pack(side='left')
        nombre_sgdb = tk.StringVar(value=simplificar_titulo_steam(self.nombre_juego.get()) or self.nombre_juego.get())
        ttk.Entry(filtro_nombre, textvariable=nombre_sgdb, width=44).pack(side='left', padx=6, fill='x', expand=True)
        buscar_juegos_btn = ttk.Button(filtro_nombre, text='BUSCAR JUEGOS')
        buscar_juegos_btn.pack(side='left')
        juegos_sgdb = []
        juego_elegido = tk.StringVar(value='')
        selector_juego = ttk.Combobox(ventana, textvariable=juego_elegido, state='readonly', width=70)
        selector_juego.pack(fill='x', padx=10, pady=(0, 4))
        ttk.Button(ventana, text='Usar AppID de Steam (quitar selección SGDB)',
                   command=lambda: selector_juego.set('')).pack(anchor='w', padx=10)
        estado = tk.StringVar(value='Buscá por nombre en SteamGridDB o usá un AppID de Steam.')
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
            buscar_juegos_btn.configure(state='disabled')
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
                buscar_juegos_btn.configure(state='normal')
                if error:
                    estado.set('Error: ' + error)
                else:
                    listo(resultado)
            threading.Thread(target=worker, daemon=True).start()

        def buscar_juegos():
            termino = nombre_sgdb.get().strip()
            if not termino:
                return
            def obtener():
                ruta = '/search/autocomplete/' + urllib.parse.quote(termino, safe='')
                return sgdb_get(ruta)
            def mostrar(items):
                juegos_sgdb[:] = [x for x in items if x.get('id') is not None]
                selector_juego['values'] = [f'{x.get("name", "Sin nombre")} (SGDB ID {x["id"]})' for x in juegos_sgdb]
                juego_elegido.set('')
                estado.set(f'{len(juegos_sgdb)} juegos encontrados. Elegí uno en la lista para ver sus portadas.')
            tarea(obtener, mostrar)

        def buscar():
            numero = appid.get().strip()
            indice = selector_juego.current()
            if indice >= 0 and indice < len(juegos_sgdb):
                ruta = '/grids/game/' + str(juegos_sgdb[indice]['id'])
            elif numero.isdigit():
                ruta = '/grids/steam/' + numero
            else:
                messagebox.showinfo('SteamGridDB', 'Buscá un juego por nombre y elegilo, o ingresá un AppID.', parent=ventana)
                return
            def obtener():
                encontrados = sgdb_get(ruta + '?dimensions=600x900')
                if not encontrados:
                    encontrados = sgdb_get(ruta)
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
        buscar_juegos_btn.configure(command=buscar_juegos)
        nombre_sgdb_entry = filtro_nombre.winfo_children()[1]
        nombre_sgdb_entry.bind('<Return>', lambda event: buscar_juegos())
        selector_juego.bind('<<ComboboxSelected>>', lambda event: buscar())
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

    def extraer_updates_url(self):
        url = self.url_updates.get().strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in ('fitgirl-repacks.site', 'www.fitgirl-repacks.site'):
            messagebox.showwarning('URL incorrecta', 'Pegá una URL HTTPS de fitgirl-repacks.site.')
            return
        self.boton_extraer_updates.configure(state='disabled')
        def trabajo():
            try:
                peticion = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'en-US,en;q=0.9'})
                with urllib.request.urlopen(peticion, timeout=25) as respuesta:
                    datos = respuesta.read(3 * 1024 * 1024 + 1)
                    if len(datos) > 3 * 1024 * 1024:
                        raise ValueError('La página supera los 3 MB.')
                    charset = respuesta.headers.get_content_charset() or 'utf-8'
                pagina = datos.decode(charset, errors='replace')
                resultados = extraer_updates_fitgirl(pagina)
                titulo_juego = extraer_titulo_fitgirl(pagina)
                self.after(0, lambda: self.previsualizar_updates(resultados, titulo_juego))
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda: messagebox.showerror('No se pudieron extraer updates', error + '\n\nPodés probar con HTML guardado (Ctrl+U).'))
            finally:
                self.after(0, lambda: self.boton_extraer_updates.configure(state='normal'))
        threading.Thread(target=trabajo, daemon=True).start()

    def extraer_updates_archivo(self):
        archivo = filedialog.askopenfilename(title='Seleccionar HTML de FitGirl', filetypes=[('Archivos HTML', '*.html *.htm'), ('Todos', '*.*')])
        if not archivo:
            return
        try:
            contenido = Path(archivo).read_text(encoding='utf-8-sig', errors='replace')
            self.previsualizar_updates(extraer_updates_fitgirl(contenido), extraer_titulo_fitgirl(contenido))
        except Exception as exc:
            messagebox.showerror('Error al leer HTML', str(exc))

    def previsualizar_updates(self, resultados, titulo_juego=''):
        ventana = tk.Toplevel(self)
        ventana.title('Kalaka’s Soft · Vista previa de updates')
        centrar_ventana(ventana, 850, 600)
        ventana.transient(self)
        ttk.Label(ventana, text=f'Se encontraron {len(resultados)} actualizaciones. Revisá el texto antes de incorporarlo.', padding=10).pack(anchor='w')
        if titulo_juego:
            ttk.Label(ventana, text='Título detectado: ' + titulo_juego, padding=(10, 0, 10, 8)).pack(anchor='w')
        # Formato Markdown: nombre visible y URL clicable en el gestor.
        contenido = '\n\n'.join(f'[{nombre}]({url})' for nombre, url in resultados)
        vista = tk.Text(ventana, wrap='none', font=('Consolas', 10))
        vista.insert('1.0', contenido)
        vista.pack(fill='both', expand=True, padx=10, pady=5)
        botones = ttk.Frame(ventana, padding=10)
        botones.pack(fill='x')
        def incorporar():
            caja = next(caja for nombre, caja, _ in self.paneles if nombre == 'UPDATES')
            anterior = caja.get('1.0', 'end-1c').strip()
            if anterior and not messagebox.askyesno('Reemplazar Updates', 'El cuadro Updates ya contiene texto. ¿Querés reemplazarlo?', parent=ventana):
                return
            caja.delete('1.0', 'end')
            caja.insert('1.0', vista.get('1.0', 'end-1c'))
            if titulo_juego:
                actual = self.nombre_juego.get().strip()
                if not actual or actual == titulo_juego or messagebox.askyesno('Nombre del juego', f'Ya existe un nombre: {actual}\n\n¿Querés reemplazarlo por {titulo_juego}?', parent=ventana):
                    self.nombre_juego.set(titulo_juego)
            ventana.destroy()
        ttk.Button(botones, text='Incorporar al cuadro UPDATES', command=incorporar).pack(side='left')
        ttk.Button(botones, text='Cancelar', command=ventana.destroy).pack(side='right')

    def guardar_configuracion(self):
        datos = {nombre: ruta.get().strip() for nombre, _, ruta in self.paneles}
        datos['CAPTURAS'] = self.ruta_capturas.get().strip()
        datos['PORTADAS'] = self.ruta_portadas.get().strip()
        datos['STEAMGRIDDB_KEY'] = self.sgdb_key.get().strip()
        datos['GEMINI_API_KEY'] = self._gemini_api_key
        datos['TORRENTS'] = self.ruta_torrents.get().strip()
        datos['CATALOGO'] = self.configuracion.get('CATALOGO', '')
        datos['DRIVE_CREDENTIALS'] = self.configuracion.get('DRIVE_CREDENTIALS', '')
        datos['DRIVE_FOLDER'] = self.configuracion.get('DRIVE_FOLDER', 'MiCatalogoRemoto')
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

    def ejecutar_preparar_biblioteca(self):
        """Localiza el repositorio desde las carpetas de destino ya configuradas."""
        candidatos = []
        for variable, subcarpeta in (
            (self.ruta_portadas, 'imagenes'),
            (self.ruta_capturas, 'capturas'),
        ):
            valor = variable.get().strip()
            if valor:
                carpeta = Path(valor).expanduser()
                if carpeta.name.casefold() == subcarpeta:
                    candidatos.append(carpeta.parent)
        for seccion, _caja, ruta in self.paneles:
            if seccion not in ('DATOS', 'SINOPSIS'):
                continue
            valor = ruta.get().strip()
            if valor:
                carpeta = Path(valor).expanduser()
                if carpeta.name.casefold() == seccion.casefold():
                    candidatos.append(carpeta.parent)
        for raiz in dict.fromkeys(candidatos):
            script = raiz / 'preparar_biblioteca.py'
            if script.is_file():
                try:
                    subprocess.Popen([sys.executable, str(script)], cwd=str(raiz))
                    return f'\n\nPreparar Biblioteca: iniciado ({raiz})'
                except OSError as error:
                    return f'\n\nATENCIÓN: se guardó todo, pero no se pudo ejecutar Preparar Biblioteca: {error}'
        return ('\n\nATENCIÓN: se guardó todo, pero no se encontró preparar_biblioteca.py '
                'junto a las carpetas del repositorio. Revisá sus ubicaciones.')

    def guardar(self):
        titulo_completo = self.nombre_juego.get().strip()
        nombre = nombre_base_juego(titulo_completo)
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
        # Advertir antes de guardar si no se seleccionó un torrent.
        # Se permite continuar para fichas preparatorias o actualizaciones.
        if self.archivo_torrent is None:
            if not messagebox.askyesno(
                'Falta el archivo torrent',
                'No seleccionaste ningún archivo .torrent para este juego.\\n\\n'
                '¿Querés guardar los demás archivos de todas maneras?\\n\\n'
                'Elegí NO para volver y agregar el torrent.',
                parent=self,
                default='no',
            ):
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
        self.ultimo_juego_guardado = titulo_completo
        self.ultimo_torrent_guardado = self.archivo_torrent.name if self.archivo_torrent else ''
        mensaje += self.ejecutar_preparar_biblioteca()
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
