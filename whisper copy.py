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
        self.frames = []
        self.frames_lock = threading.Lock()

        # ✅ Twee events per toets: één voor opname actief, één voor opname klaar
        self.recording_events = {
            'scroll_lock': asyncio.Event(),
            'f4': asyncio.Event(),
            'f7': asyncio.Event(),
            'f9': asyncio.Event(),
            'f10': asyncio.Event()
        }
        self.recording_finished_events = {
            key: asyncio.Event() for key in self.recording_events
        }

        self.audio_interface = pyaudio.PyAudio()
        self.channels = 1
        self.audio_format = pyaudio.paInt16
        self.rate = 16000

    def audio_callback(self, in_data, frame_count, time_info, status):   
        with self.frames_lock:
            self.frames.append(in_data)
        return (None, pyaudio.paContinue)

    async def start_recording(self, key):
        print(f"\n>>>>>>  Listening... <<<<<<", end='')
        stream = self.audio_interface.open(
            format=self.audio_format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=256,
            stream_callback=self.audio_callback
        )
        stream.start_stream()
        await self.recording_finished_events[key].wait()
        await asyncio.sleep(0.2)
        stream.stop_stream()
        stream.close()
        self.recording_finished_events[key].clear()

    def _save_audio_sync(self):
        with self.frames_lock:
            frames_copy = list(self.frames)
            self.frames.clear()

        wav_buffer = BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.audio_interface.get_sample_size(self.audio_format))
            wav_file.setframerate(self.rate)
            wav_file.writeframes(b''.join(frames_copy))
        wav_buffer.seek(0)

        audio_segment = AudioSegment.from_wav(wav_buffer)
        mp3_buffer = BytesIO()
        audio_segment.export(mp3_buffer, format="mp3")
        mp3_buffer.seek(0)
        return mp3_buffer

    async def save_audio(self):
        return await asyncio.to_thread(self._save_audio_sync)

    # Changed this method to be fully async, not mixed
    async def transcribe_audio(self):
        mp3_buffer = await self.save_audio()
        print("\r" + " " * len(f">>>>>>  Listening...  <<<<<<<") + "\r<<<<<<  Transcribing  >>>>>>", end='')

        try:
            transcription_response = await self.client.audio.transcriptions.create(
                file=("audio.mp3", mp3_buffer),
                model="whisper-large-v3-turbo"
                # model="whisper-1",
                # model="gpt-4o-transcribe",
                # model="gpt-4o-mini-transcribe"
            )
            return transcription_response.text

        except PermissionDeniedError as e:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + "\n❌ Geen toegang tot Groq spraakherkenning.")
            print("➤ Zet je VPN uit of controleer je netwerkverbinding.")
            # print(f"   [403] {e}")
            return

        except Exception as e:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + f"\n⚠️ Onverwachte fout tijdens transcriiptie: {type(e).__name__}: {e}")
            return

    # ✅ Nieuwe event-driven key handler setup
    def setup_key_handlers(self):
        for key in self.recording_events.keys():
            keyboard.on_press_key(key, lambda _, k=key: self.recording_events[k].set())
            keyboard.on_release_key(key, lambda _, k=key: (
                self.recording_events[k].clear(),
                self.recording_finished_events[k].set()
                ))


    async def transcript_to_paste(self):
        # I now have Whisper Typing, so I don't need this anymore
        while True:
            print("Transcripting to paste")
            await asyncio.sleep(0.1)

    async def transcript_to_obsidian_agent(self):
        while True:
            await self.recording_events['f4'].wait()
            self.frames = []
            await self.start_recording('f4')
            transcription = await self.transcribe_audio()
            if not transcription:
                continue
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "red"))
            return transcription

    async def transcript_to_tasks_agent(self):
        while True:
            await self.recording_events['f10'].wait()
            self.frames = []
            await self.start_recording('f10')
            transcription = await self.transcribe_audio()
            if not transcription:
                continue
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "green") + "\n")
            return transcription                 

    async def idea_event(self):
        while True:
            await self.recording_events['f9'].wait()
            self.frames = []
            await self.start_recording('f9')
            transcription = await self.transcribe_audio()
            if not transcription:
                continue
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "yellow"))
            return transcription

    async def journal_event(self):
        while True:
            await self.recording_events['f7'].wait()
            self.frames = []
            await self.start_recording('f7')
            transcription = await self.transcribe_audio()
            if not transcription:
                continue
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "blue"))
            return transcription

    async def start(self):
        while True:
            await self.recording_events['scroll_lock'].wait()
            self.frames = []
            await self.start_recording('scroll_lock')
            transcription = await self.transcribe_audio()
            if not transcription:
                continue  # niks teruggeven, gewoon wachten op volgende input
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "green"))
            return transcription

    def __del__(self):
        self.audio_interface.terminate()