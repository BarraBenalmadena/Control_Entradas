"""Catálogo principal de entradas seleccionadas por el usuario.
Cada modelo utiliza un motivo gráfico extraído de la imagen de referencia.
Los QR y Code128 se generan de nuevo para cada entrada: nunca se reutilizan
los códigos impresos de las fotografías de ejemplo.
"""
from pathlib import Path
import sys

CATALOG_MODELS = (
    ("01 · Veinte diseños musicales 08", "music6_08", 0),
    ("02 · Veinte diseños musicales 11", "music6_11", 19),
    ("03 · Veinte diseños musicales 12", "music6_12", 7),
    ("04 · Veinte diseños musicales 17", "music6_17", 22),
    ("05 · Veinte diseños musicales 18", "music6_18", 23),
    ("06 · Veinte diseños musicales 20", "music6_20", 30),
    ("07 · Colección musical 01", "music5_01", 0),
    ("08 · Colección musical 02", "music5_02", 19),
    ("09 · Colección musical 03", "music5_03", 2),
    ("10 · Colección musical 04", "music5_04", 11),
    ("11 · Colección musical 05", "music5_05", 4),
    ("12 · Colección musical 06", "music5_06", 8),
    ("13 · Colección musical 09", "music5_09", 3),
    ("14 · Colección musical 11", "music5_11", 7),
    ("15 · Colección musical 16", "music5_16", 19),
    ("16 · Colección musical 18", "music5_18", 31),
    ("17 · Municipal 01", "municipal_01", 0),
    ("18 · Municipal 02", "municipal_02", 11),
    ("19 · Municipal 03", "municipal_03", 19),
    ("20 · Municipal 05", "municipal_05", 23),
    ("21 · Municipal 06", "municipal_06", 3),
    ("22 · Municipal 07", "municipal_07", 6),
    ("23 · Municipal 09", "municipal_09", 8),
    ("24 · Municipal 11", "municipal_11", 24),
    ("25 · Municipal 19", "municipal_19", 31),
)
CATALOG_NAMES = tuple(item[0] for item in CATALOG_MODELS)
CATALOG_INDEX = {item[0]: item for item in CATALOG_MODELS}


def catalog_asset_dir() -> Path:
    """Assets alongside the distributed EXE; also works in source mode."""
    binary_dir = Path(sys.executable).resolve().parent
    script_dir = Path(__file__).resolve().parent
    for location in (binary_dir / 'catalogo_entradas', script_dir / 'catalogo_entradas'):
        if location.is_dir():
            return location
    return binary_dir / 'catalogo_entradas'


def catalog_asset(name: str) -> Path:
    _, key, _ = CATALOG_INDEX[name]
    image = catalog_asset_dir() / (key + '.jpg')
    if not image.is_file():
        raise FileNotFoundError(
            f'No se encuentra el motivo del catálogo {key}. '
            'Extrae el ZIP completo con la carpeta catalogo_entradas al lado del EXE.'
        )
    return image
