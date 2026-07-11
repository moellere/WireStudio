from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wirestudio.csp.compatibility import strict_blockers
from wirestudio.generate.ascii_gen import render_ascii
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import default_library
from wirestudio.model import Design


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wirestudio.generate",
        description="Generate ESPHome YAML and ASCII diagram from a design.json.",
    )
    parser.add_argument("design", type=Path, help="path to design.json")
    parser.add_argument("--out-yaml", type=Path, default=None, help="write YAML to this path")
    parser.add_argument("--out-ascii", type=Path, default=None, help="write ASCII diagram to this path")
    parser.add_argument(
        "--strict", action="store_true",
        help="refuse to generate when warn/error compatibility or design "
             "warnings remain (overrides the design's own strict flag)",
    )
    args = parser.parse_args(argv)

    with args.design.open() as f:
        data = json.load(f)
    design = Design.model_validate(data)
    library = default_library()

    if args.strict or design.strict:
        blockers = strict_blockers(data, library)
        if blockers:
            sys.stderr.write(
                f"strict mode blocked generation: {len(blockers)} issue"
                f"{'s' if len(blockers) != 1 else ''} need attention\n"
            )
            for b in blockers:
                sys.stderr.write(f"  [{b.severity}] {b.code}: {b.detail}\n")
            return 1

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
