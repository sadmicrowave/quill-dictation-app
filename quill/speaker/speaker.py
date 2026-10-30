"""Text-to-speech: speaks prompts aloud and prints them to the console.

On macOS: uses the ``say`` subprocess command (built in to macOS).
On Windows: uses pyttsx3 (SAPI voice).

The mic should be drained after the speaker finishes so Quill does not
transcribe its own voice: pass ``on_done=listener.drain`` to :meth:`say`.
"""

from __future__ import annotations
import subprocess
import sys
import threading
from typing import Callable

DoneCallback = Callable[[], None]


class Speaker:
    """Speaks text aloud on the platform's TTS engine.

    Args:
        enabled: If False, only prints — useful for testing or when running
            with spoken prompts turned off.
        platform: Override ``sys.platform`` (tests).
        run_in_thread: Speak on a daemon thread (default). Tests pass False to
            run synchronously.
    """

    def __init__(
        self,
        enabled: bool = True,
        platform: str | None = None,
        run_in_thread: bool = True,
    ) -> None:
        self.enabled = enabled
        self._platform = platform or sys.platform
        self._threaded = run_in_thread

    def say(self, text: str, on_done: DoneCallback | None = None) -> None:
        """Print and optionally speak *text*. Non-blocking by default.

        Args:
            text: What to say.
            on_done: Called after speech ends (also when speech is disabled
                or fails), on the speaking thread.
        """
        print(f"  Quill: {text}")
        if not self.enabled:
            if on_done:
                on_done()
            return
        job = self._job(text, on_done)
        if self._threaded:
            threading.Thread(target=job, name="quill-speaker", daemon=True).start()
        else:
            job()

    # ------------------------------------------------------------------ #
    # Platform implementations                                             #
    # ------------------------------------------------------------------ #

    def _job(self, text: str, on_done: DoneCallback | None) -> Callable[[], None]:
        def run() -> None:
            try:
                if self._platform == "darwin":
                    self._say_mac(text)
                elif self._platform == "win32":
                    self._say_win(text)
            finally:
                if on_done:
                    on_done()
        return run

    def _say_mac(self, text: str) -> None:
        try:
            subprocess.run(["say", text], check=False, timeout=30)
        except Exception:
            pass   # TTS is a nicety; the prompt is also printed and logged

    def _say_win(self, text: str) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()   # one engine per utterance: SAPI engines are thread-bound
            engine.say(text)
            engine.runAndWait()
        except Exception:
            pass
