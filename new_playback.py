import simpleaudio as sa
import numpy as np
import miniaudio

# ── audio ────────────────────────────────────────────────────────────────────
def play(mp3_bytes: bytes) -> None:
    """Decode MP3 → signed-16 PCM and play it synchronously."""
    # decoded = miniaudio.decode(mp3_bytes,
    #                            output_format=miniaudio.SampleFormat.SIGNED16,
    #                            nchannels=1,
    #                            sample_rate=44100)
    decoded = miniaudio.decode(mp3_bytes)
    # simpleaudio wants raw bytes; each sample = 2 bytes
    play_obj = sa.play_buffer(decoded.samples.tobytes(),
                              num_channels=decoded.nchannels,
                              bytes_per_sample=decoded.sample_width,
                              sample_rate=decoded.sample_rate)         # :contentReference[oaicite:0]{index=0}
    play_obj.wait_done()

# def play(decoded: bytes) -> None:
#     # simpleaudio wants raw bytes; each sample = 2 bytes
#     play_obj = sa.play_buffer(decoded.samples.tobytes(),
#                               num_channels=decoded.nchannels,
#                               bytes_per_sample=2,
#                               sample_rate=decoded.sample_rate)         # :contentReference[oaicite:0]{index=0}
#     play_obj.wait_done()