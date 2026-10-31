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
import os
import pathlib
import threading
from typing import Callable

import shiboken6
from PySide6.QtCore import QObject, Qt, QTimer, Signal

from quill.assets import app_icon
from quill.bridge.base import BridgeError, WorkbookBridge
from quill.bridge.factory import get_bridge
from quill.bridge.hosts import HostApp, SpreadsheetHosts
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.controller import NO_WORKBOOK_HELP, Controller
from quill.feedback import Feedback
from quill.listener.listener import Listener
from quill.listener.model import download_model, ensure_model, user_model_dir
from quill.session import Decision, Event, TermKey
from quill.speaker.speaker import Speaker
from quill.stream import match_words
from quill.ui.chrome import (
    SYMBOL_HELP,
    SYMBOL_SETTINGS,
    SYMBOL_UNDO,
    add_titlebar_button,
    apply_chrome,
    set_dock_icon_visible,
)
from quill.ui.help_window import HelpWindow
from quill.ui.main_window import MainWindow
from quill.ui.player import SoundPlayer
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.sorting_window import SortingWindow
from quill.ui.theme import (
    apply_opacity,
    apply_spacing,
    apply_theme,
    colors_for,
    is_dark,
)
from quill.ui.tray import TrayIcon


class Relay(QObject):
    """Signals used to hop from background threads onto the GUI thread."""

    transcript = Signal(str)
    partial = Signal(str)           # words of the phrase still being spoken
    error = Signal(str)
    progress = Signal(int, int)
    model_ready = Signal(object)   # pathlib.Path on success, None on failure
    background_done = Signal(object, object)   # (callback, result) of a task that ran off the GUI thread


log = logging.getLogger("quill.app")

#: How long after the last write the program showing the file is asked to reload it, and how many
#: watcher ticks pass between looks for a file open in another spreadsheet program.
HOST_RELOAD_MS = 1500
HOST_PROBE_EVERY = 3


class QuillApp:
    """Owns every component and runs the app.

    Args:
        qapp: The QApplication.
        settings: Loaded settings.
        bridge: Workbook bridge (live Excel, or a file bridge).
        listener_factory: ``(model_path, on_transcript, on_error) -> listener``;
            tests inject a fake so no microphone is needed.
        model_finder: ``(configured_path) -> Path | None``.
        model_downloader: ``(dest_dir, progress) -> Path``; tests inject a fake.
        speaker: Speaker to use (default: platform TTS honouring settings).
        poll_interval_ms: How often to look for workbooks being opened/closed.
    """

    #: Default polling period of the workbook watcher.
    POLL_INTERVAL_MS = 3000

    def __init__(
        self,
        qapp,
        settings: Settings,
        bridge: WorkbookBridge,
        listener_factory: Callable | None = None,
        model_finder: Callable[[str], pathlib.Path | None] = ensure_model,
        model_downloader: Callable = download_model,
        speaker: Speaker | None = None,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        sound_player: Callable | None = None,
        echo_speaker=None,
        file_chooser: Callable[[], str | None] | None = None,
        live_bridge_factory: Callable[[], WorkbookBridge] = get_bridge,
        hosts: SpreadsheetHosts | None = None,
    ) -> None:
        self.qapp = qapp
        self._file_chooser = file_chooser or self._ask_for_file
        self._live_bridge_factory = live_bridge_factory
        self.hosts = hosts or SpreadsheetHosts()      # finds Numbers / LibreOffice ... and refreshes them after a save
        self._host: HostApp | None = None            # the program showing the file Quill is writing to
        self._probe_ticks = 0
        self._host_probe_running = False             # a look for files in other programs is under way
        self._host_noted = False
        self._host_reload = QTimer()
        self._host_reload.setSingleShot(True)
        self._host_reload.setInterval(HOST_RELOAD_MS)
        self._host_reload.timeout.connect(self._reload_host)
        self._quiet_timer = QTimer()                  # stops listening after a spell of silence (see "auto_stop")
        self._quiet_timer.setSingleShot(True)
        self._quiet_timer.timeout.connect(self._quiet_for_too_long)
        qapp.setWindowIcon(app_icon())               # the Dock / taskbar / window icon
        self.settings = settings
        self.relay = Relay()
        self.speaker = speaker or Speaker(enabled=bool(settings.preferences["speak_prompts"]))
        self.controller = Controller(
            bridge, settings, self.speaker,
            on_event=self.handle_event, on_speech=self._on_speech,
        )
        self.window = MainWindow(
            on_toggle=self.toggle_listening, on_settings=self.open_settings,
            on_workbook=self.select_workbook, on_open_file=self.choose_spreadsheet_file,
            on_use_excel=self.use_live_excel,
            on_download_model=self.download_model, on_sorting=self.show_sorting,
            on_undo=self.undo, on_help=self.open_help, on_log_toggled=self._log_toggled,
            on_resized=self._window_resized, on_mini_resized=self._mini_window_resized,
            on_field_removed=self.remove_field,
            log_collapsed=bool(settings.preferences["log_collapsed"]),
            on_mini_toggled=self._mini_toggled, mini=bool(settings.preferences["mini_mode"]),
            mini_on_top=bool(settings.preferences["mini_on_top"]),
        )
        self.sorting = SortingWindow(self.controller.vocab, self.resolve_term,
                                     on_voice=self.toggle_voice_sorting,
                                     on_undo=self.undo, batch=self.controller.batch, on_help=self.open_help)
        self.tray = TrayIcon(
            qapp, self.window,
            on_start=lambda: self.toggle_listening(True),
            on_stop=lambda: self.toggle_listening(False),
            on_open_workbook=self.show_workbook, on_open_sorting=self.show_sorting,
            on_open_file=self.choose_spreadsheet_file,
        )
        self.listener = None
        self.connected = False
        self._listener_factory = listener_factory or self._default_listener
        self._model_finder = model_finder
        self._model_downloader = model_downloader
        self._mic_open = False
        self._seen_mtime: int | None = None      # last known state of the workbook file
        self._titlebar = None                    # the resize icon in the title bar, where supported
        self._titlebar_left = None               # Help and Undo, beside the close / zoom buttons
        self.help: HelpWindow | None = None      # created the first time a ? icon is pressed
        self._expiry = QTimer()
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self.controller.expire_prompt)
        self.echo_speaker = echo_speaker or Speaker(enabled=True)
        self.feedback = Feedback(settings, sound_player or SoundPlayer(), self._speak_word,
                                 busy=self._mute_for)
        self.controller.lead_in_s = self.feedback.lead_in_s()
        self._cue_timer = QTimer()          # lets one breath's events settle into a single cue
        self._cue_timer.setSingleShot(True)
        self._cue_timer.setInterval(60)
        self._cue_timer.timeout.connect(self.feedback.flush)
        self._watcher = QTimer()
        self._watcher.setInterval(poll_interval_ms)
        self._watcher.timeout.connect(self.poll_workbooks)

        self.relay.transcript.connect(self._on_phrase_heard)        # first: show the words before they are acted on
        self.relay.partial.connect(self._on_partial_heard)
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
        self.sorting.setup(parent=self.window.widget)
        self.sorting.install_titlebar()
        self._apply_look()          # again: the windows now exist, so their layouts get the spacing
        self.tray.setup()
        self.window.set_stream_classifier(self._match_heard_words)
        self.window.restore_mini_size(int(self.settings.preferences["mini_width"]),
                                      int(self.settings.preferences["mini_height"]))
        self.window.restore_size(int(self.settings.preferences["window_width"]),
                                 int(self.settings.preferences["window_height"]))
        self.window.show()
        self.qapp.aboutToQuit.connect(self.window.report_size)      # a size changed just before quitting counts
        self.qapp.aboutToQuit.connect(self.shutdown)
        self._apply_dock()
        self._install_titlebar_button()
        self.window.set_file_mode(isinstance(self.controller.bridge, XlsxBridge))
        self.connect_workbook(str(self.settings.preferences["last_workbook"]) or None)
        self._start_listener()
        self._watcher.start()

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
                self.window.append_log(f"Not connected: {exc}")
            self.window.set_not_connected(True)
            return
        self.connected = True
        self.window.update_workbooks(names, bridge.workbook_name)
        self.window.update_sheet(bridge.active_sheet_name())
        count = sum(len(v) for v in bridge.get_lists().values())
        self.window.append_log(
            f"Connected to {bridge.workbook_name}: {len(bridge.get_lists())} lists, {count} values"
        )
        warning = getattr(bridge, "discovery_warning", None)
        if warning:
            self.window.append_log(warning)
        self.window.set_footer("")
        self.window.set_not_connected(False)
        self.tray.set_workbook(bridge.workbook_name, bridge.workbook_path)
        self.settings.preferences["last_workbook"] = bridge.workbook_name
        self.settings.save()
        self._remember_mtime()

    def poll_workbooks(self) -> None:
        """Watcher tick: attach when a workbook appears, detach when it closes.

        This is what makes "just open a spreadsheet and start talking" work:
        Quill need not be told which workbook; it notices.
        """
        bridge = self.controller.bridge
        try:
            names = bridge.open_workbooks()
        except BridgeError:
            names = []   # Excel not running
        if self.connected:
            if bridge.workbook_name in names:
                self._check_workbook_changes()
                return
            closed = bridge.workbook_name
            self.controller.detach()
            self.connected = False
            self._set_listening(False)
            self.tray.set_workbook("", "")
            self.window.update_workbooks([])
            self.window.append_log(f"'{closed}' was closed.")
            self.window.set_not_connected(True)
        if not names and not self.connected:
            self._attach_host_file()
            if self.connected:
                return
        if names and not self.connected:
            preferred = str(self.settings.preferences["last_workbook"])
            self.connect_workbook(preferred if preferred in names else None, quiet=True)
            if self.connected:
                self.window.append_log(f"Attached to {bridge.workbook_name} automatically.")

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

    def _attach_host_file(self) -> None:
        """No Excel workbook is open: if another spreadsheet program has an Excel file open, work on that file.

        Looks every few ticks only, never while a previous look is still running, and never when the user
        chose a program in the settings or is already working on a file.
        """
        if isinstance(self.controller.bridge, XlsxBridge) or self._host_probe_running or \
                str(self.settings.preferences["spreadsheet_app"]) not in ("auto", ""):
            return
        self._probe_ticks += 1
        if self._probe_ticks % HOST_PROBE_EVERY != 1:
            return
        self._host_probe_running = True
        self.run_in_background(self.hosts.open_excel_files, self._open_host_file)

    def _open_host_file(self, found) -> None:
        """A look for files open in other spreadsheet programs finished: work on the first one found."""
        self._host_probe_running = False
        if not found or self.connected or isinstance(self.controller.bridge, XlsxBridge):
            return
        for host_app, path in found:
            if self.open_workbook_file(path, remember=False):
                self._host = host_app
                log.info("working on %s, open in %s", path.name, host_app.name)
                self.window.append_log(f"Found {path.name} open in {host_app.name}: working on it directly.")
                return

    def _reload_host(self) -> None:
        """Ask the program showing the file to load what Quill just saved (or say what to do by hand)."""
        bridge = self.controller.bridge
        if not isinstance(bridge, XlsxBridge) or not bridge.workbook_path:
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
            self.window.append_log(f"Couldn't refresh {host_app.name}. {host_app.note}")

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
        self.window.update_sheet(self._safe_sheet())
        self.window.append_log("Workbook changed: lists and columns re-read")

    def show_workbook(self) -> None:
        """Bring the workbook being dictated into to the front (tray click)."""
        try:
            self.controller.bridge.activate()
        except BridgeError as exc:
            self.window.append_log(str(exc))

    def _start_listener(self) -> None:
        model = self._model_finder(str(self.settings.preferences["model_path"]))
        if model is None:
            self.window.set_footer(
                "No speech model found. Download one (about 40 MB) to start dictating.",
                offer_download=True,
            )
            return
        self.listener = self._listener_factory(model, self.relay.transcript.emit, self.relay.error.emit)
        set_partial = getattr(self.listener, "set_partial_callback", None)
        if set_partial is not None:
            set_partial(self.relay.partial.emit)                      # words appear in the Voice Stream as they are heard
        preload = getattr(self.listener, "preload", None)
        if preload is not None:
            preload()                                   # load the model now; the mic stays off
        self._mic_open = False
        self._sync_mic()
        if not self._mic_open:
            self.window.append_log("Speech model ready. The microphone is off until you press Start.")

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

    def toggle_listening(self, active: bool) -> None:
        """Open or close the listening gate (button, tray, or menu)."""
        if active and not self.connected:
            self.connect_workbook(str(self.settings.preferences["last_workbook"]) or None,
                                  quiet=True)
        self.controller.set_listening(active)   # explains what to do if there is no workbook

    def refresh(self) -> None:
        """Re-read the workbook (or connect, if not yet connected)."""
        if not self.connected:
            self.connect_workbook()
            return
        try:
            self.controller.refresh()
        except BridgeError as exc:
            self.connected = False
            self.window.append_log(f"Lost the workbook: {exc}")
            return
        self.window.update_workbooks(self.controller.bridge.open_workbooks(),
                                     self.controller.bridge.workbook_name)
        self.window.update_sheet(self.controller.bridge.active_sheet_name())
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

    def _ask_for_file(self) -> str | None:
        """Show the standard file picker for an .xlsx workbook; None if the user cancels."""
        from PySide6.QtWidgets import QFileDialog
        remembered = str(self.settings.preferences["workbook_file"])
        start = str(pathlib.Path(remembered).parent) if remembered else str(pathlib.Path.home() / "Documents")
        path, _ = QFileDialog.getOpenFileName(self.window.widget, "Open Spreadsheet File", start,
                                              "Excel Workbooks (*.xlsx)")
        return path or None

    def choose_spreadsheet_file(self) -> None:
        """File > Open Spreadsheet File…: pick an .xlsx and work on it directly (no Excel needed)."""
        path = self._file_chooser()
        if path:
            self.open_workbook_file(path)

    def open_workbook_file(self, path: str | pathlib.Path, remember: bool = True) -> bool:
        """Switch to working on the .xlsx at *path* through the file bridge.

        The file is edited in place and saved after every change, so close it in other
        programs while dictating (or reopen it afterwards to see the new rows). An old
        macro-enabled .xlsm is not accepted, because saving it this way would drop its macros.

        Returns:
            True if Quill is now working on the file; otherwise the previous workbook is kept.
        """
        path = pathlib.Path(path)
        if path.suffix.lower() != ".xlsx" or not path.is_file():
            self.window.append_log(f"Can't open '{path.name}': choose an Excel workbook (.xlsx).")
            self.window.set_footer(f"Can't open '{path.name}'. Choose an Excel workbook (.xlsx).")
            return False
        previous, was_connected = self.controller.bridge, self.connected
        if was_connected:
            self.controller.detach()                     # closes the listening gate on the old workbook
            self.connected = False
            self._set_listening(False)
        self.controller.bridge = XlsxBridge(path)
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
        self.window.append_log(f"Working directly on the file {path.name} (no Excel needed)")
        return True

    def use_live_excel(self) -> None:
        """Go back to whichever workbook is open in Excel."""
        try:
            bridge = self._live_bridge_factory()
        except NotImplementedError as exc:
            self.window.append_log(str(exc))
            return
        if self.connected:
            self.controller.detach()
            self.connected = False
            self._set_listening(False)
        self.controller.bridge = bridge
        self.settings.preferences["workbook_file"] = ""
        self.settings.save()
        self.window.set_file_mode(False)
        self.window.append_log("Using the workbook open in Excel")
        self.connect_workbook(quiet=True)

    def select_workbook(self, name: str) -> None:
        """The user picked another workbook in the file picker: connect to it."""
        self.connect_workbook(name)

    def open_help(self, topic: str | None = None) -> None:
        """Open the help window on *topic* (a page's slug), creating it on first use."""
        if self.help is None:
            self.help = HelpWindow()
            self.help.setup()
            self.help.restyle(self.settings.preferences, self.qapp)
        self.help.show(topic)

    def open_settings(self) -> None:
        """Show the settings dialog; apply the result if saved."""
        dialog = SettingsDialog(self.settings, self.window.widget, on_preview=self.preview_feedback,
                                on_change=lambda: self.apply_settings(quiet=True))
        if dialog.exec():
            self.apply_settings()

    def _install_titlebar_button(self) -> None:
        """Put the resize icon in the title bar (macOS); the in-window one is then hidden."""
        if self._titlebar is not None or self.window.widget is None:
            return
        self._titlebar = add_titlebar_button(
            self.window.widget, lambda: self.window.set_mini(not self.window.mini, notify=True),
            mini=self.window.mini, extra=[(SYMBOL_SETTINGS, "Settings", self.open_settings)])
        native = self._titlebar is not None
        # Help, then Undo, sit right beside the window's close / minimise / zoom buttons.
        self._titlebar_left = add_titlebar_button(
            self.window.widget, self.undo, symbol=SYMBOL_UNDO, tip="Undo the Last Answer",
            extra=[(SYMBOL_HELP, "Help", lambda: self.open_help("welcome"))], side="left") if native else None
        native = native and self._titlebar_left is not None
        self.window.set_native_help_button(native)
        self.window.set_native_undo_button(native)
        self._sync_titlebar_undo()
        self.window.set_native_mini_button(native)
        self.window.set_native_settings_button(native)        # Settings and resize both live in the title bar

    def _sync_titlebar_undo(self) -> None:
        """Grey out the title bar's Undo icon while there is nothing to take back."""
        if self._titlebar_left is not None:
            self._titlebar_left.set_enabled(len(self.controller.history) > 0)

    def _mini_toggled(self, mini: bool) -> None:
        """Remember the view and keep the tray menu and the title-bar icon in step.

        The window's stay-on-top level is changed in place, so nothing needs restyling. Only
        where that was impossible (the old, window-recreating way) is the look applied again.
        """
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
        """Show or hide the Dock icon to match the setting (macOS; a no-op elsewhere)."""
        set_dock_icon_visible(not bool(self.settings.preferences["hide_dock_icon"]))

    def _app_state_changed(self, state) -> None:
        """Clicking Quill's Dock icon (or opening it from Finder) with no window up brings the window back."""
        if state == Qt.ApplicationState.ApplicationActive and self.window.widget is not None \
                and not self.window.widget.isVisible():
            self.window.show()

    def shutdown(self) -> None:
        """Quitting: close the microphone and stop the timers, so nothing is left running."""
        log.info("shutting down")
        self._watcher.stop()
        self._host_reload.stop()
        self._quiet_timer.stop()
        if self.listener is not None:
            self.listener.stop()
            self._mic_open = False

    def remove_field(self, column: str) -> None:
        """The user deleted a line of the row being built because Quill got it wrong."""
        if self.controller.remove_field(column):
            self.window.append_log(f"Removed {column} from the row")
        self.window.update_current_row(self.controller.session.record)

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
        self.settings.preferences["log_collapsed"] = collapsed
        self.settings.save()

    def _apply_look(self) -> None:
        """Apply theme, accent and spacing from the settings to the app and its windows."""
        prefs = self.settings.preferences
        apply_theme(self.qapp, str(prefs["theme"]), str(prefs["accent"]), str(prefs["spacing"]),
                    int(prefs["font_size"]))
        dark = is_dark(self.qapp)
        colors = colors_for(dark, str(prefs["accent"]))
        opacity, blur = int(prefs["opacity"]), int(prefs["blur"])
        for window, root in ((self.window.widget, self.window.root), (self.sorting.widget, self.sorting.root)):
            if window is not None:
                if window is self.window.widget:
                    self.window.apply_density(str(prefs["spacing"]))
                else:
                    apply_spacing(window, str(prefs["spacing"]))
                apply_chrome(window, dark, colors, opacity=opacity, blur=blur)
                apply_opacity(root, opacity)
        self.window.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
        self.sorting.refresh_icons(colors["text"])
        if self.help is not None:
            self.help.restyle(prefs, self.qapp)
        self.tray.set_dark(dark)
        self.tray.set_badge(self.tray.badge, colors["accent"])

    def apply_settings(self, quiet: bool = False) -> None:
        """Push changed settings into the running app (*quiet*: a live preview, nothing logged)."""
        self._apply_look()
        self.speaker.enabled = bool(self.settings.preferences["speak_prompts"])
        self.controller.apply_settings()
        self.window.set_mini_on_top(bool(self.settings.preferences["mini_on_top"]))
        self._apply_dock()
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
        if event.kind in self._WRITE_EVENTS:
            self._remember_mtime()
            if isinstance(self.controller.bridge, XlsxBridge):
                self._host_reload.start()                 # after a quiet moment, so a burst of rows reloads once
        self._sync_mic()

    def _handle_event(self, event: Event) -> None:
        kind = event.kind
        if kind in ("committed", "discarded", "stopped"):
            self.window.end_stream()                  # the row is over: the next words start a new stream
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
            self.tray.notify(NO_WORKBOOK_HELP)
        elif kind == "committed":
            self.window.set_last_saved(event.detail, event.record)
        elif kind == "confirm":
            self._expiry.start(int(self.settings.preferences["prompt_timeout_s"]) * 1000)
            self.refresh_sorting(reveal=True)
            if self.settings.preferences["auto_voice_sort"] and self.listener is not None:
                self.controller.start_voice_sort()
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
        elif kind == "sorting":
            self.sorting.set_voice_status((event.record or {}).get("heard", ""), event.detail)
            self.window.append_log(f"Voice Sort: {event.detail}")
            self.refresh_sorting()
            return
        elif kind == "undone":
            self.window.append_log(event.detail)
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
        self.window.append_log(self._describe(event))
        if self.controller.bridge is not None and self.connected:
            self.window.update_sheet(self._safe_sheet())

    @staticmethod
    def _describe(event: Event) -> str:
        labels = {
            "started": "Listening Started", "stopped": "Listening Stopped",
            "committed": "Saved Row", "discarded": "Row Discarded",
            "updated": "Heard", "confirm": "Question", "error": "Error",
            "searched": "Search", "cleared": "Search Cleared", "unsure": "Unsure",
            "undone": "Undo",
        }
        label = labels.get(event.kind)
        return f"{label}: {event.detail}".rstrip(": ") if label else event.detail

    def _safe_sheet(self) -> str:
        try:
            return self.controller.bridge.active_sheet_name()
        except BridgeError:
            return "–"

    def _set_listening(self, active: bool) -> None:
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
            return
        if keep_running and self._quiet_timer.isActive():
            return
        self._quiet_timer.start(int(self.settings.preferences["auto_stop_seconds"]) * 1000)

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
        self.echo_speaker.say(word)

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
        self.window.append_log(message)
        self.window.set_footer(message)
        if self.listener is not None and self._mic_open and not getattr(self.listener, "running", True):
            self._mic_open = False
            if self.controller.session.listening:
                self.controller.set_listening(False)

    def download_model(self) -> None:
        """Download the speech model on a background thread."""
        self.window.download_button.setEnabled(False)
        self.window.set_footer("Downloading speech model…")

        def work() -> None:
            try:
                path = self._model_downloader(user_model_dir(), self.relay.progress.emit)
            except Exception as exc:   # network, disk, bad archive
                self.relay.error.emit(f"Model download failed: {exc}")
                self.relay.model_ready.emit(None)
                return
            self.relay.model_ready.emit(path)

        threading.Thread(target=work, name="quill-model-download", daemon=True).start()

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self.window.set_footer(f"Downloading speech model… {100 * done // total}%")

    def _on_model_ready(self, path) -> None:
        if path is None:
            self.window.set_footer("Model download failed. Check your connection and try again.",
                                   offer_download=True)
            return
        self.window.set_footer("")
        self._start_listener()
