"""End-to-end journeys: whole sessions a person has with Quill, in order, through the real application. Every step is followed by the
harness's invariant check (see harness.py). Each journey below is a scenario we know about, from the checklist or from a bug found by
hand; when a new bug turns up, add the journey that reproduces it (and the invariant it breaks) here.
"""
import pathlib

import openpyxl

from quill.session import Decision
from tests.fixtures import make_workbook
from tests.journeys.harness import Journey


class TestFirstRow(Journey):
    def test_connect_dictate_save_and_start_the_next_row_clean(self):
        """Connect, press start, speak a row (the grid follows live), save it, and the grid and the words reset."""
        self.assertEqual(self.grid(), [])
        self.assertEqual(self.grid_columns(), list(self.quill.controller.sheet_headers))                # all columns listed, muted
        self.start()
        self.say_partially("fern")
        self.assertEqual(self.grid(), [("Species", "Fern")])                                            # live, before the phrase ends
        self.say_partially("fern small")
        self.assertEqual([c for c, _ in self.grid()], ["Species", "Pot Size"])
        self.say("fern small")
        self.next_row()
        self.assertEqual(self.grid(), [])                                                                # the grid starts over (the words stay until the next ones)
        self.assertEqual(self.saved_rows()[0][:2], ("Fern", "Small"))
        self.assertEqual(len(self.saved_rows()), 1)

    def test_a_long_session_of_rows_saves_each_once(self):
        self.start()
        for species, pot in (("fern", "small"), ("cactus", "large"), ("orchid", "medium")) * 4:
            self.say(f"{species} {pot}")
            self.next_row()
        self.assertEqual(len(self.saved_rows()), 12)
        self.assertEqual(self.numbers.count(self.path.stem), 1)


class TestWordsQuillDoesNotKnow(Journey):
    """The journey that found the Numbers duplicates: unknown terms, the Term Helper, quiet-timer stop, several answers."""

    def test_answering_terms_after_the_quiet_timer_stopped_the_row(self):
        self.start()
        self.say("fern small magnificent spectacular")
        self.go_quiet()
        self.assertTrue(self.quill.controller.pending_terms())
        for key in list(self.quill.controller.pending_terms()):
            self.answer(key[1], Decision.add("Species"))
        self.close_term_helper()
        self.assertEqual(self.numbers.count(self.path.stem), 1)
        self.assertIn("Magnificent", self.grid()[0][1])                                                  # the answered value is in the grid
        self.start()
        self.next_row()
        self.assertEqual(len(self.saved_rows()), 1)                                                      # saved once, with its answers
        self.assertIn("Magnificent", str(self.saved_rows()[0][0]))
        self.assertEqual(self.grid(), [])

    def test_again_and_again_never_piles_up_copies(self):
        for word in ("flibbertigibbet", "gobbledygook", "hullabaloo"):
            self.start()
            self.say(f"cactus {word}")
            self.go_quiet()
            self.answer(word, Decision.add("Species"))
            self.close_term_helper()
            self.start()
            self.next_row()
        self.assertEqual(self.numbers.count(self.path.stem), 1)
        self.assertEqual(len(self.saved_rows()), 3)

    def test_a_document_with_unsaved_changes_is_left_alone_and_explained_once(self):
        self.numbers.docs[0]["modified"] = True
        self.start()
        self.say("fern flabbergasting")
        self.answer("flabbergasting", Decision.add("Species"))
        self.start()
        self.say("cactus bamboozling")
        self.answer("bamboozling", Decision.add("Species"))
        self.assertEqual(self.numbers.count(self.path.stem), 1)
        self.assertEqual(self.count_in_log("left it alone"), 1)

    def test_a_skipped_word_is_taught_and_listed_on_the_words_to_skip_page(self):
        self.start()
        self.say("fern zonkwhistle")
        self.answer("zonkwhistle", Decision.ignore())
        self.close_term_helper()
        self.next_row()


class TestSheetsAndLayouts(Journey):
    def test_each_sheet_has_its_own_layout_and_columns_and_it_survives_a_restart(self):
        self.set_headings_row(3)
        inventory_columns = self.grid_columns()
        self.switch_sheet("Config")
        self.assertEqual(self.quill.controller.settings.preferences["headings_row"], 0)                 # another sheet: its own
        self.assertNotEqual(self.grid_columns(), inventory_columns)
        self.switch_sheet("Inventory")
        self.assertEqual(self.quill.controller.settings.preferences["headings_row"], 3)
        self.assertEqual(self.grid_columns(), inventory_columns)
        from quill.config.settings import Settings
        again = Settings.load(self.dir / "cfg")
        self.assertEqual(again.layout_for(self.quill.controller._connected_to, "Inventory").headings_row, 3)


class TestASheetWithNoColumns(Journey):
    def test_notice_then_links_then_recovery(self):
        blank = self.dir / "blank.xlsx"
        openpyxl.Workbook().save(blank)
        self.quill.controller.connect(str(blank))
        self.step("connected a blank workbook")
        self.assertEqual(self.count_in_log("no column headings"), 1)
        self.assertEqual(self.grid_columns(), [])
        self.window.row_placeholder.linkActivated.emit("file-settings")                                  # the person clicks "Headings Row"
        self.settle(500)
        self.assertEqual(self.window.panel_page, "file")
        self.assertTrue(self.window.panel.settings.isVisible())
        self.assertFalse(self.window.toggle_button.isEnabled())                                          # Start is off: nothing to match
        self.start()                                                                                     # (pressing it does nothing)
        self.assertFalse(self.window.listening)
        self.assertEqual(self.quill.controller.pending_terms(), [])
        self.quill.controller.connect(str(self.path))                                                    # the right file at last
        self.assertTrue(self.window.toggle_button.isEnabled())
        self.step("connected the real workbook")
        self.assertTrue(self.grid_columns())


class TestTheFileGoesAndComesBack(Journey):
    def test_closing_the_file_resets_everything_and_reopening_restores_it(self):
        self.start()
        self.say("fern small")
        self.close_file()
        self.assertEqual(self.grid_columns(), [])
        self.assertFalse(self.window.panel.settings_button.isEnabled())
        self.assertFalse(self.window.listening)
        self.reopen_file()
        self.assertTrue(self.grid_columns())
        self.assertTrue(self.window.panel.settings_button.isEnabled())
        self.assertEqual(self.numbers.count(self.path.stem), 1)

    def test_an_open_overlay_closes_with_the_file(self):
        self.window.open_panel("file")
        self.window.panel.settings.show()
        self.close_file()
        self.assertFalse(self.window.panel.settings.isVisible())


    def test_a_row_dictated_for_one_file_is_never_written_into_another(self):
        """Found by the journeys: the unsaved row stayed after the file was closed and went into the next file chosen."""
        self.start()
        self.say("fern small")
        self.close_file()
        self.assertEqual(self.session.record, {})
        self.assertEqual(self.grid(), [])
        self.assertEqual(self.count_in_log("Row discarded: the file was closed"), 1)
        other = self.dir / "other.xlsx"
        wb = openpyxl.Workbook()
        wb.active.append(["Species", "Colour"])
        wb.save(other)
        self.quill.open_workbook_file(str(other))
        self.step("chose a different file")
        self.start()
        self.next_row()
        self.assertEqual([c for c in openpyxl.load_workbook(other).active.iter_rows(min_row=2, values_only=True)], [])


class TestTheLiveWordsChangeTheirMind(Journey):
    def test_a_live_reading_replaced_by_the_finished_phrase(self):
        self.start()
        self.say_partially("fern")
        self.say("cactus")                                                                               # (the careful model read it differently)
        self.assertEqual(self.grid(), [("Species", "Cactus")])
        self.next_row()


class TestTheMiniViewShowsTheSameRow(Journey):
    def test_switching_views_keeps_the_row(self):
        self.start()
        self.say("fern small")
        before = self.grid()
        self.window.set_mini(True)
        self.step("switched to the mini view")
        self.assertEqual(self.grid(), before)
        self.window.set_mini(False)
        self.step("switched back")
        self.assertEqual(self.grid(), before)
        self.next_row()


class TestCorrectingARow(Journey):
    def test_removing_a_wrong_line_leaves_it_out_of_the_saved_row(self):
        self.start()
        self.say("fern small")
        self.window._remove_row_requested("Pot Size")                                                    # the person clicks the line's x
        self.step("removed the Pot Size line")
        self.assertEqual([c for c, _ in self.grid()], ["Species"])
        self.next_row()
        self.assertEqual(self.saved_rows()[0][:2], ("Fern", None))

    def test_delete_row_clears_the_grid_and_saves_nothing(self):
        self.start()
        self.say("fern small")
        self.say("delete row")
        self.assertEqual(self.grid(), [])
        self.assertEqual(self.saved_rows(), [])

    def test_undo_takes_back_the_last_term_helper_answer(self):
        self.start()
        self.say("fern flibbertigibbet")
        self.answer("flibbertigibbet", Decision.add("Species"))
        self.assertIn("Flibbertigibbet", self.quill.controller.vocab.values_for("Species"))
        self.say("undo")
        self.assertNotIn("Flibbertigibbet", self.quill.controller.vocab.values_for("Species"))
        self.assertTrue(self.quill.controller.pending_terms())                                           # asked about again

    def test_changing_a_lines_column_moves_its_value_and_keeps_the_grid_in_step(self):
        self.start()
        self.say("fern medium")                                                                          # "medium" may be a size or a light
        columns = [c for c, _ in self.grid()]
        if "Light" in columns:
            self.quill.change_field("Light", "Pot Size")
        else:
            self.quill.change_field("Pot Size", "Light")
        self.step("changed which column a line goes in")
        self.next_row()
        self.assertEqual(len(self.saved_rows()), 1)


class TestTurnsThatAppend(Journey):
    def test_in_append_mode_every_turn_adds_to_the_same_row(self):
        self.quill.controller.set_turn_mode("append")
        self.step("chose: each turn adds to the same row")
        self.start()
        self.say("fern")
        self.next_row()
        self.say("small")
        self.next_row()
        rows = self.saved_rows()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0][:2], ("Fern", "Small"))


class TestWordsToSkipAffectDictation(Journey):
    def test_a_word_added_on_the_page_is_skipped_and_removing_it_brings_it_back(self):
        self.quill.open_settings("Words To Skip")
        dialog = self.quill._settings_dialog
        self.step("opened Settings > Words To Skip")
        dialog.skipped.add_edit.setText("flummox")
        dialog.skipped.add_typed()
        self.step("added a word to skip")
        self.assertIn("flummox", self.settings.skip_words)
        self.start()
        self.say("fern flummox")
        self.assertEqual(self.quill.controller.pending_terms(), [])                                      # nothing to ask: it is skipped
        self.next_row()
        dialog.skipped.tree.topLevelItem(0).setSelected(True)
        dialog.skipped.remove_selected()
        self.step("removed it again")
        self.assertNotIn("flummox", self.settings.skip_words)
        self.start()
        self.say("fern flummox")
        self.assertTrue(self.quill.controller.pending_terms())                                           # asked about again


class TestRowsThatRunDown(Journey):
    def test_a_workbook_with_headings_down_the_side_dictates_into_columns(self):
        from tests.test_side_panel_and_turns import make_vertical
        vertical = make_vertical(self.dir / "stock.xlsx")
        self.numbers.import_xlsx(str(vertical))
        self.quill.settings.set_layout(str(vertical.resolve()), "Stock", __import__("quill.config.settings", fromlist=["SheetLayout"]).SheetLayout(0, 0, True))
        self.quill.open_workbook_file(str(vertical))
        self.step("opened a workbook whose headings run down the first column")
        self.assertEqual(self.grid_columns(), ["Fruit", "Color", "Qty"])
        self.start()
        self.say("banana yellow")
        self.assertEqual([c for c, _ in self.grid()], ["Fruit", "Color"])
        self.next_row()
        self.assertEqual(openpyxl.load_workbook(vertical)["Stock"]["C1"].value, "Banana")
        self.assertEqual(self.grid(), [])


class TestChangesOfMindMidRow(Journey):
    """Things a person does with a row half built, found by the random walks."""

    def test_a_column_that_stops_existing_mid_row_leaves_the_grid(self):
        self.start()
        self.say_partially("fern")
        self.assertIn("Species", [c for c, _ in self.grid()])
        self.set_headings_row(1)                                                                         # row 1 holds a title: no such column now
        self.assertNotIn("Species", [c for c, _ in self.grid()])

    def test_deleting_a_row_takes_its_waiting_terms_off_the_term_helper_button(self):
        self.start()
        self.say("fern flibbertigibbet")
        self.assertEqual(len(self.quill.controller.pending_terms()), 1)
        self.say("delete row")
        self.assertEqual(self.quill.controller.pending_terms(), [])
        self.assertEqual(self.window._sorting_count, 0)

    def test_pressing_start_again_on_a_stopped_row_goes_on_with_the_same_row_and_words(self):
        self.start()
        self.say("fern")
        self.stop()
        self.start()
        self.say("small")
        self.assertEqual([c for c, _ in self.grid()], ["Species", "Pot Size"])
        self.assertIn("fern", self.window.stream_text())                                                 # (the words of the whole row stay together)
        self.assertIn("small", self.window.stream_text())
        self.next_row()
        self.assertEqual(self.saved_rows()[0][:2], ("Fern", "Small"))

    def test_removing_a_line_still_being_heard_takes_it_out_of_the_grid(self):
        self.start()
        self.say_partially("fern small")
        self.window._remove_row_requested("Pot Size")
        self.step("clicked the x on a line still being heard")
        self.assertNotIn("Pot Size", [c for c, _ in self.grid()])


class TestTitleBars(Journey):
    """The macOS title bars (a stand-in that remembers what each window's title bar holds). Found on screen: after the Term Helper opened
    by itself the main window had a second row of icons drawn over its title, because the Term Helper's rebuild put the *main*
    window's icons on again as well."""

    native_titlebars = True

    def test_at_launch_each_window_has_its_icons_once(self):
        self.assertEqual(len(self.native.icons[id(self.window.widget)]), 2)         # the right row and the left row
        self.assertEqual(len(self.native.icons[id(self.quill.sorting.widget)]), 1)

    def test_the_term_helper_coming_back_on_a_new_native_window_leaves_the_main_window_alone(self):
        before = list(self.native.icons[id(self.window.widget)])
        self.start()
        self.say("fern gobbledygook")
        self.rebuild_window("sorting")
        self.assertEqual(self.native.icons[id(self.window.widget)], before)
        self.assertEqual(len(self.native.icons[id(self.quill.sorting.widget)]), 1)

    def test_the_term_helper_opened_again_and_again_never_stacks_icons_anywhere(self):
        self.start()
        for _ in range(4):
            self.say("fern gobbledygook")
            self.rebuild_window("sorting")
            self.close_term_helper()

    def test_the_main_window_rebuilt_gets_its_icons_back_once_and_the_term_helper_is_left_alone(self):
        before = list(self.native.icons[id(self.quill.sorting.widget)])
        self.rebuild_window("main")
        self.assertEqual(len(self.native.icons[id(self.window.widget)]), 2)
        self.assertEqual(self.native.icons[id(self.quill.sorting.widget)], before)

    def test_both_rebuilt_one_after_the_other(self):
        self.rebuild_window("main")
        self.rebuild_window("sorting")
        self.rebuild_window("main")


class TestAnEmptySheet(Journey):
    """Found on screen: Quill followed Numbers to a blank sheet, Start could still be pressed, and the words sat in the grid with nowhere to
    be written. Now Start is off there, says why, and a turn already running stops."""

    def test_start_is_off_on_an_empty_sheet_and_comes_back_with_a_sheet_that_has_columns(self):
        self.open_empty_sheet()
        self.assertFalse(self.window.toggle_button.isEnabled())
        self.window.toggle_button.click()
        self.step("pressed Start (it is off)")
        self.assertFalse(self.window.listening)
        self.open_usual_sheet()
        self.start()
        self.say("fern small")
        self.assertEqual([c for c, _ in self.grid()], ["Species", "Pot Size"])

    def test_a_turn_running_when_the_sheet_turns_empty_stops_and_writes_nothing(self):
        wb = openpyxl.load_workbook(self.path)
        wb.create_sheet("Blank")                                     # (the person adds an empty sheet and switches to it in the program)
        wb.save(self.path)
        self.quill.open_workbook_file(self.path, remember=False)       # (the saved file has the sheet now)
        self.start()
        self.say("fern small")
        self.switch_sheet("Blank")
        self.assertFalse(self.window.listening)
        self.assertIn("Stopped listening", self.log())
        self.assertEqual(self.saved_rows(), [])                           # (the stopped row keeps its words; none of it was written anywhere)
        self.assertFalse(self.window.toggle_button.isEnabled())
        self.switch_sheet("Inventory")
        self.assertTrue(self.window.toggle_button.isEnabled())

    def test_the_voice_cannot_start_it(self):
        self.open_empty_sheet()
        self.hear("start listening")
        self.step("said 'start listening'")
        self.assertFalse(self.window.listening)
