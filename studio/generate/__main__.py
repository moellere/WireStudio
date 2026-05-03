from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from studio.generate.ascii_gen import render_ascii
from studio.generate.yaml_gen import render_yaml
from studio.library import default_library
from studio.model import Design


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="studio.generate",
        description="Generate ESPHome YAML and ASCII diagram from a design.json.",
    )
    parser.add_argument("design", type=Path, help="path to design.json")
    parser.add_argument("--out-yaml", type=Path, default=None, help="write YAML to this path")
    parser.add_argument("--out-ascii", type=Path, default=None, help="write ASCII diagram to this path")
    args = parser.parse_args(argv)

    with args.design.open() as f:
        data = json.load(f)
    design = Design.model_validate(data)
    library = default_library()

    yaml_text = render_yaml(design, library)
    ascii_text = render_ascii(design, library)

    if args.out_yaml:
        args.out_yaml.write_text(yaml_text)
    else:
        sys.stdout.write("# ===== YAML =====\n")
        sys.stdout.write(yaml_text)

    if args.out_ascii:
        args.out_ascii.write_text(ascii_text + "\n")
    else:
        sys.stdout.write("\n# ===== ASCII =====\n")
        sys.stdout.write(ascii_text + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
