import miniaudio
import numpy as np
import sounddevice as sd
import threading

sd.default.latency = 'low'

DEFAULT_BUFFER_SIZE = 64
DEFAULT_FADE_MS = 0
DTYPE_MAP = {1: np.int8, 2: np.int16, 4: np.int32}

def play(file_path, fade_ms=DEFAULT_FADE_MS, buffer_size=DEFAULT_BUFFER_SIZE, block=True):
    """
    Play an MP3 file with minimal latency using miniaudio for decoding.  
    """
    # Decode MP3 file to PCM using miniaudio
    decoded_audio = miniaudio.decode_file(file_path)

    # Extract audio properties
    channels = decoded_audio.nchannels
    frame_rate = decoded_audio.sample_rate
    dtype = np.int16  # miniaudio outputs 16-bit PCM by default

    # Convert raw PCM data to numpy array
    audio_data = np.frombuffer(decoded_audio.samples, dtype=dtype)

    # Reshape for channel structure
    if channels > 1:
        audio_data = audio_data.reshape((-1, channels))
    else:
        audio_data = audio_data.reshape((-1, 1))

    # Apply fade-out if needed
    if fade_ms > 0:
        fade_samples = int(frame_rate * fade_ms / 1000)
        total_samples = audio_data.shape[0]

        if 0 < fade_samples < total_samples:
            audio_data = audio_data.copy()
            fade_curve = np.linspace(1.0, 0.0, fade_samples).reshape(-1, 1)
            fade_start = total_samples - fade_samples
            audio_data[fade_start:] = (audio_data[fade_start:].astype(np.float32) * fade_curve).astype(dtype)

    # Configure blocksize if needed
    if sd.default.blocksize != buffer_size:
        sd.default.blocksize = buffer_size

    # Setup for callback-based playback
    event = threading.Event()

    def callback(outdata, frames, time, status):
        if status:
            print(f"Status: {status}")

        remaining = len(audio_data) - callback.position
        if remaining > 0:
            chunk_size = min(remaining, frames)
            outdata[:chunk_size] = audio_data[callback.position:callback.position+chunk_size]
            if chunk_size < frames:
                outdata[chunk_size:].fill(0)
            callback.position += chunk_size
            if callback.position >= len(audio_data):
                event.set()
                raise sd.CallbackStop
        else:
            outdata.fill(0)
            event.set()
            raise sd.CallbackStop

    callback.position = 0

    with sd.OutputStream(
        samplerate=frame_rate,
        blocksize=buffer_size,
        channels=channels,
        dtype=dtype,
        callback=callback
    ):
        if block:
            event.wait()
            return True
        else:
            return None