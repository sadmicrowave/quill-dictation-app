"""A connected file whose open sheet has no columns Quill can find has nothing to match the words to: Start is off (the button, the menu, the
tray, the voice command), the button says why, and a turn that was running when the sheet turned empty stops."""
import openpyxl

from quill.parser.vocab import NO_COLUMNS_START_HELP
from quill.ui.listen_button import NO_COLUMNS_TEXT, NOT_CONNECTED_TEXT
from tests.test_app import AppCase


class StartCase(AppCase):
    def blank(self):
        path = self.dir / "blank.xlsx"
        openpyxl.Workbook().save(path)
        self.quill.controller.connect(str(path))

    def usual(self):
        self.quill.controller.connect(str(self.path))

    @property
    def button(self):
        return self.quill.window.toggle_button


class TestStartIsOffOnASheetWithNoColumns(StartCase):
    def test_the_button_is_disabled_and_says_why(self):
        self.blank()
        self.assertFalse(self.button.isEnabled())
        self.assertEqual(self.button.notice_text, NO_COLUMNS_TEXT)
        self.assertEqual(self.button.text_pill.text(), "No columns on this sheet")
        self.assertEqual(self.button.toolTip(), NO_COLUMNS_START_HELP)
        self.assertIn("Headings Row", NO_COLUMNS_START_HELP)                         # (and what to do about it)

    def test_pressing_it_starts_nothing(self):
        self.blank()
        self.button.click()
        self.assertFalse(self.quill.window.listening)
        self.assertFalse(self.quill.controller.session.listening)

    def test_the_other_ways_to_start_are_refused_too_and_say_why(self):
        self.blank()
        self.quill.toggle_listening(True)                                            # (the menu, the tray, a shortcut)
        self.assertFalse(self.quill.controller.session.listening)
        self.assertIn("Start is off", self.log())
        self.assertFalse(self.quill.window.listening)

    def test_the_voice_command_cannot_start_it_either(self):
        self.blank()
        self.hear("start listening")
        self.assertFalse(self.quill.controller.session.listening)
        self.assertFalse(self.quill.window.listening)

    def test_the_session_itself_refuses_with_the_reason(self):
        from quill.parser.commands import Action
        self.blank()
        events = self.quill.controller.session.apply(Action.START_LISTENING)
        self.assertEqual([(e.kind, e.detail) for e in events], [("ignored", NO_COLUMNS_START_HELP)])

    def test_the_menu_item_is_off(self):
        self.blank()
        self.quill._sync_menus()
        action = self.quill.menus.actions()["toggle_listening"]
        self.assertFalse(action.isEnabled())

    def test_nothing_heard_is_kept_in_the_grid(self):
        self.blank()
        self.hear("start listening", "fern small")
        self.assertEqual(self.quill.window.heard_lines(), [])
        self.assertEqual(self.quill.controller.session.record, {})


class TestStartComesBack(StartCase):
    def test_a_sheet_with_columns_brings_start_back(self):
        self.blank()
        self.usual()
        self.assertTrue(self.button.isEnabled())
        self.assertFalse(self.button.notice)
        self.assertEqual(self.button.text_pill.text(), "Start Listening")
        self.button.click()
        self.assertTrue(self.quill.window.listening)

    def test_the_menu_item_comes_back_too(self):
        self.blank()
        self.usual()
        self.quill._sync_menus()
        self.assertTrue(self.quill.menus.actions()["toggle_listening"].isEnabled())

    def test_with_no_file_connected_start_is_still_allowed_as_before(self):
        self.quill.controller.detach()
        self.assertTrue(self.button.isEnabled())
        self.assertNotEqual(self.button.notice_text, NO_COLUMNS_TEXT)
        self.assertEqual(self.button.notice_text if self.button.notice else "", NOT_CONNECTED_TEXT if self.button.notice else "")


class TestASheetThatTurnsEmptyWhileListening(StartCase):
    def test_the_turn_stops_with_a_reason_and_start_goes_off(self):
        self.hear("start listening", "fern small")
        self.assertTrue(self.quill.window.listening)
        self.blank()
        self.assertFalse(self.quill.window.listening)
        self.assertFalse(self.quill.controller.session.listening)
        self.assertIn("Stopped listening: this sheet has no columns", self.log())
        self.assertFalse(self.button.isEnabled())
        self.assertEqual(self.button.text_pill.text(), "No columns on this sheet")

    def test_it_stops_only_once_and_says_so_once(self):
        self.hear("start listening")
        self.blank()
        self.quill.controller.reload_vocab()
        self.assertEqual(self.log().count("Stopped listening: this sheet has no columns"), 1)


class TestTheMiniViewIsNotMadeWider(StartCase):
    """Found when the 'Start is off' label was longer than 'File not connected': the mini view's minimum width grew from 470 to 497. The mini
    view says the short 'No columns' and the button's width budget is unchanged."""

    def test_the_compact_button_says_the_short_words_and_the_full_window_the_full_ones(self):
        from quill.ui.listen_button import NO_COLUMNS_SHORT
        self.blank()
        window = self.quill.window
        self.assertEqual(self.button.text_pill.text(), NO_COLUMNS_TEXT)
        window.set_mini(True)
        self.assertEqual(self.button.text_pill.text(), NO_COLUMNS_SHORT)
        self.assertEqual(self.button.toolTip(), NO_COLUMNS_START_HELP, "the reason is still on hover")
        window.set_mini(False)
        self.assertEqual(self.button.text_pill.text(), NO_COLUMNS_TEXT)

    def test_the_least_width_does_not_depend_on_the_new_label(self):
        from quill.ui.listen_button import ListenButton
        button = ListenButton()
        button.set_compact(True)
        plain = button.minimumWidth()
        button.set_notice(True, "why", NO_COLUMNS_TEXT, blocked=True, short="No columns")
        self.assertEqual(button.minimumWidth(), plain)
