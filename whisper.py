import asyncio
import pyaudio
import wave
import keyboard
import os
import dotenv
import aiohttp
from termcolor import colored
from groq import Groq
from openai import OpenAI
from pydub import AudioSegment
from io import BytesIO

dotenv.load_dotenv()

class WhisperTranscriber:
    def __init__(self):
        # self.api_key = os.getenv('GROQ_API_KEY')
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.client = OpenAI(api_key=self.api_key)
        # self.client = Groq(api_key=self.api_key)
        self.frames = []
        # Replace single recording flag with a dictionary of recording flags
        self.recording_states = {
            'scroll_lock': False,
            'f9': False,
            'f7': False,
            'f4': False,
            'f10': False
        }
        self.active_recording = None
        self.audio_interface = pyaudio.PyAudio()
        self.channels = 1
        self.audio_format = pyaudio.paInt16
        self.rate = 16000

    def audio_callback(self, in_data, frame_count, time_info, status):
        self.frames.append(in_data)
        return (in_data, pyaudio.paContinue)

    async def start_recording(self):
        print(f"\n>>>>>>  Listening...  <<<<<<", end='')
        stream = self.audio_interface.open(
            format=self.audio_format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=256,
            stream_callback=self.audio_callback
        )
        stream.start_stream()
        # Check the specific recording state that's currently active
        while self.recording_states.get(self.active_recording, False):
            await asyncio.sleep(0.1)
        stream.stop_stream()
        stream.close()

    def _save_audio_sync(self):
        # Create a BytesIO object to hold the WAV data
        wav_buffer = BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.audio_interface.get_sample_size(self.audio_format))
            wav_file.setframerate(self.rate)
            wav_file.writeframes(b''.join(self.frames))
        wav_buffer.seek(0)

        # Create an AudioSegment from the WAV buffer
        audio_segment = AudioSegment.from_wav(wav_buffer)

        # Export to MP3 in a BytesIO buffer
        mp3_buffer = BytesIO()
        audio_segment.export(mp3_buffer, format="mp3")
        mp3_buffer.seek(0)
        return mp3_buffer

    async def save_audio(self):
        return await asyncio.to_thread(self._save_audio_sync)

    def _transcribe_audio_sync(self, mp3_buffer):
        transcription_response = self.client.audio.transcriptions.create(
            file=("audio.mp3", mp3_buffer),
            # model="whisper-large-v3-turbo",
            model="whisper-1",
            # model="gpt-4o-transcribe",
            # prompt="Bülent, schattenbout, Obsidian, Aşk, Enver"
            
            # language="nl"
        )
        return transcription_response.text

    async def transcribe_audio(self):
        mp3_buffer = await self.save_audio()
        print("\r" + " " * len(f">>>>>>  Listening ({self.active_recording})...  <<<<<<<") + "\r<<<<<<  Transcribing  >>>>>>", end='')
        transcription_text = await asyncio.to_thread(self._transcribe_audio_sync, mp3_buffer)
        return transcription_text

    # Method to set up key handlers that won't interfere with each other
    def setup_key_handlers(self):
        keyboard.on_press_key('scroll lock', lambda _: self._set_recording_state('scroll_lock', True))
        keyboard.on_release_key('scroll lock', lambda _: self._set_recording_state('scroll_lock', False))

        keyboard.on_press_key('f10', lambda _: self._set_recording_state('f10', True))
        keyboard.on_release_key('f10', lambda _: self._set_recording_state('f10', False))
        
        keyboard.on_press_key('f9', lambda _: self._set_recording_state('f9', True))
        keyboard.on_release_key('f9', lambda _: self._set_recording_state('f9', False))

        keyboard.on_press_key('f7', lambda _: self._set_recording_state('f7', True))
        keyboard.on_release_key('f7', lambda _: self._set_recording_state('f7', False))

        keyboard.on_press_key('f4', lambda _: self._set_recording_state('f4', True))
        keyboard.on_release_key('f4', lambda _: self._set_recording_state('f4', False))


    def _set_recording_state(self, key, state):
        # If we're starting a recording and no other recording is active
        if state and self.active_recording is None:
            self.recording_states[key] = True
            self.active_recording = key
        # If we're stopping the active recording
        elif not state and self.active_recording == key:
            self.recording_states[key] = False
            self.active_recording = None

    async def transcript_to_paste(self):
        # I now have Whisper Typing, so I don't need this anymore
        while True:
            print("Transcripting to paste")
            await asyncio.sleep(0.1)

    async def transcript_to_obsidian_agent(self):
        while True:
            if self.recording_states['f4'] and self.active_recording == 'f4':
                self.frames = []
                await self.start_recording()
                # print("Obsidian agent working")
                transcription = await self.transcribe_audio()
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "red"))
                return transcription
            await asyncio.sleep(0.1)

    # async def transcript_and_note_content(self):
    #     while True:
    #         if self.recording_states['f10'] and self.active_recording == 'f10':
    #             self.frames = []
    #             await self.start_recording()
    #             transcription = await self.transcribe_audio()

    #             print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "yellow"))
    #             # Return the transcription for further processing
    #             return transcription
            
    #         await asyncio.sleep(0.1)  # Small delay to prevent high CPU usage

    async def transcript_to_tasks_agent(self):
        while True:
            if self.recording_states['f10'] and self.active_recording == 'f10':
                self.frames = []
                await self.start_recording()
                transcription = await self.transcribe_audio()

                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "green") + "\n")
                # Return the transcription for further processing
                return transcription
            
            await asyncio.sleep(0.1)  # Small delay to prevent high CPU usage                    


    async def idea_event(self):
        # No need to set up keyboard handlers here - they're set up once in setup_key_handlers
        while True:
            if self.recording_states['f9'] and self.active_recording == 'f9':
                self.frames = []
                await self.start_recording()
                transcription = await self.transcribe_audio()
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "yellow"))
                return transcription
            await asyncio.sleep(0.1)

    async def journal_event(self):
        while True:
            if self.recording_states['f7'] and self.active_recording == 'f7':
                self.frames = []
                await self.start_recording()
                transcription = await self.transcribe_audio()
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "blue"))
                return transcription
            await asyncio.sleep(0.1)


    async def start(self):
        # No need to set up keyboard handlers here - they're set up once in setup_key_handlers
        while True:
            if self.recording_states['scroll_lock'] and self.active_recording == 'scroll_lock':
                self.frames = []
                await self.start_recording()
                transcription = await self.transcribe_audio()
                print("\r" + " " * len(">>>>>>  Transcribing  <<<<<<<") + "\r" + colored(transcription, "green"))
                return transcription
            await asyncio.sleep(0.1)

    def __del__(self):
        self.audio_interface.terminate()