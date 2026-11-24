"""The `stljoiner` command.

    stljoiner PART.stl PART.stl ... [-o joined.stl]   join parts automatically
    stljoiner web [--port 4300]                       start the web interface
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args and args[0] == "web":
        from stljoiner import web  # Flask is only loaded for the web interface

        return web.main(args[1:])
    from stljoiner import join

    return join.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
