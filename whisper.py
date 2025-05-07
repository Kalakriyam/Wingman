import asyncio
import sounddevice as sd              # modern, low-latency bindings
import numpy as np                    # sounddevice delivers NumPy blocks
import wave
import keyboard
import os
import dotenv
from termcolor import colored
from groq import AsyncGroq
from openai import AsyncOpenAI
from groq import PermissionDeniedError
from io import BytesIO

dotenv.load_dotenv()

class WhisperTranscriber:
    def __init__(self):
        # print("---- [DEBUG] WhisperTranscriber __init__ called ----") # Add this line
        self.api_key = os.getenv('GROQ_API_KEY')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.client = AsyncGroq(api_key=self.api_key)
        self.openai_client = AsyncOpenAI(api_key=self.openai_api_key)

        self.dtype   = 'int16'                # 16-bit is what Whisper expects
        self.channels = 1
        self.rate     = 16000
        sd.default.samplerate = self.rate     # global defaults → less boiler-plate
        sd.default.channels   = self.channels
        sd.default.latency    = 'low'         # ask PortAudio for interactive latency
        self.frames = []  # Directe opslag van audioframes

        # ✅ Twee events per toets: één voor opname actief, één voor opname klaar
        self.recording_events = {
            'f10': asyncio.Event(),
            'scroll_lock': asyncio.Event(),
            'f4': asyncio.Event(),
            'f7': asyncio.Event(),
            'f9': asyncio.Event(),
            }
        self.recording_finished_events = {
            key: asyncio.Event() for key in self.recording_events}

        # Setup key handlers
        self.setup_key_handlers()

    def audio_callback(self, indata, frames, time, status):
        if status:                        # XRuns/overflows show up here
            print(f"⚠️  SoundDevice status: {status}", flush=True)
        self.frames.append(indata.tobytes())

    async def save_audio(self):
        """Sla audio op vanuit de frames."""
        if not self.frames:
            print("⚠️ Geen audioframes om op te slaan.")
            return None

        # Converteer frames naar een audiobestand
        wav_buffer = BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)              # 16-bit = 2 bytes per sample
            wav_file.setframerate(self.rate)
            wav_file.writeframes(b''.join(self.frames))
        wav_buffer.seek(0)
        return wav_buffer

    async def start_recording(self, key):
        """Start de audio-opname."""
        print(f"\n>>>>>>  Listening... <<<<<<", end='')
        self.frames = []  # Reset frames
        stream = sd.InputStream(
            channels     = self.channels,
            samplerate   = self.rate,
            dtype        = self.dtype,
            blocksize    = 0,        # PortAudio chooses optimal size (lowest latency)
            latency      = 'low',
            callback     = self.audio_callback)
        stream.start()
        await self.recording_finished_events[key].wait()
        await asyncio.sleep(0.2)  # Wacht even om resterende data te verwerken
        stream.stop()
        stream.close()
        self.recording_finished_events[key].clear()

    async def transcribe_audio(self):
        """Transcribeer de opgenomen audio."""
        audio_buffer = await self.save_audio()  
        if not audio_buffer:
            return None

        print("\r" + " " * len(f">>>>>>  Listening...  <<<<<<<") + "\r<<<<<<  Transcribing  >>>>>>", end='')

        try:
            # print("\n[DEBUG] About to call Groq for transcription.")
            transcription_response = await self.client.audio.transcriptions.create(
                file=("audio.wav", audio_buffer),
                model="whisper-large-v3-turbo")
            # print("[DEBUG] Groq call returned successfully.")
            return transcription_response.text
        except asyncio.TimeoutError:
            # print("\n[DEBUG] Groq transcription call timed out.")
            return None
        except Exception as e:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + f"\n⚠️ Fout tijdens transcriptie: {type(e).__name__}: {e}")
            return None

    def setup_key_handlers(self):
        """Stel key handlers in voor opname."""
        for key in self.recording_events.keys():
            keyboard.on_press_key(key, lambda _, k=key: self.recording_events[k].set())
            keyboard.on_release_key(key, lambda _, k=key: (
                self.recording_events[k].clear(),
                self.recording_finished_events[k].set(),
                # print(f"[DEBUG] Key '{k}' released")
            ))


    async def transcript_to_obsidian_agent(self):
        await self.recording_events['f4'].wait()
        await self.start_recording('f4')
        transcription = await self.transcribe_audio()
        if transcription:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "red"))
            return transcription
        else:
            print("\n⚠️ Geen transcriptie ontvangen.")

    async def transcript_to_tasks_agent(self):
            await self.recording_events['f10'].wait()
            await self.start_recording('f10')
            # print("[DEBUG] About to transcribe audio") # You were seeing this before the last Groq debug msg
            
            transcription = await self.transcribe_audio()
            
            # YOUR NEW PRINT STATEMENT:
            # print(f"[DEBUG T2TA] After transcribe_audio: transcription = '{transcription}' (type: {type(transcription)})") 
            
            if transcription:
                # print(f"[DEBUG T2TA] 'if transcription' is TRUE. About to print colored text.") # ADD THIS TOO
                try:
                    # colored_text = colored(transcription, "pink")
                    # print(f"[DEBUG T2TA] colored_text = '{colored_text}' (type: {type(colored_text)})") # AND THIS
                    # print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored_text)
                    print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "magenta"))
                    return transcription
                except Exception as e_color:
                    print(f"[DEBUG T2TA] ERROR during colored print: {e_color}") # AND THIS
                    # Fallback or re-raise, but for now, just return to see if tasks_agent gets it
                    return transcription # or return None if this path is problematic
            else:
                # print(f"[DEBUG T2TA] 'if transcription' is FALSE.") # AND THIS
                print("\n⚠️ Geen transcriptie ontvangen.")
                return None              

    async def idea_event(self):
        await self.recording_events['f9'].wait()
        await self.start_recording('f9')
        transcription = await self.transcribe_audio()
        if transcription:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "yellow"))
            return transcription
        else:
            print("\n⚠️ Geen transcriptie ontvangen.")

    async def journal_event(self):
        await self.recording_events['f7'].wait()
        await self.start_recording('f7')
        transcription = await self.transcribe_audio()
        if transcription:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "blue"))
            return transcription
        else:
            print("\n⚠️ Geen transcriptie ontvangen.")


    async def start(self):
        """Start de hoofdopname- en transcriptielus."""
        await self.recording_events['scroll_lock'].wait()
        await self.start_recording('scroll_lock')
        transcription = await self.transcribe_audio()
        if transcription:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "green"))
            return transcription
        else:
            print("\n⚠️ Geen transcriptie ontvangen.")

    def __del__(self):
        pass  # sounddevice auto-closes streams when they're out of scope