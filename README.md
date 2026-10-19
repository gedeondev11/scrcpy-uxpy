# uxpy panel

Panel web local en Flask para controlar [scrcpy](https://github.com/Genymobile/scrcpy): muestra, graba o comparte la pantalla de tu Android con audio desde Linux o Windows.

## Descripción

**uxpy panel** es una interfaz web local, hecha con Flask y Tailwind CSS, que facilita el uso de scrcpy sin escribir comandos en la terminal. Desde el navegador puedes elegir cómo usar la pantalla de tu celular Android: verla en una ventana con sonido, grabarla a un archivo, hacer ambas cosas a la vez o enviarla como cámara virtual en Linux para usarla en Meet, Zoom u OBS.

## Características

- Cuatro modos: mostrar, grabar, mostrar + grabar y cámara virtual (v4l2, solo Linux).
- Perfiles de calidad predefinidos (Básica, Media y Avanzada) y ajustes manuales de resolución, FPS, tasa de bits y códecs de video y audio.
- Audio del teléfono o micrófono, con búfer configurable para ajustar la latencia.
- Opciones de ventana: título, siempre visible, sin bordes, solo ver, mantener el teléfono despierto y apagar su pantalla.
- Selector de dispositivo a partir de `adb devices`.
- Consola en vivo con la salida real de scrcpy y detección automática de cuando el proceso termina.
- Validación de los datos del formulario y detención segura de las grabaciones.
- Compatible con Linux y Windows.

## Requisitos

- Python 3 y Flask
- scrcpy 2.0 o superior y adb
- Android 11 o superior para el audio, con la **Depuración USB** activada
- Para la cámara virtual: Linux con `v4l2loopback`

## Instalación

```bash
pip install flask
sudo apt install scrcpy adb   # Debian/Ubuntu
```

Comprueba que todo se ve correctamente:

```bash
scrcpy --version
adb devices
```

El celular debe aparecer como `device` (no como `unauthorized`).

## Uso

```bash
python3 app.py
```

Abre `http://127.0.0.1:5000` en el navegador, elige el modo y el perfil, y presiona **Iniciar**. Las grabaciones se guardan en la carpeta `grabaciones/`.

### Usar un scrcpy descargado manualmente

Si no lo instalaste con el gestor de paquetes, puedes poner `scrcpy` y `adb` junto a `app.py` (con `chmod +x scrcpy adb` en Linux) o indicar sus rutas:

```bash
SCRCPY=/ruta/a/scrcpy ADB=/ruta/a/adb python3 app.py
```

### Cámara virtual (solo Linux)

```bash
sudo modprobe v4l2loopback video_nr=2 card_label="Celular" exclusive_caps=1
```

Luego selecciona el modo **Cámara virtual** con el dispositivo `/dev/video2`. La cámara virtual no transmite audio.

### Compartir la pantalla con sonido

Usa el modo **Mostrar** y, en Meet, Discord o Zoom, comparte la ventana de scrcpy (el título de la ventana se puede cambiar en el panel). El audio del teléfono sale por las bocinas del equipo, así que para que los demás lo escuchen debes compartir también el audio del sistema o usar un sink virtual de PipeWire/PulseAudio.

## Notas

- En Windows todo funciona igual, excepto la cámara virtual. Si una grabación se corta mal, cierra la ventana de scrcpy directamente.
- MP4 no admite audio Raw PCM; usa MKV (recomendado) u otro códec de audio.
- El servidor escucha solo en `127.0.0.1`, por lo que no es accesible desde otros equipos.
