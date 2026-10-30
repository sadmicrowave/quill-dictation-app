"""Generate Quill's feedback sounds: five packs of four short cues each.

Run from the project root to (re)create ``quill/sounds/<pack>/<cue>.wav``:

    python tools/make_sounds.py

The files are committed, so this is only needed to change the sounds. It uses
the standard library only. Cues: ``success``, ``sort`` (terms need sorting),
``dismiss`` (ignore / undo / delete) and ``error``.

The packs are meant to be easy to tell apart: each has its own instrument *and*
its own melodic habit, not just a different pitch.

  chime ....... bell, rising fifth; a three-note arpeggio for sorting
  marimba ..... wooden mallet knocks: a quick two-step up, a tremolo roll, one low knock
  glass ....... high, soft, long-ringing pings: an octave pair, a falling cascade
  digital ..... 8-bit square-wave: fast arpeggio, a two-tone siren, a pitch dive
  walkie ...... radio roger beeps wrapped in a puff of static
"""

from __future__ import annotations
import math
import pathlib
import random
import struct
import wave

RATE = 22050
OUT = pathlib.Path(__file__).resolve().parents[1] / "quill" / "sounds"


def n(freq: float, start: float, length: float, *instruments: dict, **options) -> dict:
    """A note: ``freq`` Hz at ``start`` s for ``length`` s, with instrument settings.

    Later settings win, so ``n(131, 0, .2, MALLET, tau=.08)`` is a mallet with a longer ring.
    """
    note = dict(freq=freq, start=start, length=length)
    for instrument in instruments:
        note.update(instrument)
    note.update(options)
    return note


def semis(base: float, steps: float) -> float:
    return base * 2 ** (steps / 12)


# ---- instruments -------------------------------------------------------------

BELL = dict(partials=[(1, 1.0), (2.76, 0.25), (5.4, 0.1)], tau=0.11)
MALLET = dict(partials=[(1, 1.0), (3.9, 0.45), (9.2, 0.12)], tau=0.045, click=0.5)
GLASS = dict(partials=[(1, 1.0), (2.0, 0.3), (3.0, 0.12)], tau=0.32, attack=0.012)
SQUARE = dict(wave="square", flat=True)
RADIO = dict(partials=[(1, 1.0), (3, 0.18)], flat=True)
BUZZ = dict(partials=[(1, 1.0), (3, 0.5), (5, 0.3), (7, 0.2)], flat=True)

PACKS = {
    "chime": {
        "success": [n(semis(880, 0), 0.00, 0.16, BELL), n(semis(880, 7), 0.11, 0.24, BELL)],
        "sort":    [n(semis(880, 0), 0.00, 0.12, BELL), n(semis(880, 4), 0.13, 0.12, BELL),
                    n(semis(880, 9), 0.26, 0.22, BELL)],
        "dismiss": [n(semis(880, 0), 0.00, 0.12, BELL), n(semis(880, -5), 0.10, 0.20, BELL)],
        "error":   [n(semis(880, -12), 0.00, 0.18, BUZZ), n(semis(880, -13), 0.17, 0.30, BUZZ)],
    },
    "marimba": {
        "success": [n(262, 0.00, 0.14, MALLET), n(330, 0.09, 0.22, MALLET)],
        "sort":    [n(392, 0.00, 0.09, MALLET), n(392, 0.07, 0.09, MALLET), n(392, 0.14, 0.09, MALLET),
                    n(392, 0.21, 0.09, MALLET), n(587, 0.30, 0.26, MALLET)],
        "dismiss": [n(147, 0.00, 0.30, MALLET)],
        "error":   [n(131, 0.00, 0.22, MALLET, tau=0.08), n(139, 0.06, 0.30, MALLET, tau=0.08)],
    },
    "glass": {
        "success": [n(1319, 0.00, 0.45, GLASS), n(2637, 0.08, 0.55, GLASS, level=0.45)],
        "sort":    [n(2349, 0.00, 0.35, GLASS), n(1760, 0.17, 0.35, GLASS), n(1319, 0.34, 0.50, GLASS)],
        "dismiss": [n(988, 0.00, 0.28, GLASS, tau=0.12)],
        "error":   [n(660, 0.00, 0.55, GLASS, tau=0.5), n(680, 0.00, 0.55, GLASS, tau=0.5)],   # beating
    },
    "digital": {
        "success": [n(523, 0.00, 0.05, SQUARE), n(659, 0.05, 0.05, SQUARE), n(784, 0.10, 0.05, SQUARE),
                    n(1047, 0.15, 0.10, SQUARE)],
        "sort":    [n(880, i * 0.06, 0.055, SQUARE) if i % 2 == 0 else n(1175, i * 0.06, 0.055, SQUARE)
                    for i in range(6)],
        "dismiss": [n(900, 0.00, 0.20, SQUARE, glide_to=180)],
        "error":   [n(98, 0.00, 0.42, wave="saw", flat=True, tremolo=28)],
    },
    "walkie": {
        "success": [n(1200, 0.05, 0.13, RADIO), n(0, 0.00, 0.05, noise=0.35), n(0, 0.18, 0.09, noise=0.3, fade=True)],
        "sort":    [n(1000, 0.04, 0.07, RADIO), n(1000, 0.16, 0.07, RADIO), n(1000, 0.28, 0.07, RADIO),
                    n(0, 0.00, 0.04, noise=0.3), n(0, 0.35, 0.07, noise=0.28, fade=True)],
        "dismiss": [n(600, 0.04, 0.10, RADIO), n(0, 0.00, 0.04, noise=0.3), n(0, 0.14, 0.12, noise=0.3, fade=True)],
        "error":   [n(420, 0.04, 0.22, RADIO), n(300, 0.30, 0.30, RADIO),
                    n(0, 0.00, 0.04, noise=0.4), n(0, 0.60, 0.14, noise=0.35, fade=True)],
    },
}


def wave_value(kind: str, phase: float) -> float:
    frac = phase % 1.0
    if kind == "square":
        return 1.0 if frac < 0.5 else -1.0
    if kind == "saw":
        return 2 * frac - 1
    return math.sin(2 * math.pi * phase)


def render(notes: list[dict], seed: int = 7) -> list[int]:
    """Mix *notes* into 16-bit samples."""
    rng = random.Random(seed)
    total = max(note["start"] + note["length"] for note in notes) + 0.05
    mix = [0.0] * int(total * RATE)
    for note in notes:
        first, count = int(note["start"] * RATE), int(note["length"] * RATE)
        level = note.get("level", 1.0)
        phase = 0.0
        for i in range(count):
            t = i / RATE
            attack = min(1.0, t / note.get("attack", 0.005))
            release = min(1.0, (note["length"] - t) / 0.012)
            if note.get("noise"):                                       # a puff of static
                fade = (1 - t / note["length"]) if note.get("fade") else 1.0
                value = rng.uniform(-1, 1) * note["noise"] * fade
            else:
                ring = 1.0 if note.get("flat") else math.exp(-t / note["tau"])
                freq = note["freq"]
                if note.get("glide_to"):
                    freq = freq + (note["glide_to"] - freq) * (t / note["length"])
                phase += freq / RATE
                if note.get("partials"):
                    value = sum(lv * math.sin(2 * math.pi * phase * mult) for mult, lv in note["partials"])
                else:
                    value = wave_value(note.get("wave", "sine"), phase) * 0.6
                if note.get("tremolo"):
                    value *= 0.55 + 0.45 * math.sin(2 * math.pi * note["tremolo"] * t)
                if note.get("click") and t < 0.006:                       # the mallet's wooden tap
                    value += rng.uniform(-1, 1) * note["click"]
                value *= ring
            if first + i < len(mix):
                mix[first + i] += value * attack * release * level
    peak = max(abs(v) for v in mix) or 1.0
    return [int(v / peak * 0.55 * 32767) for v in mix]


def write(path: pathlib.Path, samples: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(struct.pack(f"<{len(samples)}h", *samples))


if __name__ == "__main__":
    count = 0
    for name, cues in PACKS.items():
        for cue, notes in cues.items():
            write(OUT / name / f"{cue}.wav", render(notes))
            count += 1
    print(f"Wrote {count} sounds to {OUT}")
