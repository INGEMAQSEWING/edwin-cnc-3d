"""Pruebas de Materiales EDWIN (core/edwin_materiales.py + core/finish.py +
GLB + script de Blender). Correr: py -3.10 -I edwin/pruebas/prueba_materiales.py"""
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.chdir(REPO)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from core import edwin_materiales as em  # noqa: E402
from core import finish as fin  # noqa: E402
from core import render_blender as rb  # noqa: E402
from core.group import Group  # noqa: E402
from core.materials import Material  # noqa: E402
from core.mesh import Mesh  # noqa: E402
from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402
from formats.gltf import save_glb  # noqa: E402

ok = fallos = 0


def prueba(nombre, cond):
    global ok, fallos
    if cond:
        ok += 1
    else:
        fallos += 1
        print("FALLA:", nombre)


# 1. Catálogo
prueba("18 acabados", len(em.ACABADOS) == 18)
for k, (etq, grupo, color, pbr) in em.ACABADOS.items():
    prueba(f"{k} en FINISHES", k in fin.FINISHES)
    prueba(f"{k} etiqueta", fin.LABELS[k] == etq)
    prueba(f"{k} grupo", grupo in em.GRUPOS)
    prueba(f"{k} pbr", fin.PBR[k] == pbr and len(pbr) == 4)
prueba("grupos llenos", all(em.del_grupo(g) for g in em.GRUPOS))
prueba("los 6 de IngeTrazo siguen", all(k in fin.FINISHES for k in
                                        ("matte", "satin", "gloss", "metal", "glass", "water")))

# 2. Adivinar por el nombre (lo nuevo y lo de antes)
prueba("llanta", fin.guess("Llanta trasera") == "llanta")
prueba("neumático", fin.guess("Neumático 195/65") == "llanta")
prueba("tire", fin.guess("Tire_rubber") == "llanta")
prueba("caucho", fin.guess("Caucho negro") == "caucho")
prueba("inox sigue metal", fin.guess("Acero inoxidable") == "metal")
prueba("madera sigue satin", fin.guess("Madera") == "satin")
prueba("elegido gana", fin.resolve("pintura_brillante", "Llanta") == "pintura_brillante")

# 3. Se guarda en el .igz
scene = Scene()
scene.materials["Rojo"] = Material("Rojo", color=(0.8, 0.05, 0.03), finish="pintura_brillante")
scene.materials["Llanta"] = Material("Llanta", color=(0.05, 0.05, 0.05), finish="llanta")
me = Mesh()
p = [V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)]
me.add_face(p)
g = Group(me, name="placa")
for f in g.mesh.faces:
    f.attrs.update(scene.materials["Rojo"].face_attrs())
scene.groups.append(g)
me2 = Mesh()
me2.add_face([V(0, 0, 1), V(1, 0, 1), V(1, 1, 1), V(0, 1, 1)])
g2 = Group(me2, name="llanta")
for f in g2.mesh.faces:
    f.attrs.update(scene.materials["Llanta"].face_attrs())
scene.groups.append(g2)
tmp = Path(tempfile.mkdtemp())
igz.save_scene(scene, tmp / "doc.igz")
otra = Scene()
igz.load_into(otra, tmp / "doc.igz")
prueba("igz guarda acabado", otra.materials["Rojo"].finish == "pintura_brillante")

# 4. Viaja en el GLB (extras + PBR)
save_glb(scene, tmp / "m.glb")
data = (tmp / "m.glb").read_bytes()
n = struct.unpack_from("<I", data, 12)[0]
gl = json.loads(data[20:20 + n])
extras = {m.get("extras", {}).get("ingetrazo_finish") for m in gl["materials"]}
prueba("glb lleva pintura_brillante", "pintura_brillante" in extras)
prueba("glb lleva llanta", "llanta" in extras)
m_rojo = next(m for m in gl["materials"]
              if m.get("extras", {}).get("ingetrazo_finish") == "pintura_brillante")
prueba("glb rugosidad", abs(m_rojo["pbrMetallicRoughness"]["roughnessFactor"] - 0.10) < 1e-6)

# 5. Ambiente estudio y el módulo de Blender viaja junto al script
prueba("estudio en ambientes", "studio" in rb.AMBIENCES and "studio" in rb.EXPOSURE)
job = rb.write_job(scene, _cam := __import__("core.camera", fromlist=["OrbitCamera"]).OrbitCamera(),
                   tmp / "job", ambience="studio", width=320, height=180)
prueba("job estudio", json.loads(job.read_text(encoding="utf-8"))["ambience"] == "studio")


class _B:
    command = ["blender"]


cmd = rb.command(_B(), job)
prueba("script copiado", (tmp / "job" / "render_scene.py").exists())
prueba("modulo EDWIN copiado", (tmp / "job" / "edwin_materiales_blender.py").exists())
import py_compile  # noqa: E402
py_compile.compile(str(REPO / "resources/blender/edwin_materiales_blender.py"), doraise=True)
src = (REPO / "resources/blender/edwin_materiales_blender.py").read_text(encoding="utf-8")
claves_bl = set(em.ACABADOS)
prueba("Blender conoce todos", all(f'"{k}"' in src for k in claves_bl))

print(f"Materiales EDWIN: {ok} OK, {fallos} fallas")
sys.exit(1 if fallos else 0)
