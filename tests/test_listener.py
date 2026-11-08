"""Listener loop tests with a fake recogniser and fake audio stream."""
import contextlib
import json
import pathlib
import threading
import time
import unittest

from quill.listener.listener import Listener


class FakeRecognizer:
    """Treats every chunk b'<word>' as a finished phrase; b'.' is partial."""

    created = 0

    def __init__(self, model, rate):
        FakeRecognizer.created += 1
        self._last = b""

    def AcceptWaveform(self, chunk):
        self._last = chunk
        return chunk != b"."

    def Result(self):
        return json.dumps({"text": self._last.decode()})


def wait_for(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ListenerCase(unittest.TestCase):
    def setUp(self):
        FakeRecognizer.created = 0
        self.heard, self.errors = [], []
        self.push = None
        self.stream_opened = threading.Event()
        self.stream_closed = threading.Event()

        @contextlib.contextmanager
        def stream(rate, push):
            self.push = push
            self.stream_opened.set()
            try:
                yield
            finally:
                self.stream_closed.set()

        self.listener = Listener(
            pathlib.Path("model"), self.heard.append, on_error=self.errors.append,
            model_loader=lambda path: "model", recognizer_factory=FakeRecognizer,
            stream_factory=stream,
        )

    def tearDown(self):
        self.listener.stop()

    def start(self):
        self.listener.start()
        self.assertTrue(self.stream_opened.wait(2))


class TestListener(ListenerCase):
    def test_emits_final_phrases(self):
        self.start()
        self.push(b"hello")
        self.push(b"world")
        self.assertTrue(wait_for(lambda: self.heard == ["hello", "world"]))

    def test_partial_results_not_emitted(self):
        self.start()
        self.push(b".")
        self.push(b"done")
        self.assertTrue(wait_for(lambda: self.heard == ["done"]))

    def test_blank_and_bad_results_ignored(self):
        self.listener._emit(json.dumps({"text": "   "}))
        self.listener._emit("not json")
        self.listener._emit("[]")
        self.assertEqual(self.heard, [])

    def test_stop_closes_stream_and_thread(self):
        self.start()
        self.assertTrue(self.listener.running)
        self.listener.stop()
        self.assertTrue(self.stream_closed.wait(2))
        self.assertFalse(self.listener.running)

    def test_start_twice_opens_one_stream(self):
        self.start()
        self.listener.start()
        self.assertEqual(FakeRecognizer.created, 1)

    def test_restart_after_stop(self):
        self.start()
        self.listener.stop()
        self.stream_opened.clear()
        self.start()
        self.push(b"again")
        self.assertTrue(wait_for(lambda: self.heard == ["again"]))

    def test_drain_discards_queued_audio_and_recreates_recogniser(self):
        # Queue audio while the loop is parked on the drain flag's clear step.
        self.start()
        self.assertTrue(wait_for(lambda: FakeRecognizer.created == 1))
        self.listener._drain.set()
        self.push(b"stale")   # may race the drain; either way it must not survive a later drain
        self.listener.drain()
        self.assertTrue(wait_for(lambda: FakeRecognizer.created >= 2))
        self.heard.clear()
        self.push(b"fresh")
        self.assertTrue(wait_for(lambda: "fresh" in self.heard))


class TestMute(ListenerCase):
    def test_audio_while_muted_is_dropped(self):
        self.start()
        self.listener.mute()
        self.push(b"own voice")
        time.sleep(0.3)
        self.assertEqual(self.heard, [])
        self.listener.unmute()
        self.assertTrue(wait_for(lambda: FakeRecognizer.created >= 2))   # drained + recreated
        self.push(b"user")
        self.assertTrue(wait_for(lambda: self.heard == ["user"]))


class TestListenerErrors(unittest.TestCase):
    def test_model_failure_reports_and_stops(self):
        errors = []

        def bad_loader(path):
            raise FileNotFoundError("no model here")

        listener = Listener(pathlib.Path("x"), lambda t: None, on_error=errors.append,
                            model_loader=bad_loader)
        listener.start()
        self.assertTrue(wait_for(lambda: errors))
        self.assertIn("no model here", errors[0])
        self.assertTrue(wait_for(lambda: not listener.running))

    def test_microphone_failure_reports(self):
        errors = []

        def bad_stream(rate, push):
            raise OSError("no microphone")

        listener = Listener(pathlib.Path("x"), lambda t: None, on_error=errors.append,
                            model_loader=lambda p: "m", recognizer_factory=FakeRecognizer,
                            stream_factory=bad_stream)
        listener.start()
        self.assertTrue(wait_for(lambda: errors))
        self.assertIn("no microphone", errors[0])


if __name__ == "__main__":
    unittest.main()


class TestGrammar(unittest.TestCase):
    """The recogniser can be limited to the words an answer is made of."""

    def make(self, factory):
        made = []

        @contextlib.contextmanager
        def stream(rate, push):
            made.append(push)
            yield

        heard = []
        listener = Listener(pathlib.Path("m"), heard.append, model_loader=lambda p: "m", recognizer_factory=factory, stream_factory=stream)
        return listener, heard, made

    def test_a_grammar_is_given_to_the_recogniser_and_taken_away_again(self):
        grammars = []

        class Rec:
            def __init__(self, model, rate, grammar=None):
                grammars.append(grammar)
            def AcceptWaveform(self, chunk): return False
            def PartialResult(self): return json.dumps({"partial": ""})

        listener, heard, made = self.make(Rec)
        listener.set_grammar(["Yes", "ignore", "yes"])
        listener.start()
        self.assertTrue(wait_for(lambda: made))
        self.assertEqual(json.loads(grammars[0]), ["yes", "ignore", "[unk]"])              # lower case, no repeats, and [unk] for the rest
        listener.set_grammar(None)
        made[0](b"x" * 3200)                                                            # audio makes the capture thread apply it
        self.assertTrue(wait_for(lambda: grammars[-1] is None))
        listener.stop()

    def test_a_recogniser_that_takes_no_grammar_still_works(self):
        listener, heard, made = self.make(FakeRecognizer)
        listener.set_grammar(["yes"])
        listener.start()
        self.assertTrue(wait_for(lambda: made))
        made[0](b"hello")
        self.assertTrue(wait_for(lambda: heard))
        listener.stop()

    def test_unknown_sounds_are_not_words(self):
        self.assertEqual(Listener._clean({"text": "[unk] yes [unk]"}), "yes")
        self.assertEqual(Listener._clean({"text": "[unk]"}), "")
        self.assertEqual(Listener._clean({"text": "[unk] yes", "result": [{"word": "[unk]", "conf": 0.9}, {"word": "yes", "conf": 0.95}]}), "yes")
