import ctypes
from ctypes import (
    Structure, POINTER, byref,
    c_int, c_ulong, c_void_p, c_double
)
from pathlib import Path
# verbose: bool = False

# ── PortAudio DLL ───────────────────────────────────────────────────────
dll_path = Path.cwd() / "portaudio" / "portaudio.dll"
if not dll_path.exists():
    raise FileNotFoundError(f"PortAudio DLL not found: {dll_path}")

pa = ctypes.cdll.LoadLibrary(str(dll_path))

# ── PortAudio constants + helpers ──────────────────────────────────────
PA_INT16 = 0x00000008
CHUNK_FRAMES = 4096  # ≈93 ms @ 44.1 kHz mono

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

# blocking-I/O specific prototypes
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

def play(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> None:
    """Play entire PCM buffer with one blocking write."""
    samples  = len(pcm_bytes) // 2        # 16-bit
    pcm_buf  = (ctypes.c_int16 * samples).from_buffer_copy(pcm_bytes)

    # if verbose:
    #     print("--- play() called ---")
    #     print(f"pcm bytes: {len(pcm_bytes)}   samples: {len(pcm_bytes)//2}")
    #     print(f"sample_rate={sample_rate}   channels={channels}")

    _pa_ok(pa.Pa_Initialize(), "Pa_Initialize failed")
    ret = pa.Pa_Initialize()
    # if verbose:
    #     print("Pa_Initialize →", ret)
    _pa_ok(ret, "Pa_Initialize failed")

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