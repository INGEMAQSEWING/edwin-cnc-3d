# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""Helicoidal (aleta de sinfín) para EDWIN CNC 3D, sin Qt.

Superficie entre el eje (diámetro interior) y el borde (diámetro exterior) que sube
un «paso» por cada vuelta.  Cada tramo es un cuadrilátero torcido, así que se parte
en dos triángulos planos: así «Desdoblar caras» los puede acostar tramo por tramo,
como se hacía en SketchUp (el usuario escoge tramos pequeños y acepta la pequeña
deformación).

Todo en milímetros; el eje del sinfín es Z y arranca en el origen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Medidas:
    exterior: float = 300.0       # diámetro de afuera (mm)
    interior: float = 76.0        # diámetro del eje / tubo (mm)
    paso: float = 300.0           # lo que sube en una vuelta (mm)
    vueltas: float = 1.0          # puede ser fraccionario (media vuelta = 0,5)
    divisiones: int = 36          # tramos por vuelta
    ancho: int = 1                # tramos a lo ancho (del eje al borde)
    derecha: bool = True          # sentido de la hélice (derecha = antihorario al subir)


def problema(m: Medidas) -> str | None:
    """None = medidas válidas; si no, el motivo en palabras sencillas."""
    if m.exterior <= 0:
        return "El diámetro de afuera debe ser mayor que cero."
    if m.interior <= 0:
        return "El diámetro del eje debe ser mayor que cero."
    if m.interior >= m.exterior:
        return "El diámetro del eje debe ser menor que el de afuera."
    if m.paso <= 0:
        return "El paso debe ser mayor que cero."
    if m.vueltas <= 0:
        return "El número de vueltas debe ser mayor que cero."
    if m.divisiones < 6:
        return "Use al menos 6 tramos por vuelta."
    if m.ancho < 1:
        return "Use al menos 1 tramo a lo ancho."
    if m.divisiones * m.vueltas * m.ancho > 20000:
        return "Son demasiados tramos; baje las divisiones o las vueltas."
    return None


def construir(m: Medidas):
    """Devuelve (vertices, triangulos, diagonales).

    vertices: lista de (x, y, z) en mm.
    triangulos: índices, todos con el mismo sentido de giro (caras consistentes).
    diagonales: pares de índices de la línea que parte cada tramo en dos
    (se dibujan suaves para que un clic tome el tramo entero)."""
    err = problema(m)
    if err:
        raise ValueError(err)
    total = max(1, round(m.divisiones * m.vueltas))
    ri, re = m.interior / 2.0, m.exterior / 2.0
    signo = 1.0 if m.derecha else -1.0
    vertices = []
    for i in range(total + 1):
        t = m.vueltas * i / total               # vueltas recorridas
        ang = signo * 2.0 * math.pi * t
        z = m.paso * t
        c, s = math.cos(ang), math.sin(ang)
        for j in range(m.ancho + 1):
            r = ri + (re - ri) * j / m.ancho
            vertices.append((r * c, r * s, z))

    fila = m.ancho + 1
    triangulos, diagonales = [], []
    for i in range(total):
        for j in range(m.ancho):
            a = i * fila + j            # eje, ángulo i
            b = a + 1                   # borde, ángulo i
            c = a + fila                # eje, ángulo i+1
            d = b + fila                # borde, ángulo i+1
            if m.derecha:
                triangulos += [(a, b, d), (a, d, c)]
            else:
                triangulos += [(a, d, b), (a, c, d)]
            diagonales.append((a, d))
    return vertices, triangulos, diagonales


def arandela(m: Medidas) -> dict:
    """Medidas de taller de la arandela abierta de UNA vuelta (fórmula de los
    sinfines), solo como dato de referencia en la ventana."""
    lo = math.hypot(math.pi * m.exterior, m.paso)   # largo del borde en una vuelta
    li = math.hypot(math.pi * m.interior, m.paso)   # largo junto al eje
    b = (m.exterior - m.interior) / 2.0
    r = b * li / (lo - li)
    R = r + b
    angulo = 360.0 * (1.0 - lo / (2.0 * math.pi * R))
    return {"largo_borde": lo, "largo_eje": li, "ancho": b,
            "radio_interior": r, "radio_exterior": R, "angulo_abertura": angulo}
