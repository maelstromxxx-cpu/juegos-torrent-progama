"""Juegos Torrent - genera biblioteca.json con hashes compatibles con Git.

Ubicar en la raíz del repositorio, junto a imagenes/, capturas/ y sinopsis/.
Los archivos TXT se publican con saltos de línea LF (ver .gitattributes).
No modifica las imágenes, capturas ni sinopsis originales.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
CARPETAS = {
    'imagenes': {'.jpg', '.jpeg', '.png', '.webp'},
    'capturas': {'.jpg', '.jpeg', '.png', '.webp'},
    'sinopsis': {'.txt'},
    'datos': {'.txt'},
}
LIMITE_BYTES = 12_000_000


def bytes_publicados(archivo: Path) -> bytes:
    """Reproduce la normalización de fin de línea de Git para TXT."""
    datos = archivo.read_bytes()
    if archivo.suffix.lower() == '.txt':
        # Git con atributos `text eol=lf` elimina el CR de cada CRLF.
        # NO convierte CR aislados: en CRCRLF debe quedar CRLF.
        datos = datos.replace(b'\r\n', b'\n')
    return datos


def main() -> None:
    registros = []
    omitidos = 0
    for nombre, extensiones in CARPETAS.items():
        carpeta = BASE / nombre
        if not carpeta.is_dir():
            print(f'Aviso: no existe la carpeta {nombre}/')
            continue
        for archivo in sorted(carpeta.rglob('*')):
            if not archivo.is_file():
                continue
            if archivo.is_symlink() or archivo.suffix.lower() not in extensiones:
                omitidos += 1
                continue
            if any(parte.is_symlink() for parte in archivo.relative_to(BASE).parents if parte != Path('.')):
                omitidos += 1
                continue
            try:
                if archivo.suffix.lower() == '.txt' and b'\r\r\n' in archivo.read_bytes():
                    print(f'AVISO: saltos de línea CRCRLF detectados: {archivo.relative_to(BASE)}; se calculará el hash como Git.')
                datos = bytes_publicados(archivo)
            except OSError as error:
                print(f'No se pudo leer {archivo.relative_to(BASE)}: {error}')
                omitidos += 1
                continue
            if not datos:
                print(f'ADVERTENCIA: archivo vacío omitido: {archivo.relative_to(BASE)}')
                omitidos += 1
                continue
            if len(datos) > LIMITE_BYTES:
                print(f'Omitido por tamaño: {archivo.relative_to(BASE)}')
                omitidos += 1
                continue
            registros.append({
                'path': archivo.relative_to(BASE).as_posix(),
                'size': len(datos),
                'sha256': hashlib.sha256(datos).hexdigest(),
            })

    if not registros:
        print('ERROR: no encontré archivos válidos. No se modificó biblioteca.json.')
        return

    destino = BASE / 'biblioteca.json'
    contenido = json.dumps({'schema': 1, 'files': registros}, ensure_ascii=False, indent=2) + '\n'
    if destino.exists() and destino.read_text(encoding='utf-8') == contenido:
        print(f'Biblioteca sin cambios: {len(registros)} archivos.')
    else:
        temporal = BASE / 'biblioteca.json.tmp'
        temporal.write_text(contenido, encoding='utf-8', newline='\n')
        temporal.replace(destino)
        print(f'Actualizado biblioteca.json: {len(registros)} archivos.')
    if omitidos:
        print(f'Archivos omitidos: {omitidos}.')
    print('Ahora abrí GitHub Desktop: Commit to main y Push origin.')


if __name__ == '__main__':
    main()
