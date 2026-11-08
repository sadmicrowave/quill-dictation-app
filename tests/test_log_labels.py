"""The SYS / USR labels on the log: only SYS lines can ever go into a support report."""

import ast
import logging
import pathlib
import re
import tempfile
import unittest

from quill import diagnostics

ROOT = pathlib.Path(diagnostics.__file__).resolve().parent

#: The only argument shapes a SYS line may carry. Adding a new shape means someone looked at it and decided it holds nothing personal.
SAFE_ARGUMENTS = (
    r"^-?\d+(\.\d+)?$",                                   # a number
    r"^len\(.+\)$", r"^count$", r"^seconds$",              # counts
    r"^diagnostics\.exc_kind\(\w+\)$", r"^exc_kind\(\w+\)$",   # an error's class name
    r"^host_app\.name$",                                   # the spreadsheet program's name (a fixed list)
    r"^program(_name)?$",                                  # the same, from a live bridge's PROGRAM (LibreOffice / Numbers)
    r"^(self\.)?QUALITY_LABELS\[.+\]$",                    # Quick / Broad / Careful
    r"^event\.kind$",                                      # a fixed list of event kinds
    r"^__version__$", r"^platform\.\w+\(\)$",              # version and system facts
)


def _calls_with_sys_text(tree):
    """Yield (line, [argument nodes]) for every SYS call: syslog().x(...) and append_log(..., safe=...)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Call)
                and getattr(func.value.func, "id", getattr(func.value.func, "attr", "")) == "syslog"
                and func.attr in ("debug", "info", "warning", "error", "exception", "log")):
            args = node.args[1:] if func.attr == "log" else node.args
            if any(isinstance(a, ast.Starred) for a in args):   # append_log's own hand-over of a caller's wording
                continue
            yield node.lineno, args
        for kw in node.keywords:
            if kw.arg == "safe":
                value = kw.value
                yield node.lineno, list(value.elts) if isinstance(value, ast.Tuple) else [value]


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp())
        diagnostics.setup_logging(self.folder)
        self.addCleanup(lambda: [logging.getLogger("quill").removeHandler(h) or h.close()
                                 for h in list(logging.getLogger("quill").handlers) if getattr(h, "_quill_file", False)])

    def text(self):
        return (self.folder / diagnostics.LOG_NAME).read_text(encoding="utf-8")

    def test_an_ordinary_log_line_is_usr(self):
        logging.getLogger("quill.controller").info("Connected to Personal Debt.xlsx")
        self.assertRegex(self.text(), r"INFO USR Connected to Personal Debt\.xlsx")

    def test_only_the_sys_logger_writes_sys_lines(self):
        diagnostics.syslog().info("Connected to a spreadsheet: %d lists", 3)
        self.assertRegex(self.text(), r"INFO SYS Connected to a spreadsheet: 3 lists")

    def test_a_report_holds_sys_lines_and_nothing_else(self):
        logging.getLogger("quill").info("Heard: paid thirty dollars to Acme")
        diagnostics.syslog().info("Microphone on")
        lines = diagnostics.sys_lines(self.folder)
        self.assertTrue(any("Microphone on" in line for line in lines))
        self.assertFalse(any("Acme" in line or "paid" in line for line in lines))

    def test_unlabelled_lines_from_older_logs_never_go_in_a_report(self):
        (self.folder / diagnostics.LOG_NAME).write_text("2026-11-04 11:03:47,058 WARNING Not connected: Budget.xlsx\n", encoding="utf-8")
        self.assertEqual(diagnostics.sys_lines(self.folder), [])

    def test_a_sys_error_shows_code_locations_and_not_the_message(self):
        try:
            open("/Users/someone/Secret Budget.xlsx")
        except OSError as exc:
            diagnostics.syslog().warning("Could not open a file: %s", diagnostics.exc_kind(exc), exc_info=True)
        report = "\n".join(diagnostics.sys_lines(self.folder))
        self.assertIn("FileNotFoundError", report)
        self.assertIn(" at ", report)
        self.assertNotIn("Secret", report)
        self.assertNotIn("someone", report)
        self.assertNotIn("open(", report)                      # no source lines either

    def test_every_line_of_a_sys_traceback_is_labelled(self):
        try:
            {}["name"]
        except KeyError:
            diagnostics.syslog().error("Failed", exc_info=True)
        for line in self.text().splitlines():
            self.assertRegex(line, r"^\d{4}-\d\d-\d\d \S+ [A-Z]+ (SYS|USR) ")

    def test_a_usr_error_keeps_its_full_traceback_at_home(self):
        try:
            {}["name"]
        except KeyError:
            logging.getLogger("quill").exception("Failed")
        self.assertIn("Traceback", self.text())
        self.assertEqual([l for l in diagnostics.sys_lines(self.folder) if "Traceback" in l or "KeyError" in l], [])

    def test_the_report_facts_name_the_version_and_system(self):
        facts = diagnostics.environment_facts()
        for key in ("Quill", "System", "Computer", "Python"):
            self.assertIn(key, facts)


class TestSysWordingStaysSafe(unittest.TestCase):
    """Reads the code itself: a SYS line may only be built from fixed text and the safe argument shapes."""

    def sites(self):
        for path in sorted(ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for line, args in _calls_with_sys_text(tree):
                yield path, line, args

    def test_the_wording_is_a_fixed_string(self):
        found = 0
        for path, line, args in self.sites():
            found += 1
            first = args[0] if args else None
            self.assertTrue(isinstance(first, ast.Constant) and isinstance(first.value, str),
                            f"{path.name}:{line}: a SYS line must start with a fixed string, not an f-string or a variable")
        self.assertGreater(found, 20)                            # the scan really found the labelled calls

    def test_the_arguments_are_numbers_names_from_a_fixed_list_or_error_kinds(self):
        for path, line, args in self.sites():
            for arg in args[1:]:
                shown = ast.unparse(arg)
                fixed = isinstance(arg, ast.Constant) or (isinstance(arg, ast.IfExp) and isinstance(arg.body, ast.Constant)
                                                          and isinstance(arg.orelse, ast.Constant))     # text written in the code
                self.assertTrue(fixed or any(re.match(pattern, shown) for pattern in SAFE_ARGUMENTS),
                                f"{path.name}:{line}: {shown!r} is not a known-safe SYS argument (see SAFE_ARGUMENTS)")


if __name__ == "__main__":
    unittest.main()
