"""Pruebas del acomodo de piezas en la lámina (core/edwin_nesting.py).
Correr desde la raíz del repositorio:  py -3.10 -I edwin/pruebas/prueba_nesting.py
Revisa con la geometría REAL (no con la cuadrícula) que ninguna pieza se monte sobre otra,
que respeten la separación y el margen, y que no se pierda ninguna. Son las mismas pruebas
de EDWIN CNC CAD-CAM 2D (plugins/edwincnc/pruebas_nesting.cpp)."""
import math
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)

from core import edwin_nesting as nz  # noqa: E402

mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


def circulo(cx, cy, r, n=72):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rect(x0, y0, w, h):
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def abanico(R, r, th, n=40):
    p = [(R * math.sin(-th / 2 + th * i / n), R * math.cos(-th / 2 + th * i / n)) for i in range(n + 1)]
    p += [(r * math.sin(-th / 2 + th * i / n), r * math.cos(-th / 2 + th * i / n)) for i in range(n, -1, -1)]
    return p


def mover(p, c):
    out = []
    for v in p:
        g = nz.girar(v, c.angulo)
        out.append((g[0] + c.dx, g[1] + c.dy))
    return out


def dist_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L if L else 0
    t = max(0.0, min(1.0, t))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def dentro(p, q):
    c = False
    j = len(q) - 1
    for i in range(len(q)):
        if (q[i][1] > p[1]) != (q[j][1] > p[1]) and p[0] < (q[j][0] - q[i][0]) * (p[1] - q[i][1]) / (q[j][1] - q[i][1]) + q[i][0]:
            c = not c
        j = i
    return c


def dist_pol(a, b):
    d = 1e300
    for i in range(len(a)):
        for j in range(len(b)):
            d = min(d, dist_seg(a[i], b[j], b[(j + 1) % len(b)]), dist_seg(b[j], a[i], a[(i + 1) % len(a)]))
    return d


def montadas(A, ca, B, cb, sep):
    a, b = mover(A.afuera, ca), mover(B.afuera, cb)
    d = dist_pol(a, b)
    if dentro(a[0], b):
        for h in B.huecos:
            hh = mover(h, cb)
            if dentro(a[0], hh):
                d = dist_pol(a, hh)
                return d < sep - 1e-6, d
        return True, d
    if dentro(b[0], a):
        for h in A.huecos:
            hh = mover(h, ca)
            if dentro(b[0], hh):
                d = dist_pol(b, hh)
                return d < sep - 1e-6, d
        return True, d
    return d < sep - 1e-6, d


def revisar_resultado(nombre, ps, op, r):
    esperadas = sum(p.cantidad for i, p in enumerate(ps) if i not in r.no_caben)
    revisar(f"{nombre}: se colocaron todas ({len(r.colocadas)} de {esperadas})", len(r.colocadas) == esperadas)
    fuera = 0
    peor = 1e300
    for i, ci in enumerate(r.colocadas):
        for v in mover(ps[ci.pieza].afuera, ci):
            if v[0] < op.margen - 1e-6 or v[1] < op.margen - 1e-6 or v[0] > op.ancho - op.margen + 1e-6 or v[1] > op.alto - op.margen + 1e-6:
                fuera += 1
                break
        for cj in r.colocadas[i + 1:]:
            if ci.lamina != cj.lamina:
                continue
            m, d = montadas(ps[ci.pieza], ci, ps[cj.pieza], cj, op.separacion)
            peor = min(peor, d)
            if m:
                fuera += 1
    revisar(f"{nombre}: ninguna montada ni fuera del margen", fuera == 0, fuera)
    uso = sum(r.uso_por_lamina) / max(1, r.laminas) * 100
    print(f"    {len(r.colocadas)} piezas en {r.laminas} lámina(s), celda {r.celda:.2f} mm, uso medio {uso:.1f} %, "
          f"menor separación {peor if peor < 1e200 else 0:.2f} mm")


op = nz.Opciones()

# 1) diez rectángulos de 500 x 300 caben en una lámina
ps = [nz.Pieza(rect(0, 0, 500, 300), cantidad=10)]
r = nz.acomodar(ps, op)
revisar_resultado("rectángulos", ps, op, r)
revisar("10 rectángulos 500x300 en 1 lámina", r.laminas == 1, r.laminas)

# 2) el disco solo cabe dentro del hueco del aro
o2 = nz.Opciones(ancho=700, alto=640)
ps = [nz.Pieza(circulo(0, 0, 300), [circulo(0, 0, 200)]), nz.Pieza(circulo(0, 0, 120))]
r = nz.acomodar(ps, o2)
revisar_resultado("aro con disco", ps, o2, r)
revisar("el disco cae dentro del hueco del aro (1 lámina)", r.laminas == 1 and len(r.colocadas) == 2, r.laminas)

# 3) medias piezas de tolva cónica
ps = [nz.Pieza(abanico(1897.4, 948.7, 0.9933), cantidad=4)]
r = nz.acomodar(ps, op)
revisar_resultado("abanicos", ps, op, r)
revisar("4 medias piezas en máximo 4 láminas", r.laminas <= 4, r.laminas)

# 4) pieza que no cabe
ps = [nz.Pieza(rect(0, 0, 3000, 1500)), nz.Pieza(rect(0, 0, 100, 100), cantidad=3)]
r = nz.acomodar(ps, op)
revisar_resultado("no cabe", ps, op, r)
revisar("la de 3000x1500 sale en 'no caben'", r.no_caben == [0], r.no_caben)

# 5) mezcla grande: 30 discos, 20 rectángulos, 10 bridas con huecos, 8 abanicos
brida = nz.Pieza(circulo(0, 0, 160), [circulo(0, 0, 70)] +
                 [circulo(115 * math.cos(k * math.pi / 2), 115 * math.sin(k * math.pi / 2), 9, 24) for k in range(4)], 10)
ps = [nz.Pieza(circulo(0, 0, 90), cantidad=30), nz.Pieza(rect(0, 0, 260, 140), cantidad=20), brida,
      nz.Pieza(abanico(700, 350, 1.0), cantidad=8)]
t0 = time.perf_counter()
r = nz.acomodar(ps, op)
seg = time.perf_counter() - t0
revisar_resultado("mezcla", ps, op, r)
print(f"    tiempo: {seg:.2f} s")
revisar("la mezcla de 68 piezas se acomoda en menos de 30 s", seg < 30, seg)

# 6) sin girar: 5 piezas de 2300 x 100 acostadas
o6 = nz.Opciones(giros=1)
ps = [nz.Pieza(rect(0, 0, 2300, 100), cantidad=5)]
r = nz.acomodar(ps, o6)
revisar_resultado("largas sin girar", ps, o6, r)
revisar("5 piezas de 2300x100 en 1 lámina sin girar", r.laminas == 1, r.laminas)

# 6b) piezas rotas o gigantes (dibujo en metros leído como mm): no caben y no agotan la memoria
ps = [nz.Pieza(rect(0, 0, 5e9, 5e9)), nz.Pieza([(0, 0), (float("nan"), 0), (100, 100)]), nz.Pieza(rect(0, 0, 100, 100))]
t0 = time.perf_counter()
r = nz.acomodar(ps, op)
revisar("gigante y con NaN: 2 en 'no caben', 1 colocada", sorted(r.no_caben) == [0, 1] and len(r.colocadas) == 1,
        (r.no_caben, len(r.colocadas)))
revisar("gigante: rápido (sin reservar la cuadrícula)", time.perf_counter() - t0 < 5)

# 7) desde piezas del desdoblado (con arcos): tolva cónica real desdoblada
from core import edwin_desdoblar as ed  # noqa: E402
from core import edwin_piezas3d as p3  # noqa: E402
parte = p3.construir("conica", {"ds": 1200, "di": 600, "alto": 900, "tramos": 72})[0]
malla = ed.Malla(parte.vertices, parte.caras, parte.huecos)
mitad = list(range(36))
planas = ed.desdoblar(malla, mitad)
pzs = nz.desde_desdoblado(planas, cantidad=2)
r = nz.acomodar(pzs, op)
revisar_resultado("media tolva cónica desdoblada x2", pzs, op, r)
acom, lams = nz.piezas_acomodadas(planas, r, op)
revisar("piezas acomodadas: una copia por colocación", len(acom) == len(r.colocadas), (len(acom), len(r.colocadas)))
salida = os.path.join(os.path.dirname(__file__), "salida")
os.makedirs(salida, exist_ok=True)
ruta = ed.guardar_dxf(acom, os.path.join(salida, "nesting-tolva.dxf"), "TOLVA", laminas=lams)
import ezdxf  # noqa: E402
doc = ezdxf.readfile(ruta)
capas = {e.dxf.layer for e in doc.modelspace()}
revisar("DXF con CORTE y REFERENCIA (láminas)", {"CORTE", "REFERENCIA"} <= capas, capas)

print()
print("TODO BIEN" if mal == 0 else f"{mal} PRUEBA(S) MAL")
sys.exit(1 if mal else 0)
