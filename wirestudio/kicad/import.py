"""`python -m wirestudio.kicad.import` entrypoint.

The filename is the `import` keyword on purpose: it matches the
documented command spelling. `-m` resolves a module by string, so this
runs fine; internal callers import `wirestudio.kicad.importer` instead
(a literal `import` statement can't name this file).
"""
from wirestudio.kicad.importer import main

if __name__ == "__main__":
    raise SystemExit(main())
