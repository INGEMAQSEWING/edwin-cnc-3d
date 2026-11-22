# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""Materiales EDWIN: acabados extra para «Renderizar con Blender».

Se suman a los seis de IngeTrazo (mate, satinado, brillante, metal, vidrio,
agua) y viajan igual: el nombre del acabado va en el GLB (``extras``) y el
script de Blender (``resources/blender/edwin_materiales_blender.py``) arma el
material completo: metales con su color propio, pinturas con el color que el
usuario pintó, caucho de llanta con labrado por relieve y rin maquinado.

Cada acabado: (etiqueta, grupo, color propio o None, PBR) con
PBR = (rugosidad, metálico, transmisión, ior) para el glTF simple que
entienden otros programas.
"""
from __future__ import annotations

GRUPOS = ("Metales", "Pinturas sobre metal", "Llantas y caucho")

ACABADOS = {
    # ---- Metales sin pintar (tienen su color: se ignora el del modelo)
    "acero":            ("Acero natural (cold rolled)", "Metales",
                         (0.60, 0.61, 0.62), (0.32, 1.0, 0.0, 1.5)),
    "inox_cepillado":   ("Inox cepillado", "Metales",
                         (0.74, 0.75, 0.76), (0.24, 1.0, 0.0, 1.5)),
    "cromo":            ("Cromo / inox espejo", "Metales",
                         (0.86, 0.87, 0.88), (0.03, 1.0, 0.0, 1.5)),
    "galvanizado":      ("Galvanizado", "Metales",
                         (0.70, 0.72, 0.73), (0.35, 1.0, 0.0, 1.5)),
    "aluminio":         ("Aluminio", "Metales",
                         (0.91, 0.92, 0.92), (0.30, 1.0, 0.0, 1.5)),
    "hierro_negro":     ("Lámina hot rolled (hierro negro)", "Metales",
                         (0.16, 0.16, 0.17), (0.55, 0.85, 0.0, 1.5)),
    "oro":              ("Oro", "Metales",
                         (1.00, 0.77, 0.34), (0.18, 1.0, 0.0, 1.5)),
    "bronce":           ("Bronce", "Metales",
                         (0.80, 0.56, 0.32), (0.25, 1.0, 0.0, 1.5)),
    "cobre":            ("Cobre", "Metales",
                         (0.95, 0.64, 0.54), (0.22, 1.0, 0.0, 1.5)),
    # ---- Pinturas: usan el color con que se pintó la cara
    "pintura_mate":        ("Pintura mate", "Pinturas sobre metal",
                            None, (0.75, 0.0, 0.0, 1.5)),
    "pintura_satinada":    ("Pintura satinada", "Pinturas sobre metal",
                            None, (0.40, 0.0, 0.0, 1.5)),
    "pintura_brillante":   ("Pintura brillante / esmalte", "Pinturas sobre metal",
                            None, (0.10, 0.0, 0.0, 1.5)),
    "pintura_texturizada": ("Pintura texturizada (arrugada)", "Pinturas sobre metal",
                            None, (0.60, 0.0, 0.0, 1.5)),
    "pintura_metalizada":  ("Pintura metalizada (escarcha)", "Pinturas sobre metal",
                            None, (0.30, 0.6, 0.0, 1.5)),
    # ---- Llantas y caucho
    "llanta":           ("Llanta (caucho con labrado)", "Llantas y caucho",
                         (0.024, 0.024, 0.026), (0.60, 0.0, 0.0, 1.5)),
    "caucho":           ("Caucho liso", "Llantas y caucho",
                         (0.030, 0.030, 0.032), (0.55, 0.0, 0.0, 1.5)),
    "caucho_usado":     ("Caucho usado (opaco)", "Llantas y caucho",
                         (0.055, 0.054, 0.052), (0.85, 0.0, 0.0, 1.5)),
    "rin_maquinado":    ("Rin de aluminio maquinado", "Llantas y caucho",
                         (0.80, 0.81, 0.82), (0.20, 1.0, 0.0, 1.5)),
}

LABELS = {k: v[0] for k, v in ACABADOS.items()}
PBR = {k: v[3] for k, v in ACABADOS.items()}
COLOR = {k: v[2] for k, v in ACABADOS.items() if v[2] is not None}


def del_grupo(grupo: str) -> list:
    return [k for k, v in ACABADOS.items() if v[1] == grupo]


#: Palabras que adivinan un acabado EDWIN por el nombre (van ANTES que las
#: de IngeTrazo; las demás, como «inox» → metal, se quedan como estaban).
PALABRAS = (
    ("llanta", r"llanta|neum[aá]tic|tire|tyre|pneu"),
    ("caucho", r"caucho|rubber|borracha"),
)
