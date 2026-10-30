"""Text-to-speech: speaks prompts aloud and prints them to the console.

On macOS: uses the 'say' subprocess command (built in to macOS).
On Windows: uses pyttsx3 (SAPI voice).

The mic should be drained / recogniser recreated after the speaker
finishes so Quill does not transcribe its own voice.
"""

from __future__ import annotations
import subprocess
import sys
import threading


class Speaker:
    """Speaks text aloud on the platform's TTS engine.

    Args:
        enabled: If False, only prints — useful for testing or when
                 running headless / in text mode.
    """

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._engine = None   # pyttsx3 engine; lazy-initialised on Windows

    def say(self, text: str) -> None:
        """Print and optionally speak *text*. Non-blocking."""
        print(f"  Quill: {text}")
        if not self.enabled:
            return
        if sys.platform == "darwin":
            threading.Thread(target=self._say_mac, args=(text,), daemon=True).start()
        elif sys.platform == "win32":
            threading.Thread(target=self._say_win, args=(text,), daemon=True).start()

    # ------------------------------------------------------------------ #
    # Platform implementations                                             #
    # ------------------------------------------------------------------ #

    def _say_mac(self, text: str) -> None:
        try:
            subprocess.run(["say", text], check=False, timeout=30)
        except Exception:
            pass

    def _say_win(self, text: str) -> None:
        try:
            import pyttsx3
            if self._engine is None:
                self._engine = pyttsx3.init()
            self._engine.say(text)
            self._engine.runAndWait()
        except Exception:
            pass
