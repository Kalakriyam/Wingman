import asyncio
import pyaudio
import wave
import keyboard
import os
import dotenv
import threading
import queue
from termcolor import colored
from groq import AsyncGroq
from openai import AsyncOpenAI
from groq import PermissionDeniedError
from pydub import AudioSegment
from io import BytesIO

dotenv.load_dotenv()

class WhisperTranscriber:
    def __init__(self):
        self.api_key = os.getenv('GROQ_API_KEY')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.client = AsyncGroq(api_key=self.api_key)
        self.openai_client = AsyncOpenAI(api_key=self.openai_api_key)

        self.audio_interface = pyaudio.PyAudio()
        self.channels = 1
        self.audio_format = pyaudio.paInt16
        self.rate = 16000
        self.frames = []  # Directe opslag van audioframes

        # ✅ Twee events per toets: één voor opname actief, één voor opname klaar
        self.recording_events = {
            'scroll_lock': asyncio.Event(),
            'f4': asyncio.Event(),
            'f7': asyncio.Event(),
            'f9': asyncio.Event(),
            'f10': asyncio.Event()}
        self.recording_finished_events = {
            key: asyncio.Event() for key in self.recording_events}
        # track physical key state so we ignore auto-repeats
        self._key_is_down = {k: False for k in self.recording_events}
        # Setup key handlers
        self.setup_key_handlers()


    async def save_audio(self):
        """Sla audio op vanuit de frames."""
        if not self.frames:
            print("[DEBUG] no frames → nothing to save")
            return None

        wav_buffer = BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.audio_interface.get_sample_size(self.audio_format))
            wav_file.setframerate(self.rate)
            wav_file.writeframes(b"".join(self.frames))
        wav_buffer.seek(0)
        print("[DEBUG] WAV ready, size:", wav_buffer.getbuffer().nbytes, "bytes")
        return wav_buffer

    # ---------- KEY HANDLERS (noise-free) ----------
    def setup_key_handlers(self):
        def _on_press(event_key: str):
            if self._key_is_down[event_key]:
                return                        # ignore repeat downs
            self._key_is_down[event_key] = True
            print(f"[DEBUG] {event_key} ↓  (recording start)")
            self.recording_events[event_key].set()

        def _on_release(event_key: str):
            if not self._key_is_down[event_key]:
                return                        # shouldn’t happen, but guard anyway
            self._key_is_down[event_key] = False
            print(f"[DEBUG] {event_key} ↑  (recording stop)")
            self.recording_events[event_key].clear()
            self.recording_finished_events[event_key].set()

        for key in self.recording_events:
            keyboard.on_press_key(key,  lambda _e, k=key: _on_press(k))
            keyboard.on_release_key(key, lambda _e, k=key: _on_release(k))

    # ---------- AUDIO PIPELINE DEBUG ----------
    def audio_callback(self, in_data, *_):
        # fires every ~64 ms with 1024 frames at 16 kHz
        self.frames.append(in_data)
        if len(self.frames) % 25 == 0:        # print every ~1.6 s
            print(f"\r[DEBUG] frames collected: {len(self.frames)}", end="")
        return (None, pyaudio.paContinue)

    async def start_recording(self, key):
        print("\n>>>>>>  Listening... <<<<<<")
        self.frames = []
        stream = self.audio_interface.open(
            format=self.audio_format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=1024,
            stream_callback=self.audio_callback,
        )
        stream.start_stream()
        print("[DEBUG] audio stream opened")

        await self.recording_finished_events[key].wait()
        await asyncio.sleep(0.2)              # let the callback flush last chunk
        stream.stop_stream()
        stream.close()
        print(f"\n[DEBUG] stream closed, total frames: {len(self.frames)}")
        self.recording_finished_events[key].clear()

    async def transcribe_audio(self):
        wav_buffer = await self.save_audio()
        if not wav_buffer:
            return None

        print("<<<<<<  Transcribing  >>>>>>", end="")
        try:
            response = await self.client.audio.transcriptions.create(
                file=("audio.wav", wav_buffer),    # 👈 use WAV
                model="whisper-large-v3-turbo",
            )
            return response.text
        except Exception as e:
            print(f"\n⚠️  transcription error: {type(e).__name__}: {e}")
            return None
        
        
    # def setup_key_handlers(self):
    #     """Stel key handlers in voor opname."""
    #     for key in self.recording_events.keys():
    #         keyboard.on_press_key(key, lambda _, k=key: self.recording_events[k].set())
    #         keyboard.on_release_key(key, lambda _, k=key: (
    #             self.recording_events[k].clear(),
    #             self.recording_finished_events[k].set()))

    async def start(self):
        """Start de hoofdopname- en transcriptielus."""
        while True:
            await self.recording_events['scroll_lock'].wait()
            await self.start_recording('scroll_lock')
            transcription = await self.transcribe_audio()
            if transcription:
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "green"))
                return transcription
            else:
                print("\n⚠️ Geen transcriptie ontvangen.")


    async def transcript_to_paste(self):
        # I now have Whisper Typing, so I don't need this anymore
        while True:
            print("Transcripting to paste")
            await asyncio.sleep(0.1)

    async def transcript_to_obsidian_agent(self):
        while True:
            await self.recording_events['f4'].wait()
            await self.start_recording('f4')
            transcription = await self.transcribe_audio()
            if transcription:
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "red"))
                return transcription
            else:
                print("\n⚠️ Geen transcriptie ontvangen.")

    async def transcript_to_tasks_agent(self):
        while True:
            await self.recording_events['f10'].wait()
            await self.start_recording('f10')
            transcription = await self.transcribe_audio()
            if transcription:
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "purple"))
                return transcription
            else:
                print("\n⚠️ Geen transcriptie ontvangen.")              

    async def idea_event(self):
        while True:
            await self.recording_events['f9'].wait()
            await self.start_recording('f9')
            transcription = await self.transcribe_audio()
            if transcription:
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "yellow"))
                return transcription
            else:
                print("\n⚠️ Geen transcriptie ontvangen.")

    async def journal_event(self):
        while True:
            await self.recording_events['f7'].wait()
            await self.start_recording('f7')
            transcription = await self.transcribe_audio()
            if transcription:
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "blue"))
                return transcription
            else:
                print("\n⚠️ Geen transcriptie ontvangen.")

    async def start(self):
        while True:
            await self.recording_events['scroll_lock'].wait()
            print("Starting recording")
            await self.start_recording('scroll_lock')
            print("Recording ready")
            transcription = await self.transcribe_audio()
            print("Transcription ready")
            if transcription:
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "green"))
                return transcription
            else:
                print("\n⚠️ Geen transcriptie ontvangen.")

    def __del__(self):
        self.audio_interface.terminate()