"""Keeping the room out of the speech recogniser.

A recogniser will find words in any sound it is given: a fan, a passing car or a TV in the next room comes out as "you love it as
then lab". Two cheap, light steps keep most of that away (nothing here uses a model or more than a few thousand sums a second):

* :class:`HighPass` removes the rumble and hum under a voice (below about 100 Hz), which carries no words but can fool a loudness test.
* :class:`NoiseGate` learns how loud the room is when nobody speaks and lets audio through only while something clearly louder
  than that is going on (a voice), plus a short tail so the ends of words are not cut. In between it hands the recogniser
  *silence* (not nothing), so a phrase still ends when the speaker stops.

Pure Python on 16-bit audio, so it is the same on every platform and easy to test.
"""

from __future__ import annotations

import math
from array import array
from collections import deque

#: Quietest sound (RMS of 16-bit samples) ever treated as a voice, however quiet the room.
ABS_MIN_RMS = 350.0
#: How much louder than the room's quiet level a sound must be to count as a voice (about +8 dB).
SNR = 2.5
#: Seconds the gate stays open after the last loud chunk (the ends of words are quiet).
HANGOVER_S = 0.4
#: Seconds of audio the room's quiet level is judged over.
WINDOW_S = 8.0
#: Quiet level above which the room is called noisy (RMS).
NOISY_RMS = 800.0
#: Chunks needed before the room can be judged noisy.
JUDGE_AFTER = 20


def rms(samples: array) -> float:
    """The root-mean-square loudness of 16-bit *samples*."""
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


class HighPass:
    """A one-pole high-pass filter (about 100 Hz at 16 kHz): ``y[n] = a (y[n-1] + x[n] - x[n-1])``."""

    def __init__(self, sample_rate: int = 16_000, cutoff: float = 100.0) -> None:
        self._a = 1.0 / (1.0 + 2.0 * math.pi * cutoff / sample_rate)
        self._x = 0.0
        self._y = 0.0

    def process(self, samples: array) -> array:
        a, x_prev, y_prev = self._a, self._x, self._y
        out = array("h", samples)
        for i, x in enumerate(samples):
            y = a * (y_prev + x - x_prev)
            x_prev, y_prev = x, y
            out[i] = max(-32768, min(32767, int(y)))
        self._x, self._y = x_prev, y_prev
        return out


class NoiseGate:
    """Opens for a voice, closes for the room. ``process(chunk)`` returns ``(audio, open)``: the chunk itself while the gate is open
    and the same length of silence while it is closed.

    Args:
        sample_rate: Samples a second.
        chunk_s: Seconds of audio in each chunk handed to :meth:`process`.
    """

    def __init__(self, sample_rate: int = 16_000, chunk_s: float = 0.1) -> None:
        self._chunk_s = chunk_s
        self._filter = HighPass(sample_rate)
        self._levels: deque[float] = deque(maxlen=max(int(WINDOW_S / chunk_s), 1))
        self._hang = 0.0
        self._seen = 0
        self.noisy = False                    # set once, when the room's quiet level is judged
        self._judged = False

    @property
    def floor(self) -> float:
        """The room's quiet level (RMS): the low end of what was heard recently."""
        if not self._levels:
            return ABS_MIN_RMS / SNR
        ordered = sorted(self._levels)
        return ordered[int(len(ordered) * 0.05)]                         # (the quietest moments: pauses between words)

    @property
    def threshold(self) -> float:
        """The loudness a chunk needs to count as a voice now."""
        return max(ABS_MIN_RMS, self.floor * SNR)

    def process(self, chunk: bytes) -> tuple[bytes, bool]:
        samples = array("h")
        samples.frombytes(chunk[: len(chunk) // 2 * 2])
        if not samples:
            return chunk, False
        samples = self._filter.process(samples)
        level = rms(samples)
        loud = level >= self.threshold
        self._seen += 1
        if self._seen > 2:                                                   # (the filter's first chunks are not the room)
            self._levels.append(level)
        if not self._judged and len(self._levels) >= JUDGE_AFTER:
            self._judged = True
            self.noisy = self.floor >= NOISY_RMS
        if loud:
            self._hang = HANGOVER_S
        elif self._hang > 0:
            self._hang -= self._chunk_s
        else:
            return bytes(len(samples) * 2), False
        return samples.tobytes(), True
