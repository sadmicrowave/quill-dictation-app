"""Application wiring: connects the bridge, listener, controller and UI.

:class:`QuillApp` is the only place that knows about all the pieces. It turns
Session events into window/tray updates and carries user actions (tray click,
settings, workbook picker) back to the controller.

Threading: the Vosk listener and the model download run on background
threads. They talk to the GUI only through :class:`Relay` signals, which Qt
delivers on the GUI thread, so no widget is touched off-thread.
"""

from __future__ import annotations
import pathlib
import threading
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from quill.bridge.base import BridgeError, WorkbookBridge
from quill.config.settings import Settings
from quill.controller import NO_WORKBOOK_HELP, Controller
from quill.feedback import Feedback
from quill.listener.listener import Listener
from quill.listener.model import download_model, ensure_model, user_model_dir
from quill.session import Decision, Event, TermKey
from quill.speaker.speaker import Speaker
from quill.ui.main_window import MainWindow
from quill.ui.player import SoundPlayer
from quill.ui.settings_dialog import SettingsDialog
from quill.ui.sorting_window import SortingWindow
from quill.ui.chrome import apply_chrome
from quill.ui.theme import apply_opacity, apply_spacing, apply_theme, colors_for, is_dark
from quill.ui.tray import TrayIcon


class Relay(QObject):
    """Signals used to hop from background threads onto the GUI thread."""

    transcript = Signal(str)
    error = Signal(str)
    progress = Signal(int, int)
    model_ready = Signal(object)   # pathlib.Path on success, None on failure


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
    ) -> None:
        self.qapp = qapp
        self.settings = settings
        self.relay = Relay()
        self.speaker = speaker or Speaker(enabled=bool(settings.preferences["speak_prompts"]))
        self.controller = Controller(
            bridge, settings, self.speaker,
            on_event=self.handle_event, on_speech=self._on_speech,
        )
        self.window = MainWindow(
            on_toggle=self.toggle_listening, on_settings=self.open_settings,
            on_refresh=self.refresh, on_workbook=self.select_workbook,
            on_download_model=self.download_model, on_sorting=self.show_sorting,
            on_undo=self.undo, on_log_toggled=self._log_toggled,
            log_collapsed=bool(settings.preferences["log_collapsed"]),
            on_row_toggled=self._row_toggled, row_collapsed=bool(settings.preferences["row_collapsed"]),
        )
        self.sorting = SortingWindow(self.controller.vocab, self.resolve_term,
                                     on_voice=self.toggle_voice_sorting,
                                     on_undo=self.undo, batch=self.controller.batch)
        self.tray = TrayIcon(
            qapp, self.window,
            on_start=lambda: self.toggle_listening(True),
            on_stop=lambda: self.toggle_listening(False),
            on_open_workbook=self.show_workbook, on_open_sorting=self.show_sorting,
        )
        self.listener = None
        self.connected = False
        self._listener_factory = listener_factory or self._default_listener
        self._model_finder = model_finder
        self._model_downloader = model_downloader
        self._mic_open = False
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

        self.relay.transcript.connect(self.controller.handle_transcript)
        self.relay.error.connect(self._on_error)
        self.relay.progress.connect(self._on_progress)
        self.relay.model_ready.connect(self._on_model_ready)
        qapp.styleHints().colorSchemeChanged.connect(self._system_scheme_changed)

    # ------------------------------------------------------------------ #
    # Startup                                                              #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """Build the UI, connect to the workbook, and start listening for speech."""
        self._apply_look()
        self.window.setup()
        self.sorting.setup()
        self._apply_look()          # again: the windows now exist, so their layouts get the spacing
        self.tray.setup()
        self.window.show()
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
            self.window.set_footer(NO_WORKBOOK_HELP)
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
        self.tray.set_workbook(bridge.workbook_name, bridge.workbook_path)
        self.settings.preferences["last_workbook"] = bridge.workbook_name
        self.settings.save()

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
                return
            closed = bridge.workbook_name
            self.controller.detach()
            self.connected = False
            self._set_listening(False)
            self.tray.set_workbook("", "")
            self.window.update_workbooks([])
            self.window.append_log(f"'{closed}' was closed.")
            self.window.set_footer(NO_WORKBOOK_HELP)
        if names and not self.connected:
            preferred = str(self.settings.preferences["last_workbook"])
            self.connect_workbook(preferred if preferred in names else None, quiet=True)
            if self.connected:
                self.window.append_log(f"Attached to {bridge.workbook_name} automatically.")

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
            self.window.append_log("Microphone on")
        elif not want and self._mic_open:
            self.listener.stop()
            self._mic_open = False
            self.window.append_log("Microphone off")

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
        self.refresh_sorting(reveal=True)

    def select_workbook(self, name: str) -> None:
        self.connect_workbook(name)

    def open_settings(self) -> None:
        """Show the settings dialog; apply the result if saved."""
        dialog = SettingsDialog(self.settings, self.window.widget, on_preview=self.preview_feedback,
                                on_change=lambda: self.apply_settings(quiet=True))
        if dialog.exec():
            self.apply_settings()

    def _row_toggled(self, collapsed: bool) -> None:
        """Remember whether the user collapsed the Current row section."""
        self.settings.preferences["row_collapsed"] = collapsed
        self.settings.save()

    def _system_scheme_changed(self, *_args) -> None:
        """The operating system switched between light and dark: follow it when set to Auto."""
        if str(self.settings.preferences["theme"]) == "auto":
            self._apply_look()

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
                apply_spacing(window, str(prefs["spacing"]))
                apply_chrome(window, dark, colors, opacity=opacity, blur=blur)
                apply_opacity(root, opacity)
        self.window.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
        self.tray.set_badge(self.tray.badge, colors["accent"])

    def apply_settings(self, quiet: bool = False) -> None:
        """Push changed settings into the running app (*quiet*: a live preview, nothing logged)."""
        self._apply_look()
        self.speaker.enabled = bool(self.settings.preferences["speak_prompts"])
        self.controller.apply_settings()
        self._sync_mic()
        self.controller.lead_in_s = self.feedback.lead_in_s()
        self.refresh_sorting()
        if not quiet:
            self.window.append_log("Settings saved")

    # ------------------------------------------------------------------ #
    # Events from the controller                                           #
    # ------------------------------------------------------------------ #

    def handle_event(self, event: Event) -> None:
        """Reflect a Session/Controller event in the window and tray."""
        self._handle_event(event)
        self._sync_mic()

    def _handle_event(self, event: Event) -> None:
        kind = event.kind
        self.feedback.request(event)
        if not self._cue_timer.isActive():
            self._cue_timer.start()
        if kind == "started":
            self._set_listening(True)
        elif kind == "stopped":
            self._set_listening(False)
        elif kind == "error" and event.detail == NO_WORKBOOK_HELP:
            self.window.set_footer(NO_WORKBOOK_HELP)
            self.tray.notify(NO_WORKBOOK_HELP)
        elif kind == "committed":
            self.window.set_last_saved(event.detail or "Row saved", event.record)
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
            self.window.append_log(f"Voice sort: {event.detail}")
            self.refresh_sorting()
            return
        elif kind == "undone":
            self.window.append_log(event.detail)
            self.refresh_sorting(reveal=True)
            return
        elif kind in ("add_values", "alias_added", "skipped"):
            self.window.append_log(event.detail)
            self.refresh_sorting()
            return
        self.window.update_current_row(self.controller.session.record)
        if kind == "updated" and not event.detail:
            return
        self.window.append_log(self._describe(event))
        if self.controller.bridge is not None and self.connected:
            self.window.update_sheet(self._safe_sheet())

    @staticmethod
    def _describe(event: Event) -> str:
        labels = {
            "started": "Listening started", "stopped": "Listening stopped",
            "committed": "Saved row", "discarded": "Row discarded",
            "updated": "Heard", "confirm": "Question", "error": "Error",
            "searched": "Search", "cleared": "Search cleared", "unsure": "Unsure",
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

    # ------------------------------------------------------------------ #
    # Background-thread results                                            #
    # ------------------------------------------------------------------ #

    def _on_error(self, message: str) -> None:
        self.window.append_log(message)
        self.window.set_footer(message)

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
