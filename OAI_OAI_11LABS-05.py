# de verbeterde tts_request function werkt in deze versie.
import os
import asyncio
import winloop
import io
import dotenv
import aiohttp
import regex
import aiofiles
import logging
import signal
import json
import sys
import requests
import threading
import keyboard
import uvicorn
import urllib.request
import urllib.parse
import orjson
import tkinter as tk
# import pydantic
# from mcp.server.fastmcp import FastMCP
from aiohttp import TCPConnector, AsyncResolver
from asyncio import to_thread
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from datetime import datetime, timedelta
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
# from pydub.playback import play
from ultimate_playback import play
from openai import AsyncOpenAI
from whisper import WhisperTranscriber
from elevenlabs.client import AsyncElevenLabs
from cerebras.cloud.sdk import AsyncCerebras
from filelock import AsyncFileLock
from collections import defaultdict
from typing import Optional, Any
from enum import Enum

dotenv.load_dotenv()

# logging.basicConfig(level=logging.CRITICAL, format='%(asctime)s - %(levelname)s - %(message)s')


# Add this right after your imports and global definitions
async def initialize_http_session():
    global global_http_session
    
    # Configure optimized TCP connector
    connector = aiohttp.TCPConnector(
        limit=20,              # Up to 20 concurrent connections (matches Elevenlabs limit)
        ttl_dns_cache=300,     # Cache DNS lookups for 5 minutes
        force_close=False,     # Allow connection reuse
        enable_cleanup_closed=True
    )
    
    # Create the session with optimized settings
    global_http_session = aiohttp.ClientSession(
        connector=connector,
        timeout=aiohttp.ClientTimeout(total=20),
        headers={'Accept-Encoding': 'gzip, deflate'}  # Enable compression by default
    )

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
elevenlabs_client = AsyncElevenLabs(api_key=ELEVENLABS_API_KEY)

model_audio = {}  # Will store AudioSegments for each model
audio_order = 0
total_response_time = 0
response_count = 0
request_start_time = 0

tts_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
audio_ready_event = asyncio.Event()
segment_ready_events = defaultdict(lambda: None)
tts_semaphore = asyncio.Semaphore(18)
audio_segments = defaultdict(lambda: None)
numbered_sentences = defaultdict(lambda: None)
midi_commands = defaultdict(lambda: None)
note_received = asyncio.Event()
shutdown_event = asyncio.Event()
text_finalized = asyncio.Event()
tool_finalized = asyncio.Event()
priority_input_event = asyncio.Event()   
record_key_pressed = asyncio.Event()
record_key_released = asyncio.Event()
text_chunk_queue = asyncio.Queue(maxsize=1)
tool_chunk_queue = asyncio.Queue(maxsize=1)
DEFAULT_FADE_MS = 30
DEFAULT_TRIM_MS = 185
# SENTENCE_END_PATTERN = regex.compile(
#     r'(?<=[^\d\s]{2}[.!?])(?= |$)|(?<=[^\n]{2})(?=\n)|(?<=:)(?=\n)'
# )
SENTENCE_END_PATTERN = regex.compile(
    r'(?<=[^\d\s]{2}[.!?])(?=(?![*_])[\s$])|(?<=[^\n]{2})(?=\n)|(?<=:)(?=\n)')


CLEAN_PATTERN = regex.compile(r'(- )|(#)|(\*)')
HAS_ALNUM = regex.compile(r'[a-zA-Z0-9]')




app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Pas dit aan naar jouw behoeften
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class NoteData(BaseModel):
    title: str
    content: str

class DefaultPrompts(BaseModel):
    system_prompt: str = Field(default="system_prompt.txt")
    dynamic_context: str = Field(default="dynamic_context.txt")

class ConversationState(BaseModel):
    system_prompt_file: str = Field(default="system_prompt.txt")
    dynamic_context_file: str = Field(default="dynamic_context.txt")
    messages_list_file: str
    summary: str = Field(default="")
    timestamp: str
    tags: list = Field(default_factory=list)
    links: list = Field(default_factory=list)

class VoiceUpdateRequest(BaseModel):
    voice_id: str
    voice_name: str

class MessageType(Enum):
    EXCHANGE = "exchange"
    TRIGGER = "trigger"
    ACTION_REQUEST = "action_request"
    TOOL_CALL = "tool_call"
    STATUS_UPDATE = "status_update"

class TriggerType(Enum):
    REFRESH_ALL_PROMPTS = "refresh_all_prompts"
    CLEAR_CONTEXT = "clear_context"
    RESTART_AGENT = "restart_agent"
    PULL_CONVERSATION = "pull_conversation"
    PULL_SUMMARY = "pull_summary"
    # Andere directe triggers zonder payload

class ActionType(Enum):
    REFRESH_SPECIFIC_PROMPT = "refresh_specific_prompt"
    UPDATE_PLACEHOLDERS = "update_placeholders"
    PUSH_SUMMARY = "push_summary"
    PUSH_CONVERSATION = "push_conversation"
    CHANGE_VOICE = "change_voice"
    # Complexere acties met payload

class Message(BaseModel):
    sender: str
    recipient: str
    message_type: MessageType
    trigger_type: Optional[TriggerType]
    action_type: Optional[ActionType]
    payload: Optional[dict[str, Any]]
    # timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

@app.post('/update')
async def update_content(note: NoteData):
    if note.title and note.content:
        communication_manager.update_obsidian_content(note.title, note.content)
        # return {"message": f"{note.title} succesvol ontvangen"}
        print (f"'{note.title}' succesvol ontvangen")
    
    else:
        raise HTTPException(status_code=400, detail="Titel of inhoud ontbreekt")


@app.post('/message')
async def handle_message(message: Message):
    if message.action_type:
        return communication_manager.handle_action(message)
    elif message.trigger_type:
        return communication_manager.handle_trigger(message)
    

@app.post('/update_voice')
async def update_voice(request: VoiceUpdateRequest):
    update_voice_id(request.voice_id, request.voice_name)
    await generate_model_audio_segments()
    return {"message": f"Stem bijgewerkt naar {request.voice_name}"}

@app.post('/reload_default_prompts')
async def reload_default_prompts(refresh: DefaultPrompts):
    if refresh.system_prompt and refresh.dynamic_context:
        await prompt_manager.reload_default_prompts(refresh.system_prompt, refresh.dynamic_context)
        print ("Verzoek tot reload succesvol ontvangen")
        return {"message": "Verzoek tot reload succesvol ontvangen"}
        
    else:
        raise HTTPException(status_code=400, detail="Bericht incompleet")

### Settings for elevenlabs
# Frank_Khalid = GJR2IWXAu2geGLDhmrk4
# Bill = pqHfZKP75CvOlQylNhV4
# Brian = nPczCjzI2devNBz1zQrb
# Chris = iP95p4xoKVk53GoZ742B
# Callum = N2lVS1w4EtoT3dr4eOWO
# Daniel = onwK4e9ZLuTAKqWW03F9
# Frank_v6 = gBmKqfIy2w4nae40skKr
# Frank_Christiaan = gFwlAMshRYWaSeoMt2md
# 
# Serena = pMsXgVXv3BLzUgSXRplE
# Anthony = sjwRAsCdMJodJszgJ6Ks
# Thomas = GBv7mTt0atIp3Br8iCZE
# Drew = wgHvco1wiREKN0BdyVx5
# Jessie = t0jbNlBVZ17f02VDIeMI
# Frank_test01 = DGN7GRQJuQ20lU3i8TBQ
# Frank_test02 = K39njLPkay6U5iCJ9JrD
# Hale = dXtC3XhB9GtPusIpNtQx
# Blake = WMGLSY8TISdIWLob6J0s
# George_original = JBFqnCBsd6RMkjVDRZzb
# Nigel = P8SCfGzhQzNMelY60M3w
# Lily = pFZP5JQG7iQjIQuC4Bku
# Kingsley02 = PXqGP2aYBHPegRIzWzOC
# Mark = UgBBYS2sOqTuMpoF3BR0
# W.L. Oxley = gOkFV1JMCt0G0n9xmBwV
# David_conversational = EozfaQ3ZX0esAp1cW5nG
# David_narrator = v9LgF91V36LGgbLX3iHW
# David_storyteller = BNgbHR0DNeZixGQVzloa
# Martin-6 = LlZr3QuzbW4WrPjgATHG
# Martin-aimable = FNOttooGMYDRXmqkQ0Fz
# Martin-profond = wyZnrAs18zdIj8UgFSV8
# Martin-intime = a5n9pJUnAhX4fn7lx3uo

# George = Yko7PKHZNXotIFUBG7I9

VOICE_ID = "Yko7PKHZNXotIFUBG7I9"
# MODEL_ID = "eleven_multilingual_v2"
MODEL_ID = "eleven_flash_v2_5"
model_options = ["chatgpt-4o-latest","gpt-4o-2024-11-20", "gpt-4o-mini", "gpt-4.5-preview"]

current_model_index = 0


async def fetch_elevenlabs_audio(text: str) -> AudioSegment:
    """
    Asynchronously makes a POST to ElevenLabs to synthesize 'text', using a
    semaphore to limit concurrent requests.  Returns a pydub AudioSegment
    (or None on failure).
    """
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    data = {
        "text": text,
        "model_id": MODEL_ID,
    }

    try:
        async with tts_semaphore:  # Acquire the semaphore
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=data) as resp:
                    resp.raise_for_status()  # Raise HTTPError for bad requests
                    audio_data = await resp.read()

                    # Convert raw bytes -> AudioSegment
                    try:
                        return AudioSegment.from_file(io.BytesIO(audio_data), format="mp3")
                    except CouldntDecodeError:
                        print(f"Error: Could not decode audio data for '{text}'.")
                        return None
                    except Exception as e:
                        print(f"Error processing audio for '{text}': {e}")
                        return None

    except aiohttp.ClientError as e:
        print(f"Error during ElevenLabs API request for '{text}': {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

async def generate_model_audio_segments():
    """
    Downloads a short TTS segment for each model name in model_options asynchronously.
    """
    async def load_model_segment(model_name):
        segment = await fetch_elevenlabs_audio(model_name)  # Await the async function directly
        model_audio[model_name] = segment  # No need for try-except here, handled within fetch_elevenlabs_audio

    # Start all tasks in parallel
    tasks = [load_model_segment(m) for m in model_options]
    await asyncio.gather(*tasks)

def update_voice_id(new_voice_id: str, new_name: str):
    global VOICE_ID
    VOICE_ID = new_voice_id
    print(f"Stem bijgewerkt naar: {new_name}")


class RedirectStdoutToGUI:
    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.line_start = "1.0"  # Track the start of the current line

    def write(self, message):
        if '\r' in message:
            # Handle carriage return by deleting current line and writing new content
            parts = message.split('\r')
            
            # Delete the current line
            line_end = self.text_widget.index(f"{self.line_start} lineend")
            self.text_widget.delete(self.line_start, line_end)
            
            # Insert the last part after the carriage return
            self.text_widget.insert(self.line_start, parts[-1])
        else:
            # Regular insertion
            self.text_widget.insert(tk.END, message)
            
            # Update line_start if we're at a new line
            if message.endswith('\n'):
                self.line_start = self.text_widget.index(tk.END + " linestart")
                
        self.text_widget.see(tk.END)

    def flush(self):
        pass

async def gui_loop():
    root = tk.Tk()
    root.title("Conversatie Interface")
    root.overrideredirect(True)  # Removes the title bar
    
    # Get screen dimensions
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    
    # Calculate window dimensions (half width, full height)
    window_width = screen_width // 2
    window_height = screen_height
    
    # Position the window in the right half of the screen
    # Starting from the middle-top (x=screen_width//2, y=0)
    # and extending to the bottom-right corner
    x_position = screen_width // 2
    y_position = 0
    
    # Set the window size and position
    root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
    
    text_output = tk.Text(root, wrap='word', font=("TkDefaultFont", 22), bg='black', fg='white', insertbackground='white')
    text_output.pack(expand=True, fill='both')

    sys.stdout = RedirectStdoutToGUI(text_output)

    print("Welkom Alexander! Onze gedeelde ruimte is nu helder en rustig.")
    print("Alles wat je print verschijnt hier.")

    try:
        while True:
            root.update()
            await asyncio.sleep(0.01)  # korte pauze om andere async taken ruimte te geven
    except tk.TclError:
        print("GUI afgesloten.")


async def first_compound_action():
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    while True:
        user_input = await whisper_transcriber.transcript_and_note_content()
        # Get the current note content from Obsidian
        try:
            # Using the server running on port 5005 as defined in your Obsidian plugin
            # Request to get the current active note content
            payload = {
                "action": "read_current_note",
                "payload": {}
            }
            
            async with global_http_session.post("http://127.0.0.1:5005/process", 
                            json=payload) as response:
                if response.status == 200:
                    print("Successfully requested current note content")
                else:
                    print(f"Failed to request note content: {response.status}")
            
        except Exception as e:
            print(f"Error communicating with Obsidian: {str(e)}")
        
        communication_manager.add_user_message(user_input)
        await note_received.wait()
        communication_manager.process_incoming_message()
        note_received.clear()

        print("\n>>>>>>  Thinking...  <<<<<<", end='')
        response_text = await chat_with_llm(client, communication_manager.get_messages())
        communication_manager.add_assistant_message(response_text)

n8n_tool = {
    "type": "function",
    "function": {
        "name": "n8n_tool",
        "description": "Send user requests regarding calendar, tasks and email, to N8 workflow",
        "parameters": {
            "type": "object",
            "properties": {
                "chatInput": {
                    "type": "string",
                    "description": "The user's message to be processed by the n8n workflow"
                }
            },
            "required": ["chatInput"]
        }
    }
}

perplexity_tool = {
    "type": "function",
    "function": {
        "name": "perplexity_tool",
        "description": "Use this tool when Alexander asks you to search for something on the internet.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_query": {
                    "type": "string",
                    "description": "The query for Perplexity. Longer, conversational style queries give better results. Put Alexander's question here; correct grammar, and add all necessary information like Obsidian notes and previous parts of the conversation."
                }
            },
            "required": ["search_query"]
        }
    }
}

# Tool for basic note operations
obsidian_notes_tool = {
    "type": "function",
    "function": {
        "name": "ObsidianNotesTool",
        "description": "Perform operations on Obsidian notes such as creating, reading, and modifying content",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The note operation to perform",
                    "enum": [
                        "create_note",
                        "replace_current_content",
                        "paste_text",
                        "read_current_note",
                        "open_note"
                    ]
                },
                "payload": {
                    "type": "object",
                    "description": "The payload data for the action",
                    "properties": {
                        "title": {
                            "anyOf": [
                                { "type": "string" },
                                { "type": "null" }
                            ],
                            "description": "The title of the note, required for create_note and open_note (null if not needed)."
                        },
                        "text": {
                            "anyOf": [
                                { "type": "string" },
                                { "type": "null" }
                            ],
                            "description": "The text content to use based on the action: for create_note (new note content), replace_current_content (replacement content), or paste_text (text to insert at cursor position)."
                        }
                    },
                    "additionalProperties": False
                }
            },
            "required": ["action", "payload"],
            "additionalProperties": False
        }
    }
}

# Tool for executing commands
obsidian_command_tool = {
    "type": "function",
    "function": {
        "name": "ObsidianCommandTool",
        "description": "Execute specific commands in Obsidian by their command ID",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform",
                    "enum": ["execute_command"]
                },
                "payload": {
                    "type": "object",
                    "description": "The payload data for the command execution",
                    "properties": {
                        "commandId": {
                            "type": "string",
                            "description": "The Obsidian command ID to execute. Only use specific command IDs that will be provided to you."
                        }
                    },
                }
            },
            "required": ["action", "payload"],
            "additionalProperties": False
        }
    }
}

params_with_tools = {
    "tools": [n8n_tool, perplexity_tool],
    "tool_choice": "auto",
    "max_tokens": 2000,
    "temperature": 0,
    "top_p": 1,
    "stream": True
}

params_no_tools = {
    "max_tokens": 2000,
    "temperature": 0,
    "top_p": 1,
    "stream": True
}




async def tasks_agent():
    """
    Asynchronous coroutine that continuously waits for transcriptions intended
    for the Pydantic tasks agent. It can read and write files, and streams
    text output to the text_chunk_queue.
    """
    global audio_order

    logging.info("\nStarting Tasks Agent event listener...")
    
    tasks_agent_instance = Agent(
        'google-gla:gemini-2.0-flash', # Use your desired model
        system_prompt=("""
# general instructions:
- You are Bülent, Alexander's AI assistant for tasks, groceries, and brainstorming.
- Your job is to read the lists in the files, add items to the files, mark items and tasks as done, and work with the scratchpad.
- Always work step by step as instructed.

Tasks and items are stored in markdown tasks format:
- [ ] clean the sink
- [x] write a blogpost   
                                           
The files you have access to are: 
boodschappen.md (groceries list)
dagtaken.md (for general, daily tasks)
werktaken.md (for work related tasks)
our_scratchpad.md (for brainstorming and collaboration)
                     
# list instructions: 
## Adding items to the list:
1) Alexander will say something like 'zet pizza op mijn boodschappenlijst'
2) You will read the file to see if the item is already in the list
3) if it is, tell Alexander that the item is already in the list
4) if it is not, write **a new line** with the item to the list
5) read the file again to verify your changes
6) if your change didn't work, write the line again

## Modifying items in the list:
1) Alexander will say something like 'verander pietsa in pizza op mijn boodschappenlijst'
2) You will read the file to see if the item ('pietsa') is in the list
3) if it is, write the list again, with the modified item ('pizza')
4) read the file again to verify your changes
5) if your change didn't work, write the updated list to the fileagain

## Marking items as done:
1) Alexander will say something like 'ik heb het bureau opgeruimd'
2) You will read the daily tasks file to see if the item ('bureau opruimen')  in the list
3) If it's not in the daily tasks file, read the work tasks file
4) write the list to the file you found it in, with the item marked as done (use [x])
5) read the file again to verify your changes
6) if your change didn't work, write the updated list to the file again 

The file our_scratchpad.md - your 'kladblok' - is where you and Alexander can write down and exchange ideas, thoughts, questions, etc.
Double check the file after you've written to it, to verify your changes.
                       
# correct evident text errors:
like 'glued together' words:
'huisartsbellenmedicatie' > 'huisarts bellen medicatie'
'brahimbellen' > 'Brahim bellen'

or nonexistent words:
'klapblok' > 'kladblok'
'dagdaken' > 'dagtaken'
                                        
# format of the tasks and items in the files:                   
The tasks and items are stored in markdown tasks format:
- [ ] clean the sink
- [x] write a blogpost
- [ ] trim beard
* But you will answer in simple lists without the markdown formatting.
* Unless explicitly asked, **don't** mention completed tasks in your answers.
                                          
# formatting tasks and items in your answers:
Format your answers like this:

Op je boodschappenlijst staat:
- appel
- peer
                       
Je hebt nog maar één dagtaak over:
- kleding kopen

Ik heb afwasmiddel op je boodschappenlijst gezet. 

# using the scratchpad:
No special formatting required in the file or your answers.
Use the scratchpad to collaborate, write down and exchange ideas, thoughts, questions, etc.                  
"""))
    
    @tasks_agent_instance.tool
    async def read_file(ctx: RunContext[str], file_path: str) -> str: # Make the tool async
        """Reads the content of a .md or .txt file."""
        allowed_files = ["boodschappen.md", "dagtaken.md", "werktaken.md", "our_scratchpad.md"]
        if file_path not in allowed_files:
            return f"Error: Access denied. You can only access {', '.join(allowed_files)}."

        # Use os.path.exists (still sync, but very fast) or try/except below
        if not os.path.exists(file_path):
            try:
                async with aiofiles.open(file_path, 'w', encoding='utf-8') as file:
                    await file.write("") # Create empty file asynchronously
                return "" # Return empty string for a new file
            except Exception as e:
                return f"Error creating file {file_path}: {e}" # Handle creation error

        # Redundant check removed as allowed_files handles it
        # if not file_path.endswith(('.md', '.txt')):
        #     return f"Error: Unsupported file type. Only .txt and .md are allowed."

        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
                # Read the file asynchronously
                return await file.read()
        except FileNotFoundError:
            # Should ideally be caught by os.path.exists, but good failsafe
            return f"Error: File {file_path} does not exist (async read)."
        except Exception as e:
            return f"Error reading file {file_path}: {e}"

    @tasks_agent_instance.tool
    async def write_file(ctx: RunContext[str], file_path: str, content: str) -> str: # Make the tool async
        """Writes content to a .md or .txt file."""
        lock = AsyncFileLock(f"{file_path}.lock")

        allowed_files = ["boodschappen.md", "dagtaken.md", "werktaken.md", "our_scratchpad.md"]
        if file_path not in allowed_files:
            return f"Error: Access denied. You can only access {', '.join(allowed_files)}."

        try:
            async with lock:
                async with aiofiles.open(file_path, 'w', encoding='utf-8') as file:
                    # Write the file asynchronously
                    await file.write(content)
            return f"Content successfully written to {file_path}."
        except Exception as e:
            return f"Error writing to file {file_path}: {e}"

    while True:
        # Wait for transcription using the new method
        user_input = await whisper_transcriber.transcript_to_tasks_agent()
        logging.info(f"TASKS_AGENT: Received transcription: '{user_input}'")
        # print(f"TASKS_AGENT: Received transcription: '{user_input}'")
        if not user_input:
            logging.warning("TASKS_AGENT: Empty transcription received, skipping.")
            continue

        audio_order = 0
        audio_segments.clear()
        numbered_sentences.clear()
        midi_commands.clear()

        print("\r>>>>>> Receiving... <<<<<<", end="")

        try:

            async with tasks_agent_instance.run_stream(user_input) as result:
                async for chunk in result.stream_text(delta=True):
                    if chunk: # Ensure chunk is not empty
                        await text_chunk_queue.put({"type": "text", "content": chunk})

            logging.info("TASKS_AGENT: Finished streaming response.")

        except Exception as e:
            logging.error(f"TASKS_AGENT: Error during PydanticAI run: {e}", exc_info=True)
            # Optionally send an error message to the queue
            await text_chunk_queue.put({"type": "text", "content": f"\n[Agent Error: {e}]"})
        finally:
            print("\r" + " " * 40 + "\r", end="") # Clear the receiving message
            # Signal that this agent's text stream is complete for this turn
            await text_chunk_queue.put({"type": "finalize"})
            logging.debug("TASKS_AGENT: Sent finalize signal to text queue.")

            # Wait for the consumer to acknowledge finalization   
            await text_finalized.wait()
            text_finalized.clear()
            logging.debug("TASKS_AGENT: Text queue consumer finalized.")

def cycle_llm():
    global current_model_index
    current_model_index = (current_model_index + 1) % len(model_options)
    new_model = model_options[current_model_index]

    # See if its AudioSegment is ready yet
    segment = model_audio.get(new_model)
    if segment:
        print(f"Switched LLM to: {new_model}")
        # If ready, play it (blocking, but short)
        play(segment)
    else:
        # If not ready or an error happened, only print
        print(f"Switched LLM to: {new_model}")

keyboard.add_hotkey('ctrl+shift+l', cycle_llm)

async def get_dynamic_context(filename="dynamic_context.txt"):
    summary = communication_manager.get_summary()
    try:
        async with global_http_session.get(
            'http://192.168.178.144:5000/read-file',
            params={'filename': filename}, 
            timeout=2
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    content = data.get('content', '') # use .get for safety
                    
                    # Optional placeholder replacements
                    now = datetime.now()
                    content = content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
                    content = content.replace("{local_time}", now.strftime("%H:%M:%S"))
                    content = content.replace("{summary}", summary)
                    
                    return [
                        {"role": "user", "content": content},
                        {"role": "assistant", "content": "OK!"}
                    ]
                else:
                    logging.warning(f"Dynamic context server error: {response.status} - {await response.text()}") # Use warning, not error yet
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logging.warning(f"Failed to fetch dynamic context from server, trying local file: {e}") # Use warning

    # Fallback to local file if server fetch failed or returned non-200
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, filename)
        async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
            content = await file.read()
            now = datetime.now()
            content = content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
            content = content.replace("{local_time}", now.strftime("%H:%M:%S"))
            content = content.replace("{summary}", summary)
            logging.info("Fetched dynamic context from local file") # Use info or print
            dynamic_context = [
                {"role": "user", "content": content},
                {"role": "assistant", "content": "OK!"}
            ]
            # prompt_manager.set_default_dynamic_context(dynamic_context) # This line is redundant here and can be removed
            # **** FIX: Add the return statement ****
            return dynamic_context
    except IOError as e:
        logging.error(f"Failed to read local dynamic_context file '{filename}': {e}")
        # **** FIX: Return an empty list instead of a string ****
        # This signifies no dynamic context could be loaded, but prevents the TypeError
        return []
    except Exception as e:
        # Catch any other unexpected errors during local file processing
        logging.error(f"Unexpected error processing local dynamic context file '{filename}': {e}")
        return [] # Return empty list on unexpected errors too


def reset_chat_history():
    global audio_order, audio_segments, numbered_sentences, dynamic_context, system_prompt
    audio_order = 0
    audio_segments.clear()
    numbered_sentences.clear()
    empty_messages = []
    communication_manager.set_messages(empty_messages)
    # system_prompt = await get_system_prompt("system_prompt.txt") # gaat niet, want dit is een sync functie
    # dynamic_context = await get_dynamic_context("dynamic_context.txt") # gaat niet, want dit is een sync functie
    print("Chat history reset.")

keyboard.add_hotkey('ctrl+shift+9', reset_chat_history)


def save_conversation_state(system_prompt_file="system_prompt.txt", dynamic_context_file="dynamic_context.txt",
                            summary=""):
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    # Save messages list to events/states folder
    messages_list_file = f"chat_{timestamp}.json"
    states_dir = os.path.join(os.getcwd(), "events/states")
    os.makedirs(states_dir, exist_ok=True)

    messages = communication_manager.get_messages()
    summary = communication_manager.get_summary()

    messages_path = os.path.join(states_dir, messages_list_file)
    with open(messages_path, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)

    # Create ConversationState object
    conversation_state = ConversationState(
        system_prompt_file=system_prompt_file,
        dynamic_context_file=dynamic_context_file,
        messages_list_file=messages_list_file,
        summary=summary,
        timestamp=timestamp,
        tags=[],  # We'll implement tags later
        links=[]  # We'll implement links later
    )

    # Save ConversationState object to events folder
    events_dir = os.path.join(os.getcwd(), "events")
    os.makedirs(events_dir, exist_ok=True)

    # Save with timestamp in filename
    cs_file = f"conversation_state_{timestamp}.json"
    cs_path = os.path.join(events_dir, cs_file)

    with open(cs_path, 'w', encoding='utf-8') as f:
        f.write(conversation_state.model_dump_json(indent=2))

    # Also save to the default location for current state
    current_cs_path = os.path.join(os.getcwd(), "latest_conversation_state.txt")
    with open(current_cs_path, 'w', encoding='utf-8') as f:
        f.write(cs_file)  # Just the filename, not the full JSON

    print(f"Conversation state saved as: {cs_path}")
    print(f"Messages saved as: {messages_path}")

    # Try to save to server as well
    try:
        # Save messages to server
        response = requests.post(
            "http://192.168.178.144:5000/write-file",
            json={"filename": f"events/states/{messages_list_file}",
                  "content": json.dumps(communication_manager.get_messages(), ensure_ascii=False, indent=2)},
            timeout=5
        )

        if response.status_code == 200:
            print(f"Messages saved to server: events/states/{messages_list_file}")
        else:
            print(f"Failed to save messages to server. Status code: {response.status_code}")

        # Save ConversationState to server
        response = requests.post(
            "http://192.168.178.144:5000/write-file",
            json={"filename": f"events/{cs_file}", "content": conversation_state.model_dump_json(indent=2)},
            timeout=5
        )

        if response.status_code == 200:
            print(f"ConversationState saved to server: events/{cs_file}")
        else:
            print(f"Failed to save ConversationState to server. Status code: {response.status_code}")

        # Update current state file on server
        response = requests.post(
            "http://192.168.178.144:5000/write-file",
            json={"filename": "latest_conversation_state.txt", "content": cs_file},
            timeout=5
        )

        if response.status_code == 200:
            print("Current state reference updated on server")
        else:
            print(f"Failed to update current state reference on server. Status code: {response.status_code}")

    except requests.RequestException as e:
        print(f"Error saving to server: {e}")

    return cs_file

# put this after the function definition, because it needs to be defined first
keyboard.add_hotkey('ctrl+shift+o', save_conversation_state)


def use_specific_conversation_state():
    global audio_order

    # Clear audio and sentence queues
    audio_order = 0
    audio_segments.clear()
    numbered_sentences.clear()

    system_prompt = ""
    dynamic_context = []  # Initialize as empty list, not string

    print("Restarting conversation state...")

    # First try to get the configuration from the server
    conversation_state_filename = ""
    try:
        # Try to get the specific conversation_state.txt file from the server root
        response = requests.get(
            "http://192.168.178.144:5000/read-file",
            params={"filename": "specific_conversation_state.txt"},
            timeout=5
        )

        if response.status_code == 200:
            response_data = response.json()
            if "content" in response_data:
                conversation_state_filename = response_data["content"].strip()
                print(f"Found conversation state reference in server config: {conversation_state_filename}")
            else:
                print("Server returned invalid data for config file")
        else:
            print(f"Failed to load config from server. Status code: {response.status_code}")
    except requests.RequestException as e:
        print(f"Error connecting to server for config: {e}")

    # If server config file is not available or empty, fall back to local config
    if not conversation_state_filename:
        print("Falling back to local config file...")
        try:
            local_config = os.path.join(os.getcwd(), "specific_conversation_state.txt")
            if os.path.exists(local_config):
                with open(local_config, 'r', encoding='utf-8') as f:
                    conversation_state_filename = f.read().strip()
                    if conversation_state_filename:
                        print(f"Found conversation state reference in local config: {conversation_state_filename}")
        except Exception as e:
            print(f"Error reading local config file: {e}")
            conversation_state_filename = ""

    # If config file is empty, just clear messages and return
    if not conversation_state_filename:
        print("No specific state requested.  Starting fresh conversation.")
        return

    # Try to load the ConversationState object from server
    conversation_state = None
    server_loaded = False

    try:
        response = requests.get(
            "http://192.168.178.144:5000/read-file",
            params={"filename": f"events/{conversation_state_filename}"},
            timeout=5
        )

        if response.status_code == 200:
            response_data = response.json()
            if "content" in response_data:
                # Parse the JSON into our Pydantic model
                try:
                    conversation_state = ConversationState.model_validate_json(response_data["content"])
                    server_loaded = True
                    print(f"Loaded ConversationState from server: {conversation_state_filename}")
                except Exception as e:
                    print(f"Error parsing ConversationState from server: {e}")
            else:
                print(f"Server returned invalid data for file: {conversation_state_filename}")
        else:
            print(f"Failed to load ConversationState from server. Status code: {response.status_code}")
    except requests.RequestException as e:
        print(f"Error connecting to server for ConversationState: {e}")

    # If server load failed, fallback to local files
    if not server_loaded:
        print("Falling back to local ConversationState file...")
        try:
            local_file = os.path.join(os.getcwd(), "events", conversation_state_filename)
            if os.path.exists(local_file):
                with open(local_file, 'r', encoding='utf-8') as f:
                    try:
                        conversation_state = ConversationState.model_validate_json(f.read())
                        print(f"Loaded ConversationState from local file: {local_file}")
                    except Exception as e:
                        print(f"Error parsing ConversationState from local file: {e}")
                        return
            else:
                print(f"ConversationState file not found locally: {local_file}")
                return
        except Exception as e:
            print(f"Error reading local ConversationState file: {e}")
            return

    # If we have a valid ConversationState, load all required files
    if conversation_state:
        # Print summary if available
        if conversation_state.summary:
            new_summary = conversation_state.summary
            communication_manager.load_summary(new_summary) # Update the instance's summary attribute
            print(f"Conversation summary: {new_summary}")

        # 1. Load the system prompt
        system_prompt_loaded = False
        try:
            response = requests.get(
                "http://192.168.178.144:5000/read-file",
                params={"filename": conversation_state.system_prompt_file},
                timeout=5
            )

            if response.status_code == 200:
                response_data = response.json()
                if "content" in response_data:
                    system_prompt = response_data["content"]
                    system_prompt_loaded = True
                    print(f"Loaded system prompt from server: {conversation_state.system_prompt_file}")
                else:
                    print(f"Server returned invalid data for system prompt file")
            else:
                print(f"Failed to load system prompt from server. Status code: {response.status_code}")
        except requests.RequestException as e:
            print(f"Error connecting to server for system prompt: {e}")

        # If server load failed, fallback to local file
        if not system_prompt_loaded:
            print("Falling back to local system prompt file...")
            try:
                local_path = os.path.join(os.getcwd(), conversation_state.system_prompt_file)
                if os.path.exists(local_path):
                    with open(local_path, 'r', encoding='utf-8') as f:
                        system_prompt = f.read()
                        print(f"Loaded system prompt from local file: {local_path}")
                else:
                    print(f"System prompt file not found locally: {local_path}")
                    system_prompt = ""  # Empty system prompt if file not found
            except Exception as e:
                print(f"Error loading local system prompt file: {e}")
                system_prompt = ""

        # 2. Load the dynamic context
        context_content = ""
        dynamic_context_loaded = False
        try:
            response = requests.get(
                "http://192.168.178.144:5000/read-file",
                params={"filename": conversation_state.dynamic_context_file},
                timeout=5
            )

            if response.status_code == 200:
                response_data = response.json()
                if "content" in response_data:
                    context_content = response_data["content"]
                    dynamic_context_loaded = True
                    print(f"Loaded dynamic context from server: {conversation_state.dynamic_context_file}")
                else:
                    print(f"Server returned invalid data for dynamic context file")
            else:
                print(f"Failed to load dynamic context from server. Status code: {response.status_code}")
        except requests.RequestException as e:
            print(f"Error connecting to server for dynamic context: {e}")

        # If server load failed, fallback to local file
        if not dynamic_context_loaded:
            print("Falling back to local dynamic context file...")
            try:
                local_path = os.path.join(os.getcwd(), conversation_state.dynamic_context_file)
                if os.path.exists(local_path):
                    with open(local_path, 'r', encoding='utf-8') as f:
                        context_content = f.read()
                        print(f"Loaded dynamic context from local file: {local_path}")
                else:
                    print(f"Dynamic context file not found locally: {local_path}")
                    context_content = ""  # Empty dynamic context if file not found
            except Exception as e:
                print(f"Error loading local dynamic context file: {e}")
                context_content = ""

        # 3. Load the messages
        messages_loaded = False
        try:
            # Corrected params for the request to the 'states' endpoint
            response = requests.get(
                "http://192.168.178.144:5000/read-file",
                params={"filename": f"events/states/{conversation_state.messages_list_file}"},
                timeout=5
            )
            if response.status_code == 200:
                response_data = response.json()
                if "content" in response_data:
                    new_messages = json.loads(response_data["content"])
                    communication_manager.set_messages(new_messages)

                    messages_loaded = True
                    print(f"Loaded messages from server: {conversation_state.messages_list_file}")
                else:
                    print(f"Server returned invalid data for messages file")
            else:
                print(f"Failed to load messages from server. Status code: {response.status_code}")
        except requests.RequestException as e:
            print(f"Error connecting to server for messages: {e}")

        # If server load failed, fallback to local files
        if not messages_loaded:
            print("Falling back to local messages file...")
            try:
                local_dir = os.path.join(os.getcwd(), "events/states")
                file_path = os.path.join(local_dir, conversation_state.messages_list_file)

                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        new_messages = json.loads(f.read())
                        communication_manager.set_messages(new_messages)
                        print(f"Loaded messages from local file: {file_path}")
                else:
                    print(f"Messages file not found locally: {file_path}")
                    empty_messages = []  # Start with empty messages if file not found
                    communication_manager.set_messages(empty_messages)
            except Exception as e:
                print(f"Error loading local messages file: {e}")
                empty_messages = []  # Ensure messages is reset if loading fails
                communication_manager.set_messages(empty_messages)
        # Replace placeholders in system prompt and dynamic context content
        now = datetime.now()

        # Replace date and time placeholders in system prompt
        if system_prompt:
            system_prompt = system_prompt.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
            system_prompt = system_prompt.replace("{local_time}", now.strftime("%H:%M:%S"))
            prompt_manager.set_default_system_prompt(system_prompt)

        # Replace date and time placeholders in dynamic context
        if context_content:
            context_content = context_content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
            context_content = context_content.replace("{local_time}", now.strftime("%H:%M:%S"))
            context_content = context_content.replace("{summary}", communication_manager.get_summary())

            # Convert context_content to the expected format for dynamic_context
            dynamic_context = [
                {"role": "user", "content": context_content},
                {"role": "assistant", "content": "OK!"}
            ]
            prompt_manager.set_default_dynamic_context(dynamic_context)

    else:
        print("Failed to load ConversationState. Starting fresh conversation.")
        new_messages = []
        communication_manager.set_messages(new_messages)
        system_prompt = ""
        dynamic_context = []  # Initialize as empty list

# Register the hotkey
keyboard.add_hotkey('ctrl+shift+0', use_specific_conversation_state)


def load_latest_conversation_state():
    global audio_order

    # Clear audio and sentence queues
    audio_order = 0
    audio_segments.clear()
    numbered_sentences.clear()

    # initialize variables
    system_prompt = ""
    dynamic_context = []  # Initialize as empty list, not string

    print("Loading latest conversation state...")

    # Try to load the ConversationState object from server
    conversation_state = None
    server_loaded = False

    try:
        # Get the latest conversation state filename
        response = requests.get(
            "http://192.168.178.144:5000/read-file",
            params={"filename": "latest_conversation_state.txt"},
            timeout=5
        )
        if response.status_code == 200:
            response_data = response.json()
            if "content" in response_data:
                conversation_state_filename = response_data["content"].strip()
                # Load the actual conversation state object
                response = requests.get(
                    "http://192.168.178.144:5000/read-file",
                    params={"filename": f"events/{conversation_state_filename}"},
                    timeout=5
                )
                if response.status_code == 200:
                    response_data = response.json()
                    if "content" in response_data:
                        conversation_state = ConversationState.model_validate_json(response_data["content"])
                        server_loaded = True
                        print(f"Loaded ConversationState from server: {conversation_state_filename}")
                    else:
                        print("Server returned invalid data for ConversationState file")
                else:
                    print(f"Failed to load ConversationState from server. Status code: {response.status_code}")

            else:
                print("Server returned invalid data for latest_conversation_state.txt")
        else:
            print(f"Failed to load latest conversation state filename from server. Status code: {response.status_code}")
    except requests.RequestException as e:
        print(f"Error connecting to server: {e}")

        # If server load failed, fallback to local files
    if not server_loaded:
        print("Falling back to local files...")
        try:
            # First try to find the latest ConversationState file
            local_cs_file_path = os.path.join(os.getcwd(), "latest_conversation_state.txt")

            if os.path.exists(local_cs_file_path):
                with open(local_cs_file_path, 'r', encoding='utf-8') as f:
                    conversation_state_filename = f.read().strip()

                events_dir = os.path.join(os.getcwd(), "events")
                file_path = os.path.join(events_dir, conversation_state_filename)

                with open(file_path, 'r', encoding='utf-8') as f:
                    conversation_state = ConversationState.model_validate_json(f.read())
                    print(f"Loaded latest ConversationState from local file: {file_path}")
            else:
                print("No local latest_conversation_state.txt found. Starting fresh.")
                return

        except Exception as e:
            print(f"Error loading local conversation state: {e}")
            return  # Exit if there is an error


    # If we have a valid ConversationState, load all required files (same logic as in use_specific_conversation_state)
    if conversation_state:
        # Print summary if available
        if conversation_state.summary:
            new_summary = conversation_state.summary
            communication_manager.load_summary(new_summary) # Update the instance's summary attribute
            print(f"Conversation summary: {new_summary}")

        # 1. Load the system prompt
        system_prompt_loaded = False
        try:
            response = requests.get(
                "http://192.168.178.144:5000/read-file",
                params={"filename": conversation_state.system_prompt_file},
                timeout=5
            )

            if response.status_code == 200:
                response_data = response.json()
                if "content" in response_data:
                    system_prompt = response_data["content"]
                    system_prompt_loaded = True
                    print(f"Loaded system prompt from server: {conversation_state.system_prompt_file}")
                else:
                    print(f"Server returned invalid data for system prompt file")
            else:
                print(f"Failed to load system prompt from server. Status code: {response.status_code}")
        except requests.RequestException as e:
            print(f"Error connecting to server for system prompt: {e}")

        # If server load failed, fallback to local file
        if not system_prompt_loaded:
            print("Falling back to local system prompt file...")
            try:
                local_path = os.path.join(os.getcwd(), conversation_state.system_prompt_file)
                if os.path.exists(local_path):
                    with open(local_path, 'r', encoding='utf-8') as f:
                        system_prompt = f.read()
                        print(f"Loaded system prompt from local file: {local_path}")
                else:
                    print(f"System prompt file not found locally: {local_path}")
                    system_prompt = ""  # Empty system prompt if file not found
            except Exception as e:
                print(f"Error loading local system prompt file: {e}")
                system_prompt = ""

        # 2. Load the dynamic context
        context_content = ""
        dynamic_context_loaded = False
        try:
            response = requests.get(
                "http://192.168.178.144:5000/read-file",
                params={"filename": conversation_state.dynamic_context_file},
                timeout=5
            )

            if response.status_code == 200:
                response_data = response.json()
                if "content" in response_data:
                    context_content = response_data["content"]
                    dynamic_context_loaded = True
                    print(f"Loaded dynamic context from server: {conversation_state.dynamic_context_file}")
                else:
                    print(f"Server returned invalid data for dynamic context file")
            else:
                print(f"Failed to load dynamic context from server. Status code: {response.status_code}")
        except requests.RequestException as e:
            print(f"Error connecting to server for dynamic context: {e}")

        # If server load failed, fallback to local file
        if not dynamic_context_loaded:
            print("Falling back to local dynamic context file...")
            try:
                local_path = os.path.join(os.getcwd(), conversation_state.dynamic_context_file)
                if os.path.exists(local_path):
                    with open(local_path, 'r', encoding='utf-8') as f:
                        context_content = f.read()
                        print(f"Loaded dynamic context from local file: {local_path}")
                else:
                    print(f"Dynamic context file not found locally: {local_path}")
                    context_content = ""  # Empty dynamic context if file not found
            except Exception as e:
                print(f"Error loading local dynamic context file: {e}")
                context_content = ""

        # 3. Load the messages
        messages_loaded = False
        try:
             # Corrected params for the request to the 'states' endpoint
            response = requests.get(
                "http://192.168.178.144:5000/read-file",
                params={"filename": f"events/states/{conversation_state.messages_list_file}"},
                timeout=5
            )
            if response.status_code == 200:
                response_data = response.json()
                if "content" in response_data:
                    new_messages = json.loads(response_data["content"])
                    communication_manager.set_messages(new_messages)
                    messages_loaded = True
                    print(f"Loaded messages from server: {conversation_state.messages_list_file}")
                else:
                    print(f"Server returned invalid data for messages file")
            else:
                print(f"Failed to load messages from server. Status code: {response.status_code}")

        except requests.RequestException as e:
            print(f"Error connecting to server for messages: {e}")

        # If server load failed, fallback to local files
        if not messages_loaded:
            print("Falling back to local messages file...")
            try:
                local_dir = os.path.join(os.getcwd(), "events/states")
                file_path = os.path.join(local_dir, conversation_state.messages_list_file)

                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8') as f:
                        new_messages = json.loads(f.read())
                        communication_manager.set_messages(new_messages)
                        print(f"Loaded messages from local file: {file_path}")
                else:
                    print(f"Messages file not found locally: {file_path}")
                    empty_messages = []  # Start with empty messages if file not found
                    communication_manager.set_messages(empty_messages)
            except Exception as e:
                print(f"Error loading local messages file: {e}")
                empty_messages = []  # Ensure messages is reset if loading fails
                communication_manager.set_messages(empty_messages)

        # Replace placeholders in system prompt and dynamic context content (same as before)
        now = datetime.now()
        if system_prompt:
            system_prompt = system_prompt.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
            system_prompt = system_prompt.replace("{local_time}", now.strftime("%H:%M:%S"))
            prompt_manager.set_default_system_prompt(system_prompt)
        if context_content:
            context_content = context_content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
            context_content = context_content.replace("{local_time}", now.strftime("%H:%M:%S"))
            print("timestamp replaced")
            context_content = context_content.replace("{summary}", communication_manager.get_summary())
            dynamic_context = [
                {"role": "user", "content": context_content},
                {"role": "assistant", "content": "OK!"}
            ]
            prompt_manager.set_default_dynamic_context(dynamic_context)

    else:
        print("Failed to load ConversationState. Starting fresh conversation.")
        new_messages = []
        communication_manager.set_messages(new_messages)
        system_prompt = ""
        dynamic_context = []

keyboard.add_hotkey('ctrl+shift+r', load_latest_conversation_state)


async def save_idea_event():
    """
    Asynchronous coroutine that continuously waits for transcriptions from idea events (F9 key),
    and saves each transcription as an idea event to Obsidian in markdown format and to 
    the private server (or locally as fallback) in JSON format.
    """
    global global_http_session
    logging.info("\nStarting idea event listener...")
    
    while True:
        # Wait for transcription using idea_event method
        user_input = await whisper_transcriber.idea_event()
        logging.info(f"Received idea event transcription")
        
        if not user_input:
            logging.error("Empty transcription received, skipping idea save")
            continue
        
        # Generate a timestamp for the event ID
        timestamp_id = datetime.now().strftime("%Y%m%d%H%M%S")
        # Create a prettier timestamp for display
        pretty_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Create the event data with transcription as content (for JSON storage)
        event_data = {
            "event_id": timestamp_id,
            "type": "idea",
            "source": {"content": user_input}
        }
        
        # Convert to JSON for server storage
        event_json = json.dumps(event_data, indent=2, ensure_ascii=False)
        
        # Create the filename that will be used on the server
        server_filename = f"idea_{timestamp_id}.json"
        
        # Create the markdown content for Obsidian
        obsidian_markdown = f"""#idee

link:: {server_filename}

{pretty_timestamp}

{user_input}
"""
        
        # 1. Save to Obsidian with markdown format
        obsidian_title = f"Inbox/idea_{timestamp_id}"
        obsidian_data = {
            "action": "create_note",
            "payload": {
                "title": obsidian_title,
                "text": obsidian_markdown  # Changed from 'content' to 'text' to match plugin
            }
        }
        
        try:
            async with global_http_session.post(
                "http://127.0.0.1:5005/process",
                json=obsidian_data,
                headers={'Content-Type': 'application/json'},
                timeout=5
            ) as response:
                if response.status == 200:
                    logging.info(f"Idea saved to Obsidian: {obsidian_title}")
                else:
                    logging.error(f"Failed to save idea to Obsidian. Status code: {response.status}")
        except Exception as e:
            logging.error(f"Error saving idea to Obsidian: {e}")
        
        # 2. Try to save JSON via API to server
        server_filepath = f"events/{server_filename}"
        server_data = {
            'filename': server_filepath,
            'content': event_json
        }
        
        server_saved = False
        try:
            async with global_http_session.post(
                "http://192.168.178.144:5000/write-file", 
                json=server_data, 
                timeout=5
            ) as response:
                if response.status == 200:
                    logging.info(f"Idea saved to server: {server_filepath}")
                    server_saved = True
                else:
                    logging.error(f"Failed to save idea to server. Status code: {response.status}")
        except Exception as e:
            logging.error(f"Error saving idea to server: {e}")
        
        # 3. Fallback: Save locally if server save failed
        if not server_saved:
            try:
                local_dir = os.path.join(os.getcwd(), "events")
                os.makedirs(local_dir, exist_ok=True)  # Ensure the directory exists
                local_path = os.path.join(local_dir, server_filename)
                
                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(event_json)
                logging.info(f"Idea saved locally: {local_path}")
            except IOError as e:
                logging.error(f"Error saving idea locally: {e}")

async def save_journal_event():
    """
    Asynchronous coroutine that continuously waits for transcriptions from journal events (F7 key),
    and saves each transcription as a new journal entry to Obsidian in markdown format and to 
    the private server (or locally as fallback) in JSON format.
    """
    global global_http_session
    logging.info("\nStarting journal event listener...")
    
    while True:
        # Wait for transcription using journal_event method
        user_input = await whisper_transcriber.journal_event()
        logging.info(f"Received journal event transcription")
        
        if not user_input:
            logging.error("Empty transcription received, skipping journal save")
            continue
        
        # Generate a timestamp for the event ID
        timestamp_id = datetime.now().strftime("%Y%m%d%H%M%S")
        # Create a prettier timestamp for display
        pretty_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Create the event data with transcription as content (for JSON storage)
        event_data = {
            "event_id": timestamp_id,
            "type": "journal",
            "source": {"content": user_input}
        }
        
        # Convert to JSON for server storage
        event_json = json.dumps(event_data, indent=2, ensure_ascii=False)
        
        # Create the filename that will be used on the server
        server_filename = f"journal_{timestamp_id}.json"
        
        # Create the markdown content for Obsidian
        obsidian_markdown = f"""#journal

link:: {server_filename}

{pretty_timestamp}

{user_input}
"""
        
        # 1. Save to Obsidian with markdown format
        obsidian_title = f"Inbox/journal_{timestamp_id}"
        obsidian_data = {
            "action": "create_note",
            "payload": {
                "title": obsidian_title,
                "text": obsidian_markdown  # Changed from 'content' to 'text' to match plugin
            }
        }
        
        try:
            async with global_http_session.post(
                "http://127.0.0.1:5005/process",
                json=obsidian_data,
                headers={'Content-Type': 'application/json'},
                timeout=5
            ) as response:
                if response.status == 200:
                    logging.info(f"Journal event saved to Obsidian: {obsidian_title}")
                else:
                    logging.error(f"Failed to save journal event to Obsidian. Status code: {response.status}")
        except Exception as e:
            logging.error(f"Error saving journal event to Obsidian: {e}")
        
        # 2. Try to save JSON via API to server
        server_filepath = f"events/{server_filename}"
        server_data = {
            'filename': server_filepath,
            'content': event_json
        }
        
        server_saved = False
        try:
            async with global_http_session.post(
                "http://192.168.178.144:5000/write-file", 
                json=server_data, 
                timeout=5
            ) as response:
                if response.status == 200:
                    logging.info(f"Journal event saved to server: {server_filepath}")
                    server_saved = True
                else:
                    logging.error(f"Failed to save journal event to server. Status code: {response.status}")
        except Exception as e:
            logging.error(f"Error saving journal event to server: {e}")
        
        # 3. Fallback: Save locally if server save failed
        if not server_saved:
            try:
                local_dir = os.path.join(os.getcwd(), "events")
                os.makedirs(local_dir, exist_ok=True)  # Ensure the directory exists
                local_path = os.path.join(local_dir, server_filename)
                
                with open(local_path, 'w', encoding='utf-8') as f:
                    f.write(event_json)
                logging.info(f"Journal event saved locally: {local_path}")
            except IOError as e:
                logging.error(f"Error saving journal event locally: {e}")

async def perplexity_request(llm_request):
    global audio_order
    audio_order = 0
    audio_segments.clear()
    numbered_sentences.clear()

    SYSTEM_PROMPT = (
        "You are an artificial intelligence assistant and you need to engage in a helpful, polite conversation with a user. \n"
        "The information density should be 'to the point' and not too detailed.\n"
        "After collecting your search results, limit the answer to 3 events/topics or if necessary a maximum of 5. \n"
        "Unless the user asks for detailed information or tables, compress your answer without losing essential meaning.\n"
        "Remove the reference numbers like '[1],[4]' from the answer.\n"
        "Finally, translate your answer to the same language as the user's question."
    )
    
    px_client = AsyncOpenAI(api_key=PERPLEXITY_API_KEY, base_url="https://api.perplexity.ai")
    
    perplexity_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": llm_request}
    ]

    perplexity_response = await px_client.chat.completions.create(
        model="sonar",
        messages=perplexity_messages,
        stream=True
    )

    try:
        chunks = perplexity_response.__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(chunks.__anext__(), timeout=20)
                delta = chunk.choices[0].delta

                # Push text chunks to the universal queue
                if delta.content:
                    await text_chunk_queue.put({
                        "type": "text",
                        "content": delta.content
                    })
                    

            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                break
    finally:
        await text_chunk_queue.put({"type": "finalize"})

    # logging.debug("Completed receiving perplexity response.")
    full_response = "".join(numbered_sentences[i] for i in sorted(numbered_sentences.keys()))
    return full_response

async def get_system_prompt(filename):

    # Step 2: Fetch the Context
    system_prompt_content = ""
    try:
        async with global_http_session.get(
            'http://192.168.178.144:5000/read-file',
            params={'filename': filename},
            timeout=2
        ) as response:
                if response.status == 200:
                    data = await response.json()
                    # logging.info(f"Context fetched from server: {data}")
                    system_prompt_content = data.get('content', "")
                else:
                    logging.warning(f"Context server error: {await response.text()}")
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logging.error(f"Failed to fetch context from server: {e}")
    
    # If fetching from server failed, try reading from local file
    if not system_prompt_content:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            system_prompt_path = os.path.join(script_dir, filename)
            async with aiofiles.open(system_prompt_path, 'r', encoding='utf-8') as file:
                system_prompt_content = await file.read()
                # logging.info("Context fetched from local file.")
        except IOError as e:
            logging.error(f"Failed to read local system prompt file: {e}")
            return "Failed to retrieve system prompt from both server and local file."

    # Step 3: Replace Placeholders
    try:
        # Replace date and time placeholders
        now = datetime.now()
        system_prompt_content = system_prompt_content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
        system_prompt_content = system_prompt_content.replace("{local_time}", now.strftime("%H:%M:%S"))
        
        return system_prompt_content
    
    except Exception as e:
        logging.error(f"Error processing {filename} content: {e}")
        return f"Failed to process {filename} content."
    
async def initialize():
    global audio_order
    audio_order = 0

    print("\r>>>>>>  Initializing...  <<<<<<", end='\r', flush=True)
    
    # Start playing the initialization sound in a separate task
    script_dir = os.path.dirname(os.path.abspath(__file__))
    init_audio_path = os.path.join(script_dir, 'INITIALIZING.mp3')
    first_audio = AudioSegment.from_mp3(init_audio_path)
    second_audio = AudioSegment.from_mp3(init_audio_path)
    
    # Prepare and start the TTS request for the welcome sentence
    sentence_order = 0
    welcome_sentence = "Hallo Alexander, waar wil je mee beginnen?"
    numbered_sentences[sentence_order] = welcome_sentence
    
    init_sound_task = asyncio.create_task(asyncio.to_thread(play, first_audio))
    # Ensure the initialization sound has finished playing
    await init_sound_task
    # Start the TTS request and wait for it to complete
    segment_ready_events[sentence_order] = asyncio.Event()
    asyncio.create_task(tts_request(welcome_sentence, sentence_order))
    
    # logging.info("Initialization complete.")

def split_into_sentences(text):
    """
    Splits the given text into sentences using regex.
    This can be replaced with more sophisticated methods if needed.
    """
    sentence_endings = regex.compile(
        r'(?<=[^\d\s]{2}[.!?])(?= |$)|(?<=[^\n]{2})(?=\n)|(?<=:)(?=\n)'
    )
    sentences = sentence_endings.split(text)
    return sentences

# async def tts_request(sentence, order):
#     try:
#         response = await tts_client.audio.speech.create(
#             # model="gpt-4o-mini-tts",
#             model="tts-1", 
#             voice="echo", 
#             input=sentence
#             ) 
#         audio = await to_thread(AudioSegment.from_file, io.BytesIO(response.content), codec="mp3")

#         audio_segments[order] = audio
#         if order == 0:
#             audio_ready_event.set()

#     except Exception as e:
#         print(f"Error in TTS requestfor sentence {order}: {e}")

async def tts_request(sentence, order):
    try:
        async with tts_semaphore:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
            headers = {
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip"  # Enable compression for faster transfers
            }
            
            # Base request data
            data = {
                "text": sentence,
                "model_id": MODEL_ID
            }

            # More efficient collection of previous context
            previous_sentences = []
            for i in range(1, 5):  # Check up to 4 sentences
                if order >= i:
                    prev_sentence = numbered_sentences.get(order - i)
                    if prev_sentence is not None and audio_segments.get(order - i) != "EMPTYLINE":
                        previous_sentences.append(prev_sentence)
                        if len(previous_sentences) == 2:  # Two 'non-None' sentences are enough
                            break

            if previous_sentences:
                data["previous_text"] = " ".join(previous_sentences[::-1])  # Reverse to maintain original order

            # More efficient collection of next context
            next_sentences = []
            for i in range(1, 5):  # Check up to 4 sentences
                next_sentence = numbered_sentences.get(order + i)
                if next_sentence is not None and audio_segments.get(order + i) != "EMPTYLINE":
                    next_sentences.append(next_sentence)
                    if len(next_sentences) == 2:
                        break

            if next_sentences:
                data["next_text"] = " ".join(next_sentences)

            # Encode data using orjson and pass as bytes to 'data' parameter
            json_payload = orjson.dumps(data)
            
            # Use the global session with performance optimizations
            async with global_http_session.post(
                url, 
                headers=headers, 
                data=json_payload,
                timeout=15  # Add explicit timeout to prevent hanging requests
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    print(f"ElevenLabs API error: Status {response.status}, Response: {error_text}")
                    raise Exception(f"ElevenLabs API returned status {response.status}")

                # More efficient audio data collection with larger chunks
                audio_data = b''
                async for chunk in response.content.iter_chunked(8192):  # Larger chunks for better performance
                    if chunk:
                        audio_data += chunk

                # Process audio in a non-blocking way
                audio = await asyncio.to_thread(AudioSegment.from_file, io.BytesIO(audio_data), format="mp3")

                # Delete the last DEFAULT_FADE_MS milliseconds and add fade-out
                if DEFAULT_TRIM_MS > 0 and len(audio) > DEFAULT_TRIM_MS:
                    trimmed_audio = audio[:-DEFAULT_TRIM_MS]
                    audio = trimmed_audio.fade_out(DEFAULT_FADE_MS)
                
                audio_segments[order] = audio
                
                # Set events to signal completion
                if order == 0:
                    audio_ready_event.set()
                # segment_ready_events[order].set()
                    
    except Exception as e:
        print(f"TTS API error for sentence {order} ({sentence}): {e}")
        # Make sure we don't block the audio playback queue by setting the event even on error
        # if order in segment_ready_events:
        #     segment_ready_events[order].set()

async def manage_audio_playback():
    global audio_order
    await audio_ready_event.wait()
    audio_ready_event.clear()
    
    while True:
        while audio_segments.get(audio_order) is not None:
            content = audio_segments[audio_order]

            if content == "MIDI_COMMAND":
                # Process MIDI command
                midi_command = midi_commands[audio_order]
                await process_midi_command(midi_command)
            elif content == "EMPTYLINE":
                print(f"\r{numbered_sentences[audio_order]}")
            else:
                # Process regular audio
                if audio_order == 0:
                    print(f"\r" + f" "*len(">>>>>>  Receiving...  <<<<<<<") + f"\r{numbered_sentences[audio_order]}")
                
                else:
                    sentence = numbered_sentences[audio_order]
                    nospace = sentence[1:] if sentence.startswith(" ") else sentence
                    nonewline = nospace[1:] if nospace.startswith("\n") else nospace
                    
                    print (nonewline)
                    
                await asyncio.to_thread(play, content)
            
            audio_order += 1

        await asyncio.sleep(0.8)

async def process_midi_as_audio(midi_command, order):
    # Create a special marker in audio_segments to maintain ordering
    audio_segments[order] = "MIDI_COMMAND"
    # Store the actual command for processing during playback
    midi_commands[order] = midi_command
    if order == 0:
        audio_ready_event.set()

async def process_empty_sentence(order):
    # Mark this order as a EMPTYLINE.
    audio_segments[order] = "EMPTYLINE"
    # (Optionally, log that an empty sentence was encountered.)
    # logging.debug(f"Order {order} flagged as EMPTYLINE.")

async def text_processor():
    text_buffer = ""
    sentence_order = 0

    async def handle_text_chunk(text_content):
        nonlocal text_buffer, sentence_order
        # Add the new chunk to the buffer
        text_buffer += text_content
        
        # Process any complete MIDI commands first
        await extract_and_handle_midi_commands()
        
        # Now check for complete sentences
        match = SENTENCE_END_PATTERN.search(text_buffer)
        while match:
            # Extract the sentence
            sentence = text_buffer[:match.end()]
            text_buffer = text_buffer[match.end():]

            # Clean the sentence for TTS
            clean_sentence = CLEAN_PATTERN.sub(lambda m: "'" if m.group(0) == "*" else "", sentence).strip()
            
            # Store the original sentence
            numbered_sentences[sentence_order] = sentence.strip() if not HAS_ALNUM.search(sentence) else sentence
            segment_ready_events[sentence_order] = asyncio.Event()
            
            # Process the sentence immediately - don't batch or delay
            if not HAS_ALNUM.search(sentence):
                # Empty line or non-alphanumeric
                asyncio.create_task(process_empty_sentence(sentence_order))
            else:
                # Regular sentence - send for TTS
                asyncio.create_task(tts_request(clean_sentence, sentence_order))
                
                # Special handling for first sentence (order 0)
                if sentence_order == 0:
                    # Look ahead for context
                    numbered_sentences[sentence_order+1] = text_buffer
            
            # Move to next sentence
            sentence_order += 1
            
            # Check for more sentences
            match = SENTENCE_END_PATTERN.search(text_buffer)

    async def finalize_text_buffer():
        nonlocal text_buffer, sentence_order
        if text_buffer.strip():
            # Process any remaining text in the buffer
            numbered_sentences[sentence_order] = text_buffer
            clean_sentence = CLEAN_PATTERN.sub(lambda m: "'" if m.group(0) == "*" else "", text_buffer).strip()
            
            if not HAS_ALNUM.search(text_buffer):
                # If sentence starts with newline, trim it
                numbered_sentences[sentence_order] = (
                    numbered_sentences[sentence_order][1:]
                    if numbered_sentences[sentence_order].startswith("\n")
                    else numbered_sentences[sentence_order]
                )
                segment_ready_events[sentence_order] = asyncio.Event()
                asyncio.create_task(process_empty_sentence(sentence_order))
            else:
                segment_ready_events[sentence_order] = asyncio.Event()
                asyncio.create_task(tts_request(clean_sentence, sentence_order))
            sentence_order += 1
        text_buffer = ""

    async def extract_and_handle_midi_commands():
        nonlocal text_buffer, sentence_order
        while '[SYSTEM]' in text_buffer and '[/SYSTEM]' in text_buffer:
            start_idx = text_buffer.find('[SYSTEM]')
            end_idx = text_buffer.find('[/SYSTEM]') + len('[/SYSTEM]')
            pre_text = text_buffer[:start_idx]
            
            # Process any text before the MIDI command
            if pre_text:
                numbered_sentences[sentence_order] = pre_text
                clean_text = CLEAN_PATTERN.sub(lambda m: "'" if m.group(0) == "*" else "", pre_text).strip()
                segment_ready_events[sentence_order] = asyncio.Event()
                asyncio.create_task(tts_request(clean_text, sentence_order))
                sentence_order += 1
                
            # Process the MIDI command
            midi_command = text_buffer[start_idx:end_idx]
            numbered_sentences[sentence_order] = midi_command
            segment_ready_events[sentence_order] = asyncio.Event()
            asyncio.create_task(process_midi_as_audio(midi_command, sentence_order))
            sentence_order += 1
            
            # Update the buffer
            text_buffer = text_buffer[end_idx:].lstrip()

    # Main loop to process items from the queue
    while True:
        item = await text_chunk_queue.get()
        if item["type"] == "finalize":
            await finalize_text_buffer()
            text_buffer = ""
            sentence_order = 0
            # Signal the finalization is complete
            text_finalized.set()
        elif item["type"] == "text":
            await handle_text_chunk(item["content"])
        text_chunk_queue.task_done()


async def tool_processor():
    tool_call_buffer = defaultdict(lambda: {"name": "", "arguments": ""})
    
    async def handle_tool_call(tool_calls, is_complete):
        complete_indices = set()
        
        for tool_call in tool_calls:
            call_index = getattr(tool_call, "index", 0)
            
            # Update name and arguments if they exist
            if tool_call.function:
                if tool_call.function.name:
                    tool_call_buffer[call_index]["name"] = tool_call.function.name
                if tool_call.function.arguments:
                    tool_call_buffer[call_index]["arguments"] += tool_call.function.arguments
            
            # Track completed calls
            if is_complete:
                complete_indices.add(call_index)
        
        # Process completed calls
        for call_index in complete_indices:
            await finalize_tool_call(call_index)

    async def finalize_tool_call(call_index):
        call_data = tool_call_buffer.get(call_index)
        if not call_data:
            return
            
        arguments_str = call_data["arguments"]
        if not arguments_str.strip():
            tool_call_buffer.pop(call_index, None)
            return
            
        try:
            arguments_dict = orjson.loads(arguments_str)
            call_data["arguments"] = arguments_dict
            
            # Handle different tool types with appropriate formatting
            if call_data["name"] in ("ObsidianCommandTool", "ObsidianNotesTool"):
                # Pass through to process_structured_output with name change
                await process_structured_output("Obsidian_tool", arguments_dict)
            else:
                # For other tools, pass through arguments as-is
                await process_structured_output(call_data["name"], call_data["arguments"])
                
        except (orjson.JSONDecodeError, ValueError) as e:
            logging.error(f"Error decoding JSON for call_index {call_index}: {e}")
            logging.error(f"Accumulated arguments: {arguments_str}")
            
            # Attempt to salvage basic info for minimal processing
            try:
                # Extract just the action and basic payload structure
                import re
                action_match = re.search(r'"action":\s*"([^"]+)"', arguments_str)
                title_match = re.search(r'"title":\s*"([^"]+)"', arguments_str)
                
                if action_match:
                    action = action_match.group(1)
                    title = title_match.group(1) if title_match else "Untitled"
                    
                    minimal_payload = {
                        "action": action,
                        "payload": {
                            "title": title,
                            "content": "Note content could not be properly parsed. Please try again with simpler formatting."
                        }
                    }
                    logging.warning(f"Using minimal payload after JSON parse failure: {minimal_payload}")
                    await process_structured_output(call_data["name"], minimal_payload)
            except Exception as fallback_error:
                logging.error(f"Failed to create fallback payload: {fallback_error}")
                
        tool_call_buffer.pop(call_index, None)

    while True:
        item = await tool_chunk_queue.get()
        
        if item["type"] == "finalize":
            # Process and clear all remaining items in the buffer
            for call_index in list(tool_call_buffer.keys()):
                await finalize_tool_call(call_index)
            tool_call_buffer.clear()  # More efficient than reassigning
            tool_finalized.set()
            
        elif item["type"] == "tool":
            await handle_tool_call(item["tool_calls"], item.get("is_complete", False))
            
        tool_chunk_queue.task_done()

async def obsidian_agent():
    """
    Asynchronous coroutine that continuously waits for transcriptions from obsidian_agent (f4 key),
    and sends each transcription as a contextualised user input to the 'Obsidian augmented LLM'  
    
    In the future I want to have the option to let the agent reload the system prompt just 
    after receiving user input and before doing the API call
    """
    global audio_order, global_http_session
    obsidian_agent_prompt = await get_system_prompt("obsidian_agent_prompt.txt")


    logging.info("\nStarting idea event listener...")
    obsidian_agent_client = AsyncCerebras(api_key=CEREBRAS_API_KEY)
    # obsidian_agent_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    while True:
        # Wait for transcription using obsidian_agent method
        user_input = await whisper_transcriber.transcript_to_obsidian_agent()
        logging.info(f"Received idea event transcription")

        formatted_user_input = [{"role": "user", "content": user_input}]
        
        if not user_input:
            logging.error("Empty transcription received, skipping Obsidian agent")
            continue

        audio_order = 0
        audio_segments.clear()
        numbered_sentences.clear()
        midi_commands.clear()
        messages = communication_manager.get_messages()

        # take only up to the last 5 exchanges in the messages list
        last_exchanges = messages[-5:] if len(messages) >= 5 else messages[:]
        # print("got the last messages")      
        contextualised_user_input = last_exchanges + formatted_user_input
        
        messages_to_agent = [{"role": "system", "content": obsidian_agent_prompt}] + contextualised_user_input
        
        # agent_response = await obsidian_agent_client.chat.completions.create(
        #     model="gpt-4o-2024-11-20",
        #     messages=messages_to_agent,
        #     tools=[obsidian_notes_tool, obsidian_command_tool],
        #     tool_choice="auto",
        #     max_tokens=2000,
        #     temperature=0,
        #     top_p=0.1,
        #     stream=True
        #     )
        agent_response = await obsidian_agent_client.chat.completions.create(
                model="llama-3.3-70b",
                messages=messages_to_agent,
                tools=[obsidian_notes_tool, obsidian_command_tool],
                tool_choice="auto",
                max_tokens=2500,
                temperature=0,
                top_p=0,
                stream=True
            )

        print("\r>>>>>>  Receiving...  <<<<<<", end="")

        try:
            chunks = agent_response.__aiter__()
            while True:
                try:
                    chunk = await asyncio.wait_for(chunks.__anext__(), timeout=20.0)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    break

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                if delta.content:
                    await text_chunk_queue.put({"type": "text", "content": delta.content})

                if delta.tool_calls:
                    is_complete = bool(finish_reason and finish_reason == 'tool_call')
                    await tool_chunk_queue.put({
                        "type": "tool",
                        "tool_calls": delta.tool_calls,
                        "is_complete": is_complete
                    })

                if finish_reason is not None:
                    break

        finally:
            # Instead of sending an 'end' that stops the consumer, send a 'finalize' message.
            await asyncio.gather(
                text_chunk_queue.put({"type": "finalize"}),
                tool_chunk_queue.put({"type": "finalize"})
            )
            # Wait until the consumer signals finalization is complete
            await asyncio.gather(text_finalized.wait(), tool_finalized.wait())
            text_finalized.clear()
            tool_finalized.clear()

async def chat_with_llm(client, messages):
    global audio_order
    audio_order = 0
    audio_segments.clear()
    numbered_sentences.clear()
    midi_commands.clear()

    chosen_model = model_options[current_model_index]
    call_params = dict(params_no_tools) if chosen_model == "chatgpt-4o-latest" else dict(params_with_tools)
    call_params["model"] = chosen_model

    system_prompt = await prompt_manager.get_system_prompt()
    dynamic_context = await prompt_manager.get_dynamic_context()

    combined_messages = [{"role": "system", "content": system_prompt}] + dynamic_context + messages
    chat_completion = await client.chat.completions.create(
        messages=combined_messages,
        **call_params
    )

    print("\r>>>>>>  Receiving...  <<<<<<", end="")

    try:
        chunks = chat_completion.__aiter__()
        while True:
            try:
                chunk = await asyncio.wait_for(chunks.__anext__(), timeout=20.0)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                break

            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            if delta.content:
                await text_chunk_queue.put({"type": "text", "content": delta.content})

            if delta.tool_calls:
                is_complete = bool(finish_reason and finish_reason == 'tool_call')
                await tool_chunk_queue.put({
                    "type": "tool",
                    "tool_calls": delta.tool_calls,
                    "is_complete": is_complete
                })

            if finish_reason is not None:
                break

    finally:
        # Instead of sending an 'end' that stops the consumer, send a 'finalize' message.
        await asyncio.gather(
            text_chunk_queue.put({"type": "finalize"}),
            tool_chunk_queue.put({"type": "finalize"})
        )
        # Wait until the consumer signals finalization is complete
        await asyncio.gather(text_finalized.wait(), tool_finalized.wait())
        text_finalized.clear()
        tool_finalized.clear()
        
    full_response = "".join(
        numbered_sentences[i] for i in sorted(numbered_sentences.keys()) if numbered_sentences[i] is not None
        )

    return full_response

# --- Process Structured Output ---
async def process_structured_output(function_name, function_args):
    
    global audio_order
    audio_order = 0
    audio_segments.clear()
    numbered_sentences.clear()
    
    if function_name == "perplexity_tool":
        print(f"\r{' ' * len('>>>>>>  Receiving...  <<<<<<<')}\r📡🌎🔍: {function_name}", end="")

        if isinstance(function_args, str):
            function_args = json.loads(function_args)
        search_query = function_args.get("search_query", "")
        response_text = await perplexity_request(search_query)
        communication_manager.add_assistant_message(response_text)
        return

    if function_name == "n8n_tool":
        print(f"\r{' ' * len('>>>>>>  Receiving...  <<<<<<<')}\r🛠️ 📞: {function_name}", end="")
        if isinstance(function_args, str):
            function_args = json.loads(function_args)
        chatInput = function_args.get("chatInput")
        try:
            async with global_http_session.get(
                'https://n8n-l5en.onrender.com/webhook/task_agent',
                json={'chatInput': chatInput},
                timeout=50
            ) as resp:
                    if resp.status == 200:
                        n8n_response = await resp.text()
                        sentences = split_into_sentences(n8n_response)
            
                        for sentence_order, sentence in enumerate(sentences):
                            # content = sentence.strip()
                            # numbered_sentences[sentence_order] = sentence
                            # if content == "" or not any(char.isalnum() for char in content):
                            #     asyncio.create_task(process_empty_sentence(sentence_order))
                            # else:
                            #     clean_sentence = sentence.replace("- ", "").replace("#", "").replace("*", "").strip()
                            #     asyncio.create_task(tts_request(clean_sentence, sentence_order))
                            numbered_sentences[sentence_order] = sentence
                            clean_sentence = sentence.replace("- ", "").replace("#", "").replace("*", "'").strip()
                            if not any(char.isalnum() for char in sentence):
                                segment_ready_events[sentence_order] = asyncio.Event()
                                asyncio.create_task(process_empty_sentence(sentence_order))
                            else:
                                segment_ready_events[sentence_order] = asyncio.Event()
                                asyncio.create_task(tts_request(clean_sentence, sentence_order))

                    else:
                        logging.error(f"Webhook returned status code {resp.status}")
        except Exception as e:
            logging.error(f"Error sending user input to webhook: {e}")
        return

    print(f"\r{' ' * len('>>>>>>            Receiving...           <<<<<<<')} + \rCalling Obsidian...", end='')

    try:
        if isinstance(function_args, str):
            function_args = json.loads(function_args)
        action = function_args.get("action")
        payload = function_args.get("payload")
        print(f"\r" + f"action: {action}")
        # print(f"payload: {payload}")
        if not action or payload is None:
            # logging.error("Missing action or payload in function arguments.")
            print("Missing action or payload in function arguments.")
            return
        async with global_http_session.post(
            "http://127.0.0.1:5005/process",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"action": action, "payload": payload}),
            timeout=5
        ) as resp:
                if resp.status == 200:
                    response_text = await resp.text()
                    print(f"Obsidian response: {response_text}")
                    # logging.info("Structured output successfully sent to Obsidian plugin.")
                else:
                    logging.error(f"Failed to send structured output. Status code: {resp.status}")
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON: {e}")
    except asyncio.TimeoutError:
        logging.error("Timeout error: Obsidian plugin did not respond in time.")
    except aiohttp.ClientError as e:
        logging.error(f"HTTP request to Obsidian plugin failed: {e}")

    return

async def process_midi_command(midi_message):
    """
    Extracts the MIDI note or command from the LLM response and sends it to the Flask server.

    Args:
        midi_message (str): The response text from the LLM containing the MIDI command.
    """
    global midi_details
    # Log the entire response for debugging
    # logging.debug(f"Entire response: {midi_message}")

    # Extract the note or command using regex
    note_match = regex.search(r'\[SYSTEM\] \[MIDI\] \[note=(.*?)\] \[/SYSTEM\]', midi_message)
    command_match = regex.search(r'\[SYSTEM\] \[MIDI\] \[command=(.*?)\] \[/SYSTEM\]', midi_message)

    if note_match and note_match.group(1):
        note = note_match.group(1)
        # logging.debug(f"Extracted note: {note}")

        # Prepare the query parameters
        params = {
            'note': note
        }

        # URL of the Flask server
        flask_url = 'http://127.0.0.1:5000/play'

        try:
            async with global_http_session.post(flask_url, params=params) as resp:
                print("\r🎵                               ", flush=True)
                if resp.status == 200:
                    midi_details = await resp.json()
                    # logging.info(f"Successfully sent note '{note}' to Flask server.")
                else:
                    logging.error(f"Failed to send note to Flask server. Status code: {resp.status}")

        except aiohttp.ClientError as e:
            logging.error(f"HTTP request to Flask server failed: {e}")

    elif command_match and command_match.group(1):
        command = command_match.group(1)
        # logging.debug(f"Extracted command: {command}")

        # Prepare the query parameters
        params = {
            'command': command
        }

        # URL of the Flask server
        flask_url = 'http://127.0.0.1:5000/play'

        try:
            async with global_http_session.post(flask_url, params=params) as resp:
                print("\r🎵                               ", flush=True)
                if resp.status == 200:
                        midi_details = await resp.json()
                        # logging.info(f"Successfully sent command '{command}' to Flask server.")
                else:
                    logging.error(f"Failed to send command to Flask server. Status code: {resp.status}")

        except aiohttp.ClientError as e:
            logging.error(f"HTTP request to Flask server failed: {e}")

    else:
        logging.warning("No valid MIDI note or command found in the response.")

class CommunicationManager:
    def __init__(self):
        self.messages: list[dict[str, str]] = []
        self.obsidian_content: str = ""
        self.obsidian_title: str = ""
        self.midi_details: str = ""
        self._lock = threading.Lock()
        self.summary: str = ""

    def handle_action(self, message: Message) -> None:
        """Handles incoming messages based on their type and action."""

        # Check for the specific action type for updating the summary
        if message.action_type == ActionType.PUSH_SUMMARY: # Use the actual Enum member name
            with self._lock:
                # FIRST: Check if the payload dictionary exists
                if message.payload:
                    # SECOND: Safely get the 'text' value from the payload
                    # The .get("text", "") handles cases where 'text' might be missing
                    new_summary = message.payload.get("text", "")
                    self.summary = new_summary # Update the instance's summary attribute
                    print(f"CommunicationManager: Summary updated to: '{self.summary}'") # Optional: Confirmation log
                    return("summary updated")
                else:
                    # Handle the case where payload is None for an update_summary action
                    # You might want to log this as a warning or error
                    
                    print("CommunicationManager: Warning - Received UPDATE_SUMMARY action but payload was missing.")
                    # Decide if you want to clear the summary or leave it as is
                    # self.summary = "" # Optionally clear if payload is missing
                    return("warning - payload was missing")

        if message.action_type == ActionType.PUSH_CONVERSATION:
            with self._lock:
                # FIRST: Check if the payload dictionary exists
                if message.payload:
                    # SECOND: Safely get the 'text' value from the payload
                    # The .get("text", "") handles cases where 'text' might be missing
                    new_conversation = message.payload.get("conversation", [])
                    self.messages = new_conversation # Update the instance's messages attribute
                    # print(f"CommunicationManager: Conversation updated to: {self.messages}")
                    print(f"CommunicationManager: Conversation updated ;-)")
                    return("conversation updated")
                else:
                    print("CommunicationManager: Warning - Received UPDATE_CONVERSATION action but payload was missing.")
                    return("warning - payload was missing")
    
    def handle_trigger(self, message: Message) -> None:
        if message.trigger_type == TriggerType.PULL_CONVERSATION:
            with self._lock:
                return self.messages
            
        if message.trigger_type == TriggerType.PULL_SUMMARY:
            with self._lock:
                return self.summary
            
    def get_summary(self):
        with self._lock:
            return self.summary
        
    def load_summary(self, summary: str) -> None:
        with self._lock:
            self.summary = summary
            
    def add_user_message(self, user_input: str) -> None:
        with self._lock:
            self.messages.append({"role": "user", "content": user_input})

    def add_assistant_message(self, assistant_output: str) -> None:
        with self._lock:
            self.messages.append({"role": "assistant", "content": assistant_output})

    def get_messages(self) -> list[dict[str, str]]:     
        with self._lock:
            return list(self.messages)

    def set_messages(self, new_messages: list[dict[str, str]]) -> None:
        with self._lock:
            self.messages = new_messages

    def update_obsidian_content(self, title: str, content: str) -> None:
        """Update the Obsidian note content."""
        with self._lock:
            self.obsidian_title = title
            self.obsidian_content = content
            note_received.set()

    def update_midi_details(self, midi_details: str) -> None:
        """Update the MIDI details."""
        with self._lock:
            self.midi_details = midi_details

    def process_incoming_message(self) -> None:
        """Process additional context (Obsidian notes, MIDI details) and append to the last message."""
        with self._lock:
            # Append Obsidian note if available
            if self.obsidian_content:
                last_message = next((msg for msg in reversed(self.messages) if msg['role'] in ['user', 'assistant']), None)
                if last_message:
                    last_message['content'] += f"\n\n(Obsidian Note: {self.obsidian_title})\n{self.obsidian_content}"
                self.obsidian_content = ""
                self.obsidian_title = ""
                print(f"Obsidian note added to last message: {self.obsidian_title}")

            # Append MIDI details if available
            if self.midi_details:
                last_message = next((msg for msg in reversed(self.messages) if msg['role'] in ['user', 'assistant']), None)
                if last_message:
                    last_message['content'] += f"\n\nMIDI Details:\n{self.midi_details}"
                self.midi_details = ""
                print(f"MIDI details added to last message: {self.midi_details}")


class PromptManager:
    def __init__(self):
        self.system_prompt = ""
        self.dynamic_context = []

    async def load_default_prompts(self):
        self.system_prompt = await get_system_prompt("system_prompt.txt")
        self.dynamic_context = await get_dynamic_context("dynamic_context.txt")

    async def reload_default_prompts(self, new_system_prompt: str, new_dynamic_context: str):
        self.system_prompt = await get_system_prompt(f"{new_system_prompt}")
        self.dynamic_context = await get_dynamic_context(f"{new_dynamic_context}")

    def set_default_system_prompt(self, new_system_prompt: str):
        self.system_prompt = new_system_prompt

    def set_default_dynamic_context(self, new_dynamic_context: str):
        self.dynamic_context = new_dynamic_context

    async def get_system_prompt(self):
        return self.system_prompt

    async def get_dynamic_context(self):
        return self.dynamic_context
    
async def main():
    
    os.system("cls")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    # Start de taak bij het opstarten
    asyncio.create_task(generate_model_audio_segments())

    
    await initialize()

    try:
        while not shutdown_event.is_set() and not priority_input_event.is_set():
            user_input = await whisper_transcriber.start()
            communication_manager.add_user_message(user_input)
            if note_received.is_set():
                communication_manager.process_incoming_message()

            print("\n>>>>>>  Thinking...  <<<<<<", end='')
            response_text = await chat_with_llm(client, communication_manager.get_messages())
            communication_manager.add_assistant_message(response_text)

    finally:
        logging.warning("Shutdown complete.")
        sys.exit(0)

async def start_uvicorn():
    config = uvicorn.Config(app, host="127.0.0.1", port=5001, log_level="error")
    server = uvicorn.Server(config)
    await server.serve()

# Add this near the end of your file, before the if __name__ == "__main__": block
async def http_session_shutdown():
    if 'global_http_session' in globals() and not global_http_session.closed:
        await global_http_session.close()

if __name__ == "__main__":
    winloop.install()
    whisper_transcriber = WhisperTranscriber()
    whisper_transcriber.setup_key_handlers()  # Set up all key handlers once
    communication_manager = CommunicationManager()
    prompt_manager = PromptManager()
    
    async def run_all():
        await initialize_http_session()

        # Set up signal handler at the top level
        # signal.signal(signal.SIGINT, save_conversation)
        load_default_prompts_task = await asyncio.create_task(prompt_manager.load_default_prompts())
        main_task = asyncio.create_task(main())
        

        server = asyncio.create_task(start_uvicorn())
        playback_task = asyncio.create_task(manage_audio_playback())
        # gui_task = asyncio.create_task(gui_loop())
        first_compound_action_task = asyncio.create_task(first_compound_action())
        tasks_agent_task = asyncio.create_task(tasks_agent())
        obsidian_agent_task = asyncio.create_task(obsidian_agent())
        save_idea_event_task = asyncio.create_task(save_idea_event())
        save_journal_event_task = asyncio.create_task(save_journal_event())
        text_consumer_task = asyncio.create_task(text_processor())
        tool_consumer_task = asyncio.create_task(tool_processor())
        
        # Wait for shutdown_event to be set (by save_conversation)
        await shutdown_event.wait()
        
        # Once shutdown_event is set, cancel all tasks
        server.cancel()
        playback_task.cancel()
        # gui_task.cancel()
        first_compound_action_task.cancel()
        obsidian_agent_task.cancel()
        save_idea_event_task.cancel()
        save_journal_event_task.cancel()
        tasks_agent_task.cancel()
        main_task.cancel()
        text_consumer_task.cancel()
        tool_consumer_task.cancel()

        await http_session_shutdown()        
        # Wait for cancellation to complete
        await asyncio.gather(load_default_prompts_task, server, playback_task, obsidian_agent_task, first_compound_action_task, tasks_agent_task, main_task, text_consumer_task, tool_consumer_task, return_exceptions=True)
        sys.exit(0)

    asyncio.run(run_all())