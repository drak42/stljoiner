"""Tests for the web interface's API."""
import io

import pytest
import trimesh

import app as webapp
import stljoin


@pytest.fixture
def client():
    webapp.S = webapp.Session()
    return webapp.app.test_client()


def upload(client, paths):
    files = [(open(p, "rb"), p.name) for p in paths]
    try:
        res = client.post("/api/parts", data={"files": files}, content_type="multipart/form-data")
    finally:
        for f, _ in files:
            f.close()
    assert res.status_code == 200
    return [p["id"] for p in res.get_json()["parts"]]


def face_tri(pid, area, pick=0):
    m = webapp.S.parts[pid].placed()
    return [int(g[0]) for g in stljoin.coplanar_groups(m) if abs(m.area_faces[g].sum() - area) < 1][pick]


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"stljoiner" in res.data


def test_upload_and_mesh(client, in_place):
    ids = upload(client, in_place)
    assert len(ids) == 3
    res = client.get(f"/api/parts/{ids[0]}/mesh")
    assert res.status_code == 200
    assert len(trimesh.load(io.BytesIO(res.data), file_type="stl").faces) > 0


def test_face_lookup(client, in_place):
    ids = upload(client, in_place)
    res = client.post("/api/face", json={"part": ids[0], "triangle": face_tri(ids[0], 840)}).get_json()
    assert res["area"] == pytest.approx(840, abs=0.5)


def test_manual_join_rotation_undo_export(client, scattered):
    ids = upload(client, scattered)
    original = trimesh.load_mesh(scattered[0].parent / "original.stl")

    res = client.post("/api/join", json={"a": ids[0], "faceA": face_tri(ids[0], 840),
                                         "b": ids[1], "faceB": face_tri(ids[1], 840)}).get_json()
    assert res["pending"]["fits"] == [100.0]   # an asymmetric face fits only one way
    assert len({p["group"] for p in res["parts"]}) == 2

    # Joining two parts of the same group is refused.
    res = client.post("/api/join", json={"a": ids[0], "faceA": 0, "b": ids[1], "faceB": 0})
    assert res.status_code == 400

    # piece2's real cut face, in its right rotation, gives back the original.
    found = False
    for pick in range(2):
        res = client.post("/api/join", json={"a": ids[1], "faceA": face_tri(ids[1], 1200),
                                             "b": ids[2], "faceB": face_tri(ids[2], 1200, pick)}).get_json()
        for i in range(len(res["pending"]["fits"])):
            client.post("/api/join/rotation", json={"index": i})
            data = client.post("/api/export", json={"ids": ids, "union": True}).data
            out = trimesh.load(io.BytesIO(data), file_type="stl")
            if out.convex_hull.volume == pytest.approx(original.convex_hull.volume, rel=1e-4):
                assert out.is_watertight
                found = True
        assert client.post("/api/undo").status_code == 200
    assert found


def test_auto_join_in_place(client, in_place):
    ids = upload(client, in_place)
    res = client.post("/api/auto", json={"ids": ids}).get_json()
    assert all(j["inPlace"] for j in res["joins"])
    assert len({p["group"] for p in res["parts"]}) == 1


def test_unselected_parts_left_out(client, in_place):
    ids = upload(client, in_place)
    client.post("/api/auto", json={"ids": ids})
    data = client.post("/api/export", json={"ids": ids[:2], "union": True}).data
    out = trimesh.load(io.BytesIO(data), file_type="stl")
    assert out.bounds[1][0] == pytest.approx(25.0)   # piece2 (x > 25) not exported


def test_other_host_names_refused(client):
    assert client.get("/", headers={"Host": "evil.example:4300"}).status_code == 403
    assert client.get("/", headers={"Host": "127.0.0.1:4300"}).status_code == 200
