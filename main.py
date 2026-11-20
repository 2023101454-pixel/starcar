"""
STAR-CAR · Modelo SC-1 · Creado por STARKING
Control USB para carro RC (Arduino Nano) + asistente IA (Groq) con voz.
Funciona en PC (python main.py) y en Android (.apk con Buildozer).
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback

from kivy.config import Config
from kivy.utils import platform

# python main.py --celular  ->  simula en PC el tamaño de un celular horizontal
if platform != "android" and "--celular" in sys.argv:
    sys.argv.remove("--celular")
    Config.set("graphics", "width", "820")
    Config.set("graphics", "height", "370")
    Config.set("graphics", "resizable", "0")
elif platform != "android":
    Config.set("graphics", "width", "1000")
    Config.set("graphics", "height", "500")

from kivy.app import App
from kivy.base import ExceptionHandler, ExceptionManager
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.utils import escape_markup

import requests

import config

if platform == "android":
    from usb4a import usb
    from usbserial4a import serial4a as serial
else:
    import serial
    from serial.tools import list_ports

VERSION = "1.1"
BAUD = 9600
VEL_MIN, VEL_MAX = 50, 255
MAX_PASOS = 24
MAX_PASO_MS = 1500     # a máxima potencia los pasos deben ser cortos
MAX_TOTAL_MS = 12000
REQ_VOZ = 4242

# Paleta STAR-CAR
BG = (0.043, 0.059, 0.102, 1)
OK = (0.40, 0.87, 0.47, 1)
ERR = (0.94, 0.33, 0.31, 1)
ACCENT = (0.0, 0.90, 1.0, 1)
GOLD = (1.0, 0.78, 0.34, 1)

Window.clearcolor = BG
Window.softinput_mode = "below_target"  # el teclado no tapa el cuadro de texto


# ======================================================================
#  Registro de errores: la app ya no se cierra por una excepción
# ======================================================================
RUTA_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "starcar_log.txt")


def registrar_error(texto):
    try:
        with open(RUTA_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + texto + "\n\n")
    except Exception:
        pass
    print(texto)


class ManejadorErrores(ExceptionHandler):
    def handle_exception(self, inst):
        registrar_error("".join(traceback.format_exception(type(inst), inst, inst.__traceback__)))
        try:
            app = App.get_running_app()
            if app:
                app.parar_por_error()  # ante cualquier fallo, el carro se detiene
        except Exception:
            pass
        return ExceptionManager.PASS  # sigue corriendo en vez de cerrarse


ExceptionManager.add_handler(ManejadorErrores())


def _hook_hilos(args):
    registrar_error("".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                         args.exc_traceback)))


threading.excepthook = _hook_hilos


KV = """
<Panel>:
    padding: dp(10)
    spacing: dp(6)
    canvas.before:
        Color:
            rgba: 0.075, 0.10, 0.17, 1
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14),]
        Color:
            rgba: 0.12, 0.17, 0.28, 1
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(14))
            width: 1

<Header>:
    canvas.before:
        Color:
            rgba: 0.06, 0.085, 0.15, 1
        Rectangle:
            pos: self.pos
            size: self.size
    canvas.after:
        Color:
            rgba: 0.0, 0.90, 1.0, 1
        Rectangle:
            pos: self.x, self.y
            size: self.width, dp(2)

<Banner>:
    canvas.before:
        Color:
            rgba: 0.28, 0.17, 0.02, 1
        Rectangle:
            pos: self.pos
            size: self.size
        Color:
            rgba: 1, 0.78, 0.34, 1
        Rectangle:
            pos: self.x, self.y
            size: self.width, dp(2)

<PadButton>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    bold: True
    always_release: True
    color: (0.04, 0.06, 0.1, 1) if (self.activa or self.state == 'down') else (0.92, 0.95, 1, 1)
    canvas.before:
        Color:
            rgba: (0.0, 0.90, 1.0, 1) if (self.activa or self.state == 'down') else self.color_base
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(18),]
    canvas.after:
        Color:
            rgba: self.color
        Triangle:
            points: self.tri

<Toggle>:
    background_normal: ''
    background_down: ''
    background_color: 0, 0, 0, 0
    color: (0.04, 0.06, 0.1, 1) if self.state == 'down' else (0.85, 0.9, 1, 1)
    canvas.before:
        Color:
            rgba: (0.0, 0.90, 1.0, 1) if self.state == 'down' else (0.13, 0.18, 0.29, 1)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10),]
"""


# ======================================================================
#  Widgets
# ======================================================================
class Panel(BoxLayout):
    pass


class Header(BoxLayout):
    pass


class Banner(BoxLayout):
    pass


class Toggle(ToggleButton):
    pass


class PadButton(Button):
    activa = BooleanProperty(False)
    color_base = ListProperty([0.13, 0.18, 0.29, 1])
    direccion = StringProperty("")
    tri = ListProperty([0, 0, 0, 0, 0, 0])

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(pos=self._calc_tri, size=self._calc_tri, direccion=self._calc_tri)
        self._calc_tri()

    def _calc_tri(self, *_):
        d = self.direccion
        if not d:
            self.tri = [0, 0, 0, 0, 0, 0]
            return
        cx, cy = self.center
        s = min(self.width, self.height) * 0.26
        if d == "up":
            p = [cx - s, cy - s * 0.8, cx + s, cy - s * 0.8, cx, cy + s * 0.9]
        elif d == "down":
            p = [cx - s, cy + s * 0.8, cx + s, cy + s * 0.8, cx, cy - s * 0.9]
        elif d == "left":
            p = [cx + s * 0.8, cy - s, cx + s * 0.8, cy + s, cx - s * 0.9, cy]
        else:
            p = [cx - s * 0.8, cy - s, cx - s * 0.8, cy + s, cx + s * 0.9, cy]
        self.tri = p


def titulo(texto):
    return Label(text=texto, size_hint_y=None, height=dp(22), bold=True,
                 color=ACCENT, font_size="12sp")


def etiqueta_izq(texto, **kw):
    lbl = Label(text=texto, markup=True, halign="left", valign="middle", **kw)
    lbl.bind(size=lambda i, s: setattr(i, "text_size", s))
    return lbl


def texto_scroll():
    """ScrollView con una Label larga adentro. Devuelve (scroll, label)."""
    sc = ScrollView(bar_width=dp(4))
    lbl = Label(markup=True, size_hint_y=None, halign="left", valign="top", font_size="14sp")
    lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)))

    def ajustar(i, ts):
        i.height = max(ts[1] + dp(8), sc.height)
        sc.scroll_y = 0

    lbl.bind(texture_size=ajustar)
    sc.add_widget(lbl)
    return sc, lbl


# ======================================================================
#  Enlace serial: la escritura va en un hilo aparte (la UI nunca se congela)
# ======================================================================
class Enlace:
    def __init__(self, port, al_fallar):
        self.port = port
        self.al_fallar = al_fallar
        self._cmd = None
        self._lock = threading.Lock()
        self._evento = threading.Event()
        self._vivo = True
        threading.Thread(target=self._run, daemon=True).start()

    def enviar(self, texto):
        with self._lock:
            self._cmd = texto  # solo importa la orden más reciente
        self._evento.set()

    def _run(self):
        while self._vivo:
            self._evento.wait()
            self._evento.clear()
            if not self._vivo:
                break
            with self._lock:
                cmd, self._cmd = self._cmd, None
            if cmd is None:
                continue
            try:
                self.port.write(cmd.encode("utf-8"))
            except Exception:
                self._vivo = False
                Clock.schedule_once(lambda dt: self.al_fallar(), 0)
                break

    def cerrar(self):
        self._vivo = False
        self._evento.set()
        try:
            self.port.close()
        except Exception:
            pass


CHIPS_USB = {0x1A86: "chip CH340 (típico de Nano clon)", 0x0403: "chip FTDI",
             0x10C4: "chip CP210x", 0x2341: "Arduino original", 0x2A03: "Arduino"}


def elegir_puerto_pc():
    """Escoge el puerto del Arduino y evita los puertos Bluetooth."""
    candidatos = []
    for p in list_ports.comports():
        desc = ((p.description or "") + " " + (p.manufacturer or "")).lower()
        if "bluetooth" in desc:
            continue
        conocido = (p.vid in CHIPS_USB) or any(
            x in desc for x in ("arduino", "ch340", "usb-serial", "usb serial", "cp210", "ftdi"))
        candidatos.append((2 if conocido else 1, p.device))
    candidatos.sort(reverse=True)
    return candidatos[0][1] if candidatos else None


# ======================================================================
#  Voz (respuesta hablada) — en PC usa un proceso aparte para no tumbar la app
# ======================================================================
_tts_proc = None


def callar_voz():
    global _tts_proc
    try:
        if _tts_proc is not None and _tts_proc.poll() is None:
            _tts_proc.terminate()
    except Exception:
        pass
    _tts_proc = None


def hablar(texto):
    global _tts_proc
    try:
        if platform == "android":
            from plyer import tts
            tts.speak(texto)
        elif platform == "win":
            callar_voz()
            env = dict(os.environ)
            env["STARCAR_TTS"] = texto
            script = ("Add-Type -AssemblyName System.Speech; "
                      "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                      "$s.Speak($env:STARCAR_TTS)")
            _tts_proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", script], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000)  # sin ventana
        elif platform == "macosx":
            subprocess.Popen(["say", texto])
        else:
            subprocess.Popen(["espeak", "-v", "es", texto])
    except Exception:
        pass


# ======================================================================
#  Groq (IA)
# ======================================================================
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """Eres STAR-AI, la inteligencia a bordo de STAR-CAR, un carro a control remoto modelo SC-1 creado por Starking.
Hablas en español, con personalidad creativa, simpática y segura, como un copiloto de carreras. Respuestas cortas (1 a 3 frases), porque se leen en voz alta.

Respondes SIEMPRE con un único objeto JSON y nada más:
{"habla": "lo que dices en voz alta", "pasos": [{"m1": 0, "m2": 0, "ms": 500}]}

Reglas:
- "pasos" es la maniobra que el carro ejecuta. Déjalo vacío [] si solo conversan.
- m1 = motor de dirección: -1 izquierda, 1 derecha, 0 recto.
- m2 = llantas traseras: -1 adelante, 1 atrás, 0 parado.
- Solo se permiten los valores -1, 0 y 1. La app SIEMPRE aplica la potencia máxima de los dos motores (así no se atascan), por eso el control se logra con la duración de cada paso y alternando pasos.
- ms = duración del paso en milisegundos (100 a __MAXPASOMS__). Máximo __MAXP__ pasos y __MAXT__ ms en total. Como el carro va a tope, usa pasos cortos.
- Ejemplo de zigzag: [{"m1":-1,"m2":-1,"ms":500},{"m1":1,"m2":-1,"ms":500},{"m1":-1,"m2":-1,"ms":500},{"m1":1,"m2":-1,"ms":500},{"m1":0,"m2":0,"ms":100}]
- Otros trucos: círculo (m1 fijo con m2 avanzando), vaivén (adelante y atrás), baile (cambios rápidos de dirección), salida de carrera (adelante recto), reversa con giro. Sé creativo dentro de esos límites.
- El carro NO tiene sensores: no sabes qué hay delante. Si la maniobra es amplia, pide al usuario que despeje el espacio. El usuario puede cortar el truco diciendo "para" o pulsando PARAR TRUCO.
- Si piden algo peligroso o fuera de los límites, dilo con humor y propón una versión segura.
- Estado actual del carro: __ESTADO__
"""

PALABRAS_PARAR = {"para", "parar", "pare", "stop", "detente", "detén", "deten", "alto",
                  "corta", "corte", "cortar", "cancela", "cancelar", "basta", "frena", "frenar"}


class ErrorGroq(Exception):
    pass


def clave_valida():
    k = (config.GROQ_API_KEY or "").strip()
    return bool(k) and not k.startswith("PEGA")


def llamar_groq(mensajes, max_tokens=1200, json_mode=True):
    if not clave_valida():
        raise ErrorGroq("Falta la API key de Groq: pégala en config.py")
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY.strip()}",
               "Content-Type": "application/json"}
    ultimo = None
    for modelo in (config.GROQ_MODEL, config.GROQ_MODEL_RESPALDO):
        for completo in (True, False):
            body = {"model": modelo, "messages": mensajes,
                    "temperature": 0.7, "max_tokens": max_tokens}
            if completo:
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                body["reasoning_effort"] = "low"
            try:
                r = requests.post(GROQ_URL, headers=headers, json=body, timeout=30)
            except requests.exceptions.RequestException as e:
                raise ErrorGroq("Sin internet o Groq no responde.") from e
            if r.status_code == 200:
                texto = r.json()["choices"][0]["message"].get("content")
                if texto:
                    return texto
                ultimo = "Groq devolvió una respuesta vacía."
                continue
            if r.status_code == 401:
                raise ErrorGroq("La API key de Groq no es válida o fue revocada (revisa config.py).")
            if r.status_code == 429:
                raise ErrorGroq("Groq alcanzó su límite de uso. Espera un momento.")
            ultimo = f"Groq respondió con error {r.status_code}."
    raise ErrorGroq(ultimo or "Error desconocido con Groq.")


def preguntar_groq(historial, estado):
    sistema = (SYSTEM_PROMPT
               .replace("__MAXPASOMS__", str(MAX_PASO_MS))
               .replace("__MAXP__", str(MAX_PASOS))
               .replace("__MAXT__", str(MAX_TOTAL_MS))
               .replace("__ESTADO__", estado))
    return llamar_groq([{"role": "system", "content": sistema}] + historial)


def extraer_json(texto):
    t = texto.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1])


def _signo(v):
    v = float(v)
    return 1 if v > 0 else (-1 if v < 0 else 0)


def sanear_pasos(crudos):
    """Valida lo que devuelve la IA: solo -1/0/1, duración y cantidad limitadas."""
    pasos, total = [], 0
    if not isinstance(crudos, list):
        return pasos
    for p in crudos[:MAX_PASOS]:
        try:
            m1 = _signo(p.get("m1", 0))
            m2 = _signo(p.get("m2", 0))
            ms = max(100, min(MAX_PASO_MS, int(float(p.get("ms", 500)))))
        except Exception:
            continue
        if total + ms > MAX_TOTAL_MS:
            break
        total += ms
        pasos.append({"m1": m1, "m2": m2, "ms": ms})
    return pasos


def potencia(signo, valor):
    return signo * max(VEL_MIN, min(VEL_MAX, int(valor))) if signo else 0


# ======================================================================
#  App
# ======================================================================
class StarCarApp(App):
    def build(self):
        Builder.load_string(KV)
        self.title = "STAR-CAR SC-1"
        self.conn = None            # Enlace (o None)
        self.conectando = False
        self.nombre_puerto = None
        self.pidiendo_permiso = False
        self.keys = {k: False for k in "wasd"}
        self.botones = {}
        self.val_m1 = 0
        self.val_m2 = 0
        self._ultimo = None
        self.maniobra = []
        self.total_pasos = 0
        self.maniobra_activa = False
        self._ev = None
        self.token = 0              # sube con cada STOP: invalida respuestas de la IA en camino
        self.historial = []
        self.mensajes = []
        self.pensando = False
        self.diag_lineas = []
        self._activo = True

        root = BoxLayout(orientation="vertical")
        root.add_widget(self.crear_header())

        # Franja visible mientras la IA ejecuta un truco
        self.banner = Banner(size_hint_y=None, height=0, opacity=0, disabled=True,
                             padding=(dp(12), dp(4)), spacing=dp(10))
        self.lbl_banner = etiqueta_izq("", font_size="13sp")
        self.banner.add_widget(self.lbl_banner)
        btn = PadButton(text="PARAR TRUCO", font_size="14sp", size_hint_x=None, width=dp(150),
                        color_base=[0.85, 0.2, 0.1, 1])
        btn.bind(on_release=lambda *_: self.parar_truco())
        self.banner.add_widget(btn)
        root.add_widget(self.banner)

        self.sm = ScreenManager(transition=NoTransition())
        self.sm.add_widget(self.pantalla_control())
        self.sm.add_widget(self.pantalla_ia())
        self.sm.add_widget(self.pantalla_diag())
        cont = BoxLayout(padding=dp(10))
        cont.add_widget(self.sm)
        root.add_widget(cont)

        self.on_slider()
        self.actualizar_estado()
        self.chat_ia("Hola, soy STAR-AI, el copiloto de Star-Car. Pídeme que converse "
                     "contigo o que haga un truco, por ejemplo: haz un zigzag. "
                     "Para cortarlo di o escribe \"para\".")

        Window.bind(on_key_down=self.key_down, on_key_up=self.key_up)
        if platform == "android":
            from android import activity
            activity.bind(on_activity_result=self.on_activity_result)
            Clock.schedule_interval(self.buscar_dispositivo_android, 1.0)
        else:
            threading.Thread(target=self._vigilante_pc, daemon=True).start()
        return root

    # ------------------------------------------------------------------
    #  Header
    # ------------------------------------------------------------------
    def crear_header(self):
        h = Header(size_hint_y=None, height=dp(58), padding=(dp(12), dp(4)), spacing=dp(8))

        marca = BoxLayout(orientation="vertical", size_hint_x=0.30)
        marca.add_widget(etiqueta_izq("[b][color=00e5ff]STAR[/color]-CAR[/b]", font_size="24sp"))
        marca.add_widget(etiqueta_izq("MODELO SC-1  ·  CREADO POR [color=ffc857][b]STARKING[/b][/color]",
                                      font_size="10sp"))
        h.add_widget(marca)

        nav = BoxLayout(spacing=dp(6), size_hint_x=0.42, padding=(0, dp(6)))
        for nombre, texto in (("control", "CONTROL"), ("ia", "ASISTENTE IA"), ("diag", "DIAGNÓSTICO")):
            b = Toggle(text=texto, group="nav", allow_no_selection=False,
                       font_size="12sp", bold=True)
            if nombre == "control":
                b.state = "down"
            b.bind(on_press=lambda inst, n=nombre: self.ir_a(n))
            nav.add_widget(b)
        h.add_widget(nav)

        self.lbl_estado = Label(text="", markup=True, halign="right", valign="middle",
                                size_hint_x=0.17, font_size="12sp")
        self.lbl_estado.bind(size=lambda i, s: setattr(i, "text_size", s))
        h.add_widget(self.lbl_estado)

        stop = PadButton(text="STOP", font_size="18sp", size_hint_x=0.11,
                         color_base=[0.78, 0.16, 0.16, 1])
        stop.bind(on_press=lambda *_: self.detener_todo())
        h.add_widget(stop)
        return h

    def ir_a(self, nombre):
        self.sm.current = nombre
        if nombre != "control":
            self.liberar_teclas()
            if not self.maniobra_activa:
                self.actualizar_movimiento()

    def actualizar_estado(self):
        if self.conn:
            linea1 = "[color=66dd77][b]USB CONECTADO[/b][/color]"
        elif self.conectando:
            linea1 = "[color=ffc857][b]CONECTANDO...[/b][/color]"
        else:
            linea1 = "[color=ef5350][b]SIN USB[/b][/color]"
        if self.maniobra_activa:
            linea2 = "[color=ffc857]IA EN MANIOBRA[/color]"
        else:
            linea2 = "[color=8899bb]modo manual[/color]"
        self.lbl_estado.text = linea1 + "\n" + linea2

    def mostrar_banner(self, mostrar, texto=""):
        if mostrar:
            self.banner.height = dp(44)
            self.banner.opacity = 1
            self.banner.disabled = False
            self.lbl_banner.text = texto
        else:
            self.banner.height = 0
            self.banner.opacity = 0
            self.banner.disabled = True

    # ------------------------------------------------------------------
    #  Pantalla CONTROL
    # ------------------------------------------------------------------
    def pantalla_control(self):
        s = Screen(name="control")
        fila = BoxLayout(spacing=dp(10))

        izq = Panel(orientation="vertical", size_hint_x=0.31)
        izq.add_widget(titulo("DIRECCIÓN  ·  A / D"))
        f = BoxLayout(spacing=dp(10))
        f.add_widget(self.tecla("a", "left"))
        f.add_widget(self.tecla("d", "right"))
        izq.add_widget(f)

        centro = BoxLayout(orientation="vertical", size_hint_x=0.38, spacing=dp(8))
        ajustes = Panel(orientation="vertical")
        self.lbl_atras = Label(text="", size_hint_y=None, height=dp(20), font_size="12sp")
        self.sl_atras = Slider(min=VEL_MIN, max=VEL_MAX, value=180, step=5,
                               value_track=True, value_track_color=ACCENT,
                               cursor_size=(dp(28), dp(28)))
        self.lbl_dir = Label(text="", size_hint_y=None, height=dp(20), font_size="12sp")
        self.sl_dir = Slider(min=VEL_MIN, max=VEL_MAX, value=180, step=5,
                             value_track=True, value_track_color=ACCENT,
                             cursor_size=(dp(28), dp(28)))
        self.sl_atras.bind(value=self.on_slider)
        self.sl_dir.bind(value=self.on_slider)
        for w in (self.lbl_atras, self.sl_atras, self.lbl_dir, self.sl_dir):
            ajustes.add_widget(w)

        inv = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        self.inv_atras = Toggle(text="Invertir llantas", font_size="12sp")
        self.inv_dir = Toggle(text="Invertir dirección", font_size="12sp")
        self.inv_atras.bind(state=lambda *_: self.actualizar_movimiento())
        self.inv_dir.bind(state=lambda *_: self.actualizar_movimiento())
        inv.add_widget(self.inv_atras)
        inv.add_widget(self.inv_dir)
        ajustes.add_widget(inv)
        centro.add_widget(ajustes)

        self.lbl_monitor = Label(text="M1:+0   M2:+0", size_hint_y=None, height=dp(26),
                                 font_size="14sp", color=ACCENT, bold=True)
        centro.add_widget(self.lbl_monitor)

        der = Panel(orientation="vertical", size_hint_x=0.31)
        der.add_widget(titulo("LLANTAS  ·  W / S"))
        col = BoxLayout(orientation="vertical", spacing=dp(10))
        col.add_widget(self.tecla("w", "up"))
        col.add_widget(self.tecla("s", "down"))
        der.add_widget(col)

        fila.add_widget(izq)
        fila.add_widget(centro)
        fila.add_widget(der)
        s.add_widget(fila)
        return s

    def tecla(self, k, direccion):
        b = PadButton(direccion=direccion)
        b.bind(on_press=lambda *_: self.set_tecla(k, True))
        b.bind(on_release=lambda *_: self.set_tecla(k, False))
        self.botones[k] = b
        return b

    def set_tecla(self, k, estado):
        if self.keys[k] == estado:
            return
        if estado and self.maniobra_activa:
            self.cancelar_maniobra()  # si tocas un control, tú tomas el mando
        self.keys[k] = estado
        self.botones[k].activa = estado
        self.actualizar_movimiento()

    def liberar_teclas(self):
        for k in self.keys:
            self.keys[k] = False
            if k in self.botones:
                self.botones[k].activa = False

    # ------------------------------------------------------------------
    #  Teclado (PC)
    # ------------------------------------------------------------------
    MAPA = {119: "w", 97: "a", 115: "s", 100: "d",
            273: "w", 274: "s", 275: "d", 276: "a"}

    def key_down(self, window, key, scancode, codepoint, modifier):
        if key == 32 and self.maniobra_activa:   # espacio corta el truco en cualquier pantalla
            if self.sm.current == "control":
                self.detener_todo()
            return False
        if self.sm.current != "control":  # no mover el carro mientras escribes
            return False
        if key == 32:
            self.detener_todo()
        elif key in self.MAPA:
            self.set_tecla(self.MAPA[key], True)
        return False

    def key_up(self, window, key, scancode):
        if self.sm.current == "control" and key in self.MAPA:
            self.set_tecla(self.MAPA[key], False)
        return False

    # ------------------------------------------------------------------
    #  Pantalla ASISTENTE IA
    # ------------------------------------------------------------------
    def pantalla_ia(self):
        s = Screen(name="ia")
        caja = BoxLayout(orientation="vertical", spacing=dp(8))

        panel = Panel(orientation="vertical")
        self.scroll_chat, self.chat = texto_scroll()
        panel.add_widget(self.scroll_chat)
        self.lbl_pensando = Label(text="", size_hint_y=None, height=dp(18),
                                  font_size="12sp", color=GOLD)
        panel.add_widget(self.lbl_pensando)
        caja.add_widget(panel)

        chips = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
        for texto, frase in (("Preséntate", "Preséntate brevemente"),
                             ("Zigzag", "Haz un zigzag"),
                             ("Círculo", "Gira en círculo"),
                             ("Sorpréndeme", "Hazme un truco que me sorprenda")):
            b = PadButton(text=texto, font_size="12sp", color_base=[0.16, 0.22, 0.38, 1])
            b.bind(on_release=lambda inst, f=frase: self.hablar_con_ia(f))
            chips.add_widget(b)
        self.tg_voz = Toggle(text="Voz IA", font_size="12sp", state="down")
        self.tg_voz.bind(state=lambda i, st: callar_voz() if st == "normal" else None)
        chips.add_widget(self.tg_voz)
        caja.add_widget(chips)

        fila = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
        self.entrada = TextInput(hint_text="Escríbele a Star-AI...", multiline=False,
                                 background_normal="", background_active="",
                                 background_color=(0.09, 0.12, 0.2, 1),
                                 foreground_color=(1, 1, 1, 1),
                                 hint_text_color=(0.5, 0.58, 0.75, 1),
                                 cursor_color=ACCENT, padding=(dp(12), dp(12)),
                                 write_tab=False)
        self.entrada.bind(on_text_validate=self.enviar_texto)
        fila.add_widget(self.entrada)
        voz = PadButton(text="HABLAR", font_size="13sp", size_hint_x=None, width=dp(90),
                        color_base=[0.45, 0.22, 0.85, 1])
        voz.bind(on_release=lambda *_: self.iniciar_voz())
        fila.add_widget(voz)
        env = PadButton(text="ENVIAR", font_size="13sp", size_hint_x=None, width=dp(90),
                        color_base=[0.0, 0.55, 0.68, 1])
        env.bind(on_release=self.enviar_texto)
        fila.add_widget(env)
        caja.add_widget(fila)

        s.add_widget(caja)
        return s

    def render_chat(self):
        self.mensajes = self.mensajes[-60:]
        self.chat.text = "\n\n".join(self.mensajes)

    def chat_usuario(self, t):
        self.mensajes.append(f"[color=ffc857][b]Tú:[/b][/color] {escape_markup(t)}")
        self.render_chat()

    def chat_ia(self, t):
        self.mensajes.append(f"[color=00e5ff][b]Star-AI:[/b][/color] {escape_markup(t)}")
        self.render_chat()

    def chat_sistema(self, t):
        self.mensajes.append(f"[color=8899bb][i]{escape_markup(t)}[/i][/color]")
        self.render_chat()

    def enviar_texto(self, *_):
        t = self.entrada.text.strip()
        self.entrada.text = ""
        if t:
            self.hablar_con_ia(t)

    def hablar_con_ia(self, texto):
        # "para", "stop", "detente"... cortan al instante, sin pasar por la IA
        palabras = re.sub(r"[^\w ]", "", texto.lower()).split()
        if palabras and palabras[0] in PALABRAS_PARAR and len(palabras) <= 3:
            self.chat_usuario(texto)
            self.detener_todo()
            self.chat_sistema("Truco cancelado. Carro detenido.")
            return
        if self.pensando:
            return
        if not clave_valida():
            self.chat_sistema("Falta la API key de Groq: pégala en config.py y vuelve a abrir la app.")
            return
        self.chat_usuario(texto)
        self.historial.append({"role": "user", "content": texto})
        self.historial = self.historial[-12:]
        self.pensando = True
        self.lbl_pensando.text = "Star-AI está pensando..."
        estado = "USB conectado" if self.conn else "USB NO conectado (modo simulación)"
        threading.Thread(target=self._hilo_ia, args=(list(self.historial), estado, self.token),
                         daemon=True).start()

    def _hilo_ia(self, historial, estado, token):
        try:
            raw = preguntar_groq(historial, estado)
            try:
                data = extraer_json(raw)
            except Exception:
                data = {"habla": raw, "pasos": []}
            Clock.schedule_once(lambda dt: self.respuesta_ia(raw, data, token), 0)
        except Exception as e:
            msg = str(e)
            Clock.schedule_once(lambda dt: self.error_ia(msg), 0)

    def respuesta_ia(self, raw, data, token):
        self.pensando = False
        self.lbl_pensando.text = ""
        self.historial.append({"role": "assistant", "content": raw})
        self.historial = self.historial[-12:]
        if not isinstance(data, dict):
            data = {"habla": str(data), "pasos": []}
        habla = str(data.get("habla", "")).strip()
        pasos = sanear_pasos(data.get("pasos", []))
        self.chat_ia(habla or "...")
        if token != self.token:   # pulsaste STOP mientras la IA pensaba
            if pasos:
                self.chat_sistema("Maniobra descartada porque pulsaste STOP.")
            return
        if habla and self.tg_voz.state == "down":
            hablar(habla)
        if pasos:
            total = sum(p["ms"] for p in pasos) / 1000.0
            extra = "" if self.conn else " (sin USB: solo simulación en pantalla)"
            self.chat_sistema(f"Ejecutando truco: {len(pasos)} pasos, unos {total:.1f} s, a máxima "
                              f"potencia. Di \"para\" o pulsa PARAR TRUCO.{extra}")
            self.ejecutar_pasos(pasos)

    def error_ia(self, msg):
        self.pensando = False
        self.lbl_pensando.text = ""
        self.chat_sistema(f"Error: {msg}")

    # ---------- Voz de entrada (solo celular) ----------
    def iniciar_voz(self):
        if platform != "android":
            self.chat_sistema("En PC escribe tu mensaje. El micrófono funciona en la versión del celular.")
            return
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            RI = autoclass("android.speech.RecognizerIntent")
            PA = autoclass("org.kivy.android.PythonActivity")
            intent = Intent(RI.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RI.EXTRA_LANGUAGE_MODEL, RI.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(RI.EXTRA_LANGUAGE, "es-ES")
            intent.putExtra(RI.EXTRA_PROMPT, "Habla con Star-Car")
            PA.mActivity.startActivityForResult(intent, REQ_VOZ)
        except Exception as e:
            self.chat_sistema(f"No se pudo abrir el reconocimiento de voz: {e}")

    def on_activity_result(self, request, result, data):
        # Se llama desde el hilo de Android: pasamos el trabajo al hilo de Kivy
        if request != REQ_VOZ or result != -1 or data is None:
            return
        try:
            from jnius import autoclass
            RI = autoclass("android.speech.RecognizerIntent")
            lista = data.getStringArrayListExtra(RI.EXTRA_RESULTS)
            texto = str(lista.get(0)) if lista is not None and lista.size() > 0 else ""
        except Exception:
            texto = ""
        if texto:
            Clock.schedule_once(lambda dt: self.hablar_con_ia(texto), 0)

    # ------------------------------------------------------------------
    #  Pantalla DIAGNÓSTICO
    # ------------------------------------------------------------------
    def pantalla_diag(self):
        s = Screen(name="diag")
        caja = BoxLayout(orientation="vertical", spacing=dp(8))
        panel = Panel(orientation="vertical")
        self.scroll_diag, self.lbl_diag = texto_scroll()
        self.lbl_diag.text = ("Pulsa [b]EJECUTAR TEST[/b] para revisar USB, envío, internet, "
                              "Groq y voz.\nPulsa [b]TEST MOTORES[/b] con el carro levantado "
                              "(mueve cada motor un instante a máxima potencia).")
        panel.add_widget(self.scroll_diag)
        caja.add_widget(panel)

        fila = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        b1 = PadButton(text="EJECUTAR TEST", font_size="14sp", color_base=[0.0, 0.55, 0.68, 1])
        b1.bind(on_release=lambda *_: self.diagnostico())
        b2 = PadButton(text="TEST MOTORES  (levanta el carro)", font_size="14sp",
                       color_base=[0.7, 0.45, 0.05, 1])
        b2.bind(on_release=lambda *_: self.test_motores())
        fila.add_widget(b1)
        fila.add_widget(b2)
        caja.add_widget(fila)
        s.add_widget(caja)
        return s

    def diag_render(self):
        self.lbl_diag.text = "\n".join(self.diag_lineas)

    def diagnostico(self):
        L = self.diag_lineas = []

        def ok(t):
            L.append("[color=66dd77][b]OK[/b][/color]      " + escape_markup(t))

        def mal(t):
            L.append("[color=ef5350][b]FALLO[/b][/color]  " + escape_markup(t))

        def aviso(t):
            L.append("[color=ffc857][b]AVISO[/b][/color]  " + escape_markup(t))

        ok(f"Star-Car v{VERSION} corriendo en {platform}")

        # USB
        try:
            if platform == "android":
                devs = usb.get_usb_device_list()
                if not devs:
                    mal("No se detecta ningún USB. Revisa el cable (que sea de datos) y el adaptador OTG.")
                for d in devs:
                    vid, pid = d.getVendorId(), d.getProductId()
                    ok(f"USB detectado: {d.getDeviceName()}  ID {vid:04X}:{pid:04X}  "
                       f"{CHIPS_USB.get(vid, 'chip desconocido')}")
                    if usb.has_usb_permission(d):
                        ok("Permiso USB concedido")
                    else:
                        aviso("Permiso USB pendiente: acepta el aviso de Android")
            else:
                puertos = [p.device for p in list_ports.comports()]
                if puertos:
                    ok("Puertos serial en PC: " + ", ".join(puertos))
                else:
                    mal("No hay puertos serial. Conecta el Arduino Nano por USB.")
        except Exception as e:
            mal(f"Error revisando USB: {e}")

        # Serial + envío
        if self.conn:
            ok("Puerto serial abierto")
            self.conn.enviar("M1:0,M2:0\n")
            ok("Comando de prueba enviado (M1:0,M2:0)")
        else:
            mal("Puerto serial NO abierto (el carro no recibirá órdenes)")

        # Voz
        if platform == "android":
            try:
                from jnius import autoclass
                Intent = autoclass("android.content.Intent")
                RI = autoclass("android.speech.RecognizerIntent")
                PA = autoclass("org.kivy.android.PythonActivity")
                i = Intent(RI.ACTION_RECOGNIZE_SPEECH)
                if i.resolveActivity(PA.mActivity.getPackageManager()) is not None:
                    ok("Reconocimiento de voz disponible")
                else:
                    aviso("No se pudo confirmar el reconocimiento de voz (necesitas la app de Google)")
            except Exception as e:
                aviso(f"Voz: {e}")
        else:
            aviso("En PC el micrófono no se usa; escribe tus mensajes")
        hablar("Star-Car listo")
        ok("Prueba de voz enviada (deberías oír 'Star-Car listo')")

        # Groq (en hilo, necesita internet)
        if not clave_valida():
            mal("Groq: falta la API key en config.py")
            self.diag_render()
            return
        L.append("[color=8899bb]...probando internet y Groq[/color]")
        self.diag_render()
        threading.Thread(target=self._test_groq, daemon=True).start()

    def _test_groq(self):
        try:
            llamar_groq([{"role": "user", "content": "Responde solo: ok"}],
                        max_tokens=60, json_mode=False)
            linea = ("[color=66dd77][b]OK[/b][/color]      Groq responde correctamente "
                     f"(modelo {escape_markup(config.GROQ_MODEL)})")
        except Exception as e:
            linea = "[color=ef5350][b]FALLO[/b][/color]  Groq: " + escape_markup(str(e))

        def poner(dt):
            if self.diag_lineas:
                self.diag_lineas[-1] = linea
            self.diag_render()

        Clock.schedule_once(poner, 0)

    def test_motores(self):
        self.diag_lineas.append("[color=ffc857]Test de motores: dirección izq/der y llantas "
                                "adelante/atrás, a máxima potencia (~1.6 s)[/color]")
        self.diag_render()
        self.ejecutar_pasos([{"m1": -1, "m2": 0, "ms": 400}, {"m1": 1, "m2": 0, "ms": 400},
                             {"m1": 0, "m2": -1, "ms": 400}, {"m1": 0, "m2": 1, "ms": 400}])

    # ------------------------------------------------------------------
    #  Conexión USB
    # ------------------------------------------------------------------
    def _conectado(self, port, nombre):
        self.conn = Enlace(port, self._perdido)
        self.nombre_puerto = nombre
        self.conectando = False
        self.enviar_datos(forzar=True)
        self.actualizar_estado()

    def _perdido(self):
        """Se desenchufó el cable o falló la escritura."""
        self.cancelar_maniobra()
        self.liberar_teclas()
        self.val_m1 = self.val_m2 = 0
        self._ultimo = None
        self.lbl_monitor.text = "M1:+0   M2:+0"
        self.desconectar()

    def desconectar(self):
        if self.conn:
            self.conn.cerrar()
        self.conn = None
        self.conectando = False
        self.actualizar_estado()

    # PC: un hilo se encarga de buscar/abrir el puerto, así la ventana no se congela
    def _vigilante_pc(self):
        while self._activo:
            try:
                if self.conn is None and not self.conectando:
                    puerto = elegir_puerto_pc()
                    if puerto:
                        self.conectando = True
                        Clock.schedule_once(lambda dt: self.actualizar_estado(), 0)
                        try:
                            p = serial.Serial(puerto, BAUD, timeout=0.2, write_timeout=0.5)
                            time.sleep(1.8)  # el Nano se reinicia al abrir el puerto
                            Clock.schedule_once(lambda dt, p=p, n=puerto: self._conectado(p, n), 0)
                        except Exception:
                            self.conectando = False
                elif self.conn is not None:
                    nombres = [p.device for p in list_ports.comports()]
                    if self.nombre_puerto not in nombres:
                        Clock.schedule_once(lambda dt: self._perdido(), 0)
            except Exception:
                self.conectando = False
            time.sleep(2.0)

    # Android: la lista de dispositivos USB es rápida, se revisa cada segundo
    def buscar_dispositivo_android(self, dt):
        try:
            dispositivos = usb.get_usb_device_list()
            if self.conn is not None:
                if not dispositivos:
                    self._perdido()
                return
            if self.conectando or not dispositivos:
                return
            dev = dispositivos[0]
            if not usb.has_usb_permission(dev):
                if not self.pidiendo_permiso:
                    self.pidiendo_permiso = True
                    usb.request_usb_permission(dev)
                return
            self.pidiendo_permiso = False
            nombre = dev.getDeviceName()
            port = serial.get_serial_port(nombre, BAUD, 8, "N", 1, timeout=1)
            self.conectando = True
            self.actualizar_estado()
            Clock.schedule_once(lambda dt2: self._conectado(port, nombre), 1.8)
        except Exception:
            self.conectando = False

    # ------------------------------------------------------------------
    #  Movimiento
    # ------------------------------------------------------------------
    def on_slider(self, *_):
        self.lbl_atras.text = f"Velocidad llantas: {int(self.sl_atras.value)}"
        self.lbl_dir.text = f"Fuerza dirección: {int(self.sl_dir.value)}"
        self.actualizar_movimiento()

    def actualizar_movimiento(self):
        if self.maniobra_activa:  # la IA tiene el mando
            return
        raw_m2 = 0
        if self.keys["w"] and not self.keys["s"]:
            raw_m2 = -1
        elif self.keys["s"] and not self.keys["w"]:
            raw_m2 = 1
        vel_m2 = raw_m2 * int(self.sl_atras.value)
        if self.inv_atras.state == "down":
            vel_m2 = -vel_m2
        self.val_m2 = vel_m2

        raw_m1 = 0
        if self.keys["a"] and not self.keys["d"]:
            raw_m1 = -1
        elif self.keys["d"] and not self.keys["a"]:
            raw_m1 = 1
        vel_m1 = raw_m1 * int(self.sl_dir.value)
        if self.inv_dir.state == "down":
            vel_m1 = -vel_m1
        self.val_m1 = vel_m1

        self.enviar_datos()

    def detener_todo(self):
        self.token += 1            # invalida cualquier respuesta de la IA que venga en camino
        callar_voz()
        self.cancelar_maniobra()
        self.liberar_teclas()
        self.val_m1 = 0
        self.val_m2 = 0
        self.enviar_datos(forzar=True)

    def parar_truco(self):
        self.detener_todo()
        self.chat_sistema("Truco cancelado. Carro detenido.")

    def parar_por_error(self):
        try:
            self.detener_todo()
        except Exception:
            pass

    def enviar_datos(self, forzar=False):
        self.lbl_monitor.text = f"M1:{self.val_m1:+d}   M2:{self.val_m2:+d}"
        par = (self.val_m1, self.val_m2)
        if not forzar and par == self._ultimo:
            return  # no repetir la misma orden (evita saturar el puerto al mover sliders)
        self._ultimo = par
        if self.conn:
            self.conn.enviar(f"M1:{par[0]},M2:{par[1]}\n")

    # ---------- Trucos de la IA (a máxima potencia) ----------
    def ejecutar_pasos(self, pasos):
        self.cancelar_maniobra()
        self.liberar_teclas()
        self.maniobra = list(pasos)
        self.total_pasos = len(pasos)
        self.maniobra_activa = True
        self.actualizar_estado()
        self._siguiente_paso()

    def _siguiente_paso(self, dt=None):
        if not self.maniobra_activa:
            return
        if not self.maniobra:
            self.fin_maniobra()
            return
        p = self.maniobra.pop(0)
        m1 = potencia(p["m1"], config.IA_POTENCIA_DIRECCION)
        m2 = potencia(p["m2"], config.IA_POTENCIA_LLANTAS)
        if self.inv_dir.state == "down":
            m1 = -m1
        if self.inv_atras.state == "down":
            m2 = -m2
        self.val_m1, self.val_m2 = m1, m2
        actual = self.total_pasos - len(self.maniobra)
        self.mostrar_banner(True, f"[b]TRUCO EN EJECUCIÓN[/b]  paso {actual}/{self.total_pasos}  ·  "
                                  f"di [b]\"para\"[/b] o pulsa el botón")
        self.enviar_datos()
        self._ev = Clock.schedule_once(self._siguiente_paso, p["ms"] / 1000.0)

    def fin_maniobra(self):
        self.maniobra_activa = False
        self._ev = None
        self.val_m1 = 0
        self.val_m2 = 0
        self.enviar_datos(forzar=True)
        self.mostrar_banner(False)
        self.actualizar_estado()

    def cancelar_maniobra(self):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        self.maniobra = []
        if self.maniobra_activa:
            self.maniobra_activa = False
            self.mostrar_banner(False)
            self.actualizar_estado()

    # ------------------------------------------------------------------
    #  Ciclo de vida
    # ------------------------------------------------------------------
    def on_pause(self):
        self.detener_todo()
        return True

    def on_stop(self):
        self._activo = False
        self.detener_todo()
        time.sleep(0.2)  # deja que el hilo de envío escriba el STOP antes de cerrar el puerto
        self.desconectar()


if __name__ == "__main__":
    StarCarApp().run()