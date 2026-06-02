"""Compile the valeri_api package to native extensions (client distribution).

Used by the `dist` Docker target (decision D10 in docs/specs/m0-foundation.md):
images delivered to clients must not contain readable VALERI source code.
Every module in valeri_api/ is compiled to a native .so and the .py sources
(and intermediate .c files) are removed afterwards. __init__.py files are kept
so the package structure stays importable.

Run from apps/api:  python build_ext.py
"""

import sys
from pathlib import Path

from Cython.Build import cythonize
from setuptools import Distribution
from setuptools.command.build_ext import build_ext

PACKAGE = Path("valeri_api")


def find_modules() -> list[str]:
    """Every .py in the package except __init__.py (kept for package structure)."""
    return [str(p) for p in sorted(PACKAGE.rglob("*.py")) if p.name != "__init__.py"]


def main() -> None:
    modules = find_modules()
    if not modules:
        print("nothing to compile", file=sys.stderr)
        return

    ext_modules = cythonize(
        modules,
        compiler_directives={"language_level": "3"},
        quiet=True,
    )

    dist = Distribution({"ext_modules": ext_modules})
    cmd = build_ext(dist)
    cmd.inplace = True  # write each .so next to its source module
    cmd.ensure_finalized()
    cmd.run()

    # Strip sources and intermediate C files: binaries only in the dist image.
    for module in modules:
        Path(module).unlink()
        Path(module).with_suffix(".c").unlink(missing_ok=True)

    print(f"compiled {len(modules)} modules to native extensions", file=sys.stderr)


if __name__ == "__main__":
    main()
