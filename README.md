# Control de Entradas · v0.8 (prototipo)

Proyecto de pruebas para la Escuela Municipal de Música y Danza de Benalmádena. Permite generar entradas libres o numeradas con QR firmado y validación local en varios dispositivos Android.

## Cambios v0.8: encuadre y corte

- **Seis diseños**: Clásico, Cartel protagonista, Panorámico, Fondo suave, Editorial y Mosaico.
- **Longitud real**: cada diseño se genera directamente a la medida elegida, sin redimensionar posteriormente el texto, la fotografía o el QR. El PDF individual y el RAW ESC/POS utilizan el mismo lienzo.
- **Galería corregida**: las seis miniaturas respetan la relación de aspecto exacta del ticket, centradas en paneles con fondo neutro, sin recortes adicionales de la entrada.
- **Márgenes de seguridad para el corte**: se evita colocar el borde exterior justo sobre los extremos longitudinales del papel. El diseñador añade un ajuste de desplazamiento de -3 a +3 mm sin cambiar la longitud ni modificar el QR.
- **Lotes**: una única inicialización ESC/POS por lote y una orden de corte por entrada. Se mantienen los dos modos (avance manual configurable / avance automático GS V 65) y la selección de impresora Windows.
- **QR**: se conserva bit a bit sin interpolación cuando cambia la longitud o el diseño.
- **Imágenes**: JPG/PNG del espectáculo, dos logos opcionales, rellenar con recorte o mostrar completo, fondo suave en plantilla 04.

## Instalación y pruebas

Windows: usar el EXE compilado de la sección GitHub Actions, artefacto `ControlEntradas_Windows_v0.8`, o compilar con `pyinstaller --onefile --windowed --hidden-import=win32print --name ControlEntradas_Windows_v0.8 desktop/control_entradas.py`.

Pruebas de desarrollo: `pip install -r desktop/requirements.txt opencv-python-headless numpy` y `python -m unittest discover -s tests -v`.

## Calibración de la ZYWELL

El papel de 80 mm no siempre permite imprimir 80 mm de ancho; esta aplicación utiliza 576 puntos (~72 mm) para rollo de 80 mm y 384 puntos (~48 mm) para 58 mm. El diseño horizontal se imprime girado 90 grados.

Para calibrar: elige un ticket de 135 mm en rollo de 80 mm, **modo automático GS V 65 si el firmware lo soporta**, y prueba dos tickets. Si el modelo no admite GS V 65, usa avance manual en puntos y prueba incrementos pequeños; si sigue sin cortar en una franja blanca, ajusta el desplazamiento del diseño de -3 a +3 mm. El corte exacto NO se puede garantizar desde software sin conocer modelo, mecanismo y resultados de prueba física.

**Importante**: no imprimir lotes grandes antes de verificar dos cortes consecutivos. El programa no marca entradas como usadas cuando solo se imprimen. Las funciones y ajustes previos se conservan.

Prototipo independiente, no es un producto municipal oficial ni una solución de producción acreditada.


## Corrección corte ZYWELL (0.8)

- La versión anterior usaba `GS V 65` como corte automático; el manual de la serie POS-80XX documenta `GS V 66` con avance a la cuchilla y corte parcial, no garantiza `65` para todos los modelos.
- El nuevo modo predeterminado **ZYWELL compatible (GS V 66)** se activa también al actualizar configuraciones antiguas con el automático genérico.
- Botón **CALIBRAR ZYWELL**: tira pequeña, sin QR ni números de entrada, para comprobar que imprime por completo y ejecuta el corte al final.
- Permanece disponible el modo manual (`ESC J` con avance ajustable hasta 800 puntos) y el modo genérico; no debe utilizarse el último sin comprobar que el modelo lo admite.
- **No imprimir lotes grandes** hasta comprobar dos entradas reales. La compatibilidad del corte sigue condicionada al modelo y firmware; sin el modelo exacto no es posible garantizar la posición física.

Referencia del comando: manual del fabricante ZYWELL POS-80XX, apartado `GS V m [n]`: https://www.zywell.com/Content/upload/pdf/202338268/r41cb4d8a-efd7-499a-a60c-f76882783040.pdf