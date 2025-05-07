import asyncio
import pyaudio
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

        # Setup key handlers
        self.setup_key_handlers()

    def audio_callback(self, in_data, frame_count, time_info, status):
        """Callback om audioframes direct op te slaan."""
        self.frames.append(in_data)  # Voeg frames direct toe aan de lijst
        return (None, pyaudio.paContinue)

    async def save_audio(self):
        """Sla audio op vanuit de frames."""
        if not self.frames:
            print("⚠️ Geen audioframes om op te slaan.")
            return None

        # Converteer frames naar een audiobestand
        wav_buffer = BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.audio_interface.get_sample_size(self.audio_format))
            wav_file.setframerate(self.rate)
            wav_file.writeframes(b''.join(self.frames))
        wav_buffer.seek(0)
        return wav_buffer

    async def start_recording(self, key):
        """Start de audio-opname."""
        print(f"\n>>>>>>  Listening... <<<<<<", end='')
        self.frames = []  # Reset frames
        stream = self.audio_interface.open(
            format=self.audio_format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=1024,  # Grotere buffer om callbacks te verminderen
            stream_callback=self.audio_callback)
        stream.start_stream()
        await self.recording_finished_events[key].wait()
        await asyncio.sleep(0.2)  # Wacht even om resterende data te verwerken
        stream.stop_stream()
        stream.close()
        self.recording_finished_events[key].clear()

    async def transcribe_audio(self):
        """Transcribeer de opgenomen audio."""
        audio_buffer = await self.save_audio()  
        if not audio_buffer:
            return None

        print("\r" + " " * len(f">>>>>>  Listening...  <<<<<<<") + "\r<<<<<<  Transcribing  >>>>>>", end='')

        try:
            transcription_response = await self.client.audio.transcriptions.create(
                file=("audio.wav", audio_buffer),
                model="whisper-large-v3-turbo")
            return transcription_response.text

        except Exception as e:
            print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + f"\n⚠️ Fout tijdens transcriptie: {type(e).__name__}: {e}")
            return None

    def setup_key_handlers(self):
        """Stel key handlers in voor opname."""
        for key in self.recording_events.keys():
            keyboard.on_press_key(key, lambda _, k=key: self.recording_events[k].set())
            keyboard.on_release_key(key, lambda _, k=key: (
                self.recording_events[k].clear(),
                self.recording_finished_events[k].set()))


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

    def __del__(self):
        self.audio_interface.terminate()