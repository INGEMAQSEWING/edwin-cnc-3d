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
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import edwin_desdoblar as ed
from core import edwin_helicoidal as eh

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


# ---------------------------------------------------------------- helicoidal
CLAVE_HELI = "edwin/helicoidal/"


class _VentanaHelicoidal(QDialog):
    """Pide las medidas del sinfín y dibuja la helicoidal como un grupo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Helicoidal (sinfín) — EDWIN CNC")
        cfg = QSettings()
        d = eh.Medidas()

        def num(clave, valor, minimo, maximo, decimales=1, sufijo=" mm"):
            w = QDoubleSpinBox()
            w.setRange(minimo, maximo)
            w.setDecimals(decimales)
            w.setSuffix(sufijo)
            w.setValue(float(cfg.value(CLAVE_HELI + clave, valor)))
            w.valueChanged.connect(self._actualizar)
            return w

        def entero(clave, valor, minimo, maximo):
            w = QSpinBox()
            w.setRange(minimo, maximo)
            w.setValue(int(cfg.value(CLAVE_HELI + clave, valor)))
            w.valueChanged.connect(self._actualizar)
            return w

        self.exterior = num("exterior", d.exterior, 1, 10000)
        self.interior = num("interior", d.interior, 1, 10000)
        self.paso = num("paso", d.paso, 1, 20000)
        self.vueltas = num("vueltas", d.vueltas, 0.1, 500, 2, "")
        self.divisiones = entero("divisiones", d.divisiones, 6, 720)
        self.ancho = entero("ancho", d.ancho, 1, 50)
        self.sentido = QComboBox()
        self.sentido.addItems(["Derecha", "Izquierda"])
        self.sentido.setCurrentIndex(int(cfg.value(CLAVE_HELI + "sentido", 0)))
        self.sentido.currentIndexChanged.connect(self._actualizar)

        form = QFormLayout()
        form.addRow("Diámetro de afuera:", self.exterior)
        form.addRow("Diámetro del eje (tubo):", self.interior)
        form.addRow("Paso (lo que sube en una vuelta):", self.paso)
        form.addRow("Número de vueltas:", self.vueltas)
        form.addRow("Tramos por vuelta:", self.divisiones)
        form.addRow("Tramos a lo ancho:", self.ancho)
        form.addRow("Sentido:", self.sentido)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Dibujar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        self._ok = botones.button(QDialogButtonBox.Ok)

        caja = QVBoxLayout(self)
        caja.addLayout(form)
        caja.addWidget(self.info)
        caja.addWidget(botones)
        self._actualizar()

    def medidas(self):
        return eh.Medidas(
            exterior=self.exterior.value(), interior=self.interior.value(),
            paso=self.paso.value(), vueltas=self.vueltas.value(),
            divisiones=self.divisiones.value(), ancho=self.ancho.value(),
            derecha=self.sentido.currentIndex() == 0)

    def _actualizar(self, *_):
        m = self.medidas()
        err = eh.problema(m)
        self._ok.setEnabled(err is None)
        if err:
            self.info.setText("<b style='color:#c0392b'>" + err + "</b>")
            return
        a = eh.arandela(m)
        tramo = 360.0 / m.divisiones
        self.info.setText(
            f"Cada tramo abarca {tramo:.1f}°. Para cortar, entre al grupo (doble clic), "
            "seleccione los tramos que quiera y use «Desdoblar caras».<br><br>"
            "<i>Dato de taller (una vuelta como arandela abierta):</i><br>"
            f"radio de adentro {a['radio_interior']:.1f} mm · radio de afuera {a['radio_exterior']:.1f} mm · "
            f"ancho {a['ancho']:.1f} mm · abertura {a['angulo_abertura']:.1f}°")

    def _aceptar(self):
        cfg = QSettings()
        for clave, w in (("exterior", self.exterior), ("interior", self.interior), ("paso", self.paso),
                         ("vueltas", self.vueltas), ("divisiones", self.divisiones), ("ancho", self.ancho)):
            cfg.setValue(CLAVE_HELI + clave, w.value())
        cfg.setValue(CLAVE_HELI + "sentido", self.sentido.currentIndex())
        self.accept()


def _nombre_helicoidal(m):
    f = lambda x: f"{x:g}"   # noqa: E731
    return f"Helicoidal Ø{f(m.exterior)} eje {f(m.interior)} paso {f(m.paso)} x {f(m.vueltas)} vueltas"


def construir_grupo_helicoidal(m):
    """Grupo con la helicoidal (en metros, como guarda el programa)."""
    from PySide6.QtGui import QVector3D
    from core.group import Group
    from core.mesh import Mesh

    vertices, triangulos, diagonales = eh.construir(m)
    pts = [QVector3D(x / MM, y / MM, z / MM) for x, y, z in vertices]
    g = Group(Mesh(), name=_nombre_helicoidal(m))
    for t in triangulos:
        g.mesh.add_face([pts[i] for i in t])
    # La diagonal de cada tramo, suave: un clic toma el tramo entero.
    for a, b in diagonales:
        va, vb = g.mesh.vertex_at(pts[a]), g.mesh.vertex_at(pts[b])
        e = g.mesh.find_edge(va, vb) if va is not None and vb is not None else None
        if e is not None:
            e.soft = True
    return g


def crear_helicoidal(app):
    ventana = _VentanaHelicoidal(app.window)
    if ventana.exec() != QDialog.Accepted:
        return
    m = ventana.medidas()
    from core.history import SnapshotImport
    nuevo = {}

    def mutar(scene):
        g = construir_grupo_helicoidal(m)
        scene.groups.append(g)
        nuevo["g"] = g

    app.viewport.history.execute(SnapshotImport(mutar))
    try:
        app.scene.selection.clear()
        app.scene.selection.add(nuevo["g"])
    except Exception:                     # noqa: BLE001
        pass
    app.viewport.notify_scene_changed()
    try:
        app.window._on_zoom_extents()
    except Exception:                     # noqa: BLE001
        pass
    try:
        app.viewport.flash_status("Helicoidal dibujada. Doble clic para entrar y escoger los tramos a desdoblar.", 6000)
    except Exception:                     # noqa: BLE001
        pass


def setup(app):
    hacer = lambda: desdoblar_seleccion(app)   # noqa: E731
    sub = app.add_menu("EDWIN CNC")
    if sub is not None:
        act = sub.addAction("Desdoblar caras seleccionadas…")
        act.setStatusTip("Acuesta en plano las caras seleccionadas y guarda el DXF para cortar.")
        act.triggered.connect(lambda _c=False: hacer())
        act2 = sub.addAction("Helicoidal (sinfín)…")
        act2.setStatusTip("Dibuja una helicoidal de sinfín con sus medidas para luego desdoblarla por tramos.")
        act2.triggered.connect(lambda _c=False: crear_helicoidal(app))

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
    accion_h = QAction("Helicoidal", barra)
    accion_h.setToolTip("Dibujar una helicoidal de sinfín con sus medidas")
    accion_h.triggered.connect(lambda _c=False: crear_helicoidal(app))
    barra.addAction(accion_h)
    win.addToolBar(barra)
    try:
        app.restore_toolbar_layout()
    except Exception:                     # noqa: BLE001
        pass
