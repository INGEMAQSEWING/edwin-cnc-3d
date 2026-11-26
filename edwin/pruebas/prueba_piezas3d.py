"""Pruebas de «Insertar pieza por medidas» (core/edwin_piezas3d.py).
Correr desde la raíz del repositorio:  py -3.10 -I edwin/pruebas/prueba_piezas3d.py
Construye cada pieza, la desdobla con «Desdoblar caras» (core/edwin_desdoblar.py) y compara
el plano con las fórmulas de las calculadoras (las mismas de piezas.h del CAD-CAM 2D)."""
import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, RAIZ)

from core import edwin_desdoblar as ed  # noqa: E402
from core import edwin_piezas3d as p3  # noqa: E402

PI = math.pi
mal = 0


def revisar(nombre, cond, detalle=""):
    global mal
    print(("  OK   " if cond else "  MAL  ") + nombre + ("" if cond else f"  {detalle}"))
    mal += 0 if cond else 1


def area3d(parte, caras=None):
    s = 0.0
    for k in (caras if caras is not None else range(len(parte.caras))):
        pts = [parte.vertices[i] for i in parte.caras[k]]
        n = p3._normal(pts)
        s += math.sqrt(p3._punto(n, n)) / 2
    return s


def desdoblar(parte, caras=None):
    malla = ed.Malla(parte.vertices, parte.caras, parte.huecos)
    return ed.desdoblar(malla, caras)


def sin_avisos(piezas):
    return [a for pz in piezas for a in pz.avisos]


def area_plana(piezas):
    return sum(pz.area for pz in piezas)


def cerca(a, b, rel):
    return abs(a - b) <= abs(b) * rel


# --- medidas malas
for tipo, m, texto in [("conica", {"ds": 0, "di": 100, "alto": 100}, "diámetro cero"),
                       ("u", {"ancho": 600, "alto": 200, "largo": 1000}, "alto menor que el radio"),
                       ("codo", {"D": 200, "ang": 90, "R": 90, "N": 4, "recto": 0}, "radio de curva chico"),
                       ("boca", {"D": 300, "Lp": 800, "d": 280, "g": 90, "e": 30, "L": 400}, "ramal que se sale"),
                       ("boca", {"D": 300, "Lp": 800, "d": 150, "g": 90, "e": 0, "L": 100}, "ramal corto")]:
    revisar(f"{tipo}: rechaza {texto}", p3.problema(tipo, m) is not None)

# --- todas con sus medidas por defecto: se construyen, caras planas y bien orientadas
for tipo in p3.PIEZAS:
    m = p3.valores_por_defecto(tipo)
    partes = p3.construir(tipo, m)
    revisar(f"{tipo}: se construye ({len(partes)} parte(s), {sum(len(p.caras) for p in partes)} caras)",
            all(p.caras for p in partes))
    for p in partes:
        avisos = sin_avisos(desdoblar(p))
        revisar(f"{tipo} · {p.nombre}: desdobla sin avisos", not avisos, avisos[:3])

# --- tolva cónica Ø1200 / Ø600 / 900: la mitad desdoblada tiene los radios 1897,4 / 948,7
parte = p3.construir("conica", {"ds": 1200, "di": 600, "alto": 900, "tramos": 72})[0]
mitad = desdoblar(parte, list(range(36)))
revisar("cónica: media tolva = 1 pieza", len(mitad) == 1, len(mitad))
pts = [q for l in mitad[0].contornos for q in ed._puntos_arco(l)]
# los radios del abanico se miden desde el vértice: la distancia entre los arcos es la generatriz
g = math.hypot(900, 300)
ancho, alto = ed.medidas(mitad[0])
revisar("cónica: área plana = área de las caras", cerca(area_plana(mitad), area3d(parte, range(36)), 1e-6))
lateral = PI * (600 + 300) * g / 2
revisar("cónica: área de media tolva ≈ media área lateral del cono (facetas)", cerca(area_plana(mitad), lateral, 0.002),
        (area_plana(mitad), lateral))

# --- tolva en U 600 x 550 x 1200: cuerpo (2h + πR) x largo, tapas
cuerpo, tapas = p3.construir("u", {"ancho": 600, "alto": 550, "largo": 1200, "tramos": 36})
pc = desdoblar(cuerpo)
revisar("U: el cuerpo sale en 1 pieza", len(pc) == 1, len(pc))
arco = 2 * 300 * 36 * math.sin(PI / 2 / 36)          # medio círculo hecho de 36 cuerdas
w, h = ed.medidas(pc[0])
revisar("U: cuerpo de (2h + arco) x largo", cerca(max(w, h), 2 * 250 + arco, 1e-6) and cerca(min(w, h), 1200, 1e-6), (w, h))
pt = desdoblar(tapas)
revisar("U: 2 tapas", len(pt) == 2, len(pt))

# --- tolva piramidal: área plana = área 3D
parte = p3.construir("piramidal", {"A": 800, "B": 600, "a": 200, "b": 100, "alto": 500})[0]
pl = desdoblar(parte)
revisar("piramidal: área plana = área de las 4 caras", cerca(area_plana(pl), area3d(parte), 1e-6))

# --- cuadrado a redondo y reducción: área plana = área de las caras
for tipo in ("cuadrado", "reduccion"):
    parte = p3.construir(tipo, p3.valores_por_defecto(tipo))[0]
    pl = desdoblar(parte)
    revisar(f"{tipo}: área plana = área de las caras", cerca(area_plana(pl), area3d(parte), 1e-6))
# el redondo del cuadrado a redondo mide justo π·D (cuerdas abiertas como en el plano del 2D)
parte = p3.construir("cuadrado", {"A": 600, "B": 400, "D": 300, "alto": 400, "N": 6})[0]
abajo = [v for v in parte.vertices if abs(v[2]) < 1e-9]
abajo.sort(key=lambda v: math.atan2(v[1], v[0]))
per = sum(math.dist(abajo[i], abajo[(i + 1) % len(abajo)]) for i in range(len(abajo)))
revisar("cuadrado a redondo: el redondo mide π·D", cerca(per, PI * 300, 1e-9), (per, PI * 300))

# --- codo de 90° en 4 gajos Ø200: cada gajo desdoblado mide el perímetro alrededor
gajos = p3.construir("codo", {"D": 200, "ang": 90, "R": 300, "N": 4, "recto": 50, "tramos": 48})
revisar("codo: 4 gajos", len(gajos) == 4)
per = 2 * 100 * 48 * math.sin(PI / 48)
for k, gj in enumerate(gajos):
    pl = desdoblar(gj)
    w, h = ed.medidas(pl[0])
    revisar(f"codo: gajo {k + 1} mide {per:.1f} alrededor", len(pl) == 1 and (cerca(w, per, 1e-3) or cerca(h, per, 1e-3)), (w, h))
# los gajos se tocan: la boca de arriba de un gajo coincide con la de abajo del siguiente
def boca(parte, arriba):
    zs = {}
    for f in parte.caras:
        for i in f:
            zs[i] = parte.vertices[i]
    pts = list(zs.values())
    return pts
a, b = gajos[0], gajos[1]
comunes = set(map(lambda v: tuple(round(c, 4) for c in v), a.vertices)) & set(map(lambda v: tuple(round(c, 4) for c in v), b.vertices))
revisar("codo: el gajo 1 y el 2 comparten su unión (48 puntos)", len(comunes) == 48, len(comunes))

# --- boca de pescado: ramal Ø150 a 90° en principal Ø300
principal, ramal = p3.construir("boca", {"D": 300, "Lp": 800, "d": 150, "g": 90, "e": 0, "L": 400})
pr = desdoblar(ramal)
w, h = ed.medidas(pr[0])
per = 2 * 75 * 120 * math.sin(PI / 120)
revisar("boca: el ramal desdoblado mide π·d alrededor", len(pr) == 1 and (cerca(w, per, 1e-3) or cerca(h, per, 1e-3)), (w, h))
pp = desdoblar(principal)
huecos = sum(len(pz.contornos) - 1 for pz in pp)
revisar("boca: el principal sale con el agujero", len(pp) == 1 and huecos == 1, (len(pp), huecos))
# la boca del ramal cae sobre el principal: todos sus puntos del corte están a R del eje X
corte = [v for v in ramal.vertices if abs(math.hypot(v[1], v[2]) - 150) < 1e-6]
revisar("boca: el corte del ramal está sobre el principal", len(corte) >= 120, len(corte))

print()
print("TODO BIEN" if mal == 0 else f"{mal} PRUEBA(S) MAL")
sys.exit(1 if mal else 0)
