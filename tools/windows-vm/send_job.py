"""Mac side of the VM job runner: leave a job in the shared folder and wait for the answer.

    python tools/windows-vm/send_job.py ping
    python tools/windows-vm/send_job.py sync                       # copy the code the last sync-to-share.sh left, install requirements
    python tools/windows-vm/send_job.py pytest --k windows         # pytest on Windows (--full, --native, --workers auto, --path tests/x.py)
    python tools/windows-vm/send_job.py looks | dictation | libreoffice

Prints the result, the checks that failed and where the screenshots are (``~/Developer/QuillShare/out/<id>/``). Exit code 0 only when it passed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
import time

DEFAULT_SHARE = pathlib.Path.home() / "Developer" / "QuillShare"
ALIVE = "runner-alive.txt"
KINDS = ("ping", "sync", "pytest", "looks", "dictation", "libreoffice")


def submit(share: pathlib.Path, kind: str, args: dict | None = None) -> str:
    """Write a job and return its id. (Written under a temporary name and renamed, so the runner never reads half a file.)"""
    jobs = pathlib.Path(share) / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    job_id = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{kind}"
    path = jobs / f"{job_id}.json"
    n = 1
    while path.exists() or (jobs / "done" / path.name).exists():
        n += 1
        job_id = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{kind}-{n}"
        path = jobs / f"{job_id}.json"
    temporary = jobs / f"{job_id}.tmp"
    temporary.write_text(json.dumps({"id": job_id, "kind": kind, "args": args or {}, "created": dt.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    temporary.replace(path)
    return job_id


def runner_age(share: pathlib.Path) -> float | None:
    """Seconds since the runner last said it was alive (None: never)."""
    mark = pathlib.Path(share) / "out" / ALIVE
    return time.time() - mark.stat().st_mtime if mark.is_file() else None


def wait(share: pathlib.Path, job_id: str, timeout: float, poll: float = 2.0, sleep=time.sleep) -> dict | None:
    """The job's ``result.json`` once it is there, or None when *timeout* seconds pass."""
    result = pathlib.Path(share) / "out" / job_id / "result.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result.is_file():
            try:
                return json.loads(result.read_text(encoding="utf-8"))
            except ValueError:
                pass
        sleep(poll)
    return None


def report(share: pathlib.Path, outcome: dict) -> str:
    folder = pathlib.Path(share) / "out" / outcome["id"]
    lines = [f"{outcome['status'].upper()}: {outcome['summary']}  ({outcome['seconds']} s)"]
    for check in outcome.get("checks", []):
        if not check.get("ok"):
            lines.append(f"  FAILED {check['name']}: {str(check.get('detail', ''))[:300]}")
    files = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
    lines.append(f"  files in {folder}: {', '.join(files) or '(none)'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("--share", type=pathlib.Path, default=DEFAULT_SHARE)
    parser.add_argument("--wait", type=float, default=900, help="seconds to wait for the answer")
    parser.add_argument("--k", help="pytest: only tests matching this expression")
    parser.add_argument("--path", action="append", default=[], help="pytest: a test file or folder (repeatable)")
    parser.add_argument("--full", action="store_true", help="pytest: every test, the slow ones too")
    parser.add_argument("--native", action="store_true", help="pytest: the real display plugin instead of the headless one")
    parser.add_argument("--workers", help="pytest: run in parallel with this many processes (a number, or auto)")
    parser.add_argument("--no-install", action="store_true", help="sync: do not install requirements")
    args = parser.parse_args(argv)
    age = runner_age(args.share)
    if age is None or age > 30:
        print(f"The job runner does not look alive (last seen: {'never' if age is None else f'{int(age)} s ago'}). In the VM run "
              "'Install job runner.bat' once, or start it by hand; the job is left waiting.")
    job_args: dict = {}
    if args.kind == "pytest":
        job_args = {"paths": args.path, "k": args.k, "full": args.full, "native": args.native, "workers": args.workers}
    if args.kind == "sync":
        job_args = {"no_install": args.no_install}
    job_id = submit(args.share, args.kind, job_args)
    print(f"job {job_id} left; waiting up to {int(args.wait)} s ...")
    outcome = wait(args.share, job_id, args.wait)
    if outcome is None:
        print("no answer yet: the job is still waiting or running (look in jobs/ and out/ of the shared folder)")
        return 2
    print(report(args.share, outcome))
    return 0 if outcome["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
