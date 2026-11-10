# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""EDWIN CNC ▸ Desdoblar caras seleccionadas.

Como «Unwrap and Flatten Faces» de SketchUp: el usuario selecciona las caras que
quiere cortar (toda la tolva, media, una pestaña...) y el programa las acuesta en
plano y guarda un DXF en milímetros con las capas del EDWIN CNC CAD-CAM:
CORTE (contorno), MARCADO (dobleces) y REFERENCIA (textos).

El cálculo está en core/edwin_desdoblar.py (sin Qt, con sus pruebas en
edwin/pruebas/).  Aquí solo se lee la selección y se muestra la ventana.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import edwin_desdoblar as ed

MM = 1000.0          # el modelo guarda metros; el plano sale en milímetros
CLAVE_CARPETA = "edwin/carpeta_dxf"
CLAVE_ANGULO = "edwin/angulo_marca"


# ---------------------------------------------------------------- selección -> malla
def _malla_de_seleccion(scene):
    """Convierte las caras seleccionadas (sueltas o dentro de grupos) en una Malla en mm."""
    from core.group import Group, iter_placements
    from core.mesh import Face

    vertices, caras, huecos = [], [], {}
    indice = {}

    def idx(v, colocacion, matriz):
        clave = (id(v), colocacion)
        if clave not in indice:
            p = v.position if matriz is None else matriz.map(v.position)
            indice[clave] = len(vertices)
            vertices.append((p.x() * MM, p.y() * MM, p.z() * MM))
        return indice[clave]

    def agregar(face, colocacion, matriz):
        if len(face.loop) < 3:
            return
        n = len(caras)
        caras.append([idx(v, colocacion, matriz) for v in face.loop])
        hs = [[idx(v, colocacion, matriz) for v in h] for h in face.hole_loops if len(h) >= 3]
        if hs:
            huecos[n] = hs

    vistas = set()
    for ent in list(scene.selection):
        if isinstance(ent, Face):
            if id(ent) not in vistas:
                vistas.add(id(ent))
                agregar(ent, 0, None)
        elif isinstance(ent, Group):
            for k, (g, m) in enumerate(iter_placements(ent), start=1):
                col = (id(ent), k)
                for face in g.mesh.faces:
                    agregar(face, col, m)
    return ed.Malla(vertices, caras, huecos)


# ---------------------------------------------------------------- vista previa
class _Vista(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.piezas = []
        self.setMinimumSize(520, 300)

    def poner(self, piezas):
        self.piezas = piezas
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        if not self.piezas:
            p.drawText(self.rect(), Qt.AlignCenter, "Nada para mostrar")
            return
        pts = [q for pz in self.piezas for l in pz.contornos for q in ed._puntos_arco(l)]
        x0, x1 = min(q[0] for q in pts), max(q[0] for q in pts)
        y0, y1 = min(q[1] for q in pts), max(q[1] for q in pts)
        m = 16
        esc = min((self.width() - 2 * m) / max(x1 - x0, 1e-9), (self.height() - 2 * m) / max(y1 - y0, 1e-9))
        ox = (self.width() - (x1 - x0) * esc) / 2
        oy = (self.height() - (y1 - y0) * esc) / 2

        def a_pantalla(x, y):
            return QPointF(ox + (x - x0) * esc, self.height() - (oy + (y - y0) * esc))

        p.setPen(QPen(pal.text().color(), 1.6))
        for pz in self.piezas:
            for l in pz.contornos:
                camino = QPainterPath()
                for k, (x, y, bl) in enumerate(l):
                    if k == 0:
                        camino.moveTo(a_pantalla(x, y))
                    x2, y2, _ = l[(k + 1) % len(l)]
                    if bl:
                        for t in [i / 16 for i in range(1, 17)]:
                            camino.lineTo(a_pantalla(*ed._punto_en_arco((x, y), (x2, y2), bl, t)))
                    else:
                        camino.lineTo(a_pantalla(x2, y2))
                p.drawPath(camino)
        p.setPen(QPen(QColor(0, 160, 70), 1.2, Qt.DashLine))
        for pz in self.piezas:
            for d in pz.dobleces:
                p.drawLine(a_pantalla(*d.a), a_pantalla(*d.b))


# ---------------------------------------------------------------- ventana
class _Ventana(QDialog):
    def __init__(self, viewport, malla, nombre):
        super().__init__(viewport.window() if viewport is not None else None)
        self.setWindowTitle("Desdoblar caras — EDWIN CNC")
        self.malla = malla
        self.piezas = []
        cfg = QSettings()

        lay = QVBoxLayout(self)
        intro = QLabel(
            f"<b>{len(malla.caras)} cara(s) seleccionada(s).</b> "
            "El plano se ve por la cara de AFUERA, en milímetros y con la medida tal cual "
            "está dibujada (sin compensar espesor).")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QFormLayout()
        self.nombre = QLineEdit(nombre)
        form.addRow("Nombre de la pieza:", self.nombre)
        self.angulo = QDoubleSpinBox()
        self.angulo.setRange(0.5, 179.0)
        self.angulo.setDecimals(1)
        self.angulo.setSuffix(" °")
        try:
            self.angulo.setValue(float(cfg.value(CLAVE_ANGULO, 15.0)))
        except (TypeError, ValueError):
            self.angulo.setValue(15.0)
        self.angulo.setToolTip(
            "Las aristas que doblan este ángulo o más se marcan como DOBLEZ (capa MARCADO).\n"
            "Las de menos ángulo se toman como curva suave (por ejemplo un cono que se rola).")
        form.addRow("Marcar dobleces desde:", self.angulo)
        lay.addLayout(form)

        self.vista = _Vista(self)
        lay.addWidget(self.vista, 1)
        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.resumen.setTextFormat(Qt.RichText)
        lay.addWidget(self.resumen)

        botones = QDialogButtonBox()
        self.guardar = botones.addButton("Guardar DXF…", QDialogButtonBox.AcceptRole)
        botones.addButton("Cerrar", QDialogButtonBox.RejectRole)
        botones.accepted.connect(self._guardar)
        botones.rejected.connect(self.reject)
        lay.addWidget(botones)

        self.angulo.valueChanged.connect(self._calcular)
        self.resize(760, 620)
        self._calcular()

    def _calcular(self):
        try:
            self.piezas = ed.desdoblar(self.malla, angulo_marca=self.angulo.value())
        except Exception as exc:          # noqa: BLE001 - se muestra al usuario
            self.piezas = []
            self.resumen.setText(f"<span style='color:#c0392b'>No se pudo desdoblar: {exc}</span>")
            self.vista.poner([])
            self.guardar.setEnabled(False)
            return
        self.vista.poner(self.piezas)
        filas = []
        for n, pz in enumerate(self.piezas, 1):
            ancho, alto = ed.medidas(pz)
            dob = f", {len(pz.dobleces)} doblez(ces)" if pz.dobleces else ""
            filas.append(f"<b>Pieza {n}:</b> lámina de {ancho:.1f} × {alto:.1f} mm, "
                         f"área {pz.area / 1e6:.3f} m²{dob}")
            for a in dict.fromkeys(pz.avisos):
                filas.append(f"&nbsp;&nbsp;<span style='color:#d35400'>⚠ {a}</span>")
        self.resumen.setText("<br>".join(filas))
        self.guardar.setEnabled(bool(self.piezas))

    def _guardar(self):
        cfg = QSettings()
        cfg.setValue(CLAVE_ANGULO, self.angulo.value())
        carpeta = str(cfg.value(CLAVE_CARPETA, str(Path.home() / "Documents")))
        nombre = (self.nombre.text().strip() or "PIEZA")
        archivo = "".join(c if c.isalnum() or c in " -_" else "-" for c in nombre).strip() or "pieza"
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar plano desdoblado",
                                              str(Path(carpeta) / f"{archivo}-desdoblado.dxf"),
                                              "Dibujo DXF (*.dxf)")
        if not ruta:
            return
        if not ruta.lower().endswith(".dxf"):
            ruta += ".dxf"
        try:
            ed.guardar_dxf(self.piezas, ruta, nombre.upper())
        except Exception as exc:          # noqa: BLE001
            QMessageBox.warning(self, "EDWIN CNC", f"No se pudo guardar el DXF:\n{exc}")
            return
        cfg.setValue(CLAVE_CARPETA, str(Path(ruta).parent))
        QMessageBox.information(
            self, "EDWIN CNC",
            f"Plano guardado:\n{ruta}\n\nÁbralo en EDWIN CNC CAD-CAM para generar el código G.")
        self.accept()


# ---------------------------------------------------------------- extensión
def desdoblar_seleccion(app):
    malla = _malla_de_seleccion(app.scene)
    if not malla.caras:
        QMessageBox.information(
            app.window, "Desdoblar caras — EDWIN CNC",
            "Primero seleccione las caras que quiere desdoblar:\n\n"
            "• Clic en una cara para seleccionarla.\n"
            "• Ctrl + clic para agregar más caras.\n"
            "• También puede seleccionar un grupo entero.\n\n"
            "Después vuelva a darle a «Desdoblar caras».")
        return
    try:
        ruta = getattr(app.window, "_current_path", None)
        titulo = Path(ruta).stem if ruta else ""
    except Exception:                     # noqa: BLE001
        titulo = ""
    _Ventana(app.viewport, malla, titulo or "PIEZA").exec()


def setup(app):
    hacer = lambda: desdoblar_seleccion(app)   # noqa: E731
    sub = app.add_menu("EDWIN CNC")
    if sub is not None:
        act = sub.addAction("Desdoblar caras seleccionadas…")
        act.setStatusTip("Acuesta en plano las caras seleccionadas y guarda el DXF para cortar.")
        act.triggered.connect(lambda _c=False: hacer())

    def menu_contextual(menu, seleccion):
        from core.mesh import Face
        from core.group import Group
        if any(isinstance(e, (Face, Group)) for e in seleccion):
            menu.addAction("Desdoblar caras (EDWIN CNC)…", lambda: QTimer.singleShot(0, hacer))
    app.add_context_menu(menu_contextual)

    # Barra propia con el botón, como en SketchUp.
    win = app.window
    barra = QToolBar("EDWIN CNC", win)
    barra.setObjectName("edwin_cnc_barra")
    barra.setToolButtonStyle(Qt.ToolButtonTextOnly)
    accion = QAction("Desdoblar caras", barra)
    accion.setToolTip("Desdoblar caras seleccionadas a plano (DXF para el CAD-CAM)")
    accion.triggered.connect(lambda _c=False: hacer())
    barra.addAction(accion)
    win.addToolBar(barra)
    try:
        app.restore_toolbar_layout()
    except Exception:                     # noqa: BLE001
        pass
