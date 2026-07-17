"""Specctra DSN/SES bridge, run under the *system* python that has pcbnew.

kicad-cli has no Specctra support; the headless path is the pcbnew SWIG
module, which lives in KiCad's own python environment, not the app's. This
script is therefore dependency-free (stdlib + pcbnew only) so route.py can
invoke it as ``<pcbnew-python> pcbnew_bridge.py <cmd> ...`` regardless of
which interpreter carries the bindings.

Commands:
    probe                       print the pcbnew build version
    dsn <board> <out.dsn>       export a Specctra DSN
    ses <board> <in.ses>        import a routed session into <board> in place

Requires KiCad >= 8: the standalone ImportSpecctraSES(BOARD, path) overload
does not exist in KiCad 7.
"""
import sys


def main() -> int:
    import pcbnew

    cmd = sys.argv[1]
    if cmd == "probe":
        if not hasattr(pcbnew, "ImportSpecctraSES"):
            print("pcbnew lacks ImportSpecctraSES (KiCad >= 8 required)", file=sys.stderr)
            return 1
        print(pcbnew.GetBuildVersion())
        return 0
    if cmd == "dsn":
        board = pcbnew.LoadBoard(sys.argv[2])
        if not pcbnew.ExportSpecctraDSN(board, sys.argv[3]):
            print("ExportSpecctraDSN failed", file=sys.stderr)
            return 1
        return 0
    if cmd == "ses":
        board_path, ses_path = sys.argv[2], sys.argv[3]
        board = pcbnew.LoadBoard(board_path)
        if not pcbnew.ImportSpecctraSES(board, ses_path):
            print("ImportSpecctraSES failed", file=sys.stderr)
            return 1
        pcbnew.SaveBoard(board_path, board)
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
