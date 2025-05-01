import simpleaudio as sa

def play(audio_blob: dict) -> None:
    """
    Play one PCM fragment produced by the updated `tts_request`.

    Parameters
    ----------
    audio_blob : dict
        {
            "pcm": bytes,            # raw signed-16 PCM
            "nchannels": int,        # e.g. 1
            "sample_rate": int,      # e.g. 44100
            "bytes_per_sample": int  # always 2 for signed-16
        }
    """
    play_obj = sa.play_buffer(
        audio_blob["pcm"],
        num_channels=audio_blob["nchannels"],
        bytes_per_sample=audio_blob["bytes_per_sample"],
        sample_rate=audio_blob["sample_rate"],
    )
    play_obj.wait_done()
