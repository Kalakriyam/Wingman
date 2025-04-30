"""
play_segment.py
Decodes an MP3 byte-string to 16-bit PCM and writes it into an
already-open miniaudio PlaybackDevice.
"""
import miniaudio


def _decode_mp3_to_pcm(mp3_bytes: bytes) -> bytes:
    decoded = miniaudio.decode(
        mp3_bytes,
        output_format=miniaudio.SampleFormat.SIGNED16,
        nchannels=1,
        sample_rate=44_100,
    )
    return decoded.samples.tobytes()


def play_audio_segment(playback_device: miniaudio.PlaybackDevice,
                       mp3_bytes: bytes) -> None:
    pcm_bytes = _decode_mp3_to_pcm(mp3_bytes)
    playback_device.write(pcm_bytes)   # blocks until buffer is queued
