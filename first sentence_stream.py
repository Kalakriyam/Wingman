"""
low_latency_tts_player.py
─────────────────────────
Plays ElevenLabs TTS with the fastest decode path (miniaudio)
and the lowest-latency PortAudio stream (manual ctypes).

env:
    ELEVENLABS_API_KEY  - put in .env or your shell
"""

from __future__ import annotations
import os, sys, time, ctypes, asyncio
from pathlib import Path
from ctypes import (
    Structure, POINTER, byref,
    c_int, c_ulong, c_void_p, c_double
)
from typing import Final

import aiohttp
import miniaudio
from dotenv import load_dotenv

# ── PortAudio DLL discovery (unchanged) ────────────────────────────────
if sys.platform.startswith("win"):
    libdir = Path(sys.prefix) / "Library" / "bin"
    os.add_dll_directory(libdir)
    for _dll in ("portaudio.dll", "libportaudio-2.dll"):
        dll_path = libdir / _dll
        if dll_path.exists():
            break
    else:
        raise FileNotFoundError("PortAudio DLL not found in Library\\bin")
elif sys.platform == "darwin":
    dll_path = "libportaudio.dylib"
else:
    dll_path = "libportaudio.so"

pa = ctypes.cdll.LoadLibrary(str(dll_path))

# ── PortAudio constants + helpers ──────────────────────────────────────
PA_INT16          = 0x00000008
FRAMES_PER_BUFFER = 64           # ≈1.3 ms at 48 kHz
PA_CONTINUE, PA_COMPLETE = 0, 1

class PaStreamParameters(Structure):
    _fields_ = [
        ("device",                     c_int),
        ("channelCount",               c_int),
        ("sampleFormat",               c_ulong),
        ("suggestedLatency",           c_double),
        ("hostApiSpecificStreamInfo",  c_void_p),
]

def _pa_ok(code: int, ctx: str) -> None:
    if code != 0:
        pa.Pa_Terminate()
        raise RuntimeError(f"{ctx} (PaError={code})")

# declare PortAudio prototypes only once
pa.Pa_Initialize.restype              = c_int
pa.Pa_Terminate.restype               = c_int
pa.Pa_GetDefaultOutputDevice.restype  = c_int
pa.Pa_OpenStream.restype              = c_int
pa.Pa_OpenStream.argtypes = [
    POINTER(c_void_p), POINTER(PaStreamParameters), POINTER(PaStreamParameters),
    c_double, c_ulong, c_ulong, c_void_p, c_void_p,
]
for fn in ("Pa_StartStream", "Pa_StopStream",
           "Pa_CloseStream", "Pa_IsStreamActive"):
    getattr(pa, fn).restype  = c_int
    getattr(pa, fn).argtypes = [c_void_p]

# ── helper: play PCM through PortAudio (callback) ───────────────────────
def play_pcm_with_portaudio(pcm_bytes: bytes,
                            sample_rate: int,
                            channels: int = 1) -> None:
    """Blocks until the entire buffer is heard."""
    samples = len(pcm_bytes) // 2  # 16-bit
    pcm_buf = (ctypes.c_int16 * samples).from_buffer_copy(pcm_bytes)

    _pa_ok(pa.Pa_Initialize(), "Pa_Initialize failed")
    dev = pa.Pa_GetDefaultOutputDevice()
    if dev < 0:
        _pa_ok(dev, "No default output device")

    out_params = PaStreamParameters(
        device      = dev,
        channelCount= channels,
        sampleFormat= PA_INT16,
        suggestedLatency = 0.05,
        hostApiSpecificStreamInfo = None,
    )

    stream          = c_void_p()
    play_pos_frames = 0
    total_frames    = samples // channels

    CB_FUNCTYPE = ctypes.CFUNCTYPE(
        c_int, c_void_p, c_void_p, c_ulong, c_void_p, c_ulong, c_void_p
    )

    @CB_FUNCTYPE
    def callback(_in_ptr, out_ptr, frames, *_):  # type: ignore[return-value]
        nonlocal play_pos_frames
        dest = ctypes.cast(out_ptr, ctypes.c_void_p).value

        remaining     = total_frames - play_pos_frames
        to_copy       = min(remaining, frames)
        bytes_to_copy = to_copy * channels * 2
        src_offset    = play_pos_frames * channels * 2

        ctypes.memmove(dest,
                       ctypes.addressof(pcm_buf) + src_offset,
                       bytes_to_copy)

        if to_copy < frames:  # pad tail with silence
            ctypes.memset(dest + bytes_to_copy,
                          0,
                          (frames - to_copy) * channels * 2)

        play_pos_frames += to_copy
        return PA_CONTINUE if play_pos_frames < total_frames else PA_COMPLETE

    _pa_ok(pa.Pa_OpenStream(
        byref(stream), None, byref(out_params),
        sample_rate, FRAMES_PER_BUFFER, 0,
        callback, None),
        "Pa_OpenStream failed")

    _pa_ok(pa.Pa_StartStream(stream), "Pa_StartStream failed")

    # wait until callback finishes
    while pa.Pa_IsStreamActive(stream):
        time.sleep(0.01)

    pa.Pa_StopStream(stream)
    pa.Pa_CloseStream(stream)
    pa.Pa_Terminate()

# ── ElevenLabs TTS fetch + decode ───────────────────────────────────────
load_dotenv()
API_KEY: Final = os.getenv("ELEVENLABS_API_KEY") or sys.exit("ELEVENLABS_API_KEY missing")
VOICE_ID: Final      = "Yko7PKHZNXotIFUBG7I9"
OUTPUT_FORMAT: Final = "mp3_44100_128"
MODEL_ID: Final      = "eleven_turbo_v2_5"
TTS_URL: Final       = (
    f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
    f"?output_format={OUTPUT_FORMAT}"
)
DEFAULT_TEXT: Final  = "Hallo Alexander, waar wil je mee beginnen?"

async def fetch_tts_mp3(text: str) -> bytes:
    headers = {"xi-api-key": API_KEY, "Content-Type": "application/json"}
    body    = {"text": text, "model_id": MODEL_ID}
    async with aiohttp.ClientSession() as sess:
        print(f"Fetching TTS MP3 from ElevenLabs...")
        async with sess.post(TTS_URL, headers=headers, json=body) as resp:
            if resp.status != 200:
                raise RuntimeError(f"ElevenLabs {resp.status}: {await resp.text()}")
            return await resp.read()

def decode_mp3_to_pcm(mp3_bytes: bytes) -> tuple[bytes, int]:
    decoded = miniaudio.decode(
        mp3_bytes,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=44100,
    )
    return decoded.samples.tobytes(), decoded.sample_rate

# ── main entrypoint ─────────────────────────────────────────────────────
async def main(text: str = DEFAULT_TEXT) -> None:
    mp3_bytes  = await fetch_tts_mp3(text)
    pcm_bytes, sample_rate = await asyncio.to_thread(decode_mp3_to_pcm, mp3_bytes)
    print(f"TTS fetched and decoded – {len(pcm_bytes)//2} samples @ {sample_rate} Hz")
    play_pcm_with_portaudio(pcm_bytes, sample_rate)
    print("Playback finished")

if __name__ == "__main__":
    asyncio.run(main())
