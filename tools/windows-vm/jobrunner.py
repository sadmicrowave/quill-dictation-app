"""The job runner of the Windows test VM: it watches a ``jobs`` folder in the shared folder and runs what it finds there, so a person (or Claude) at
the Mac can start a test in the VM without touching it. Python standard library only: it must start before anything of Quill's is built.

    jobs/<id>.json      a job: {"id", "kind", "args", "created"}   (written by ``send_job.py`` on the Mac)
    out/<id>/           what the job made: ``result.json`` (status, summary, checks), ``log.txt``, screenshots
    out/runner-alive.txt   rewritten every few seconds: the runner is up, and when it last looked

Run it by hand:   python jobrunner.py <share>          Make it start with Windows:   python jobrunner.py --install <share>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import time
import traceback

POLL_SECONDS = 2.0
#: Longest a job may run (seconds) by kind: a job that hangs is stopped and reported, not waited for.
TIMEOUTS = {"ping": 30, "sync": 900, "pytest": 3600, "looks": 600, "dictation": 600, "libreoffice": 900}
DEFAULT_TIMEOUT = 900
WORK = pathlib.Path(os.environ.get("QUILL_VM_WORK", r"C:\QuillTest" if os.name == "nt" else str(pathlib.Path.home() / "QuillTest")))
ALIVE_NAME = "runner-alive.txt"


def console_python(python: str = sys.executable) -> str:
    """The Python that runs commands: ``pythonw.exe`` (which starts with no window, so the runner itself uses it) has no output to report errors in, so
    the commands the runner starts use ``python.exe`` beside it (and are hidden by the flags they are started with)."""
    path = pathlib.Path(python)
    sibling = path.with_name("python.exe")
    return str(sibling) if path.name.lower() == "pythonw.exe" and sibling.is_file() else python


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def write_json(path: pathlib.Path, data) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)                                              # (never a half-written file for the reader)


def result(status: str, summary: str, checks: list | None = None) -> dict:
    """What a handler returns: *status* is ``passed``, ``failed`` (a check did not hold) or ``error`` (the job itself broke)."""
    return {"status": status, "summary": summary, "checks": checks or []}


class Runner:
    """Watches ``<share>/jobs`` and runs each job once, oldest first."""

    def __init__(self, share: pathlib.Path, work: pathlib.Path = WORK, python: str | None = None, handlers: dict | None = None,
                 restart=None) -> None:
        self.share, self.work = pathlib.Path(os.path.normpath(str(share))), pathlib.Path(work)
        self.python = python or console_python()
        self.restart = restart or self._restart
        self.jobs = self.share / "jobs"
        self.out = self.share / "out"
        self.handlers = dict(HANDLERS if handlers is None else handlers)
        for folder in (self.jobs, self.jobs / "running", self.jobs / "done", self.out):
            folder.mkdir(parents=True, exist_ok=True)

    @property
    def src(self) -> pathlib.Path:
        return self.work / "src"

    @property
    def installed_script(self) -> pathlib.Path:
        return self.work / "jobrunner" / "jobrunner.py"

    def newer_script(self) -> pathlib.Path | None:
        """The runner's own file in the synced code, when it differs from the one running (so a new runner is picked up by itself)."""
        import hashlib
        offered = self.share / "src" / "tools" / "windows-vm" / "jobrunner.py"
        if not offered.is_file() or not self.installed_script.is_file():
            return None
        same = hashlib.sha256(offered.read_bytes()).digest() == hashlib.sha256(self.installed_script.read_bytes()).digest()
        return None if same else offered

    def update_if_newer(self) -> bool:
        """Replace the running file with the newer one and start it in this one's place. True when it did (the caller stops)."""
        offered = self.newer_script()
        if offered is None:
            return False
        shutil.copyfile(offered, self.installed_script)
        self.restart()
        return True

    def _restart(self) -> None:
        subprocess.Popen([sys.executable, str(self.installed_script), str(self.share)],              # noqa: S603
                         **({"creationflags": 0x08000000 | 0x00000008} if os.name == "nt" else {}))

    def heartbeat(self) -> None:
        (self.out / ALIVE_NAME).write_text(f"{now()}\nhost={platform.node()}\npython={sys.version.split()[0]}\nwork={self.work}\n", encoding="utf-8")

    def pending(self) -> list[pathlib.Path]:
        return sorted(self.jobs.glob("*.json"), key=lambda p: (p.stat().st_mtime, p.name))

    def poll_once(self) -> bool:
        """Run the oldest waiting job, if any. True when one was run."""
        self.heartbeat()
        waiting = self.pending()
        if not waiting:
            return False
        self.run_job(waiting[0])
        return True

    def run_job(self, path: pathlib.Path) -> dict:
        running = self.jobs / "running" / path.name
        path.replace(running)
        try:
            job = json.loads(running.read_text(encoding="utf-8"))
        except ValueError as exc:
            job = {"id": path.stem, "kind": "?", "args": {}}
            outcome = result("error", f"the job file could not be read: {exc}")
        else:
            outcome = None
        job.setdefault("id", path.stem)
        job.setdefault("args", {})
        folder = self.out / str(job["id"])
        folder.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        started_at = now()
        if outcome is None:
            handler = self.handlers.get(job.get("kind"))
            if handler is None:
                outcome = result("error", f"unknown job kind {job.get('kind')!r} (known: {', '.join(sorted(self.handlers))})")
            else:
                try:
                    outcome = handler(self, job, folder)
                except Exception:                                       # noqa: BLE001 (a job that breaks must be reported, not stop the runner)
                    outcome = result("error", "the job raised an error", [{"name": "traceback", "ok": False, "detail": traceback.format_exc()}])
        outcome.update({"id": job["id"], "kind": job.get("kind"), "started": started_at, "finished": now(), "seconds": round(time.monotonic() - started, 1)})
        write_json(folder / "result.json", outcome)
        running.replace(self.jobs / "done" / path.name)
        return outcome

    def write_pid(self) -> None:
        self.installed_script.parent.mkdir(parents=True, exist_ok=True)
        (self.installed_script.parent / "runner.pid").write_text(str(os.getpid()), encoding="utf-8")

    def serve(self, stop=lambda: False) -> None:
        self.write_pid()
        while not stop():
            if not self.poll_once():
                if self.update_if_newer():
                    return                                   # (the new runner has been started: this one ends)
                time.sleep(POLL_SECONDS)


# ---- handlers ---------------------------------------------------------------------------------------------------------------------------------

def run_command(runner: Runner, args: list[str], folder: pathlib.Path, timeout: int, cwd: pathlib.Path | None = None, env: dict | None = None,
                log: str = "log.txt") -> int:
    """Run *args*, append its output to ``<folder>/<log>`` and return its exit code (124 when it had to be stopped)."""
    environment = {**os.environ, **(env or {})}
    with (folder / log).open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(f"$ {' '.join(args)}\n")
        handle.flush()
        try:
            done = subprocess.run(args, cwd=str(cwd or runner.src), stdout=handle, stderr=subprocess.STDOUT, timeout=timeout, env=environment,
                                  check=False, **({"creationflags": 0x08000000} if os.name == "nt" else {}))
            return done.returncode
        except subprocess.TimeoutExpired:
            handle.write(f"\n[stopped after {timeout} s]\n")
            return 124


def handle_ping(runner: Runner, job: dict, folder: pathlib.Path) -> dict:
    return result("passed", f"the runner is up on {platform.node()} ({platform.platform()}), python {sys.version.split()[0]}",
                  [{"name": "echo", "ok": True, "detail": json.dumps(job.get("args", {}))}])


def requirements_hash(src: pathlib.Path) -> str:
    import hashlib
    return hashlib.sha256((src / "requirements.txt").read_bytes()).hexdigest() if (src / "requirements.txt").is_file() else ""


def handle_sync(runner: Runner, job: dict, folder: pathlib.Path) -> dict:
    """Copy the code the Mac synced (``<share>/src``) to the VM's own folder, and install the requirements when they changed."""
    source = runner.share / "src"
    if not (source / "main.py").is_file():
        return result("error", f"no Quill code at {source}: run tools/windows-vm/sync-to-share.sh on the Mac")
    runner.src.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        code = run_command(runner, ["robocopy", str(source), str(runner.src), "/MIR", "/XD", "__pycache__", "build", "dist", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
                           folder, 600, cwd=runner.work)
        if code >= 8:
            return result("error", f"copying the code failed (robocopy exit code {code})")
    else:
        if runner.src.exists():
            shutil.rmtree(runner.src)
        shutil.copytree(source, runner.src, ignore=shutil.ignore_patterns("__pycache__", "build", "dist"))
    marker = runner.work / "requirements.sha"
    wanted = requirements_hash(runner.src)
    notes = []
    if wanted and (not marker.is_file() or marker.read_text(encoding="utf-8").strip() != wanted) and not job["args"].get("no_install"):
        code = run_command(runner, [runner.python, "-m", "pip", "install", "-r", "requirements.txt"], folder, 1500)
        if code != 0:
            return result("error", f"installing the requirements failed (exit code {code}): see log.txt")
        marker.write_text(wanted, encoding="utf-8")
        notes.append("requirements installed")
    stamp = runner.src / "quill" / "_build.py"
    build = stamp.read_text(encoding="utf-8").strip() if stamp.is_file() else "(no build stamp)"
    return result("passed", f"code synced: {build}" + (f"; {', '.join(notes)}" if notes else ""))


def ensure_test_tools(runner: Runner, folder: pathlib.Path) -> str | None:
    """Make sure pytest (and pytest-xdist, for parallel runs) are in the VM's Python: the requirements file does not list them. None when fine, else why not."""
    probe = subprocess.run([runner.python, "-c", "import pytest, xdist"], capture_output=True, timeout=60, check=False,
                           **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    if probe.returncode == 0:
        return None
    code = run_command(runner, [runner.python, "-m", "pip", "install", "pytest", "pytest-xdist"], folder, 900, cwd=runner.work)
    return None if code == 0 else f"installing pytest failed (exit code {code}): see log.txt"


def parse_pytest(log: pathlib.Path) -> str:
    lines = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    return next((line for line in reversed(lines) if " passed" in line or " failed" in line or " error" in line), "(no pytest summary line)")


def handle_pytest(runner: Runner, job: dict, folder: pathlib.Path) -> dict:
    """Run the test suite on this machine. args: ``paths`` (list), ``k`` (expression), ``full`` (bool), ``native`` (real Windows display plugin),
    ``workers`` (parallel processes: a number or ``auto``)."""
    args = job["args"]
    problem = ensure_test_tools(runner, folder)
    if problem:
        return result("error", problem)
    command = [runner.python, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={folder / 'junit.xml'}", *args.get("paths", [])]
    if args.get("workers"):
        command += ["-n", str(args["workers"])]
    if args.get("k"):
        command += ["-k", str(args["k"])]
    env = {"QUILL_FULL": "1"} if args.get("full") else {}
    if args.get("native"):
        env["QT_QPA_PLATFORM"] = "windows" if os.name == "nt" else "cocoa"      # the real display plugin, not the headless one
    code = run_command(runner, command, folder, TIMEOUTS["pytest"], env=env)
    summary = parse_pytest(folder / "log.txt")
    if code == 124:
        return result("error", f"the tests were stopped (too long): {summary}")
    return result("passed" if code == 0 else "failed", summary, [{"name": "pytest exit code", "ok": code == 0, "detail": str(code)}])


def handle_script(name: str):
    """A job that runs ``tools/vm_journeys/<name>.py --out <folder>`` and reads the ``checks.json`` it writes."""
    def handler(runner: Runner, job: dict, folder: pathlib.Path) -> dict:
        script = runner.src / "tools" / "vm_journeys" / f"{name}.py"
        if not script.is_file():
            return result("error", f"{script} is missing: run a sync job first")
        command = [runner.python, str(script), "--out", str(folder), *[str(a) for a in job["args"].get("argv", [])]]
        code = run_command(runner, command, folder, TIMEOUTS.get(name, DEFAULT_TIMEOUT), env=job["args"].get("env", {}))
        checks_file = folder / "checks.json"
        checks = json.loads(checks_file.read_text(encoding="utf-8")) if checks_file.is_file() else []
        failed = [c for c in checks if not c.get("ok")]
        if code == 124:
            return result("error", f"{name} was stopped (too long)", checks)
        if code != 0 and not checks:
            return result("error", f"{name} stopped with exit code {code} before it wrote its checks: see log.txt", checks)
        passed = len(checks) - len(failed)
        return result("failed" if failed or code != 0 else "passed", f"{passed} of {len(checks)} checks held" + (f"; failed: {', '.join(c['name'] for c in failed)}" if failed else ""), checks)
    return handler


HANDLERS = {"ping": handle_ping, "sync": handle_sync, "pytest": handle_pytest,
            "looks": handle_script("looks"), "dictation": handle_script("dictation"), "libreoffice": handle_script("libreoffice")}


# ---- start with Windows -------------------------------------------------------------------------------------------------------------------------

def startup_folder() -> pathlib.Path:
    return pathlib.Path(os.environ.get("APPDATA", str(pathlib.Path.home()))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def launcher_text(python: str, script: pathlib.Path, share: str) -> str:
    """A tiny Windows script that starts the runner with no window."""
    pythonw = str(pathlib.Path(python).with_name("pythonw.exe"))
    quote = lambda s: '"' + s.replace('"', '""') + '"'                  # noqa: E731 (VBScript doubles its quotes)
    command = f'{quote(pythonw)} {quote(str(script))} {quote(share)}'
    return f'CreateObject("WScript.Shell").Run {quote(command)}, 0, False\r\n'


def install(share: str) -> pathlib.Path:
    """Copy this file to the VM's own folder and make Windows start it at every sign-in (and start it now, in place of one already running)."""
    WORK.mkdir(parents=True, exist_ok=True)
    folder = WORK / "jobrunner"
    folder.mkdir(exist_ok=True)
    stop_running(folder)
    script = folder / "jobrunner.py"
    shutil.copyfile(__file__, script)
    launcher = startup_folder() / "Quill job runner.vbs"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text(launcher_text(sys.executable, script, share), encoding="utf-8")
    if os.name == "nt":
        subprocess.Popen(["wscript.exe", str(launcher)], creationflags=0x08000000)         # noqa: S603, S607
    return launcher


def stop_running(folder: pathlib.Path) -> bool:
    """End a runner that is already running (its process number is in ``runner.pid``), so two never take the same job."""
    pid_file = folder / "runner.pid"
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    if pid == os.getpid():
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=30, check=False, creationflags=0x08000000)    # noqa: S603, S607
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            return False
    pid_file.unlink(missing_ok=True)
    return True


def uninstall() -> bool:
    launcher = startup_folder() / "Quill job runner.vbs"
    existed = launcher.is_file()
    launcher.unlink(missing_ok=True)
    return existed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the test jobs the Mac leaves in the shared folder.")
    parser.add_argument("share", nargs="?", default=r"\\vmware-host\Shared Folders\QuillShare", help="the shared folder (holds jobs, out, src)")
    parser.add_argument("--install", action="store_true", help="start with Windows, and start now")
    parser.add_argument("--uninstall", action="store_true", help="stop starting with Windows")
    parser.add_argument("--once", action="store_true", help="run the waiting jobs and stop")
    args = parser.parse_args(argv)
    if args.uninstall:
        print("removed" if uninstall() else "was not installed")
        return 0
    if args.install:
        print(f"installed: {install(args.share)}")
        return 0
    runner = Runner(pathlib.Path(args.share))
    if args.once:
        while runner.poll_once():
            pass
        return 0
    runner.serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())
