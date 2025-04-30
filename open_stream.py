"""
open_stream.py
Opens a single low-latency playback stream and keeps it running.
"""
import miniaudio


def open_audio_output_stream(sample_rate: int = 44_100,
                             channels: int = 1) -> miniaudio.PlaybackDevice:
    """
    Start a miniaudio PlaybackDevice once and return the handle.
    Keep the handle alive for the whole session.
    """
    playback_device = miniaudio.PlaybackDevice(sample_rate=sample_rate,
                                               channels=channels)
    playback_device.start()
    return playback_device
