"""Make a test part, split it in three, scatter the pieces randomly."""
import sys
from pathlib import Path
import numpy as np
import trimesh

args = [a for a in sys.argv[1:] if not a.startswith("--")]
out = Path(args[0] if args else "test_parts")
out.mkdir(exist_ok=True)
rng = np.random.default_rng(1)
# An asymmetric L-shaped block with a hole, so cut faces aren't symmetric.
a = trimesh.creation.box([120, 40, 30])
b = trimesh.creation.box([30, 40, 50]); b.apply_translation([45, 0, 40])
hole = trimesh.creation.cylinder(radius=6, height=60); hole.apply_translation([-20, 5, 0])
part = trimesh.boolean.difference([trimesh.boolean.union([a, b], engine="manifold"), hole], engine="manifold")
part.export(out / "original.stl")
pieces, rest = [], part
for x in (-20.0, 25.0):
    left = trimesh.intersections.slice_mesh_plane(rest, [-1, 0, 0], [x, 0, 0], cap=True)
    rest = trimesh.intersections.slice_mesh_plane(rest, [1, 0, 0], [x, 0, 0], cap=True)
    pieces.append(left)
pieces.append(rest)
for i, p in enumerate(pieces):
    if "--in-place" in sys.argv: p.export(out / f"piece{i}.stl"); continue
    R = trimesh.transformations.random_rotation_matrix(rng.random(3))
    R[:3, 3] = rng.uniform(-200, 200, 3)
    p.apply_transform(R)
    p.export(out / f"piece{i}.stl")
print("wrote", out)
