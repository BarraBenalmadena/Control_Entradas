# Control de Entradas · Versión 0.9 (pruebas)

Aplicación de Windows para espectáculos de la Escuela Municipal de Música y Danza. Conserva el lector Android existente, la gestión de funciones, las entradas numeradas y libres, QR firmados, vista previa e impresión en rollo térmico. No es una aplicación oficial del Ayuntamiento.

## Novedades de la v0.9

- **Diez plantillas**: 01 Clásico, 02 Cartel protagonista, 03 Panorámico, 04 Fondo suave, 05 Editorial, 06 Mosaico, 07 Institucional, 08 Escenario, 09 Tríptico y 10 Minimalista.
- **Logos a elegir**: según plantilla, extremos, juntos a la izquierda/derecha, apilados a izquierda/derecha o centrados. Los JPG/PNG se guardan por función.
- **Tipografía**: tamaños de letras generales, cabecera, fecha y hora ajustables entre 70 y 140 %.
- **Márgenes independientes**: izquierdo y derecho (avance y corte), superior e inferior (ancho imprimible); 0–18 mm en extremos y 0–12 mm arriba/abajo.
- **Galería de diez diseños** y panel desplazable.
- **QR sin deformar** y mismo lienzo para PDF individual e impresión ESC/POS. Se conservan impresión consecutiva por rango y las opciones de corte anteriores.

## Uso

1. Abre el EXE 0.9. Los datos anteriores permanecen en `Documentos/ControlEntradas`.
2. Selecciona una función y abre `DISEÑAR / PREVISUALIZAR / IMPRIMIR TICKETS ZYWELL`.
3. En `Diseñar entrada`, elige `VER 10 DISEÑOS`, JPG, logos, posiciones, tipografía y márgenes.
4. Visualiza, guarda y prueba **una o dos** entradas antes de emitir un lote.

## Calibración física

En rollo de 80 mm la aplicación usa 576 puntos de ancho imprimible y en 58 mm usa 384. Los márgenes dejan espacio blanco en el diseño, pero **no mueven la cuchilla**. La posición del corte todavía requiere calibración en el modelo ZYWELL concreto; no imprimir lotes grandes sin verificar dos cortes.

## Compilar

En Windows se puede usar `pyinstaller --noconfirm --onefile --windowed --hidden-import=win32print --name ControlEntradas_Windows_v0.9 desktop/control_entradas.py`. El archivo compilado se publica en GitHub Actions bajo el nombre `ControlEntradas_Windows_v0.9`. Esta versión no cambia la APK Android.
