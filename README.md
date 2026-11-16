# Control de Entradas v1.0 · Piloto para la Escuela Municipal de Música y Danza

Aplicación independiente en pruebas. No constituye software oficial del Ayuntamiento ni sustituye a un sistema de seguridad homologado.

## 1. Windows: funciones, entradas y diseño

- Conserva las entradas QR firmadas de las versiones 0.x y los datos en `Documentos/ControlEntradas`.
- **16 diseños horizontales** de ticket en 58/80 mm, incluidos seis modelos de estilo institucional (11 a 16). Los logotipos del Ayuntamiento y del centro se colocan dentro del marco, con tamaño y posición ajustables. Mantiene JPG del espectáculo, fecha, hora, número y un código QR sin distorsión.
- Vista previa, exportación de PDF individual e impresión consecutiva ESC/POS. Calibración de avance/corte según impresora, sin garantías de resultado en un modelo ZYWELL no identificado.
- Importación del plano de butacas `JPG/PNG/PDF` (primera página PDF). **Editor asistido, no OCR automático**: superpone las butacas de la función, que pueden arrastrarse a su posición real y reservarse al pulsarlas.
- Exportación JSON **firmada** para Android. Incluye la lista de entradas válidas y los estados iniciales; no contiene la clave privada.
- Importación de registros JSON de accesos producidos en Android. Añade los nuevos accesos al histórico, informa de duplicados y desconocidos.

## 2. APK Android: validación con o sin IP Windows

1. En Windows selecciona un espectáculo y pulsa `EXPORTAR JSON PARA APK (SIN IP)`.
2. Pasa ese archivo a los teléfonos (USB, correo interno, Bluetooth, etc.). Evita publicarlo.
3. En la APK pulsa `IMPORTAR JSON FIRMADO DE WINDOWS`. La primera vez comprueba la **huella de firma** mostrada por Windows. Selecciona función y modo de validación.

### Modos de validación

- **Servidor Windows:** validación online de la aplicación original (misma Wi-Fi).
- **JSON offline independiente:** valida firma, pertenencia al evento y repetición **en el mismo teléfono**. Es obligatorio fijar un rango exclusivo de números por móvil, por ejemplo móvil 1 `1–100`, móvil 2 `101–200`. Si se solapan los rangos, no se puede impedir un doble uso entre teléfonos aislados.
- **Coordinador Android:** un teléfono carga el JSON y pulsa `INICIAR COORDINADOR`. Los demás usan `LECTOR CONECTADO A OTRO MÓVIL`, introducen la dirección IPv4 y PIN del coordinador. Todos se conectan al **mismo hotspot o Wi-Fi local**, sin ordenador. El coordinador valida en una sección sincronizada, de modo que una entrada solo puede aceptarse una vez. Mantén el coordinador abierto y conectado; si falla la red, los lectores remotos **rechazan** los accesos en lugar de aprobarlos de forma provisional.

Tras el espectáculo pulsa `EXPORTAR ACCESOS PARA WINDOWS (JSON)` en el coordinador (o en cada móvil independiente). En Windows pulsa `IMPORTAR ACCESOS DE MÓVILES (JSON)` para fusionar la actividad.

**Limitaciones:** la coordinación entre móviles requiere una red local compartida (hotspot/Wi-Fi, **no** Internet). No existe sincronización de duplicados en tiempo real si los móviles están completamente aislados. Un archivo JSON es una instantánea: las entradas usadas o revocadas en Windows **después** de exportarlo no se reflejan automáticamente. No alternes los modos Windows y JSON offline durante la misma función sin reconciliar los accesos. El registro de accesos importado es administrativo y no está firmado criptográficamente por el móvil. La comunicación del coordinador es HTTP local protegida por PIN, no cifrada: utiliza red privada de confianza.

## 3. Plano de butacas

Primero crea una función de modalidad **numerada** (número de filas y asientos por fila). Al abrir `PLANO DE BUTACAS`, el programa genera una cuadrícula inicial sobre un fondo blanco. Puedes importar el plano real del recinto, mover cada butaca a su posición y cambiar entre libre/reservada mediante clic. Los colores indican reservas y entradas usadas. Las coordenadas y las reservas se guardan en la misma base de datos. Cada butaca está vinculada a un número de entrada existente.

**No hay detección automática fiable** de asientos en cualquier plano escaneado: el editor permite colocarlos visualmente y corregirlos. Reservar es una anotación de gestión; no cambia por sí sola la validez del QR ni imprime la entrada. La emisión e impresión se hace por número en el módulo de tickets.

## 4. Instalación y compilación

- Windows: `pip install -r desktop/requirements.txt` y `python desktop/control_entradas.py`.
- Tests: `pip install opencv-python-headless numpy && python -m unittest discover -s tests -v`.
- APK: GitHub Actions `Compilar v1.0 Windows y Android` o Gradle `gradle -p android :app:assembleDebug` con JDK17 y SDK35.
- EXE: GitHub Actions, PyInstaller `--onefile --windowed --paths desktop --hidden-import=seat_plan --hidden-import=fitz`.

## 5. Cuidado con la impresora ZYWELL

Los márgenes del diseño **no calibran la cuchilla**. El corte físico sigue dependiendo del modelo, del firmware y del avance real del rollo. Realiza pruebas de dos tickets, primero sin corte, y después con el modo compatible. No atribuir a la v1.0 una corrección física del corte sin confirmarla en tu impresora.
