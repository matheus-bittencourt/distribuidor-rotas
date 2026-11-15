"""Sintetiza a trilha e os efeitos sonoros do zero (numpy), sem amostras de terceiros.

Uso:  .tts\\Scripts\\python scripts\\som.py
Saída: public/audio/musica.wav e public/audio/fx-*.wav
Como tudo é gerado por este script, não há direito autoral de terceiros envolvido.
"""
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "public" / "audio"
rng = np.random.default_rng(7)


def save(name: str, x: np.ndarray, peak: float = 0.89) -> None:
    """Grava WAV 16 bits (mono ou estéreo), normalizado para `peak`."""
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    x = x / (np.max(np.abs(x)) or 1) * peak
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    print(f"{name:16s} {len(x) / SR:5.2f} s")


def t(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def lowpass(x: np.ndarray, cutoff) -> np.ndarray:
    """Passa-baixa de um polo; `cutoff` pode variar no tempo (Hz)."""
    a = 1 - np.exp(-2 * np.pi * np.broadcast_to(cutoff, x.shape) / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


# ------------------------------------------------------------------ efeitos
def fx_whoosh() -> np.ndarray:
    x = t(0.55)
    n = rng.standard_normal(len(x))
    sweep = 400 + 5200 * np.sin(np.pi * x / x[-1]) ** 2
    y = lowpass(n, sweep) - lowpass(n, sweep * 0.25)
    return y * np.sin(np.pi * x / x[-1]) ** 2


def fx_pop() -> np.ndarray:
    x = t(0.12)
    f = 620 * np.exp(-x * 14) + 240
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-x * 34)


def fx_tick() -> np.ndarray:
    x = t(0.16)
    one = np.sin(2 * np.pi * 1500 * x) * np.exp(-x * 90)
    two = np.roll(np.sin(2 * np.pi * 1100 * x) * np.exp(-x * 90), int(0.07 * SR))
    two[: int(0.07 * SR)] = 0
    return one + two * 0.8


def fx_ding() -> np.ndarray:
    x = t(1.1)
    y = sum(a * np.sin(2 * np.pi * f * x) * np.exp(-x * d) for f, a, d in [(880, 1, 4.5), (1320, 0.5, 6), (1760, 0.3, 8), (2640, 0.12, 11)])
    return y * np.minimum(1, x / 0.004)


def fx_click() -> np.ndarray:
    x = t(0.05)
    return (np.sin(2 * np.pi * 2100 * x) + 0.4 * rng.standard_normal(len(x))) * np.exp(-x * 160)


# ------------------------------------------------------------------ música
BPM = 92
BEAT = 60 / BPM
NOTE = {n: 440 * 2 ** ((i - 9) / 12) for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name: str, octave: int) -> float:
    return NOTE[name] * 2 ** (octave - 4)


# Progressão leve em Dó maior, 2 compassos por acorde.
CHORDS = [["F", "A", "C", "E"], ["C", "E", "G", "B"], ["A", "C", "E", "G"], ["G", "B", "D", "A"]]


def music(seconds: float) -> np.ndarray:
    n = int(seconds * SR)
    L, R = np.zeros(n), np.zeros(n)

    def add(buf, start, sig, gain=1.0):
        i = int(start * SR)
        if i >= n:
            return
        sig = sig[: n - i]
        buf[i:i + len(sig)] += sig * gain

    bar = BEAT * 4
    total_bars = int(np.ceil(seconds / bar))
    for b in range(total_bars):
        chord = CHORDS[(b // 2) % len(CHORDS)]
        t0 = b * bar
        # cama: senoides suaves com leve desafinação entre os canais
        x = t(bar + 0.6)
        env = np.minimum(1, x / 0.5) * np.minimum(1, (x[-1] - x) / 0.6)
        for k, nm in enumerate(chord):
            f = hz(nm, 3 if k == 0 else 4)
            add(L, t0, (np.sin(2 * np.pi * f * 0.998 * x) + 0.25 * np.sin(2 * np.pi * 2 * f * x)) * env, 0.11)
            add(R, t0, (np.sin(2 * np.pi * f * 1.002 * x) + 0.25 * np.sin(2 * np.pi * 2 * f * x)) * env, 0.11)
        if b < 2:
            continue  # dois compassos de entrada só com a cama
        # dedilhado em colcheias, alternando os lados
        x = t(0.9)
        for s in range(8):
            nm = chord[[0, 2, 1, 3, 2, 1, 3, 2][s]]
            f = hz(nm, 5)
            pl = (np.sin(2 * np.pi * f * x) + 0.3 * np.sin(2 * np.pi * 2 * f * x) + 0.1 * np.sin(2 * np.pi * 3 * f * x)) * np.exp(-x * 6) * np.minimum(1, x / 0.003)
            when = t0 + s * BEAT / 2
            near, far = (L, R) if s % 2 == 0 else (R, L)
            add(near, when, pl, 0.16)
            add(far, when, pl, 0.07)
            add(far, when + BEAT * 0.75, pl, 0.05)  # eco
        # bumbo macio nos tempos 1 e 3, chocalho nos contratempos
        x = t(0.3)
        kick = np.sin(2 * np.pi * np.cumsum(45 + 75 * np.exp(-x * 30)) / SR) * np.exp(-x * 13)
        for beat in (0, 2):
            add(L, t0 + beat * BEAT, kick, 0.34)
            add(R, t0 + beat * BEAT, kick, 0.34)
        x = t(0.07)
        for beat in range(4):
            sh = rng.standard_normal(len(x)) * np.exp(-x * 70)
            sh = sh - lowpass(sh, 5000)
            add(L, t0 + (beat + 0.5) * BEAT, sh, 0.05)
            add(R, t0 + (beat + 0.5) * BEAT, sh, 0.045)

    x = np.arange(n) / SR
    fade = np.minimum(1, x / 1.5) * np.minimum(1, (seconds - x) / 3.0)
    return np.stack([np.tanh(L * 1.4) * fade, np.tanh(R * 1.4) * fade], axis=1)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    save("fx-whoosh.wav", fx_whoosh(), 0.6)
    save("fx-pop.wav", fx_pop(), 0.7)
    save("fx-tick.wav", fx_tick(), 0.6)
    save("fx-ding.wav", fx_ding(), 0.7)
    save("fx-click.wav", fx_click(), 0.6)
    save("musica.wav", music(64), 0.8)
