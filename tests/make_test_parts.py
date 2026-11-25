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



def _box(size, center=(0, 0, 0)) -> trimesh.Trimesh:
    b = trimesh.creation.box(size)
    b.apply_translation(center)
    return b


def _union(*ms):
    return trimesh.boolean.union(list(ms), engine="manifold")


def _diff(a, *ms):
    return trimesh.boolean.difference([a, *ms], engine="manifold")


def _cyl_x(radius, length, start, y=0.0, z=0.0):
    """Cylinder along +x from x=start."""
    c = trimesh.creation.cylinder(radius=radius, height=length, sections=48)
    c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    c.apply_translation([start + length / 2, y, z])
    return c


def connector_pieces() -> tuple[trimesh.Trimesh, list[trimesh.Trimesh]]:
    """A 60x40x30 block cut at x=0 with a peg (left) and a 0.2 mm-clearance hole (right)."""
    original = _box([60, 40, 30])
    left = _union(_box([30, 40, 30], (-15, 0, 0)), _cyl_x(4, 10, 0, y=6, z=-3))
    right = _diff(_box([30, 40, 30], (15, 0, 0)), _cyl_x(4.2, 11, -0.5, y=6, z=-3))
    return original, [left, right]


def stepped_pieces() -> tuple[trimesh.Trimesh, list[trimesh.Trimesh]]:
    """An 80x40x30 block split along a Z-shaped (stepped) cut."""
    original = _box([80, 40, 30])
    left = _union(_box([40, 40, 15], (-20, 0, -7.5)), _box([55, 40, 15], (-12.5, 0, 7.5)))
    right = _diff(original, left)
    return original, [left, right]


def dovetail_pieces() -> tuple[trimesh.Trimesh, list[trimesh.Trimesh]]:
    """A 70x40x20 plate split by a dovetail joint (tab on the left piece)."""
    original = _box([70, 40, 20])
    tail = trimesh.creation.extrude_polygon(
        __import__("shapely.geometry", fromlist=["Polygon"]).Polygon([(0, -6), (12, -10), (12, 10), (0, 6)]), 20)
    tail.apply_translation([0, 0, -10])
    left = _union(_box([35, 40, 20], (-17.5, 0, 0)), tail)
    right = _diff(original, left)
    return original, [left, right]


def scatter(pieces: list[trimesh.Trimesh], seed: int = 1) -> list[trimesh.Trimesh]:
    """Copies of the pieces, each moved and rotated randomly."""
    rng = np.random.default_rng(seed)
    out = []
    for piece in pieces:
        T = trimesh.transformations.random_rotation_matrix(rng.random(3))
        T[:3, 3] = rng.uniform(-200, 200, 3)
        out.append(piece.copy().apply_transform(T))
    return out

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0] if args else "test_parts")
    make_parts(out, scatter="--in-place" not in sys.argv)
    print("wrote", out)
