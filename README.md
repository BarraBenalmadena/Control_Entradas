# Control de Entradas · v0.6 (pruebas)

**6 plantillas horizontales seleccionables:** Clásico, Cartel protagonista, Panorámico, Fondo suave, Editorial y Mosaico. Entrada independiente y QR firmado.

**ZYWELL:** impresión consecutiva de un rango (número inicial + cantidad), cada entrada con un QR diferente y avance de papel configurable de 0 a 255 puntos antes de ordenar el corte ESC/POS tras cada entrada. La orden de corte requiere impresora y controlador compatibles y debe probarse físicamente.

**Imágenes:** seleccionar cartel JPG/PNG, logotipos de Ayuntamiento y centro, tamaño de logos (tres opciones) y tratamiento del cartel (rellenar recortando o mostrar completo). «Fondo suave» queda ahora como diseño visible (número 04); los antiguos ajustes en que era el fondo se conservan.

**Seguridad y persistencia:** La impresión o reimpresión no consume entradas ni modifica la validación del QR. Las funciones anteriores se mantienen. Eliminación de funciones con confirmación.

**Compilar Windows:** en GitHub Actions descargar el artefacto `ControlEntradas_Windows_v0.6`; o instalar las dependencias de `desktop/requirements.txt` y ejecutar `pyinstaller --onefile --windowed --hidden-import=win32print --name ControlEntradas_Windows_v0.6 desktop/control_entradas.py`.

**Probar:** `python -m pip install -r desktop/requirements.txt opencv-python-headless numpy` y `python -m unittest discover -s tests -v`.

> Prototipo independiente para evaluar el flujo, no una solución de producción ni herramienta oficial municipal. No se ha verificado físicamente la ZYWELL; utiliza entradas de prueba y calibra el cortador antes de emitir entradas reales.

## Calibración del cabezal y corte en v0.6

- El papel de 80 mm habitualmente tiene 72 mm imprimibles: no se pueden imprimir los 80 mm con un cabezal de 576 puntos.
- Ahora se puede cambiar el largo (en mm), manteniendo el tamaño y la legibilidad del QR; se ajusta el cuerpo del ticket sin escalar el talón.
- Se añaden dos modos de corte: **manual con avance en puntos** y **automático GS V 65** (requiere soporte en el firmware).
- El avance manual predeterminado para instalaciones nuevas es **120 puntos**; es un punto de partida que necesita calibración física. Se conservan las preferencias de instalaciones anteriores.
- Probar primero con dos tickets. Si el corte cae dentro de los datos, aumentar el avance. Si queda mucho papel en blanco, reducirlo en pasos de 8 o 16 puntos.
- El corte no puede estar totalmente garantizado sin la referencia exacta de ZYWELL y una prueba real.
