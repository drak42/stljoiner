"""Tests for the joining engine and the command line."""
import subprocess
import sys

import numpy as np
import pytest
import trimesh

import stljoin
from conftest import ROOT


def load(path):
    m = trimesh.load_mesh(path, force="mesh")
    m.merge_vertices()
    return m


def original_of(pieces):
    return trimesh.load_mesh(pieces[0].parent / "original.stl")


def faces_with_area(mesh, area):
    """Triangle indices, one per coplanar face of the given area."""
    return [int(g[0]) for g in stljoin.coplanar_groups(mesh) if abs(mesh.area_faces[g].sum() - area) < 1]


def test_in_place_pieces_rejoin_exactly(in_place, tmp_path):
    out = tmp_path / "joined.stl"
    assert stljoin.main([*map(str, in_place), "-o", str(out), "-q"]) == 0
    joined, original = trimesh.load_mesh(out), original_of(in_place)
    assert joined.is_watertight
    np.testing.assert_allclose(joined.bounds, original.bounds, atol=1e-6)
    assert joined.volume == pytest.approx(original.volume, rel=1e-6)


def test_cut_through_hole_is_one_face(in_place):
    # The first cut passes through the hole, leaving two flat islands
    # (570 + 270 mm²) that must be treated as one 840 mm² face.
    piece = load(in_place[0])
    tri = faces_with_area(piece, 840)
    assert len(tri) == 1
    assert len(stljoin.planar_region(piece, tri[0])) > 2


def test_picked_faces_rebuild_scattered_part(scattered):
    """Joining by chosen faces restores the original shape exactly."""
    meshes = [load(p) for p in scattered]
    original = original_of(scattered)

    def join(a, b, area, pick_b=0):
        fa = stljoin.make_face(a, 0, stljoin.planar_region(a, faces_with_area(a, area)[0]))
        fb = stljoin.make_face(b, 1, stljoin.planar_region(b, faces_with_area(b, area)[pick_b]))
        fits = stljoin.rotation_fits(fa, fb)
        assert fits[0][1] > 0.99
        return [stljoin.placement(fa, fb, th, dth, off) for th, _, dth, off in fits]

    p0, p1, p2 = meshes
    p1 = p1.copy().apply_transform(join(p0, p1, 840)[0])
    # piece2 has two 1200 mm² faces (its cut face and the top of the tower) and
    # its cut face is a rectangle that fits two ways: exactly one of those
    # combinations is the original part.
    results = []
    for pick in range(2):
        for T in join(p1, p2, 1200, pick):
            joined = stljoin.combine([p0, p1, p2.copy().apply_transform(T)], union=True)
            results.append(joined)
    exact = [j for j in results if j.convex_hull.volume == pytest.approx(original.convex_hull.volume, rel=1e-4)]
    assert exact, "no face/rotation choice rebuilt the original"
    assert exact[0].is_watertight
    assert exact[0].volume == pytest.approx(original.volume, rel=1e-4)


def test_alignment_is_exact():
    """ICP refinement leaves no measurable gap between mating faces."""
    box = trimesh.creation.box([30, 20, 10])
    left = trimesh.intersections.slice_mesh_plane(box, [-1, 0, 0], [3, 0, 0], cap=True)
    right = trimesh.intersections.slice_mesh_plane(box, [1, 0, 0], [3, 0, 0], cap=True)
    moved = right.copy().apply_transform(trimesh.transformations.random_rotation_matrix(np.array([0.3, 0.6, 0.1])))
    tri_l = faces_with_area(left, 200)
    fa = next(f for f in (stljoin.make_face(left, 0, stljoin.planar_region(left, t)) for t in tri_l)
              if f.normal[0] > 0.99)
    tri_m = faces_with_area(moved, 200)
    candidates = [stljoin.make_face(moved, 1, stljoin.planar_region(moved, t)) for t in tri_m]
    back = []
    for fb in candidates:
        for th, _, dth, off in stljoin.rotation_fits(fa, fb):
            placed = moved.copy().apply_transform(stljoin.placement(fa, fb, th, dth, off))
            back.append(np.abs(np.sort(placed.vertices, axis=0) - np.sort(right.vertices, axis=0)).max())
    assert min(back) < 1e-6


def test_cli_version():
    out = subprocess.run([sys.executable, str(ROOT / "stljoin.py"), "--version"], capture_output=True, text=True)
    assert out.stdout.strip() == f"stljoiner {stljoin.__version__}"
