"""Prueba de «Pieza por medidas» y «Acomodar en láminas» dentro del programa (Qt offscreen).
Correr desde la raíz del repositorio:  py -3.10 edwin/pruebas/prueba_pieza_ventana.py
Arma cada pieza como grupo del modelo (en metros), la selecciona, la desdobla con la ventana
de «Desdoblar caras», la acomoda en láminas y guarda el DXF con las láminas."""
import importlib.util
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
from core import edwin_desdoblar as ed  # noqa: E402
from core import edwin_piezas3d as p3  # noqa: E402

spec = importlib.util.spec_from_file_location("edwin_cnc_prueba", os.path.join(RAIZ, "plugins", "edwin_cnc.py"))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


# --- cada pieza como grupo: mismas caras y el desdoblado desde la selección da la misma área
for tipo in p3.PIEZAS:
    m = p3.valores_por_defecto(tipo)
    partes = p3.construir(tipo, m)
    scene = Scene()
    grupos = [plugin.grupo_desde_parte(p) for p in partes]
    scene.groups.extend(grupos)
    revisar(f"{tipo}: grupos con todas las caras",
            all(len(g.mesh.faces) == len(p.caras) for g, p in zip(grupos, partes)),
            [(len(g.mesh.faces), len(p.caras)) for g, p in zip(grupos, partes)])
    for g, p in zip(grupos, partes):
        scene.selection.clear()
        scene.selection.add(g)
        malla = plugin._malla_de_seleccion(scene)
        plano = ed.desdoblar(malla)
        directo = ed.desdoblar(ed.Malla(p.vertices, p.caras, p.huecos))
        a1, a2 = sum(x.area for x in plano), sum(x.area for x in directo)
        revisar(f"{tipo} · {p.nombre}: desdoblado desde el grupo = desde la pieza ({len(plano)} pieza(s))",
                abs(a1 - a2) <= a2 * 1e-6 and len(plano) == len(directo), (a1, a2, len(plano), len(directo)))

# un clic toma toda la lámina curva (aristas suaves)
cono = plugin.grupo_desde_parte(p3.construir("conica", p3.valores_por_defecto("conica"))[0])
revisar("tolva cónica: un clic toma toda la lámina", len(cono.mesh.surface_of(cono.mesh.faces[0])) == 72,
        len(cono.mesh.surface_of(cono.mesh.faces[0])))
pir = plugin.grupo_desde_parte(p3.construir("piramidal", p3.valores_por_defecto("piramidal"))[0])
revisar("tolva piramidal: cada cara por separado (dobleces de verdad)",
        len(pir.mesh.surface_of(pir.mesh.faces[0])) == 1, len(pir.mesh.surface_of(pir.mesh.faces[0])))

# --- ventana de la pieza
w = plugin._VentanaPieza()
revisar("ventana: 7 piezas + helicoidal", w.tipo.count() == len(p3.PIEZAS) + 1, w.tipo.count())
w.tipo.setCurrentIndex(list(p3.PIEZAS).index("u"))
w.campos["u"]["alto"].setValue(100)          # menos que el radio
revisar("ventana: Dibujar apagado con medidas malas", not w._ok.isEnabled())
revisar("ventana: explica el problema", "mitad del ancho" in w.info.text(), w.info.text())
w.campos["u"]["alto"].setValue(550)
revisar("ventana: Dibujar encendido con medidas buenas", w._ok.isEnabled())
revisar("ventana: medidas leídas", w.medidas()["alto"] == 550 and w.tipo_actual() == "u")
w.grab().save(os.path.join(SALIDA, "ventana-pieza.png"))
w.tipo.setCurrentIndex(len(p3.PIEZAS))
revisar("ventana: la helicoidal no se dibuja desde aquí (abre su ventana)", not w._ok.isEnabled())

# --- desdoblar + acomodar en láminas: media tolva cónica x 2 copias, y una tolva en U
parte = p3.construir("conica", {"ds": 1200, "di": 600, "alto": 900, "tramos": 72})[0]
malla = ed.Malla(parte.vertices, parte.caras, parte.huecos)
mitad = ed.Malla(malla.vertices, malla.caras[:36], {})
v = plugin._Ventana(None, mitad, "TOLVA")
revisar("desdoblar: una pieza", len(v.piezas) == 1, len(v.piezas))
revisar("botón Acomodar encendido", v.acomodar.isEnabled())


class _AcomodoFalso(plugin._VentanaAcomodo):
    def exec(self):
        self.copias.setValue(2)
        return QDialog.Accepted


plugin._VentanaAcomodo = _AcomodoFalso
v._acomodar()
revisar("acomodo hecho: 2 copias", v.acomodo is not None and len(v.acomodo[0]) == 2,
        None if v.acomodo is None else len(v.acomodo[0]))
revisar("acomodo: muestra láminas y aprovechamiento", "aprovechamiento" in v.resumen.text(), v.resumen.text())
revisar("botón Quitar acomodo visible", not v.quitar.isHidden())
v.resize(820, 640)
v.grab().save(os.path.join(SALIDA, "ventana-acomodo.png"))
ruta = os.path.join(SALIDA, "acomodo-desde-ventana.dxf")
ed.guardar_dxf(v.acomodo[0], ruta, "TOLVA", laminas=v.acomodo[1])
import ezdxf  # noqa: E402
doc = ezdxf.readfile(ruta)
cortes = [e for e in doc.modelspace() if e.dxf.layer == "CORTE"]
refs = [e for e in doc.modelspace() if e.dxf.layer == "REFERENCIA" and e.dxftype() == "LWPOLYLINE"]
revisar("DXF: 2 piezas en CORTE y sus láminas en REFERENCIA", len(cortes) == 2 and len(refs) == v.acomodo[2].laminas,
        (len(cortes), len(refs)))
v._quitar_acomodo()
revisar("Quitar acomodo vuelve al desdoblado", v.acomodo is None and v.quitar.isHidden())

print(f"\n{'TODO BIEN' if mal == 0 else f'{mal} con problemas'}")
sys.exit(1 if mal else 0)
