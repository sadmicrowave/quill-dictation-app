"""The live link to LibreOffice: the helper's server (the real script, run here against pretend documents) and Quill's side."""

import json
import pathlib
import socket
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from quill.bridge.libreoffice_live import LiveLink
from quill.bridge.libreoffice_mirror import SCRIPT_VERSION, LibreOfficeMirror, file_addresses


class Cell:
    def __init__(self): self.text, self.number, self.NumberFormat = "", None, 0
    def setString(self, text): self.text = text
    def setValue(self, number): self.number = number


class Sheets:
    def __init__(self, names): self.cells = {n: {} for n in names}
    def getElementNames(self): return list(self.cells)
    def hasByName(self, name): return name in self.cells
    def getByName(self, name): return Sheet(name, self.cells[name])
    def getByIndex(self, i): n = list(self.cells)[i]; return Sheet(n, self.cells[n])


class Sheet:
    def __init__(self, name, cells): self.Name, self._cells = name, cells
    def getCellByPosition(self, c, r): return self._cells.setdefault((c, r), Cell())


class Document:
    """Just enough of a LibreOffice spreadsheet document."""

    def __init__(self, url, names=("Sheet1", "Sheet2")):
        self.URL, self.sheets, self.active, self.modified, self.saved = url, Sheets(names), names[0], True, 0
    def supportsService(self, name): return name == "com.sun.star.sheet.SpreadsheetDocument"
    def getCurrentController(self): return self
    def getActiveSheet(self): return Sheet(self.active, self.sheets.cells[self.active])
    def getSheets(self): return self.sheets
    def isModified(self): return self.modified
    def store(self): self.saved += 1; self.modified = False


class FakeLibreOffice:
    """The desktop: the open documents."""

    def __init__(self): self.documents = []
    def getDesktop(self): return self
    def getComponents(self): return self
    def createEnumeration(self):
        items = list(self.documents)
        return types.SimpleNamespace(hasMoreElements=lambda: bool(items), nextElement=lambda: items.pop(0))


class LiveCase(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict("os.environ", {}, clear=False)       # (the suite switches the programs off; these tests use pretend ones)
        env.start()
        self.addCleanup(env.stop)
        __import__("os").environ.pop("QUILL_NO_HOSTS", None)
        self.base = pathlib.Path(tempfile.mkdtemp())
        self.lo = FakeLibreOffice()
        self.path = pathlib.Path(tempfile.mkdtemp()) / "Budget.xlsx"
        self.path.write_bytes(b"x")
        self.doc = Document(file_addresses(self.path)[0])
        self.lo.documents.append(self.doc)
        self.mirror = LibreOfficeMirror(base=self.base, scripts_dir=self.base / "scripts", running=lambda: True,
                                        soffice="/x/soffice", wait_s=2, runner=self.run_soffice, live_retry_s=0)
        (self.base / "user").mkdir(exist_ok=True)
        self.namespace = None
        self.launches = []
        self.addCleanup(self.stop)

    def load_script(self):
        """Run the installed script's text as LibreOffice would, with a pretend desktop."""
        namespace = {"XSCRIPTCONTEXT": self.lo, "__name__": "quill_mirror"}
        exec(compile(self.mirror.script_text().replace("WATCH_S = 0.3", "WATCH_S = 0.03"), "quill_mirror.py", "exec"), namespace)
        return namespace

    def run_soffice(self, args):
        """What launching ``soffice --headless <script address>`` does: LibreOffice runs the entry point."""
        entry = args[-1].split("$", 1)[1].split("?", 1)[0]
        self.launches.append(entry)
        if self.namespace is None:
            self.namespace = self.load_script()
        self.namespace[entry]()
        return 0

    def stop(self):
        self.mirror._live and self.mirror._live.close()
        server = getattr(__import__("sys"), "_quill_live", None)
        if server is not None:
            server.stop()
            del __import__("sys")._quill_live

    def wait_for(self, condition, seconds=3.0):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if condition():
                return True
            time.sleep(0.02)
        return condition()


class TestServerAndLink(LiveCase):
    def link(self, events=None):
        self.namespace = self.load_script()
        self.namespace["serve"]()
        link = LiveLink(self.base, on_event=(lambda *a: events.append(a)) if events is not None else None)
        self.assertTrue(link.connect())
        self.addCleanup(link.close)
        return link

    def test_the_link_knows_what_is_open_and_which_sheet(self):
        link = self.link()
        doc = link.find(file_addresses(self.path))
        self.assertEqual((doc["sheet"], doc["sheets"]), ("Sheet1", ["Sheet1", "Sheet2"]))

    def test_the_secret_and_address_are_in_a_file_only_the_owner_can_read(self):
        self.link()
        mode = (self.base / "live.json").stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)
        info = json.loads((self.base / "live.json").read_text())
        self.assertEqual(set(info), {"port", "token", "version", "pid"})

    def test_a_connection_without_the_secret_is_refused(self):
        self.link()
        info = json.loads((self.base / "live.json").read_text())
        sock = socket.create_connection(("127.0.0.1", info["port"]), 2)
        sock.sendall(b'{"hello": "wrong"}\n')
        sock.settimeout(2)
        self.assertEqual(sock.recv(100), b"")                      # hung up on, nothing said
        sock.close()

    def test_a_move_to_another_sheet_is_pushed_at_once(self):
        events = []
        link = self.link(events)
        self.doc.active = "Sheet2"
        self.assertTrue(self.wait_for(lambda: events))
        self.assertEqual(events[0], ("sheet", self.doc.URL, "Sheet2"))
        self.assertEqual(link.find([self.doc.URL])["sheet"], "Sheet2")

    def test_a_new_sheet_and_its_name_are_pushed(self):
        events = []
        link = self.link(events)
        self.doc.sheets.cells["Sheet3"] = {}
        self.doc.active = "Sheet3"
        self.assertTrue(self.wait_for(lambda: events))
        self.assertEqual(link.find([self.doc.URL])["sheets"], ["Sheet1", "Sheet2", "Sheet3"])

    def test_opening_and_closing_documents_are_pushed(self):
        events = []
        link = self.link(events)
        other = Document("file:///tmp/Other.xlsx")
        self.lo.documents.append(other)
        self.assertTrue(self.wait_for(lambda: any(e[0] == "opened" for e in events)))
        self.lo.documents.remove(other)
        self.assertTrue(self.wait_for(lambda: any(e[0] == "closed" for e in events)))
        self.assertIsNone(link.find(["file:///tmp/Other.xlsx"]))

    def test_save_and_cell_writes_are_requests_on_the_link(self):
        link = self.link()
        urls = file_addresses(self.path)
        self.assertTrue(link.request("save", urls=urls)["ok"])
        self.assertEqual(self.doc.saved, 1)
        changes = [["Sheet2", 3, 2, "s", "hello"], ["Sheet2", 3, 3, "n", "4.5"]]
        self.assertTrue(link.request("apply", urls=urls, changes=changes)["ok"])
        cells = self.doc.sheets.cells["Sheet2"]
        self.assertEqual(cells[(1, 2)].text, "hello")
        self.assertEqual(cells[(2, 2)].number, 4.5)

    def test_a_document_that_is_not_open_is_reported_not_guessed(self):
        link = self.link()
        answer = link.request("save", urls=["file:///nowhere.xlsx"])
        self.assertEqual((answer["ok"], answer["error"]), (False, "nodoc"))

    def test_only_the_fixed_commands_are_understood(self):
        link = self.link()
        answer = link.request("exec", urls=file_addresses(self.path), code="import os")
        self.assertFalse(answer["ok"])

    def test_losing_the_server_is_noticed(self):
        events = []
        link = self.link(events)
        self.namespace["serve"]                                      # (the server is in sys._quill_live)
        __import__("sys")._quill_live.stop()
        self.assertTrue(self.wait_for(lambda: not link.connected))
        self.assertTrue(any(e[0] == "lost" for e in events))
        self.assertIsNone(link.request("state"))


class TestMirrorUsesTheLink(LiveCase):
    def test_the_first_question_starts_the_server_and_later_ones_start_nothing(self):
        self.assertEqual(self.mirror.active_sheet(self.path), "Sheet1")
        self.assertEqual(self.launches, ["serve"])
        self.assertTrue(self.mirror.live_connected)
        self.assertEqual(self.mirror.active_sheet(self.path), "Sheet1")
        self.assertTrue(self.mirror.has_document(self.path))
        self.assertEqual(self.launches, ["serve"])                  # no more launches: the answer is already known

    def test_the_sheet_it_reports_follows_the_document_without_asking_again(self):
        self.mirror.active_sheet(self.path)
        self.doc.active = "Sheet2"
        self.assertTrue(self.wait_for(lambda: self.mirror.active_sheet(self.path) == "Sheet2"))
        self.assertEqual(self.launches, ["serve"])

    def test_events_reach_the_listener(self):
        events = []
        self.mirror.on_event = lambda *a: events.append(a)
        self.mirror.active_sheet(self.path)
        self.doc.active = "Sheet2"
        self.assertTrue(self.wait_for(lambda: events))
        self.assertEqual(events[-1][0], "sheet")

    def test_saving_and_writing_go_over_the_link(self):
        self.mirror.active_sheet(self.path)
        self.assertTrue(self.mirror.save(self.path))
        self.assertEqual(self.doc.saved, 1)
        result = self.mirror.push(self.path, [("Sheet1", 2, 1, "x")])
        self.assertTrue(result.ok)
        self.assertEqual(self.doc.sheets.cells["Sheet1"][(0, 1)].text, "x")
        self.assertEqual(self.launches, ["serve"])

    def test_a_file_that_is_not_open_there_is_nodoc(self):
        self.mirror.active_sheet(self.path)
        self.assertFalse(self.mirror.has_document(self.path.with_name("Other.xlsx")))

    def test_without_a_server_it_falls_back_to_the_older_way(self):
        calls = []
        self.mirror.runner = lambda args: calls.append(args[-1].split("$")[1].split("?")[0]) or 1       # nothing starts
        self.assertIsNone(self.mirror.active_sheet(self.path))
        self.assertIn("serve", calls)
        self.assertIn("apply", calls)                               # the one-off job was tried afterwards

    def test_a_failed_start_is_not_retried_at_every_look(self):
        calls = []
        self.mirror.runner = lambda args: calls.append(args) or 1
        self.mirror.live_retry_s = 60
        self.mirror.active_sheet(self.path)
        count = sum(1 for c in calls if "$serve" in c[-1])
        self.mirror.active_sheet(self.path)
        self.assertEqual(sum(1 for c in calls if "$serve" in c[-1]), count)

    def test_a_newer_helper_replaces_an_older_server(self):
        self.mirror.active_sheet(self.path)
        sys = __import__("sys")
        sys._quill_live.version = SCRIPT_VERSION - 1                # pretend the running server is from an older helper
        self.mirror._live.version = SCRIPT_VERSION - 1
        self.mirror.active_sheet(self.path)
        self.assertEqual(sys._quill_live.version, SCRIPT_VERSION)
        self.assertEqual(self.launches.count("serve"), 2)

    def test_it_never_starts_libreoffice_for_the_link(self):
        self.mirror.running = lambda: False
        self.assertEqual(self.mirror.push(self.path, [], probe=True).reason, "notrunning")
        self.assertEqual(self.launches, [])


if __name__ == "__main__":
    unittest.main()
