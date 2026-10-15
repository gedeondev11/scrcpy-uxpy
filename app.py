import subprocess
import os
import signal
import datetime
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
scrcpy_process = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es" class="bg-slate-900 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>scrcpy Recorder</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen p-6 max-w-4xl mx-auto flex flex-col justify-center select-none">

    <div class="bg-slate-800 border border-slate-700 rounded-xl p-6 shadow-2xl">
        <div class="flex justify-between items-center mb-6 border-b border-slate-700 pb-4">
            <h1 class="text-xl font-bold tracking-wide text-slate-100">Panel de Control scrcpy</h1>
            <span id="status-badge" class="px-3 py-1 rounded-full text-xs font-semibold bg-slate-700 text-slate-300 uppercase tracking-wider">
                Listo
            </span>
        </div>

        <!-- Presets -->
        <label class="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Perfil de Configuración</label>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
            <button type="button" onclick="setPreset('basica')" id="btn-basica" class="preset-btn p-3 rounded-lg border border-slate-600 bg-slate-700 hover:bg-slate-650 transition text-left cursor-pointer">
                <div class="font-semibold text-white">Básica</div>
                <div class="text-xs text-slate-300">720p @ 30fps | 8M</div>
            </button>
            <button type="button" onclick="setPreset('media')" id="btn-media" class="preset-btn p-3 rounded-lg border-2 border-indigo-500 bg-indigo-900/40 text-left cursor-pointer">
                <div class="font-semibold text-white">Media</div>
                <div class="text-xs text-indigo-200">1080p @ 60fps | 12M | Opus</div>
            </button>
            <button type="button" onclick="setPreset('avanzada')" id="btn-avanzada" class="preset-btn p-3 rounded-lg border border-slate-600 bg-slate-700 hover:bg-slate-650 transition text-left cursor-pointer">
                <div class="font-semibold text-white">Avanzada</div>
                <div class="text-xs text-slate-300">Res. Nativa @ 60fps | 16M | Raw</div>
            </button>
        </div>

        <!-- Ajustes -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
            <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Resolución Máxima (-m)</label>
                <input type="number" id="max-size" value="1920" class="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                <span class="text-[10px] text-slate-400">0 = Nativa / Sin límite</span>
            </div>
            <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">FPS Máximos (--max-fps)</label>
                <input type="number" id="max-fps" value="60" class="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
            </div>
            <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Tasa de Bits (--video-bit-rate)</label>
                <input type="text" id="bit-rate" value="12M" class="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
            <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Códec de Video</label>
                <select id="video-codec" class="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                    <option value="h264" selected>H.264 (Estable)</option>
                    <option value="h265">H.265 / HEVC</option>
                    <option value="av1">AV1</option>
                </select>
            </div>
            <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Códec de Audio</label>
                <select id="audio-codec" class="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                    <option value="opus" selected>Opus (Sincronizado)</option>
                    <option value="raw">Raw PCM (Baja Latencia)</option>
                    <option value="aac">AAC</option>
                </select>
            </div>
            <div>
                <label class="block text-xs font-medium text-slate-300 mb-1">Formato Contenedor</label>
                <select id="container" class="w-full bg-slate-900 border border-slate-700 rounded p-2 text-sm text-white focus:outline-none focus:border-indigo-500">
                    <option value="mkv" selected>MKV (Recomendado)</option>
                    <option value="mp4">MP4</option>
                </select>
            </div>
        </div>

        <div class="flex items-center gap-2 mb-6">
            <input type="checkbox" id="no-playback" checked class="w-4 h-4 text-indigo-600 rounded bg-slate-900 border-slate-700 cursor-pointer">
            <label for="no-playback" class="text-sm font-medium text-slate-300 cursor-pointer">Modo sin previsualización (--no-playback)</label>
        </div>

        <!-- Botones de Acción -->
        <div class="flex gap-4 mb-6">
            <button type="button" id="btn-start" onclick="startRecording()" class="flex-1 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3 rounded-lg transition cursor-pointer text-sm tracking-wide uppercase">
                Iniciar Grabación
            </button>
            <button type="button" id="btn-stop" onclick="stopRecording()" disabled class="flex-1 bg-slate-700 text-slate-500 font-semibold py-3 rounded-lg cursor-not-allowed text-sm tracking-wide uppercase">
                Detener Grabación
            </button>
        </div>

        <!-- Salida de la Consola -->
        <div class="bg-slate-950 p-4 rounded-lg border border-slate-800">
            <div class="text-xs text-slate-500 mb-2 font-mono uppercase tracking-wider">Consola de Estado</div>
            <pre id="terminal-log" class="text-xs font-mono text-slate-300 h-24 overflow-y-auto whitespace-pre-wrap">Sistema listo.</pre>
        </div>
    </div>

    <script>
        function setPreset(type) {
            const btnBasica = document.getElementById('btn-basica');
            const btnMedia = document.getElementById('btn-media');
            const btnAvanzada = document.getElementById('btn-avanzada');

            const activeStyle = "preset-btn p-3 rounded-lg border-2 border-indigo-500 bg-indigo-900/40 text-left cursor-pointer";
            const inactiveStyle = "preset-btn p-3 rounded-lg border border-slate-600 bg-slate-700 hover:bg-slate-650 transition text-left cursor-pointer";

            btnBasica.className = inactiveStyle;
            btnMedia.className = inactiveStyle;
            btnAvanzada.className = inactiveStyle;

            if (type === 'basica') {
                btnBasica.className = activeStyle;
                document.getElementById('max-size').value = 1280;
                document.getElementById('max-fps').value = 30;
                document.getElementById('bit-rate').value = "8M";
                document.getElementById('video-codec').value = "h264";
                document.getElementById('audio-codec').value = "aac";
                document.getElementById('container').value = "mp4";
            } else if (type === 'media') {
                btnMedia.className = activeStyle;
                document.getElementById('max-size').value = 1920;
                document.getElementById('max-fps').value = 60;
                document.getElementById('bit-rate').value = "12M";
                document.getElementById('video-codec').value = "h264";
                document.getElementById('audio-codec').value = "opus";
                document.getElementById('container').value = "mkv";
            } else if (type === 'avanzada') {
                btnAvanzada.className = activeStyle;
                document.getElementById('max-size').value = 0;
                document.getElementById('max-fps').value = 60;
                document.getElementById('bit-rate').value = "16M";
                document.getElementById('video-codec').value = "h264";
                document.getElementById('audio-codec').value = "raw";
                document.getElementById('container').value = "mkv";
            }
            log("Perfil seleccionado: " + type);
        }

        async function startRecording() {
            const data = {
                max_size: document.getElementById('max-size').value,
                max_fps: document.getElementById('max-fps').value,
                bit_rate: document.getElementById('bit-rate').value,
                video_codec: document.getElementById('video-codec').value,
                audio_codec: document.getElementById('audio-codec').value,
                container: document.getElementById('container').value,
                no_playback: document.getElementById('no-playback').checked
            };

            log("Enviando orden de ejecución...");

            try {
                const response = await fetch('/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });

                const result = await response.json();
                log(result.message);

                if (result.status === 'ok') {
                    setUIState(true);
                }
            } catch(e) {
                log("Error de comunicación con el servidor local.");
            }
        }

        async function stopRecording() {
            log("Finalizando proceso...");
            try {
                const response = await fetch('/stop', {method: 'POST'});
                const result = await response.json();
                log(result.message);
                setUIState(false);
            } catch(e) {
                log("Error al detener el proceso.");
            }
        }

        function setUIState(isRecording) {
            const badge = document.getElementById('status-badge');
            const btnStart = document.getElementById('btn-start');
            const btnStop = document.getElementById('btn-stop');

            if (isRecording) {
                badge.className = "px-3 py-1 rounded-full text-xs font-semibold bg-red-900/80 text-red-200 border border-red-700 uppercase tracking-wider";
                badge.innerText = "Grabando";
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

        function log(msg) {
            const el = document.getElementById('terminal-log');
            el.innerText += "\\n[INFO] " + msg;
            el.scrollTop = el.scrollHeight;
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/start', methods=['POST'])
def start():
    global scrcpy_process
    
    if scrcpy_process is not None and scrcpy_process.poll() is None:
        return jsonify({'status': 'error', 'message': 'Ya existe una grabación activa.'})

    data = request.json
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"grabacion_{now}.{data['container']}"

    cmd = ["./scrcpy", f"--record={filename}"]

    if data['no_playback']:
        cmd.append("--no-playback")
    
    if int(data['max_size']) > 0:
        cmd.extend(["-m", str(data['max_size'])])
        
    if int(data['max_fps']) > 0:
        cmd.extend(["--max-fps", str(data['max_fps'])])
        
    cmd.extend(["--video-bit-rate", data['bit_rate']])
    cmd.extend(["--video-codec", data['video_codec']])
    cmd.extend(["--audio-codec", data['audio_codec']])

    try:
        scrcpy_process = subprocess.Popen(cmd)
        cmd_str = " ".join(cmd)
        return jsonify({'status': 'ok', 'message': f"Ejecutado: {cmd_str}\nArchivo: {filename}"})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Error de ejecución: {str(e)}"})

@app.route('/stop', methods=['POST'])
def stop():
    global scrcpy_process
    
    if scrcpy_process is None or scrcpy_process.poll() is not None:
        return jsonify({'status': 'error', 'message': 'No hay grabaciones en curso.'})

    scrcpy_process.send_signal(signal.SIGINT)
    scrcpy_process.wait(timeout=5)
    scrcpy_process = None

    return jsonify({'status': 'ok', 'message': 'Grabación finalizada y guardada correctamente.'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)