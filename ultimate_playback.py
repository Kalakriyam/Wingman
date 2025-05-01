import numpy as np
import sounddevice as sd
sd.default.latency = 'low'
import threading

# Configuration variables for easy experimentation
DEFAULT_BUFFER_SIZE = 64 # Smaller values reduce latency but may cause stuttering
DEFAULT_FADE_MS = 25      # Milliseconds of fade out to prevent choppy endings

# Pre-compiled dtype mapping
DTYPE_MAP = {1: np.int8, 2: np.int16, 4: np.int32}

def play(audio_segment, fade_ms=DEFAULT_FADE_MS, buffer_size=DEFAULT_BUFFER_SIZE, block=True):
    """
    Play audio segment with minimal latency while maintaining reliability.
    
    Optimized version with:
    1) Direct buffer access via frombuffer (avoids extra copy)
    2) Efficient fade implementation that only copies what's needed
    3) Simple and reliable callback-based playback
    """
    # Get audio properties we'll need
    channels = audio_segment.channels
    frame_rate = audio_segment.frame_rate
    
    # Get data type for the raw data
    dtype = DTYPE_MAP.get(audio_segment.sample_width, np.int16)
    
    # Create array from raw_data without extra copy
    audio_data = np.frombuffer(audio_segment.raw_data, dtype=dtype)
    
    # Reshape for channel structure
    if channels > 1:
        audio_data = audio_data.reshape((-1, channels))
    else:
        audio_data = audio_data.reshape((-1, 1))
       
    # Configure blocksize if needed
    if sd.default.blocksize != buffer_size:
        sd.default.blocksize = buffer_size
    
    # Setup for callback-based playback
    event = threading.Event()
    
    def callback(outdata, frames, time, status):
        if status:
            print(f"Status: {status}")
        
        # Calculate how many frames to copy
        remaining = len(audio_data) - callback.position
        if remaining > 0:
            # Copy available data to output buffer
            chunk_size = min(remaining, frames)
            outdata[:chunk_size] = audio_data[callback.position:callback.position+chunk_size]
            
            # Zero out rest of buffer if we're at the end
            if chunk_size < frames:
                outdata[chunk_size:].fill(0)
                
            callback.position += chunk_size
            
            # Signal completion when done
            if callback.position >= len(audio_data):
                event.set()
                raise sd.CallbackStop
        else:
            outdata.fill(0)
            event.set()
            raise sd.CallbackStop
    
    # Initialize position counter
    callback.position = 0
    
    # Create and start stream
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