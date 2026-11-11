"""After Quill saves the file it asks Numbers to show what was saved. Whatever happens, that must never leave a second copy of the file
open in Numbers: these tests look at the documents Numbers has open afterwards (against a stand-in that behaves like it), and walk a
whole dictation with Term Helper answers through the application to count them at the end."""
import unittest

from quill.bridge.hosts import NUMBERS, SpreadsheetHosts
from quill.platforms.macos import hosts as mac_hosts
from quill.session import Decision
from tests.fake_numbers import FakeNumbers
from tests.test_app import AppCase

PATH = "/Users/me/Documents/Apparel Inventory.xlsx"


def reload(numbers, path=PATH):
    return SpreadsheetHosts("darwin", numbers).reload(NUMBERS, path)


class _Installed(mac_hosts.MacHosts):
    def installed(self, program):
        return True


def launch(numbers, path=PATH):
    return _Installed(numbers).launch(path, "numbers")


class TestOpeningNeverAddsACopy(unittest.TestCase):
    """Start (and Open File) ask Numbers to open the file when nobody seems to have it: if Numbers already has it, nothing is opened."""

    def test_a_workbook_already_open_in_numbers_is_not_opened_again(self):
        numbers = FakeNumbers()
        numbers.import_xlsx(PATH)
        self.assertTrue(launch(numbers))
        self.assertEqual(len(numbers.docs), 1)
        self.assertFalse([c for c in numbers.calls if c[0] == "open"])

    def test_a_numbers_document_with_that_file_is_not_opened_again(self):
        numbers = FakeNumbers()
        numbers.open_numbers_document(PATH)
        launch(numbers)
        self.assertEqual(len(numbers.docs), 1)

    def test_a_file_nobody_has_open_is_opened_once_however_often_it_is_asked(self):
        numbers = FakeNumbers()
        for _ in range(4):
            launch(numbers)
        self.assertEqual(numbers.count("Apparel Inventory"), 1)

    def test_other_open_documents_do_not_stop_it(self):
        numbers = FakeNumbers()
        numbers.import_xlsx("/Users/me/Documents/Other.xlsx")
        launch(numbers)
        self.assertEqual(sorted(d["name"] for d in numbers.docs), ["Apparel Inventory", "Other"])

    def test_the_numbers_that_is_running_is_asked_by_its_bundle_id(self):
        numbers = FakeNumbers()
        numbers.bundle = "com.apple.Numbers"
        launch(numbers)
        self.assertIn(["open", "-g", "-b", "com.apple.Numbers", PATH], numbers.calls)

    def test_nothing_running_the_newer_installed_numbers_is_chosen_not_the_old_one_by_name(self):
        numbers = FakeNumbers()
        numbers.installed = ["com.apple.Numbers", "com.apple.iWork.Numbers"]
        launch(numbers)
        self.assertIn(["open", "-g", "-b", "com.apple.Numbers", PATH], numbers.calls)
        self.assertFalse([c for c in numbers.calls if c[:3] == ["open", "-g", "-a"]])

    def test_only_the_classic_numbers_installed_it_is_the_one_opened(self):
        numbers = FakeNumbers()
        numbers.installed = ["com.apple.iWork.Numbers"]
        launch(numbers)
        self.assertIn(["open", "-g", "-b", "com.apple.iWork.Numbers", PATH], numbers.calls)

    def test_the_running_numbers_wins_over_an_installed_one(self):
        numbers = FakeNumbers()
        numbers.bundle = "com.apple.iWork.Numbers"
        numbers.installed = ["com.apple.Numbers", "com.apple.iWork.Numbers"]
        launch(numbers)
        self.assertIn(["open", "-g", "-b", "com.apple.iWork.Numbers", PATH], numbers.calls)

    def test_when_it_cannot_be_told_apart_the_name_is_used(self):
        numbers = FakeNumbers()
        launch(numbers)
        self.assertIn(["open", "-g", "-a", "Numbers", PATH], numbers.calls)


class TestEveryNumbersScriptPicksTheRunningNumbers(unittest.TestCase):
    """Two Numbers apps can be installed; asking for "Numbers" by name reaches only one, so no script may do that."""

    def test_no_script_asks_for_numbers_by_name_alone(self):
        from quill.platforms.macos import numbers_live, numbers_mirror
        scripts = [mac_hosts._LIST_NUMBERS, mac_hosts._LIST_NUMBERS_FOR_RELOAD, mac_hosts._CLOSE_NUMBERS, numbers_live.SCRIPT,
                   numbers_mirror.SCRIPT, numbers_mirror.PROBE, numbers_mirror.ACTIVE_SHEET]
        for script in scripts:
            self.assertIn("numbersApp()", script)
            self.assertEqual(script.count('Application("Numbers")'), 1, "only the fallback inside numbersApp() may use the name")


class TestNeverASecondCopy(unittest.TestCase):
    def test_an_imported_workbook_is_replaced_not_added_to(self):
        numbers = FakeNumbers()
        numbers.import_xlsx(PATH)
        self.assertIs(reload(numbers), True)
        self.assertEqual(numbers.count("Apparel Inventory"), 1)

    def test_asking_again_and_again_still_leaves_one(self):
        numbers = FakeNumbers()
        numbers.import_xlsx(PATH)
        for _ in range(6):
            reload(numbers)
        self.assertEqual(len(numbers.docs), 1)

    def test_a_numbers_document_that_reports_its_file_is_replaced_too(self):
        numbers = FakeNumbers()
        numbers.open_numbers_document(PATH)
        reload(numbers)
        reload(numbers)
        self.assertEqual(len(numbers.docs), 1)

    def test_copies_already_open_are_closed_down_to_one(self):
        numbers = FakeNumbers()
        for _ in range(3):
            numbers.import_xlsx(PATH)
        reload(numbers)
        self.assertEqual(numbers.count("Apparel Inventory"), 1)

    def test_a_document_with_unsaved_changes_is_left_alone_and_nothing_is_opened(self):
        numbers = FakeNumbers()
        numbers.import_xlsx(PATH, modified=True)
        self.assertEqual(reload(numbers), "kept")
        self.assertEqual(len(numbers.docs), 1)
        self.assertTrue(numbers.docs[0]["modified"])
        self.assertFalse([c for c in numbers.calls if c[0] == "open"])

    def test_a_file_the_user_closed_is_not_opened_again(self):
        numbers = FakeNumbers()
        numbers.import_xlsx("/Users/me/Documents/Other.xlsx")
        self.assertEqual(reload(numbers), "not open")
        self.assertEqual([d["name"] for d in numbers.docs], ["Other"])

    def test_other_documents_are_never_touched(self):
        numbers = FakeNumbers()
        numbers.import_xlsx("/x/Budget.xlsx", modified=True)
        numbers.import_xlsx(PATH)
        numbers.open_numbers_document("/x/Notes.numbers")
        reload(numbers)
        self.assertEqual(sorted(d["name"] for d in numbers.docs), ["Apparel Inventory", "Budget", "Notes"])

    def test_numbers_that_cannot_be_asked_changes_nothing(self):
        class Refusing(FakeNumbers):
            def __call__(self, args):
                super().__call__(args)
                return "no" if args[0] == "osascript" else ""
        numbers = Refusing()
        numbers.import_xlsx(PATH)
        self.assertIs(reload(numbers), False)
        self.assertEqual(len(numbers.docs), 1)

    def test_a_close_that_fails_opens_nothing(self):
        class CannotClose(FakeNumbers):
            def __call__(self, args):
                if args[0] == "osascript" and args[5:]:
                    self.calls.append(list(args))
                    return "no"
                return super().__call__(args)
        numbers = CannotClose()
        numbers.import_xlsx(PATH)
        self.assertIs(reload(numbers), False)
        self.assertEqual(len(numbers.docs), 1)


class TestAWholeDictationThroughTheApplication(AppCase):
    """What happened for real: a sentence with words Quill did not know, a Term Helper answered for each, and Numbers ended up with
    the file open three times."""

    def setUp(self):
        super().setUp()
        self.numbers = FakeNumbers()
        self.numbers.import_xlsx(str(self.path.resolve()))
        self.quill.hosts = SpreadsheetHosts("darwin", self.numbers)
        self.quill._host = NUMBERS
        self.quill.run_in_background = lambda work, done: done(work())             # (no helper thread in tests)

    def open_copies(self):
        return self.numbers.count(self.path.stem)

    def test_answering_the_term_helper_never_opens_the_file_again(self):
        self.hear("start listening", "fern magnificent spectacular")
        for term in ("magnificent", "spectacular"):
            self.quill.resolve_term((None, term), Decision.add("Species"), term)
            self.quill._reload_host()                                              # (what the timer does a moment after a save)
            self.assertEqual(self.open_copies(), 1, f"after answering {term!r}")

    def test_many_saves_in_a_row_leave_one_copy(self):
        for _ in range(8):
            self.quill._reload_host()
        self.assertEqual(self.open_copies(), 1)

    def test_a_document_with_unsaved_changes_gets_a_single_explanation_and_no_copy(self):
        self.numbers.docs[0]["modified"] = True
        for _ in range(3):
            self.quill._reload_host()
        self.assertEqual(self.open_copies(), 1)
        self.assertEqual(self.log().count("left it alone"), 1)


if __name__ == "__main__":
    unittest.main()
