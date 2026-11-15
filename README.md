# Control de Entradas v0.4 — Escuela Municipal de Música y Danza

**Prototipo de pruebas** no homologado como sistema oficial. Proyecto para gestionar funciones, tickets numerados y acceso QR en la Casa de la Cultura. Mantiene los datos y los códigos QR generados en versiones 0.1–0.3.

## Novedades v0.4

- **Diseño horizontal** inspirado en el ejemplo aportado: logotipos opcionales, fotografía/JPG elegible, nombre, fecha, hora, lugar, número destacado y QR compacto.
- JPG del espectáculo como **cartel lateral** o **imagen de fondo suavizada** para impresión térmica monocroma.
- Una sola entrada por orden de impresión, con orientación girada 90° en el spool: al girar el ticket cortado se lee en horizontal.
- Vista previa integrada y PDF horizontal de una entrada, rollos de **80 mm** (72 mm de anchura útil, modelo de referencia) y **58 mm** (48 mm útiles, depende del modelo).
- **Eliminar función** junto con todos sus tickets, previa confirmación explícita e irreversible.
- Posibilidad de pedir corte **completo o parcial** usando comandos ESC/POS, prueba separada del cortador y avance del papel antes de cortar.
- No se cambia la firma criptográfica del QR, ni la sincronización de la APK Android existente.

## Descarga Windows

En GitHub → **Actions** → **Compilar v0.4 Windows** → ejecución con conclusión correcta → **Artifacts** → `ControlEntradas_Windows_v0.4`. El artefacto es ZIP que incluye el `.exe`.

## Uso

1. Abrir el `.exe` en Windows. Crear función con nombre, fecha, modalidad (libre o numerada), aforo.
2. Seleccionar la función en la tabla y pulsar **«Diseñar / ver / imprimir una entrada horizontal (ZYWELL)»**.
3. Indicar el nº de entrada, impresora instalada y rollo **80/58**.
4. Elegir JPG/PNG y logotipos (Ayuntamiento/centro) y optar por «Cartel lateral» o «Fondo suave». Guardar diseño.
5. Usar **Vista previa horizontal**; verificar QR y distribución. También puede guardar PDF horizontal.
6. Para imprimir un ticket y solicitar corte, usar **IMPRIMIR 1 TICKET**, seleccionar «Enviar orden de corte ESC/POS» y elegir «Completo» o «Parcial».
7. Para diagnosticar el cortador usar **Probar cortador (sin ticket)** con la ZYWELL seleccionada y tras confirmar.
8. Para borrar una función de prueba, seleccionarla y pulsar **Eliminar función seleccionada**.

### Aclaraciones críticas de impresión

- **No imprime en color**: fotos y logos se convierten a blanco y negro y se traman para impresora térmica.
- En una impresora de **80 mm de ancho**, el diseño horizontal se imprime GIRADO: el rollo avanza a lo largo (aprox. 135 mm en 80 mm), se corta y se gira el papel. No significa que la impresora imprima físicamente más de 80 mm a lo ancho.
- **Imprimir el PDF desde un lector PDF NO garantiza corte**. Para enviar `GS V` hay que pulsar **IMPRIMIR 1 TICKET**, con cola Windows que acepte trabajos `RAW`, firmware compatible con **ESC/POS** y cortador físico.
- Un trabajo aceptado por la cola de Windows **no demuestra** que el ticket saliera ni que el cortador se activase. Debe comprobarse en la ZYWELL real. No conocemos todavía el modelo exacto ni la configuración USB/LAN.
- El QR se representa compacto pero sin reducir sus módulos por interpolación. **Haz una prueba de lectura real con el móvil**, en especial para 58 mm.
- Los datos se guardan en `Documentos/ControlEntradas` (puede variar si el usuario ha redirigido Documentos). La actualización v0.4 reutiliza esos datos. Realiza copia de seguridad de `entradas.sqlite3`, `clave_privada.pem`, `pin.txt` antes de eliminar funciones si contienen datos útiles.
- Las imágenes seleccionadas se copian a `Documentos/ControlEntradas/imagenes/` y se reutilizan para imprimir entradas de esa función.

## Seguridad y concurrencia

Los códigos QR incluyen firma ECDSA-P256 verificable. Al validar desde múltiples móviles, el servidor usa una única transacción SQLite por escaneo, de modo que la misma entrada no puede validarse dos veces en el servidor central. Para evitar dobles accesos cuando se pierde también la conexión entre móviles, se necesita procedimiento de contingencia (un solo dispositivo autorizado). No se ha probado todavía el funcionamiento operativo durante un evento real.

## Pruebas

`python -m unittest discover -s tests -v`

Se incluyen pruebas de entrada libre, numerada, duplicados, eliminación, PDF individual y QR compacto. La comprobación física de impresión/corte debe efectuarse en el modelo real de ZYWELL.

## No incluido en v0.4

La APK Android se mantiene en la versión de pruebas anterior. Esta versión actualiza la **aplicación Windows** y los tickets. Los modelos de impresora no compatibles con ESC/POS pueden necesitar otro protocolo o el controlador del fabricante.
