# Changelog

All notable changes to stljoiner are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.1] - 2026-11-25

### Fixed

- The README's images and links now use full GitHub URLs, so they show up
  on the PyPI project page.

## [0.2.0] - 2026-11-25

Install from PyPI, face suggestions, smarter auto-join and more file formats.

### Added

- stljoiner is a Python package: `pipx install stljoiner` (or `pip install
  stljoiner`) installs the `stljoiner` command on Linux, macOS and Windows.
- `stljoiner web` starts the web interface (`--port`, `--host`).
- `python -m stljoiner` works the same as `stljoiner`.
- Release workflow: pushing a version tag creates the GitHub release and
  uploads the package to PyPI.
- CI also runs on Windows and macOS and checks that the package builds.
- Face suggestions in the web interface: click face A and the best-fitting
  faces on the other checked parts light up and are listed by fit. Press S
  (or click one) to take it.
- Auto-join understands stepped and dovetailed cuts: face matches that agree
  on the same placement count as one strong joint. Pegs and holes with
  clearance match too.
- Auto-join never pushes one part into another, trusts faces that fit only
  one partner over plain faces that fit many, and marks joints that are a
  guess with ⚠.
- Mesh formats: read STL, 3MF, OBJ, PLY, OFF and GLB. A 3MF or GLB with
  several objects loads as several parts. Write STL, 3MF, OBJ, PLY, OFF or
  GLB (`-o` extension on the command line, a format menu in the page).
  Unmerged 3MF/GLB keeps each part as its own object.
- Adjust panel: move a part (and what's joined to it) by a step, or turn it
  90°.
- Green-screen theme, keyboard shortcuts (press ? in the page), and the
  page remembers your theme, export format and unchecked parts.
- An optional end-to-end browser test (`tests/test_browser.py`).

### Changed

- `stljoiner PART.stl ...` replaces `python stljoin.py PART.stl ...`, and
  `stljoiner web` replaces `python app.py`. The code now lives in
  `src/stljoiner/`.
- Dependencies are listed in `pyproject.toml`. `requirements.txt` is gone.
- The web page works offline: three.js is bundled instead of loaded from a
  CDN.
- Picked and suggested faces show through the model, so they're never
  hidden.

### Fixed

- The disabled Join button no longer looks active in the green-screen theme.

## [0.1.0] - 2026-11-25

First release.

### Added

- Web interface (`app.py`, <http://127.0.0.1:4300>): drop in STL parts, view
  them in 3D, click the two faces that touch to join them, step through
  every rotation a symmetric face fits with **Next rotation**, auto-join,
  undo, reset, detach, and export the checked parts as one merged STL.
  Unchecked parts are faded out and left out of joining and export.
- Command line (`stljoin.py`): joins parts automatically and writes one STL,
  with `--no-union`, `--export-parts`, `--tolerance`, `--max-faces`,
  `--min-area`, `--version` and `-q`.
- Face matching by outline shape, holes included. Flat islands on one plane
  count as one face, so cuts through holes and slots match.
- Exact alignment: a 2D ICP pass snaps the matched outlines together vertex
  to vertex.
- Pieces already in their original positions are detected and kept in place.
- Seam vertices are welded before the boolean union (manifold3d), so the
  result is watertight.
- User guide, test suite and CI.

[Unreleased]: https://github.com/drak42/stljoiner/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/drak42/stljoiner/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/drak42/stljoiner/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/drak42/stljoiner/releases/tag/v0.1.0
