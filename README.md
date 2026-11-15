# Control de Entradas · versión de prueba 0.2

**Proyecto piloto** para espectáculos de la Escuela Municipal de Música y Danza de Benalmádena. Software independiente; no es un sistema oficial del Ayuntamiento.

## Descargas compiladas

En este repositorio, abrir **Actions** → **Compilar v0.2 - Windows y Android** → ejecución correcta → **Artifacts**. Se generan:

- `ControlEntradas_Windows_v0.2` — programa `.exe` para Windows 10/11 (PyInstaller).
- `ControlEntradas_Android_v0.1` — APK de prueba Android 8.0 o posterior, firmado con certificado *debug*, no distribuible en Google Play.

**La APK de prueba no está destinada a uso público ni garantiza disponibilidad ininterrumpida.**

## Primera puesta en marcha

1. Abrir en Windows el programa `.exe`. La primera apertura puede requerir autorizar el firewall para redes privadas.
2. Crear una función con **entrada libre** (aforo) o **numerada** (filas x butacas). Pulsar **Exportar entradas PDF**.
3. Conectar Windows y los móviles a la **misma Wi-Fi**. Internet no es necesario cuando hay conexión local.
4. Instalar la APK Android. En ella introducir la dirección `http://IP-DEL-ORDENADOR:8765` y el **PIN de seis cifras** que aparece en Windows.
5. Pulsar **Conectar / actualizar funciones**, elegir la función y **Iniciar escáner QR**. Probar primero con entradas de demostración.
6. El primer escaneo de una entrada muestra **ACCESO PERMITIDO**. Un segundo escaneo devuelve **ENTRADA YA UTILIZADA**.

En Windows, el comando `ipconfig` muestra la dirección IPv4 si el programa no logra identificarla automáticamente.

## Si se pierde Internet

- Con **Wi-Fi local funcionando** y ordenador encendido: todos los móviles siguen validando simultáneamente, incluso sin Internet.
- Si **también se pierde la red local**: el lector rechaza las entradas por defecto. Puede activarse el **modo de contingencia**, pero **solo en un único móvil**. La comprobación criptográfica funciona sin red siempre que el móvil se haya vinculado previamente; la aceptación es provisional. Deben dejar de utilizarse todos los demás lectores para evitar duplicados.
- Tras recuperar la conexión, usar **Sincronizar accesos pendientes**; los posibles conflictos se muestran en pantalla.
- El modo contingencia **no garantiza** evitar duplicados entre dispositivos desconectados. Nunca ejecutar la contingencia simultánea en varios móviles.

## Archivos y seguridad

- Datos locales de Windows: `Documentos/ControlEntradas/` (base de datos SQLite, PIN y clave privada del evento).
- **Conservar copia de seguridad privada** de esa carpeta: perder la clave privada impedirá validar las entradas antiguas con una instalación nueva.
- La clave privada **no** se incluye en QR ni APK ni repositorio; los QR llevan una firma digital ECDSA P-256.
- La comunicación local usa HTTP y PIN simple: **seguridad de prototipo**. No se recomienda para redes Wi-Fi públicas ni datos personales. Para uso real deberá añadirse TLS, vinculación segura de dispositivos, revocación y trazabilidad de auditoría.
- El aforo debe introducirse según la autorización vigente del recinto, y las butacas numeradas son una cuadrícula genérica, **no un plano real de la Casa de la Cultura**.

## Limitaciones de esta v0.1

Sin venta de entradas, reservas nominales, control de reentrada, cambios de función, anulaciones, roles de usuario, asignación visual real de butacas, TLS, firmas de APK de producción ni notificaciones. La hora de acceso provisional queda registrada al sincronizar, no al escanear sin red. Es un **prototipo funcional para pruebas supervisadas**, no una solución de control de aforo lista para explotarse en público.

## Desarrollo

- `desktop/control_entradas.py`: interfaz Windows, SQLite, servidor HTTP local, QR firmados y PDF.
- `android/app`: aplicación nativa Android, escáner CameraX + ML Kit, comprobación con servidor y contingencia offline de un solo lector.
- `.github/workflows/build.yml`: compilación automática Windows y Android, con dos artefactos.
- `tests/test_core.py`: validación concurrente, QR falsificados y PDF.

Pruebas Python (en un entorno con las dependencias instaladas): `python -m unittest discover -s tests -v`.

## Versión Windows 0.2: guardar y imprimir

La barra de acciones se encuentra encima de la tabla de funciones, visible incluso con ventanas pequeñas.

1. Introduce nombre, fecha y modalidad; pulsa **1 · Guardar función y generar entradas**. Se guardan automáticamente en `Documentos/ControlEntradas/entradas.sqlite3`.
2. Selecciona la función de la tabla.
3. Pulsa **2 · Vista previa** para abrir el PDF en tu visor predeterminado.
4. Pulsa **3 · Guardar PDF** para elegir carpeta y nombre del documento.
5. Pulsa **4 · Imprimir...**, luego **Ctrl + P** en el lector PDF. Desde allí eliges la impresora y las páginas.

**Aviso:** No se ha implementado envío directo silencioso a impresora. La impresión utiliza el diálogo del visor PDF. La versión Android continúa siendo 0.1 y es compatible con el formato de QR v0.2 de Windows.