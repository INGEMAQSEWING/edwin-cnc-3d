# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""Piezas de lámina por medidas (EDWIN CNC 3D): tolvas, transiciones y tubos.

Cada pieza se arma como la LÁMINA (superficie sin espesor) con caras planas, en
milímetros, con las caras en orden antihorario vistas desde AFUERA, de modo que
«Desdoblar caras» dé el mismo plano que las calculadoras de taller de la web y
que «Piezas por medidas» de EDWIN CNC CAD-CAM 2D (piezas.h).

Sin Qt: se prueba solo (edwin/pruebas/prueba_piezas3d.py). El plugin
(plugins/edwin_cnc.py) convierte cada Parte en un grupo del modelo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

PI = math.pi
GRAD = PI / 180


@dataclass
class Parte:
    """Una parte de la pieza (un grupo en el modelo)."""
    nombre: str
    vertices: list = field(default_factory=list)      # [(x, y, z)] mm
    caras: list = field(default_factory=list)         # [[i, j, k, ...]] antihorario visto desde afuera
    huecos: dict = field(default_factory=dict)        # {cara: [[i, ...]]}
    suaves: list = field(default_factory=list)        # [(i, j)] aristas suaves (un clic toma toda la lámina)
    costuras: set = field(default_factory=set)        # aristas que deben quedar marcadas (no suaves)
    _indice: dict = field(default_factory=dict, repr=False)

    def v(self, p):
        clave = (round(p[0], 6), round(p[1], 6), round(p[2], 6))
        if clave not in self._indice:
            self._indice[clave] = len(self.vertices)
            self.vertices.append((float(p[0]), float(p[1]), float(p[2])))
        return self._indice[clave]

    def cara(self, pts, adentro, huecos=None):
        """Agrega la cara de puntos `pts`; `adentro` es un punto del lado de adentro de la lámina
        (para dejar la normal hacia afuera)."""
        idx = [self.v(p) for p in pts]
        limpio = []
        for i in idx:                       # sin puntos repetidos seguidos
            if not limpio or limpio[-1] != i:
                limpio.append(i)
        if len(limpio) > 1 and limpio[0] == limpio[-1]:
            limpio.pop()
        if len(set(limpio)) < 3:
            return None
        n = _normal([self.vertices[i] for i in limpio])
        c = _centro([self.vertices[i] for i in limpio])
        if _punto(n, _resta(c, adentro)) < 0:
            limpio.reverse()
        k = len(self.caras)
        self.caras.append(limpio)
        if huecos:
            self.huecos[k] = [[self.v(p) for p in h] for h in huecos]
        return k


def _resta(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _punto(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _centro(pts): return tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))


def _normal(pts):
    nx = ny = nz = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return (nx, ny, nz)


def _marcar_suaves(parte: Parte, angulo_max=20.0):
    """Aristas entre dos caras casi en el mismo plano (menos de `angulo_max`): suaves."""
    aristas = {}
    for k, f in enumerate(parte.caras):
        for i in range(len(f)):
            a, b = f[i], f[(i + 1) % len(f)]
            aristas.setdefault((min(a, b), max(a, b)), []).append(k)
    normales = []
    for f in parte.caras:
        n = _normal([parte.vertices[i] for i in f])
        l = math.sqrt(_punto(n, n)) or 1.0
        normales.append((n[0] / l, n[1] / l, n[2] / l))
    for e, fs in aristas.items():
        if len(fs) != 2 or e in parte.costuras:
            continue
        c = max(-1.0, min(1.0, _punto(normales[fs[0]], normales[fs[1]])))
        if math.degrees(math.acos(c)) < angulo_max:
            parte.suaves.append(e)


# ---------------------------------------------------------------- catálogo
# (clave, etiqueta, valor por defecto, mínimo, máximo, decimales, sufijo)
PIEZAS = {
    "conica": ("Tolva cónica", [
        ("ds", "Diámetro de arriba (boca)", 1200, 1, 20000, 1, " mm"),
        ("di", "Diámetro de abajo (salida)", 600, 0, 20000, 1, " mm"),
        ("alto", "Alto", 900, 1, 20000, 1, " mm"),
        ("tramos", "Tramos alrededor", 72, 12, 720, 0, ""),
    ]),
    "u": ("Tolva en U (mezcladora)", [
        ("ancho", "Ancho (diámetro del fondo)", 600, 1, 20000, 1, " mm"),
        ("alto", "Alto total", 550, 1, 20000, 1, " mm"),
        ("largo", "Largo", 1200, 1, 50000, 1, " mm"),
        ("tramos", "Tramos del fondo redondo", 36, 6, 360, 0, ""),
    ]),
    "piramidal": ("Tolva piramidal", [
        ("A", "Boca: largo", 800, 1, 20000, 1, " mm"),
        ("B", "Boca: ancho", 600, 1, 20000, 1, " mm"),
        ("a", "Salida: largo", 200, 0, 20000, 1, " mm"),
        ("b", "Salida: ancho", 100, 0, 20000, 1, " mm"),
        ("alto", "Alto", 500, 1, 20000, 1, " mm"),
    ]),
    "cuadrado": ("Cuadrado a redondo", [
        ("A", "Lado largo del cuadrado (arriba)", 600, 1, 20000, 1, " mm"),
        ("B", "Lado corto del cuadrado (arriba)", 400, 1, 20000, 1, " mm"),
        ("D", "Diámetro del redondo (abajo)", 300, 1, 20000, 1, " mm"),
        ("alto", "Alto", 400, 1, 20000, 1, " mm"),
        ("N", "Divisiones por cuarto de redondo", 6, 1, 60, 0, ""),
    ]),
    "reduccion": ("Reducción excéntrica", [
        ("D1", "Diámetro de arriba", 600, 1, 20000, 1, " mm"),
        ("D2", "Diámetro de abajo", 300, 1, 20000, 1, " mm"),
        ("alto", "Alto", 500, 1, 20000, 1, " mm"),
        ("e", "Corrido del centro de abajo", 150, 0, 20000, 1, " mm"),
        ("N", "Divisiones por cuarto de vuelta", 12, 1, 90, 0, ""),
    ]),
    "codo": ("Codo de gajos", [
        ("D", "Diámetro del tubo", 200, 1, 20000, 1, " mm"),
        ("ang", "Ángulo del codo", 90, 1, 180, 1, " °"),
        ("R", "Radio de la curva (al eje del tubo)", 300, 1, 50000, 1, " mm"),
        ("N", "Número de piezas (gajos)", 4, 2, 30, 0, ""),
        ("recto", "Tramo recto en cada punta", 50, 0, 20000, 1, " mm"),
        ("tramos", "Tramos alrededor", 48, 12, 360, 0, ""),
    ]),
    "boca": ("Boca de pescado (tubo con tubo)", [
        ("D", "Diámetro del tubo principal", 300, 1, 20000, 1, " mm"),
        ("Lp", "Largo del tubo principal", 800, 1, 50000, 1, " mm"),
        ("d", "Diámetro del ramal", 150, 1, 20000, 1, " mm"),
        ("g", "Ángulo del ramal", 90, 15, 90, 1, " °"),
        ("e", "Corrido del ramal (0 = centrado)", 0, -20000, 20000, 1, " mm"),
        ("L", "Largo del ramal (desde el eje del principal)", 400, 1, 50000, 1, " mm"),
    ]),
}


def valores_por_defecto(tipo):
    return {c[0]: c[2] for c in PIEZAS[tipo][1]}


def problema(tipo, m):
    """Texto con el problema de las medidas, o None si se puede construir."""
    try:
        construir(tipo, m)
    except ValueError as exc:
        return str(exc)
    return None


def nombre(tipo, m):
    f = lambda x: f"{x:g}"   # noqa: E731
    if tipo == "conica":
        return f"Tolva cónica Ø{f(m['ds'])} / Ø{f(m['di'])} alto {f(m['alto'])}"
    if tipo == "u":
        return f"Tolva en U {f(m['ancho'])} x {f(m['alto'])} x {f(m['largo'])}"
    if tipo == "piramidal":
        return f"Tolva piramidal {f(m['A'])}x{f(m['B'])} a {f(m['a'])}x{f(m['b'])} alto {f(m['alto'])}"
    if tipo == "cuadrado":
        return f"Cuadrado a redondo {f(m['A'])}x{f(m['B'])} a Ø{f(m['D'])} alto {f(m['alto'])}"
    if tipo == "reduccion":
        return f"Reducción Ø{f(m['D1'])} a Ø{f(m['D2'])} alto {f(m['alto'])} corrido {f(m['e'])}"
    if tipo == "codo":
        return f"Codo Ø{f(m['D'])} {f(m['ang'])}° radio {f(m['R'])}"
    if tipo == "boca":
        return f"Boca de pescado Ø{f(m['D'])} con ramal Ø{f(m['d'])} a {f(m['g'])}°"
    return PIEZAS[tipo][0]


def construir(tipo, m):
    """Lista de Partes (en mm). Lanza ValueError con un texto claro si las medidas no sirven."""
    fn = {"conica": _conica, "u": _u, "piramidal": _piramidal, "cuadrado": _cuadrado,
          "reduccion": _reduccion, "codo": _codo, "boca": _boca}[tipo]
    partes = fn(m)
    for p in partes:
        _marcar_suaves(p)
    return partes


# ---------------------------------------------------------------- 1) tolva cónica
def _conica(m):
    ds, di, H, n = float(m["ds"]), float(m["di"]), float(m["alto"]), int(m.get("tramos", 72))
    if ds <= 0 or di < 0 or H <= 0:
        raise ValueError("Revise las medidas: el diámetro de arriba y el alto deben ser mayores que cero.")
    if n < 12:
        raise ValueError("Use por lo menos 12 tramos alrededor.")
    p = Parte(nombre("conica", m))
    R1, R2 = ds / 2, di / 2
    for i in range(n):
        a0, a1 = 2 * PI * i / n, 2 * PI * (i + 1) / n
        arriba = [(R1 * math.cos(a), R1 * math.sin(a), H) for a in (a0, a1)]
        if R2 > 1e-9:
            abajo = [(R2 * math.cos(a), R2 * math.sin(a), 0.0) for a in (a0, a1)]
            pts = [abajo[0], abajo[1], arriba[1], arriba[0]]
        else:
            pts = [(0.0, 0.0, 0.0), arriba[1], arriba[0]]
        p.cara(pts, (0.0, 0.0, H / 2))
    return [p]


# ---------------------------------------------------------------- 2) tolva en U
def _u(m):
    ancho, alto, L, n = float(m["ancho"]), float(m["alto"]), float(m["largo"]), int(m.get("tramos", 36))
    R = ancho / 2
    h = alto - R
    if ancho <= 0 or L <= 0:
        raise ValueError("El ancho y el largo deben ser mayores que cero.")
    if h < 0:
        raise ValueError("El alto total debe ser por lo menos la mitad del ancho (el fondo es medio círculo).")
    if n < 6:
        raise ValueError("Use por lo menos 6 tramos en el fondo redondo.")
    # perfil (y, z): pared izquierda, medio círculo por abajo, pared derecha; centro del arco en z = R
    perfil = []
    if h > 1e-9:
        perfil.append((-R, R + h))
    for k in range(n + 1):
        a = PI + PI * k / n
        perfil.append((R * math.cos(a), R + R * math.sin(a)))
    if h > 1e-9:
        perfil.append((R, R + h))
    cuerpo = Parte(nombre("u", m) + " · cuerpo")
    for i in range(len(perfil) - 1):
        (y0, z0), (y1, z1) = perfil[i], perfil[i + 1]
        pts = [(0.0, y0, z0), (0.0, y1, z1), (L, y1, z1), (L, y0, z0)]
        cuerpo.cara(pts, (L / 2, 0.0, R))
    tapas = Parte(nombre("u", m) + " · tapas")
    for x, dentro in ((0.0, L / 2), (L, L / 2)):
        tapas.cara([(x, y, z) for y, z in perfil], (dentro, 0.0, R + h / 2))
    return [cuerpo, tapas]


# ---------------------------------------------------------------- 3) tolva piramidal
_SG = [(-1, -1), (1, -1), (1, 1), (-1, 1)]


def _piramidal(m):
    A, B, a, b, H = (float(m[k]) for k in ("A", "B", "a", "b", "alto"))
    if A <= 0 or B <= 0 or a < 0 or b < 0 or H <= 0:
        raise ValueError("Revise las medidas: la boca y el alto deben ser mayores que cero.")
    T = [(sx * A / 2, sy * B / 2, H) for sx, sy in _SG]
    Bt = [(sx * a / 2, sy * b / 2, 0.0) for sx, sy in _SG]
    p = Parte(nombre("piramidal", m))
    for i in range(4):
        j = (i + 1) % 4
        p.cara([Bt[i], Bt[j], T[j], T[i]], (0.0, 0.0, H / 2))
    return [p]


# ---------------------------------------------------------------- 4) cuadrado a redondo
def _cuadrado(m):
    A, B, D, H, N = float(m["A"]), float(m["B"]), float(m["D"]), float(m["alto"]), int(m["N"])
    if A <= 0 or B <= 0 or D <= 0 or H <= 0 or N < 1:
        raise ValueError("Revise las medidas: lados, diámetro y alto mayores que cero.")
    ANG = [270 * GRAD, 0.0, 90 * GRAD, 180 * GRAD]
    C = [(sx * A / 2, sy * B / 2, H) for sx, sy in _SG]
    M = [((C[i][0] + C[(i + 1) % 4][0]) / 2, (C[i][1] + C[(i + 1) % 4][1]) / 2, H) for i in range(4)]
    n = 4 * N
    Rp = D / 2 * (PI / n) / math.sin(PI / n)      # cuerdas que suman justo π·D (igual que el plano)

    def P(a):
        return (Rp * math.cos(a), Rp * math.sin(a), 0.0)

    p = Parte(nombre("cuadrado", m))

    def adentro(pts):
        return (0.0, 0.0, sum(q[2] for q in pts) / len(pts))

    for lado in range(4):
        esq0, esq1 = lado, (lado + 1) % 4
        q = P(ANG[lado])
        # cara plana del lado, partida en la mitad del lado (ahí va la costura si se corta en partes)
        for t in ([C[esq0], M[lado], q], [M[lado], C[esq1], q]):
            p.cara(t, adentro(t))
        p.costuras.add(tuple(sorted((p.v(M[lado]), p.v(q)))))
        # abanico de la esquina esq1 hacia el cuarto de redondo
        for t in range(N):
            a0, a1 = ANG[lado] + t * PI / 2 / N, ANG[lado] + (t + 1) * PI / 2 / N
            tri = [C[esq1], P(a0), P(a1)]
            p.cara(tri, adentro(tri))
    return [p]


# ---------------------------------------------------------------- 5) reducción excéntrica
def _reduccion(m):
    D1, D2, H, e, N = float(m["D1"]), float(m["D2"]), float(m["alto"]), float(m["e"]), int(m["N"])
    if D1 <= 0 or D2 <= 0 or H <= 0 or N < 1:
        raise ValueError("Revise las medidas: diámetros y alto mayores que cero.")
    n = 4 * N
    k = (PI / n) / math.sin(PI / n)
    R1, R2 = D1 / 2, D2 / 2

    def T(i):
        a = 2 * PI * i / n
        return (R1 * k * math.cos(a), R1 * k * math.sin(a), H)

    def Bq(i):
        a = 2 * PI * i / n
        return (e + R2 * k * math.cos(a), R2 * k * math.sin(a), 0.0)

    p = Parte(nombre("reduccion", m))
    for i in range(n):
        for tri in ([T(i), Bq(i), T(i + 1)], [T(i + 1), Bq(i), Bq(i + 1)]):
            zc = sum(q[2] for q in tri) / 3
            f = zc / H                                    # punto del eje a esa altura
            p.cara(tri, (e * (1 - f), 0.0, zc))
    return [p]


# ---------------------------------------------------------------- 6) codo de gajos
def _codo(m):
    D, ang, Rc, N, recto = float(m["D"]), float(m["ang"]), float(m["R"]), int(m["N"]), float(m["recto"])
    n = int(m.get("tramos", 48))
    r = D / 2
    if D <= 0 or not (0 < ang <= 180) or not (2 <= N <= 30) or recto < 0:
        raise ValueError("Revise: diámetro mayor que cero, ángulo de 1° a 180° y de 2 a 30 piezas.")
    if Rc <= r:
        raise ValueError("El radio de la curva debe ser mayor que medio diámetro del tubo.")
    b = ang * GRAD / (N - 1) / 2
    partes = []
    for k in range(N):
        ini, fin = k == 0, k == N - 1
        bAb, bAr = (0.0 if ini else b), (0.0 if fin else b)
        rAb, rAr = (recto if ini else 0.0), (recto if fin else 0.0)
        giro = 2 * b * k
        cg, sg = math.cos(giro), math.sin(giro)

        def g(x, y, z, cg=cg, sg=sg):
            # gira alrededor del eje Y (el eje de la curva): x→z
            return (x * cg - z * sg, y, x * sg + z * cg)

        p = Parte(f"Codo · gajo {k + 1} de {N}")
        # Costuras alternadas como en el plano (garganta, dorso, garganta…): «Desdoblar caras»
        # empieza por la primera cara y corta del lado contrario.
        inicio = n // 2 if k % 2 == 1 else 0
        for i in [(inicio + q) % n for q in range(n)]:
            esquinas = []
            for fi in (2 * PI * i / n, 2 * PI * (i + 1) / n):
                x, y = Rc + r * math.cos(fi), r * math.sin(fi)
                esquinas.append(((x, y, -(rAb + x * math.tan(bAb))), (x, y, rAr + x * math.tan(bAr))))
            (b0, t0), (b1, t1) = esquinas
            zc = (b0[2] + t0[2]) / 2
            p.cara([g(*b0), g(*b1), g(*t1), g(*t0)], g(Rc, 0.0, zc))
        partes.append(p)
    return partes


# ---------------------------------------------------------------- 7) boca de pescado
def _corte_boca(D, d, gG, e, pasos=120):
    R, r, g = D / 2, d / 2, gG * GRAD
    pts = []
    for i in range(pasos):
        fi = 2 * PI * i / pasos
        y = r * math.sin(fi) + e
        z = math.sqrt(max(0.0, R * R - y * y))
        t = (z + r * math.cos(fi) * math.cos(g)) / math.sin(g)
        X = t * math.cos(g) + r * math.cos(fi) * math.sin(g)
        pts.append((fi, t, X, y, z))
    return pts


def _boca(m):
    D, Lp, d, gG, e, L = (float(m[k]) for k in ("D", "Lp", "d", "g", "e", "L"))
    R, r, g = D / 2, d / 2, gG * GRAD
    if D <= 0 or d <= 0 or not (15 <= gG <= 90):
        raise ValueError("Revise: diámetros mayores que cero y ángulo del ramal de 15° a 90°.")
    if r + abs(e) > R + 1e-6:
        raise ValueError("El ramal corrido se sale del principal: el radio del ramal más el corrido "
                         f"no puede pasar de {R:g} mm.")
    pasos = 120
    corte = _corte_boca(D, d, gG, e, pasos)
    tmax = max(q[1] for q in corte)
    if L <= tmax + 1:
        raise ValueError(f"El ramal debe medir más de {tmax:.0f} mm desde el eje del principal.")
    xs = [q[2] for q in corte]
    x0, x1 = min(xs), max(xs)
    if Lp < (x1 - x0) + 20:
        raise ValueError(f"El tubo principal debe medir más que el agujero ({x1 - x0:.0f} mm a lo largo).")
    eje = (math.cos(g), 0.0, math.sin(g))
    u = (math.sin(g), 0.0, -math.cos(g))

    def en_ramal(t, fi):
        return (t * eje[0] + r * math.cos(fi) * u[0], r * math.sin(fi) + e, t * eje[2] + r * math.cos(fi) * u[2])

    ramal = Parte(nombre("boca", m) + " · ramal")
    for i in [(pasos // 2 + q) % pasos for q in range(pasos)]:     # costura en el mismo sitio que el plano 2D
        j = (i + 1) % pasos
        fi0, fi1 = corte[i][0], (corte[j][0] if j else 2 * PI)
        a0 = (corte[i][2], corte[i][3], corte[i][4])     # punto del corte (X, y, z)
        a1 = (corte[j][2], corte[j][3], corte[j][4])
        p0, p1 = en_ramal(L, fi0), en_ramal(L, fi1)
        tc = (corte[i][1] + L) / 2
        centro = (tc * eje[0], e, tc * eje[2])
        ramal.cara([a0, a1, p1, p0], centro)

    # principal: cilindro de radio R a lo largo de X, con el agujero exacto del ramal.
    # Las tiras van entre ángulos; dentro del agujero se usan los ángulos de los puntos del corte.
    xm = (x0 + x1) / 2
    X0, X1 = xm - Lp / 2, xm + Lp / 2
    s_pts = [(R * math.asin(max(-1.0, min(1.0, q[3] / R))), q[2]) for q in corte]   # (alrededor, a lo largo)
    smin, smax = min(s for s, _ in s_pts), max(s for s, _ in s_pts)
    fmin, fmax = smin / R, smax / R

    def intervalo(fi):
        """Parte del principal que el agujero quita a este ángulo: (desde, hasta) a lo largo de X."""
        s = fi * R
        cruces = []
        for i in range(len(s_pts)):
            (sa, xa), (sb, xb) = s_pts[i], s_pts[(i + 1) % len(s_pts)]
            if (sa - s) * (sb - s) <= 0 and abs(sb - sa) > 1e-12:
                cruces.append(xa + (s - sa) * (xb - xa) / (sb - sa))
            elif abs(sa - s) < 1e-12:
                cruces.append(xa)
        if not cruces:
            return None
        return (min(cruces), max(cruces))

    n_vuelta = 96
    angulos = [-PI + 2 * PI * k / n_vuelta for k in range(n_vuelta + 1)]
    angulos = [a for a in angulos if not (fmin - 1e-9 <= a <= fmax + 1e-9)]
    n_hueco = 32
    angulos += [fmin + (fmax - fmin) * k / n_hueco for k in range(n_hueco + 1)]
    angulos = sorted(set(round(a, 12) for a in angulos))

    def P(fi, X):
        return (X, R * math.sin(fi), R * math.cos(fi))

    principal = Parte(nombre("boca", m) + " · principal")
    # Primero la tira del medio del agujero: «Desdoblar caras» empieza por la primera cara y la
    # costura queda del lado contrario (atrás, lejos del agujero), igual que el plano del CAD-CAM 2D.
    fm = (fmin + fmax) / 2
    orden = sorted(range(len(angulos) - 1), key=lambda k: abs((angulos[k] + angulos[k + 1]) / 2 - fm))
    for k in orden:
        fa, fb = angulos[k], angulos[k + 1]
        dentro = fa >= fmin - 1e-9 and fb <= fmax + 1e-9
        ia, ib = (intervalo(fa), intervalo(fb)) if dentro else (None, None)
        Xc = (X0 + X1) / 2
        if ia and ib:
            principal.cara([P(fa, X0), P(fb, X0), P(fb, ib[0]), P(fa, ia[0])], (Xc, 0.0, 0.0))
            principal.cara([P(fa, ia[1]), P(fb, ib[1]), P(fb, X1), P(fa, X1)], (Xc, 0.0, 0.0))
        else:
            # La tira vecina del agujero lleva en su borde los mismos puntos donde empieza el agujero
            # (si no, las tiras no quedan unidas y no se desdobla en una sola pieza).
            lado_b, lado_a = [P(fb, X0)], [P(fa, X1)]
            if abs(fb - fmin) < 1e-9 and intervalo(fb):
                iv = intervalo(fb)
                lado_b += [P(fb, x) for x in sorted(set((round(iv[0], 9), round(iv[1], 9))))]
            if abs(fa - fmax) < 1e-9 and intervalo(fa):
                iv = intervalo(fa)
                lado_a += [P(fa, x) for x in sorted(set((round(iv[0], 9), round(iv[1], 9))), reverse=True)]
            principal.cara(lado_b + [P(fb, X1)] + lado_a + [P(fa, X0)], (Xc, 0.0, 0.0))
    return [principal, ramal]
