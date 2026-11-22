# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 EDWIN CNC.
"""Materiales EDWIN dentro de Blender (lo llama render_scene.py).

- ``aplicar(mat, bsdf, clave, motor)``: arma el material de un acabado EDWIN
  (core/edwin_materiales.py): metales con su color, pinturas con el color del
  modelo, caucho, llanta con labrado y rin maquinado. Todo es procedural
  (nodos de ruido/voronoi), no necesita archivos de textura.
- ``preparar_ejes(objetos)``: la llanta y el rin necesitan saber dónde está el
  eje de cada rueda; separa cada rueda en su propio objeto y le pone un
  «Empty» en el centro con Z por el eje.
- ``bordes_suaves(radio)``: con Cycles, todos los materiales redondean sus
  aristas al renderizar (nodo Bevel): las aristas atrapan la luz.
- ``estudio(scene, objetos, camara)``: fondo curvo (ciclorama) y cajas de luz.

Escrito para Blender 4.x–5.x; si falta algo, se degrada sin fallar.
"""
import math

import bpy
from mathutils import Matrix, Vector

# Los mismos colores que core/edwin_materiales.py (Blender no ve ese módulo).
COLOR = {
    "acero": (0.60, 0.61, 0.62), "inox_cepillado": (0.74, 0.75, 0.76),
    "cromo": (0.86, 0.87, 0.88), "galvanizado": (0.70, 0.72, 0.73),
    "aluminio": (0.91, 0.92, 0.92), "hierro_negro": (0.16, 0.16, 0.17),
    "oro": (1.00, 0.77, 0.34), "bronce": (0.80, 0.56, 0.32),
    "cobre": (0.95, 0.64, 0.54), "llanta": (0.024, 0.024, 0.026),
    "caucho": (0.030, 0.030, 0.032), "caucho_usado": (0.055, 0.054, 0.052),
    "rin_maquinado": (0.80, 0.81, 0.82),
}
CLAVES = set(COLOR) | {"pintura_mate", "pintura_satinada", "pintura_brillante",
                       "pintura_texturizada", "pintura_metalizada"}
CON_EJE = ("llanta", "rin_maquinado")


# ---------------------------------------------------------------- utilidades
def _inp(node, *names):
    for n in names:
        s = node.inputs.get(n)
        if s is not None:
            return s
    return None


def _out(node, *names):
    for n in names:
        s = node.outputs.get(n)
        if s is not None:
            return s
    return node.outputs[0]


def _val(node, names, value):
    s = _inp(node, *names) if isinstance(names, tuple) else _inp(node, names)
    if s is None:
        return False
    for link in list(s.links):
        s.id_data.links.remove(link)
    try:
        s.default_value = value
    except (TypeError, ValueError):
        return False
    return True


class _Arbol:
    """Atajos para crear nodos en el árbol de un material."""

    def __init__(self, mat):
        self.mat = mat
        self.nodes = mat.node_tree.nodes
        self.links = mat.node_tree.links

    def nuevo(self, tipo, **inputs):
        n = self.nodes.new(tipo)
        for k, v in inputs.items():
            s = n.inputs.get(k)
            if s is not None:
                s.default_value = v
        return n

    def unir(self, a, b):
        self.links.new(a, b)

    def math(self, op, a, b=None, clamp=False):
        n = self.nodes.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = float(v)
            else:
                self.links.new(v, n.inputs[i])
        return n.outputs[0]

    def rango(self, v, a, b, c=0.0, d=1.0, suave=True):
        """Map Range: v de [a, b] a [c, d] (suave = smoothstep)."""
        n = self.nodes.new("ShaderNodeMapRange")
        if suave:
            try:
                n.interpolation_type = "SMOOTHSTEP"
            except (TypeError, AttributeError):
                pass
        n.clamp = True
        ins = n.inputs
        if isinstance(v, (int, float)):
            ins["Value"].default_value = float(v)
        else:
            self.links.new(v, ins["Value"])
        ins["From Min"].default_value = a
        ins["From Max"].default_value = b
        ins["To Min"].default_value = c
        ins["To Max"].default_value = d
        return _out(n, "Result")

    def coordenadas(self, objeto=None):
        tc = self.nodes.new("ShaderNodeTexCoord")
        if objeto is not None:
            tc.object = objeto
        return tc.outputs["Object"]

    def ruido(self, vec, escala, detalle=4.0, rugosidad=0.5, estirar=None):
        if estirar is not None:
            mp = self.nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = estirar
            self.links.new(vec, mp.inputs["Vector"])
            vec = mp.outputs["Vector"]
        n = self.nodes.new("ShaderNodeTexNoise")
        self.links.new(vec, n.inputs["Vector"])
        n.inputs["Scale"].default_value = escala
        if "Detail" in n.inputs:
            n.inputs["Detail"].default_value = detalle
        if "Roughness" in n.inputs:
            n.inputs["Roughness"].default_value = rugosidad
        return n.outputs["Fac"]

    def voronoi(self, vec, escala):
        n = self.nodes.new("ShaderNodeTexVoronoi")
        self.links.new(vec, n.inputs["Vector"])
        n.inputs["Scale"].default_value = escala
        return n


def _bsdf_normal_chain(t, bsdf):
    """Lo que ya llega a Normal (el bevel, por ejemplo) para encadenar."""
    s = bsdf.inputs["Normal"]
    return s.links[0].from_socket if s.links else None


def _relieve(t, bsdf, altura, fuerza, distancia, capa=False):
    """altura → Bump → Normal (y a Coat Normal si ``capa``)."""
    bump = t.nuevo("ShaderNodeBump")
    bump.inputs["Strength"].default_value = fuerza
    if "Distance" in bump.inputs:
        bump.inputs["Distance"].default_value = distancia
    t.unir(altura, bump.inputs["Height"])
    previo = _bsdf_normal_chain(t, bsdf)
    if previo is not None:
        t.unir(previo, bump.inputs["Normal"])
    t.unir(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if capa:
        cn = _inp(bsdf, "Coat Normal", "Clearcoat Normal")
        if cn is not None:
            t.unir(bump.outputs["Normal"], cn)
    return bump


def _color_base(t, bsdf, clave):
    if clave in COLOR:
        _val(bsdf, ("Base Color",), (*COLOR[clave], 1.0))
    s = bsdf.inputs["Base Color"]
    return s.links[0].from_socket if s.links else None


def _variar_color(t, bsdf, fac, minimo, maximo):
    """Multiplica el brillo del color base entre ``minimo`` y ``maximo``."""
    s = bsdf.inputs["Base Color"]
    hsv = t.nuevo("ShaderNodeHueSaturation")
    if s.links:
        t.unir(s.links[0].from_socket, hsv.inputs["Color"])
    else:
        hsv.inputs["Color"].default_value = s.default_value
    t.unir(t.rango(fac, 0.0, 1.0, minimo, maximo, suave=False),
           hsv.inputs["Value"])
    t.unir(hsv.outputs["Color"], s)


def _rugosidad(t, bsdf, fac, minimo, maximo):
    t.unir(t.rango(fac, 0.0, 1.0, minimo, maximo, suave=False),
           bsdf.inputs["Roughness"])


# ---------------------------------------------------------------- materiales
def aplicar(mat, bsdf, clave, ejes=None):
    """Arma el material ``clave``. ``ejes`` = Empty con Z por el eje de la
    rueda (llanta, rin maquinado), o None."""
    t = _Arbol(mat)
    co = t.coordenadas()
    spec = ("Specular IOR Level", "Specular")
    _color_base(t, bsdf, clave)
    _val(bsdf, ("Coat Weight", "Clearcoat"), 0.0)

    if clave in COLOR and clave not in ("llanta", "caucho", "caucho_usado"):
        _val(bsdf, ("Metallic",), 0.85 if clave == "hierro_negro" else 1.0)

    if clave == "acero":
        _val(bsdf, ("Roughness",), 0.32)
        f = t.ruido(co, 6.0, 6.0, 0.6)
        _rugosidad(t, bsdf, f, 0.26, 0.40)
        _variar_color(t, bsdf, f, 0.93, 1.05)
    elif clave == "inox_cepillado":
        # Rayitas en una sola dirección: ruido muy estirado a lo largo de X.
        f = t.ruido(co, 1.0, 2.0, 0.5, estirar=(6.0, 900.0, 900.0))
        _rugosidad(t, bsdf, f, 0.18, 0.32)
        _relieve(t, bsdf, f, 0.12, 0.0003)
        a = _inp(bsdf, "Anisotropic")
        if a is not None:
            a.default_value = 0.6
    elif clave == "cromo":
        _val(bsdf, ("Roughness",), 0.03)
    elif clave == "galvanizado":
        # Las «flores» del galvanizado: celdas de unos 2–5 cm, cada una con
        # su propio brillo y rugosidad.
        v = t.voronoi(co, 55.0)
        bw = t.nuevo("ShaderNodeRGBToBW")
        t.unir(_out(v, "Color"), bw.inputs["Color"])
        f = bw.outputs["Val"]
        _rugosidad(t, bsdf, f, 0.22, 0.42)
        _variar_color(t, bsdf, f, 0.93, 1.04)
        _relieve(t, bsdf, _out(v, "Distance"), 0.05, 0.0002)
    elif clave == "aluminio":
        f = t.ruido(co, 40.0, 4.0, 0.5)
        _rugosidad(t, bsdf, f, 0.24, 0.36)
    elif clave == "hierro_negro":
        # Cascarilla de laminación: manchas grandes y opacas.
        f = t.ruido(co, 4.0, 8.0, 0.65)
        _rugosidad(t, bsdf, f, 0.42, 0.72)
        _variar_color(t, bsdf, f, 0.65, 1.35)
        _relieve(t, bsdf, t.ruido(co, 120.0, 4.0), 0.06, 0.0002)
    elif clave in ("oro", "bronce", "cobre"):
        base = {"oro": 0.16, "bronce": 0.24, "cobre": 0.2}[clave]
        _rugosidad(t, bsdf, t.ruido(co, 30.0, 4.0), base * 0.75, base * 1.35)

    elif clave == "pintura_mate":
        _val(bsdf, ("Metallic",), 0.0)
        _val(bsdf, ("Roughness",), 0.78)
        _val(bsdf, spec, 0.35)
        _relieve(t, bsdf, t.ruido(co, 300.0, 3.0), 0.04, 0.0002)
    elif clave == "pintura_satinada":
        _val(bsdf, ("Metallic",), 0.0)
        _val(bsdf, ("Roughness",), 0.38)
        _relieve(t, bsdf, t.ruido(co, 300.0, 3.0), 0.04, 0.0002)
    elif clave == "pintura_brillante":
        # Esmalte: color con laca encima; un poquito de «piel de naranja».
        _val(bsdf, ("Metallic",), 0.0)
        _val(bsdf, ("Roughness",), 0.25)
        _val(bsdf, ("Coat Weight", "Clearcoat"), 1.0)
        _val(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.02)
        _relieve(t, bsdf, t.ruido(co, 180.0, 2.0), 0.025, 0.0002, capa=True)
    elif clave == "pintura_texturizada":
        # Arrugada / granulada, como un tablero eléctrico o una máquina.
        _val(bsdf, ("Metallic",), 0.0)
        _val(bsdf, ("Roughness",), 0.55)
        v = t.voronoi(co, 260.0)
        grano = t.math("ADD", _out(v, "Distance"),
                       t.math("MULTIPLY", t.ruido(co, 90.0, 6.0), 0.6))
        _relieve(t, bsdf, grano, 0.55, 0.0005)
    elif clave == "pintura_metalizada":
        # Escarcha: partículas metálicas bajo una laca transparente.
        _val(bsdf, ("Metallic",), 0.65)
        _val(bsdf, ("Roughness",), 0.32)
        _val(bsdf, ("Coat Weight", "Clearcoat"), 1.0)
        _val(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.02)
        v = t.voronoi(co, 2500.0)
        bw = t.nuevo("ShaderNodeRGBToBW")
        t.unir(_out(v, "Color"), bw.inputs["Color"])
        _relieve(t, bsdf, bw.outputs["Val"], 0.5, 0.00005)

    elif clave == "caucho":
        _val(bsdf, ("Metallic",), 0.0)
        _val(bsdf, ("Roughness",), 0.55)
        _val(bsdf, spec, 0.35)
        _relieve(t, bsdf, t.ruido(co, 400.0, 3.0), 0.05, 0.0002)
    elif clave == "caucho_usado":
        _val(bsdf, ("Metallic",), 0.0)
        _val(bsdf, spec, 0.25)
        f = t.ruido(co, 12.0, 6.0)
        _rugosidad(t, bsdf, f, 0.75, 0.95)
        _variar_color(t, bsdf, f, 0.8, 1.5)
        _relieve(t, bsdf, t.ruido(co, 400.0, 3.0), 0.08, 0.0002)
    elif clave == "llanta":
        _val(bsdf, ("Metallic",), 0.0)
        _val(bsdf, spec, 0.4)
        _llanta(t, bsdf, ejes)
    elif clave == "rin_maquinado":
        _val(bsdf, ("Roughness",), 0.12)
        _rin(t, bsdf, ejes)


def _polares(t, ejes):
    """(r, ángulo, z) en el sistema de la rueda (Empty: Z = eje)."""
    sep = t.nuevo("ShaderNodeSeparateXYZ")
    t.unir(t.coordenadas(ejes), sep.inputs[0])
    x, y, z = sep.outputs[0], sep.outputs[1], sep.outputs[2]
    r = t.math("SQRT", t.math("ADD", t.math("MULTIPLY", x, x),
                              t.math("MULTIPLY", y, y)))
    ang = t.math("ARCTAN2", y, x)
    return r, ang, z


def _llanta(t, bsdf, ejes):
    """Caucho de llanta con labrado por relieve (bump): bloques en V a lo
    largo de la banda de rodadura y tres canales alrededor. Sin eje
    conocido, solo el caucho con su grano."""
    grano = t.ruido(t.coordenadas(), 500.0, 3.0)
    if ejes is None:
        _val(bsdf, ("Roughness",), 0.6)
        _relieve(t, bsdf, grano, 0.05, 0.0002)
        return
    R = float(ejes.get("edwin_radio", 0.33))
    W = float(ejes.get("edwin_ancho", 0.10))      # medio ancho
    r, ang, z = _polares(t, ejes)
    az = t.math("ABSOLUTE", z)
    # Bloques: unos 56 por vuelta, en V (desplazados según |z|).
    n = max(24, int(round(2 * math.pi * R / 0.045)))
    fase = t.math("ADD", t.math("MULTIPLY", ang, n / (2 * math.pi)),
                  t.math("MULTIPLY", az, 1.6 / max(W, 1e-3)))
    seno = t.math("SINE", t.math("MULTIPLY", fase, 2 * math.pi))
    bloques = t.rango(seno, 0.55, 0.8, 1.0, 0.0)           # 0 = ranura
    # Canales alrededor: en el centro y a ±45 % del medio ancho.
    canal_w = W * 0.07
    altura = bloques
    for c in (0.0, 0.45 * W):
        d = t.math("ABSOLUTE", t.math("SUBTRACT", az, c))
        altura = t.math("MULTIPLY", altura, t.rango(d, canal_w * 0.5, canal_w))
    # Solo en la banda de rodadura: radio alto y dentro del ancho.
    banda = t.math("MULTIPLY", t.rango(r, R * 0.90, R * 0.94),
                   t.rango(az, W * 0.92, W * 0.80))
    ranura = t.math("MULTIPLY", banda, t.math("SUBTRACT", 1.0, altura))
    # Letras/costado lisos con un brillo satinado; las ranuras más opacas.
    _rugosidad(t, bsdf, ranura, 0.55, 0.85)
    alt = t.math("SUBTRACT", 1.0, ranura)
    alt = t.math("ADD", alt, t.math("MULTIPLY", grano, 0.02))
    _relieve(t, bsdf, alt, 1.0, max(0.004, R * 0.022))


def _rin(t, bsdf, ejes):
    """Aluminio maquinado: rayitas circulares de torno alrededor del eje."""
    if ejes is None:
        f = t.ruido(t.coordenadas(), 40.0, 4.0)
        _rugosidad(t, bsdf, f, 0.10, 0.18)
        return
    r, _ang, _z = _polares(t, ejes)
    anillos = t.math("SINE", t.math("MULTIPLY", r, 2 * math.pi / 0.0006))
    anillos = t.math("ADD", anillos,
                     t.math("MULTIPLY", t.ruido(t.coordenadas(ejes), 3.0, 2.0), 0.6))
    _rugosidad(t, bsdf, t.rango(anillos, -1.0, 1.0), 0.14, 0.28)
    _relieve(t, bsdf, anillos, 0.06, 0.00015)


# ------------------------------------------------- ruedas: separar y su eje
def _clave(mat):
    return mat.get("ingetrazo_finish") if mat is not None else None


def preparar_ejes(say=print):
    """Cada rueda con llanta o rin maquinado en su propio objeto, con un
    Empty en su centro (Z por el eje). Devuelve {material: Empty}."""
    import bmesh
    try:
        import numpy as np
    except ImportError:                       # sin numpy: sin labrado
        return {}
    objetivo = [m for m in bpy.data.materials if _clave(m) in CON_EJE]
    if not objetivo:
        return {}
    piezas = []          # (objeto, material)
    for obj in [o for o in bpy.context.scene.objects if o.type == "MESH"]:
        for mat in objetivo:
            idx = [i for i, s in enumerate(obj.material_slots) if s.material is mat]
            if not idx:
                continue
            # Copia del objeto con SOLO las caras de este material.
            nuevo = obj.copy()
            nuevo.data = obj.data.copy()
            bpy.context.scene.collection.objects.link(nuevo)
            bm = bmesh.new()
            bm.from_mesh(nuevo.data)
            bmesh.ops.delete(bm, geom=[f for f in bm.faces
                                       if f.material_index not in idx],
                             context="FACES")
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
            # Partes sueltas = ruedas.
            sin_ver = set(bm.faces)
            grupos = []
            while sin_ver:
                semilla = sin_ver.pop()
                pila, grupo = [semilla], [semilla]
                while pila:
                    f = pila.pop()
                    for e in f.edges:
                        for g in e.link_faces:
                            if g in sin_ver:
                                sin_ver.remove(g)
                                pila.append(g)
                                grupo.append(g)
                grupos.append(grupo)
            mw = obj.matrix_world
            info = []
            for g in grupos:
                pts = np.array([tuple(mw @ v.co) for f in g for v in f.verts])
                c = pts.mean(axis=0)
                info.append((g, pts, c, float(np.linalg.norm(pts - c, axis=1).max())))
            if not info:
                bm.free()
                bpy.data.objects.remove(nuevo)
                continue
            rmax = max(i[3] for i in info)
            grandes = [i for i in info if i[3] > rmax * 0.35]
            # Las partes chicas (letras, válvula) van con la rueda más cercana.
            ruedas = {id(gr[0]): (gr, list(gr[0])) for gr in grandes}
            for i in info:
                if i[3] > rmax * 0.35:
                    continue
                cerca = min(grandes, key=lambda gr: np.linalg.norm(gr[2] - i[2]))
                ruedas[id(cerca[0])][1].extend(i[0])
            for n_r, (gr, caras) in enumerate(ruedas.values()):
                pts = np.array([tuple(mw @ v.co) for f in caras for v in f.verts])
                c = pts.mean(axis=0)
                cov = np.cov((pts - c).T)
                val, vec = np.linalg.eigh(cov)
                eje = vec[:, 0]                       # menor dispersión = eje
                rel = pts - c
                z = rel @ eje
                radial = np.linalg.norm(rel - np.outer(z, eje), axis=1)
                radio = float(radial.max())
                ancho = float(np.abs(z).max())
                vacio = bpy.data.objects.new(f"EDWIN eje {mat.name} {n_r + 1}", None)
                bpy.context.scene.collection.objects.link(vacio)
                q = Vector(tuple(eje)).to_track_quat("Z", "Y")
                vacio.matrix_world = Matrix.Translation(Vector(tuple(c))) @ q.to_matrix().to_4x4()
                vacio["edwin_radio"] = radio
                vacio["edwin_ancho"] = ancho
                propio = mat.copy()
                propio.name = f"{mat.name} rueda {n_r + 1}"
                propio["edwin_eje"] = vacio.name
                for f in caras:
                    f.material_index = idx[0]
                piezas.append((caras, propio, vacio))
            # Un objeto por rueda: se separan aquí con bmesh.
            for caras, propio, vacio in piezas[-len(ruedas):]:
                pieza = bpy.data.objects.new(propio.name, bpy.data.meshes.new(propio.name))
                bpy.context.scene.collection.objects.link(pieza)
                pieza.matrix_world = mw.copy()
                bm2 = bmesh.new()
                vmap = {}
                for f in caras:
                    vs = []
                    for v in f.verts:
                        if v not in vmap:
                            vmap[v] = bm2.verts.new(v.co)
                        vs.append(vmap[v])
                    try:
                        bm2.faces.new(vs).smooth = f.smooth
                    except ValueError:
                        pass
                bm2.to_mesh(pieza.data)
                bm2.free()
                pieza.data.materials.append(propio)
            bm.free()
            bpy.data.objects.remove(nuevo)
            # Quitar esas caras del objeto original.
            bm0 = bmesh.new()
            bm0.from_mesh(obj.data)
            bmesh.ops.delete(bm0, geom=[f for f in bm0.faces
                                        if f.material_index in idx],
                             context="FACES")
            bm0.to_mesh(obj.data)
            bm0.free()
    salida = {}
    for _caras, propio, vacio in piezas:
        salida[propio.name] = vacio
    if salida:
        say("ruedas", len(salida))
    return salida


# ----------------------------------------------------------- bordes suaves
def bordes_suaves(radio=0.0015):
    """Nodo Bevel en la normal de cada material (solo lo calcula Cycles)."""
    for mat in bpy.data.materials:
        if not mat.node_tree or mat.name.startswith("EDWIN estudio"):
            continue
        bsdf = next((n for n in mat.node_tree.nodes
                     if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None or bsdf.inputs["Normal"].links:
            continue
        bev = mat.node_tree.nodes.new("ShaderNodeBevel")
        bev.inputs["Radius"].default_value = radio
        if hasattr(bev, "samples"):
            bev.samples = 8
        mat.node_tree.links.new(bev.outputs["Normal"], bsdf.inputs["Normal"])


# ------------------------------------------------------------------ estudio
def _caja(objs):
    lo = Vector((1e18, 1e18, 1e18))
    hi = Vector((-1e18, -1e18, -1e18))
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            p = o.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    if lo.x > hi.x:
        return Vector((-0.5, -0.5, 0.0)), Vector((0.5, 0.5, 1.0))
    return lo, hi


def estudio(scene, cam_cfg, say=print):
    """Fondo curvo gris (ciclorama) detrás del modelo, visto desde la
    cámara, y tres cajas de luz grandes (principal, relleno y contraluz)
    más una franja arriba que se refleja en los metales."""
    import bmesh
    objs = [o for o in scene.objects if o.type == "MESH"]
    lo, hi = _caja(objs)
    centro = (lo + hi) / 2
    tam = max((hi - lo).length, 0.05)
    piso = lo.z - 0.0005
    ojo = Vector(cam_cfg["eye"])
    d = Vector((centro.x - ojo.x, centro.y - ojo.y, 0.0))
    if d.length < 1e-6:
        d = Vector((0.0, 1.0, 0.0))
    d.normalize()                       # de la cámara hacia el modelo
    lado = Vector((d.y, -d.x, 0.0))     # a la derecha de la cámara

    # -- ciclorama: piso + curva + pared, en el plano (adelante, arriba)
    ancho = tam * 12
    atras = tam * 1.6                   # dónde empieza la curva detrás
    radio = tam * 1.2
    alto = tam * 6
    perfil = [(-tam * 10, 0.0)]
    for i in range(0, 17):
        a = math.radians(-90 + 90 * i / 16)
        perfil.append((atras + radio * math.cos(a), radio + radio * math.sin(a)))
    perfil.append((atras + radio, alto))
    me = bpy.data.meshes.new("EDWIN estudio fondo")
    bm = bmesh.new()
    filas = []
    for s in (-0.5, 0.5):
        fila = []
        for (u, v) in perfil:
            p = Vector((centro.x, centro.y, piso)) + d * u + lado * (s * ancho) \
                + Vector((0, 0, v))
            fila.append(bm.verts.new(p))
        filas.append(fila)
    for i in range(len(perfil) - 1):
        f = bm.faces.new((filas[0][i], filas[0][i + 1], filas[1][i + 1], filas[1][i]))
        f.smooth = True
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    fondo = bpy.data.objects.new("EDWIN estudio fondo", me)
    scene.collection.objects.link(fondo)
    # Normales hacia arriba/adelante (hacia el modelo).
    if me.polygons and me.polygons[0].normal.z < 0:
        for p in me.polygons:
            p.flip()
    mat = bpy.data.materials.new("EDWIN estudio fondo")
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    b = mat.node_tree.nodes.get("Principled BSDF")
    if b is not None:
        b.inputs["Base Color"].default_value = (0.16, 0.16, 0.17, 1.0)
        b.inputs["Roughness"].default_value = 0.55
    me.materials.append(mat)

    # -- mundo: gris oscuro (lo que se refleja donde no hay cajas de luz)
    world = bpy.data.worlds.new("EDWIN estudio")
    scene.world = world
    if hasattr(world, "use_nodes"):
        world.use_nodes = True
    bg = world.node_tree.nodes.get("Background") or world.node_tree.nodes.new(
        "ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.05, 0.05, 0.055, 1.0)
    bg.inputs["Strength"].default_value = 1.0

    # -- cajas de luz (área) — potencia según la distancia
    def caja(nombre, pos, tamano, potencia, forma="RECTANGLE", alargada=1.0, color=(1, 1, 1)):
        luz = bpy.data.lights.new(nombre, type="AREA")
        luz.shape = forma
        luz.size = tamano
        if hasattr(luz, "size_y"):
            luz.size_y = tamano * alargada
        luz.energy = potencia
        luz.color = color
        ob = bpy.data.objects.new(nombre, luz)
        scene.collection.objects.link(ob)
        ob.location = pos
        hacia = (centro - pos).normalized()
        ob.rotation_euler = hacia.to_track_quat("-Z", "Y").to_euler()
        return ob

    D = tam * 1.8
    escala = (D / 2.0) ** 2
    arriba = Vector((0, 0, 1))
    # principal: caja grande arriba-adelante-izquierda (sombra suave)
    caja("EDWIN luz principal", centro - d * D * 0.8 - lado * D * 0.7 + arriba * D * 0.9,
         tam * 1.2, 120 * escala, alargada=1.3, color=(1.0, 0.98, 0.95))
    # dos franjas verticales a los lados: las líneas de luz en pintura y cromo
    for s_, pot in ((-1, 45), (1, 60)):
        ob = caja(f"EDWIN franja {'izq' if s_ < 0 else 'der'}",
                  centro - d * D * 0.45 + lado * (s_ * D * 1.05) + arriba * D * 0.25,
                  tam * 0.22, pot * escala, alargada=5.0)
    # techo: caja grande encima (se refleja en las caras de arriba)
    caja("EDWIN techo", centro + arriba * D * 1.2, tam * 1.6, 70 * escala, alargada=0.6)
    # contraluz: separa el modelo del fondo
    caja("EDWIN contraluz", centro + d * D * 0.9 + lado * D * 0.3 + arriba * D * 1.0,
         tam * 0.8, 90 * escala)
    say("estudio", f"{tam:.3f} m")
