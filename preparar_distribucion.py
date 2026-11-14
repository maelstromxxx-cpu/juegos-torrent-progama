"""Una fuente del gestor -> EXE onefile, archivo SHA-256 e instalador Inno."""
import argparse
import ast
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
INPUT=ROOT/'ARCHIVOS_DEL_GESTOR'
FOLDERS=('recursos','tutoriales','datos','imagenes','capturas','sinopsis')
CONFIGS=('biblioteca_remota.json','actualizaciones.json','promociones_config.json','catalogo_cache.txt')


def select_source():
    sources=list(ROOT.glob('Juegos_Torrent*.py'))
    if len(sources)!=1:
        raise ValueError('Dejá exactamente un Juegos_Torrent*.py en la carpeta del kit. Retirá las versiones anteriores.')
    source=sources[0]
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    version=None
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='APP_VERSION' for t in node.targets):
            version=ast.literal_eval(node.value)
    import actualizador
    actualizador.version_tuple(version)
    return source,str(version)


def validate_inputs():
    if not (INPUT/'recursos').is_dir() or not any((INPUT/'recursos').iterdir()):
        raise ValueError('Copiá recursos/ dentro de ARCHIVOS_DEL_GESTOR.')
    if not (INPUT/'biblioteca_remota.json').is_file():
        raise ValueError('Falta ARCHIVOS_DEL_GESTOR/biblioteca_remota.json.')
    for name in CONFIGS:
        path=INPUT/name
        if path.is_file() and path.suffix=='.json':
            data=json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(data,dict):
                raise ValueError(name+': formato JSON inválido.')
            if name=='actualizaciones.json' and ('USUARIO_GITHUB' in str(data.get('repositorio',''))):
                raise ValueError('actualizaciones.json todavía contiene USUARIO_GITHUB. Usá maelstromxxx-cpu/juegos-torrent-progama.')


def find_iscc():
    override = os.environ.get('ISCC', '').strip().strip('"')
    if override:
        candidate = Path(override)
        if candidate.is_dir():
            candidate = candidate / 'ISCC.exe'
        if candidate.is_file():
            return candidate
        raise ValueError('La ruta indicada en ISCC no existe: ' + str(candidate))
    candidate = shutil.which('ISCC.exe')
    if candidate:
        return Path(candidate)
    for version in ('7', '6'):
        for base in (os.environ.get('ProgramFiles'), os.environ.get('ProgramFiles(x86)'),
                     os.environ.get('LOCALAPPDATA')):
            if not base:
                continue
            for relative in (f'Inno Setup {version}/ISCC.exe', f'Programs/Inno Setup {version}/ISCC.exe'):
                candidate = Path(base) / relative
                if candidate.is_file():
                    return candidate
    raise ValueError('No se encontró Inno Setup 7 ni 6. Indicá ISCC con la ruta completa de ISCC.exe y repetí CREAR_INSTALADOR.bat; no hace falta recompilar el EXE.')


def write_version_info(version):
    parts=tuple(map(int,version.split('.')))+(0,)
    if any(x>65535 for x in parts):raise ValueError('Versión demasiado grande para Windows.')
    info="""VSVersionInfo(ffi=FixedFileInfo(filevers=%r, prodvers=%r, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName', "Kalaka's Soft"),StringStruct('ProductName','Juegos Torrent'),StringStruct('FileVersion',%r),StringStruct('ProductVersion',%r),StringStruct('OriginalFilename','JuegosTorrent.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])"""%(parts,parts,version,version)
    path=ROOT/'version_windows.txt';path.write_text(info,encoding='utf-8');return path


def build(source,version):
    if sys.platform!='win32':raise ValueError('La compilación debe ejecutarse en Windows.')
    if sys.version_info < (3, 10):
        raise ValueError('La corrección SSL necesita Python 3.10 o superior para compilar.')
    try:
        import truststore
        import ssl
        truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except (ImportError, AttributeError, OSError) as exc:
        raise ValueError(
            'Falta truststore o no se pudo inicializar. Ejecutá en esta PC: '
            'python -m pip install --upgrade truststore. Luego repetí COMPILAR_PORTATIL.bat.'
        ) from exc
    output=ROOT/'SALIDA'/('v'+version)/'JuegosTorrent'
    if output.exists():raise ValueError('Ya existe '+str(output)+'. Renombrá esa salida para conservarla antes de repetir.')
    validate_inputs()
    if not (ROOT/'ICONOS'/'JuegosTorrent.ico').is_file():
        raise ValueError('Falta ICONOS/JuegosTorrent.ico para el EXE y el instalador.')
    version_file=write_version_info(version)
    dist=ROOT/'dist'/('v'+version)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
             '--name','JuegosTorrent','--hidden-import','truststore._windows','--icon',str(ROOT/'ICONOS'/'JuegosTorrent.ico'),'--version-file',str(version_file),'--paths',str(ROOT),
             '--distpath',str(dist),'--workpath',str(ROOT/'build'), '--specpath',str(ROOT),str(source)]
    subprocess.run(command,cwd=ROOT,check=True)
    output.mkdir(parents=True)
    exe=output/'JuegosTorrent.exe';shutil.copy2(dist/'JuegosTorrent.exe',exe)
    for name in FOLDERS:
        if (INPUT/name).is_dir():shutil.copytree(INPUT/name,output/name)
    for name in CONFIGS:
        if (INPUT/name).is_file():shutil.copy2(INPUT/name,output/name)
    if not (output/'actualizaciones.json').exists():
        (output/'actualizaciones.json').write_text(json.dumps({'repositorio':'maelstromxxx-cpu/juegos-torrent-progama','habilitado':True},indent=2),encoding='utf-8')
    subprocess.run([str(exe),'--diagnostico'],cwd=output,check=True,timeout=90)
    report=json.loads((output/'diagnostico_portatil.json').read_text(encoding='utf-8'))
    if (not report['compilado'] or report['version']!=version or not report['pillow_disponible'] or
            Path(report['carpeta_base']).resolve()!=output.resolve()):
        raise ValueError('El diagnóstico del EXE no confirmó las rutas/versión/Pillow.')
    release=ROOT/'PUBLICAR'/('v'+version)
    release.mkdir(parents=True,exist_ok=True)
    shutil.copy2(exe,release/'JuegosTorrent.exe')
    import actualizador
    digest=actualizador.file_hash(exe)
    (release/'JuegosTorrent.exe.sha256').write_text(digest+'  JuegosTorrent.exe\n',encoding='ascii')
    print('EXE listo:',exe)
    print('Archivos para GitHub Releases:',release)
    return output


def installer(version,output):
    if not (output/'JuegosTorrent.exe').is_file():
        raise ValueError('Primero ejecutá COMPILAR_PORTATIL.bat.')
    diag=output/'diagnostico_portatil.json'
    if not diag.is_file():
        raise ValueError('Falta diagnostico_portatil.json: usá el EXE generado por este kit.')
    report=json.loads(diag.read_text(encoding='utf-8-sig'))
    if report.get('version')!=version or not report.get('compilado'):
        raise ValueError('El diagnóstico no coincide con la versión '+version+'.')
    sha_file=ROOT/'PUBLICAR'/('v'+version)/'JuegosTorrent.exe.sha256'
    if not sha_file.is_file():
        raise ValueError('Falta el SHA-256 de PUBLICAR/v'+version+'. Compilá primero.')
    expected=sha_file.read_text(encoding='ascii').split()[0].lower()
    actual=hashlib.sha256((output/'JuegosTorrent.exe').read_bytes()).hexdigest()
    if actual!=expected:
        raise ValueError('El EXE compilado no coincide con el SHA-256 de PUBLICAR.')
    command=[str(find_iscc()),'/DMyAppVersion='+version,'/DSourceDir='+str(output),str(ROOT/'JuegosTorrent.iss')]
    subprocess.run(command,cwd=ROOT,check=True)
    print('Instalador listo:',ROOT/'INSTALADORES'/('JuegosTorrent_Setup_v'+version+'.exe'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--instalador',action='store_true')
    parser.add_argument('--solo-instalador',action='store_true')
    args=parser.parse_args()
    try:
        source,version=select_source()
        output=ROOT/'SALIDA'/('v'+version)/'JuegosTorrent'
        if not args.solo_instalador:output=build(source,version)
        if args.instalador or args.solo_instalador:installer(version,output)
        return 0
    except (OSError,ValueError,subprocess.SubprocessError,SyntaxError) as exc:
        print('ERROR:',exc,file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
