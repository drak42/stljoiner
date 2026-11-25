# Contributing to stljoiner

Thank you for taking the time to contribute! Bug reports, ideas and pull requests are all welcome.

## Reporting a problem

Open an [issue](https://github.com/drak42/stljoiner/issues/new/choose). The most useful thing you can attach is the **STL pieces that don't join correctly** (zipped), plus a note on how they were split.

For security problems, please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

```bash
git clone https://github.com/drak42/stljoiner.git
cd stljoiner
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

This installs the `stljoiner` command from your working copy (`.venv/bin/stljoiner`), so changes take effect right away. On Windows the programs are in `.venv\Scripts\` instead of `.venv/bin/`.

Before committing, run the same checks as GitHub Actions:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/python -m build && .venv/bin/twine check --strict dist/*
```

`tests/test_browser.py` drives the web page in a real browser. It's skipped unless Playwright and Google Chrome (or Chromium) are installed:

```bash
.venv/bin/pip install playwright
.venv/bin/pytest tests/test_browser.py
```

## Project layout

| Path | What it is |
|---|---|
| `src/stljoiner/join.py` | The joining engine and the `stljoiner` command line: face extraction, matching, alignment, assembly, union. |
| `src/stljoiner/web.py` | The Flask web server (`stljoiner web`) and its JSON API. |
| `src/stljoiner/static/index.html` | The web page (3D viewer, face picking, suggestions). |
| `src/stljoiner/static/vendor/three/` | three.js r170 (MIT, see its LICENSE), bundled so the page works offline. |
| `src/stljoiner/cli.py` | Sends `stljoiner web` to the web server and everything else to the joiner. |
| `src/stljoiner/version.py` | The version number (the only place it is set). |
| `tests/` | pytest suite. `make_test_parts.py` builds the test parts: the split L-bracket (also used by the media), plus connector, stepped and dovetail cuts. |
| `docs/USER_GUIDE.md` | The user guide. |
| `docs/images/` | README media. `make_media.py` regenerates them. |

## Guidelines

- **Keep it simple.** Readable code beats clever code.
- **Add a test** for any bug you fix or behavior you add. The test part in `tests/make_test_parts.py` covers most cases. Add new shapes there if you need them.
- **Update the docs** (README, user guide, CHANGELOG under *Unreleased*) when behavior changes.
- Code style is checked by ruff (settings in `pyproject.toml`, 120-column lines).

## Regenerating the media

The banner and animation are drawn from the real test part. You need Google Chrome or Chromium, plus Pillow:

```bash
.venv/bin/pip install -e '.[media]'
.venv/bin/python docs/images/make_media.py
```

## Releasing

1. Set the new version in `src/stljoiner/version.py`.
2. Move the *Unreleased* notes in `CHANGELOG.md` under a heading for the new version, and update the links at the bottom.
3. Commit, then tag and push: `git tag -a vX.Y.Z -m "stljoiner X.Y.Z" && git push origin vX.Y.Z`.

The **Release** workflow then checks that the tag matches the version, runs the tests, builds the package, creates the GitHub release with that version's changelog notes, and uploads to PyPI using trusted publishing (no token needed).
