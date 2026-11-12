"""Prueba de la ventana «Foto → plano → DXF» y de la hoja PDF, sin abrir ventanas.
Correr desde la raíz del repositorio:  py -3.10 edwin/pruebas/prueba_foto_ventana.py

1. Genera la Hoja de escala EDWIN (PDF carta y A4) y las 4 marcas grandes.
2. "Imprime" la hoja (la convierte en imagen con QtPdf), le pone encima una
   pieza conocida y la "fotografía" torcida.
3. Pasa la foto por la ventana, en los 3 modos, y revisa medidas, DXF y el
   botón «Poner en el modelo 3D»."""
import importlib.util
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)
SALIDA = os.path.join(os.path.dirname(__file__), "salida")
os.makedirs(SALIDA, exist_ok=True)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setApplicationName("EDWIN CNC 3D prueba")
app.setOrganizationName("EDWIN CNC")

from core import edwin_foto_dxf as fd  # noqa: E402
from core.scene import Scene  # noqa: E402
from core.history import History  # noqa: E402

spec = importlib.util.spec_from_file_location("edwin_cnc_prueba", os.path.join(RAIZ, "plugins", "edwin_cnc.py"))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
# Reutiliza el "celular" simulado de prueba_foto_dxf.py (solo sus funciones, sin correr sus pruebas).
_aux = {"__file__": os.path.join(os.path.dirname(__file__), "prueba_foto_dxf.py"), "__name__": "aux"}
exec(open(os.path.join(os.path.dirname(__file__), "prueba_foto_dxf.py"), encoding="utf-8").read().split("# --- marcas")[0],
     _aux)
fotografiar = _aux["fotografiar"]

mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


def pdf_a_imagenes(ruta, ppmm=10):
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    doc.load(ruta)
    out = []
    for k in range(doc.pageCount()):
        tam = doc.pagePointSize(k)                    # puntos (1/72 pulgada)
        w, h = int(tam.width() / 72 * 25.4 * ppmm), int(tam.height() / 72 * 25.4 * ppmm)
        from PySide6.QtGui import QImage
        img = doc.render(k, QSize(w, h)).convertToFormat(QImage.Format_ARGB32)
        b = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, :].astype(np.float32)
        alfa = b[..., 3:4] / 255.0                      # el PDF sale con fondo transparente: papel blanco
        a = (b[..., :3] * alfa + 255.0 * (1 - alfa)).clip(0, 255).astype(np.uint8)
        out.append(a)
    return out, doc.pageCount()


# --- 1. PDFs
for papel in ("carta", "a4"):
    ruta = os.path.join(SALIDA, f"hoja-{papel}.pdf")
    plugin.hacer_pdf_marcas(ruta, papel)
    revisar(f"PDF hoja {papel} creado", os.path.getsize(ruta) > 1000)
ruta_g = os.path.join(SALIDA, "4-marcas-grandes.pdf")
plugin.hacer_pdf_marcas(ruta_g, "carta", grandes=True)
paginas, n = pdf_a_imagenes(ruta_g, 4)
revisar("4 marcas grandes = 4 páginas", n == 4, n)
for i, pg in enumerate(paginas):
    c, _ = fd.buscar_marcas(pg)
    revisar(f"página {i}: se reconoce la marca {i}", list(c) == [i], list(c))

# --- 2. hoja impresa (carta) con una pieza encima, a 10 px/mm
[hoja], _ = pdf_a_imagenes(os.path.join(SALIDA, "hoja-carta.pdf"), 10)
cv2.imwrite(os.path.join(SALIDA, "hoja-impresa.png"), hoja)
c, _ = fd.buscar_marcas(hoja)
revisar("la hoja impresa tiene las 4 marcas", sorted(c) == [0, 1, 2, 3], sorted(c))
d01 = np.hypot(*np.subtract(c[1], c[0])) / 10
d03 = np.hypot(*np.subtract(c[3], c[0])) / 10
revisar(f"en el PDF las marcas están a 170 x 230 mm (salen {d01:.2f} x {d03:.2f})",
        abs(d01 - fd.HOJA_ANCHO) < 0.3 and abs(d03 - fd.HOJA_ALTO) < 0.3, (d01, d03))
# la hoja vacía (con su texto y regla) no debe dar piezas
e, pz = fd.procesar_con_hoja(fotografiar(hoja, semilla=4))
revisar("el texto y la regla de la hoja no cuentan como pieza", len(pz) == 0, [(round(p.ancho), round(p.alto)) for p in pz])
# pieza: brida redonda Ø100 con hueco Ø40, gris oscuro
cx = int((c[0][0] + c[2][0]) / 2)
cy = int((c[0][1] + c[2][1]) / 2)
con = hoja.copy()
cv2.circle(con, (cx, cy), 500, (60, 60, 65), -1)
cv2.circle(con, (cx, cy), 200, (250, 250, 250), -1)
foto = fotografiar(con, torcer=0.13, luz=0.4, semilla=11)
ruta_foto = os.path.join(SALIDA, "brida-foto.jpg")
cv2.imwrite(ruta_foto, foto)

# --- 3. la ventana
class VP:
    def __init__(self):
        self.scene = Scene()
        self.history = History(self.scene)
        self.estado = ""

    def flash_status(self, t, ms=0):
        self.estado = t

    def notify_scene_changed(self):
        pass


class AppFalsa:
    window = None

    def __init__(self):
        self.viewport = VP()
        self.scene = self.viewport.scene


a = AppFalsa()
v = plugin._VentanaFoto(a)
v.modo.setCurrentIndex(0)
revisar("sin foto: botones apagados", not v.b_dxf.isEnabled() and not v.b_modelo.isEnabled())
v.foto = fd.leer_foto(ruta_foto)
v.ruta_foto = ruta_foto
v._enderezar()
revisar("modo hoja: encuentra 1 pieza", len(v.piezas) == 1, v.info.text())
if v.piezas:
    p = v.piezas[0]
    revisar(f"brida Ø100 (sale {p.ancho:.2f} x {p.alto:.2f})", abs(p.ancho - 100) < 0.8 and abs(p.alto - 100) < 0.8)
    revisar("con su hueco", len(p.huecos) == 1)
    hx = [x for x, _ in p.huecos[0]] if p.huecos else [0]
    revisar(f"hueco Ø40 (sale {max(hx) - min(hx):.2f})", abs(max(hx) - min(hx) - 40) < 0.8)
revisar("botones encendidos", v.b_dxf.isEnabled() and v.b_modelo.isEnabled())
revisar("muestra la medida", "99.8" in v.info.text() or "100.0" in v.info.text(), v.info.text())
v.grab().save(os.path.join(SALIDA, "ventana-foto.png"))

# DXF
ruta_dxf = os.path.join(SALIDA, "brida.dxf")
fd.guardar_dxf(v.piezas, ruta_dxf, "BRIDA")
import ezdxf  # noqa: E402
doc = ezdxf.readfile(ruta_dxf)
revisar("DXF con 2 contornos", len([x for x in doc.modelspace() if x.dxftype() == "LWPOLYLINE"]) == 2)

# sensibilidad a mano y pieza clara: no se cae
v.auto.setChecked(False)
v.umbral.setValue(120)
v._buscar()
revisar("sensibilidad a mano: sigue encontrando la brida", len(v.piezas) == 1, v.info.text())
v.oscura.setChecked(False)
revisar("si dice 'clara' por error: no se cae (avisa)", isinstance(v.piezas, list))
v.oscura.setChecked(True)
v.auto.setChecked(True)

# modo 4 esquinas a mano: marcar las esquinas de la hoja de marcas (centros) como rectángulo 170 x 230
v.modo.setCurrentIndex(2)
revisar("modo esquinas: pide la primera esquina", "ARRIBA-IZQUIERDA" in v.info.text(), v.info.text())
v.ancho.setValue(fd.HOJA_ANCHO)
v.alto.setValue(fd.HOJA_ALTO)
cen, _ = fd.buscar_marcas(v.foto)
for i in range(4):
    v._clic_esquina(*cen[i])
revisar("modo esquinas: 4 clics y encuentra la brida", len(v.piezas) >= 1, v.info.text())
if v.piezas:
    revisar(f"modo esquinas: Ø100 (sale {v.piezas[0].ancho:.1f})", abs(v.piezas[0].ancho - 100) < 2.0)
v._rehacer_esquinas()
revisar("volver a marcar: borra los clics", v.esquinas == [] and "ARRIBA-IZQUIERDA" in v.info.text())

# modo 4 marcas grandes con las medidas de la hoja: igual que la hoja
v.modo.setCurrentIndex(1)
v.lado_grande.setValue(fd.HOJA_MARCA)
v._enderezar()
revisar("modo marcas grandes con medidas: encuentra la brida", len(v.piezas) == 1 and abs(v.piezas[0].ancho - 100) < 0.8,
        v.info.text())

# foto sin marcas en modo hoja: mensaje claro, sin caerse
v.modo.setCurrentIndex(0)
v.foto = np.full((800, 600, 3), 200, np.uint8)
v._enderezar()
revisar("foto sin marcas: avisa", "marcas" in v.info.text() and not v.b_dxf.isEnabled(), v.info.text())

# poner en el modelo
pz = fd.procesar_con_hoja(fd.leer_foto(ruta_foto))[1]
g = plugin.grupo_desde_piezas(pz, "brida (desde foto)")
revisar("al modelo: 1 cara con 1 hueco", len(g.mesh.faces) == 1 and len(g.mesh.faces[0].hole_loops) == 1)
zs = {round(v_.position.z(), 9) for v_ in g.mesh.vertices}
revisar("al modelo: en el piso (Z = 0)", zs == {0.0}, zs)
xs = [v_.position.x() for v_ in g.mesh.vertices]
revisar(f"al modelo: 0,1 m de ancho (sale {max(xs) - min(xs):.4f})", abs(max(xs) - min(xs) - 0.1) < 0.001)

print(f"\n{'TODO BIEN' if mal == 0 else f'{mal} con problemas'}")
sys.exit(1 if mal else 0)
