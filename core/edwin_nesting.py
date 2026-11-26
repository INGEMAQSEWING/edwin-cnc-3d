# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""Acomodo automático de piezas en la lámina (nesting) — EDWIN CNC 3D.

Es el mismo método de EDWIN CNC CAD-CAM 2D (plugins/edwincnc/nesting.h):
  1) La lámina se ve como una cuadrícula de celdas de `celda` mm. Cada pieza, en
     cada giro permitido, se convierte en las celdas que toca (si la toca aunque
     sea un poquito, la celda cuenta: así nunca se montan dos piezas). Los huecos
     quedan libres: una pieza pequeña puede caer DENTRO del hueco de una grande.
  2) La separación entre piezas se garantiza engordando la pieza nueva esa
     distancia; el borde de la lámina deja `margen`.
  3) De la más grande a la más chica; cada una en la primera lámina donde quepa,
     lo más a la izquierda posible y después lo más abajo (lo que sobra queda
     junto a la derecha, como retal). Si no cabe, se abre otra lámina.
Para que sea rápido en Python, la búsqueda de sitio se hace de una vez para toda
la lámina con una correlación por FFT (numpy).

Sin Qt: se prueba solo (edwin/pruebas/prueba_nesting.py).
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Pieza:
    afuera: list                                   # [(x, y)] mm
    huecos: list = field(default_factory=list)     # [[(x, y)], ...]
    cantidad: int = 1


@dataclass
class Opciones:
    ancho: float = 2440.0        # lámina (mm)
    alto: float = 1220.0
    margen: float = 10.0         # al borde de la lámina
    separacion: float = 6.0      # entre piezas (ancho del corte + lo que se quiera dejar)
    celda: float = 0.0           # 0 = automática
    giros: int = 4               # 1 (no gira), 2 (0/180°), 4 (cada 90°), 8 (cada 45°), 24 (cada 15°)
    max_laminas: int = 200


@dataclass
class Colocacion:
    """Girar `angulo` (radianes, contra el reloj) alrededor del origen y mover (dx, dy):
    coordenadas de la lámina `lamina`, con su esquina de abajo a la izquierda en (0, 0)."""
    pieza: int
    copia: int
    lamina: int
    angulo: float
    dx: float
    dy: float


@dataclass
class Resultado:
    colocadas: list = field(default_factory=list)
    no_caben: list = field(default_factory=list)
    laminas: int = 0
    uso_por_lamina: list = field(default_factory=list)
    area_piezas: float = 0.0
    celda: float = 0.0


def area(p):
    s = 0.0
    for i in range(len(p)):
        x1, y1 = p[i - 1]
        x2, y2 = p[i]
        s += x1 * y2 - x2 * y1
    return s / 2


def _valida(pz: Pieza):
    if len(pz.afuera) < 3:
        return False
    for anillo in [pz.afuera] + list(pz.huecos):
        for p in anillo:
            if not (math.isfinite(p[0]) and math.isfinite(p[1])):
                return False
    return True


def area_neta(pz: Pieza):
    if not _valida(pz):
        return 0.0
    a = max(0.0, abs(area(pz.afuera)) - sum(abs(area(h)) for h in pz.huecos))
    return a if math.isfinite(a) else 0.0


def girar(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


# ---------------------------------------------------------------- cuadrícula
def rasterizar(anillos, ox, oy, c, w, h):
    """Celdas (h x w, bool) que toca el polígono con huecos (pares/impares)."""
    b = np.zeros((h, w), dtype=bool)
    # 1) centros de celda dentro
    ys = oy + (np.arange(h) + 0.5) * c
    for y_i, yc in enumerate(ys):
        xs = []
        for p in anillos:
            arr = np.asarray(p, dtype=float)
            a, q = np.roll(arr, 1, axis=0), arr
            cruza = (a[:, 1] > yc) != (q[:, 1] > yc)
            if np.any(cruza):
                aa, qq = a[cruza], q[cruza]
                xs.extend((aa[:, 0] + (yc - aa[:, 1]) * (qq[:, 0] - aa[:, 0]) / (qq[:, 1] - aa[:, 1])).tolist())
        if len(xs) < 2:
            continue
        xs.sort()
        for k in range(0, len(xs) - 1, 2):
            x0 = int(math.ceil((xs[k] - ox) / c - 0.5))
            x1 = int(math.floor((xs[k + 1] - ox) / c - 0.5))
            x0, x1 = max(0, x0), min(w - 1, x1)
            if x0 <= x1:
                b[y_i, x0:x1 + 1] = True
    # 2) celdas por donde pasa cada borde (sin saltarse ninguna)

    def poner(cx, cy):
        if 0 <= cx < w and 0 <= cy < h:
            b[cy, cx] = True

    for p in anillos:
        for i in range(len(p)):
            x0, y0 = (p[i - 1][0] - ox) / c, (p[i - 1][1] - oy) / c
            x1, y1 = (p[i][0] - ox) / c, (p[i][1] - oy) / c
            cx, cy = int(math.floor(x0)), int(math.floor(y0))
            ex, ey = int(math.floor(x1)), int(math.floor(y1))
            dx, dy = x1 - x0, y1 - y0
            sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
            tmx = ((cx + 1 - x0) if sx > 0 else (x0 - cx)) / abs(dx) if dx else 1e30
            tmy = ((cy + 1 - y0) if sy > 0 else (y0 - cy)) / abs(dy) if dy else 1e30
            tdx = 1 / abs(dx) if dx else 1e30
            tdy = 1 / abs(dy) if dy else 1e30
            poner(cx, cy)
            guarda = 0
            while (cx != ex or cy != ey) and guarda < 100000:
                guarda += 1
                if tmx < tmy:
                    cx += sx; tmx += tdx
                elif tmy < tmx:
                    cy += sy; tmy += tdy
                else:
                    poner(cx + sx, cy); poner(cx, cy + sy)
                    cx += sx; cy += sy; tmx += tdx; tmy += tdy
                poner(cx, cy)
    return b


def engordar(b, r):
    """Engorda las celdas ocupadas r celdas (disco); la salida crece r por cada lado."""
    if r <= 0:
        return b.copy()
    h, w = b.shape
    o = np.zeros((h + 2 * r, w + 2 * r), dtype=bool)
    for dy in range(-r, r + 1):
        a = int(math.floor(math.sqrt(r * r - dy * dy) + 1e-9))
        for dx in range(-a, a + 1):
            o[r + dy:r + dy + h, r + dx:r + dx + w] |= b
    return o


@dataclass
class _Forma:
    angulo: float
    nucleo: np.ndarray          # pieza real
    mascara: np.ndarray         # pieza engordada
    min_x: float
    min_y: float
    espectro: object = None     # FFT de la máscara (por tamaño de lámina)


def _tam_fft(n):
    m = 1
    while m < n:
        m *= 2
    return m


def acomodar(piezas, op: Opciones) -> Resultado:
    res = Resultado()
    W, H = op.ancho - 2 * op.margen, op.alto - 2 * op.margen
    if W <= 0 or H <= 0 or not piezas:
        return res
    c = op.celda if op.celda > 0 else max(1.0, max(W, H) / 600.0)
    c = max(0.5, c)
    res.celda = c
    cw, ch = int(math.floor(W / c)), int(math.floor(H / c))
    r = int(math.ceil(op.separacion / c))
    giros = max(1, int(op.giros))
    # cuadrícula de la lámina con r celdas de más por cada lado: ahí puede caer el engorde,
    # nunca la pieza real
    Wp, Hp = cw + 2 * r, ch + 2 * r
    sy, sx = _tam_fft(Hp), _tam_fft(Wp)

    formas = []
    for pz in piezas:
        lista = []
        for gi in range(giros):
            ang = 2 * math.pi * gi / giros
            # Pieza rota (menos de 3 puntos, números no finitos) o más grande que la lámina (por
            # ejemplo un dibujo en metros leído como mm): no cabe con este giro y NO se reserva la
            # cuadrícula (así no se agota la memoria).
            if not _valida(pz):
                lista.append(_Forma(ang, np.zeros((0, 0), bool), np.zeros((0, 0), bool), 0.0, 0.0))
                continue
            af = [girar(p, ang) for p in pz.afuera]
            hs = [[girar(p, ang) for p in h] for h in pz.huecos]
            x0 = min(p[0] for p in af); y0 = min(p[1] for p in af)
            x1 = max(p[0] for p in af); y1 = max(p[1] for p in af)
            if (x1 - x0) / c + 1 > cw or (y1 - y0) / c + 1 > ch:
                lista.append(_Forma(ang, np.zeros((0, 0), bool), np.zeros((0, 0), bool), x0, y0))
                continue
            nw, nh = int(math.floor((x1 - x0) / c)) + 1, int(math.floor((y1 - y0) / c)) + 1
            nuc = rasterizar([af] + hs, x0, y0, c, nw, nh)
            f = _Forma(ang, nuc, engordar(nuc, r), x0, y0)
            if nw <= cw and nh <= ch:
                pad = np.zeros((sy, sx))
                mh, mw = f.mascara.shape
                pad[:mh, :mw] = f.mascara
                f.espectro = np.conj(np.fft.rfft2(pad))
            lista.append(f)
        formas.append(lista)

    copias = []
    for i, pz in enumerate(piezas):
        for k in range(max(1, int(pz.cantidad))):
            copias.append((i, k, area_neta(pz)))
    copias.sort(key=lambda t: -t[2])

    laminas, espectros, usado = [], [], []

    def buscar(L, f):
        mh, mw = f.mascara.shape
        if mw > Wp or mh > Hp:
            return None
        corr = np.fft.irfft2(espectros[L] * f.espectro, s=(sy, sx))
        libre = corr[:Hp - mh + 1, :Wp - mw + 1] < 0.5
        cols = np.flatnonzero(libre.any(axis=0))
        if cols.size == 0:
            return None
        x = int(cols[0])
        y = int(np.flatnonzero(libre[:, x])[0])
        return x, y

    for (i, k, a) in copias:
        if not any(f.espectro is not None for f in formas[i]):
            if k == 0:
                res.no_caben.append(i)
            continue
        puesto = False
        L = 0
        while not puesto:
            if L == len(laminas):
                if len(laminas) >= op.max_laminas:
                    break
                laminas.append(np.zeros((Hp, Wp), dtype=bool))
                espectros.append(np.fft.rfft2(np.zeros((sy, sx))))
                usado.append(0.0)
            mejor = None
            for f in formas[i]:
                if f.espectro is None:
                    continue
                pos = buscar(L, f)
                if pos is not None and (mejor is None or (pos[0], pos[1]) < (mejor[1][0], mejor[1][1])):
                    mejor = (f, pos)
            if mejor is None:
                vacia = not laminas[L].any()
                L += 1
                if vacia:          # ni en una lámina vacía: no cabe con ningún giro
                    break
                continue
            f, (x, y) = mejor
            nh, nw = f.nucleo.shape
            laminas[L][y + r:y + r + nh, x + r:x + r + nw] |= f.nucleo
            pad = np.zeros((sy, sx))
            pad[:Hp, :Wp] = laminas[L]
            espectros[L] = np.fft.rfft2(pad)
            # celda (x, y) del núcleo (sin la franja) ↔ esquina (min_x, min_y) de la pieza girada
            res.colocadas.append(Colocacion(i, k, L, f.angulo,
                                            op.margen + x * c - f.min_x, op.margen + y * c - f.min_y))
            usado[L] += a
            res.area_piezas += a
            puesto = True
        if not puesto and i not in res.no_caben:
            res.no_caben.append(i)
    # quitar láminas que quedaron vacías al final (si una pieza no cupo en ninguna)
    while laminas and not laminas[-1].any():
        laminas.pop(); usado.pop()
    res.laminas = len(laminas)
    res.uso_por_lamina = [u / (op.ancho * op.alto) for u in usado]
    return res


# ---------------------------------------------------------------- piezas del desdoblado
def _arco_a_puntos(a, b, bulge, paso_grados=5.0):
    from core.edwin_desdoblar import _punto_en_arco
    ang = abs(4 * math.atan(bulge))
    n = max(2, int(math.ceil(math.degrees(ang) / paso_grados)))
    return [_punto_en_arco(a, b, bulge, t / n) for t in range(n)]


def contorno_a_poligono(l):
    """Contorno [(x, y, bulge)] → polígono con los arcos en tramos de 5°."""
    out = []
    for k, (x, y, bl) in enumerate(l):
        if bl:
            x2, y2, _ = l[(k + 1) % len(l)]
            out.extend(_arco_a_puntos((x, y), (x2, y2), bl))
        else:
            out.append((x, y))
    return out


def desde_desdoblado(piezas_ed, cantidad=1):
    """Piezas de core.edwin_desdoblar → Piezas para acomodar (el contorno más grande es el de afuera)."""
    out = []
    for pz in piezas_ed:
        pols = [contorno_a_poligono(l) for l in pz.contornos]
        if not pols:
            continue
        k = max(range(len(pols)), key=lambda i: abs(area(pols[i])))
        out.append(Pieza(pols[k], [p for i, p in enumerate(pols) if i != k], cantidad))
    return out


PASO_LAMINAS = 200.0   # mm entre una lámina y la siguiente en el DXF


def piezas_acomodadas(piezas_ed, res: Resultado, op: Opciones):
    """Copias de las piezas del desdoblado ya giradas y movidas a su lámina (láminas una al lado de
    la otra en X). Devuelve (piezas, laminas) con laminas = [(x0, y0, ancho, alto, texto)]."""
    from core.edwin_desdoblar import _transformar
    salida = []
    for col in res.colocadas:
        pz = copy.deepcopy(piezas_ed[col.pieza])
        c, s = math.cos(col.angulo), math.sin(col.angulo)
        ox = col.lamina * (op.ancho + PASO_LAMINAS) + col.dx
        _transformar(pz, lambda p, c=c, s=s, ox=ox, oy=col.dy: (c * p[0] - s * p[1] + ox, s * p[0] + c * p[1] + oy))
        salida.append(pz)
    laminas = []
    for L in range(res.laminas):
        uso = res.uso_por_lamina[L] * 100
        laminas.append((L * (op.ancho + PASO_LAMINAS), 0.0, op.ancho, op.alto,
                        f"Lamina {L + 1} de {res.laminas} - {op.ancho:.0f} x {op.alto:.0f} mm - "
                        f"aprovechada {uso:.1f} %"))
    return salida, laminas
