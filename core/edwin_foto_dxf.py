# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""Foto → plano → DXF para EDWIN CNC (sin Qt).

El usuario pone la pieza (plantilla, brida, letra, lámina...) sobre la «Hoja de
escala EDWIN» o entre 4 marcas grandes, le toma una foto con el celular, y aquí:

1. se encuentran las 4 marcas (ArUco 4x4, números 0 a 3) o se usan 4 esquinas
   que el usuario marcó a mano;
2. se endereza la foto (se quita la perspectiva) a escala 1:1 en milímetros;
3. se separa la pieza del fondo y se saca su contorno con sus huecos;
4. se guarda el DXF en mm (capas CORTE y REFERENCIA, como el CAD-CAM).

Usa numpy + OpenCV (Apache-2.0) + ezdxf (MIT).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------- la hoja
# Pensada para caber en CARTA y en A4 con márgenes de impresora.
HOJA_MARCA = 25.0            # lado de cada marca (mm)
HOJA_ANCHO = 170.0           # distancia entre CENTROS de marcas, horizontal (mm)
HOJA_ALTO = 230.0            # distancia entre CENTROS de marcas, vertical (mm)
DICCIONARIO = "DICT_4X4_50"
CONTRASTE_MINIMO = 35       # diferencia mínima de gris entre pieza y fondo (0..255)
# Orden de las marcas: 0 arriba-izquierda, 1 arriba-derecha, 2 abajo-derecha, 3 abajo-izquierda.


def _cv():
    import cv2
    return cv2


def imagen_marca(numero: int, pixeles: int = 200):
    """La marca ArUco como matriz de píxeles (0 negro, 255 blanco), para imprimir."""
    cv2 = _cv()
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICCIONARIO))
    return cv2.aruco.generateImageMarker(dic, numero, pixeles)


def leer_foto(ruta: str):
    """Abre la foto aunque la ruta tenga tildes o eñes (cv2.imread no puede)."""
    cv2 = _cv()
    datos = np.fromfile(ruta, dtype=np.uint8)
    img = cv2.imdecode(datos, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("No se pudo abrir la foto (¿es una imagen JPG o PNG?).")
    return img


def buscar_marcas(img):
    """Centros de las marcas 0..3 en la foto: {numero: (x, y)} y sus esquinas."""
    cv2 = _cv()
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    dic = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICCIONARIO))
    param = cv2.aruco.DetectorParameters()
    param.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.ArucoDetector(dic, param)
    esquinas, ids, _ = detector.detectMarkers(gris)
    centros, todas = {}, {}
    if ids is not None:
        for c, i in zip(esquinas, ids.flatten()):
            i = int(i)
            if 0 <= i <= 3 and i not in centros:
                pts = c.reshape(4, 2).astype(np.float64)
                centros[i] = tuple(pts.mean(axis=0))
                todas[i] = pts
    return centros, todas


@dataclass
class Enderezado:
    imagen: np.ndarray            # foto enderezada (BGR), 1 píxel = 1/ppmm mm
    ppmm: float                   # píxeles por milímetro
    origen_mm: tuple              # (x, y) en mm del píxel (0, 0), y hacia ABAJO
    error_mm: float | None        # qué tan bien calzan las marcas (None = no se pudo medir)
    ancho: float
    alto: float


def enderezar(img, puntos_foto, ancho_mm, alto_mm, margen_mm=0.0, ppmm=None, esquinas_marcas=None,
              lado_marca=None):
    """Quita la perspectiva. puntos_foto = 4 puntos (arriba-izq, arriba-der, abajo-der,
    abajo-izq) que en la realidad forman un rectángulo de ancho_mm × alto_mm."""
    cv2 = _cv()
    src = np.array(puntos_foto, dtype=np.float64).reshape(4, 2)
    dst = np.array([(0, 0), (ancho_mm, 0), (ancho_mm, alto_mm), (0, alto_mm)], dtype=np.float64)
    error = None
    if esquinas_marcas is not None and lado_marca:
        # 16 puntos (las 4 esquinas de cada marca) en vez de 4: más precisión y una
        # medida del error.
        s, d = [], []
        mitad = lado_marca / 2.0
        for i, (cx, cy) in enumerate(dst):
            if i not in esquinas_marcas:
                continue
            s += list(esquinas_marcas[i])
            d += [(cx - mitad, cy - mitad), (cx + mitad, cy - mitad), (cx + mitad, cy + mitad), (cx - mitad, cy + mitad)]
        H, _ = cv2.findHomography(np.array(s), np.array(d), 0)
        proy = cv2.perspectiveTransform(np.array(s).reshape(-1, 1, 2), H).reshape(-1, 2)
        error = float(np.sqrt(((proy - np.array(d)) ** 2).sum(axis=1)).max())
    else:
        H = cv2.getPerspectiveTransform(src.astype(np.float32), dst.astype(np.float32)).astype(np.float64)
    if ppmm is None:
        # que la foto enderezada tenga más o menos la resolución de la original, sin pasarse
        lado_foto = float(np.linalg.norm(src[1] - src[0]) + np.linalg.norm(src[2] - src[3])) / 2.0
        ppmm = min(max(lado_foto / ancho_mm, 2.0), 10.0)
        tot = (ancho_mm + 2 * margen_mm) * (alto_mm + 2 * margen_mm) * ppmm * ppmm
        if tot > 36e6:                       # máximo ~36 megapíxeles (memoria de 8 GB)
            ppmm *= (36e6 / tot) ** 0.5
    T = np.array([[ppmm, 0, margen_mm * ppmm], [0, ppmm, margen_mm * ppmm], [0, 0, 1]], dtype=np.float64)
    w = int(round((ancho_mm + 2 * margen_mm) * ppmm))
    h = int(round((alto_mm + 2 * margen_mm) * ppmm))
    salida = cv2.warpPerspective(img, T @ H, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(255, 255, 255))
    return Enderezado(salida, ppmm, (-margen_mm, -margen_mm), error, ancho_mm, alto_mm)


@dataclass
class Ajustes:
    umbral: int | None = None       # None = automático (Otsu); si no, 0..255
    pieza_oscura: bool = True       # pieza más oscura que el fondo (lo normal sobre papel blanco)
    suavizado_mm: float = 0.3       # cuánto se simplifica el contorno
    minimo_mm2: float = 20.0        # manchas y huecos más pequeños se ignoran
    solo_la_mayor: bool = True      # True = solo la pieza más grande
    tapar_marcas: bool = True       # borrar las marcas antes de buscar la pieza


@dataclass
class Pieza:
    contorno: list                  # [(x, y), ...] mm, y hacia ARRIBA (como en CAD)
    huecos: list = field(default_factory=list)
    ancho: float = 0.0
    alto: float = 0.0
    area: float = 0.0


def _zona_marcas(forma, e: Enderezado, lado_marca, extra=3.0):
    """Máscara (True) de los cuadros de las 4 marcas, que no son pieza ni fondo."""
    z = np.zeros(forma, bool)
    for cx, cy in [(0, 0), (e.ancho, 0), (e.ancho, e.alto), (0, e.alto)]:
        m = lado_marca / 2.0 + extra
        x0 = max(0, int((cx - m - e.origen_mm[0]) * e.ppmm))
        y0 = max(0, int((cy - m - e.origen_mm[1]) * e.ppmm))
        x1 = max(0, int((cx + m - e.origen_mm[0]) * e.ppmm))
        y1 = max(0, int((cy + m - e.origen_mm[1]) * e.ppmm))
        z[y0:y1, x0:x1] = True
    return z


def _superficie(gris, cuales):
    """Superficie suave (polinomio de grado 2) ajustada a los píxeles «cuales»."""
    h, w = gris.shape
    paso = max(1, int((h * w / 40000) ** 0.5))          # ~40 000 muestras
    ys, xs = np.mgrid[0:h:paso, 0:w:paso]
    sel = cuales[::paso, ::paso]
    if sel.sum() < 50:
        return None
    x = xs[sel].astype(np.float64) / w
    y = ys[sel].astype(np.float64) / h
    z = gris[::paso, ::paso][sel].astype(np.float64)
    A = np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], axis=1)
    coef, *_ = np.linalg.lstsq(A, z, rcond=None)
    Y, X = np.mgrid[0:h, 0:w].astype(np.float32)
    X /= w
    Y /= h
    sup = coef[0] + coef[1] * X + coef[2] * Y + coef[3] * X * X + coef[4] * X * Y + coef[5] * Y * Y
    return np.clip(sup, 1.0, None), float(z.mean())


def _otsu(valores, tipo):
    """Umbral de Otsu sobre una lista de valores; devuelve (umbral, contraste)."""
    cv2 = _cv()
    v = valores.reshape(-1, 1).astype(np.uint8)
    u, m = cv2.threshold(v, 0, 255, tipo | cv2.THRESH_OTSU)
    m = m.reshape(-1) > 0
    if m.all() or not m.any():
        return u, 0.0
    return u, abs(float(valores[m].mean()) - float(valores[~m].mean()))


def _parejar_luz(gris, tipo, validos):
    """Quita la luz dispareja (un lado más oscuro, sombra suave del celular).

    Se ajusta una superficie suave al FONDO y se divide la foto por ella, en
    3 pasadas: la primera con todo, las siguientes sin lo que parece pieza. Si
    no hay contraste (hoja vacía) se usa todo como fondo."""
    cv2 = _cv()
    fondo = validos.copy()
    nivel = gris
    for _ in range(3):
        r = _superficie(gris, fondo)
        if r is None:
            break
        sup, media = r
        nivel = np.clip(gris.astype(np.float32) * (media / sup), 0, 255).astype(np.uint8)
        u, contraste = _otsu(nivel[validos], tipo)
        if contraste < CONTRASTE_MINIMO:
            fondo = validos.copy()
        else:
            _, m = cv2.threshold(nivel, u, 255, tipo)
            fondo = validos & (m == 0)
    return nivel


def mascara(e: Enderezado, aj: Ajustes, lado_marca=None):
    """Blanco = pieza, negro = fondo. Devuelve (mascara, umbral usado)."""
    cv2 = _cv()
    gris = cv2.cvtColor(e.imagen, cv2.COLOR_BGR2GRAY)
    gris = cv2.GaussianBlur(gris, (5, 5), 0)
    tipo = cv2.THRESH_BINARY_INV if aj.pieza_oscura else cv2.THRESH_BINARY
    marcas = _zona_marcas(gris.shape, e, lado_marca) if (aj.tapar_marcas and lado_marca) else np.zeros(gris.shape, bool)
    validos = ~marcas
    gris = _parejar_luz(gris, tipo, validos)
    if aj.umbral is None:
        u, contraste = _otsu(gris[validos], tipo)
        # Sin contraste entre las dos partes = no hay pieza (hoja vacía): Otsu
        # siempre parte la imagen en dos, aunque solo sea por la luz.
        _, m = cv2.threshold(gris, u, 255, tipo)
        if contraste < CONTRASTE_MINIMO:
            m[:] = 0
    else:
        u, m = cv2.threshold(gris, int(aj.umbral), 255, tipo)
    m[marcas] = 0
    r = max(1, int(round(e.ppmm * 0.5)))
    el = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, el)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, el)
    return m, int(u)


def _limpiar(poli, tol):
    """Quita los puntos que sobran en una recta (cada punto a menos de «tol» mm de
    la línea entre sus vecinos), incluido el punto donde arranca el contorno."""
    pts = list(poli)
    cambio = True
    while cambio and len(pts) > 3:
        cambio = False
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            dx, dy = c[0] - a[0], c[1] - a[1]
            largo = (dx * dx + dy * dy) ** 0.5
            if largo < 1e-12:
                d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            else:
                d = abs(dx * (b[1] - a[1]) - dy * (b[0] - a[0])) / largo
            if d < tol:
                del pts[i]
                cambio = True
                break
    return _esquinas(pts, tol)


def _esquinas(pts, tol, corto=2.5, giro_minimo=30.0):
    """El desenfoque redondea las esquinas y el contorno sale con un «chaflán»
    cortísimo. Si un tramo mide menos de «corto» mm, los lados giran más de
    «giro_minimo» grados (una esquina, no una curva) y sus rectas se cruzan
    cerca, los dos puntos se cambian por ese cruce."""
    cambio = True
    while cambio and len(pts) > 3:
        cambio = False
        n = len(pts)
        for i in range(n):
            a, b, c, d = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
            if ((c[0] - b[0]) ** 2 + (c[1] - b[1]) ** 2) ** 0.5 >= corto:
                continue
            # cruce de la recta a-b con la recta c-d
            r = (b[0] - a[0], b[1] - a[1])
            q = (d[0] - c[0], d[1] - c[1])
            den = r[0] * q[1] - r[1] * q[0]
            if abs(den) < 1e-9:
                continue
            # solo en esquinas de verdad (en una curva cada tramo gira poquito)
            giro = abs(math.degrees(math.atan2(den, r[0] * q[0] + r[1] * q[1])))
            if giro < giro_minimo:
                continue
            t = ((c[0] - a[0]) * q[1] - (c[1] - a[1]) * q[0]) / den
            x = (a[0] + t * r[0], a[1] + t * r[1])
            if ((x[0] - b[0]) ** 2 + (x[1] - b[1]) ** 2) ** 0.5 > 2 * corto:
                continue
            j = (i + 1) % n
            pts[i] = x
            del pts[j]
            cambio = True
            break
    return pts


def _a_mm(pts, e: Enderezado):
    """Píxeles → mm con Y hacia arriba (en la hoja el 0 está arriba a la izquierda;
    en el DXF queda abajo a la izquierda de la pieza)."""
    out = []
    for x, y in pts:
        out.append((x / e.ppmm + e.origen_mm[0], -(y / e.ppmm + e.origen_mm[1])))
    return out


def _area(poli):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(poli, poli[1:] + poli[:1]):
        a += x0 * y1 - x1 * y0
    return a / 2.0


def contornos(e: Enderezado, aj: Ajustes, lado_marca=None):
    """Las piezas encontradas, de la más grande a la más pequeña."""
    cv2 = _cv()
    m, _ = mascara(e, aj, lado_marca)
    cs, jer = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if jer is None:
        return []
    jer = jer[0]
    tol_px = max(0.5, aj.suavizado_mm * e.ppmm)
    min_px = aj.minimo_mm2 * e.ppmm * e.ppmm
    piezas = []
    for i, c in enumerate(cs):
        if jer[i][3] != -1:                      # es un hueco: se agrega con su pieza
            continue
        if cv2.contourArea(c) < min_px:
            continue
        # una pieza que toca el borde de la foto enderezada no está entera
        x, y, w, h = cv2.boundingRect(c)
        ap = cv2.approxPolyDP(c, tol_px, True).reshape(-1, 2)
        if len(ap) < 3:
            continue
        cont = _limpiar(_a_mm(ap.tolist(), e), aj.suavizado_mm)
        if _area(cont) < 0:
            cont.reverse()                      # contorno antihorario
        huecos = []
        j = jer[i][2]
        while j != -1:
            if cv2.contourArea(cs[j]) >= min_px:
                hp = cv2.approxPolyDP(cs[j], tol_px, True).reshape(-1, 2)
                if len(hp) >= 3:
                    hh = _limpiar(_a_mm(hp.tolist(), e), aj.suavizado_mm)
                    if _area(hh) > 0:
                        hh.reverse()            # huecos horario
                    huecos.append(hh)
            j = jer[j][0]
        xs = [p[0] for p in cont]
        ys = [p[1] for p in cont]
        area = _area(cont) + sum(_area(hh) for hh in huecos)
        p = Pieza(cont, huecos, max(xs) - min(xs), max(ys) - min(ys), area)
        p.toca_borde = x <= 1 or y <= 1 or x + w >= m.shape[1] - 1 or y + h >= m.shape[0] - 1
        piezas.append(p)
    piezas.sort(key=lambda p: -p.area)
    return piezas[:1] if aj.solo_la_mayor else piezas


def guardar_dxf(piezas, ruta, nombre="PIEZA", mover_al_origen=True):
    """DXF R2000 en mm: contornos y huecos en CORTE, un texto en REFERENCIA."""
    import ezdxf
    doc = ezdxf.new("R2000", setup=False)
    doc.units = 4                                  # milímetros
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1
    doc.layers.add("CORTE", color=1)
    doc.layers.add("REFERENCIA", color=8)
    msp = doc.modelspace()
    dx = dy = 0.0
    if mover_al_origen and piezas:
        dx = -min(x for p in piezas for x, _ in p.contorno)
        dy = -min(y for p in piezas for _, y in p.contorno)
    for k, p in enumerate(piezas, start=1):
        for lazo in [p.contorno] + list(p.huecos):
            msp.add_lwpolyline([(x + dx, y + dy) for x, y in lazo], close=True, dxfattribs={"layer": "CORTE"})
        x0 = min(x for x, _ in p.contorno) + dx
        y0 = min(y for _, y in p.contorno) + dy
        txt = f"{nombre}{'-' + str(k) if len(piezas) > 1 else ''}  {p.ancho:.1f} x {p.alto:.1f} mm (desde foto)"
        msp.add_text(txt, height=max(3.0, min(p.ancho, p.alto) / 25.0),
                     dxfattribs={"layer": "REFERENCIA", "insert": (x0, y0 - 8.0)})
    doc.saveas(ruta)
    return ruta


def procesar_con_hoja(img, aj: Ajustes | None = None, ancho=HOJA_ANCHO, alto=HOJA_ALTO, lado_marca=HOJA_MARCA,
                      margen_mm=None):
    """Todo de una vez con las marcas (hoja EDWIN o 4 marcas grandes)."""
    aj = aj or Ajustes()
    centros, esquinas = buscar_marcas(img)
    faltan = [i for i in range(4) if i not in centros]
    if faltan:
        raise ValueError(
            "No se encontraron todas las marcas (faltan: " + ", ".join(str(f) for f in faltan) + "). "
            "Que se vean las 4 completas, sin reflejo, sin sombra encima y con la foto enfocada.")
    if margen_mm is None:
        margen_mm = 0.0
    e = enderezar(img, [centros[i] for i in range(4)], ancho, alto, margen_mm=margen_mm,
                  esquinas_marcas=esquinas, lado_marca=lado_marca)
    return e, contornos(e, aj, lado_marca)
