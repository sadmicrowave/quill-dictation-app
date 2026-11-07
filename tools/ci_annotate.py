"""Show the end of a log as a GitHub Actions error annotation, so a failed run can be read without opening the full log
(annotations are visible on the run page and through the API; raw logs need a sign-in).

Usage: python tools/ci_annotate.py TITLE LOGFILE [LINES]
"""
import pathlib
import sys


def main(argv: list[str]) -> int:
    title, path = argv[1], pathlib.Path(argv[2])
    lines = int(argv[3]) if len(argv) > 3 else 60
    text = path.read_text(errors="replace") if path.is_file() else "(no log)"
    tail = "\n".join(text.splitlines()[-lines:])
    safe = tail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title={title}::{safe[:60000]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
