# Contributing to stljoiner

Thank you for taking the time to contribute! Bug reports, ideas and pull requests are all welcome.

## Reporting a problem

Open an [issue](https://github.com/drak42/stljoiner/issues/new/choose). The most useful thing you can attach is the **STL pieces that don't join correctly** (zipped), plus a note on how they were split.

For security problems, please follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

```bash
uv venv
uv pip install -r requirements.txt pytest
```

Before committing, run the same checks as GitHub Actions:

```bash
uvx ruff check .
.venv/bin/python -m pytest -q
```

## Project layout

| Path | What it is |
|---|---|
| `stljoin.py` | The joining engine and the command line: face extraction, matching, alignment, assembly, union. |
| `app.py` | The Flask web server and its JSON API. |
| `static/index.html` | The web page (three.js viewer, face picking). |
| `tests/` | pytest suite. `make_test_parts.py` builds the split L-bracket the tests and media use. |
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
uv pip install pillow
.venv/bin/python docs/images/make_media.py
```

## Releasing

1. Update the version in `pyproject.toml` and `__version__` in `stljoin.py`.
2. Move the *Unreleased* notes in `CHANGELOG.md` under the new version.
3. Tag `vX.Y.Z` and create a GitHub release with those notes.
