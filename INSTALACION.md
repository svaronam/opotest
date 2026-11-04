# OpoTest TIC

App de tests de aprendizaje continuo para las oposiciones TIC (A1 CSSTIC, A2 GSI, C1 TAI).
El servidor corre en la Raspberry **homelab2** y el móvil se conecta por **Tailscale**.

## Qué incluye

- **Temario A1 (ASTIC, 132 temas) y A2 (GSI, 57 temas y documentos extra)**: lectura por páginas, búsqueda en todo el temario, visor de PDF y resúmenes.
- **16.503 preguntas** de PreparaTIC sin duplicados (el archivo del banco no se incluye en el repositorio). Cada una lleva su tema del A1, su tema o temas del A2 y la escala del examen de origen.
- **Tests** con filtros por temario, bloque, tema, escala, origen (banco o IA), solo de examen y no vistas. Se pueden corregir al momento o al final, puntuando acierto +1 y fallo −1/3.
- **Revisión con 3 fuentes** en cada pregunta:
  - **Temario**: fragmentos del temario con las palabras resaltadas.
  - **Internet**: resultados de DuckDuckGo y Wikipedia.
  - **IA**: explicación de Gemini, que además indica si está de acuerdo con la respuesta del banco.
- **"La correcta es otra"**: corrige una respuesta del banco y recalcula tus resultados de esa pregunta.
- **Repaso espaciado de falladas**: cada fallada vuelve a los 1, 3, 7, 15 y 30 días. Recibes un aviso cuando tienes repasos pendientes.
- **Preguntas nuevas cada día**: las genera Gemini a partir del temario, del banco y de tus fallos, y salen más de los temas que más fallas. También hay un botón para generar las que quieras con los filtros elegidos.
- **Nivel de las preguntas de IA**: cada pregunta pasa por tres controles.
  - **Estilo de examen**: Gemini recibe como modelo preguntas reales de examen del mismo tema, con sus opciones, y las técnicas del tribunal (datos literales, distractores casi correctos, formulaciones negativas…).
  - **Revisión**: una segunda llamada resuelve cada pregunta sin ver la solución y le pone una nota de dificultad. Se descartan las fáciles, las ambiguas y aquellas en las que la revisión llega a otra respuesta.
  - **Nivel automático**: sube si aciertas las de la IA bastante más que las del banco o si marcas varias como "Demasiado fácil", y baja si las aciertas bastante menos. También se puede fijar a mano en Ajustes.
- **Mínimo diario** con aviso por la tarde si no lo has cumplido, y una racha de días seguidos cumpliéndolo.
- **Estadísticas**:
  - actividad por días, semanas y meses
  - temas que más fallas y los que mejor llevas
  - resultados por bloque, escala y origen
  - las preguntas que más fallas
  - a qué hora rindes mejor
- **APK** con icono propio y notificaciones nativas, que la app recibe consultando la Raspberry por Tailscale.

## Instalación

### 1. Compilar la APK (GitHub)

1. Crea un repositorio **privado** en GitHub, por ejemplo `svaronam/opotest`, y sube el contenido de esta carpeta. Puedes hacerlo con GitHub Desktop, o con `git init`, `git add .`, `git commit` y `git push`.
2. La pestaña **Actions** compila la APK sola, en unos 5 minutos.
3. Entra en **Releases** desde el móvil, descarga `OpoTest.apk` e instálala. Si te lo pide, permite instalar apps de origen desconocido.

Cada vez que cambies algo en `android/`, se publica una APK nueva que se instala encima de la anterior, porque la firma siempre es la misma.

> La clave de firma no está en el repositorio: va en GitHub Secrets (ver «Firma de la APK»).

### 2. Instalar el servidor en homelab2 (desde el PC)

En PowerShell, dentro de esta carpeta:

```powershell
powershell -ExecutionPolicy Bypass -File pc\instalar.ps1
```

El script hace tres cosas:

1. Copia la app a la Pi.
2. Instala los paquetes necesarios (Python, poppler y tesseract con español) y deja dos servicios arrancados con el sistema:
   - `opotest`: la web y la API. El puerto se elige solo: el primero libre desde el 8790, saltando los que ya usen tus otros servicios aunque estén parados. Al terminar, el script te dice cuál ha cogido. Si quieres uno concreto, usa `-Puerto 8795`.
   - `opotest-ocr`: indexa el temario a baja prioridad.
3. Copia el temario A1 y A2 desde la carpeta del temario en tu PC (parámetro del script).

Te pedirá la contraseña de `usuario@homelab2` y la de sudo.

- **A1**: el texto ya está en los PDF y se indexa en unos 5 minutos.
- **A2**: son escaneados del CEF y pasan por OCR página a página. En una Pi 3 tarda entre 1 y 2 días. Los temas se pueden consultar y usar a medida que terminan; la app muestra el porcentaje de cada uno.
- **Resúmenes manuscritos**: se ven como PDF pero no se indexan, porque el OCR no lee bien la letra a mano.

Para actualizar solo el código, sin volver a copiar el temario:

```powershell
powershell -ExecutionPolicy Bypass -File pc\instalar.ps1 -SoloServidor
```

### 3. Configurar

1. Abre la app y pon la dirección que te dio el instalador, por ejemplo `http://homelab2:8790`. Si MagicDNS no resuelve el nombre, usa la IP 100.x de Tailscale.
2. En **Ajustes**, pega tu API key de Gemini (gratis en <https://aistudio.google.com>, en "Get API key") y pulsa **Probar la IA**.
3. Ajusta el mínimo diario (50 por defecto), las preguntas nuevas por día (20), las horas de los avisos y la escala que preparas.
4. Para que los avisos lleguen puntuales, quita a OpoTest de la optimización de batería: Ajustes de Android → Apps → OpoTest → Batería → Sin restricciones.

## Comandos útiles en la Pi

```bash
systemctl status opotest opotest-ocr      # estado de los servicios
journalctl -u opotest-ocr -f              # progreso del OCR
journalctl -u opotest -n 100              # log del servidor
cd ~/opotest/server && ../venv/bin/python ingest.py --doc A2-IV-02   # reprocesar un tema
```

Tus datos están en `~/opotest/server/var/`: `opotest.db` (preguntas, intentos, tests) y `config.json` (ajustes y API key). Copia esa carpeta si quieres hacer una copia de seguridad.

## Estructura

```
server/        API y web (Python, Starlette, SQLite con búsqueda de texto completo)
  data/        catálogo de temas, equivalencias A1/A2 y banco de preguntas de PreparaTIC
  web/         interfaz (HTML, CSS y JavaScript, sin compilar)
  ingest.py    extracción de texto y OCR del temario
  logic.py     tests, repaso, estadísticas, generación con IA y avisos
  sources.py   las 3 fuentes de revisión
android/       APK (Java, sin librerías externas)
pi/install.sh  instalador para la Raspberry
pc/instalar.ps1  instalación y copia del temario desde Windows
```

## Notas

- **Equivalencia de temas**: los temas de PreparaTIC coinciden con los del ASTIC del 1 al 84. El 85 (Blockchain) no existe en el ASTIC, y del 86 al 133 se corresponden con los temas 85 a 132. La equivalencia con el GSI A2 está hecha por contenido; algunos temas del A2, como administración del SO, de SGBD o de redes, también reciben preguntas de temas afines.
- **Escala de cada pregunta**: se deduce del examen de origen. Las preguntas propias de PreparaTIC cuentan como A1. Del C1 hay pocas en el banco, así que conviene generarlas con la IA eligiendo la escala C1.
- **Modelo de IA**: por defecto `gemini-3.8-flash`, con `gemini-3.6-flash` y `gemini-3.5-flash-lite` de reserva si se agota la cuota gratuita. Se puede cambiar en Ajustes.

## Firma de la APK

La clave de firma no está en el repositorio. GitHub Actions la recibe de dos secretos del repo (*Settings → Secrets and variables → Actions*):

| Secreto | Contenido |
|---|---|
| `KEYSTORE_BASE64` | el archivo de la clave en Base64 (`base64 -w0 archivo`) |
| `KEYSTORE_PASSWORD` | su contraseña |

Para compilar en local, deja el archivo de la clave en `android/app/opotest.keystore` (está en `.gitignore`) y define `KEYSTORE_PASSWORD` antes de lanzar Gradle.
