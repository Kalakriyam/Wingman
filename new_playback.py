# new_playback.py
"""
Ultra-low-latency drop-in replacement for ultimate_playback.play

Dependencies
------------
pip install simpleaudio          # PortAudio wrapper, starts playing immediately

Usage
-----
from new_playback import play
play(audio_segment)              # blocks until done by default
"""

import simpleaudio as sa


def play(audio_segment,
         fade_ms=None,
         buffer_size=None,
         block: bool = True):
    """
    Play a pydub.AudioSegment with minimal overhead.

    Parameters
    ----------
    audio_segment : pydub.AudioSegment
        The audio to play.
    fade_ms, buffer_size : Ignored
        Kept only to preserve the original function signature.
    block : bool, default True
        If True, wait until playback finishes and return True.
        If False, return immediately (returns None, matching the
        behaviour of the original ultimate_playback.play).

    Returns
    -------
    bool | None
        True when blocking playback completes, otherwise None.
    """
    play_obj = sa.play_buffer(
        audio_segment.raw_data,
        num_channels=audio_segment.channels,
        bytes_per_sample=audio_segment.sample_width,
        sample_rate=audio_segment.frame_rate,
    )

    if block:
        play_obj.wait_done()
        return True
    return None
