"""Prueba de «Escala por 2 puntos» sin abrir ventanas (Qt offscreen).
Correr desde la raíz del repositorio:  py -3.10 edwin/pruebas/prueba_escala.py"""
import importlib.util
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)
SALIDA = os.path.join(os.path.dirname(__file__), "salida")
os.makedirs(SALIDA, exist_ok=True)

from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from core.scene import Scene  # noqa: E402
from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.history import History  # noqa: E402
from core.image_plane import ImagePlane  # noqa: E402

spec = importlib.util.spec_from_file_location("edwin_cnc_prueba", os.path.join(RAIZ, "plugins", "edwin_cnc.py"))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


class VP:   # lo mínimo del visor que usa aplicar_escala
    def __init__(self, scene):
        self.scene = scene
        self.history = History(scene)
        self.cambios = 0

    def notify_scene_changed(self):
        self.cambios += 1


def armar():
    s = Scene()
    # cara suelta: cuadrado de 0,2 m (dibujado "a ojo": en la realidad mide 500 mm)
    s.mesh.add_face([QVector3D(0, 0, 0), QVector3D(0.2, 0, 0), QVector3D(0.2, 0.2, 0), QVector3D(0, 0.2, 0)])
    g = Group(Mesh(), name="pieza")
    g.mesh.add_face([QVector3D(1, 0, 0), QVector3D(1.1, 0, 0), QVector3D(1.1, 0.1, 0)])
    s.groups.append(g)
    im = ImagePlane("foto.png", QVector3D(0, 0, 0), QVector3D(0.4, 0, 0), QVector3D(0, 0.3, 0))
    s.image_planes.append(im)
    return s, g, im


revisar("factor 200 → 500 = 2,5", abs(plugin.factor_escala(200, 500) - 2.5) < 1e-12)
revisar("factor con medida cero = None", plugin.factor_escala(0, 500) is None and plugin.factor_escala(200, 0) is None)

# --- sin selección: todo el modelo
s, g, im = armar()
vp = VP(s)
_, _, _, que = plugin._objetivos_escala(s)
revisar("sin selección dice TODO el modelo", "TODO" in que, que)
centro = QVector3D(0, 0, 0)
revisar("aplica", plugin.aplicar_escala(vp, centro, 2.5))
xs = sorted(round(v.position.x() * 1000, 3) for v in s.mesh.vertices)
revisar("cara suelta: 200 mm → 500 mm", xs[-1] == 500.0, xs)
gx = sorted(round(v.position.x() * 1000, 3) for v in g.mesh.vertices)
revisar("grupo escalado desde el punto A (1000→2500, 1100→2750)", gx[0] == 2500.0 and gx[-1] == 2750.0, gx)
revisar("imagen escalada sin deformar (400x300 → 1000x750)",
        abs(im.u.length() - 1.0) < 1e-6 and abs(im.v.length() - 0.75) < 1e-6, (im.u.length(), im.v.length()))
revisar("avisó al visor", vp.cambios == 1)
vp.history.undo()
xs = sorted(round(v.position.x() * 1000, 3) for v in s.mesh.vertices)
gx = sorted(round(v.position.x() * 1000, 3) for v in g.mesh.vertices)
revisar("Ctrl+Z deja todo como estaba", xs[-1] == 200.0 and gx[0] == 1000.0 and abs(im.u.length() - 0.4) < 1e-6,
        (xs, gx, im.u.length()))

# --- con selección: solo el grupo
s, g, im = armar()
vp = VP(s)
s.selection.add(g)
_, _, _, que = plugin._objetivos_escala(s)
revisar("con selección dice solo lo seleccionado", "solo lo seleccionado" in que and "1 grupo" in que, que)
plugin.aplicar_escala(vp, QVector3D(1, 0, 0), 2.0)
xs = sorted(round(v.position.x() * 1000, 3) for v in s.mesh.vertices)
gx = sorted(round(v.position.x() * 1000, 3) for v in g.mesh.vertices)
revisar("la cara suelta no se tocó", xs[-1] == 200.0, xs)
revisar("el grupo sí (100 → 200 mm de ancho)", gx[0] == 1000.0 and gx[-1] == 1200.0, gx)
revisar("la imagen no se tocó", abs(im.u.length() - 0.4) < 1e-6)

# --- selección vacía de verdad (nada que escalar)
s2 = Scene()
revisar("modelo vacío: no hace nada", not plugin.aplicar_escala(VP(s2), centro, 2.0))

# --- herramienta interactiva: se crea y responde
class AppFalsa:
    window = None
herr = plugin._herramienta_escala(AppFalsa())
revisar("herramienta creada con nombre", herr.name == "Escala por 2 puntos")
herr.a = QVector3D(0, 0, 0)
herr.hover = QVector3D(0.3, 0.4, 0)
lab = herr.value_label()
revisar("muestra la distancia mientras mueve (0,5 m)", lab is not None and "500" in lab[0].replace(".", "").replace(",", ""), lab)
revisar("línea elástica entre los puntos", len(herr.rubber_band_lines()) == 1)

# --- ventana
v = plugin._VentanaEscala(None, 200.0, "TODO el modelo")
v.real.setValue(500)
revisar("ventana: muestra el factor 2,5", "2.5000" in v.info.text(), v.info.text())
v.grab().save(os.path.join(SALIDA, "ventana-escala.png"))

print(f"\n{'TODO BIEN' if mal == 0 else f'{mal} con problemas'}")
sys.exit(1 if mal else 0)
