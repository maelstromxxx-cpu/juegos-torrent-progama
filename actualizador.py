"""Actualización del EXE. Este módulo se incorpora dentro del onefile."""
import ctypes
import hashlib
import json
import os
import re
import ssl
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ASSET_NAME = 'JuegosTorrent.exe'
MAX_SIZE = 1_500_000_000
USER_AGENT = 'JuegosTorrent-Updater/1.1'


def trusted_urlopen(request, timeout):
    """HTTPS seguro. En Windows valida con el almacén de confianza del sistema.

    No se desactiva la verificación de certificados. Se aplica solamente a las
    conexiones del actualizador; el catálogo mantiene su transporte original.
    """
    if sys.platform != 'win32':
        return urlopen(request, timeout=timeout)
    try:
        import truststore
    except ImportError as exc:
        raise RuntimeError(
            'Falta truststore en el ejecutable. En la PC de compilación ejecutá '
            'python -m pip install --upgrade truststore y volvé a compilar.'
        ) from exc
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return urlopen(request, timeout=timeout, context=context)


def version_tuple(value):
    match = re.fullmatch(r'[vV]?(\d+)\.(\d+)\.(\d+)', str(value))
    if not match:
        raise ValueError('Versión inválida; se esperaba X.Y.Z.')
    return tuple(map(int, match.groups()))


def github_asset_url(value, repo):
    parsed = urlparse(str(value))
    if (parsed.scheme != 'https' or parsed.hostname != 'github.com' or
            not parsed.path.startswith('/'+repo+'/releases/download/')):
        raise ValueError('El archivo no pertenece a las Releases del repositorio configurado.')
    return str(value)


def select_release(release, local_version, repo):
    if release.get('draft') or release.get('prerelease'):
        return None
    version = str(release.get('tag_name', '')).lstrip('vV')
    if version_tuple(version) <= version_tuple(local_version):
        return None
    assets = release.get('assets', [])
    assets = [item for item in assets if isinstance(item, dict)]
    matching = [item for item in assets if item.get('name') == ASSET_NAME]
    if len(matching) != 1:
        raise ValueError('La Release debe tener exactamente un JuegosTorrent.exe (no Setup).')
    asset = dict(matching[0])
    github_asset_url(asset.get('browser_download_url', ''), repo)
    size = int(asset.get('size', 0))
    if not 512 <= size <= MAX_SIZE:
        raise ValueError('Tamaño del ejecutable inválido.')
    raw_digest = str(asset.get('digest', ''))
    if re.fullmatch(r'sha256:[a-fA-F0-9]{64}', raw_digest):
        digest = raw_digest[7:].lower()
    else:
        hashes = [a for a in assets if a.get('name') == ASSET_NAME+'.sha256']
        if len(hashes) != 1:
            raise ValueError('La Release no incluye SHA-256 para verificar el EXE.')
        req = Request(github_asset_url(hashes[0].get('browser_download_url', ''), repo),
                      headers={'User-Agent': USER_AGENT})
        with trusted_urlopen(req, timeout=18) as response:
            raw = response.read(1025)
        if len(raw)>1024:
            raise ValueError('Archivo SHA-256 demasiado grande.')
        match = re.fullmatch(r'\s*([a-fA-F0-9]{64})(?:[ \t]+\*?JuegosTorrent\.exe)?\s*',raw.decode('ascii'))
        if not match:
            raise ValueError('Formato de SHA-256 inválido.')
        digest = match.group(1).lower()
    return {'version': version, 'url': asset['browser_download_url'], 'size': size,
            'sha256': digest}


def check_release(repo, local_version):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):
        raise ValueError('Repositorio inválido.')
    request = Request(f'https://api.github.com/repos/{repo}/releases/latest',
                      headers={'User-Agent': USER_AGENT,'Accept':'application/vnd.github+json'})
    with trusted_urlopen(request, timeout=18) as response:
        raw=response.read(1_000_001)
    if len(raw)>1_000_000:
        raise ValueError('Respuesta de GitHub demasiado grande.')
    release=json.loads(raw)
    if not isinstance(release,dict):
        raise ValueError('Respuesta de GitHub inválida.')
    return select_release(release,local_version,repo)


def file_hash(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):
            result.update(chunk)
    return result.hexdigest()


def verify_executable(path, expected_size, expected_hash):
    path=Path(path)
    if path.stat().st_size!=expected_size:
        raise ValueError('Tamaño de ejecutable incorrecto.')
    with path.open('rb') as source:
        if source.read(2)!=b'MZ':
            raise ValueError('El archivo descargado no es un ejecutable Windows.')
    if file_hash(path)!=expected_hash:
        raise ValueError('El SHA-256 no coincide. Se conserva la versión instalada.')


def download_update(info, target, on_progress=lambda done,total:None):
    target=Path(target).resolve()
    handle,path=tempfile.mkstemp(prefix='.jt-update-',suffix='.exe',dir=target.parent)
    stage=Path(path)
    try:
        request=Request(info['url'],headers={'User-Agent':USER_AGENT})
        count=0
        with os.fdopen(handle,'wb') as output, trusted_urlopen(request, timeout=45) as response:
            while chunk:=response.read(1024*1024):
                count+=len(chunk)
                if count>info['size']:
                    raise ValueError('La descarga excedió el tamaño anunciado.')
                output.write(chunk)
                on_progress(count,info['size'])
            output.flush()
            os.fsync(output.fileno())
        verify_executable(stage,info['size'],info['sha256'])
        return stage
    except Exception:
        stage.unlink(missing_ok=True)
        raise


def restart_environment():
    env=dict(os.environ)
    env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    return env


def preflight_executable(stage, info):
    """Comprobar versión y arranque de diagnóstico antes de tocar el EXE instalado."""
    with tempfile.TemporaryDirectory(prefix='jt-preflight-') as folder:
        diagnostic=Path(folder)/'candidate.json'
        subprocess.run([str(stage),'--diagnostico',str(diagnostic)],cwd=Path(stage).parent,
                       env=restart_environment(),check=True,timeout=90)
        report=json.loads(diagnostic.read_text(encoding='utf-8'))
        if (not report.get('compilado') or report.get('version')!=info['version'] or
                Path(report.get('carpeta_base','')).resolve()!=Path(stage).parent.resolve()):
            raise ValueError('La versión del EXE no coincide con la Release o sus rutas no son válidas.')


def prepare_handoff(info,stage,target):
    target=Path(target).resolve()
    preflight_executable(stage,info)
    folder=Path(tempfile.mkdtemp(prefix='jt-updater-'))
    helper=folder/'JuegosTorrentUpdater.exe'
    shutil.copy2(target,helper)
    payload={'target':str(target),'stage':str(Path(stage).resolve()),'size':info['size'],
             'sha256':info['sha256'],'previous_sha256':file_hash(target),
             'parent_pid':os.getpid(),'ready':str(folder/'helper.ready'),
             'ack':str(folder/'app.ready'),'version':info['version']}
    config=folder/'job.json'
    config.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    flags=getattr(subprocess,'DETACHED_PROCESS',0)|getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0)
    subprocess.Popen([str(helper),'--aplicar-actualizacion',str(config)],cwd=folder,
                     env=restart_environment(),close_fds=True,creationflags=flags)
    return config


def wait_for_parent(pid,ready):
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x00100000,False,int(pid))
    if not handle:
        raise OSError('No se pudo esperar el cierre del gestor; no se reemplazó el EXE.')
    try:
        Path(ready).write_text('ready',encoding='ascii')
        if kernel.WaitForSingleObject(handle,120_000)!=0:
            raise TimeoutError('El gestor no terminó de cerrarse en dos minutos.')
    finally:
        kernel.CloseHandle(handle)


def replace_retry(source,destination,timeout=60):
    deadline=time.monotonic()+timeout
    while True:
        try:
            Path(source).replace(destination)
            return
        except OSError:
            if time.monotonic()>=deadline:
                raise
            time.sleep(.25)


def launch_executable(path,ack=None):
    command=[str(path)]
    if ack is not None:
        command+=['--update-ack',str(ack)]
    return subprocess.Popen(command,cwd=Path(path).parent,env=restart_environment(),close_fds=True)


def apply_update(job,wait=wait_for_parent,launch=launch_executable,replace=replace_retry):
    target=Path(job['target']).resolve()
    stage=Path(job['stage']).resolve()
    if (target.suffix.lower()!='.exe' or stage.parent!=target.parent or
            not stage.name.startswith('.jt-update-') or stage==target):
        raise ValueError('Rutas de actualización inválidas.')
    verify_executable(stage,int(job['size']),job['sha256'])
    if file_hash(target)!=job['previous_sha256']:
        raise ValueError('El ejecutable instalado cambió durante la descarga.')
    wait(job['parent_pid'],job['ready'])
    if Path(job['ready']).with_name('cancelled').exists():
        raise InterruptedError('Actualización cancelada; se conserva el ejecutable instalado.')
    backup=target.with_name(target.name+'.bak')
    # Volver a comprobar después de esperar, justo antes del reemplazo.
    verify_executable(stage,int(job['size']),job['sha256'])
    if file_hash(target)!=job['previous_sha256']:
        raise ValueError('El ejecutable instalado ya no coincide con el original.')
    replace(target,backup)
    try:
        replace(stage,target)
        process=launch(target,Path(job['ack']))
    except Exception:
        if target.exists():
            replace(target,stage)
        replace(backup,target)
        launch(target)
        raise
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        if Path(job['ack']).is_file():
            return 'ok'
        if process.poll() is not None:
            # El nuevo programa terminó antes de confirmar el arranque.
            replace(target,stage)
            replace(backup,target)
            launch(target)
            raise RuntimeError('La nueva versión no arrancó. Se restauró la versión anterior.')
        time.sleep(.25)
    # No cerrar un proceso que sigue funcionando: mantener respaldo para recuperar.
    raise TimeoutError('La nueva versión sigue abierta, pero no confirmó el arranque. Se conserva el respaldo .exe.bak.')


def run_updater(config):
    log=Path(config).with_name('actualizacion.log')
    try:
        if sys.platform!='win32':
            raise RuntimeError('El reemplazo del EXE solo se ejecuta en Windows.')
        job=json.loads(Path(config).read_text(encoding='utf-8'))
        result=apply_update(job)
        log.write_text('Actualización verificada e inicio confirmado: '+str(result),encoding='utf-8')
        return 0
    except Exception as exc:
        detail=str(exc)
        try:log.write_text(detail,encoding='utf-8')
        except OSError:pass
        if sys.platform=='win32':
            ctypes.windll.user32.MessageBoxW(None,detail+'\n\nRegistro: '+str(log),
                                           'Juegos Torrent | Actualización',0x10)
        return 1
