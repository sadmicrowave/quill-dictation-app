"""Generate Quill's feedback sounds: five packs of four short cues each.

Run from the project root to (re)create ``quill/sounds/<pack>/<cue>.wav``:

    python tools/make_sounds.py

The files are committed, so this is only needed to change the sounds. It uses
the standard library only. Cues: ``success`` (rising), ``sort`` (an attention
arpeggio: terms need sorting), ``dismiss`` (falling: ignore / undo / delete)
and ``error`` (low and buzzy).
"""

from __future__ import annotations
import math
import pathlib
import struct
import wave

RATE = 22050
OUT = pathlib.Path(__file__).resolve().parents[1] / "quill" / "sounds"

#: Each pack: base pitch (Hz), harmonic partials (multiplier, level), decay time constant (s),
#: and whether notes are held flat (radio beeps) rather than ringing out.
PACKS = {
    "chime":   dict(base=880.0,  partials=[(1, 1.0), (2.76, 0.25), (5.4, 0.1)], tau=0.11, flat=False),
    "marimba": dict(base=523.25, partials=[(1, 1.0), (4.0, 0.3)],               tau=0.06, flat=False),
    "glass":   dict(base=1046.5, partials=[(1, 1.0), (2.0, 0.4), (3.0, 0.2)],   tau=0.2,  flat=False),
    "digital": dict(base=659.25, partials=[(1, 1.0), (3, 0.33), (5, 0.2)],      tau=0.0,  flat=True),
    "walkie":  dict(base=1000.0, partials=[(1, 1.0), (3, 0.2)],                 tau=0.0,  flat=True),
}

#: (semitones from the base pitch, start seconds, length seconds)
CUES = {
    "success": [(0, 0.00, 0.16), (7, 0.11, 0.24)],
    "sort":    [(0, 0.00, 0.12), (4, 0.13, 0.12), (9, 0.26, 0.22)],
    "dismiss": [(0, 0.00, 0.12), (-5, 0.10, 0.20)],
    "error":   [(-12, 0.00, 0.18), (-13, 0.17, 0.30)],
}


def render(pack: dict, notes: list[tuple[int, float, float]], buzzy: bool) -> list[int]:
    """Mix *notes* into 16-bit samples."""
    total = max(start + length for _, start, length in notes) + 0.05
    mix = [0.0] * int(total * RATE)
    partials = [(1, 1.0), (3, 0.5), (5, 0.3), (7, 0.2)] if buzzy else pack["partials"]
    for semitones, start, length in notes:
        freq = pack["base"] * 2 ** (semitones / 12)
        first = int(start * RATE)
        for n in range(int(length * RATE)):
            t = n / RATE
            attack = min(1.0, t / 0.005)
            release = min(1.0, (length - t) / 0.012)
            ring = 1.0 if (pack["flat"] or buzzy) else math.exp(-t / pack["tau"])
            wave_value = sum(level * math.sin(2 * math.pi * freq * mult * t) for mult, level in partials)
            if first + n < len(mix):
                mix[first + n] += wave_value * attack * release * ring
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
    for name, pack in PACKS.items():
        for cue, notes in CUES.items():
            write(OUT / name / f"{cue}.wav", render(pack, notes, buzzy=(cue == "error")))
    print(f"Wrote {len(PACKS) * len(CUES)} sounds to {OUT}")
