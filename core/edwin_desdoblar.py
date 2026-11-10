# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""
EDWIN CNC 3D - Desdoblar caras seleccionadas a plano.

Idea (igual que "Unwrap and Flatten Faces" de SketchUp, pero escrito por nosotros):
  1. Se toma la cara raíz y se acuesta en el plano (Z = 0).
  2. Cada cara vecina (que comparte una arista con una ya acostada) se "gira" sobre
     esa arista hasta quedar en el mismo plano.  Así hasta acostar todas.
  3. El contorno de todo lo acostado es la línea de CORTE.  Las aristas con doblez
     marcado (ángulo grande entre caras) van a la capa MARCADO.
  4. Avisa si hay caras torcidas (no planas) o si el plano se monta sobre sí mismo.

Sin dependencias para el cálculo (solo math).  Para guardar el DXF usa ezdxf.
Unidades: milímetros.  Medida interna, sin compensar espesor (decisión del usuario).
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

TOL = 1e-6          # tolerancia numérica general (mm)
TOL_PLANA = 0.05    # una cara se considera torcida si un vértice se sale más de esto del plano (mm)
TOL_ARCO = 0.02     # tolerancia para reconocer arcos en el contorno (mm)


# ---------------------------------------------------------------- vectores 3D
def _resta(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _punto(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _cruz(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def _largo(a): return math.sqrt(_punto(a, a))


def _unit(a):
    l = _largo(a)
    return (a[0] / l, a[1] / l, a[2] / l) if l > TOL else (0.0, 0.0, 0.0)


def normal_newell(pts):
    """Normal de un polígono 3D (robusta aunque tenga muchos lados)."""
    nx = ny = nz = 0.0
    for i in range(len(pts)):
        x1, y1, z1 = pts[i]
        x2, y2, z2 = pts[(i + 1) % len(pts)]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    return _unit((nx, ny, nz))


def area2d(p):
    return 0.5 * sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


# ---------------------------------------------------------------- datos
@dataclass
class Malla:
    """vertices: [(x, y, z)];  caras: [[i, j, k, ...]] en orden antihorario visto desde AFUERA.
    huecos: {cara: [[i, j, ...], ...]} huecos de cada cara (cualquier sentido)."""
    vertices: list
    caras: list
    huecos: dict = field(default_factory=dict)


@dataclass
class Doblez:
    a: tuple            # punto 2D
    b: tuple
    angulo: float       # grados que hay que doblar (0 = plano)
    hacia: str          # "arriba" / "abajo" visto desde la cara que queda hacia el usuario (afuera)


@dataclass
class Pieza:
    caras: list                         # índices de caras de la malla
    poligonos: dict                     # cara -> [(x, y)] ya acostada
    contornos: list = field(default_factory=list)   # [[(x, y, bulge), ...]] cerrados (bulge = arco al siguiente)
    dobleces: list = field(default_factory=list)    # [Doblez]
    avisos: list = field(default_factory=list)
    area: float = 0.0


# ---------------------------------------------------------------- núcleo
def _marco_local(pts3, n):
    """Coordenadas 2D de los puntos en el plano de la cara (conserva el giro visto desde afuera)."""
    o = pts3[0]
    u = None
    for p in pts3[1:]:
        d = _resta(p, o)
        if _largo(d) > TOL:
            u = _unit(d)
            break
    w = _cruz(n, u)
    return [(_punto(_resta(p, o), u), _punto(_resta(p, o), w)) for p in pts3]


def _encajar(loc, ia, ib, A, B):
    """Gira y mueve los puntos 'loc' para que loc[ia] caiga en A y loc[ib] en B."""
    fa, fb = loc[ia], loc[ib]
    ang = math.atan2(B[1] - A[1], B[0] - A[0]) - math.atan2(fb[1] - fa[1], fb[0] - fa[0])
    c, s = math.cos(ang), math.sin(ang)
    out = []
    for x, y in loc:
        dx, dy = x - fa[0], y - fa[1]
        out.append((A[0] + c * dx - s * dy, A[1] + s * dx + c * dy))
    return out


def _aristas(cara):
    return [(cara[i], cara[(i + 1) % len(cara)]) for i in range(len(cara))]


def _clave(a, b):
    return (a, b) if a < b else (b, a)


def desdoblar(malla: Malla, seleccion=None, angulo_marca: float = 15.0, separacion: float = 20.0,
              acomodar: bool = True):
    """
    Desdobla las caras 'seleccion' (índices; None = todas).
    angulo_marca: dobleces de este ángulo o más se dibujan en MARCADO (los menores se
                  consideran curvatura suave, p. ej. un cono que se rola).
    Devuelve una lista de Pieza (una por cada grupo de caras unidas).
    """
    V = malla.vertices
    sel = list(range(len(malla.caras))) if seleccion is None else list(dict.fromkeys(seleccion))
    sel = [f for f in sel if len(malla.caras[f]) >= 3]

    normales = {f: normal_newell([V[i] for i in malla.caras[f]]) for f in sel}

    # Cada cara: sus lazos (borde de afuera + huecos), con los huecos en sentido horario.
    lazos_de = {}   # cara -> [[vértices], ...]  (el primero es el borde)
    todos = {}      # cara -> todos los vértices seguidos (borde + huecos)
    pos = {}        # cara -> {vértice: posición en 'todos'}
    sigue = {}      # cara -> {vértice: siguiente vértice en su lazo}
    for f in sel:
        borde = list(malla.caras[f])
        huecos = []
        for h in malla.huecos.get(f, []):
            h = list(h)
            if len(h) < 3:
                continue
            loc = _marco_local([V[i] for i in borde] + [V[i] for i in h], normales[f])[len(borde):]
            if area2d(loc) > 0:
                h.reverse()
            huecos.append(h)
        lazos_de[f] = [borde] + huecos
        todos[f] = [v for l in lazos_de[f] for v in l]
        pos[f] = {v: k for k, v in enumerate(todos[f])}
        sigue[f] = {l[i]: l[(i + 1) % len(l)] for l in lazos_de[f] for i in range(len(l))}

    def aristas_de(f):
        return [e for l in lazos_de[f] for e in _aristas(l)]

    def plano_de(f):
        return _marco_local([V[i] for i in todos[f]], normales[f])

    # arista -> caras seleccionadas que la usan
    usa = defaultdict(list)
    for f in sel:
        for a, b in aristas_de(f):
            usa[_clave(a, b)].append(f)

    piezas = []
    pendientes = set(sel)
    for raiz in sel:
        if raiz not in pendientes:
            continue
        # ---- recorrido en anchura: árbol de bisagras
        poligonos = {}
        bisagras = {}             # arista (clave) -> (cara, vecina) que quedan unidas; el resto se corta
        orden = []
        avisos = []
        p2 = {raiz: plano_de(raiz)}     # cara -> puntos 2D de 'todos[cara]'
        espejo = {raiz: False}         # cara reflejada (estaba volteada)
        pendientes.discard(raiz)
        cola = deque([raiz])
        while cola:
            f = cola.popleft()
            orden.append(f)
            for a, b in aristas_de(f):
                for g in usa[_clave(a, b)]:
                    if g == f or g not in pendientes:
                        continue
                    if len(usa[_clave(a, b)]) > 2:
                        avisos.append(f"La arista {a}-{b} la comparten más de 2 caras; se unió solo una.")
                    loc = plano_de(g)
                    ia, ib = pos[g][a], pos[g][b]
                    # misma arista en el mismo sentido en las dos caras = una de las dos está volteada
                    voltear = (sigue[g].get(a) == b) != espejo[f]
                    if voltear:
                        loc = [(x, -y) for x, y in loc]
                        avisos.append(f"La cara {g} estaba volteada (normal hacia adentro); se corrigió.")
                    espejo[g] = voltear
                    p2[g] = _encajar(loc, ia, ib, p2[f][pos[f][a]], p2[f][pos[f][b]])
                    bisagras[_clave(a, b)] = (f, g)
                    pendientes.discard(g)
                    cola.append(g)

        for f in orden:
            poligonos[f] = p2[f][:len(lazos_de[f][0])]
        pieza = Pieza(caras=orden, poligonos=poligonos, avisos=avisos)

        # ---- caras torcidas
        for f in orden:
            pts = [V[i] for i in todos[f]]
            if len(pts) > 3:
                c = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
                dev = max(abs(_punto(_resta(p, c), normales[f])) for p in pts)
                if dev > TOL_PLANA:
                    pieza.avisos.append(f"La cara {f} está torcida ({dev:.2f} mm fuera de plano); "
                                        f"el plano de esa cara sale aproximado.")

        # ---- dobleces
        esquinas = set()   # puntos 2D (redondeados) donde termina un doblez marcado
        for k, (f, g) in bisagras.items():
            a, b = k
            # sentido a->b como queda la cara f ya corregida
            if (sigue[f].get(a) == b) == espejo[f]:
                a, b = b, a
            n1 = normales[f] if not espejo[f] else tuple(-x for x in normales[f])
            n2 = normales[g] if not espejo[g] else tuple(-x for x in normales[g])
            ang = math.degrees(math.acos(max(-1.0, min(1.0, _punto(n1, n2)))))
            s = _punto(_cruz(n1, n2), _unit(_resta(V[b], V[a])))
            # El plano se ve por la cara de AFUERA: una esquina hacia afuera (como las de una
            # caja) se dobla alejándose del que mira = "hacia abajo".
            hacia = "abajo" if s >= 0 else "arriba"
            if ang >= angulo_marca:
                A = p2[f][pos[f][a]]
                B = p2[f][pos[f][b]]
                pieza.dobleces.append(Doblez(A, B, ang, hacia))
                esquinas.add(_r(A)); esquinas.add(_r(B))

        # ---- contorno: aristas que NO son bisagra
        segs = []
        for f in orden:
            pts = p2[f]
            invertir = area2d(poligonos[f]) < 0      # asegurar borde antihorario, huecos horario
            for lazo in lazos_de[f]:
                sec = list(reversed(lazo)) if invertir else lazo
                for a, b in _aristas(sec):
                    if _clave(a, b) in bisagras:
                        continue
                    segs.append((pts[pos[f][a]], pts[pos[f][b]]))
        lazos = _encadenar(segs, pieza.avisos)
        pieza.area = 0.0
        for f in orden:
            pts = p2[f]
            pieza.area += abs(area2d(poligonos[f]))
            for h in lazos_de[f][1:]:
                pieza.area -= abs(area2d([pts[pos[f][v]] for v in h]))

        # ---- solapes
        if _se_monta(lazos):
            pieza.avisos.append("¡OJO! El plano se monta sobre sí mismo. Seleccione menos caras "
                                "(parta la pieza en dos) para poder cortarla de una lámina.")

        pieza.contornos = [_simplificar(l, esquinas) for l in lazos]
        piezas.append(pieza)

    if acomodar:
        _acomodar(piezas, separacion)
    return piezas


def _r(p, d=4):
    return (round(p[0], d), round(p[1], d))


def _encadenar(segs, avisos):
    """Une los segmentos sueltos en lazos cerrados."""
    salen = defaultdict(list)
    for s in segs:
        salen[_r(s[0])].append(s)
    usados = set()
    lazos = []
    for s0 in segs:
        if id(s0) in usados:
            continue
        lazo = [s0[0]]
        s = s0
        usados.add(id(s))
        while True:
            fin = _r(s[1])
            if fin == _r(s0[0]):
                break
            sig = [t for t in salen.get(fin, []) if id(t) not in usados]
            if not sig:
                avisos.append("Un contorno quedó abierto (revise la malla).")
                break
            s = sig[0]
            usados.add(id(s))
            lazo.append(s[0])
        lazos.append(lazo)
    # el lazo de afuera primero
    lazos.sort(key=lambda l: -abs(area2d(l)))
    return lazos


def _cruzan(p1, p2, q1, q2):
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = o(q1, q2, p1), o(q1, q2, p2)
    d3, d4 = o(p1, p2, q1), o(p1, p2, q2)
    eps = 1e-7
    return ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and \
           ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps))


def _se_monta(lazos):
    segs = []
    for li, l in enumerate(lazos):
        for i in range(len(l)):
            segs.append((l[i], l[(i + 1) % len(l)]))
    cajas = [(min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])) for a, b in segs]
    orden = sorted(range(len(segs)), key=lambda i: cajas[i][0])
    activos = []
    for i in orden:
        activos = [j for j in activos if cajas[j][1] >= cajas[i][0] - 1e-9]
        for j in activos:
            if cajas[j][3] < cajas[i][2] or cajas[i][3] < cajas[j][2]:
                continue
            if _cruzan(*segs[i], *segs[j]):
                return True
        activos.append(i)
    return False


def _circulo(a, b, c):
    ax, ay = a; bx, by = b; cx, cy = c
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
    return (ux, uy), math.hypot(ax - ux, ay - uy)


def _giro(a, b, c):
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def _simplificar(lazo, esquinas):
    """Quita puntos sobre líneas rectas y convierte tramos de muchos puntos sobre un círculo
    en un solo arco (bulge).  No pasa arcos por esquinas de doblez."""
    # 1) quitar puntos colineales
    pts = list(lazo)
    cambio = True
    while cambio and len(pts) > 3:
        cambio = False
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            L = math.hypot(c[0] - a[0], c[1] - a[1])
            if L > TOL and abs(_giro(a, b, c)) / L < 1e-4:
                pts.pop(i)
                cambio = True
                break
    n = len(pts)
    # 2) empezar en una esquina (si hay) para que los arcos no queden partidos
    ini = 0
    for i in range(n):
        if _r(pts[i]) in esquinas or _es_quiebre(pts, i):
            ini = i
            break
    pts = pts[ini:] + pts[:ini]
    out = []
    i = 0
    while i < n:
        mejor = None
        # intentar un arco desde i con al menos 4 tramos
        j = i + 4
        while j <= n:
            ok = _arco_valido(pts, i, j, esquinas)
            if not ok:
                break
            mejor = (j, ok)
            j += 1
        if mejor:
            j, (centro, radio, angulo) = mejor
            out.append((pts[i][0], pts[i][1], math.tan(angulo / 4)))
            i = j
        else:
            out.append((pts[i][0], pts[i][1], 0.0))
            i += 1
    return out


def _es_quiebre(pts, i):
    a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
    v1 = (b[0] - a[0], b[1] - a[1]); v2 = (c[0] - b[0], c[1] - b[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < TOL or l2 < TOL:
        return False
    cosang = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)
    return cosang < math.cos(math.radians(20))


def _arco_valido(pts, i, j, esquinas):
    """¿Los puntos pts[i..j] (j puede ser n = vuelve al inicio) están sobre un mismo arco?"""
    n = len(pts)
    tramo = [pts[k % n] for k in range(i, j + 1)]
    for p in tramo[1:-1]:
        if _r(p) in esquinas:
            return None
    m = len(tramo) // 2
    c = _circulo(tramo[0], tramo[m], tramo[-1])
    if not c:
        return None
    centro, radio = c
    if radio > 1e5:
        return None
    signo = None
    for k in range(len(tramo)):
        if abs(math.hypot(tramo[k][0] - centro[0], tramo[k][1] - centro[1]) - radio) > TOL_ARCO:
            return None
        if 0 < k < len(tramo) - 1:
            g = _giro(tramo[k - 1], tramo[k], tramo[k + 1])
            s = g > 0
            if signo is None:
                signo = s
            elif s != signo:
                return None
            if _es_quiebre(tramo, k):
                return None
    # ángulo recorrido con signo
    tot = 0.0
    for k in range(len(tramo) - 1):
        a1 = math.atan2(tramo[k][1] - centro[1], tramo[k][0] - centro[0])
        a2 = math.atan2(tramo[k + 1][1] - centro[1], tramo[k + 1][0] - centro[0])
        d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        tot += d
    if abs(tot) >= math.radians(359):   # un arco no puede ser un círculo completo
        return None
    return centro, radio, tot


# ---------------------------------------------------------------- acomodar piezas
def _transformar(pieza, fn):
    pieza.poligonos = {f: [fn(p) for p in pts] for f, pts in pieza.poligonos.items()}
    pieza.contornos = [[(*fn((x, y)), bl) for x, y, bl in l] for l in pieza.contornos]
    pieza.dobleces = [Doblez(fn(d.a), fn(d.b), d.angulo, d.hacia) for d in pieza.dobleces]


def _puntos_arco(l):
    """Puntos del contorno incluyendo puntos medios de arcos (para medir la caja)."""
    out = []
    for k, (x, y, bl) in enumerate(l):
        out.append((x, y))
        if bl:
            x2, y2, _ = l[(k + 1) % len(l)]
            for t in (0.25, 0.5, 0.75):
                out.append(_punto_en_arco((x, y), (x2, y2), bl, t))
    return out


def _punto_en_arco(a, b, bulge, t):
    ang = 4 * math.atan(bulge)
    cx = (a[0] + b[0]) / 2; cy = (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    cuerda = math.hypot(dx, dy)
    r = cuerda / (2 * math.sin(ang / 2))
    h = r * math.cos(ang / 2)
    # centro a la izquierda si bulge > 0
    ox, oy = cx - dy / cuerda * h, cy + dx / cuerda * h
    a0 = math.atan2(a[1] - oy, a[0] - ox)
    ra = abs(r)
    return (ox + ra * math.cos(a0 + ang * t), oy + ra * math.sin(a0 + ang * t))


def _acomodar(piezas, separacion):
    """Gira cada pieza para que ocupe la menor lámina posible y las pone una al lado de la otra."""
    x_sig = 0.0
    for pz in piezas:
        pts = [p for l in pz.contornos for p in _puntos_arco(l)]
        mejor = None
        for k in range(len(pts)):
            a, b = pts[k], pts[(k + 1) % len(pts)]
            ang = -math.atan2(b[1] - a[1], b[0] - a[0])
            c, s = math.cos(ang), math.sin(ang)
            xs = [c * x - s * y for x, y in pts]; ys = [s * x + c * y for x, y in pts]
            area = (max(xs) - min(xs)) * (max(ys) - min(ys))
            ancho = max(xs) - min(xs); alto = max(ys) - min(ys)
            if alto > ancho:   # dejarla acostada (más ancha que alta)
                ang += math.pi / 2
            if mejor is None or area < mejor[0] - 1e-6:
                mejor = (area, ang)
        ang = mejor[1] if mejor else 0.0
        c, s = math.cos(ang), math.sin(ang)
        _transformar(pz, lambda p, c=c, s=s: (c * p[0] - s * p[1], s * p[0] + c * p[1]))
        pts = [p for l in pz.contornos for p in _puntos_arco(l)]
        mx, my = min(p[0] for p in pts), min(p[1] for p in pts)
        dx = x_sig - mx
        _transformar(pz, lambda p, dx=dx, my=my: (p[0] + dx, p[1] - my))
        x_sig = max(p[0] for l in pz.contornos for p in _puntos_arco(l)) + separacion


def medidas(pieza):
    pts = [p for l in pieza.contornos for p in _puntos_arco(l)]
    return (max(p[0] for p in pts) - min(p[0] for p in pts), max(p[1] for p in pts) - min(p[1] for p in pts))


# ---------------------------------------------------------------- DXF
def guardar_dxf(piezas, ruta, nombre="PIEZA"):
    """DXF R2000 en mm con capas CORTE / MARCADO / REFERENCIA (las mismas del CAD-CAM 2D)."""
    import ezdxf
    doc = ezdxf.new("R2000", setup=True)
    doc.header["$INSUNITS"] = 4      # milímetros
    doc.header["$MEASUREMENT"] = 1
    doc.layers.add("CORTE", color=7)
    doc.layers.add("MARCADO", color=3, linetype="DASHED")
    doc.layers.add("REFERENCIA", color=8)
    msp = doc.modelspace()
    for n, pz in enumerate(piezas, 1):
        for l in pz.contornos:
            msp.add_lwpolyline([(x, y, 0, 0, bl) for x, y, bl in l], format="xyseb", close=True,
                               dxfattribs={"layer": "CORTE"})
        for d in pz.dobleces:
            msp.add_line(d.a, d.b, dxfattribs={"layer": "MARCADO"})
            mx, my = (d.a[0] + d.b[0]) / 2, (d.a[1] + d.b[1]) / 2
            ang = math.degrees(math.atan2(d.b[1] - d.a[1], d.b[0] - d.a[0]))
            if ang > 90 or ang < -90:
                ang += 180
            msp.add_text(f"Doblar {d.angulo:.1f}° hacia {d.hacia}", height=8,
                         dxfattribs={"layer": "REFERENCIA", "rotation": ang}).set_placement((mx, my))
        ancho, alto = medidas(pz)
        pts = [p for l in pz.contornos for p in _puntos_arco(l)]
        x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
        etiqueta = nombre if len(piezas) == 1 else f"{nombre} {n}"
        msp.add_text(f"{etiqueta} - {ancho:.1f} x {alto:.1f} mm", height=10,
                     dxfattribs={"layer": "REFERENCIA"}).set_placement((x0, y0 - 18))
        if pz.dobleces:
            msp.add_text("Plano visto por la cara de AFUERA", height=7,
                         dxfattribs={"layer": "REFERENCIA"}).set_placement((x0, y0 - 32))
    doc.saveas(ruta)
    return ruta
