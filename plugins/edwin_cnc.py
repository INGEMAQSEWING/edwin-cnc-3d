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
from PySide6.QtGui import QAction, QColor, QPainter, QPainterPath, QPen, QVector3D
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


# ---------------------------------------------------------------- escala por 2 puntos
def _objetivos_escala(scene):
    """Qué se escala: lo seleccionado o, sin selección, TODO el modelo.
    Devuelve (grupos, posiciones sueltas, imágenes, texto para el usuario)."""
    from core.group import Group
    from core.image_plane import ImagePlane
    from core.mesh import Edge, Face

    sel = list(scene.selection)
    if sel:
        grupos = [e for e in sel if isinstance(e, Group) and not getattr(e, "locked", False)]
        imagenes = [e for e in sel if isinstance(e, ImagePlane)]
        pos = []
        for e in sel:
            if isinstance(e, Edge):
                pos += [e.a, e.b]
            elif isinstance(e, Face):
                pos += [v.position for v in e.loop]
                for h in e.hole_loops:
                    pos += [v.position for v in h]
        partes = []
        if grupos:
            partes.append(f"{len(grupos)} grupo(s)")
        if pos:
            partes.append("las caras y líneas seleccionadas")
        if imagenes:
            partes.append(f"{len(imagenes)} imagen(es)")
        return grupos, pos, imagenes, "solo lo seleccionado: " + (", ".join(partes) or "nada")
    grupos = [g for g in scene.groups if not getattr(g, "locked", False)]
    pos = [v.position for v in scene.mesh.vertices]
    imagenes = list(scene.image_planes)
    return grupos, pos, imagenes, "TODO el modelo (no hay nada seleccionado)"


def factor_escala(medida_actual, medida_real):
    if medida_actual <= 1e-9 or medida_real <= 0:
        return None
    return medida_real / medida_actual


def aplicar_escala(viewport, centro, factor):
    """Un solo paso de deshacer, con los mismos comandos de la herramienta Escala."""
    from core.history import CompoundCommand, ScaleGroupCommand, ScaleImagePlanesCommand, ScaleVerticesCommand
    grupos, pos, imagenes, _ = _objetivos_escala(viewport.scene)
    cmds = [ScaleGroupCommand(g, centro, factor) for g in grupos]
    if pos:
        cmds.append(ScaleVerticesCommand(pos, centro, factor))
    if imagenes:
        cmds.append(ScaleImagePlanesCommand(imagenes, centro, factor))
    if not cmds:
        return False
    viewport.history.execute(cmds[0] if len(cmds) == 1 else CompoundCommand(cmds))
    viewport.notify_scene_changed()
    return True


class _VentanaEscala(QDialog):
    def __init__(self, parent, medida_actual_mm, que):
        super().__init__(parent)
        self.setWindowTitle("Escala por 2 puntos — EDWIN CNC")
        self.actual = medida_actual_mm
        self.real = QDoubleSpinBox()
        self.real.setRange(0.01, 1e7)
        self.real.setDecimals(2)
        self.real.setSuffix(" mm")
        self.real.setValue(round(medida_actual_mm, 2) or 1.0)
        self.real.selectAll()
        self.real.valueChanged.connect(self._actualizar)
        form = QFormLayout()
        form.addRow("Distancia entre los 2 puntos ahora:", QLabel(f"<b>{medida_actual_mm:.2f} mm</b>"))
        form.addRow("Medida REAL (la de la cinta):", self.real)
        self.info = QLabel()
        self.info.setWordWrap(True)
        aviso = QLabel(f"Se va a escalar {que}.<br>No se escalan: grupos bloqueados, líneas guía, "
                       "textos ni cotas.<br>Se puede deshacer con Ctrl+Z.")
        aviso.setWordWrap(True)
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Escalar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        caja = QVBoxLayout(self)
        caja.addLayout(form)
        caja.addWidget(self.info)
        caja.addWidget(aviso)
        caja.addWidget(botones)
        self._actualizar()

    def _actualizar(self, *_):
        f = factor_escala(self.actual, self.real.value())
        self.info.setText("" if f is None else f"Todo se multiplica por <b>{f:.4f}</b>.")


def _herramienta_escala(app):
    """Herramienta interactiva (con imán a puntos, como la cinta métrica)."""
    from tools.base import Tool

    class EscalaDosPuntos(Tool):
        name = "Escala por 2 puntos"
        description = "Clic en dos puntos de medida conocida y escriba la medida real."

        def __init__(self):
            self.a = None
            self.hover = None

        def _avisar(self, viewport):
            viewport.flash_status(
                "Escala por 2 puntos: clic en el PRIMER punto de una medida que conozca." if self.a is None
                else "Ahora clic en el SEGUNDO punto (Esc cancela).", 60000)

        def on_activate(self, viewport):
            self.a = None
            self._avisar(viewport)

        def on_deactivate(self, viewport):
            self.a = None

        def status_clause(self):
            return "Esc = cancelar"

        def on_hover(self, ctx):
            self.hover = QVector3D(ctx.world)
            ctx.viewport.update()

        def on_click(self, ctx):
            vp = ctx.viewport
            if self.a is None:
                self.a = QVector3D(ctx.world)
                self._avisar(vp)
                return
            b = QVector3D(ctx.world)
            a, self.a = self.a, None
            actual = (b - a).length() * MM
            if actual < 1e-6:
                vp.flash_status("Los dos puntos son el mismo; vuelva a empezar.", 4000)
                return
            if getattr(vp.scene, "edit_group", None) is not None:
                QMessageBox.information(app.window, "Escala por 2 puntos",
                                        "Está dentro de un grupo. Salga del grupo (Esc o clic afuera) "
                                        "y vuelva a usar la herramienta.")
                return
            _, _, _, que = _objetivos_escala(vp.scene)
            v = _VentanaEscala(app.window, actual, que)
            if v.exec() == QDialog.Accepted:
                f = factor_escala(actual, v.real.value())
                if f and abs(f - 1) > 1e-9 and aplicar_escala(vp, a, f):
                    vp.flash_status(f"Escalado ×{f:.4f}. Ahora mide {v.real.value():.2f} mm.", 6000)
            self._avisar(vp)
            vp.update()

        def on_cancel(self, viewport):
            self.a = None
            self._avisar(viewport)
            viewport.update()

        def rubber_band_lines(self):
            if self.a is None or self.hover is None:
                return []
            return [(self.a, self.hover)]

        def value_label(self):
            if self.a is None or self.hover is None:
                return None
            from core.units import fmt_len
            return (fmt_len((self.hover - self.a).length()), (self.a + self.hover) * 0.5)

    return EscalaDosPuntos()


def activar_escala(app):
    herr = getattr(app, "_edwin_escala", None)
    if herr is None:
        herr = app._edwin_escala = _herramienta_escala(app)
    app.viewport.set_active_tool(herr)
    app.viewport.setFocus()


# ---------------------------------------------------------------- foto → DXF
CLAVE_FOTO = "edwin/foto/"
MODOS_FOTO = ["Hoja EDWIN (automático)", "4 marcas grandes (escribir medidas)", "4 esquinas a mano (escribir medidas)"]


def hacer_pdf_marcas(ruta, papel="carta", grandes=False):
    """PDF para imprimir a TAMAÑO REAL: la Hoja de escala EDWIN (1 página) o las
    4 marcas grandes (1 página por marca)."""
    from PySide6.QtCore import QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import QFont, QImage, QPageLayout, QPageSize, QPdfWriter
    from core import edwin_foto_dxf as fd

    w = QPdfWriter(str(ruta))
    w.setResolution(600)
    tam = QPageSize(QPageSize.Letter if papel == "carta" else QPageSize.A4)
    w.setPageLayout(QPageLayout(tam, QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    pag = tam.size(QPageSize.Millimeter)
    pw, ph = pag.width(), pag.height()
    pmm = 600 / 25.4                                  # puntos por mm

    def marca(p, numero, cx, cy, lado):
        m = fd.imagen_marca(numero, 600)
        img = QImage(m.data, m.shape[1], m.shape[0], m.strides[0], QImage.Format_Grayscale8).copy()
        p.drawImage(QRectF((cx - lado / 2) * pmm, (cy - lado / 2) * pmm, lado * pmm, lado * pmm), img)

    def texto(p, x, y, t, tam_pt=9, negrita=False, alto=40):
        f = QFont("Arial", tam_pt)
        f.setBold(negrita)
        p.setFont(f)
        p.drawText(QRectF(x * pmm, y * pmm, (pw - 2 * x) * pmm, alto * pmm), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, t)

    def regla(p, x, y):
        p.setPen(QPen(QColor(0, 0, 0), 0.25 * pmm))
        p.drawLine(QPointF(x * pmm, y * pmm), QPointF((x + 100) * pmm, y * pmm))
        for k in range(0, 101, 5):
            alto = 4 if k % 10 == 0 else 2
            p.drawLine(QPointF((x + k) * pmm, y * pmm), QPointF((x + k) * pmm, (y - alto) * pmm))
        f = QFont("Arial", 6)
        p.setFont(f)
        p.drawText(QPointF((x + 101.5) * pmm, (y + 0.5) * pmm), "100 mm")

    p = QPainter(w)
    try:
        if not grandes:
            cx0, cy0 = (pw - fd.HOJA_ANCHO) / 2, (ph - fd.HOJA_ALTO) / 2
            pos = [(0, 0), (fd.HOJA_ANCHO, 0), (fd.HOJA_ANCHO, fd.HOJA_ALTO), (0, fd.HOJA_ALTO)]
            for i, (x, y) in enumerate(pos):
                marca(p, i, cx0 + x, cy0 + y, fd.HOJA_MARCA)
            # Textos y regla en las franjas ENTRE las marcas, fuera del rectángulo de los
            # centros: lo de adentro es la zona de la pieza y se confundiría con ella.
            m2 = fd.HOJA_MARCA / 2
            texto(p, cx0 + m2 + 3, cy0 - m2, "HOJA DE ESCALA EDWIN CNC", 8, True, 4)
            texto(p, cx0 + m2 + 3, cy0 - m2 + 4,
                  "Imprimir a TAMAÑO REAL (100 %, sin «ajustar a la página») y comprobar que la regla mida 100 mm. "
                  "Pieza en el centro, sin tapar las 4 marcas; foto desde arriba, sin sombra ni reflejo.", 5, False, 8)
            regla(p, (pw - 100) / 2, cy0 + fd.HOJA_ALTO + m2 - 3)
        else:
            lado = min(pw, ph) - 60
            for i in range(4):
                if i:
                    w.newPage()
                marca(p, i, pw / 2, ph / 2, lado)
                p.setPen(QPen(QColor(255, 255, 255), 0.5 * pmm))
                c = QPointF(pw / 2 * pmm, ph / 2 * pmm)
                p.drawLine(c - QPointF(6 * pmm, 0), c + QPointF(6 * pmm, 0))
                p.drawLine(c - QPointF(0, 6 * pmm), c + QPointF(0, 6 * pmm))
                p.setPen(QPen(QColor(0, 0, 0)))
                lugar = ["ARRIBA-IZQUIERDA", "ARRIBA-DERECHA", "ABAJO-DERECHA", "ABAJO-IZQUIERDA"][i]
                texto(p, 15, 8, f"MARCA {i} — va en la esquina {lugar}", 14, True)
                texto(p, 15, ph - 26,
                      "Ponga las 4 marcas en las esquinas de un rectángulo alrededor de la pieza. Mida la distancia "
                      "entre los CENTROS (la cruz): ancho = de la 0 a la 1, alto = de la 0 a la 3. Las dos diagonales "
                      "deben medir lo mismo. Imprimir a tamaño real.", 8)
                regla(p, (pw - 100) / 2, ph - 30)
    finally:
        p.end()
    return ruta


def _qimage(bgr):
    from PySide6.QtGui import QImage
    import numpy as np
    rgb = np.ascontiguousarray(bgr[..., ::-1])
    return QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy()


class _VistaFoto(QWidget):
    """Muestra la foto (o la foto enderezada con el contorno encontrado) y, en el modo
    «4 esquinas a mano», recibe los 4 clics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 420)
        self.img = None            # QImage
        self.piezas = []           # contornos ya en píxeles de self.img
        self.puntos = []           # clics del usuario (píxeles de la foto)
        self.pidiendo = False
        self.al_clic = None
        self._t = None

    def poner(self, qimg, piezas_px=(), puntos=(), pidiendo=False):
        self.img = qimg
        self.piezas = list(piezas_px)
        self.puntos = list(puntos)
        self.pidiendo = pidiendo
        self.setCursor(Qt.CrossCursor if pidiendo else Qt.ArrowCursor)
        self.update()

    def _transformacion(self):
        if self.img is None or self.img.width() == 0:
            return None
        esc = min((self.width() - 10) / self.img.width(), (self.height() - 10) / self.img.height())
        ox = (self.width() - self.img.width() * esc) / 2
        oy = (self.height() - self.img.height() * esc) / 2
        return esc, ox, oy

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(60, 60, 60))
        t = self._transformacion()
        if t is None:
            p.setPen(QColor(230, 230, 230))
            p.drawText(self.rect(), Qt.AlignCenter, "Abra una foto")
            return
        esc, ox, oy = t
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        from PySide6.QtCore import QRectF
        p.drawImage(QRectF(ox, oy, self.img.width() * esc, self.img.height() * esc), self.img)
        p.setRenderHint(QPainter.Antialiasing)
        for k, lazos in enumerate(self.piezas):
            for j, lazo in enumerate(lazos):
                camino = QPainterPath()
                for n, (x, y) in enumerate(lazo):
                    q = QPointF(ox + x * esc, oy + y * esc)
                    camino.moveTo(q) if n == 0 else camino.lineTo(q)
                camino.closeSubpath()
                p.setPen(QPen(QColor(230, 30, 30) if j == 0 else QColor(255, 140, 0), 2.0))
                p.drawPath(camino)
        for n, (x, y) in enumerate(self.puntos):
            q = QPointF(ox + x * esc, oy + y * esc)
            p.setPen(QPen(QColor(255, 220, 0), 2))
            p.drawEllipse(q, 7, 7)
            p.drawText(q + QPointF(9, -9), str(n + 1))
        if len(self.puntos) >= 2:
            p.setPen(QPen(QColor(255, 220, 0), 1, Qt.DashLine))
            for a, b in zip(self.puntos, self.puntos[1:] + (self.puntos[:1] if len(self.puntos) == 4 else [])):
                p.drawLine(QPointF(ox + a[0] * esc, oy + a[1] * esc), QPointF(ox + b[0] * esc, oy + b[1] * esc))

    def mousePressEvent(self, ev):
        t = self._transformacion()
        if not self.pidiendo or t is None or ev.button() != Qt.LeftButton:
            return
        esc, ox, oy = t
        x = (ev.position().x() - ox) / esc
        y = (ev.position().y() - oy) / esc
        if 0 <= x < self.img.width() and 0 <= y < self.img.height() and self.al_clic:
            self.al_clic(x, y)


class _VentanaFoto(QDialog):
    def __init__(self, app):
        super().__init__(app.window)
        from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QSlider
        self.app = app
        self.setWindowTitle("Foto → plano → DXF — EDWIN CNC")
        self.resize(980, 720)
        cfg = QSettings()
        self.foto = None
        self.ruta_foto = ""
        self.enderezado = None
        self.piezas = []
        self.esquinas = []
        self.lado_marca = None

        # --- columna de ajustes
        self.modo = QComboBox()
        self.modo.addItems(MODOS_FOTO)
        self.modo.setCurrentIndex(int(cfg.value(CLAVE_FOTO + "modo", 0)))
        self.ancho = QDoubleSpinBox()
        self.alto = QDoubleSpinBox()
        for w_, clave, v in ((self.ancho, "ancho", 1000.0), (self.alto, "alto", 1000.0)):
            w_.setRange(10, 20000)
            w_.setDecimals(1)
            w_.setSuffix(" mm")
            w_.setValue(float(cfg.value(CLAVE_FOTO + clave, v)))
        self.lado_grande = QDoubleSpinBox()
        self.lado_grande.setRange(20, 1000)
        self.lado_grande.setDecimals(1)
        self.lado_grande.setSuffix(" mm")
        self.lado_grande.setValue(float(cfg.value(CLAVE_FOTO + "lado", 155.9)))
        self.auto = QCheckBox("Sensibilidad automática")
        self.auto.setChecked(True)
        self.umbral = QSlider(Qt.Horizontal)
        self.umbral.setRange(1, 254)
        self.umbral.setValue(128)
        self.umbral.setEnabled(False)
        self.oscura = QCheckBox("La pieza es más OSCURA que el fondo")
        self.oscura.setChecked(cfg.value(CLAVE_FOTO + "oscura", "true") in (True, "true"))
        self.suave = QDoubleSpinBox()
        self.suave.setRange(0.05, 5)
        self.suave.setDecimals(2)
        self.suave.setSingleStep(0.1)
        self.suave.setSuffix(" mm")
        self.suave.setValue(float(cfg.value(CLAVE_FOTO + "suave", 0.3)))
        self.minimo = QDoubleSpinBox()
        self.minimo.setRange(0, 100000)
        self.minimo.setDecimals(0)
        self.minimo.setSuffix(" mm²")
        self.minimo.setValue(float(cfg.value(CLAVE_FOTO + "minimo", 20)))
        self.una = QCheckBox("Solo la pieza más grande")
        self.una.setChecked(cfg.value(CLAVE_FOTO + "una", "true") in (True, "true"))

        form = QFormLayout()
        form.addRow("Cómo se da la escala:", self.modo)
        form.addRow("Ancho (de centro a centro):", self.ancho)
        form.addRow("Alto (de centro a centro):", self.alto)
        form.addRow("Lado de cada marca impresa:", self.lado_grande)
        form.addRow(self.auto)
        form.addRow("Sensibilidad a mano:", self.umbral)
        form.addRow(self.oscura)
        form.addRow("Suavizar el contorno:", self.suave)
        form.addRow("Ignorar manchas menores de:", self.minimo)
        form.addRow(self.una)
        self._fila_ancho = (form, self.ancho)

        b_abrir = QPushButton("📷 Abrir foto…")
        b_hoja = QPushButton("🖨 Hoja de marcas para imprimir…")
        self.b_rehacer = QPushButton("Volver a marcar las 4 esquinas")
        self.b_dxf = QPushButton("Guardar DXF…")
        self.b_modelo = QPushButton("Poner en el modelo 3D")
        b_cerrar = QPushButton("Cerrar")
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setMinimumWidth(300)

        izq = QVBoxLayout()
        izq.addWidget(b_abrir)
        izq.addWidget(b_hoja)
        izq.addLayout(form)
        izq.addWidget(self.b_rehacer)
        izq.addWidget(self.info, 1)
        izq.addWidget(self.b_dxf)
        izq.addWidget(self.b_modelo)
        izq.addWidget(b_cerrar)
        self.vista = _VistaFoto()
        self.vista.al_clic = self._clic_esquina
        fila = QHBoxLayout(self)
        caja_izq = QWidget()
        caja_izq.setLayout(izq)
        caja_izq.setMaximumWidth(380)
        fila.addWidget(caja_izq)
        fila.addWidget(self.vista, 1)

        b_abrir.clicked.connect(self._abrir)
        b_hoja.clicked.connect(self._hoja)
        b_cerrar.clicked.connect(self.reject)
        self.b_dxf.clicked.connect(self._guardar)
        self.b_modelo.clicked.connect(self._al_modelo)
        self.b_rehacer.clicked.connect(self._rehacer_esquinas)
        self.modo.currentIndexChanged.connect(self._cambio_modo)
        for w_ in (self.ancho, self.alto, self.lado_grande):
            w_.editingFinished.connect(self._enderezar)
        self.auto.toggled.connect(lambda on: (self.umbral.setEnabled(not on), self._buscar()))
        self.umbral.sliderReleased.connect(self._buscar)
        self.umbral.valueChanged.connect(lambda _v: None if self.umbral.isSliderDown() else self._buscar())
        for w_ in (self.oscura, self.una):
            w_.toggled.connect(self._buscar)
        for w_ in (self.suave, self.minimo):
            w_.editingFinished.connect(self._buscar)
        self._cambio_modo()

    # ---------------------------------------------------------- pasos
    def _ajustes(self):
        from core import edwin_foto_dxf as fd
        return fd.Ajustes(umbral=None if self.auto.isChecked() else self.umbral.value(),
                          pieza_oscura=self.oscura.isChecked(), suavizado_mm=self.suave.value(),
                          minimo_mm2=self.minimo.value(), solo_la_mayor=self.una.isChecked())

    def _cambio_modo(self, *_):
        m = self.modo.currentIndex()
        for w_ in (self.ancho, self.alto):
            w_.setEnabled(m != 0)
        self.lado_grande.setEnabled(m == 1)
        self.b_rehacer.setVisible(m == 2)
        self.esquinas = []
        self._enderezar()

    def _abrir(self):
        from core import edwin_foto_dxf as fd
        cfg = QSettings()
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir foto", str(cfg.value(CLAVE_FOTO + "carpeta", "")),
                                              "Fotos (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)")
        if not ruta:
            return
        cfg.setValue(CLAVE_FOTO + "carpeta", str(Path(ruta).parent))
        try:
            self.foto = fd.leer_foto(ruta)
        except Exception as e:            # noqa: BLE001
            QMessageBox.warning(self, "Foto → DXF", str(e))
            return
        self.ruta_foto = ruta
        self.esquinas = []
        self._enderezar()

    def _hoja(self):
        from PySide6.QtWidgets import QInputDialog
        opciones = ["Hoja de escala EDWIN — papel CARTA", "Hoja de escala EDWIN — papel A4",
                    "4 marcas grandes (piezas grandes) — CARTA", "4 marcas grandes (piezas grandes) — A4"]
        elegida, ok = QInputDialog.getItem(self, "Hoja de marcas", "¿Qué quiere imprimir?", opciones, 0, False)
        if not ok:
            return
        k = opciones.index(elegida)
        nombre = ["hoja-escala-EDWIN-carta.pdf", "hoja-escala-EDWIN-A4.pdf",
                  "4-marcas-grandes-EDWIN-carta.pdf", "4-marcas-grandes-EDWIN-A4.pdf"][k]
        cfg = QSettings()
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar la hoja (PDF)",
                                              str(Path(str(cfg.value(CLAVE_FOTO + "carpeta", Path.home()))) / nombre),
                                              "PDF (*.pdf)")
        if not ruta:
            return
        hacer_pdf_marcas(ruta, "carta" if k % 2 == 0 else "a4", grandes=k >= 2)
        if k >= 2:
            from core import edwin_foto_dxf as fd   # noqa: F401
            lado = min((215.9, 279.4) if k % 2 == 0 else (210.0, 297.0)) - 60
            self.lado_grande.setValue(lado)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))

    def _rehacer_esquinas(self):
        self.esquinas = []
        self._enderezar()

    def _clic_esquina(self, x, y):
        if self.modo.currentIndex() != 2 or len(self.esquinas) >= 4:
            return
        self.esquinas.append((x, y))
        self._enderezar()

    def _enderezar(self, *_):
        from core import edwin_foto_dxf as fd
        self.enderezado, self.piezas = None, []
        if self.foto is None:
            self.vista.poner(None)
            self._mostrar_info("Abra una foto de la pieza (botón 📷).")
            return
        m = self.modo.currentIndex()
        try:
            if m == 2:
                if len(self.esquinas) < 4:
                    nombres = ["ARRIBA-IZQUIERDA", "ARRIBA-DERECHA", "ABAJO-DERECHA", "ABAJO-IZQUIERDA"]
                    self.vista.poner(_qimage(self.foto), puntos=self.esquinas, pidiendo=True)
                    self._mostrar_info(f"Haga clic en la esquina {len(self.esquinas) + 1} de 4: "
                                       f"<b>{nombres[len(self.esquinas)]}</b> del rectángulo de medida conocida "
                                       "(por ejemplo, las esquinas de la lámina).")
                    return
                self.lado_marca = None
                ordenadas, reordenadas = fd.ordenar_esquinas(self.esquinas)
                self._aviso_orden = ("Las esquinas no estaban en el orden pedido; se ordenaron solas "
                                     "(empezando por la primera que marcó)." if reordenadas else "")
                self.enderezado = fd.enderezar(self.foto, ordenadas, self.ancho.value(), self.alto.value())
            else:
                centros, esquinas = fd.buscar_marcas(self.foto)
                faltan = [i for i in range(4) if i not in centros]
                if faltan:
                    raise ValueError("No se encontraron todas las marcas (faltan: " + ", ".join(map(str, faltan)) +
                                     "). Que se vean las 4 completas, sin reflejo, sin sombra encima y la foto enfocada.")
                if m == 0:
                    ancho, alto, lado = fd.HOJA_ANCHO, fd.HOJA_ALTO, fd.HOJA_MARCA
                else:
                    ancho, alto, lado = self.ancho.value(), self.alto.value(), self.lado_grande.value()
                self.lado_marca = lado
                # 16 esquinas solo con la hoja (marcas alineadas); marcas sueltas: los 4 centros
                self.enderezado = fd.enderezar(self.foto, [centros[i] for i in range(4)], ancho, alto,
                                               esquinas_marcas=esquinas if m == 0 else None, lado_marca=lado)
        except Exception as e:            # noqa: BLE001
            self.vista.poner(_qimage(self.foto))
            self._mostrar_info(f"<b style='color:#c0392b'>{e}</b>")
            return
        self._buscar()

    def _buscar(self, *_):
        from core import edwin_foto_dxf as fd
        e = self.enderezado
        if e is None:
            self._botones()
            return
        try:
            self.piezas = fd.contornos(e, self._ajustes(), self.lado_marca)
        except Exception as err:          # noqa: BLE001
            self.piezas = []
            self._mostrar_info(f"<b style='color:#c0392b'>{err}</b>")
            return
        # a píxeles de la foto enderezada, para dibujarlos encima
        def px(pt):
            return ((pt[0] - e.origen_mm[0]) * e.ppmm, (-pt[1] - e.origen_mm[1]) * e.ppmm)
        dibujo = [[[px(q) for q in lazo] for lazo in [p.contorno] + list(p.huecos)] for p in self.piezas]
        self.vista.poner(_qimage(e.imagen), dibujo)
        if not self.piezas:
            self._mostrar_info("No se encontró ninguna pieza. Pruebe quitar «Sensibilidad automática» y mover la barra, "
                               "o cambiar «La pieza es más oscura que el fondo».")
            return
        lineas = []
        for k, p in enumerate(self.piezas, start=1):
            t = f"<b>Pieza {k}:</b> {p.ancho:.1f} × {p.alto:.1f} mm"
            if p.huecos:
                t += f", {len(p.huecos)} hueco(s)"
            if getattr(p, "toca_borde", False):
                t += (" <b style='color:#c0392b'>¡toca el borde o se mete en una marca: "
                      "puede estar recortada!</b>")
            lineas.append(t)
        if e.error_mm is not None:
            lineas.append(f"Calce de las marcas: ±{e.error_mm:.2f} mm.")
        if self.modo.currentIndex() == 2 and getattr(self, "_aviso_orden", ""):
            lineas.append(f"<i>{self._aviso_orden}</i>")
        lineas.append("Rojo = contorno de CORTE, naranja = huecos. Revise que la medida coincida con la cinta "
                      "antes de cortar.")
        self._mostrar_info("<br>".join(lineas))

    def _mostrar_info(self, html):
        self.info.setText(html)
        self._botones()

    def _botones(self):
        hay = bool(self.piezas)
        self.b_dxf.setEnabled(hay)
        self.b_modelo.setEnabled(hay)

    def _guardar_ajustes(self):
        cfg = QSettings()
        cfg.setValue(CLAVE_FOTO + "modo", self.modo.currentIndex())
        cfg.setValue(CLAVE_FOTO + "ancho", self.ancho.value())
        cfg.setValue(CLAVE_FOTO + "alto", self.alto.value())
        cfg.setValue(CLAVE_FOTO + "lado", self.lado_grande.value())
        cfg.setValue(CLAVE_FOTO + "oscura", self.oscura.isChecked())
        cfg.setValue(CLAVE_FOTO + "suave", self.suave.value())
        cfg.setValue(CLAVE_FOTO + "minimo", self.minimo.value())
        cfg.setValue(CLAVE_FOTO + "una", self.una.isChecked())

    def _guardar(self):
        from core import edwin_foto_dxf as fd
        cfg = QSettings()
        base = Path(self.ruta_foto).stem if self.ruta_foto else "pieza"
        carpeta = str(cfg.value(CLAVE_CARPETA, "") or Path(self.ruta_foto).parent)
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar DXF", str(Path(carpeta) / f"{base}.dxf"), "DXF (*.dxf)")
        if not ruta:
            return
        cfg.setValue(CLAVE_CARPETA, str(Path(ruta).parent))
        self._guardar_ajustes()
        try:
            fd.guardar_dxf(self.piezas, ruta, base.upper()[:30])
        except Exception as e:            # noqa: BLE001
            QMessageBox.warning(self, "Guardar DXF", f"No se pudo guardar:\n{e}")
            return
        self.app.viewport.flash_status(f"DXF guardado: {ruta}", 6000)
        QMessageBox.information(self, "Guardar DXF", f"Listo. Ábralo en EDWIN CNC CAD-CAM:\n{ruta}")

    def _al_modelo(self):
        self._guardar_ajustes()
        piezas = list(self.piezas)
        nombre = Path(self.ruta_foto).stem if self.ruta_foto else "Pieza"
        from core.history import SnapshotImport
        n = {}

        def mutar(scene):
            n["g"] = grupo_desde_piezas(piezas, f"{nombre} (desde foto)")
            scene.groups.append(n["g"])

        self.app.viewport.history.execute(SnapshotImport(mutar))
        try:
            self.app.scene.selection.clear()
            self.app.scene.selection.add(n["g"])
        except Exception:                 # noqa: BLE001
            pass
        self.app.viewport.notify_scene_changed()
        try:
            self.app.window._on_zoom_extents()
        except Exception:                 # noqa: BLE001
            pass
        self.accept()

    def reject(self):
        self._guardar_ajustes()
        super().reject()


def grupo_desde_piezas(piezas, nombre):
    """Las piezas como caras planas en el piso (Z = 0), en un grupo."""
    from core.group import Group
    from core.mesh import Mesh
    g = Group(Mesh(), name=nombre)
    x0 = min(x for p in piezas for x, _ in p.contorno)
    y0 = min(y for p in piezas for _, y in p.contorno)
    for p in piezas:
        def q(pt):
            return QVector3D((pt[0] - x0) / MM, (pt[1] - y0) / MM, 0.0)
        g.mesh.add_face([q(pt) for pt in p.contorno], [[q(pt) for pt in h] for h in p.huecos])
    return g


def abrir_foto_dxf(app):
    try:
        import cv2  # noqa: F401
    except Exception:                     # noqa: BLE001
        QMessageBox.warning(app.window, "Foto → DXF",
                            "Falta la librería de fotos (OpenCV) en esta instalación. Reinstale EDWIN CNC 3D.")
        return
    _VentanaFoto(app).exec()


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
        act3 = sub.addAction("Escala por 2 puntos")
        act3.setStatusTip("Clic en dos puntos de medida conocida y escriba la medida real: todo queda a escala.")
        act3.triggered.connect(lambda _c=False: activar_escala(app))
        act4 = sub.addAction("Foto → plano → DXF…")
        act4.setStatusTip("Calca una pieza plana desde una foto (con la hoja de marcas) y la guarda en DXF a escala real.")
        act4.triggered.connect(lambda _c=False: abrir_foto_dxf(app))

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
    accion_e = QAction("Escala 2 puntos", barra)
    accion_e.setToolTip("Poner a escala real: clic en dos puntos y escribir la medida")
    accion_e.triggered.connect(lambda _c=False: activar_escala(app))
    barra.addAction(accion_e)
    accion_f = QAction("Foto → DXF", barra)
    accion_f.setToolTip("Calcar una pieza plana desde una foto y guardarla en DXF a escala real")
    accion_f.triggered.connect(lambda _c=False: abrir_foto_dxf(app))
    barra.addAction(accion_f)
    win.addToolBar(barra)
    try:
        app.restore_toolbar_layout()
    except Exception:                     # noqa: BLE001
        pass
