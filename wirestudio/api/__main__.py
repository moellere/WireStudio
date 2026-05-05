from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    parser = argparse.ArgumentParser(prog="wirestudio.api", description="Run the wirestudio HTTP API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true", help="reload on source changes (dev only)")
    parser.add_argument(
        "--static-dir",
        default=os.environ.get("WIRESTUDIO_STATIC_DIR"),
        help=(
            "Serve the built web bundle from this directory at `/`, "
            "with the API mounted at `/api/*`. Used by the production "
            "Docker image; leave unset for dev (Vite handles the SPA)."
        ),
    )
    args = parser.parse_args(argv)

    if args.static_dir:
        # wirestudio.api.serve reads WIRESTUDIO_STATIC_DIR at import time, so
        # propagate the flag through the env so reload-spawned workers
        # see it too.
        os.environ["WIRESTUDIO_STATIC_DIR"] = args.static_dir
        target = "wirestudio.api.serve:app"
    else:
        target = "wirestudio.api.app:app"

    uvicorn.run(
        target,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
