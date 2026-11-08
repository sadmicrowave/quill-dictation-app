"""Keeping the room out of the recogniser: the noise gate, the high-pass filter and the doubtful-word filter."""
import contextlib
import json
import math
import pathlib
import unittest
from array import array

from quill.listener.listener import Listener
from quill.listener.noise import ABS_MIN_RMS, HighPass, NoiseGate, rms


def tone(amplitude: float, n: int = 1600, hz: float = 220.0) -> bytes:
    return array("h", [int(amplitude * math.sin(2 * math.pi * hz * i / 16000)) for i in range(n)]).tobytes()


def level(chunk: bytes) -> float:
    s = array("h")
    s.frombytes(chunk)
    return rms(s)


class TestHighPass(unittest.TestCase):
    def test_a_steady_offset_is_removed_and_a_voice_pitch_is_kept(self):
        f = HighPass()
        dc = array("h", [3000] * 1600)
        for _ in range(5):
            out = f.process(dc)
        self.assertLess(abs(out[-1]), 60)                                     # the offset has gone
        voice = array("h", [int(3000 * math.sin(2 * math.pi * 300 * i / 16000)) for i in range(3200)])
        self.assertGreater(rms(HighPass().process(voice)), 1800)              # a 300 Hz voice pitch passes almost untouched


class TestGate(unittest.TestCase):
    def test_a_quiet_room_becomes_silence(self):
        gate = NoiseGate()
        for _ in range(30):
            out, voiced = gate.process(tone(120))
            self.assertFalse(voiced)
            self.assertEqual(level(out), 0.0)

    def test_a_voice_goes_through_and_the_tail_of_a_word_is_kept(self):
        gate = NoiseGate()
        for _ in range(12):
            gate.process(tone(100))
        out, voiced = gate.process(tone(3000))
        self.assertTrue(voiced)
        self.assertGreater(level(out), 1500)
        out, voiced = gate.process(tone(100))                                 # right after: still open (the hangover)
        self.assertTrue(voiced)
        for _ in range(6):
            out, voiced = gate.process(tone(100))
        self.assertFalse(voiced)                                              # and closed again after about 0.4 s

    def test_a_loud_steady_room_raises_the_bar_but_a_voice_still_passes(self):
        gate = NoiseGate()
        for _ in range(60):
            out, voiced = gate.process(tone(1400))                            # a fan (RMS about 990)
        self.assertGreater(gate.threshold, ABS_MIN_RMS)
        self.assertTrue(gate.noisy)
        self.assertFalse(voiced)
        self.assertTrue(gate.process(tone(6000))[1])

    def test_continuous_speech_does_not_gate_itself(self):
        gate = NoiseGate()
        for _ in range(10):
            gate.process(tone(100))
        passed = [gate.process(tone(3000 if i % 8 else 600))[1] for i in range(80)]   # speech with a soft moment every second
        self.assertTrue(all(passed))

    def test_the_noisy_notice_comes_once(self):
        heard = []
        listener = Listener(pathlib.Path("m"), lambda t: None)
        listener.set_noise_filter(True, heard.append)
        listener._gate = NoiseGate()
        for _ in range(40):
            listener._gate.process(tone(1400))
            listener._note_noise()
        self.assertEqual(len(heard), 1)
        self.assertIn("noisy", heard[0])


class TestDoubtfulWords(unittest.TestCase):
    def clean(self, words):
        return Listener._clean({"text": " ".join(w for w, _ in words), "result": [{"word": w, "conf": c} for w, c in words]})

    def test_low_confidence_words_are_dropped(self):
        self.assertEqual(self.clean([("black", 0.95), ("the", 0.2), ("shirt", 0.9)]), "black shirt")

    def test_a_short_unsure_phrase_is_dropped_whole(self):
        self.assertEqual(self.clean([("lab", 0.6), ("and", 0.62)]), "")
        self.assertEqual(self.clean([("next", 0.9), ("row", 0.92)]), "next row")

    def test_results_without_word_details_are_kept_as_they_are(self):
        self.assertEqual(Listener._clean({"text": "hello there"}), "hello there")


class TestListenerWithTheFilter(unittest.TestCase):
    def test_noise_reaches_the_recogniser_as_silence_and_a_voice_as_itself(self):
        fed = []

        class Recognizer:
            def __init__(self, model, rate): pass
            def AcceptWaveform(self, chunk):
                fed.append(level(chunk))
                return False
            def Result(self): return json.dumps({"text": ""})
            def PartialResult(self): return json.dumps({"partial": ""})

        pushes = []

        @contextlib.contextmanager
        def stream(rate, push):
            pushes.append(push)
            yield

        listener = Listener(pathlib.Path("m"), lambda t: None, model_loader=lambda p: "m", recognizer_factory=Recognizer, stream_factory=stream)
        listener.set_noise_filter(True)
        levels = []
        listener.set_level_callback(levels.append)
        listener.start()
        for _ in range(100):
            if pushes:
                break
            import time; time.sleep(0.01)
        for chunk in [tone(100)] * 12 + [tone(3000)] * 3:
            pushes[0](chunk)
        for _ in range(300):
            if len(fed) >= 15:
                break
            import time; time.sleep(0.01)
        listener.stop()
        self.assertEqual(fed[:12], [0.0] * 12)                                # the room: silence
        self.assertGreater(min(fed[12:15]), 1000)                             # the voice: as it was (less the filtered rumble)
        self.assertEqual(max(levels[:12]), 0.0)                               # the voice lines stay flat for the room


if __name__ == "__main__":
    unittest.main()
