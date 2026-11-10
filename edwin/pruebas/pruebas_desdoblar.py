"""Pruebas del desdoblado.  Correr:  py -3.10 -I pruebas_desdoblar.py"""
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import edwin_desdoblar as ed  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(AQUI, "salida")
os.makedirs(SALIDA, exist_ok=True)

ok = 0
mal = 0


def revisar(nombre, cond, detalle=""):
    global ok, mal
    if cond:
        ok += 1
        print(f"  OK   {nombre}")
    else:
        mal += 1
        print(f"  MAL  {nombre}  {detalle}")


# ------------------------------------------------------------ mallas de prueba
def tolva_conica(d_arriba, d_abajo, alto, lados=72):
    ra, rb = d_arriba / 2, d_abajo / 2
    V, F = [], []
    for i in range(lados):
        t = 2 * math.pi * i / lados
        V.append((rb * math.cos(t), rb * math.sin(t), 0.0))       # abajo: 0..n-1
    for i in range(lados):
        t = 2 * math.pi * i / lados
        V.append((ra * math.cos(t), ra * math.sin(t), alto))      # arriba: n..2n-1
    for i in range(lados):
        j = (i + 1) % lados
        F.append([i, j, lados + j, lados + i])
    return ed.Malla(V, F)


def tolva_cuadrada(a_arriba, a_abajo, alto):
    A, B = a_arriba / 2, a_abajo / 2
    V = [(-B, -B, 0), (B, -B, 0), (B, B, 0), (-B, B, 0),
         (-A, -A, alto), (A, -A, alto), (A, A, alto), (-A, A, alto)]
    F = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return ed.Malla(V, F)


def cubo(a):
    V = [(0, 0, 0), (a, 0, 0), (a, a, 0), (0, a, 0), (0, 0, a), (a, 0, a), (a, a, a), (0, a, a)]
    F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return ed.Malla(V, F)


def arcos(lazo):
    """[(centro, radio, angulo_grados)] de los tramos con bulge."""
    out = []
    for k, (x, y, bl) in enumerate(lazo):
        if not bl:
            continue
        x2, y2, _ = lazo[(k + 1) % len(lazo)]
        ang = 4 * math.atan(bl)
        cuerda = math.hypot(x2 - x, y2 - y)
        r = abs(cuerda / (2 * math.sin(ang / 2)))
        m = ed._punto_en_arco((x, y), (x2, y2), bl, 0.5)
        c = ed._circulo((x, y), m, (x2, y2))
        out.append((c[0], r, math.degrees(abs(ang))))
    return out


# ------------------------------------------------------------ 1. tolva cónica de prueba
print("1. Tolva cónica Ø600 -> Ø300, alto 400 (medida interna)")
N = 72
m = tolva_conica(600, 300, 400, N)
pz = ed.desdoblar(m)
revisar("sale una sola pieza", len(pz) == 1, len(pz))
p = pz[0]
revisar("sin avisos", not p.avisos, p.avisos)
revisar("sin líneas de doblez (es curva suave, se rola)", not p.dobleces, len(p.dobleces))
revisar("un solo contorno", len(p.contornos) == 1, len(p.contornos))
c = p.contornos[0]
revisar("contorno = 2 arcos + 2 rectas (4 tramos)", len(c) == 4, len(c))
ar = sorted(arcos(c), key=lambda a: a[1])
revisar("tiene 2 arcos", len(ar) == 2, ar)
s = math.hypot(150, 400)               # 427,2
revisar("radio chico 427,2", abs(ar[0][1] - s) < 0.1, ar[0][1])
revisar("radio grande 854,4", abs(ar[1][1] - 2 * s) < 0.1, ar[1][1])
revisar("los dos arcos tienen el mismo centro (punta del cono)",
        math.dist(ar[0][0], ar[1][0]) < 0.1, (ar[0][0], ar[1][0]))
# ángulo exacto para 72 caras (cada cuerda se acuesta tal cual)
cuerda = 2 * 150 * math.sin(math.pi / N)
esperado = math.degrees(2 * math.asin(cuerda / (2 * s))) * N
revisar(f"ángulo {esperado:.2f}° (cono liso: 126,42°)", abs(ar[0][2] - esperado) < 0.05 and abs(ar[1][2] - esperado) < 0.05,
        (ar[0][2], ar[1][2]))
area_real = sum(abs(ed.area2d([(x, y) for x, y in pol])) for pol in p.poligonos.values())
area_cono = math.pi * (300 + 150) * s
revisar("área ≈ área del cono liso (±0,2 %)", abs(area_real - area_cono) / area_cono < 0.002, (area_real, area_cono))
ancho, alto = ed.medidas(p)
print(f"     lámina necesaria: {ancho:.1f} x {alto:.1f} mm")
ed.guardar_dxf(pz, os.path.join(SALIDA, "tolva-conica-600-300-400.dxf"), "TOLVA CONICA 600-300 H400")

# ------------------------------------------------------------ 2. media tolva (selección)
print("2. Media tolva cónica (seleccionar 36 de 72 caras)")
pz = ed.desdoblar(m, seleccion=list(range(36)))
ar = arcos(pz[0].contornos[0])
revisar("2 arcos de la mitad del ángulo", len(ar) == 2 and all(abs(a[2] - esperado / 2) < 0.05 for a in ar),
        [a[2] for a in ar])
ed.guardar_dxf(pz, os.path.join(SALIDA, "media-tolva-conica.dxf"), "MEDIA TOLVA")

print("2b. Dos grupos separados (caras 0-9 y 30-39) -> 2 piezas")
pz = ed.desdoblar(m, seleccion=list(range(10)) + list(range(30, 40)))
revisar("2 piezas", len(pz) == 2, len(pz))
x1 = max(x for x, y, b in pz[0].contornos[0])
x2 = min(x for x, y, b in pz[1].contornos[0])
revisar("no se tocan en el DXF (separación 20 mm)", x2 - x1 >= 19.9, (x1, x2))

# ------------------------------------------------------------ 3. tolva cuadrada
print("3. Tolva cuadrada 600 -> 300, alto 400")
m2 = tolva_cuadrada(600, 300, 400)
pz = ed.desdoblar(m2)
p = pz[0]
revisar("una pieza sin avisos", len(pz) == 1 and not p.avisos, p.avisos)
revisar("3 dobleces marcados (la 4a arista es la costura)", len(p.dobleces) == 3, len(p.dobleces))
lado_inc = math.hypot(150, 400)  # altura inclinada de cada cara
n1 = ed._unit(ed._cruz((1, 0, 0), (0, -150, 400)))
n2 = ed._unit(ed._cruz((0, 1, 0), (150, 0, 400)))
ang_esp = math.degrees(math.acos(ed._punto(n1, n2)))
revisar(f"cada doblez {ang_esp:.1f}°", all(abs(d.angulo - ang_esp) < 0.01 for d in p.dobleces),
        [d.angulo for d in p.dobleces])
revisar("contorno sin arcos", all(b == 0 for x, y, b in p.contornos[0]))
area = 4 * (600 + 300) / 2 * math.sqrt(400 ** 2 + 150 ** 2)
revisar("área correcta", abs(p.area - area) < 0.01, (p.area, area))
ed.guardar_dxf(pz, os.path.join(SALIDA, "tolva-cuadrada-600-300-400.dxf"), "TOLVA CUADRADA")

# ------------------------------------------------------------ 4. cubo
print("4. Cubo 100 (6 caras)")
pz = ed.desdoblar(cubo(100))
p = pz[0]
revisar("5 dobleces de 90°", len(p.dobleces) == 5 and all(abs(d.angulo - 90) < 1e-6 for d in p.dobleces),
        [d.angulo for d in p.dobleces])
revisar("área 60 000 mm²", abs(p.area - 60000) < 1e-6, p.area)
revisar("no se monta", not any("monta" in a for a in p.avisos), p.avisos)
ed.guardar_dxf(pz, os.path.join(SALIDA, "cubo-100.dxf"), "CUBO")

# ------------------------------------------------------------ 5. casos con problemas
print("5. Casos con problemas")
m3 = tolva_cuadrada(600, 300, 400)
m3.vertices[5] = (300, -300, 430)          # una esquina levantada: 2 caras torcidas
pz = ed.desdoblar(m3)
revisar("avisa caras torcidas", sum("torcida" in a for a in pz[0].avisos) == 2, pz[0].avisos)

m4 = cubo(100)
m4.caras[3] = list(reversed(m4.caras[3]))  # cara volteada
pz = ed.desdoblar(m4)
revisar("avisa y corrige cara volteada", any("volteada" in a for a in pz[0].avisos) and abs(pz[0].area - 60000) < 1e-6,
        pz[0].avisos)
revisar("cara volteada: sigue sin montarse", not any("monta" in a for a in pz[0].avisos), pz[0].avisos)
revisar("cara volteada: 5 dobleces de 90° hacia abajo",
        len(pz[0].dobleces) == 5 and all(abs(d.angulo - 90) < 1e-6 and d.hacia == "abajo" for d in pz[0].dobleces),
        [(round(d.angulo, 1), d.hacia) for d in pz[0].dobleces])
revisar("cara volteada: solo avisa esa cara", sum("volteada" in a for a in pz[0].avisos) == 1, pz[0].avisos)

m4b = cubo(100)
m4b.caras[0] = list(reversed(m4b.caras[0]))  # la cara raíz volteada: avisa las demás, pero el plano sale igual
pz = ed.desdoblar(m4b)
revisar("raíz volteada: plano correcto (área y 5 dobleces de 90°)",
        abs(pz[0].area - 60000) < 1e-6 and len(pz[0].dobleces) == 5
        and all(abs(d.angulo - 90) < 1e-6 for d in pz[0].dobleces), pz[0].avisos)

# ------------------------------------------------------------ 5b. huecos
print("5b. Caras con huecos")
# placa 200x100 con hueco cuadrado 40x40 (como lo guarda IngeTrazo: hueco en cualquier sentido)
V = [(0, 0, 0), (200, 0, 0), (200, 100, 0), (0, 100, 0), (80, 30, 0), (120, 30, 0), (120, 70, 0), (80, 70, 0)]
pz = ed.desdoblar(ed.Malla(V, [[0, 1, 2, 3]], {0: [[4, 5, 6, 7]]}))
p = pz[0]
revisar("placa con hueco: 2 contornos", len(p.contornos) == 2, len(p.contornos))
revisar("placa con hueco: área 18 400", abs(p.area - 18400) < 1e-6, p.area)
revisar("hueco en sentido contrario al borde",
        ed.area2d([(x, y) for x, y, b in p.contornos[0]]) * ed.area2d([(x, y) for x, y, b in p.contornos[1]]) < 0)
# la tapa del hueco también seleccionada y doblada 90° (como una pestaña que se levanta)
V2 = V + [(80, 30, 40), (120, 30, 40)]
F2 = [[0, 1, 2, 3], [4, 5, 9, 8]]           # pestaña vertical sobre la arista 4-5 del hueco
pz = ed.desdoblar(ed.Malla(V2, F2, {0: [[4, 7, 6, 5]]}))
p = pz[0]
revisar("pestaña en el hueco: 1 doblez de 90°", len(p.dobleces) == 1 and abs(p.dobleces[0].angulo - 90) < 1e-6,
        [(d.angulo, d.hacia) for d in p.dobleces])
revisar("pestaña en el hueco: área 18 400 + 1 600", abs(p.area - 20000) < 1e-6, p.area)
ed.guardar_dxf(pz, os.path.join(SALIDA, "placa-con-pestana.dxf"), "PLACA")

ocho = [(0, 0), (10, 10), (10, 0), (0, 10)]
revisar("detecta contorno que se cruza", ed._se_monta([ocho]))
revisar("cuadrado no se cruza", not ed._se_monta([[(0, 0), (10, 0), (10, 10), (0, 10)]]))

# "silla de montar": 6 triángulos de 90° alrededor de un punto (suman 540° > 360°) -> se monta
cf = math.sqrt(0.7824)
V = [(0, 0, 0)] + [((100, 70)[k % 2] * cf * math.cos(math.radians(60 * k + 7 * (k % 3))),
                    (100, 70)[k % 2] * cf * math.sin(math.radians(60 * k + 7 * (k % 3))),
                    (100, 70)[k % 2] * (-1) ** k * math.sqrt(1 - 0.7824)) for k in range(6)]
F = [[0, 1 + k, 1 + (k + 1) % 6] for k in range(6)]
pz = ed.desdoblar(ed.Malla(V, F))
revisar("silla de montar: avisa que se monta", any("monta" in a for a in pz[0].avisos), pz[0].avisos)

# ------------------------------------------------------------ 6. DXF
print("6. DXF")
import ezdxf  # noqa: E402
doc = ezdxf.readfile(os.path.join(SALIDA, "tolva-conica-600-300-400.dxf"))
msp = doc.modelspace()
capas = {e.dxf.layer for e in msp}
revisar("capas CORTE y REFERENCIA", {"CORTE", "REFERENCIA"} <= capas, capas)
pl = [e for e in msp.query("LWPOLYLINE")]
revisar("1 polilínea cerrada en CORTE", len(pl) == 1 and pl[0].closed and pl[0].dxf.layer == "CORTE")
revisar("en milímetros", doc.header["$INSUNITS"] == 4)
aud = doc.audit()
revisar("DXF sin errores", not aud.has_errors, aud.errors)
doc = ezdxf.readfile(os.path.join(SALIDA, "tolva-cuadrada-600-300-400.dxf"))
revisar("tolva cuadrada: 3 líneas en MARCADO",
        len([e for e in doc.modelspace().query("LINE") if e.dxf.layer == "MARCADO"]) == 3)

print(f"\n{ok} bien, {mal} mal")
sys.exit(1 if mal else 0)

