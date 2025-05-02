"""
low_latency_tts_player_blocking.py
──────────────────────────────────
Plays ElevenLabs TTS with miniaudio decode and **direct** PortAudio
blocking writes (no callback, no per-buffer stream setup).
"""
from __future__ import annotations
import aiohttp, asyncio, ctypes, os, sys, time
from pathlib import Path
from ctypes import (
    Structure, POINTER, byref,
    c_int, c_ulong, c_void_p, c_double
)
import miniaudio
from typing import Final
from dotenv import load_dotenv


# ── PortAudio DLL ───────────────────────────────────────────────────────
dll_path = Path.cwd() / "portaudio" / "portaudio.dll"
if not dll_path.exists():
    raise FileNotFoundError(f"PortAudio DLL not found: {dll_path}")

pa = ctypes.cdll.LoadLibrary(str(dll_path))

# ── PortAudio constants + helpers ──────────────────────────────────────
PA_INT16 = 0x00000008
PA_CONTINUE, PA_COMPLETE = 0, 1     # kept for symmetry
CHUNK_FRAMES = 4096                 # ≈93 ms @ 44.1 kHz mono

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

    # core PortAudio prototypes
    pa.Pa_Initialize.restype             = c_int
    pa.Pa_Terminate.restype              = c_int
    pa.Pa_StartStream.restype            = c_int
    pa.Pa_StopStream.restype             = c_int
    pa.Pa_CloseStream.restype            = c_int
    pa.Pa_IsStreamActive.restype         = c_int
    for fn in ("Pa_StartStream", "Pa_StopStream", "Pa_CloseStream", "Pa_IsStreamActive"):
        getattr(pa, fn).argtypes = [c_void_p]

    # 🔑 blocking-I/O specific prototypes
    pa.Pa_OpenDefaultStream.restype  = c_int
    pa.Pa_OpenDefaultStream.argtypes = [
    POINTER(c_void_p),      # stream**
    c_int,                  # numInputChannels
    c_int,                  # numOutputChannels
    c_ulong,                # sampleFormat
    c_double,               # sampleRate
    c_ulong,                # framesPerBuffer
    c_void_p, c_void_p      # callback, userData (both NULL → blocking mode)
    ]
    pa.Pa_WriteStream.restype  = c_int
    pa.Pa_WriteStream.argtypes = [c_void_p, c_void_p, c_ulong]  # stream*, buffer, frames


# ── helper: play PCM through PortAudio (blocking) ───────────────────────
def play_pcm_blocking(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> None:
    """Play entire PCM buffer with one blocking write."""
    samples  = len(pcm_bytes) // 2        # 16-bit
    pcm_buf  = (ctypes.c_int16 * samples).from_buffer_copy(pcm_bytes)

    _pa_ok(pa.Pa_Initialize(), "Pa_Initialize failed")

    stream = c_void_p()
    _pa_ok(
        pa.Pa_OpenDefaultStream(
            byref(stream),
            0,                # no input
            channels,
            PA_INT16,
            sample_rate,
            0,                # let PortAudio pick optimal size
            None, None), 
        "Pa_OpenDefaultStream failed"
    )
    _pa_ok(pa.Pa_StartStream(stream), "Pa_StartStream failed")

    total_frames   = samples // channels
    frames_written = 0

    while frames_written < total_frames:
        todo_frames = min(CHUNK_FRAMES, total_frames - frames_written)
        offset      = frames_written * channels * 2  # bytes
        buf_ptr     = ctypes.c_void_p(ctypes.addressof(pcm_buf) + offset)
        _pa_ok(pa.Pa_WriteStream(stream, buf_ptr, todo_frames), "Pa_WriteStream failed")
        frames_written += todo_frames

    pa.Pa_StopStream(stream)
    pa.Pa_CloseStream(stream)
    pa.Pa_Terminate()


# ── ElevenLabs TTS fetch + decode (unchanged) ───────────────────────────
load_dotenv()
API_KEY: Final = os.getenv("ELEVENLABS_API_KEY") or sys.exit("ELEVENLABS_API_KEY missing")
VOICE_ID: Final      = "Yko7PKHZNXotIFUBG7I9"
OUTPUT_FORMAT: Final = "mp3_44100_128"
MODEL_ID: Final      = "eleven_flash_v2_5"
TTS_URL: Final       = (
    f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
    f"?output_format={OUTPUT_FORMAT}"
)
DEFAULT_TEXT: Final  = "Hallo Alexander, waar wil je mee beginnen?"

async def fetch_tts_mp3(text: str) -> bytes:
    headers = {"xi-api-key": API_KEY, "Content-Type": "application/json"}
    body    = {"text": text, "model_id": MODEL_ID}
    async with aiohttp.ClientSession() as sess:
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
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Fetching MP3...")
    mp3_bytes  = await fetch_tts_mp3(text)
    pcm_bytes, sr = await asyncio.to_thread(decode_mp3_to_pcm, mp3_bytes)
    print(f"Playing MP3 @ {sr} Hz")
    play_pcm_blocking(pcm_bytes, sr)
    print("Playback finished\n\n")

if __name__ == "__main__":
    asyncio.run(main())
