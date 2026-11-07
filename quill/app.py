"""Application wiring: connects the bridge, listener, controller and UI.

:class:`QuillApp` is the only place that knows about all the pieces. It turns
Session events into window/tray updates and carries user actions (tray click,
settings, workbook picker) back to the controller.

Threading: the Vosk listener and the model download run on background
threads. They talk to the GUI only through :class:`Relay` signals, which Qt
delivers on the GUI thread, so no widget is touched off-thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import os
import pathlib
import threading
import time
from typing import Callable

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from quill.assets import app_icon
from quill.bridge.base import BridgeError, WorkbookBridge
from quill.bridge.factory import get_bridge
from quill.bridge.hosts import APPS as HOST_APPS, HostApp, OpenFile, SpreadsheetHosts
from quill.bridge.libreoffice_mirror import LibreOfficeMirror
from quill.bridge.numbers_mirror import MirrorResult, NumbersMirror
from quill.bridge.csv_bridge import CsvBridge
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import NO_WORKBOOK_HELP, Controller
from quill.feedback import spoken_words, Feedback
from quill.listener.listener import Listener
from quill.listener.model import (
    BETTER,
    SPECS,
    WHISPER_SIZE_MB,
    fallback_choice,
    remove_model,
    user_model_dir as _user_model_dir,
    download_spec,
    download_whisper,
    ensure_model,
    find_spec_model,
    find_whisper_model,
    user_model_dir,
)
from quill.listener.whisper_refiner import WhisperRefiner, engine_available
from quill.session import Decision, Event, TermKey
from quill.speaker.clips import SpokenClips
from quill.speaker.speaker import Speaker
from quill.stream import match_words
from quill.ui.chrome import (
    SYMBOL_FOLDER,
    SYMBOL_HELP,
    SYMBOL_SETTINGS,
    SYMBOL_TURN,
    SYMBOL_UNDO,
    add_titlebar_button,
    apply_chrome,
    FileDialogWarmer,
    bring_app_forward,
    refresh_chrome_soon,
    set_title_inset,
    set_dock_icon_visible,
    watch_native_window,
)
from quill.ui.confirm import info
from quill.ui.help_window import HelpWindow
from quill.ui.main_window import MainWindow
from quill.ui.menus import MenuState, QuillMenus
from quill.ui.player import SoundPlayer
from quill.ui.settings_dialog import SettingsDialog, open_log_folder
from quill.ui.side_panel import APPEND_TO, FILE_PAGE, NEXT_ROW, TITLES, TURN_PAGE
from quill.ui.sorting_window import SortingWindow
from quill.ui.theme import (
    apply_opacity,
    backdrop_alpha,
    apply_spacing,
    apply_theme,
    colors_for,
    is_dark,
)
from quill.ui.tray import TrayIcon
from quill.ui.widgets import PopupClickThrough, CenteredToolTips


class QuillApplication(QApplication):
    """The application object. The system's "quit the application" request (Dock menu, Cmd-Q) arrives as a
    close event addressed to it; it is turned into :attr:`quit_requested`, which :meth:`QuillApp.quit_app` handles, so
    quitting closes every window the same way whatever started it (and no open Settings window can hold it back)."""

    quit_requested = Signal()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.Close:
            self.quit_requested.emit()
            return True
        return super().event(event)


class Relay(QObject):
    """Signals used to hop from background threads onto the GUI thread."""

    transcript = Signal(str)
    partial = Signal(str)           # words of the phrase still being spoken
    level = Signal(float)           # how loud the user's voice is (0 to 1), about ten times a second
    error = Signal(str)
    progress = Signal(int, int)
    model_ready = Signal(object)   # pathlib.Path on success, None on failure
    background_done = Signal(object, object)   # (callback, result) of a task that ran off the GUI thread


log = logging.getLogger("quill.app")

#: How long after the last write the program showing the file is asked to reload it, and how many
#: watcher ticks pass between looks for a file open in another spreadsheet program.
HOST_RELOAD_MS = 1500
@dataclass
class Look:
    """What one look at the spreadsheet programs found (made off the GUI thread, applied on it)."""

    files: list[OpenFile]
    sheet: str | None            # the sheet open now in the active file, when a program said so
    complete: bool               # every question was answered (an empty answer then really means "nothing open")
    bridge: object               # the bridge it looked for: a result for a bridge that was swapped meanwhile is dropped
    names: list[str] | None      # the workbooks the bridge reports open (Excel's, or the file's own); None: it could not say


#: Logged once the speech model is loaded and a spreadsheet is connected.
READY_NOTE = "Speech model ready. The microphone is off until you press Start."
#: How often (ms) held changes (the file was in use by another program) are tried again; after this many failed tries a copy is saved.
FLUSH_EVERY_MS = 5000
FLUSH_COPY_AFTER = 3
#: How long after start-up (ms) the system's file window is warmed up (see FileDialogWarmer).
FILE_DIALOG_WARM_MS = 2500


#: The speech quality choices and their names in the window.
QUALITY_LABELS = {"standard": "Quick", "better": "Broad", "best": "Careful"}


class QuillApp:
    """Owns every component and runs the app.

    Args:
        qapp: The QApplication.
        settings: Loaded settings.
        bridge: Workbook bridge (live Excel, or a file bridge).
        listener_factory: ``(model_path, on_transcript, on_error) -> listener``;
            tests inject a fake so no microphone is needed.
        model_finder: ``(configured_path) -> Path | None``.
        model_downloader: ``(dest_dir, progress[, spec]) -> Path``; tests inject a fake.
        better_finder: ``() -> Path | None``, the larger speech model if it is installed; tests inject a fake.
        speaker: Speaker to use (default: platform TTS honouring settings).
        poll_interval_ms: How often the one check loop runs (None: the ``sheet_check_seconds`` setting).
    """

    #: How long after asking to quit the event loop is forced to end if something still holds it (0 = never; tests).
    quit_failsafe_ms = 1500

    def __init__(
        self,
        qapp,
        settings: Settings,
        bridge: WorkbookBridge,
        listener_factory: Callable | None = None,
        model_finder: Callable[[str], pathlib.Path | None] = ensure_model,
        model_downloader: Callable = download_spec,
        better_finder: Callable[[], pathlib.Path | None] = lambda: find_spec_model(BETTER),
        whisper_finder: Callable[[], pathlib.Path | None] = find_whisper_model,
        whisper_downloader: Callable = download_whisper,
        whisper_engine: Callable[[], bool] = engine_available,
        refiner_factory: Callable = WhisperRefiner,
        speaker: Speaker | None = None,
        poll_interval_ms: int | None = None,
        sound_player: Callable | None = None,
        echo_speaker=None,
        clips: SpokenClips | None = None,
        file_chooser: Callable[[], str | None] | None = None,
        live_bridge_factory: Callable[[], WorkbookBridge] = get_bridge,
        hosts: SpreadsheetHosts | None = None,
        mirror: NumbersMirror | None = None,
        lo_mirror: LibreOfficeMirror | None = None,
    ) -> None:
        self.qapp = qapp
        self._file_chooser = file_chooser or self._ask_for_file
        self._file_dialog_warmer = FileDialogWarmer()
        self._live_bridge_factory = live_bridge_factory
        self.hosts = hosts or SpreadsheetHosts()      # finds Numbers / LibreOffice ... and refreshes them after a save
        self._host: HostApp | None = None            # the program showing the file Quill is writing to
        self.mirror = mirror or NumbersMirror()      # shows each turn's cells in an open Numbers document as they are written
        self.lo_mirror = lo_mirror or LibreOfficeMirror()      # ... and in an open LibreOffice Calc document
        self._mirror_warned = False
        self._lo_noted = False
        self._settings_dialog: SettingsDialog | None = None    # the open Settings window, if any
        self._model_busy, self._model_note = False, ""          # the speech model download, shown in Settings
        self._quitting = False
        self._ready_note_pending = False             # the model is ready but a warning is showing: the note waits for a connection
        self._open_files: list[OpenFile] = []        # spreadsheets other programs have open (the side panel's list)
        self._open_files_busy = False                # the check loop's look is under way (never two at once)
        self._attach_paused = False                  # Quill let go of a closed file: it picks no other file by itself until one is chosen
        self._seen_open = ""                           # the connected file's real path once a look found it open (see _check_link)
        self._look_again: tuple[bool, bool, list] | None = None   # a look asked for meanwhile: (manual, announce, callbacks)
        self._launched_at: dict[str, float] = {}        # when a program was last asked to open each file (see _launch)
        self._start_wanted = False                      # Start was pressed while the file was not yet open in a program
        self._waiting_viewer = False
        self._viewer_looks = 0
        self._viewer_running = False
        self._host_noted = False
        self._host_reload = QTimer()
        self._host_reload.setSingleShot(True)
        self._host_reload.setInterval(HOST_RELOAD_MS)
        self._host_reload.timeout.connect(self._reload_host)
        self._quiet_timer = QTimer()                  # stops listening after a spell of silence (see "auto_stop")
        self._quiet_timer.setSingleShot(True)
        self._quiet_timer.timeout.connect(self._quiet_for_too_long)
        self._countdown_timer = QTimer()              # redraws the seconds left, four times a second
        self._countdown_timer.setInterval(250)
        self._countdown_timer.timeout.connect(self._show_countdown)
        qapp.setWindowIcon(app_icon())               # the Dock / taskbar / window icon
        self.settings = settings
        self.relay = Relay()
        self.speaker = speaker or Speaker(enabled=bool(settings.preferences["speak_sort_prompts"]))
        self.controller = Controller(
            bridge, settings, self.speaker,
            on_event=self.handle_event, on_speech=self._on_speech,
        )
        self.window = MainWindow(
            on_toggle=self.toggle_listening, on_settings=self.open_settings,
            on_open_file=self.choose_spreadsheet_file,
            on_use_excel=self.use_live_excel, on_file_state=self._sync_titlebar_file,
            on_sorting=self.show_sorting,
            on_undo=self.undo, on_next_row=self.next_row, on_help=self.open_help, on_log_toggled=self._log_toggled,
            on_resized=self._window_resized, on_mini_resized=self._mini_window_resized,
            on_field_removed=self.remove_field, on_field_options=self.controller.columns_for_change,
            on_field_changed=self.change_field, on_learn_answer=self.answer_learn_offer,
            log_collapsed=bool(settings.preferences["log_collapsed"]),
            on_mini_toggled=self._mini_toggled, mini=bool(settings.preferences["mini_mode"]),
            mini_on_top=bool(settings.preferences["mini_on_top"]),
        )
        self.sorting = SortingWindow(self.controller.vocab, self.resolve_term,
                                     on_voice=self.toggle_voice_sorting,
                                     on_undo=self.undo, batch=self.controller.batch, on_help=self.open_help,
                                     on_speak=self.controller.speak)
        self.tray = TrayIcon(
            qapp, self.window,
            on_start=lambda: self.toggle_listening(True),
            on_stop=lambda: self.toggle_listening(False),
            on_open_workbook=self.show_workbook, on_open_sorting=self.show_sorting,
            on_open_file=self.choose_spreadsheet_file, on_quit=self.quit_app,
        )
        self.listener = None
        self.connected = False
        self.menus: QuillMenus | None = None             # built in start()
        self._default_menu_bar = None
        self._listener_factory = listener_factory or self._default_listener
        self._model_finder = model_finder
        self._model_downloader = model_downloader
        self._better_finder = better_finder
        self._whisper_finder, self._whisper_downloader = whisper_finder, whisper_downloader
        self._whisper_engine, self._refiner_factory = whisper_engine, refiner_factory
        self._loaded_quality = ""                       # which speech model the running listener uses
        self._downloading = "standard"
        self._model_remover = remove_model
        self._mic_open = False
        self._seen_mtime: int | None = None      # last known state of the workbook file
        self._titlebar = None                    # the resize icon in the title bar, where supported
        self._titlebar_left = None               # Help and Undo, beside the close / zoom buttons
        self.help: HelpWindow | None = None      # created the first time a ? icon is pressed
        self._expiry = QTimer()
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self.controller.expire_prompt)
        self.echo_speaker = echo_speaker or Speaker(enabled=True)
        self.sound_player = sound_player or SoundPlayer()
        self.clips = clips or SpokenClips()                      # spoken confirmation words, rendered once, played at once
        self.feedback = Feedback(settings, self.sound_player, self._speak_word,
                                 busy=self._mute_for)
        self.controller.lead_in_s = self.feedback.lead_in_s()
        self._cue_timer = QTimer()          # lets one breath's events settle into a single cue
        self._cue_timer.setSingleShot(True)
        self._cue_timer.setInterval(60)
        self._cue_timer.timeout.connect(self.feedback.flush)
        self._flush_timer = QTimer()                 # tries again to save changes that a program holding the file refused
        self._flush_timer.setInterval(FLUSH_EVERY_MS)
        self._flush_timer.timeout.connect(self._flush_waiting)
        self._flush_failures = 0
        self._watcher = QTimer()                      # the ONE check loop: files, a closed file, the open sheet (see poll_workbooks)
        self._watcher.setInterval(poll_interval_ms if poll_interval_ms is not None
                                  else int(self.settings.preferences["sheet_check_seconds"]) * 1000)
        self._watcher.timeout.connect(self.poll_workbooks)

        self.relay.transcript.connect(self._on_phrase_heard)        # first: show the words before they are acted on
        self.relay.partial.connect(self._on_partial_heard)
        self.relay.level.connect(self._on_level)
        self.relay.background_done.connect(lambda callback, result: callback(result))
        self.relay.transcript.connect(self.controller.handle_transcript)
        self.relay.error.connect(self._on_error)
        self.relay.progress.connect(self._on_progress)
        self.relay.model_ready.connect(self._on_model_ready)
        qapp.styleHints().colorSchemeChanged.connect(self._system_scheme_changed)
        qapp.applicationStateChanged.connect(self._app_state_changed)

    # ------------------------------------------------------------------ #
    # Startup                                                              #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Build the UI, connect to the workbook, and start listening for speech."""
        self._apply_look()
        self.window.setup()
        self._build_menus()
        self.sorting.setup(parent=self.window.widget)
        if not getattr(self.qapp, "_quill_click_through", None):    # one filter per application, however many windows
            self.qapp._quill_click_through = PopupClickThrough(self.qapp)   # one click on Start / Stop works with a drop-down open
            self.qapp.installEventFilter(self.qapp._quill_click_through)
        if not getattr(self.qapp, "_quill_tooltips", None):          # tool tips centred on the pointer, everywhere
            self.qapp._quill_tooltips = CenteredToolTips(self.qapp)
            self.qapp.installEventFilter(self.qapp._quill_tooltips)
        self.sorting.on_done = self.window.sorting_finished
        self.sorting.restore_place(int(self.settings.preferences["sorting_x"]), int(self.settings.preferences["sorting_y"]),
                                   int(self.settings.preferences["sorting_width"]))
        self.sorting.on_geometry = self._sorting_moved
        self._wire_panel()
        self.sorting.install_titlebar()
        self._apply_look()          # again: the windows now exist, so their layouts get the spacing
        self.tray.setup()
        self._rebuild_watchers = [watch_native_window(w, self._native_rebuilt)
                                  for w in (self.window.widget, self.sorting.widget) if w is not None]
        self.window.set_stream_classifier(self._match_heard_words)
        self.window.restore_panel_width(int(self.settings.preferences["panel_width"]))
        self.window.set_panel_size_listener(self._panel_size_changed)
        self.window.restore_log_height(int(self.settings.preferences["log_height"]))
        self.window.set_log_height_listener(self._log_height_changed)
        self.window.restore_mini_size(int(self.settings.preferences["mini_width"]),
                                      int(self.settings.preferences["mini_height"]))
        self.window.restore_size(int(self.settings.preferences["window_width"]),
                                 int(self.settings.preferences["window_height"]))
        self.window.show()
        self.qapp.aboutToQuit.connect(self._remember_view)
        self.qapp.aboutToQuit.connect(self.window.report_size)      # a size changed just before quitting counts
        self.qapp.aboutToQuit.connect(self.shutdown)
        if hasattr(self.qapp, "quit_requested"):                          # Quit from the Dock or Cmd-Q goes the same way
            self.qapp.quit_requested.connect(self.quit_app)
        self._apply_dock()
        self._install_titlebar_button()
        self.window.set_file_mode(isinstance(self.controller.bridge, XlsxBridge))
        self.connect_workbook(str(self.settings.preferences["last_workbook"]) or None)
        self._sync_menus()
        self._use_best_installed()
        self._start_listener()
        self._watcher.start()
        self._restart_check_timer()
        QTimer.singleShot(FILE_DIALOG_WARM_MS, self._warm_file_dialog)
        self._flush_timer.start()
        QTimer.singleShot(0, self._warm_up_sounds)           # after the window is up: load every sound, make spoken clips

    def connect_workbook(self, name: str | None = None, quiet: bool = False) -> None:
        """Connect (or reconnect) to a workbook and refresh the UI; never raises.

        Args:
            name: Workbook to target; None for the active one.
            quiet: Don't log or show a message when nothing is found.
        """
        bridge = self.controller.bridge
        try:
            names = bridge.open_workbooks()
            if name and names and name not in names:
                name = None   # last-used workbook is no longer open
            self.controller.connect(name)
        except BridgeError as exc:
            self.connected = False
            if not quiet:
                self.window.append_log(f"Not connected: {exc}", "warning")
            self.window.set_not_connected(True)
            return
        self.connected = True
        self._attach_paused = False
        self.window.update_workbooks(names, bridge.workbook_name)
        self.window.set_workbook_path(bridge.workbook_path, self._active_kind())
        self._show_open_files()
        count = sum(len(v) for v in bridge.get_lists().values())
        self.window.append_log(
            f"Connected to {bridge.workbook_name}: {len(bridge.get_lists())} lists, {count} values"
        )
        warning = getattr(bridge, "discovery_warning", None)
        if warning:
            self.window.append_log(warning, "warning")
        self.window.set_not_connected(False)
        if self._ready_note_pending and self.listener is not None and not self._mic_open:
            self._ready_note_pending = False
            self.window.append_log(READY_NOTE)
        self._show_active_sheet()
        self.tray.set_workbook(bridge.workbook_name, bridge.workbook_path)
        self.settings.preferences["last_workbook"] = bridge.workbook_name
        self.settings.save()
        self._remember_mtime()
        QTimer.singleShot(600, self.refresh_open_files)        # which sheet is the program on right now? (one look)

    def poll_workbooks(self) -> None:
        """The tick of the one check loop (every ``sheet_check_seconds``): attach when a workbook appears, detach when it
        closes, and take ONE look at the spreadsheet programs (:meth:`refresh_open_files`) that serves the Available Files
        list, a closed file and the open sheet together.

        This is what makes "just open a spreadsheet and start talking" work: Quill need not be told which workbook; it
        notices.
        """
        self.refresh_open_files()

    def _poll_local(self, names: list[str]) -> None:
        """Apply the workbook names the look found: attach a workbook that appeared, detach one that closed, and re-read a
        file that changed on disk. (The names are asked off the GUI thread, with the look.)"""
        bridge = self.controller.bridge
        if self.connected:
            if bridge.workbook_name in names:
                self._check_workbook_changes()
                self._show_active_sheet()
                return
            closed = bridge.workbook_name
            self.controller.detach()
            self.connected = False
            self._set_listening(False)
            self.tray.set_workbook("", "")
            self.window.update_workbooks([])
            self.window.append_log(f"'{closed}' was closed.")
            self.window.set_not_connected(True)
        if names and not self.connected and self._released_file(bridge):
            names = []                  # (the file's window was closed: it is not attached again just because the file exists)
        if names and not self.connected:
            preferred = str(self.settings.preferences["last_workbook"])
            self.connect_workbook(preferred if preferred in names else None, quiet=True)
            if self.connected:
                self.window.append_log(f"Attached to {bridge.workbook_name} automatically.")

    def _released_file(self, bridge) -> bool:
        """Is *bridge* a file whose spreadsheet window was closed and that Quill let go of (see :meth:`_check_link`)?"""
        return isinstance(bridge, XlsxBridge) and bool(bridge.workbook_path) and not self._viewer_open() \
            and not self._just_launched(bridge.workbook_path)

    def run_in_background(self, work: Callable[[], object], done: Callable[[object], None]) -> None:
        """Run ``work()`` on a helper thread and call ``done(result)`` on the GUI thread afterwards.

        For anything that may stall (asking the system what is running, asking another program to
        reload a file): the window must never freeze while waiting on it. A failing task is logged and
        its result is None. Tests replace this with a synchronous version.
        """
        def target() -> None:
            try:
                result = work()
            except Exception:                       # a helper must never take the app down
                log.exception("background task failed")
                result = None
            self.relay.background_done.emit(done, result)

        threading.Thread(target=target, name="quill-background", daemon=True).start()

    def _mirror_everywhere(self, path: str, changes: list) -> MirrorResult:
        """Show the written cells in the program that has the file open, as each turn ends.

        With several programs open at once (Excel with one workbook, Numbers with another, LibreOffice with a third), each
        turn goes to the program the last look at what is open found the file in; so switching the active file switches
        where the rows appear, with nothing to set. If that look has not found the file yet, each program is asked in turn.
        """
        known = next((f.app for f in self._open_files if f.path and os.path.realpath(f.path) == os.path.realpath(path)), "").lower()
        if "libre" in known:
            order = [self.lo_mirror]
        elif "numbers" in known:
            order = [self.mirror]
        elif known:
            return MirrorResult(False, "nodoc")                 # a program with no live display (WPS ...): the reload fallback
        else:
            order = [self.mirror, self.lo_mirror]
        failure = MirrorResult(False, "nodoc")
        for mirror in order:
            result = mirror.push(path, changes)
            if result.ok:
                return result
            if result.reason in ("denied", "error") or failure.reason == "nodoc":
                failure = result
        return failure

    def _show_in_viewer(self) -> None:
        """Quill just wrote to the file: show the same cells in the program that has it open, as they are written.

        Numbers is shown the cells directly (no reload, so no import warning and nothing flickers). Anything else, or
        Numbers failing to take them, falls back to asking the program to load the file again after a quiet moment.
        """
        bridge = self.controller.bridge
        if not isinstance(bridge, XlsxBridge):
            return
        changes = bridge.take_changes()                              # (always taken: they are not kept once this turn is written)
        if not getattr(bridge, "host_reload", True):
            return
        if not changes:
            self._host_reload.start()
            return
        path = bridge.workbook_path

        def show() -> MirrorResult:
            return self._mirror_everywhere(path, changes)

        def shown(result: object) -> None:
            if isinstance(result, MirrorResult) and result.ok:
                if self.lo_mirror.installed_note and not self._lo_noted:
                    self._lo_noted = True
                    self.window.append_log("Quill added a small script to LibreOffice (quill_mirror.py in its user scripts folder) so "
                                           "rows can appear there as they are written. It is safe to delete.")
                return                                              # the program has them: nothing to reload
            if isinstance(result, MirrorResult) and result.reason == "denied" and not self._mirror_warned:
                self._mirror_warned = True
                self.window.append_log("Numbers did not let Quill show rows as they are written. Allow it in System Settings > "
                                       "Privacy & Security > Automation (Quill > Numbers).", "warning")
            self._host_reload.start()                               # not in a program that takes live rows (or it said no): the older way

        self.run_in_background(show, shown)

    def _reload_host(self) -> None:
        """Ask the program showing the file to load what Quill just saved (or say what to do by hand)."""
        bridge = self.controller.bridge
        if not isinstance(bridge, XlsxBridge) or not bridge.workbook_path or not getattr(bridge, "host_reload", True):
            return
        path = bridge.workbook_path

        def find_and_reload() -> tuple[HostApp | None, bool]:
            host_app = self._host
            if host_app is None:
                hits = [h for h, p in self.hosts.open_excel_files() if str(p.resolve()) == path]
                host_app = hits[0] if hits else None
            reloaded = bool(host_app and host_app.reloads and self.hosts.reload(host_app, path))
            return host_app, reloaded

        self.run_in_background(find_and_reload, self._host_reloaded)

    def _host_reloaded(self, outcome) -> None:
        """A reload request finished: remember the program, and say what to do by hand if it can't be asked."""
        host_app, reloaded = outcome or (None, False)
        if host_app is None or reloaded:
            self._host = host_app or self._host
            return
        self._host = host_app
        if not host_app.reloads:
            if host_app.note and not self._host_noted:
                self._host_noted = True                         # one line of advice, not one per saved row
                self.window.append_log(f"{host_app.name}: {host_app.note}")
        else:
            self.window.append_log(f"Couldn't refresh {host_app.name}. {host_app.note}", "warning")

    #: Events after which Quill itself has just written to the workbook file.
    _WRITE_EVENTS = frozenset({"committed", "add_values", "alias_added", "undone", "searched", "cleared"})

    def _workbook_mtime(self) -> int | None:
        """When the connected workbook's file was last changed (None if unsaved or unreadable)."""
        try:
            path = self.controller.bridge.workbook_path
            return os.stat(path).st_mtime_ns if path else None
        except (BridgeError, OSError):
            return None

    def _remember_mtime(self) -> None:
        """Note the file's current state, so Quill's own writes are not mistaken for outside changes."""
        self._seen_mtime = self._workbook_mtime()

    def _on_level(self, level: float) -> None:
        """How loud the user's voice is: the sound lines on the Start buttons follow it."""
        if self.window.widget is None or not shiboken6.isValid(self.window.widget):
            return
        self.window.wave.set_level(level)
        self.sorting.voice_wave.set_level(level)

    # ------------------------------------------------------------------ #
    # Which sheet is open                                                  #
    # ------------------------------------------------------------------ #

    def _restart_check_timer(self) -> None:
        """Run the one check loop every ``sheet_check_seconds`` (the timer is only touched when the interval changed, so
        tweaking other settings never postpones a check) and say so on the refresh icons."""
        seconds = int(self.settings.preferences["sheet_check_seconds"])
        if int(self._watcher.interval()) != seconds * 1000 or not self._watcher.isActive():
            self._watcher.start(seconds * 1000)
        panel = getattr(self.window, "panel", None)
        if panel is not None:
            panel.sheet_refresh_button.setToolTip(
                f"Look at which sheet is open in the spreadsheet program now. Quill also checks every {seconds} seconds.")
            panel.refresh_button.setToolTip(
                f"Look for open spreadsheets now. The list also refreshes every {seconds} seconds.")

    def _program_holding(self, path: str) -> str:
        """``"numbers"``, ``"libreoffice"`` or ``""``: which program the last look at what is open found *path* in."""
        known = next((f.app for f in self._open_files if f.path and os.path.realpath(f.path) == os.path.realpath(path)), "").lower()
        return "libreoffice" if "libre" in known else "numbers" if "numbers" in known else ""

    def refresh_active_sheet(self, quiet: bool = False) -> None:
        """The refresh icon beside Sheet: take the check loop's look now and say which sheet is open (*quiet*: say nothing
        unless the sheet changed). There is no separate sheet timer: the sheet is part of the same look."""
        self.refresh_open_files(manual=not quiet, announce=not quiet)

    def _apply_sheet(self, sheet: str | None, quiet: bool) -> None:
        bridge = self.controller.bridge
        if not self.connected:
            return
        changed = False
        try:
            if sheet and sheet != bridge.active_sheet_name():
                if bridge.set_active_sheet(sheet):
                    changed = self.controller.follow_sheet()
            else:
                changed = self.controller.follow_sheet()                # (a live program: it says which sheet is open)
        except BridgeError as exc:
            self.window.append_log(f"Could not check the sheet: {exc}", "warning")
            return
        self._show_active_sheet()
        if not quiet and not changed:
            self.window.append_log(f"Checked: sheet '{bridge.active_sheet_name()}' is the one open.")

    def _show_active_sheet(self) -> None:
        """Tell the window which sheet is open (the folder icon's hover text names it)."""
        try:
            sheet = self.controller.bridge.active_sheet_name()
        except BridgeError:
            sheet = ""
        self.window.set_active_sheet(sheet)

    def _check_workbook_changes(self) -> None:
        """Watcher tick: if the saved file changed since we last looked, re-read its lists and columns.

        This replaces a manual Refresh button: add a column or a drop-down value in Excel, save,
        and Quill picks it up within a few seconds. A file caught mid-save is simply retried.
        """
        mtime = self._workbook_mtime()
        if mtime is None:
            return
        if self._seen_mtime is None:
            self._seen_mtime = mtime
            return
        if mtime == self._seen_mtime:
            return
        try:
            self.controller.refresh()
        except BridgeError:
            return                                   # probably being saved right now; try again next tick
        self._seen_mtime = mtime
        self.window.append_log("Workbook changed: lists and columns re-read")

    # ------------------------------------------------------------------ #
    # Menu bar                                                             #
    # ------------------------------------------------------------------ #

    def _build_menus(self) -> None:
        """Fill the window's menu bar (the OS menu bar on macOS) with every major operation; see :mod:`quill.ui.menus`."""
        w = self.window
        self.menus = QuillMenus({
            "open_file": lambda: self.choose_spreadsheet_file(), "use_excel": lambda: self.use_live_excel(),
            "refresh_files": lambda: self.refresh_open_files(manual=True),
            "settings": lambda: self.open_settings(), "settings_page": lambda page: self.open_settings(page),
            "quit": lambda: self.quit_app(),
            "toggle_listening": lambda: self.toggle_listening(not w.listening),
            "next_row": lambda: self.next_row(), "undo": lambda: self.undo(), "term_helper": lambda: self.show_sorting(),
            "new_row": lambda: self.controller.start_new_row(),
            "mode_next_row": lambda: self._set_turn_mode(NEXT_ROW), "mode_append": lambda: self._set_turn_mode(APPEND_TO),
            "mini": lambda: w.set_mini(not w.mini, notify=True),
            "files_panel": lambda: w.toggle_panel(FILE_PAGE), "turn_panel": lambda: w.toggle_panel(TURN_PAGE),
            "log": lambda: w.set_log_collapsed(not w.log_collapsed, notify=True),
            "minimize": lambda: w.widget.showMinimized(), "bring_front": lambda: self._bring_to_front(),
            "help": lambda: self.open_help(), "open_logs": lambda: open_log_folder(), "about": lambda: self._about(),
        })
        self.menus.state.file_page, self.menus.state.turn_page = FILE_PAGE, TURN_PAGE
        self.menus.install(w.widget.menuBar(), reuse={"open_file": w.open_file_action, "use_excel": w.use_excel_action})
        self._default_menu_bar = self.menus.install_default_bar()         # macOS: the same menus while Settings or Help is in front
        self._menu_timer = QTimer(self.qapp)
        self._menu_timer.setSingleShot(True)
        self._menu_timer.setInterval(0)
        self._menu_timer.timeout.connect(self._sync_menus)

    def request_menu_sync(self) -> None:
        """Something the menus show may have changed: bring them up to date (once, after the current event is handled)."""
        timer = getattr(self, "_menu_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()

    def _sync_menus(self) -> None:
        if not self._window_alive() or getattr(self, "menus", None) is None:
            return
        w, c = self.window, self.controller
        self.menus.update(
            listening=w.listening, has_file=self.connected, can_use_excel=w.use_excel_action.isEnabled(), mini=w.mini,
            panel_page=w.panel_page, log_open=not w.log_collapsed, can_undo=len(c.history) > 0,
            sorting_count=len(c.pending_terms()), turn_mode=c.turn_mode)

    def _set_turn_mode(self, mode: str) -> None:
        self.controller.set_turn_mode(mode)
        self._sync_turn_panel()

    def _bring_to_front(self) -> None:
        w = self.window.widget
        w.showNormal() if w.isMinimized() else w.show()
        w.raise_()
        w.activateWindow()

    def _about(self) -> None:
        from quill import __version__
        info(self.window.widget, f"Quill {__version__}",
             "Hands-free spreadsheet dictation. Everything runs on this computer: your voice and your spreadsheets "
             "are never sent anywhere.")

    def show_workbook(self) -> None:
        """Bring the workbook being dictated into to the front (tray click)."""
        try:
            self.controller.bridge.activate()
        except BridgeError as exc:
            self.window.append_log(str(exc), "error")

    def _find_model(self) -> pathlib.Path | None:
        """The speech model to listen with: the larger one if chosen and installed, else the standard one."""
        if self.settings.preferences["speech_quality"] == "better":
            better = self._better_finder()
            if better is not None:
                self._loaded_quality = "better"
                return better
            self.window.append_log("The Broad speech model is not installed yet: using the Quick one. "
                                   "Install it in Settings, under Speech Model.", "warning")
        self._loaded_quality = "standard"
        return self._model_finder(str(self.settings.preferences["model_path"]))

    def _make_refiner(self):
        """The Whisper second pass if "Careful" is chosen and it can run (engine and model present); else None."""
        if self.settings.preferences["speech_quality"] != "best":
            return None
        folder = self._whisper_finder()
        if folder is None or not self._whisper_engine():
            self.window.append_log("The Careful speech model is not ready (install it in Settings, under Speech Model): "
                                   "using the Quick one.", "warning")
            return None
        self._loaded_quality = "best"
        return self._refiner_factory(folder, self._whisper_hint)

    def _whisper_hint(self) -> str:
        """Words the sheet uses ("Brand: Nike, Levi's. Size: S, M."): given to Whisper so it spells them the sheet's way."""
        try:
            vocab = self.controller.vocab
            parts = [f"{column}: {', '.join(vocab.values_for(column)[:12])}." for column in vocab.columns()[:12]
                     if vocab.values_for(column)]
        except Exception:
            return ""
        return " ".join(parts)[:600]

    def quality_installed(self, quality: str) -> bool:
        """Whether the speech model for *quality* ("standard" or "better") can be found."""
        if quality == "better":
            return self._better_finder() is not None
        if quality == "best":
            return self._whisper_finder() is not None and self._whisper_engine()
        return self._model_finder(str(self.settings.preferences["model_path"])) is not None

    def _model_folder(self, quality: str):
        """Where the model for *quality* is installed (None if it is not)."""
        if quality == "better":
            return self._better_finder()
        if quality == "best":
            return self._whisper_finder()
        return self._model_finder(str(self.settings.preferences["model_path"]))

    def quality_removable(self, quality: str) -> bool:
        """Whether Settings may offer to uninstall *quality*: it was downloaded (a bundled model stays), and taking it
        away must leave something to listen with (Careful builds on Quick, so Quick stays while Careful is installed)."""
        folder = self._model_folder(quality)
        if folder is None:
            return False
        try:
            root = _user_model_dir().resolve()
            if root not in pathlib.Path(folder).resolve().parents:
                return False
        except OSError:
            return False
        if quality == "standard":
            return self.quality_installed("better") and not self.quality_installed("best")
        return True

    def uninstall_model(self, quality: str) -> None:
        """Delete the downloaded model for *quality*, and move to the next best one if it was in use."""
        if not self.quality_removable(quality):
            return
        try:
            freed = self._model_remover(self._model_folder(quality))
        except (OSError, ValueError) as exc:
            self.window.append_log(f"Could not remove the {QUALITY_LABELS[quality]} speech model: {exc}", "error")
            return
        self.window.append_log(f"{QUALITY_LABELS[quality]} speech model removed ({freed // (1024 * 1024)} MB freed)")
        if str(self.settings.preferences["speech_quality"]) == quality:
            self.settings.preferences["speech_quality"] = fallback_choice(quality, self.quality_installed)
            self.settings.save()
            self.window.append_log(f"Now using the {QUALITY_LABELS[self.settings.preferences['speech_quality']]} speech model")
            self._reload_listener()
        self._show_model_state()
        self.sync_model_panel()

    def _use_best_installed(self) -> None:
        """Once, on the first start with this feature, choose the best model already installed."""
        prefs = self.settings.preferences
        if prefs["model_migrated"]:
            return
        prefs["model_migrated"] = True
        for quality in ("best", "better"):
            if self.quality_installed(quality):
                prefs["speech_quality"] = quality
                break
        self.settings.save()

    def _reload_listener(self) -> None:
        """Listen with the model now chosen: close the microphone and the old listener, then start the new one."""
        if self.listener is not None:
            if self._mic_open:
                self.listener.stop()
                self._mic_open = False
            self.listener = None
        self._start_listener()

    def _start_listener(self) -> None:
        model = self._find_model()
        if model is None:
            self.window.append_log("No speech model found. Install one in Settings, under Speech Model, "
                                   "to start dictating.", "warning")
            return
        self.listener = self._listener_factory(model, self.relay.transcript.emit, self.relay.error.emit)
        set_partial = getattr(self.listener, "set_partial_callback", None)
        if set_partial is not None:
            set_partial(self.relay.partial.emit)                      # words appear in the Voice Stream as they are heard
        set_refiner = getattr(self.listener, "set_refiner", None)
        if set_refiner is not None:
            set_refiner(self._make_refiner())                         # "Careful": each finished phrase is re-read by Whisper
        set_level = getattr(self.listener, "set_level_callback", None)
        if set_level is not None:
            set_level(self.relay.level.emit)                          # the sound lines follow the user's voice
        preload = getattr(self.listener, "preload", None)
        if preload is not None:
            preload()                                   # load the model now; the mic stays off
        self._mic_open = False
        self._sync_mic()
        if not self._mic_open:
            if self.connected:
                self.window.append_log(READY_NOTE)
            else:
                self._ready_note_pending = True               # no "ready, press Start" next to a warning: say it once a file is connected

    def mic_wanted(self) -> bool:
        """Should the microphone be open right now?

        Only while Quill is listening, while a spoken answer is being waited for
        (a yes / no question, voice sorting), or if the user chose to keep it
        always on so they can say "start listening".
        """
        if self.listener is None:
            return False
        return bool(self.controller.session.listening
                    or self.controller.voice_sorter is not None
                    or self.controller.session.awaiting_answer
                    or self.settings.preferences["mic_always_on"])

    def _sync_mic(self) -> None:
        """Open or close the microphone to match :meth:`mic_wanted` (and say so in the log)."""
        if self.listener is None:
            return
        want = self.mic_wanted()
        if want and not self._mic_open:
            self.listener.start()
            self._mic_open = True
            self.window.append_log("Microphone On")
        elif not want and self._mic_open:
            self.listener.stop()
            self._mic_open = False
            self.window.append_log("Microphone Off")
        self._restart_quiet_timer(keep_running=True)       # starts when something opens the microphone for Quill

    @staticmethod
    def _default_listener(model: pathlib.Path, on_transcript, on_error) -> Listener:
        return Listener(model, on_transcript, on_error=on_error)

    # ------------------------------------------------------------------ #
    # User actions                                                         #
    # ------------------------------------------------------------------ #

    def _needs_fresh_look(self) -> bool:
        """Is the connected file one whose window could have been closed since the last look (so it must be checked before
        the microphone opens)?"""
        bridge = self.controller.bridge
        return (self.connected and isinstance(bridge, XlsxBridge) and bool(bridge.workbook_path)
                and not os.environ.get("QUILL_NO_HOSTS"))

    def toggle_listening(self, active: bool, _checked: bool = False) -> None:
        """Open or close the listening gate (button, tray, or menu).

        Starting first takes a fresh look at the spreadsheet programs (a fraction of a second): if the file's window was
        closed since the last look, Quill lets go of it instead of recording rows into a file nobody is looking at.
        """
        if active and not _checked and self._needs_fresh_look():
            self.refresh_open_files(manual=True, then=lambda: self.toggle_listening(True, _checked=True))
            return
        if active and not self.connected and not self._released_file(self.controller.bridge):
            self.connect_workbook(str(self.settings.preferences["last_workbook"]) or None,
                                  quiet=True)
            if not self.connected:                  # nothing to fill in yet: the Files panel opens, to pick or choose a file
                if self.window.panel_page == FILE_PAGE:         # already showing: point at Open File and open the file window
                    self.window.panel.flash_file_button()
                    self.choose_spreadsheet_file()
                else:
                    self.window.open_panel(FILE_PAGE)
        if not active:
            self._start_wanted = False                                    # (a Start that was waiting for the file to open is cancelled)
        if active and self.connected and not self._viewer_open():     # Quill only writes to a file that is open to be seen
            self._wait_for_viewer()
            return
        self.controller.set_listening(active)   # explains what to do if there is no workbook

    def next_row(self) -> None:
        """The next-row arrow: clear the heard words, save what was understood and get ready for new input."""
        if not self.controller.session.listening:
            return
        self.controller.next_row()
        self.window.end_stream()
        self.window.clear_stream()
        self.window.update_current_row(self.controller.session.record)

    def refresh(self) -> None:
        """Re-read the workbook (or connect, if not yet connected)."""
        if not self.connected:
            self.connect_workbook()
            return
        try:
            self.controller.refresh()
        except BridgeError as exc:
            self.connected = False
            self.window.append_log(f"Lost the workbook: {exc}", "error")
            return
        self.window.update_workbooks(self.controller.bridge.open_workbooks(),
                                     self.controller.bridge.workbook_name)
        self.window.append_log("Workbook re-read")

    def resolve_term(self, key: TermKey, decision: Decision, term: str) -> None:
        """The user decided what to do with an unrecognised term."""
        self.controller.resolve_term(key, decision, term)
        self.refresh_sorting()

    def refresh_sorting(self, reveal: bool = False) -> None:
        """Sync the Needs-sorting list and button with the pending terms."""
        pending = self.controller.pending_terms()
        self.sorting.set_items(pending)
        self.window.set_sorting_count(len(pending))
        self.tray.set_badge(len(pending))
        undoable = len(self.controller.history)
        self.sorting.set_undo_available(undoable)
        self.window.set_undo_count(undoable)
        self._sync_titlebar_undo()
        if reveal and pending:
            self.sorting.show()

    def undo(self) -> None:
        """Take back the last sorting answer (button); the event refreshes the list."""
        self.controller.request_undo()

    def toggle_voice_sorting(self) -> None:
        """Start or stop answering the Needs-sorting list by voice."""
        if self.controller.voice_sorter is not None:
            self.controller.stop_voice_sort()
        elif not self.controller.start_voice_sort():
            self.window.append_log("Nothing to sort")
            self.sorting.set_voice_active(False)

    def show_sorting(self) -> None:
        """Open the Term Helper window (the main window's Term Helper button and the tray menu call this)."""
        self.refresh_sorting(reveal=True)

    # ------------------------------------------------------------------ #
    # Working on a file instead of live Excel                              #
    # ------------------------------------------------------------------ #

    def _warm_file_dialog(self) -> None:
        """Get the system's file window ready (see :class:`FileDialogWarmer`), once Quill is the program in front, so
        the first Open File is not slow to appear. Not while the user is in another program (it would pull Quill forward)."""
        if os.environ.get("QUILL_NO_HOSTS") or self._file_dialog_warmer.done:
            return
        if self.qapp.applicationState() != Qt.ApplicationState.ApplicationActive:
            self.qapp.applicationStateChanged.connect(self._warm_when_active)
            return
        self._file_dialog_warmer.start()

    def _warm_when_active(self, state) -> None:
        if state == Qt.ApplicationState.ApplicationActive:
            self.qapp.applicationStateChanged.disconnect(self._warm_when_active)
            QTimer.singleShot(FILE_DIALOG_WARM_MS, self._warm_file_dialog)

    def _ask_for_file(self) -> str | None:
        """Show the standard file picker for a spreadsheet file (.xlsx, .csv, .tsv); None if the user cancels."""
        from PySide6.QtWidgets import QFileDialog
        self._file_dialog_warmer.cancel()
        remembered = self.controller.bridge.workbook_path if self.connected else ""   # where the active file is
        remembered = remembered or str(self.settings.preferences["workbook_file"])
        start = str(pathlib.Path(remembered).parent) if remembered else str(pathlib.Path.home() / "Documents")
        path, _ = QFileDialog.getOpenFileName(self.window.widget, "Open File", start,
                                              "Spreadsheets (*.xlsx *.csv *.tsv);;Excel Workbooks (*.xlsx);;Text Tables (*.csv *.tsv)")
        return path or None

    def choose_spreadsheet_file(self) -> None:
        """File > Open File…: pick an .xlsx or .csv and work on it directly (no Excel needed)."""
        path = self._file_chooser()
        if path and self.open_workbook_file(path):
            self._launch_unless_open(path)

    def open_workbook_file(self, path: str | pathlib.Path, remember: bool = True) -> bool:
        """Switch to working on the .xlsx or .csv at *path* through the file bridge.

        The file is edited in place and saved after every change, so close it in other
        programs while dictating (or reopen it afterwards to see the new rows). An old
        macro-enabled .xlsm is not accepted, because saving it this way would drop its macros.

        Returns:
            True if Quill is now working on the file; otherwise the previous workbook is kept.
        """
        path = pathlib.Path(path)
        if path.suffix.lower() not in (".xlsx", ".csv", ".tsv") or not path.is_file():
            self.window.append_log(f"Can't open '{path.name}': choose a spreadsheet file (.xlsx or .csv).", "error")
            return False
        previous, was_connected = self.controller.bridge, self.connected
        if was_connected:
            self.controller.detach()                     # closes the listening gate on the old workbook
            self.connected = False
            self._set_listening(False)
        self.controller.bridge = CsvBridge(path) if path.suffix.lower() in (".csv", ".tsv") else XlsxBridge(path)
        self.connect_workbook()
        if not self.connected:                           # unreadable file: go back to what we had
            self.controller.bridge = previous
            if was_connected:
                self.connect_workbook(quiet=True)
            return False
        if remember:
            self.settings.preferences["workbook_file"] = str(path)
            self.settings.save()
        self.window.set_file_mode(True)
        self.window.append_log(f"Working on the file {path.name}")
        return True

    # ------------------------------------------------------------------ #
    # The side panel                                                       #
    # ------------------------------------------------------------------ #

    def _wire_panel(self) -> None:
        """Connect the side panel's choices to the application, and fill in what it shows."""
        panel = self.window.panel
        panel.settings.apply_density(str(self.settings.preferences["spacing"]))
        self.sync_model_panel()
        panel.open_file_requested.connect(self.choose_spreadsheet_file)
        panel.file_chosen.connect(self._panel_pick)
        panel.refresh_requested.connect(lambda: self.refresh_open_files(manual=True))
        panel.speech_model_chosen.connect(self.choose_speech_model)
        panel.sheet_refresh_requested.connect(lambda: self.refresh_active_sheet(quiet=False))
        panel.speech_models_requested.connect(lambda: self.open_settings("Speech Model"))
        panel.mode_changed.connect(self.controller.set_turn_mode)
        panel.layout_changed.connect(self.controller.set_vertical)
        panel.new_row_requested.connect(self.controller.start_new_row)
        panel.start_row_changed.connect(self.controller.set_start_row)
        panel.headings_row_changed.connect(self.controller.set_headings_row)
        panel.keywords_requested.connect(lambda: self.open_settings("Keywords"))
        panel.learned_counter = lambda path: len(self.settings.links.for_file(path, self.controller.vocab.headers()))
        panel.learned_words_requested.connect(lambda: self.open_settings("Learned Words", this_file=True))
        self._sync_turn_panel()
        self.window.set_panel_listener(self._panel_toggled, self._panel_width)

    def _flush_waiting(self) -> None:
        self._flush_held()

    def _flush_held(self, final: bool = False) -> None:
        """Save changes the file's holder refused; after a few tries (or on quitting) keep a copy beside the file."""
        bridge = self.controller.bridge
        if not getattr(bridge, "dirty", False):
            self._flush_failures = 0
            return
        if bridge.flush():
            self._flush_failures = 0
            if not final:
                self.window.append_log(f"The file is free again: saved the waiting rows to {bridge.workbook_name}")
            return
        self._flush_failures += 1
        if final or self._flush_failures == FLUSH_COPY_AFTER:
            copy = bridge.save_copy()
            if copy and not final:
                self.window.append_log(f"{bridge.workbook_name} is still in use. Saved the waiting rows to a copy: {copy}", "warning")
            elif copy:
                log.warning("quit with unsaved rows; copy saved to %s", copy)

    def _active_kind(self) -> str:
        """What the active file is open in or stored as, for the panel: Excel, LibreOffice Calc, CSV ..."""
        bridge = self.controller.bridge
        if isinstance(bridge, CsvBridge):
            return "CSV file" if bridge.workbook_path.lower().endswith(".csv") else "TSV file"
        if not isinstance(bridge, XlsxBridge):
            return "Excel (live)"
        if self._host is not None:
            return f"Excel (.xlsx), open in {self._host.name}"
        return "Excel (.xlsx)"

    def _align_titlebar(self, tries: int = 6) -> None:
        """Centre the title bar icons on the title, a few times a moment apart (the system lays them out after we ask)."""
        buttons = [b for b in (self._titlebar, self._titlebar_left) if b is not None]
        if not buttons or tries <= 0:
            return
        off = max(abs(b.align()) for b in buttons)
        if off > 0.5:
            QTimer.singleShot(140, lambda: self._align_titlebar(tries - 1))

    def _panel_size_changed(self, width: int) -> None:
        """The user dragged the side panel to a new width: it opens that wide from now on."""
        self.settings.preferences["panel_width"] = int(width)
        self.settings.save()

    def _log_height_changed(self, height: int) -> None:
        """The user dragged the log to a new height: it opens that tall from now on."""
        self.settings.preferences["log_height"] = int(height)
        self.settings.save()

    def _sorting_moved(self, x: int, y: int, width: int) -> None:
        """The Term Helper was moved or resized: it opens there from now on (set once, kept)."""
        prefs = self.settings.preferences
        prefs["sorting_x"], prefs["sorting_y"], prefs["sorting_width"] = x, y, width
        self.settings.save()

    def _sync_turn_panel(self) -> None:
        """Show the saved turn options on the panel's turn page."""
        self.request_menu_sync()
        c = self.controller
        prefs = self.settings.preferences
        self.window.panel.set_options(c.turn_mode, c.vertical, int(prefs["start_row"]), int(prefs["headings_row"]))

    def _panel_width(self, width: int) -> None:
        """The panel is at *width* (it slides): the title bar icons stay left of its edge, which gets a line."""
        set_title_inset(self.window.widget, width)           # "Quill" stays centred in the room that is left
        if self._titlebar is not None:
            self._titlebar.set_inset(width)

    def _show_titlebar_panel(self, page: str) -> None:
        """Keep the folder / turn icon of the open panel filled."""
        if self._titlebar is not None:
            self._titlebar.set_extra_active(0, page == FILE_PAGE)
            self._titlebar.set_extra_active(1, page == TURN_PAGE)

    def _panel_toggled(self, page: str) -> None:
        self.request_menu_sync()
        self._show_titlebar_panel(page)
        if page and self._titlebar is not None:
            self._titlebar.set_panel_title(TITLES[page])
        self._panel_toggled_pages(page)

    def _panel_toggled_pages(self, page: str) -> None:
        """The panel opened on *page* or closed (""): the file page takes a fresh look at what is open."""
        if page == FILE_PAGE:
            self.refresh_open_files()                                  # (the list is kept current by the one check loop)
        if page == TURN_PAGE:
            self._sync_turn_panel()

    def _scan_open_files(self) -> list[OpenFile]:
        """Ask the running spreadsheet programs what they have open (runs off the GUI thread)."""
        return self._scan().files

    def _scan(self) -> Look:
        """The one look at the spreadsheet programs, off the GUI thread (see :class:`Look`).

        Cost: one ``ps`` always; one ``osascript`` when Numbers runs (it names its documents, their files and their open
        sheets in one answer); one LibreOffice job when LibreOffice holds the file; Excel's own list when Excel runs. Nothing
        is started: a program that is not running is never asked.
        """
        bridge = self.controller.bridge
        active = getattr(bridge, "workbook_path", "") if isinstance(bridge, XlsxBridge) else ""
        has_sheets = bool(active) and not isinstance(bridge, CsvBridge)

        def excel_files() -> list[tuple[str, str]]:
            live = bridge if hasattr(bridge, "open_workbook_files") else self._live_bridge_factory()
            return live.open_workbook_files()

        running = self.hosts.running()
        self._viewer_running = bool(running)                              # (any spreadsheet program is running at all)
        found = self.hosts.open_files(excel_files, prefer=(active,) if active else (), running=running)
        complete = bool(getattr(self.hosts, "last_look_complete", True))
        sheet: str | None = None
        if active:
            wanted = os.path.realpath(active)
            here = next((f for f in found if f.path and os.path.realpath(f.path) == wanted), None)
            keys = {a.key for a in running}
            if here is not None and here.sheet:
                sheet = here.sheet
            elif here is not None and has_sheets and ("libre" in here.app.lower() or "numbers" in here.app.lower()):
                sheet = self._ask_mirror(self.lo_mirror if "libre" in here.app.lower() else self.mirror, active)
            elif here is None:                                            # a program that did not list it may still hold it
                for key, name, mirror in (("numbers", "Numbers", self.mirror), ("libreoffice", "LibreOffice", self.lo_mirror)):
                    if key not in keys:
                        continue
                    if self._mirror_has(mirror, active):                       # (rare: only when no program listed it)
                        answer = self._ask_mirror(mirror, active) if has_sheets else None
                        found.append(OpenFile(pathlib.Path(active).name, active, name, sheet=answer or ""))
                        sheet = answer
                        break
        try:
            names: list[str] | None = bridge.open_workbooks()                # Excel's workbooks, or the file's own name
        except BridgeError:
            names = []                                                       # Excel not running
        except Exception:                                                    # (a helper never stops a look)
            log.debug("could not list the workbooks", exc_info=True)
            names, complete = None, False
        return Look(found, sheet, complete, bridge, names)

    @staticmethod
    def _ask_mirror(mirror, path: str) -> str | None:
        """The sheet *mirror*'s program has open for *path* (None: not open there or no answer)."""
        try:
            return mirror.active_sheet(path)
        except Exception:                                                  # (a helper never stops a look)
            log.debug("could not ask a program for the open sheet", exc_info=True)
            return None

    @staticmethod
    def _mirror_has(mirror, path: str) -> bool:
        try:
            return bool(mirror.has_document(path))
        except Exception:
            log.debug("could not ask a program for a document", exc_info=True)
            return False

    def _viewer_open(self) -> bool:
        """Is the connected file open in a spreadsheet program the user can see?

        Quill is an overlay for the user's spreadsheet programs, not a stand-alone editor: it writes to a file only while
        that file is open in one of them (whichever it is: Excel, Numbers, LibreOffice ... even several at once, each with
        its own file), so every row can be seen arriving and confirmed. Excel is driven live, so it always counts. For a
        file, it must be listed as open in some program (:meth:`_scan_open_files` asks each program, including the ones
        that report a document by name only). Where the system cannot be asked, it counts.
        """
        bridge = self.controller.bridge
        if os.environ.get("QUILL_NO_HOSTS") or not isinstance(bridge, XlsxBridge) or not bridge.workbook_path:
            return True
        wanted = os.path.realpath(bridge.workbook_path)
        return any(f.path and os.path.realpath(f.path) == wanted for f in self._open_files)

    #: How long (s) a file counts as "just opened" after Quill asked a program to open it: it is not asked again meanwhile
    #: (opening it a second time makes some programs, Numbers among them, open a second copy in a new window).
    JUST_LAUNCHED_S = 45
    #: How often (ms) and how many times Quill looks for the file to show up in a program while a Start is waiting.
    VIEWER_LOOK_MS, VIEWER_LOOKS = 1500, 24

    def _just_launched(self, path: str | pathlib.Path) -> bool:
        return time.monotonic() - self._launched_at.get(os.path.realpath(path), -1e9) < self.JUST_LAUNCHED_S

    def _launch(self, path: str | pathlib.Path) -> bool:
        """Ask a program to open *path* (only if that was not just done), and keep Quill in front. True if it was asked."""
        if self._just_launched(path):
            return False
        now = time.monotonic()
        self._launched_at = {k: t for k, t in self._launched_at.items() if now - t < self.JUST_LAUNCHED_S}   # (forget old ones)
        self._launched_at[os.path.realpath(path)] = now
        ok = self.hosts.launch(path, str(self.settings.preferences["open_with"]))
        if ok:
            for delay in (400, 1500):                           # a program that starts slowly may still take the focus
                QTimer.singleShot(delay, lambda: bring_app_forward(self.window.widget))
        return ok

    def _wait_for_viewer(self) -> None:
        """Start was pressed with the file not (yet) seen open in a spreadsheet program.

        Quill looks for it, asks a program to open it only if nobody has it (and only once), keeps looking, and starts
        listening the moment it is open: pressing Start again is not needed (and never opens it again).
        """
        self._start_wanted = True
        if self._waiting_viewer:
            return                                                    # one watcher at a time
        self._waiting_viewer = True
        self._viewer_looks = 0
        self.window.append_log(f"Waiting for {self.controller.bridge.workbook_name} to open in your spreadsheet program. "
                               "Quill writes to the file only while it is open there, and starts listening as soon as it is.",
                               "warning", reveal=False)
        self._viewer_look()

    def _viewer_look(self) -> None:
        self.run_in_background(self._scan_open_files, self._viewer_looked)

    def _viewer_looked(self, found: list[OpenFile] | None) -> None:
        if found is not None:
            self._open_files = found
        if not self._start_wanted or not self.connected:
            self._waiting_viewer = False                              # Stop was pressed, or the file is gone
            return
        if self._viewer_open():
            self._waiting_viewer = False
            self._start_wanted = False
            self._attach_live_if_open_in_excel()
            self.controller.set_listening(True)
            return
        path = self.controller.bridge.workbook_path
        name = self.controller.bridge.workbook_name
        if found is not None and not self._just_launched(path):
            if not self._launch(path):
                self._waiting_viewer = False
                self._start_wanted = False
                self.window.append_log(f"Could not open {name} in a spreadsheet program. Open it yourself, then press Start.", "warning")
                return
        self._viewer_looks += 1
        if self._viewer_looks >= self.VIEWER_LOOKS:
            self._waiting_viewer = False
            self._start_wanted = False
            self.window.append_log(f"{name} did not open. Open it yourself in a spreadsheet program, then press Start.", "warning")
            return
        QTimer.singleShot(self.VIEWER_LOOK_MS, self._viewer_look)

    def _window_alive(self) -> bool:
        """Is the main window still there (it is gone while Quill quits, and a late timer or look must not touch it)?"""
        widget = self.window.widget
        return widget is not None and shiboken6.isValid(widget)

    def refresh_open_files(self, manual: bool = False, announce: bool = False, then=None) -> None:
        """Take the one look at the spreadsheet programs (never two at once; one asked for meanwhile runs right after).

        It refreshes the Available Files list, lets go of the file if its window was closed, notices the program's open sheet
        and, with no file, picks up a file another program has open. *manual*: a refresh icon or Start asked, so a closed
        spreadsheet is acted on at once (a timer's look is trusted only when every question was answered anyway).
        *announce*: say which sheet is open. *then*: called when the look is done (Start waits for it).
        """
        if self._quitting or not self._window_alive():
            return                                                     # (a late timer after the window is gone)
        if self._open_files_busy:
            queued = self._look_again or (False, False, [])
            self._look_again = (queued[0] or manual, queued[1] or announce, queued[2] + ([then] if then else []))
            return
        self._open_files_busy = True
        self.run_in_background(self._scan, lambda result: self._looked(result, manual, announce, [then] if then else []))

    def _looked(self, result, manual: bool, announce: bool, thens: list) -> None:
        """The look finished (on the GUI thread): apply what it found."""
        self._open_files_busy = False
        if self._quitting or not self._window_alive():
            return
        if isinstance(result, Look) and result.bridge is self.controller.bridge:     # (not for a bridge swapped meanwhile)
            self._open_files = result.files
            if result.names is not None:
                self._poll_local(result.names)                                 # attach / detach / re-read a changed file
            self._check_link(manual, result.complete)
            if self.connected:
                self._apply_sheet(result.sheet, quiet=not announce)
            if not self.connected:
                self._attach_found_file()
        self._attach_live_if_open_in_excel()
        self._show_open_files()
        for callback in thens:
            callback()
        if self._look_again is not None:
            queued, self._look_again = self._look_again, None
            self.refresh_open_files(queued[0], queued[1], self._chain(queued[2]))

    @staticmethod
    def _chain(callbacks: list):
        """One callback that calls all of *callbacks* (None when there are none)."""
        if not callbacks:
            return None
        return lambda: [callback() for callback in callbacks]

    def _attach_found_file(self) -> None:
        """With no file, work on the first ``.xlsx`` another spreadsheet program has open (unless a program was chosen in
        the settings, or Quill already holds a file it let go of)."""
        if (self._attach_paused or isinstance(self.controller.bridge, XlsxBridge)
                or str(self.settings.preferences["spreadsheet_app"]) not in ("auto", "")):
            return
        for entry in self._open_files:
            host_app = next((a for a in HOST_APPS if a.name == entry.app and not a.live), None)
            if host_app is None or entry.live or not entry.path.lower().endswith(".xlsx") or not pathlib.Path(entry.path).is_file():
                continue
            if self.open_workbook_file(pathlib.Path(entry.path), remember=False):
                self._host = host_app
                log.info("working on %s, open in %s", entry.name, host_app.name)
                self.window.append_log(f"Found {entry.name} open in {host_app.name}: now working on it.")
                return

    def _check_link(self, manual: bool = False, complete: bool = True) -> None:
        """Notice that the connected file's spreadsheet window was closed (the link is dead) and let go of the file.

        Quill only writes to a file while it is open in a program, so a closed window means Quill goes back to how it
        starts: no active file (the Open File button), not listening, and the file back among the other files if it is
        still open somewhere. Only a file that was seen open is let go (a file remembered from the last run that no program has
        open yet stays connected until Start opens it). The look must have been *complete* (every question answered): a program that is busy or slow
        to answer gives an incomplete look, which says nothing about the file.
        """
        bridge = self.controller.bridge
        if not self.connected or self._waiting_viewer or not isinstance(bridge, XlsxBridge) or not bridge.workbook_path:
            return
        wanted = os.path.realpath(bridge.workbook_path)
        if self._viewer_open():
            self._seen_open = wanted                                    # (it is open: a later look that misses it means it closed)
            return
        if self._seen_open != wanted or not complete or self._just_launched(bridge.workbook_path):
            return                                                      # (never seen open, e.g. just after start-up: Start opens it)
        self._seen_open = ""
        self._attach_paused = True                                      # (it waits for the user to choose, however many files are open)
        closed = bridge.workbook_name
        self.settings.preferences["workbook_file"] = ""             # (a restart starts with no file, like the first time)
        self.settings.save()
        self.controller.detach()
        self.connected = False
        self._set_listening(False)
        try:
            self.controller.bridge = self._live_bridge_factory()        # back to how Quill starts: no file, nothing to reattach
            self.window.set_file_mode(False)
        except NotImplementedError:
            pass                                                        # (no live program here: _released_file keeps it let go)
        self.tray.set_workbook("", "")
        self.window.update_workbooks([])
        self.window.set_not_connected(True)
        self.window.append_log(f"{closed} was closed in your spreadsheet program, so Quill let go of it. "
                               "Open it again, or pick another file.", "warning")

    def _attach_live_if_open_in_excel(self) -> bool:
        """Working on an .xlsx file that Excel now has open: work through Excel itself instead, so there is no file for
        the two programs to fight over (Excel on Windows refuses writes to a file it holds)."""
        bridge = self.controller.bridge
        if not self.connected or not isinstance(bridge, XlsxBridge) or isinstance(bridge, CsvBridge) or not bridge.workbook_path:
            return False
        wanted = os.path.realpath(bridge.workbook_path)
        for entry in self._open_files:
            if entry.live and entry.path and os.path.realpath(entry.path) == wanted:
                bridge.flush()                                     # anything held goes to the file first
                self.use_live_excel()
                self.connect_workbook(entry.name)
                if self.connected:
                    self.window.append_log(f"Excel has {entry.name} open, so Quill now works in Excel directly (no file lock)")
                return self.connected
        return False

    def _is_active(self, entry: OpenFile) -> bool:
        """Is *entry* the file Quill is working on now?"""
        bridge = self.controller.bridge
        if not self.connected:
            return False
        if entry.path and bridge.workbook_path:
            return os.path.realpath(entry.path) == os.path.realpath(bridge.workbook_path)
        return entry.live and not isinstance(bridge, XlsxBridge) and entry.name == bridge.workbook_name

    def _show_open_files(self) -> None:
        """List the open spreadsheets in the panel: the active one first, marked, then the others (the active one is also
        shown above, in Active File)."""
        listed = [f for f in self._open_files]
        active = next((f for f in listed if self._is_active(f)), None)
        if active is None and self.connected and self._viewer_open():     # counted as open though no program reported it (Excel, or no system lookups)
            bridge = self.controller.bridge
            if getattr(bridge, "workbook_path", ""):
                active = OpenFile(bridge.workbook_name, bridge.workbook_path, "")
            else:
                active = OpenFile(bridge.workbook_name, "", "Excel", live=True)
        entries = [(f.name, f"{f.path or f.name}\nOpen in {f.app}" if f.app else f"{f.path or f.name}", f, False)
                   for f in listed if not self._is_active(f)]
        if active is not None:
            where = f"\nOpen in {active.app}" if active.app else ""
            entries.insert(0, (active.name, f"{active.path or active.name}{where}\nThe file Quill is working on.", active, True))
        self.window.panel.set_available(entries)

    def _panel_pick(self, entry: OpenFile) -> None:
        """A spreadsheet was picked in the panel's list: work on it (it moves up to the active section)."""
        if self._is_active(entry):
            return                                                    # (it is the one Quill is working on already)
        if entry.live:
            if isinstance(self.controller.bridge, XlsxBridge):
                self.use_live_excel()
            self.connect_workbook(entry.name)
        else:
            self.open_workbook_file(entry.path)
        self._show_open_files()

    def _launch_unless_open(self, path: str | pathlib.Path) -> None:
        """A file was chosen with the file window: if Excel already has it, work through Excel; if no program has it
        open, start it in its own program too (and keep Quill in front)."""
        def check() -> list[OpenFile] | None:
            return self._scan_open_files()

        def decide(found: list[OpenFile] | None) -> None:
            wanted = os.path.realpath(path)
            if found is not None:
                self._open_files = found
            if found and any(f.path and os.path.realpath(f.path) == wanted for f in found):
                self._attach_live_if_open_in_excel()
                return
            if found is not None and self._launch(path):
                for delay in (2500, 6000, 12000):                  # then notice if Excel is the one that opened it
                    QTimer.singleShot(delay, self.refresh_open_files)

        self.run_in_background(check, decide)

    def use_live_excel(self) -> None:
        """Go back to whichever workbook is open in Excel."""
        try:
            bridge = self._live_bridge_factory()
        except NotImplementedError as exc:
            self.window.append_log(str(exc), "error")
            return
        if self.connected:
            self.controller.detach()
            self.connected = False
            self._set_listening(False)
        self.controller.bridge = bridge
        self.settings.preferences["workbook_file"] = ""
        self.settings.save()
        self.window.set_file_mode(False)
        self.window.append_log("Using the workbook open in your spreadsheet program")
        self.connect_workbook(quiet=True)

    def open_help(self, topic: str | None = None) -> None:
        """Open the help window on *topic* (a page's slug), creating it on first use."""
        if self.help is None:
            self.help = HelpWindow()
            self.help.setup()
            self.help.restyle(self.settings.preferences, self.qapp)
        self.help.show(topic)

    def _active_file_facts(self) -> tuple[str, str, list[str]]:
        """``(path, name, columns)`` of the file Quill works on, for the Learned Words list ("" and [] with none)."""
        bridge = self.controller.bridge
        path = str(getattr(bridge, "workbook_path", "") or "") if self.connected else ""
        return path, os.path.basename(path), self.controller.vocab.headers() if path else []

    def open_settings(self, page: str | None = None, this_file: bool = False) -> None:
        """Show the Settings window (not modal: the app stays usable, and can be quit, while it is open), on *page* if given.

        *this_file* opens Learned Words on the active file's words.
        """
        if self._settings_dialog is not None:                 # already open: bring it forward, never a second one
            self._settings_dialog.bring_forward()
            if this_file:
                self._settings_dialog.show_learned_for_file()
            elif page:
                self._settings_dialog.show_page_named(page)
            return
        self._settings_dialog = SettingsDialog(
            self.settings, self.window.widget, on_preview=self.preview_feedback,
            on_change=lambda: self.apply_settings(quiet=True),
            on_download_model=self.download_model, model_installed=self.quality_installed,
            on_uninstall_model=self.uninstall_model, model_removable=self.quality_removable,
            program_available=self.hosts.installed, active_file=self._active_file_facts)
        self._show_model_state()
        self._settings_dialog.open(on_done=self._settings_closed)
        if this_file:
            self._settings_dialog.show_learned_for_file()
        elif page:
            self._settings_dialog.show_page_named(page)

    def _settings_closed(self, accepted: bool) -> None:
        """The Settings window closed: forget it, and apply the result if it was saved."""
        self._settings_dialog = None
        if accepted and not self._quitting:
            self.apply_settings()

    def quit_app(self) -> None:
        """Quit from anywhere (menu bar, Dock, Cmd-Q): close every window first, whatever is open, then leave.

        A modal Settings window used to be able to hold the application back; here it is closed first, the
        other windows are closed, the microphone is released, and a fail-safe makes sure the event loop ends.
        """
        if self._quitting:
            return
        self._quitting = True
        log.info("quitting")
        if self._settings_dialog is not None:
            self._settings_dialog.close_now()
        for widget in list(self.qapp.topLevelWidgets()):
            widget.close()
        self.shutdown()
        self.qapp.quit()
        if self.quit_failsafe_ms:
            QTimer.singleShot(self.quit_failsafe_ms, lambda: self.qapp.exit(0))    # fail-safe if a nested event loop lingers

    def _native_rebuilt(self) -> None:
        """A window came back after being closed on a new native window: style it and add its title bar icons again."""
        self._titlebar = self._titlebar_left = None
        self.sorting._titlebar = None
        self._apply_look()
        self._install_titlebar_button()
        self.sorting.install_titlebar()
        self.window.set_mini_on_top(bool(self.settings.preferences["mini_on_top"]))

    def _install_titlebar_button(self) -> None:
        """Put the resize icon in the title bar (macOS); the in-window one is then hidden."""
        if self._titlebar is not None or self.window.widget is None:
            return
        self._titlebar = add_titlebar_button(
            self.window.widget, lambda: self.window.set_mini(not self.window.mini, notify=True),
            mini=self.window.mini, extra=[(SYMBOL_FOLDER, "Open File", lambda: self.window.toggle_panel(FILE_PAGE)),
                                          (SYMBOL_TURN, "Turn Settings", lambda: self.window.toggle_panel(TURN_PAGE)),
                                          (SYMBOL_SETTINGS, "Settings", self.open_settings)],
            on_panel_close=self.window.close_panel)
        native = self._titlebar is not None
        # Help, then Undo, sit right beside the window's close / minimise / zoom buttons.
        self._titlebar_left = add_titlebar_button(
            self.window.widget, self.undo, symbol=SYMBOL_UNDO, tip="Undo the Last Answer",
            extra=[(SYMBOL_HELP, "Help", lambda: self.open_help("welcome"))], side="left") if native else None
        self._align_titlebar()
        native = native and self._titlebar_left is not None
        self.window.set_native_help_button(native)
        self.window.set_native_undo_button(native)
        self._sync_titlebar_undo()
        self.window.set_native_mini_button(native)
        self.window.set_native_settings_button(native)        # Settings and resize both live in the title bar
        self.window.set_native_file_button(native)
        self.window.set_native_turn_button(native)
        self.window.set_native_panel_header(native)
        self._sync_titlebar_file(bool(self.window.workbook_name), self.window.workbook_name, self.window.sheet_name)

    def _sync_titlebar_file(self, has_file: bool, name: str, sheet: str = "") -> None:
        """Draw the title bar's folder icon: muted and closed with no file, solid and open with one."""
        self.request_menu_sync()
        if self._titlebar is None:
            return
        from quill.ui.icons import titlebar_png
        png = titlebar_png("folder-open" if has_file else "folder")
        tip = (f"{name}\nSheet: {sheet}" if has_file and sheet else name if has_file else "Open File")
        self._titlebar.set_extra_image(0, png, tip, muted=not has_file)

    def _sync_titlebar_undo(self) -> None:
        """Grey out the title bar's Undo icon while there is nothing to take back."""
        self.request_menu_sync()
        if self._titlebar_left is not None:
            self._titlebar_left.set_enabled(len(self.controller.history) > 0)

    def _remember_view(self) -> None:
        """On the way out, keep whether the mini view was showing, so the next launch opens the same way."""
        self.settings.preferences["mini_mode"] = self.window.mini
        self.settings.save()

    def _mini_toggled(self, mini: bool) -> None:
        """Remember the view and keep the tray menu and the title-bar icon in step.

        The window's stay-on-top level is changed in place, so nothing needs restyling. Only
        where that was impossible (the old, window-recreating way) is the look applied again.
        """
        self.request_menu_sync()
        self.settings.preferences["mini_mode"] = mini
        self.settings.save()
        if self._titlebar is not None:
            self._titlebar.set_mini(mini)
        if self.window.native_window_recreated:
            self.window.native_window_recreated = False
            self._titlebar = self._titlebar_left = None
            self._apply_look()
            self._install_titlebar_button()

    def _system_scheme_changed(self, *_args) -> None:
        """The operating system switched between light and dark: follow it when set to Auto."""
        if str(self.settings.preferences["theme"]) == "auto":
            self._apply_look()

    def _apply_dock(self) -> None:
        """Show or hide the Dock icon to match the setting (macOS; a no-op elsewhere).

        Changing the Dock policy makes the system take the focus away; the window that had it gets it back,
        so toggling the setting in Settings leaves Settings (or the main window) where it was.
        """
        active = self.qapp.activeWindow()
        set_dock_icon_visible(not bool(self.settings.preferences["hide_dock_icon"]))
        if active is not None:
            QTimer.singleShot(0, lambda: (active.raise_(), active.activateWindow()))

    def _app_state_changed(self, state) -> None:
        """Clicking Quill's Dock icon (or opening it from Finder) with no window up brings the window back."""
        if state == Qt.ApplicationState.ApplicationActive and self.window.widget is not None \
                and not self.window.widget.isVisible():
            self.window.show()

    def shutdown(self) -> None:
        """Quitting: close the microphone and stop the timers, so nothing is left running."""
        log.info("shutting down")
        self._watcher.stop()
        self._flush_timer.stop()
        self._flush_held(final=True)
        self._host_reload.stop()
        self._quiet_timer.stop()
        self._countdown_timer.stop()
        if self.listener is not None:
            self.listener.stop()
            self._mic_open = False

    def remove_field(self, column: str) -> None:
        """The user deleted a line of the row being built because Quill got it wrong."""
        if self.controller.remove_field(column):
            self.window.append_log(f"Removed {column} from the row")
        self.window.update_current_row(self.controller.session.record)

    def change_field(self, column: str, to_column: str) -> None:
        """The user changed which column a line of the row being built goes in (from the menu on its name)."""
        self.controller.change_field(column, to_column)
        self.window.update_current_row(self.controller.session.record)

    def answer_learn_offer(self, answer: bool | None) -> None:
        """Yes or no to "Remember ...?" (None: it timed out, so nothing is learned)."""
        if answer is None:
            self.controller.expire_learn_offer()
        else:
            self.controller.answer_learn_offer(answer)

    def _match_heard_words(self, words: list[str]):
        """What Quill makes of each word heard (understood words are drawn as pills in the Voice Stream)."""
        return match_words(words, self.controller.vocab, self.controller.session.matcher)

    def _on_phrase_heard(self, text: str) -> None:
        """A finished phrase: add it to the Voice Stream while Quill is listening."""
        if self.window.listening:
            self.window.add_stream_text(text)
            self._restart_quiet_timer()

    def _on_partial_heard(self, text: str) -> None:
        """A phrase still being spoken: show it in the Voice Stream."""
        if self.window.listening:
            self.window.set_stream_partial(text)
            self._restart_quiet_timer()

    def _mini_window_resized(self, width: int, height: int) -> None:
        """Remember the mini view's size, separately from the full window's."""
        self.settings.preferences["mini_width"] = width
        self.settings.preferences["mini_height"] = height
        self.settings.save()

    def _window_resized(self, width: int, height: int) -> None:
        """Remember the window's size, so the next launch opens the way the user left it."""
        self.settings.preferences["window_width"] = width
        self.settings.preferences["window_height"] = height
        self.settings.save()

    def _log_toggled(self, collapsed: bool) -> None:
        """Remember whether the user collapsed the log."""
        self.request_menu_sync()
        self.settings.preferences["log_collapsed"] = collapsed
        self.settings.save()

    def _apply_look(self) -> None:
        """Apply theme, accent and spacing from the settings to the app and its windows."""
        prefs = self.settings.preferences
        apply_theme(self.qapp, str(prefs["theme"]), str(prefs["accent"]), str(prefs["spacing"]),
                    int(prefs["font_size"]), backdrop=backdrop_alpha(int(prefs["opacity"]), int(prefs["blur"])))
        dark = is_dark(self.qapp)
        colors = colors_for(dark, str(prefs["accent"]))
        follows = bool(prefs["sorting_follows_opacity"])
        if self.sorting.root is not None:
            self.sorting.root.setProperty("quillSolid", not follows)     # the Term Helper asks for action: solid unless chosen
            self.sorting.root.update()
        for window, root in ((self.window.widget, self.window.root), (self.sorting.widget, self.sorting.root)):
            if window is not None:
                if window is self.sorting.widget and not follows:
                    opacity, blur = 100, 0
                else:
                    opacity, blur = int(prefs["opacity"]), int(prefs["blur"])
                if window is self.window.widget:
                    self.window.apply_density(str(prefs["spacing"]))
                else:
                    apply_spacing(window, str(prefs["spacing"]))
                apply_opacity(root, opacity, blur)                  # first: Qt marks a fully opaque window opaque
                apply_chrome(window, dark, colors, opacity=opacity, blur=blur)    # ... which the chrome may undo
                refresh_chrome_soon(window)              # the system may have rebuilt the title bar: the panel's pieces go back in
        self.window.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
        self.sorting.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
        if self.help is not None:
            self.help.restyle(prefs, self.qapp)
        self.tray.set_dark(dark)
        self.tray.set_badge(self.tray.badge, colors["accent"])
        panel = getattr(self.window, "panel", None)                 # (not built yet while the application is starting)
        if panel is not None:
            panel.settings.apply_density(str(prefs["spacing"]))

    def apply_settings(self, quiet: bool = False) -> None:
        """Push changed settings into the running app (*quiet*: a live preview, nothing logged)."""
        self._apply_look()
        self.speaker.enabled = bool(self.settings.preferences["speak_sort_prompts"])
        self.controller.apply_settings()
        self.window.set_mini_on_top(bool(self.settings.preferences["mini_on_top"]))
        self._apply_dock()
        self.sync_model_panel()
        self._restart_check_timer()
        quality = str(self.settings.preferences["speech_quality"])
        if quality != self._loaded_quality and self.listener is not None and self.quality_installed(quality):
            self._reload_listener()                          # the user chose the other speech model
            self.window.append_log(f"Now listening with the {QUALITY_LABELS[quality]} speech model")
        self._sync_mic()
        self._restart_quiet_timer()
        self.controller.lead_in_s = self.feedback.lead_in_s()
        self.refresh_sorting()
        if not quiet:
            self.window.append_log("Settings Saved")

    # ------------------------------------------------------------------ #
    # Events from the controller                                           #
    # ------------------------------------------------------------------ #

    def handle_event(self, event: Event) -> None:
        """Reflect a Session/Controller event in the window and tray."""
        self._handle_event(event)
        self.request_menu_sync()
        if event.kind in self._WRITE_EVENTS:
            self._remember_mtime()
            self._show_in_viewer()
        self._sync_mic()

    def _handle_event(self, event: Event) -> None:
        kind = event.kind
        if kind in ("committed", "discarded", "stopped"):
            self.window.end_stream()                  # the row is over: the next words start a new stream
        if event.spoken:                                          # a click confirms itself on screen: no sound
            self.feedback.request(event)
        if not self._cue_timer.isActive():
            self._cue_timer.start()
        if kind == "started":
            self._set_listening(True)
        elif kind == "stopped":
            self._set_listening(False)
        elif kind == "error" and event.terms:                      # a Term Helper answer that could not be carried out
            self.sorting.note_outcome(event.terms[0], "error")
        elif kind == "error" and event.detail == NO_WORKBOOK_HELP:
            self.window.set_not_connected(True)
            self.window.toggle_button.alert()                       # Start shakes and blinks red: it could not start (the Files panel is the way out)
            self.tray.notify(NO_WORKBOOK_HELP)
            self.window.append_log(event.detail)                          # logged as plain information (no red "!" in the mini view, the Log stays shut): the Files panel and the file window are the answer
            return
        elif kind in ("turn_on", "turn_off"):
            self._sync_turn_panel()                                  # a spoken option moves the panel's choice too
            self._show_titlebar_panel(self.window.panel_page)
        elif kind == "committed":
            self.window.clear_mini_error()
            self.window.set_last_saved(event.detail, event.record)
        elif kind == "confirm":
            self._expiry.start(int(self.settings.preferences["prompt_timeout_s"]) * 1000)
            self.refresh_sorting(reveal=True)
            if self.settings.preferences["auto_voice_sort"] and self.listener is not None:
                self.controller.start_voice_sort()
        elif kind == "open_term_helper":
            if self.controller.pending_terms():
                self.show_sorting()
            else:
                self.window.append_log("Nothing to sort")
            return
        elif kind == "sort_voice_started":
            self.sorting.set_voice_active(True)
            self.refresh_sorting(reveal=True)
            self.window.append_log(event.detail)
            return
        elif kind == "sort_voice_ended":
            self.sorting.set_voice_active(False)
            self.sorting.set_voice_status("", event.detail)
            self.window.append_log(event.detail)
            return
        elif kind == "choice":
            self.sorting.note_choice(event.record["key"], event.detail)
            return
        elif kind == "sorting":
            self.sorting.set_voice_status((event.record or {}).get("heard", ""), event.detail)
            self.window.append_log(f"Voice Sort: {event.detail}")
            self.refresh_sorting()
            return
        elif kind == "learn_offer":
            self.window.show_learn_offer(event.detail)
            return
        elif kind in ("changed", "learned", "learning", "learn_declined"):
            self.window.hide_learn_offer()
            self.window.panel.refresh_learned()
            self.window.append_log(event.detail)
            self.window.update_current_row(self.controller.session.record)
            return
        elif kind == "undone":
            self.window.append_log(event.detail)
            self.window.hide_learn_offer()                              # (an undone column change takes its question with it)
            self.window.panel.refresh_learned()
            self.window.update_current_row(self.controller.session.record)
            self.refresh_sorting(reveal=True)
            return
        elif kind in ("add_values", "alias_added", "skipped"):
            if event.resolved:
                self.sorting.note_outcome(event.resolved["key"], "ignored" if kind == "skipped" else "accepted")
            self.window.append_log(event.detail)
            self.refresh_sorting()
            return
        self.window.update_current_row(self.controller.session.record)
        if kind == "updated":
            self.refresh_sorting()                    # a word that was not understood is on the Term Helper's button at once
        if kind == "updated" and not event.detail:
            return
        self.window.append_log(self._describe(event), "error" if kind == "error" else "info")

    @staticmethod
    def _describe(event: Event) -> str:
        labels = {
            "started": "Listening Started", "stopped": "Listening Stopped",
            "committed": "Saved Row", "discarded": "Row Discarded",
            "updated": "Heard", "confirm": "Question",
            "searched": "Search", "cleared": "Search Cleared", "unsure": "Unsure",
            "undone": "Undo", "turn_on": "Turn Option", "turn_off": "Turn Option",
        }
        label = labels.get(event.kind)
        return f"{label}: {event.detail}".rstrip(": ") if label else event.detail

    def _safe_sheet(self) -> str:
        try:
            return self.controller.bridge.active_sheet_name()
        except BridgeError:
            return "–"

    def _set_listening(self, active: bool) -> None:
        self.request_menu_sync()
        self.window.set_listening_indicator(active)
        self.tray.set_listening(active)
        self._restart_quiet_timer()

    def _dictation_mic_needed(self) -> bool:
        """Is the microphone open for Quill to be told something (listening, a spoken answer, voice sorting)?"""
        session = self.controller.session
        return bool(session.listening or self.controller.voice_sorter is not None or session.awaiting_answer)

    def _restart_quiet_timer(self, keep_running: bool = False) -> None:
        """(Re)start the silence countdown while the microphone is open for Quill, otherwise stop it.

        Called whenever something is heard, when Quill finishes speaking, when listening starts and when the
        settings change. It covers every reason the microphone is open (listening, waiting for a spoken
        answer, voice sorting), except the "keep the microphone open" setting, which is the user's own
        choice to leave it on. With *keep_running* an already-running countdown is left alone (so
        unrelated events don't keep postponing it).
        """
        if not self.settings.preferences["auto_stop"] or not self._dictation_mic_needed():
            self._quiet_timer.stop()
            self._show_countdown()
            return
        if keep_running and self._quiet_timer.isActive():
            return
        self._quiet_timer.start(int(self.settings.preferences["auto_stop_seconds"]) * 1000)
        self._show_countdown()

    def _show_countdown(self) -> None:
        """Show the seconds left on the quiet timer in the window (and keep the redraw timer running only while it counts)."""
        if self.window.widget is None or not shiboken6.isValid(self.window.widget):
            self._quiet_timer.stop()                   # (the window is gone, as in a test that has finished)
            self._countdown_timer.stop()
            return
        if self._quiet_timer.isActive():
            limit = int(self.settings.preferences["auto_stop_seconds"])
            seconds = min(max(-(-self._quiet_timer.remainingTime() // 1000), 0), limit)   # rounded up, never above the setting
            self.window.set_quiet_countdown(seconds)
            self.sorting.set_voice_countdown(seconds)
            if not self._countdown_timer.isActive():
                self._countdown_timer.start()
        else:
            self._countdown_timer.stop()
            self.window.set_quiet_countdown(None)
            self.sorting.set_voice_countdown(None)

    def _quiet_for_too_long(self) -> None:
        """Nothing was said for the set time: the user has forgotten the microphone or been called away.

        Everything that keeps the microphone open for Quill ends: voice sorting, a spoken answer being
        waited for, and listening itself (the questions stay on the Term Helper list to answer later).
        """
        if self.window.widget is None or not shiboken6.isValid(self.window.widget) or not self._dictation_mic_needed():
            return                                    # (the window is gone, as in a test that has finished)
        seconds = int(self.settings.preferences["auto_stop_seconds"])
        log.info("no speech for %d s: closing the microphone", seconds)
        self.window.append_log(f"Stopped listening: nothing was said for {seconds} seconds")
        if self.controller.session.listening:
            self.controller.set_listening(False)           # first: stopping may ask the pending questions again
        if self.controller.voice_sorter is not None:
            self.controller.stop_voice_sort("Voice sorting off: nothing was said")
        if self.controller.session.awaiting_answer:
            self.controller.expire_prompt()                 # last: nothing may reopen the wait for an answer
        self._sync_mic()

    def preview_feedback(self, mode: str, pack: str, echo: str) -> None:
        """Play just the chosen sound (or say just the chosen word) from the (unsaved) Settings."""
        self.feedback.cue("success", "", mode, pack, echo)

    def _speak_word(self, word: str) -> None:
        """Say a confirmation word: from its ready-made clip at once, else live (and make the clip for next time)."""
        if self.clips.ready(word):
            self.sound_player(self.clips.path(word))
            return
        self.echo_speaker.say(word)
        self.clips.make_in_background([word], done=self._clips_ready)

    def _clips_ready(self, paths) -> None:
        """(Called on the helper thread.) New clips exist: load them on the GUI thread so they start instantly."""
        preload = getattr(self.sound_player, "preload", None)
        if preload is not None:
            self.relay.background_done.emit(preload, list(paths))

    def _warm_up_sounds(self) -> None:
        """Load every feedback sound now (the first play of each would otherwise wait for it to load) and, when
        words are spoken as confirmations, make their clips in the background."""
        preload = getattr(self.sound_player, "preload", None)
        if preload is not None:
            preload(self.feedback.sound_files(all_packs=True))
        self.clips.make_in_background(spoken_words(), done=self._clips_ready)       # always: choosing Spoken Word in
                                                                                    # Settings must play at once

    def _mute_for(self, seconds: float) -> None:
        """Keep the microphone muted while a cue is sounding."""
        if self.listener is None:
            return
        self.listener.mute()
        QTimer.singleShot(int(seconds * 1000), self.listener.unmute)

    def _on_speech(self, speaking: bool) -> None:
        """Mute the microphone while Quill talks so it doesn't hear itself."""
        if self.listener is None:
            return
        (self.listener.mute if speaking else self.listener.unmute)()
        if not speaking:
            self._restart_quiet_timer()                   # Quill's own voice is not "quiet" time

    # ------------------------------------------------------------------ #
    # Background-thread results                                            #
    # ------------------------------------------------------------------ #

    def _on_error(self, message: str) -> None:
        """Show an error from a helper thread; if the listener died, close the gate so the window doesn't
        claim to be listening to a dead microphone (and a later Start opens it again)."""
        log.error("%s", message)
        self.window.append_log(message, "error")
        if self.listener is not None and self._mic_open and not getattr(self.listener, "running", True):
            self._mic_open = False
            if self.controller.session.listening:
                self.controller.set_listening(False)

    def download_model(self, quality: str = "standard") -> None:
        """Download the speech model for *quality* on a background thread."""
        quality = quality if quality in QUALITY_LABELS else "standard"
        if quality == "best" and not self._whisper_engine():
            self.window.append_log("The Careful speech model is not available in this build of Quill.", "error")
            return
        spec = SPECS.get(quality)
        self._downloading = quality
        self._model_busy = True
        self._model_note = "Downloading…"
        self._show_model_state()
        size = spec.size_mb if spec is not None else WHISPER_SIZE_MB
        self.window.append_log(f"Downloading the {QUALITY_LABELS[quality]} speech model (about {size} MB)")

        def work() -> None:
            try:
                if quality == "best":
                    path = self._whisper_downloader(user_model_dir(), self.relay.progress.emit)
                elif quality == "standard":
                    path = self._model_downloader(user_model_dir(), self.relay.progress.emit)
                else:
                    path = self._model_downloader(user_model_dir(), self.relay.progress.emit, spec)
            except Exception as exc:   # network, disk, bad archive
                self.relay.error.emit(f"Model download failed: {exc}")
                self.relay.model_ready.emit(None)
                return
            self.relay.model_ready.emit(path)

        threading.Thread(target=work, name="quill-model-download", daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self._model_note = f"Downloading… {100 * done // total}%"
            self._show_model_state()

    def _on_model_ready(self, path) -> None:
        self._model_busy = False
        if path is None:
            self.window.append_log("Model download failed. Check your connection and try again.", "error")
            self._model_note = ""
            self._show_model_state()
            return
        self._model_note = ""
        self._show_model_state()
        self.sync_model_panel()
        self.window.append_log(f"{QUALITY_LABELS[self._downloading]} speech model installed")
        if self._downloading != str(self.settings.preferences["speech_quality"]):
            self.settings.preferences["speech_quality"] = self._downloading        # the model just installed is the one wanted
            self.settings.save()
            self._show_model_state()
        self._reload_listener()                               # listen with what was just downloaded

    def model_installed(self) -> bool:
        """Whether a speech model can be found (for the Settings page)."""
        return self.quality_installed("standard")

    def sync_model_panel(self) -> None:
        """Show, in the Turn Options drop-down, which models there are, which are installed and which is in use."""
        panel = getattr(self.window, "panel", None)
        if panel is not None:
            panel.set_speech_models([(key, QUALITY_LABELS[key], self.quality_installed(key)) for key in QUALITY_LABELS],
                                    str(self.settings.preferences["speech_quality"]))

    def choose_speech_model(self, quality: str) -> None:
        """The Turn Options drop-down picked a model: use it at once (the listener is swapped, nothing else is touched), or,
        for one that is not installed, open Settings > Speech Model so the user can read about it and install it."""
        if quality not in QUALITY_LABELS:
            return
        if not self.quality_installed(quality):
            self.sync_model_panel()                                       # (back to the model in use)
            self.open_settings("Speech Model")
            return
        if quality == str(self.settings.preferences["speech_quality"]):
            return
        self.settings.preferences["speech_quality"] = quality
        self.settings.save()
        self.apply_settings(quiet=True)
        if self._settings_dialog is not None:
            self._settings_dialog.show_chosen_model(quality)

    def _show_model_state(self) -> None:
        """Tell the open Settings window how the speech model download is going (nothing to do when it is closed)."""
        if self._settings_dialog is not None:
            self._settings_dialog.set_model_state(self._model_note, self._model_busy)
