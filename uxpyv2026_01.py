"""
Panel de control para scrcpy (Linux y Windows).

Modos:
  - mirror        : mostrar la pantalla en una ventana (con audio)
  - record        : solo grabar a un archivo (opcional sin ventana)
  - mirror_record : mostrar y grabar a la vez
  - camera        : enviar el video a una cámara virtual v4l2 (solo Linux)

Variables de entorno opcionales:
  SCRCPY=/ruta/a/scrcpy      ADB=/ruta/a/adb
"""
import datetime
import os
import re
import shutil
import signal
import subprocess
import sys
import threading

from flask import Flask, Response, jsonify, request

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REC_DIR = os.path.join(BASE_DIR, "grabaciones")
IS_WINDOWS = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")

MODES = {"mirror", "record", "mirror_record", "camera"}
VIDEO_CODECS = {"h264", "h265", "av1"}
AUDIO_CODECS = {"opus", "aac", "flac", "raw"}
AUDIO_SOURCES = {"output", "mic"}
CONTAINERS = {"mkv", "mp4"}

# ---------------------------------------------------------------- estado
state_lock = threading.Lock()
proc = None
current_mode = None
current_file = None
log_lines = []
log_offset = 0


def push_log(line):
    global log_offset
    with state_lock:
        log_lines.append(line)
        if len(log_lines) > 500:
            del log_lines[:100]
            log_offset += 100


def reset_log():
    global log_lines, log_offset
    with state_lock:
        log_lines = []
        log_offset = 0


def reader(p):
    """Lee la salida de scrcpy y la guarda para mostrarla en la consola."""
    try:
        for line in p.stdout:
            line = line.rstrip()
            if line:
                push_log(line)
    except Exception:
        pass


# ---------------------------------------------------------------- binarios
def find_binary(name):
    exe = name + (".exe" if IS_WINDOWS else "")
    env = os.environ.get(name.upper())
    if env and os.path.exists(env):
        return env
    local = os.path.join(BASE_DIR, exe)
    if os.path.exists(local):
        return local
    return shutil.which(name)


def find_adb():
    env = os.environ.get("ADB")
    if env and os.path.exists(env):
        return env
    scrcpy = find_binary("scrcpy")
    if scrcpy:
        sibling = os.path.join(
            os.path.dirname(os.path.abspath(scrcpy)),
            "adb.exe" if IS_WINDOWS else "adb",
        )
        if os.path.exists(sibling):
            return sibling
    return find_binary("adb")


# ---------------------------------------------------------------- comando
def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def build_command(data):
    scrcpy = find_binary("scrcpy")
    if not scrcpy:
        raise ValueError(
            "No se encontró scrcpy. Instálalo, ponlo junto a app.py "
            "o define la variable de entorno SCRCPY."
        )

    mode = data.get("mode", "mirror")
    if mode not in MODES:
        raise ValueError("Modo no válido.")
    if mode == "camera" and not IS_LINUX:
        raise ValueError("La cámara virtual (v4l2) solo está disponible en Linux.")

    cmd = [scrcpy]
    filename = None

    # Dispositivo
    serial = (data.get("serial") or "").strip()
    if serial:
        if not re.fullmatch(r"[\w.\-:]+", serial):
            raise ValueError("Serial de dispositivo no válido.")
        cmd.extend(["-s", serial])

    # Grabación
    if mode in ("record", "mirror_record"):
        container = data.get("container", "mkv")
        if container not in CONTAINERS:
            raise ValueError("Contenedor no válido.")
        if container == "mp4" and data.get("audio_enabled", True) and data.get("audio_codec") == "raw":
            raise ValueError("MP4 no admite audio Raw PCM. Usa MKV u otro códec de audio.")
        os.makedirs(REC_DIR, exist_ok=True)
        now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(REC_DIR, f"grabacion_{now}.{container}")
        cmd.append(f"--record={filename}")
        if mode == "record" and data.get("no_playback"):
            cmd.append("--no-playback")

    # Cámara virtual (Linux)
    if mode == "camera":
        device = (data.get("v4l2_device") or "/dev/video2").strip()
        if not re.fullmatch(r"/dev/video\d+", device):
            raise ValueError("Dispositivo v4l2 no válido (ejemplo: /dev/video2).")
        cmd.append(f"--v4l2-sink={device}")
        if data.get("no_playback"):
            cmd.append("--no-playback")

    # Video
    max_size = to_int(data.get("max_size"))
    if max_size > 0:
        cmd.extend(["-m", str(max_size)])

    max_fps = to_int(data.get("max_fps"))
    if max_fps > 0:
        cmd.extend(["--max-fps", str(max_fps)])

    bit_rate = str(data.get("bit_rate", "")).strip()
    if bit_rate:
        if not re.fullmatch(r"\d+(\.\d+)?[KkMm]?", bit_rate):
            raise ValueError("Tasa de bits no válida (ejemplo: 8M).")
        cmd.extend(["--video-bit-rate", bit_rate])

    video_codec = data.get("video_codec", "h264")
    if video_codec not in VIDEO_CODECS:
        raise ValueError("Códec de video no válido.")
    cmd.extend(["--video-codec", video_codec])

    # Audio
    if data.get("audio_enabled", True):
        audio_codec = data.get("audio_codec", "opus")
        audio_source = data.get("audio_source", "output")
        if audio_codec not in AUDIO_CODECS:
            raise ValueError("Códec de audio no válido.")
        if audio_source not in AUDIO_SOURCES:
            raise ValueError("Fuente de audio no válida.")
        cmd.extend(["--audio-codec", audio_codec])
        cmd.extend(["--audio-source", audio_source])
        audio_buffer = to_int(data.get("audio_buffer"), -1)
        if audio_buffer >= 0:
            cmd.extend(["--audio-buffer", str(audio_buffer)])
    else:
        cmd.append("--no-audio")

    # Ventana y control (no aplican si no hay ventana)
    if mode in ("mirror", "mirror_record"):
        title = (data.get("window_title") or "").strip()
        if title:
            cmd.extend(["--window-title", title[:80]])
        if data.get("always_on_top"):
            cmd.append("--always-on-top")
        if data.get("borderless"):
            cmd.append("--window-borderless")

    if data.get("no_control"):
        cmd.append("--no-control")
    if data.get("stay_awake"):
        cmd.append("--stay-awake")
    if data.get("turn_screen_off"):
        cmd.append("--turn-screen-off")

    return cmd, filename


# ---------------------------------------------------------------- rutas
@app.route("/")
def index():
    return Response(HTML_TEMPLATE, mimetype="text/html")


@app.route("/info")
def info():
    scrcpy = find_binary("scrcpy")
    version = None
    if scrcpy:
        try:
            out = subprocess.run(
                [scrcpy, "--version"], capture_output=True, text=True, timeout=5
            )
            version = (out.stdout or out.stderr).splitlines()[0]
        except Exception:
            version = "desconocida"
    return jsonify(
        {
            "platform": "linux" if IS_LINUX else ("windows" if IS_WINDOWS else sys.platform),
            "scrcpy": scrcpy,
            "version": version,
            "adb": find_adb(),
            "rec_dir": REC_DIR,
        }
    )


@app.route("/devices")
def devices():
    adb = find_adb()
    if not adb:
        return jsonify({"status": "error", "message": "No se encontró adb.", "devices": []})
    try:
        out = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, timeout=10)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e), "devices": []})

    result = []
    for line in out.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), "")
        result.append({"serial": parts[0], "state": parts[1], "model": model})
    return jsonify({"status": "ok", "devices": result})


@app.route("/start", methods=["POST"])
def start():
    global proc, current_mode, current_file

    if proc is not None and proc.poll() is None:
        return jsonify({"status": "error", "message": "Ya hay un proceso activo."})

    data = request.get_json(silent=True) or {}

    try:
        cmd, filename = build_command(data)
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)})

    reset_log()
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **kwargs,
        )
    except Exception as e:
        proc = None
        return jsonify({"status": "error", "message": f"Error de ejecución: {e}"})

    current_mode = data.get("mode")
    current_file = filename
    threading.Thread(target=reader, args=(proc,), daemon=True).start()

    msg = "Ejecutado: " + " ".join(cmd)
    if filename:
        msg += f"\nArchivo: {filename}"
    return jsonify({"status": "ok", "message": msg})


@app.route("/stop", methods=["POST"])
def stop():
    global proc, current_mode, current_file

    if proc is None or proc.poll() is not None:
        proc = None
        return jsonify({"status": "error", "message": "No hay ningún proceso en curso."})

    p = proc
    try:
        # SIGINT / CTRL_BREAK permite que scrcpy cierre y finalice bien el archivo
        p.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGINT)
        p.wait(timeout=8)
    except subprocess.TimeoutExpired:
        p.terminate()
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.kill()
    except Exception:
        p.terminate()

    saved = current_file
    proc = None
    current_mode = None
    current_file = None

    message = "Proceso detenido."
    if saved:
        message += f" Archivo guardado en: {saved}"
    return jsonify({"status": "ok", "message": message})


@app.route("/status")
def status():
    since = to_int(request.args.get("since"), 0)
    running = proc is not None and proc.poll() is None
    with state_lock:
        total = log_offset + len(log_lines)
        lines = log_lines[max(0, since - log_offset):]
    return jsonify(
        {
            "running": running,
            "mode": current_mode if running else None,
            "file": current_file if running else None,
            "lines": lines,
            "total": total,
        }
    )


# ---------------------------------------------------------------- interfaz
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="es" class="bg-slate-900 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>scrcpy Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen p-6 max-w-4xl mx-auto flex flex-col justify-center">

<div class="bg-slate-800 border border-slate-700 rounded-xl p-6 shadow-2xl">
    <div class="flex justify-between items-center mb-2 border-b border-slate-700 pb-4">
        <div>
            <h1 class="text-xl font-bold tracking-wide text-slate-100">Panel de Control scrcpy</h1>
            <div id="env-info" class="text-[11px] text-slate-400 mt-1">Detectando entorno...</div>
        </div>
        <span id="status-badge" class="px-3 py-1 rounded-full text-xs font-semibold bg-slate-700 text-slate-300 uppercase tracking-wider">Listo</span>
    </div>

    <!-- Dispositivo -->
    <div class="flex gap-2 items-end my-4">
        <div class="flex-1">
            <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Dispositivo</label>
            <select id="serial" class="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                <option value="">Automático (el único conectado)</option>
            </select>
        </div>
        <button type="button" onclick="loadDevices()" class="bg-slate-700 hover:bg-slate-600 text-sm px-4 py-2 rounded cursor-pointer">Actualizar</button>
    </div>

    <!-- Modo -->
    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">¿Qué quieres hacer?</label>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-2">
        <button type="button" id="mode-mirror" onclick="setMode('mirror')" class="mode-btn p-3 rounded-lg text-left cursor-pointer">
            <div class="font-semibold text-white">Mostrar</div>
            <div class="text-xs text-slate-300">Ventana con audio</div>
        </button>
        <button type="button" id="mode-record" onclick="setMode('record')" class="mode-btn p-3 rounded-lg text-left cursor-pointer">
            <div class="font-semibold text-white">Grabar</div>
            <div class="text-xs text-slate-300">Guardar a archivo</div>
        </button>
        <button type="button" id="mode-mirror_record" onclick="setMode('mirror_record')" class="mode-btn p-3 rounded-lg text-left cursor-pointer">
            <div class="font-semibold text-white">Mostrar + Grabar</div>
            <div class="text-xs text-slate-300">Ver y guardar</div>
        </button>
        <button type="button" id="mode-camera" onclick="setMode('camera')" class="mode-btn p-3 rounded-lg text-left cursor-pointer">
            <div class="font-semibold text-white">Cámara virtual</div>
            <div class="text-xs text-slate-300">v4l2 (solo Linux)</div>
        </button>
    </div>
    <p id="mode-hint" class="text-xs text-slate-400 mb-6"></p>

    <!-- Presets -->
    <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Perfil de Configuración</label>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        <button type="button" onclick="setPreset('basica')" id="btn-basica" class="preset-btn p-3 rounded-lg text-left cursor-pointer">
            <div class="font-semibold text-white">Básica</div>
            <div class="text-xs text-slate-300">720p @ 30fps | 8M</div>
        </button>
        <button type="button" onclick="setPreset('media')" id="btn-media" class="preset-btn p-3 rounded-lg text-left cursor-pointer">
            <div class="font-semibold text-white">Media</div>
            <div class="text-xs text-slate-300">1080p @ 60fps | 12M | Opus</div>
        </button>
        <button type="button" onclick="setPreset('avanzada')" id="btn-avanzada" class="preset-btn p-3 rounded-lg text-left cursor-pointer">
            <div class="font-semibold text-white">Avanzada</div>
            <div class="text-xs text-slate-300">Res. Nativa @ 60fps | 16M | Raw</div>
        </button>
    </div>

    <!-- Ajustes de video -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
        <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Resolución Máx. (-m)</label>
            <input type="number" id="max-size" value="1920" class="field">
            <span class="text-[10px] text-slate-400">0 = Nativa / Sin límite</span>
        </div>
        <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">FPS Máx. (--max-fps)</label>
            <input type="number" id="max-fps" value="60" class="field">
        </div>
        <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Tasa de Bits</label>
            <input type="text" id="bit-rate" value="12M" class="field">
        </div>
        <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Códec de Video</label>
            <select id="video-codec" class="field">
                <option value="h264" selected>H.264 (Estable)</option>
                <option value="h265">H.265 / HEVC</option>
                <option value="av1">AV1</option>
            </select>
        </div>
    </div>

    <!-- Audio -->
    <div class="flex items-center gap-2 mb-3">
        <input type="checkbox" id="audio-enabled" checked onchange="applyMode()" class="chk">
        <label for="audio-enabled" class="text-sm font-medium text-slate-300 cursor-pointer">Transmitir audio del teléfono</label>
    </div>
    <div id="audio-box" class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Códec de Audio</label>
            <select id="audio-codec" class="field">
                <option value="opus" selected>Opus (Sincronizado)</option>
                <option value="raw">Raw PCM (Baja Latencia)</option>
                <option value="aac">AAC</option>
                <option value="flac">FLAC</option>
            </select>
        </div>
        <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Fuente de Audio</label>
            <select id="audio-source" class="field">
                <option value="output" selected>Sonido del teléfono</option>
                <option value="mic">Micrófono del teléfono</option>
            </select>
        </div>
        <div>
            <label class="block text-xs font-medium text-slate-300 mb-1">Búfer de audio (ms)</label>
            <input type="number" id="audio-buffer" value="50" min="0" class="field">
            <span class="text-[10px] text-slate-400">Menos = menor latencia (puede entrecortarse)</span>
        </div>
    </div>

    <!-- Opciones por modo -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
        <div data-modes="record mirror_record">
            <label class="block text-xs font-medium text-slate-300 mb-1">Formato Contenedor</label>
            <select id="container" class="field">
                <option value="mkv" selected>MKV (Recomendado)</option>
                <option value="mp4">MP4</option>
            </select>
        </div>
        <div data-modes="camera">
            <label class="block text-xs font-medium text-slate-300 mb-1">Dispositivo v4l2</label>
            <input type="text" id="v4l2-device" value="/dev/video2" class="field">
            <span class="text-[10px] text-slate-400">Requiere el módulo v4l2loopback</span>
        </div>
        <div data-modes="mirror mirror_record">
            <label class="block text-xs font-medium text-slate-300 mb-1">Título de la ventana</label>
            <input type="text" id="window-title" value="Pantalla del celular" class="field">
            <span class="text-[10px] text-slate-400">Útil para elegirla al compartir</span>
        </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-y-3 gap-x-4 mb-6">
        <label data-modes="record camera" class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" id="no-playback" checked class="chk"> Sin ventana (--no-playback)
        </label>
        <label data-modes="mirror mirror_record" class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" id="always-on-top" class="chk"> Siempre visible
        </label>
        <label data-modes="mirror mirror_record" class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" id="borderless" class="chk"> Sin bordes
        </label>
        <label class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" id="no-control" class="chk"> Solo ver (sin controlar)
        </label>
        <label class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" id="stay-awake" class="chk"> Mantener teléfono despierto
        </label>
        <label class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input type="checkbox" id="turn-screen-off" class="chk"> Apagar pantalla del teléfono
        </label>
    </div>

    <!-- Acciones -->
    <div class="flex gap-4 mb-6">
        <button type="button" id="btn-start" onclick="startProcess()" class="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 rounded-lg transition cursor-pointer text-sm tracking-wide uppercase">
            Iniciar
        </button>
        <button type="button" id="btn-stop" onclick="stopProcess()" disabled class="flex-1 bg-slate-700 text-slate-500 font-semibold py-3 rounded-lg cursor-not-allowed text-sm tracking-wide uppercase">
            Detener
        </button>
    </div>

    <!-- Consola -->
    <div class="bg-slate-950 p-4 rounded-lg border border-slate-800">
        <div class="text-xs text-slate-500 mb-2 font-mono uppercase tracking-wider">Consola de Estado</div>
        <pre id="terminal-log" class="text-xs font-mono text-slate-300 h-32 overflow-y-auto whitespace-pre-wrap select-text">Sistema listo.</pre>
    </div>
</div>

<style>
    .field { width: 100%; background: #0f172a; border: 1px solid #334155; border-radius: 0.25rem; padding: 0.5rem; font-size: 0.875rem; color: #fff; }
    .field:focus { outline: none; border-color: #6366f1; }
    .chk { width: 1rem; height: 1rem; cursor: pointer; }
    .mode-btn, .preset-btn { transition: background .15s; }
    .is-off  { border: 1px solid #475569; background: #334155; }
    .is-off:hover { background: #3b4a61; }
    .is-on   { border: 2px solid #6366f1; background: rgba(49,46,129,.4); }
    .is-disabled { opacity: .35; cursor: not-allowed !important; }
</style>

<script>
    const MODE_HINTS = {
        mirror: "Abre una ventana con la pantalla y el sonido del teléfono. Para compartirla en Meet, Discord o Zoom, elige 'Compartir ventana' y selecciona la que tiene el título de abajo.",
        record: "Graba a un archivo en la carpeta 'grabaciones'. Puedes ocultar la ventana con --no-playback.",
        mirror_record: "Muestra la pantalla y al mismo tiempo guarda la grabación.",
        camera: "Envía el video del teléfono a una cámara virtual (v4l2) que puedes elegir como webcam en Meet, Zoom, OBS, etc. No transmite audio por la cámara."
    };

    const PRESETS = {
        basica:   {size: 1280, fps: 30, rate: "8M",  vcodec: "h264", acodec: "aac",  container: "mp4"},
        media:    {size: 1920, fps: 60, rate: "12M", vcodec: "h264", acodec: "opus", container: "mkv"},
        avanzada: {size: 0,    fps: 60, rate: "16M", vcodec: "h264", acodec: "raw",  container: "mkv"}
    };

    let currentMode = "mirror";
    let currentPreset = "media";
    let logSince = 0;
    let running = false;
    let isLinux = false;

    const $ = (id) => document.getElementById(id);

    function log(msg) {
        const el = $('terminal-log');
        el.innerText += "\n[INFO] " + msg;
        el.scrollTop = el.scrollHeight;
    }

    function logRaw(msg) {
        const el = $('terminal-log');
        el.innerText += "\n" + msg;
        el.scrollTop = el.scrollHeight;
    }

    function paintButtons() {
        document.querySelectorAll('.mode-btn').forEach(b => {
            const id = b.id.replace('mode-', '');
            b.className = "mode-btn p-3 rounded-lg text-left cursor-pointer " + (id === currentMode ? "is-on" : "is-off");
        });
        document.querySelectorAll('.preset-btn').forEach(b => {
            const id = b.id.replace('btn-', '');
            b.className = "preset-btn p-3 rounded-lg text-left cursor-pointer " + (id === currentPreset ? "is-on" : "is-off");
        });
        const cam = $('mode-camera');
        if (!isLinux) cam.classList.add('is-disabled');
    }

    function applyMode() {
        document.querySelectorAll('[data-modes]').forEach(el => {
            const modes = el.dataset.modes.split(" ");
            el.classList.toggle('hidden', !modes.includes(currentMode));
        });
        $('audio-box').classList.toggle('hidden', !$('audio-enabled').checked);
        $('mode-hint').innerText = MODE_HINTS[currentMode];
        paintButtons();
    }

    function setMode(mode) {
        if (running) return;
        if (mode === 'camera' && !isLinux) {
            log("La cámara virtual solo está disponible en Linux.");
            return;
        }
        currentMode = mode;
        applyMode();
        log("Modo seleccionado: " + mode);
    }

    function setPreset(name) {
        const p = PRESETS[name];
        currentPreset = name;
        $('max-size').value = p.size;
        $('max-fps').value = p.fps;
        $('bit-rate').value = p.rate;
        $('video-codec').value = p.vcodec;
        $('audio-codec').value = p.acodec;
        $('container').value = p.container;
        paintButtons();
        log("Perfil seleccionado: " + name);
    }

    async function loadDevices() {
        try {
            const r = await fetch('/devices');
            const res = await r.json();
            const sel = $('serial');
            const previous = sel.value;
            sel.innerHTML = '<option value="">Automático (el único conectado)</option>';
            (res.devices || []).forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.serial;
                opt.textContent = (d.model || d.serial) + " [" + d.serial + "] — " + d.state;
                if (d.state !== 'device') opt.disabled = true;
                sel.appendChild(opt);
            });
            sel.value = previous;
            if (res.status === 'error') log(res.message);
            else log((res.devices || []).length + " dispositivo(s) encontrado(s).");
        } catch (e) {
            log("No se pudo consultar los dispositivos.");
        }
    }

    async function loadInfo() {
        try {
            const r = await fetch('/info');
            const info = await r.json();
            isLinux = info.platform === 'linux';
            const parts = [info.platform];
            parts.push(info.scrcpy ? (info.version || "scrcpy") : "scrcpy NO encontrado");
            $('env-info').innerText = parts.join(" · ");
            if (!info.scrcpy) log("No se encontró scrcpy. Instálalo o define la variable SCRCPY.");
        } catch (e) {
            $('env-info').innerText = "Sin conexión con el servidor";
        }
        paintButtons();
    }

    function gatherData() {
        return {
            mode: currentMode,
            serial: $('serial').value,
            max_size: $('max-size').value,
            max_fps: $('max-fps').value,
            bit_rate: $('bit-rate').value,
            video_codec: $('video-codec').value,
            audio_enabled: $('audio-enabled').checked,
            audio_codec: $('audio-codec').value,
            audio_source: $('audio-source').value,
            audio_buffer: $('audio-buffer').value,
            container: $('container').value,
            v4l2_device: $('v4l2-device').value,
            window_title: $('window-title').value,
            no_playback: $('no-playback').checked,
            always_on_top: $('always-on-top').checked,
            borderless: $('borderless').checked,
            no_control: $('no-control').checked,
            stay_awake: $('stay-awake').checked,
            turn_screen_off: $('turn-screen-off').checked
        };
    }

    async function startProcess() {
        log("Enviando orden de ejecución...");
        try {
            const r = await fetch('/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(gatherData())
            });
            const res = await r.json();
            log(res.message);
            if (res.status === 'ok') {
                logSince = 0;
                setUIState(true);
            }
        } catch (e) {
            log("Error de comunicación con el servidor local.");
        }
    }

    async function stopProcess() {
        log("Finalizando proceso...");
        try {
            const r = await fetch('/stop', {method: 'POST'});
            const res = await r.json();
            log(res.message);
            setUIState(false);
        } catch (e) {
            log("Error al detener el proceso.");
        }
    }

    function setUIState(isRunning) {
        running = isRunning;
        const badge = $('status-badge');
        const btnStart = $('btn-start');
        const btnStop = $('btn-stop');

        if (isRunning) {
            const labels = {mirror: "Mostrando", record: "Grabando", mirror_record: "Mostrando + Grabando", camera: "Cámara activa"};
            badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-red-900/80 text-red-200 border border-red-700 uppercase tracking-wider";
            badge.innerText = labels[currentMode] || "Activo";
            btnStart.disabled = true;
            btnStart.className = "flex-1 bg-slate-700 text-slate-500 font-semibold py-3 rounded-lg cursor-not-allowed text-sm tracking-wide uppercase";
            btnStop.disabled = false;
            btnStop.className = "flex-1 bg-red-600 hover:bg-red-500 text-white font-semibold py-3 rounded-lg transition cursor-pointer text-sm tracking-wide uppercase";
        } else {
            badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-slate-700 text-slate-300 uppercase tracking-wider";
            badge.innerText = "Listo";
            btnStart.disabled = false;
            btnStart.className = "flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 rounded-lg transition cursor-pointer text-sm tracking-wide uppercase";
            btnStop.disabled = true;
            btnStop.className = "flex-1 bg-slate-700 text-slate-500 font-semibold py-3 rounded-lg cursor-not-allowed text-sm tracking-wide uppercase";
        }
    }

    // Consulta periódica: muestra la salida de scrcpy y detecta si se cerró solo
    async function poll() {
        try {
            const r = await fetch('/status?since=' + logSince);
            const s = await r.json();
            (s.lines || []).forEach(l => logRaw(l));
            logSince = s.total;
            if (running && !s.running) {
                log("El proceso terminó.");
                setUIState(false);
            }
        } catch (e) { /* servidor no disponible */ }
    }

    applyMode();
    setPreset('media');
    loadInfo().then(() => { applyMode(); loadDevices(); });
    setInterval(poll, 1500);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
