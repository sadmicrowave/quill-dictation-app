"""Text-to-speech: speaks prompts aloud and prints them to the console.

On macOS: uses the ``say`` subprocess command (built in to macOS).
On Windows: uses pyttsx3 (SAPI voice).

The mic should be drained after the speaker finishes so Quill does not
transcribe its own voice: pass ``on_done=listener.drain`` to :meth:`say`.
"""

from __future__ import annotations
import logging
import subprocess
import sys
import threading
import time
from typing import Callable
from quill import platforms

log = logging.getLogger("quill.speaker")

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

    def say(self, text: str, on_done: DoneCallback | None = None, lead_in: float = 0.0) -> None:
        """Print and optionally speak *text*. Non-blocking by default.

        Args:
            text: What to say.
            on_done: Called after speech ends (also when speech is disabled
                or fails), on the speaking thread.
            lead_in: Seconds to wait first (a sound cue is playing).
        """
        log.info("says: %s", text)
        if sys.stdout is not None and sys.stdout.isatty():     # a developer's terminal also sees it
            print(f"  Quill: {text}")
        if not self.enabled:
            if on_done:
                on_done()
            return
        job = self._job(text, on_done, lead_in)
        if self._threaded:
            threading.Thread(target=job, name="quill-speaker", daemon=True).start()
        else:
            job()

    # ------------------------------------------------------------------ #
    # Platform implementations                                             #
    # ------------------------------------------------------------------ #

    def _job(self, text: str, on_done: DoneCallback | None,
             lead_in: float = 0.0) -> Callable[[], None]:
        def run() -> None:
            try:
                if lead_in > 0:
                    time.sleep(lead_in)
                speak = platforms.offered(self._platform, "speak")
                if speak is not None:
                    speak(text)
            finally:
                if on_done:
                    on_done()
        return run
