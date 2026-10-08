"""
Synthesises the soundtrack for CHARLIE: a gentle electric-piano / pad score that
follows the day's mood, plus sound effects timed to the animation's frames.

    python make_soundtrack.py soundtrack.wav

Only needs numpy. Timings mirror SCENES in build_charlie.py.
"""
import sys
import wave

import numpy as np

SR = 44100
FPS = 24
SCENES = [("title", 84), ("bed", 216), ("kitchen", 216), ("desk", 360),
          ("couch", 228), ("window", 300), ("outside", 216), ("end", 144)]
START = {}
_f = 1
for _n, _l in SCENES:
    START[_n] = _f
    _f += _l
TOTAL = (_f - 1) / FPS + 1.5
N = int(TOTAL * SR)
mix = np.zeros(N)
rng = np.random.default_rng(7)


def t_of(frame):
    return (frame - 1) / FPS


def add(sig, t, gain=1.0):
    i = int(t * SR)
    if i >= N:
        return
    j = min(N, i + len(sig))
    mix[i:j] += gain * sig[: j - i]


def env(n, a=0.01, d=0.3, sustain=0.0, r=None):
    t = np.arange(n) / SR
    e = np.minimum(t / max(a, 1e-4), 1.0) * (sustain + (1 - sustain) * np.exp(-t / d))
    if r:
        tail = int(r * SR)
        e[-tail:] *= np.linspace(1, 0, tail)
    return e


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def epiano(m, dur, vel=0.3):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = midi(m)
    s = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t / 0.25) \
        + 0.12 * np.sin(2 * np.pi * 3.01 * f * t) * np.exp(-t / 0.1)
    return vel * s * env(n, 0.005, 0.9, 0.0, r=0.05)


def pad(m, dur, vel=0.12):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = midi(m)
    s = sum(np.sin(2 * np.pi * f * (1 + d) * t) for d in (-0.003, 0.0, 0.004))
    s += 0.3 * np.sin(2 * np.pi * 2 * f * t)
    e = np.minimum(t / 0.8, 1) * np.minimum((dur - t) / 0.8, 1)
    return vel * s * np.clip(e, 0, 1) / 3


def bass(m, dur, vel=0.25):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * midi(m) * t) + 0.2 * np.sin(2 * np.pi * 2 * midi(m) * t)
    return vel * s * env(n, 0.01, 0.6, 0.3, r=0.1)


# ---------------------------------------------------------------- score
BPM = 84
beat = 60 / BPM
# F major-ish progression; chord tones (midi) + bass root
CHORDS = [([65, 69, 72, 76], 41), ([64, 67, 71, 74], 40),   # Fmaj7, Em7
          ([62, 65, 69, 72], 38), ([58, 62, 65, 69], 34)]   # Dm7, Bbmaj7
SAD = [([62, 65, 69, 72], 38), ([58, 62, 65, 69], 34),
       ([57, 60, 64, 67], 33), ([58, 62, 65, 69], 34)]
MEL = [72, 74, 76, 79, 81, 79, 76, 74]


def section(t0, t1, chords, density=1.0, melody=False, vel=1.0, padv=0.12):
    t = t0
    ci = 0
    while t < t1 - 0.2:
        notes, root = chords[ci % len(chords)]
        bar = 4 * beat
        add(pad(notes[0], bar + 0.6, padv * vel), t)
        add(pad(notes[2], bar + 0.6, padv * vel * 0.8), t)
        add(bass(root, bar * 0.95, 0.22 * vel), t)
        for b in range(4):
            if rng.random() < density:
                for k, nn in enumerate(notes[1:] if b % 2 else notes[:3]):
                    add(epiano(nn, beat * 1.6, 0.07 * vel), t + b * beat + 0.012 * k)
        if melody:
            for b in range(4):
                if rng.random() < 0.7:
                    add(epiano(MEL[(ci * 4 + b) % len(MEL)], beat * 1.2, 0.11 * vel),
                        t + b * beat + (beat / 2 if b % 2 else 0))
        t += bar
        ci += 1


S = {k: t_of(v) for k, v in START.items()}
END = TOTAL - 1.0
section(S["title"], S["bed"], CHORDS, 0.8, vel=0.8)
section(S["bed"], S["kitchen"], CHORDS[:2], 0.25, vel=0.45, padv=0.08)    # sleepy
section(S["kitchen"], S["desk"], CHORDS, 1.0, vel=0.9)                    # busy
section(S["desk"], S["couch"], CHORDS, 1.0, vel=0.8)
section(S["couch"], t_of(START["couch"] + 150), SAD, 0.5, vel=0.6)         # scrolling
# silence after the phone dies, then the score returns for the sunset
section(t_of(START["window"] + 20), S["outside"], SAD, 0.45, vel=0.55)
section(t_of(START["window"] + 186), END, CHORDS, 1.0, melody=True, vel=1.0, padv=0.16)

# ---------------------------------------------------------------- sfx


def buzz(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sign(np.sin(2 * np.pi * 140 * t)) * 0.5 + np.sin(2 * np.pi * 280 * t) * 0.3
    gate = ((t % 0.5) < 0.32).astype(float)
    return 0.12 * s * gate


def ping(f=1318.5):
    n = int(0.5 * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.5 * t)
    return 0.12 * s * env(n, 0.002, 0.12)


def bloop(f0=500, f1=900):
    n = int(0.16 * SR)
    t = np.arange(n) / SR
    f = np.linspace(f0, f1, n)
    return 0.16 * np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.003, 0.06)


def thud():
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    return 0.15 * (np.sin(2 * np.pi * 110 * t) + 0.3 * rng.standard_normal(n)) * env(n, 0.001, 0.025)


def power_down():
    n = int(0.8 * SR)
    t = np.arange(n) / SR
    f = np.linspace(700, 90, n)
    return 0.16 * np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.005, 0.3)


def rattle(dur):
    n = int(dur * SR)
    s = rng.standard_normal(n)
    clicks = (rng.random(n) < 0.004).astype(float)
    k = np.convolve(clicks * s, np.exp(-np.arange(200) / 30), mode="same")
    return 0.25 * k


def chime():
    out = np.zeros(int(2.5 * SR))
    for i, m in enumerate((72, 76, 79, 84)):
        seg = epiano(m, 2.0, 0.12)
        out[int(i * 0.12 * SR): int(i * 0.12 * SR) + len(seg)] += seg
    return out


b = START["bed"]
add(chime(), t_of(START["title"] + 6))
add(buzz((64 - 14) / FPS), t_of(b + 14))
add(thud(), t_of(b + 58), 1.5)
add(buzz((175 - 134) / FPS), t_of(b + 134))
k = START["kitchen"]
nf = k + 22
for i, g in enumerate([26, 16, 13, 11, 9, 8, 7]):
    add(ping(1318.5 * 2 ** ((i % 4) / 12)), t_of(nf))
    nf += g
d = START["desk"]
for i in range(14):
    add(thud(), t_of(d + 186 + i * 11), 0.7)
for kk in range(d, d + 340, 3):                       # keyboard clatter
    if rng.random() < 0.55:
        add(thud() * 0.25, t_of(kk) + rng.random() * 0.05)
c = START["couch"]
for i in range(7):
    add(bloop(520, 880) if i % 2 == 0 else bloop(700, 1100), t_of(c + 18 + i * 16))
add(ping(880), t_of(c + 132))
add(power_down(), t_of(c + 150))
w = START["window"]
for i in range(10):
    add(ping(2093 + 200 * (i % 3)) * 0.3, t_of(w + 101 + i * 3))
add(chime() * 0.6, t_of(w + 140))
add(rattle(26 / FPS), t_of(w + 186))
add(chime() * 0.5, t_of(START["outside"] + 78))

# ---------------------------------------------------------------- output
# gentle room reverb + master
ir = np.zeros(int(1.2 * SR))
for i in range(40):
    ir[int(rng.random() * len(ir))] += rng.random() * np.exp(-i / 10) * 0.2
ir[0] = 1.0
L = 1 << int(np.ceil(np.log2(N + len(ir))))
wet = np.fft.irfft(np.fft.rfft(mix, L) * np.fft.rfft(ir, L), L)[:N]
out = 0.75 * mix + 0.25 * wet
fade = int(1.2 * SR)
out[-fade:] *= np.linspace(1, 0, fade)
out = np.tanh(out / max(1e-6, np.abs(out).max()) * 1.4) * 0.8
pcm = (out * 32767).astype(np.int16)
path = sys.argv[1] if len(sys.argv) > 1 else "soundtrack.wav"
with wave.open(path, "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    wf.writeframes(pcm.tobytes())
print("wrote", path, round(TOTAL, 1), "s")
