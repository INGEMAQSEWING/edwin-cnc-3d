"""Prueba de «Foto → DXF» con fotos SIMULADAS (no hace falta celular).
Correr desde la raíz del repositorio:  py -3.10 edwin/pruebas/prueba_foto_dxf.py

Se dibuja la Hoja de escala EDWIN a 10 píxeles por mm con una pieza de medidas
conocidas (placa 120 x 80 mm con un hueco redondo de Ø30 y una muesca), se
"fotografía" torcida (perspectiva), con luz dispareja, desenfoque, ruido y
compresión JPG, y se revisa que el DXF salga con las medidas correctas."""
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)
SALIDA = os.path.join(os.path.dirname(__file__), "salida")
os.makedirs(SALIDA, exist_ok=True)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import ezdxf  # noqa: E402

from core import edwin_foto_dxf as fd  # noqa: E402

mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


PP = 10.0                       # píxeles por mm de la hoja "real"
CARTA = (215.9, 279.4)
OX = (CARTA[0] - fd.HOJA_ANCHO) / 2      # centro de la marca 0, en mm desde el borde de la hoja
OY = (CARTA[1] - fd.HOJA_ALTO) / 2


def hoja_con_pieza(gris_pieza=70, angulo=0.0, pieza=True):
    W, H = int(CARTA[0] * PP), int(CARTA[1] * PP)
    img = np.full((H, W), 245, np.uint8)
    for i, (cx, cy) in enumerate([(0, 0), (fd.HOJA_ANCHO, 0), (fd.HOJA_ANCHO, fd.HOJA_ALTO), (0, fd.HOJA_ALTO)]):
        lado = int(fd.HOJA_MARCA * PP)
        m = cv2.resize(fd.imagen_marca(i, 200), (lado, lado), interpolation=cv2.INTER_NEAREST)
        x0 = int(round((OX + cx) * PP - lado / 2))
        y0 = int(round((OY + cy) * PP - lado / 2))
        img[y0:y0 + lado, x0:x0 + lado] = m
    if pieza:
        # placa 120 x 80 centrada, girada "angulo" grados, hueco Ø30, muesca 20 x 10 en un lado
        cx, cy = (OX + fd.HOJA_ANCHO / 2) * PP, (OY + fd.HOJA_ALTO / 2) * PP
        rect = ((cx, cy), (120 * PP, 80 * PP), angulo)
        caja = cv2.boxPoints(rect).astype(np.int32)
        cv2.fillPoly(img, [caja], gris_pieza)
        cv2.circle(img, (int(cx), int(cy)), int(15 * PP), 245, -1)
        if angulo == 0:
            cv2.rectangle(img, (int(cx + 50 * PP), int(cy - 5 * PP)), (int(cx + 60 * PP), int(cy + 5 * PP)), 245, -1)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def fotografiar(img, torcer=0.12, luz=0.35, borroso=1.5, ruido=6, semilla=1):
    """Simula el celular: perspectiva, luz de un lado, desenfoque, ruido, JPG."""
    rng = np.random.default_rng(semilla)
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    d = lambda: rng.uniform(-torcer, torcer)   # noqa: E731
    dst = np.float32([[w * d(), h * d()], [w * (1 + d()), h * d()], [w * (1 + d()), h * (1 + d())], [w * d(), h * (1 + d())]])
    dst -= dst.min(axis=0) - 50
    M = cv2.getPerspectiveTransform(src, dst)
    W, H = int(dst[:, 0].max() + 50), int(dst[:, 1].max() + 50)
    foto = cv2.warpPerspective(img, M, (W, H), borderValue=(90, 80, 70))     # mesa de fondo
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    gradiente = 1.0 - luz * (X / W) * 0.7 - luz * (Y / H) * 0.3
    foto = np.clip(foto.astype(np.float32) * gradiente[..., None], 0, 255)
    foto = cv2.GaussianBlur(foto, (0, 0), borroso)
    foto = np.clip(foto + rng.normal(0, ruido, foto.shape), 0, 255).astype(np.uint8)
    ok, jpg = cv2.imencode(".jpg", foto, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return cv2.imdecode(jpg, cv2.IMREAD_COLOR)


# --- marcas
for i in range(4):
    m = fd.imagen_marca(i, 120)
    revisar(f"marca {i} se genera", m.shape == (120, 120) and set(np.unique(m)) <= {0, 255})

# --- caso 1: placa recta, foto torcida con luz dispareja
hoja = hoja_con_pieza()
foto = fotografiar(hoja, semilla=1)
cv2.imwrite(os.path.join(SALIDA, "foto-simulada-1.jpg"), foto)
e, piezas = fd.procesar_con_hoja(foto)
revisar("encuentra las 4 marcas y endereza", e is not None)
revisar(f"error de las marcas pequeño ({e.error_mm:.2f} mm)", e.error_mm is not None and e.error_mm < 0.6, e.error_mm)
revisar("encuentra 1 pieza", len(piezas) == 1, len(piezas))
p = piezas[0]
revisar(f"ancho 120 mm (sale {p.ancho:.2f})", abs(p.ancho - 120) < 0.8, p.ancho)
revisar(f"alto 80 mm (sale {p.alto:.2f})", abs(p.alto - 80) < 0.8, p.alto)
revisar("1 hueco", len(p.huecos) == 1, len(p.huecos))
if p.huecos:
    hx = [x for x, _ in p.huecos[0]]
    revisar(f"hueco Ø30 (sale {max(hx) - min(hx):.2f})", abs(max(hx) - min(hx) - 30) < 0.8, max(hx) - min(hx))
area_real = 120 * 80 - math.pi * 15 ** 2 - 10 * 10
revisar(f"área ≈ {area_real:.0f} mm² (sale {p.area:.0f})", abs(p.area - area_real) / area_real < 0.02, p.area)
revisar("no toca el borde", not p.toca_borde)
ruta = os.path.join(SALIDA, "foto-a-dxf-1.dxf")
fd.guardar_dxf(piezas, ruta, "PLACA")
doc = ezdxf.readfile(ruta)
polis = [x for x in doc.modelspace() if x.dxftype() == "LWPOLYLINE"]
revisar("DXF: 2 contornos cerrados en CORTE", len(polis) == 2 and all(x.closed and x.dxf.layer == "CORTE" for x in polis))
revisar("DXF en milímetros", doc.header.get("$INSUNITS") == 4)
xs = [pt[0] for x in polis for pt in x.get_points()]
ys = [pt[1] for x in polis for pt in x.get_points()]
revisar("DXF: la pieza arranca en 0,0", abs(min(xs)) < 1e-6 and abs(min(ys)) < 1e-6)
revisar("DXF: tiene texto de referencia", any(x.dxftype() == "TEXT" and x.dxf.layer == "REFERENCIA" for x in doc.modelspace()))
# la muesca: la pieza tiene más de 4 esquinas
revisar(f"la muesca aparece ({len(p.contorno)} esquinas)", len(p.contorno) >= 8, len(p.contorno))

# --- caso 2: placa girada 30°, otra foto, pieza más clara (gris 140)
foto = fotografiar(hoja_con_pieza(gris_pieza=140, angulo=30), torcer=0.15, luz=0.45, semilla=7)
cv2.imwrite(os.path.join(SALIDA, "foto-simulada-2.jpg"), foto)
e, piezas = fd.procesar_con_hoja(foto)
p = piezas[0]
lados = sorted(math.dist(a, b) for a, b in zip(p.contorno, p.contorno[1:] + p.contorno[:1]))
revisar(f"girada 30°: lados 80 y 120 (salen {lados[-1]:.1f}, {lados[-3]:.1f})",
        abs(lados[-1] - 120) < 1.0 and abs(lados[-2] - 120) < 1.0 and abs(lados[-3] - 80) < 1.0 and abs(lados[-4] - 80) < 1.0, lados[-4:])
revisar(f"girada: área ≈ {120 * 80 - math.pi * 225:.0f} (sale {p.area:.0f})", abs(p.area - (120 * 80 - math.pi * 225)) / 9000 < 0.02)

# --- caso 3: umbral a mano y suavizado mayor siguen funcionando
e, piezas = fd.procesar_con_hoja(foto, fd.Ajustes(umbral=170, suavizado_mm=1.0))
revisar("umbral a mano: sale la pieza", piezas and abs(piezas[0].area - (120 * 80 - math.pi * 225)) / 9000 < 0.04,
        piezas[0].area if piezas else None)

# --- caso 4: sin pieza → nada (las marcas no cuentan como piezas)
foto = fotografiar(hoja_con_pieza(pieza=False), semilla=3)
e, piezas = fd.procesar_con_hoja(foto)
revisar("hoja vacía: no inventa piezas", len(piezas) == 0, [(round(x.ancho), round(x.alto)) for x in piezas])

# --- caso 5: una marca tapada → mensaje claro
foto = fotografiar(hoja_con_pieza(), semilla=1)
c, _ = fd.buscar_marcas(foto)
x, y = map(int, c[2])
cv2.rectangle(foto, (x - 200, y - 200), (x + 200, y + 200), (60, 60, 60), -1)
try:
    fd.procesar_con_hoja(foto)
    revisar("marca tapada: avisa", False)
except ValueError as err:
    revisar("marca tapada: avisa cuál falta", "2" in str(err) and "marcas" in str(err), str(err))

# --- caso 6: 4 esquinas a mano (lámina de 1220 x 2440 vista de lado, sin marcas)
lam = np.full((2440 // 2, 1220 // 2, 3), 230, np.uint8)        # 0,5 px/mm
cv2.circle(lam, (305, 610), 100, (40, 40, 40), -1)               # disco Ø400 en el centro
foto = cv2.copyMakeBorder(lam, 0, 0, 0, 0, cv2.BORDER_CONSTANT)
h, w = lam.shape[:2]
src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
dst = np.float32([[120, 80], [700, 140], [760, 1300], [60, 1250]])
foto = cv2.warpPerspective(lam, cv2.getPerspectiveTransform(src, dst), (820, 1380), borderValue=(80, 80, 80))
e = fd.enderezar(foto, dst.tolist(), 1220, 2440)
pz = fd.contornos(e, fd.Ajustes())
revisar("4 esquinas a mano: encuentra el disco", len(pz) == 1, len(pz))
if pz:
    revisar(f"disco Ø400 (sale {pz[0].ancho:.0f} x {pz[0].alto:.0f})",
            abs(pz[0].ancho - 400) < 8 and abs(pz[0].alto - 400) < 8, (pz[0].ancho, pz[0].alto))

# --- ruta con tildes y eñes
ruta = os.path.join(SALIDA, "foto ñandú áéí.jpg")
cv2.imencode(".jpg", fotografiar(hoja_con_pieza(), semilla=2))[1].tofile(ruta)
revisar("abre fotos con tildes y eñes en el nombre", fd.leer_foto(ruta).shape[0] > 100)
try:
    fd.leer_foto(os.path.join(SALIDA, "foto-a-dxf-1.dxf"))
    revisar("archivo que no es foto: avisa", False)
except ValueError:
    revisar("archivo que no es foto: avisa", True)

# ======================= casos que encontró la revisión (2026-11-11) =======================
def hoja_con(dibujar, semilla=5, **foto):
    """Hoja con marcas + lo que dibuje la función (recibe la imagen y el centro de la marca 0 en px)."""
    img = hoja_con_pieza(pieza=False)
    dibujar(img, OX * PP, OY * PP)
    return fotografiar(img, semilla=semilla, **foto)


# R1. pieza grande (más de la mitad de la zona): sin huecos falsos
for w, h in [(120, 170), (140, 200)]:
    def placa(img, x0, y0, w=w, h=h):
        cx, cy = x0 + fd.HOJA_ANCHO / 2 * PP, y0 + fd.HOJA_ALTO / 2 * PP
        cv2.rectangle(img, (int(cx - w / 2 * PP), int(cy - h / 2 * PP)), (int(cx + w / 2 * PP), int(cy + h / 2 * PP)),
                      (70, 70, 70), -1)
    e, pz = fd.procesar_con_hoja(hoja_con(placa, luz=0.3))
    ok = len(pz) == 1 and not pz[0].huecos and abs(pz[0].area - w * h) / (w * h) < 0.02
    revisar(f"placa grande {w}x{h}: sin hueco falso", ok,
            [(round(p.ancho), round(p.alto), len(p.huecos), round(p.area)) for p in pz])

# R2. huecos redondos pequeños: redondos y de su medida
def brida(img, x0, y0):
    cx, cy = x0 + fd.HOJA_ANCHO / 2 * PP, y0 + fd.HOJA_ALTO / 2 * PP
    cv2.rectangle(img, (int(cx - 60 * PP), int(cy - 40 * PP)), (int(cx + 60 * PP), int(cy + 40 * PP)), (60, 60, 60), -1)
    for k, d in enumerate([5, 6, 8, 10, 12]):
        cv2.circle(img, (int(cx - 45 * PP + k * 22 * PP), int(cy)), int(d / 2 * PP), (245, 245, 245), -1)
e, pz = fd.procesar_con_hoja(hoja_con(brida, semilla=8))
diam = sorted(max(x for x, _ in hh) - min(x for x, _ in hh) for hh in pz[0].huecos) if pz else []
revisar(f"huecos pequeños Ø5..Ø12 con su medida (salen {[round(d, 1) for d in diam]})",
        len(diam) == 5 and all(abs(d - r) < 0.6 for d, r in zip(diam, [5, 6, 8, 10, 12])), diam)
revisar("huecos pequeños: redondos (8 o más lados)", pz and all(len(hh) >= 8 for hh in pz[0].huecos),
        [len(hh) for hh in pz[0].huecos] if pz else None)

# R3. 4 marcas grandes sueltas y giradas: la pieza sale bien usando solo los centros
P2 = 2.0                                       # 2 px/mm, rectángulo 600 x 600, marcas de 150
lienzo = np.full((int(900 * P2), int(900 * P2), 3), 240, np.uint8)
cen = [(150, 150), (750, 150), (750, 750), (150, 750)]
for i, ((cx, cy), giro) in enumerate(zip(cen, [3, 90, 180, -4])):
    lado = int(150 * P2)
    m = cv2.cvtColor(cv2.resize(fd.imagen_marca(i, 200), (lado, lado), interpolation=cv2.INTER_NEAREST), cv2.COLOR_GRAY2BGR)
    m = cv2.copyMakeBorder(m, lado // 2, lado // 2, lado // 2, lado // 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    R = cv2.getRotationMatrix2D((m.shape[1] / 2, m.shape[0] / 2), giro, 1.0)
    m = cv2.warpAffine(m, R, (m.shape[1], m.shape[0]), borderValue=(240, 240, 240))
    x0, y0 = int(cx * P2 - m.shape[1] / 2), int(cy * P2 - m.shape[0] / 2)
    lienzo[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] = m
cv2.rectangle(lienzo, (int(350 * P2), int(400 * P2)), (int(550 * P2), int(500 * P2)), (50, 50, 50), -1)
foto = fotografiar(lienzo, torcer=0.08, semilla=12)
e, pz = fd.procesar_con_hoja(foto, ancho=600, alto=600, lado_marca=150, alineadas=False)
revisar(f"marcas sueltas giradas: pieza 200 x 100 (sale {pz[0].ancho:.1f} x {pz[0].alto:.1f})" if pz else "marcas sueltas: pieza",
        pz and abs(pz[0].ancho - 200) < 2 and abs(pz[0].alto - 100) < 2)

# R4. esquinas a mano en otro orden: se ordenan solas
orden, cambio = fd.ordenar_esquinas([(0, 0), (0, 10), (10, 10), (10, 0)])        # antihorario en pantalla
revisar("esquinas al revés: se ordenan", orden == [(0, 0), (10, 0), (10, 10), (0, 10)] and cambio, orden)
orden, cambio = fd.ordenar_esquinas([(0, 0), (10, 0), (0, 10), (10, 10)])        # en Z
revisar("esquinas en Z: se ordenan", orden == [(0, 0), (10, 0), (10, 10), (0, 10)] and cambio, orden)
orden, cambio = fd.ordenar_esquinas([(1, 1), (11, 0), (12, 9), (0, 10)])
revisar("esquinas bien puestas: no se tocan", not cambio, orden)

# R5. pieza metida en el cuadro de una marca: avisa
def invasora(img, x0, y0):
    cv2.rectangle(img, (int(x0 + 14 * PP), int(y0 + 14 * PP)), (int(x0 + 156 * PP), int(y0 + 100 * PP)), (60, 60, 60), -1)
e, pz = fd.procesar_con_hoja(hoja_con(invasora, semilla=9))
revisar("pieza metida en una marca: avisa que puede estar recortada", pz and pz[0].toca_borde)
e, pz = fd.procesar_con_hoja(hoja_con(lambda img, x0, y0: cv2.rectangle(
    img, (int(x0 + 40 * PP), int(y0 + 40 * PP)), (int(x0 + 130 * PP), int(y0 + 120 * PP)), (60, 60, 60), -1), semilla=9))
revisar("pieza lejos de las marcas: no avisa", pz and not pz[0].toca_borde)

# R6. foto enorme: la foto enderezada no pasa de 12 megapíxeles
grande = np.full((6000, 8000, 3), 230, np.uint8)
e = fd.enderezar(grande, [(100, 100), (7900, 100), (7900, 5900), (100, 5900)], 1000, 800)
revisar(f"foto de 48 MP: enderezada ≤ 12 MP (sale {e.imagen.shape[0] * e.imagen.shape[1] / 1e6:.1f})",
        e.imagen.shape[0] * e.imagen.shape[1] <= 12.2e6)

# R9. PNG transparente: el fondo transparente es blanco, no negro
png = np.zeros((200, 200, 4), np.uint8)
png[50:150, 50:150] = (40, 40, 40, 255)
ruta = os.path.join(SALIDA, "transparente.png")
cv2.imencode(".png", png)[1].tofile(ruta)
im = fd.leer_foto(ruta)
revisar("PNG transparente: fondo blanco y pieza oscura", im.shape == (200, 200, 3) and im[5, 5].min() > 250 and im[100, 100].max() < 60)
gris = np.full((50, 50), 128, np.uint8)
cv2.imencode(".png", gris)[1].tofile(ruta)
revisar("foto en gris: se abre en color", fd.leer_foto(ruta).shape == (50, 50, 3))

print(f"\n{'TODO BIEN' if mal == 0 else f'{mal} con problemas'}")
sys.exit(1 if mal else 0)
