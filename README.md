# Control de Entradas · v0.7 (prototipo)

Proyecto de pruebas para la Escuela Municipal de Música y Danza de Benalmádena. Permite generar entradas libres o numeradas con QR firmado y validación local en varios dispositivos Android.

## Cambios v0.7: encuadre y corte

- **Seis diseños**: Clásico, Cartel protagonista, Panorámico, Fondo suave, Editorial y Mosaico.
- **Longitud real**: cada diseño se genera directamente a la medida elegida, sin redimensionar posteriormente el texto, la fotografía o el QR. El PDF individual y el RAW ESC/POS utilizan el mismo lienzo.
- **Galería corregida**: las seis miniaturas respetan la relación de aspecto exacta del ticket, centradas en paneles con fondo neutro, sin recortes adicionales de la entrada.
- **Márgenes de seguridad para el corte**: se evita colocar el borde exterior justo sobre los extremos longitudinales del papel. El diseñador añade un ajuste de desplazamiento de -3 a +3 mm sin cambiar la longitud ni modificar el QR.
- **Lotes**: una única inicialización ESC/POS por lote y una orden de corte por entrada. Se mantienen los dos modos (avance manual configurable / avance automático GS V 65) y la selección de impresora Windows.
- **QR**: se conserva bit a bit sin interpolación cuando cambia la longitud o el diseño.
- **Imágenes**: JPG/PNG del espectáculo, dos logos opcionales, rellenar con recorte o mostrar completo, fondo suave en plantilla 04.

## Instalación y pruebas

Windows: usar el EXE compilado de la sección GitHub Actions, artefacto `ControlEntradas_Windows_v0.7`, o compilar con `pyinstaller --onefile --windowed --hidden-import=win32print --name ControlEntradas_Windows_v0.7 desktop/control_entradas.py`.

Pruebas de desarrollo: `pip install -r desktop/requirements.txt opencv-python-headless numpy` y `python -m unittest discover -s tests -v`.

## Calibración de la ZYWELL

El papel de 80 mm no siempre permite imprimir 80 mm de ancho; esta aplicación utiliza 576 puntos (~72 mm) para rollo de 80 mm y 384 puntos (~48 mm) para 58 mm. El diseño horizontal se imprime girado 90 grados.

Para calibrar: elige un ticket de 135 mm en rollo de 80 mm, **modo automático GS V 65 si el firmware lo soporta**, y prueba dos tickets. Si el modelo no admite GS V 65, usa avance manual en puntos y prueba incrementos pequeños; si sigue sin cortar en una franja blanca, ajusta el desplazamiento del diseño de -3 a +3 mm. El corte exacto NO se puede garantizar desde software sin conocer modelo, mecanismo y resultados de prueba física.

**Importante**: no imprimir lotes grandes antes de verificar dos cortes consecutivos. El programa no marca entradas como usadas cuando solo se imprimen. Las funciones y ajustes previos se conservan.

Prototipo independiente, no es un producto municipal oficial ni una solución de producción acreditada.