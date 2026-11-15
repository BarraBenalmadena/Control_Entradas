# Control de Entradas · v0.5 (pruebas)

**6 plantillas horizontales seleccionables:** Clásico, Cartel protagonista, Panorámico, Fondo suave, Editorial y Mosaico. Entrada independiente y QR firmado.

**ZYWELL:** impresión consecutiva de un rango (número inicial + cantidad), cada entrada con un QR diferente y avance de papel configurable de 0 a 255 puntos antes de ordenar el corte ESC/POS tras cada entrada. La orden de corte requiere impresora y controlador compatibles y debe probarse físicamente.

**Imágenes:** seleccionar cartel JPG/PNG, logotipos de Ayuntamiento y centro, tamaño de logos (tres opciones) y tratamiento del cartel (rellenar recortando o mostrar completo). «Fondo suave» queda ahora como diseño visible (número 04); los antiguos ajustes en que era el fondo se conservan.

**Seguridad y persistencia:** La impresión o reimpresión no consume entradas ni modifica la validación del QR. Las funciones anteriores se mantienen. Eliminación de funciones con confirmación.

**Compilar Windows:** en GitHub Actions descargar el artefacto `ControlEntradas_Windows_v0.5`; o instalar las dependencias de `desktop/requirements.txt` y ejecutar `pyinstaller --onefile --windowed --hidden-import=win32print --name ControlEntradas_Windows_v0.5 desktop/control_entradas.py`.

**Probar:** `python -m pip install -r desktop/requirements.txt opencv-python-headless numpy` y `python -m unittest discover -s tests -v`.

> Prototipo independiente para evaluar el flujo, no una solución de producción ni herramienta oficial municipal. No se ha verificado físicamente la ZYWELL; utiliza entradas de prueba y calibra el cortador antes de emitir entradas reales.