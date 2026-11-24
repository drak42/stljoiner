# Changelog

All notable changes to stljoiner are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

Install from PyPI.

### Added

- stljoiner is a Python package: `pipx install stljoiner` (or `pip install
  stljoiner`) installs the `stljoiner` command on Linux, macOS and Windows.
- `stljoiner web` starts the web interface (`--port`, `--host`).
- `python -m stljoiner` works the same as `stljoiner`.
- Release workflow: pushing a version tag creates the GitHub release and
  uploads the package to PyPI.
- CI also runs on Windows and macOS and checks that the package builds.

### Changed

- `stljoiner PART.stl ...` replaces `python stljoin.py PART.stl ...`, and
  `stljoiner web` replaces `python app.py`. The code now lives in
  `src/stljoiner/`.
- Dependencies are listed in `pyproject.toml`. `requirements.txt` is gone.

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

[Unreleased]: https://github.com/drak42/stljoiner/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/drak42/stljoiner/releases/tag/v0.1.0
