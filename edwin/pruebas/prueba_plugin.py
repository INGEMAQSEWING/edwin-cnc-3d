"""Prueba del botón «Desdoblar caras» sin abrir ventanas (Qt offscreen).
Correr desde la raíz del repositorio:  py -3.10 edwin/pruebas/prueba_plugin.py
Arma una tolva cónica en una escena de IngeTrazo, la selecciona, abre la ventana del
plugin, guarda la vista previa en edwin/pruebas/salida/vista-plugin.png y el DXF."""
import importlib.util
import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)
SALIDA = os.path.join(os.path.dirname(__file__), "salida")
os.makedirs(SALIDA, exist_ok=True)

from PySide6.QtGui import QVector3D, QMatrix4x4  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setApplicationName("EDWIN CNC 3D prueba")
app.setOrganizationName("EDWIN CNC")

from core.scene import Scene  # noqa: E402
from core.group import Group  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core import i18n  # noqa: E402

spec = importlib.util.spec_from_file_location("edwin_cnc_prueba", os.path.join(RAIZ, "plugins", "edwin_cnc.py"))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


# --- marca
i18n.set_language(i18n.resolve_language(None))
revisar("idioma por defecto español", i18n.current_language() == "es", i18n.current_language())
revisar("tr cambia el nombre", "IngeTrazo" not in i18n.tr("About IngeTrazo"), i18n.tr("About IngeTrazo"))
from core import units  # noqa: E402
revisar("milímetros por defecto", units.DEFAULT_MODEL_UNITS["length"] == "mm")

# --- tolva cónica Ø600 -> Ø300 alto 400 en METROS (como guarda IngeTrazo)
N = 48
scene = Scene()
ra, rb, h = 0.300, 0.150, 0.400
abajo = [QVector3D(rb * math.cos(2 * math.pi * i / N), rb * math.sin(2 * math.pi * i / N), 0) for i in range(N)]
arriba = [QVector3D(ra * math.cos(2 * math.pi * i / N), ra * math.sin(2 * math.pi * i / N), h) for i in range(N)]
caras = [scene.mesh.add_face([abajo[i], abajo[(i + 1) % N], arriba[(i + 1) % N], arriba[i]]) for i in range(N)]

# sin selección
revisar("sin selección: malla vacía", not plugin._malla_de_seleccion(scene).caras)

scene.selection.update(caras)
m = plugin._malla_de_seleccion(scene)
revisar(f"{N} caras leídas", len(m.caras) == N, len(m.caras))
revisar("vértices compartidos (2N)", len(m.vertices) == 2 * N, len(m.vertices))
revisar("convertido a mm", abs(max(v[2] for v in m.vertices) - 400) < 0.01)

v = plugin._Ventana(None, m, "TOLVA PRUEBA")
pz = v.piezas
revisar("una pieza", len(pz) == 1, len(pz))
v.resize(800, 640)
v.grab().save(os.path.join(SALIDA, "vista-plugin.png"))
from core import edwin_desdoblar as ed  # noqa: E402
ed.guardar_dxf(pz, os.path.join(SALIDA, "tolva-desde-plugin.dxf"), "TOLVA PRUEBA")
revisar("sin avisos", not pz[0].avisos, pz[0].avisos)
print("   ", v.resumen.text())

# --- grupo con transformación (componente movido y girado)
g = Group(Mesh())
g.mesh.add_face([QVector3D(0, 0, 0), QVector3D(0.1, 0, 0), QVector3D(0.1, 0.1, 0), QVector3D(0, 0.1, 0)])
g.mesh.add_face([QVector3D(0, 0, 0), QVector3D(0, 0, 0.1), QVector3D(0.1, 0, 0.1), QVector3D(0.1, 0, 0)])
mat = QMatrix4x4()
mat.translate(1, 2, 3)
mat.rotate(30, 0, 0, 1)
g.xform = mat
scene.selection.clear()
scene.selection.add(g)
m = plugin._malla_de_seleccion(scene)
pz = ed.desdoblar(m)
revisar("grupo transformado: 2 caras, 1 pieza", len(m.caras) == 2 and len(pz) == 1, (len(m.caras), len(pz)))
revisar("grupo transformado: área 20 000 mm²", abs(pz[0].area - 20000) < 0.5, pz[0].area)
revisar("grupo transformado: 1 doblez de 90°", len(pz[0].dobleces) == 1 and abs(pz[0].dobleces[0].angulo - 90) < 0.01,
        [(d.angulo, d.hacia) for d in pz[0].dobleces])

print("\n" + ("todo bien" if not mal else f"{mal} mal"))
sys.exit(1 if mal else 0)
