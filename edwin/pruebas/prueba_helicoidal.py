"""Prueba del plugin «Helicoidal (sinfín)» sin abrir ventanas (Qt offscreen).
Correr desde la raíz del repositorio:  py -3.10 edwin/pruebas/prueba_helicoidal.py
Dibuja la helicoidal, revisa la geometría, toma tramos como haría el usuario,
los desdobla y guarda edwin/pruebas/salida/helicoidal-tramos.dxf."""
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

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

app = QApplication(sys.argv)
app.setApplicationName("EDWIN CNC 3D prueba")
app.setOrganizationName("EDWIN CNC")

from core.scene import Scene  # noqa: E402
from core import edwin_helicoidal as eh  # noqa: E402
from core import edwin_desdoblar as ed  # noqa: E402

spec = importlib.util.spec_from_file_location("edwin_cnc_prueba", os.path.join(RAIZ, "plugins", "edwin_cnc.py"))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


# --- medidas malas
for m, texto in [(eh.Medidas(interior=300), "eje igual al de afuera"),
                 (eh.Medidas(interior=0), "eje cero"),
                 (eh.Medidas(paso=0), "paso cero"),
                 (eh.Medidas(vueltas=0), "cero vueltas"),
                 (eh.Medidas(divisiones=3), "muy pocos tramos")]:
    revisar(f"rechaza {texto}", eh.problema(m) is not None)
    try:
        eh.construir(m)
        revisar(f"construir no acepta {texto}", False)
    except ValueError:
        revisar(f"construir no acepta {texto}", True)

# --- geometría Ø300, eje 76, paso 300, 2 vueltas, 36 tramos por vuelta
m = eh.Medidas(exterior=300, interior=76, paso=300, vueltas=2, divisiones=36)
v, t, diag = eh.construir(m)
revisar("72 tramos = 144 triángulos", len(t) == 144, len(t))
revisar("146 puntos", len(v) == 146, len(v))
zs = [p[2] for p in v]
revisar("sube 600 mm en 2 vueltas", abs(max(zs) - 600) < 1e-6 and abs(min(zs)) < 1e-6, (min(zs), max(zs)))
radios = sorted({round(math.hypot(x, y), 6) for x, y, _ in v})
revisar("solo radios 38 y 150", radios == [38.0, 150.0], radios)
# vuelta completa: el último punto queda encima del primero, un paso más arriba... ×2
revisar("termina alineado con el inicio", abs(v[-1][0] - v[1][0]) < 1e-6 and abs(v[-1][1] - v[1][1]) < 1e-6)
# sentido derecha: el ángulo crece al subir
a1 = math.atan2(v[3][1], v[3][0])
revisar("sentido derecha gira antihorario", a1 > 0, a1)
v2, _, _ = eh.construir(eh.Medidas(derecha=False))
revisar("sentido izquierda gira horario", math.atan2(v2[3][1], v2[3][0]) < 0)
revisar("media vuelta permitida", len(eh.construir(eh.Medidas(vueltas=0.5, divisiones=36))[1]) == 36)
revisar("3 tramos a lo ancho", len(eh.construir(eh.Medidas(ancho=3, vueltas=1, divisiones=36))[1]) == 36 * 3 * 2)

# --- dato de taller de la arandela (fórmula clásica)
a = eh.arandela(eh.Medidas(exterior=300, interior=76, paso=300))
lo, li = math.hypot(math.pi * 300, 300), math.hypot(math.pi * 76, 300)
revisar("largo del borde", abs(a["largo_borde"] - lo) < 1e-9)
revisar("radio de adentro ~71 mm", abs(a["radio_interior"] - 112 * li / (lo - li)) < 1e-9 and 70 < a["radio_interior"] < 72,
        a["radio_interior"])
revisar("radio de afuera = adentro + 112", abs(a["radio_exterior"] - a["radio_interior"] - 112) < 1e-9)
revisar("abertura entre 0° y 360°", 0 < a["angulo_abertura"] < 360, a["angulo_abertura"])
# el arco de afuera que queda mide lo que el borde de una vuelta
R = a["radio_exterior"]
revisar("arco de afuera = largo del borde", abs(2 * math.pi * R * (1 - a["angulo_abertura"] / 360) - lo) < 1e-6)

# --- grupo en el programa
scene = Scene()
g = plugin.construir_grupo_helicoidal(m)
scene.groups.append(g)
revisar("el grupo tiene 144 caras", len(g.mesh.faces) == 144, len(g.mesh.faces))
revisar("nombre con las medidas", "Ø300" in g.name and "paso 300" in g.name, g.name)
suaves = [e for e in g.mesh.edges if e.soft]
revisar("72 diagonales suaves", len(suaves) == 72, len(suaves))
revisar("un clic toma el tramo entero (2 triángulos)", len(g.mesh.surface_of(g.mesh.faces[0])) == 2,
        len(g.mesh.surface_of(g.mesh.faces[0])))

# --- desdoblar 3 tramos (6 triángulos, 30°) como haría el usuario dentro del grupo
scene.selection.update(g.mesh.faces[:6])
malla = plugin._malla_de_seleccion(scene)
revisar("toma 6 caras", len(malla.caras) == 6, len(malla.caras))
piezas = ed.desdoblar(malla)
revisar("sale UNA pieza", len(piezas) == 1, len(piezas))
avisos = [x for p in piezas for x in p.avisos]
revisar("sin avisos de solape ni torcidas", not any("OJO" in x or "torcida" in x for x in avisos), avisos)
ruta = os.path.join(SALIDA, "helicoidal-tramos.dxf")
ed.guardar_dxf(piezas, ruta, "HELICOIDAL")
revisar("guarda el DXF", os.path.getsize(ruta) > 0)

# --- una vuelta entera de una vez (se deforma pero no debe fallar)
scene.selection.clear()
scene.selection.update(g.mesh.faces[:72])
piezas = ed.desdoblar(plugin._malla_de_seleccion(scene))
revisar("una vuelta entera también desdobla", len(piezas) >= 1)
ed.guardar_dxf(piezas, os.path.join(SALIDA, "helicoidal-vuelta.dxf"), "HELICOIDAL")

# --- ventana
w = plugin._VentanaHelicoidal()
w.interior.setValue(w.exterior.value())
revisar("ventana: botón Dibujar apagado con medidas malas", not w._ok.isEnabled())
w.interior.setValue(76)
w.exterior.setValue(300)
revisar("ventana: botón Dibujar encendido", w._ok.isEnabled())
revisar("ventana: muestra el dato de la arandela", "radio de adentro" in w.info.text(), w.info.text())
w.grab().save(os.path.join(SALIDA, "ventana-helicoidal.png"))

print(f"\n{'TODO BIEN' if mal == 0 else f'{mal} con problemas'}")
sys.exit(1 if mal else 0)
