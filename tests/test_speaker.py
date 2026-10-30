"""Speaker tests: platform dispatch and the drain hook, without real TTS."""
import unittest
from unittest import mock

from quill.speaker.speaker import Speaker


class TestSpeaker(unittest.TestCase):
    def test_disabled_prints_and_calls_done(self):
        done = []
        with mock.patch("subprocess.run") as run:
            Speaker(enabled=False, run_in_thread=False).say("hi", on_done=lambda: done.append(1))
        run.assert_not_called()
        self.assertEqual(done, [1])

    def test_mac_uses_say_command(self):
        with mock.patch("subprocess.run") as run:
            Speaker(platform="darwin", run_in_thread=False).say("hello there")
        self.assertEqual(run.call_args[0][0], ["say", "hello there"])

    def test_done_called_after_speech(self):
        order = []
        with mock.patch("subprocess.run", side_effect=lambda *a, **k: order.append("spoke")):
            Speaker(platform="darwin", run_in_thread=False).say("x", on_done=lambda: order.append("done"))
        self.assertEqual(order, ["spoke", "done"])

    def test_done_called_even_when_tts_fails(self):
        done = []
        with mock.patch("subprocess.run", side_effect=OSError("no say")):
            Speaker(platform="darwin", run_in_thread=False).say("x", on_done=lambda: done.append(1))
        self.assertEqual(done, [1])

    def test_windows_uses_pyttsx3(self):
        engine = mock.Mock()
        fake = mock.Mock(init=mock.Mock(return_value=engine))
        with mock.patch.dict("sys.modules", {"pyttsx3": fake}):
            Speaker(platform="win32", run_in_thread=False).say("hello")
        engine.say.assert_called_once_with("hello")
        engine.runAndWait.assert_called_once()

    def test_windows_without_pyttsx3_does_not_raise(self):
        with mock.patch.dict("sys.modules", {"pyttsx3": None}):
            Speaker(platform="win32", run_in_thread=False).say("hello")

    def test_other_platform_is_silent(self):
        with mock.patch("subprocess.run") as run:
            Speaker(platform="linux", run_in_thread=False).say("hello")
        run.assert_not_called()

    def test_threaded_by_default(self):
        done = []
        import threading
        ev = threading.Event()
        with mock.patch("subprocess.run"):
            Speaker(platform="darwin").say("x", on_done=ev.set)
            self.assertTrue(ev.wait(2))


if __name__ == "__main__":
    unittest.main()
