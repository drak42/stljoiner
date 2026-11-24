"""Make a test part and split it into three pieces.

Used by the test suite, and handy for trying the tool by hand:

    .venv/bin/python tests/make_test_parts.py OUT_DIR [--in-place]

Without --in-place, each piece is moved and rotated randomly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import trimesh


def make_original() -> trimesh.Trimesh:
    """An asymmetric L-shaped block with a hole, 120 x 40 x 80 mm."""
    bar = trimesh.creation.box([120, 40, 30])
    tower = trimesh.creation.box([30, 40, 50])
    tower.apply_translation([45, 0, 40])
    hole = trimesh.creation.cylinder(radius=6, height=60)
    hole.apply_translation([-20, 5, 0])
    body = trimesh.boolean.union([bar, tower], engine="manifold")
    return trimesh.boolean.difference([body, hole], engine="manifold")


def split(part: trimesh.Trimesh, cuts=(-20.0, 25.0)) -> list[trimesh.Trimesh]:
    """Cut the part with planes x = cut. The first cut passes through the hole."""
    pieces, rest = [], part
    for x in cuts:
        pieces.append(trimesh.intersections.slice_mesh_plane(rest, [-1, 0, 0], [x, 0, 0], cap=True))
        rest = trimesh.intersections.slice_mesh_plane(rest, [1, 0, 0], [x, 0, 0], cap=True)
    pieces.append(rest)
    return pieces


def make_parts(out: Path, scatter: bool = True, seed: int = 1) -> list[Path]:
    """Write original.stl and piece0..2.stl to `out`; return the piece paths."""
    out.mkdir(parents=True, exist_ok=True)
    original = make_original()
    original.export(out / "original.stl")
    rng = np.random.default_rng(seed)
    paths = []
    for i, piece in enumerate(split(original)):
        if scatter:
            T = trimesh.transformations.random_rotation_matrix(rng.random(3))
            T[:3, 3] = rng.uniform(-200, 200, 3)
            piece.apply_transform(T)
        path = out / f"piece{i}.stl"
        piece.export(path)
        paths.append(path)
    return paths


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0] if args else "test_parts")
    make_parts(out, scatter="--in-place" not in sys.argv)
    print("wrote", out)
