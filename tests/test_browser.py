"""End-to-end test of the web page in a real browser.

Skipped unless Playwright and Google Chrome/Chromium are installed:

    .venv/bin/pip install playwright
    .venv/bin/pytest tests/test_browser.py
"""
import shutil
import socket
import threading

import pytest

playwright = pytest.importorskip("playwright.sync_api")
CHROME = next((p for p in map(shutil.which, ("google-chrome", "chromium", "chromium-browser")) if p), None)
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Google Chrome or Chromium")

from werkzeug.serving import make_server  # noqa: E402

from stljoiner import join as stljoin  # noqa: E402
from stljoiner import web  # noqa: E402

LOADED = ("window.stljoiner && window.stljoiner.meshes.size === 3 && "
          "[...window.stljoiner.meshes.values()].every(m => m.mesh.geometry.attributes.position)")
CLICK_TRIANGLE = """([pi, tri]) => {
  const { THREE, camera, controls, meshes, renderer } = window.stljoiner;
  const mesh = [...meshes.values()][pi].mesh;
  const p = mesh.geometry.attributes.position.array;
  const v = k => new THREE.Vector3(p[tri*9+k*3], p[tri*9+k*3+1], p[tri*9+k*3+2]);
  const [a, b, c] = [v(0), v(1), v(2)];
  const ctr = a.clone().add(b).add(c).divideScalar(3);
  const n = b.clone().sub(a).cross(c.clone().sub(a)).normalize();
  controls.target.copy(ctr);
  camera.position.copy(ctr).addScaledVector(n, 120).add(new THREE.Vector3(0.01, 0.02, 0.03));
  controls.update(); camera.updateMatrixWorld();
  const s = ctr.clone().project(camera), r = renderer.domElement.getBoundingClientRect();
  return [r.left + (s.x + 1) / 2 * r.width, r.top + (1 - s.y) / 2 * r.height];
}"""


@pytest.fixture
def server():
    web.S = web.Session()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = make_server("127.0.0.1", port, web.app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/"
    srv.shutdown()


def test_pick_suggest_join_export(server, scattered, tmp_path):
    tri_840 = next(int(g[0]) for g in stljoin.coplanar_groups(stljoin.load_parts(scattered[0], "p0.stl")[0][1])
                   if abs(stljoin.load_parts(scattered[0], "p0.stl")[0][1].area_faces[g].sum() - 840) < 1)
    external = []
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--use-angle=swiftshader",
                                                                   "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1280, "height": 800}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(server)
                   else (external.append(r.request.url), r.abort()))
        page.goto(server)
        page.set_input_files("#file", [str(p) for p in scattered])
        page.wait_for_function(LOADED)

        page.mouse.click(*page.evaluate(CLICK_TRIANGLE, [0, tri_840]))
        page.wait_for_function("window.stljoiner.state().suggestions.length > 0", timeout=30000)
        top = page.evaluate("window.stljoiner.state().suggestions[0]")
        assert top["fit"] == 100 and round(top["area"]) == 840

        page.keyboard.press("s")
        page.keyboard.press("j")
        page.wait_for_function("document.getElementById('status').textContent.startsWith('Joined')", timeout=30000)
        assert page.evaluate("new Set(window.stljoiner.state().parts.map(p => p.group)).size") == 2

        page.keyboard.press("t")
        page.reload()
        page.wait_for_function(LOADED)
        assert page.evaluate("document.body.classList.contains('matrix')")

        page.select_option("#format", "3mf")
        page.uncheck("#union")
        with page.expect_download() as dl:
            page.click("#export")
        out = tmp_path / "joined.3mf"
        dl.value.save_as(out)
        browser.close()
    assert len(stljoin.load_parts(out, out.name)) == 3
    assert errors == []
    assert external == []   # works offline: everything comes from the local server
