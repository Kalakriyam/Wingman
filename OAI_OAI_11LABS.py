import os
import asyncio
import threading
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
import keyboard
import uvicorn
import orjson
import sqlite3
from sqlite3 import connect
import tkinter as tk
import pyperclip
# import pydantic
# from mcp.server.fastmcp import FastMCP
import aiosqlite
from aiohttp import TCPConnector, AsyncResolver
from asyncio import to_thread
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from datetime import datetime
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
# from pydub.playback import play
from ultimate_playback import play
from db_helpers import list_modes, add_mode, delete_mode
from termcolor import colored
from openai import AsyncOpenAI
from whisper import WhisperTranscriber
from elevenlabs.client import AsyncElevenLabs
from cerebras.cloud.sdk import AsyncCerebras
from filelock import AsyncFileLock
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Optional, Literal, List, Dict, Any
from enum import Enum
from voice_ui import VoiceUI

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
segment_ready_events = defaultdict()
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
DEFAULT_TRIM_MS = 180
# SENTENCE_END_PATTERN = regex.compile(
#     r'(?<=[^\d\s]{2}[.!?])(?= |$)|(?<=[^\n]{2})(?=\n)|(?<=:)(?=\n)'
# )
SENTENCE_END_PATTERN = regex.compile(
    r'(?<=[^\d\s]{2}[.!?])(?=(?![*_])[\s$])|(?<=[^\n]{2})(?=\n)|(?<=:)(?=\n)')


CLEAN_PATTERN = regex.compile(r'(- )|(#)|(\*)')
HAS_ALNUM = regex.compile(r'[a-zA-Z0-9]')




fastapi_app = FastAPI()

fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Pas dit aan naar jouw behoeften
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConversationState(BaseModel):
    id: str  # Unieke ID, gelijk aan bestandsnaam of event_id
    messages_list_file: str
    message_upto_index: int
    summary: str = ""
    timestamp: str
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    last_mode: str
    parent_id: str
    origin_event_id: str | None = None  # Verwijst naar eerste conversation state of het event waaruit het ontstond

class MessageList(BaseModel):
    id: str
    messages: list[dict[str, str]]

class IdeaEvent(BaseModel):
    event_id: str
    source: dict[str, str]

class JournalEvent(BaseModel):
    event_id: str
    source: dict[str, str]

class NoteData(BaseModel):
    title: str
    content: str

class DefaultPrompts(BaseModel):
    system_prompt: str = Field(default="system_prompt")
    dynamic_context: str = Field(default="dynamic_context")

class VoiceUpdateRequest(BaseModel):
    voice_id: str
    voice_name: str

class ReloadRequest(BaseModel):
    profile_name: str

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
    PUSH_PLACEHOLDER = "push_placeholder"
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

class PromptProfileRequest(BaseModel):
    name: str  # profielnaam, bijv. "default", "obsidian", "code"

class PromptProfile(BaseModel):       
    name: str
    system_prompt: str
    dynamic_context: str
    voice: Optional[str] = None

class PromptsMessage(BaseModel):
    trigger_type: Optional[str] = None
    action_type: Optional[str] = None
    payload: Optional[dict[str, Any]] = None


MODES_DB_PATH = "modes_and_prompts.db"

EVENT_TYPE_TO_MODEL = {
    "ConversationState": ConversationState,
    "IdeaEvent": IdeaEvent,
    "JournalEvent": JournalEvent,
    # Voeg hier andere types toe
    }

@fastapi_app.post("/mode")
async def handle_mode(message: PromptsMessage):
    if message.trigger_type == "list_modes":
        return await list_modes(MODES_DB_PATH)
    
    elif message.action_type == "add_mode":
        name = message.payload.get("name")
        if name:
            await add_mode(name, MODES_DB_PATH)
            return {"status": "added", "name": name}
        else:
            raise HTTPException(status_code=400, detail="Naam ontbreekt")
        
    elif message.action_type == "set_mode":
        name = message.payload.get("name")
        if name:
            await communication_manager.set_current_mode_async(name)
            return {"status": "set", "mode": name}
    
    elif message.trigger_type == "get_current_mode":
        mode = await communication_manager.get_current_mode_async()
        return {"mode": mode} 
    
    elif message.action_type == "delete_mode":
        name = message.payload.get("name")
        if name:
            await delete_mode(name, MODES_DB_PATH)
            return {"status": "deleted", "name": name}
        else:
            raise HTTPException(status_code=400, detail="Naam ontbreekt")   
    
    else:
        raise HTTPException(status_code=400, detail="Ongeldige trigger of actie")
    
@fastapi_app.post("/prompts")
async def handle_prompts(message: PromptsMessage):
    # PULL: Ophalen van een profiel
    if message.trigger_type == "pull_prompts":
        profile_name = "default"
        if message.payload and isinstance(message.payload, dict):
            profile_name = message.payload.get("name", "default")

        raw_profile = await prompt_manager.get_raw_prompt_profile(profile_name)
        return raw_profile

    # PUSH: Wegschrijven van een profiel
    elif message.action_type == "push_prompts":
        if not message.payload:
            raise HTTPException(status_code=400, detail="Payload ontbreekt")

        profile = PromptProfile(**message.payload)
        await prompt_manager.save_prompt_profile(profile)

        return {"message": f"Prompt-profiel '{profile.name}' opgeslagen."}

    elif message.trigger_type == "list_prompts":
        names = await prompt_manager.list_prompt_names() 
        return names 

    elif message.action_type == "delete_prompt":
        name = message.payload.get("name")
        if not name:
            raise ValueError("Geen profielnaam opgegeven voor verwijderen.")
        await prompt_manager.delete_prompt(name)
        return {"status": "deleted", "name": name} 

    else:
        raise HTTPException(status_code=400, detail="Ongeldige trigger of actie")

@fastapi_app.post('/update')
async def update_content(note: NoteData):
    if note.title and note.content:
        await communication_manager.update_obsidian_content(note.title, note.content)
        # return {"message": f"{note.title} succesvol ontvangen"}
        print (f"'{note.title}' succesvol ontvangen")
    
    else:
        raise HTTPException(status_code=400, detail="Titel of inhoud ontbreekt")


@fastapi_app.post('/message')
async def handle_message(message: Message):
    if message.action_type:
        return await communication_manager.handle_action(message)
    elif message.trigger_type:
        return await communication_manager.handle_trigger(message)
    

@fastapi_app.post('/update_voice')
async def update_voice(request: VoiceUpdateRequest):
    await communication_manager.update_voice_id(request.voice_name)
    await generate_model_audio_segments()
    return {"message": f"Stem bijgewerkt naar {request.voice_name}"}


@fastapi_app.post('/reload_default_prompts')
async def reload_default_prompts(request: ReloadRequest):
    print("verzoek tot reload")
    if request.profile_name:
        print("verzoek had een profielnaam")
        await prompt_manager.load_default_prompts(request.profile_name)
        print("Verzoek tot reload succesvol ontvangen")
        return {"message": "Verzoek tot reload succesvol ontvangen"}
    else:
        raise HTTPException(status_code=400, detail="Bericht incompleet")

@fastapi_app.post("/events")
async def handle_events(message: PromptsMessage):
    if message.action_type == "list_events":
        event_type = message.payload.get("event_type")
        dates = message.payload.get("dates", [])
        if not event_type or not dates:
            raise HTTPException(status_code=400, detail="event_type of dates ontbreekt")
        if len(dates) == 1:
            event_ids = event_manager.list_event_ids_by_date(dates[0], event_type)
        elif len(dates) == 2:
            event_ids = event_manager.list_event_ids_by_range(dates[0], dates[1], event_type)
        else:
            raise HTTPException(status_code=400, detail="dates moet 1 of 2 datums bevatten")
        return event_ids
    
    elif message.action_type == "get_event":
        event_id = message.payload.get("event_id")
        if not event_id:
            raise HTTPException(status_code=400, detail="event_id ontbreekt")
        result = event_manager.get_event_by_id(event_id)
        if result:
            event_type, event_obj = result
            return event_obj.model_dump()
        else:
            raise HTTPException(status_code=404, detail="Event niet gevonden") 

    elif message.action_type == "delete_event":
        event_id = message.payload.get("event_id")
        if not event_id:
            raise HTTPException(status_code=400, detail="event_id ontbreekt")
        success = event_manager.delete_event(event_id)
        if success:
            return {"status": "deleted", "event_id": event_id}
        else:
            raise HTTPException(status_code=404, detail="Event niet gevonden of al verwijderd")
    
    elif message.action_type == "update_event":
        event_id = message.payload.get("event_id")
        summary = message.payload.get("summary")
        details = message.payload.get("details")

        if not event_id:
            raise HTTPException(status_code=400, detail="event_id ontbreekt")

        # Haal het bestaande event op
        result = event_manager.get_event_by_id(event_id)
        if not result:
            raise HTTPException(status_code=404, detail="Event niet gevonden")

        event_type, event_obj = result
        event_updated = False  # Flag om te checken of we het event moeten opslaan

        # Update de summary als die bestaat
        if hasattr(event_obj, "summary") and summary is not None:
            event_obj.summary = summary
            event_updated = True

        # Update de messages_list_file als het een ConversationState is
        if event_type == "ConversationState" and hasattr(event_obj, "messages_list_file"):
            list_id = event_obj.messages_list_file
            if list_id and details is not None:
                # Parse de details terug naar messages
                messages = []
                pattern = r"--- (USER|ASSISTANT): ---\n"
                splits = regex.split(pattern, details)
                for i in range(1, len(splits) - 1, 2):
                    role = splits[i].strip().lower()
                    content = splits[i + 1].strip()
                    messages.append({"role": role, "content": content})

                message_list = MessageList(id=list_id, messages=messages)
                event_manager.save_list(message_list)
                event_updated = True  # ✅ ook hier!

        # Alleen opslaan als er echt iets veranderd is
        if event_updated:
            event_manager.save_event(event_type, event_obj.model_dump(), event_id=event_id)

        return {"status": "updated", "event_id": event_id}

    elif message.action_type == "set_specific_state":    
        event_id = message.payload.get("event_id")       
        if not event_id:
            raise HTTPException(status_code=400, detail="event_id ontbreekt")
        event_manager.set_setting("specific_conversation_id", event_id)
        return {"status": "ok", "message": f"Specifieke conversatie ingesteld op {event_id}"}

    elif message.trigger_type == "get_specific_state":
        event_id = event_manager.get_setting("specific_conversation_id")
        if event_id:
            return {"status": "ok", "message": "Specifieke conversatie opgehaald", "event_id": event_id}  
        else:
            raise HTTPException(status_code=404, detail="Geen specifieke conversatie ingesteld")
    
    elif message.action_type == "open_event":
        event_id = message.payload.get("event_id")
        if not event_id:
            raise HTTPException(status_code=400, detail="event_id ontbreekt")
        use_specific_conversation_state(event_id)
        return {"status": "ok", "message": f"Event {event_id} geopend"}
    
    elif message.action_type == "save_summary":
        event_id = message.payload.get("event_id")
        event_type = message.payload.get("event_type")
        new_summary = message.payload.get("summary")

        if not event_id or not event_type or new_summary is None:
            raise HTTPException(status_code=400, detail="event_id, event_type of summary ontbreekt")

        with event_manager.lock, connect(event_manager.db_path) as conn:
            cursor = conn.execute(
                "SELECT content FROM events WHERE event_id = ? AND type = ?", 
                (event_id, event_type))
            row = cursor.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Event niet gevonden")

            content = orjson.loads(row[0])
            content['summary'] = new_summary
            content_json = orjson.dumps(content).decode('utf-8')

            conn.execute(
                "UPDATE events SET content = ? WHERE event_id = ? AND type = ?", 
                (content_json, event_id, event_type))
            conn.commit()

        return {"status": "summary updated", "event_id": event_id}
    
    elif message.action_type == "get_list":
        list_id = message.payload.get("list_id")
        if not list_id:
            raise HTTPException(status_code=400, detail="list_id ontbreekt")
        messages = event_manager.load_list(list_id)
        return messages

    else:
        raise HTTPException(status_code=400, detail="Ongeldige action_type")
    
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
# model_options = ["chatgpt-4o-latest","gpt-4o-2024-11-20", "gpt-4o-mini", "gpt-4.5-preview"]
model_options = ["chatgpt-4o-latest", "gpt-4.1", "gpt-4.1-mini", "gpt-4.5-preview"]

current_model_index = 0


async def fetch_elevenlabs_audio(text: str) -> AudioSegment:
    voice_id = communication_manager.voice_id
    """
    Asynchronously makes a POST to ElevenLabs to synthesize 'text', using a
    semaphore to limit concurrent requests.  Returns a pydub AudioSegment
    (or None on failure).
    """
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
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


def clear_clipboard():
    """
    Clears the clipboard by setting its content to an empty string.
    
    Returns:
        None
    """
    pyperclip.copy('')
    print("Clipboard cleared successfully.")

keyboard.add_hotkey('ctrl+shift+c', clear_clipboard)

# async def first_compound_action():
#     client = AsyncOpenAI(api_key=OPENAI_API_KEY)
#     while True:
#         user_input = await whisper_transcriber.transcript_and_note_content()
#         # Get the current note content from Obsidian
#         try:
#             # Using the server running on port 5005 as defined in your Obsidian plugin
#             # Request to get the current active note content
#             payload = {
#                 "action": "read_current_note",
#                 "payload": {}
#             }
            
#             async with global_http_session.post("http://127.0.0.1:5005/process", 
#                             json=payload) as response:
#                 if response.status == 200:
#                     print("Successfully requested current note content")
#                 else:
#                     print(f"Failed to request note content: {response.status}")
            
#         except Exception as e:
#             print(f"Error communicating with Obsidian: {str(e)}")
        
#         await communication_manager.add_user_message(user_input)
#         await note_received.wait()
#         await communication_manager.process_incoming_message()
#         note_received.clear()

#         print("\n>>>>>>  Thinking...  <<<<<<", end='')
#         response_text = await chat_with_llm(client, await communication_manager.get_messages())
#         await communication_manager.add_assistant_message(response_text)

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



DATABASE_NAME = "my_personal_database.db"
TABLE_SHOPPING = "shopping_list"
TABLE_PERSONAL = "personal_tasks"
TABLE_PROFESSIONAL = "professional_tasks"

ListType = Literal["shopping", "personal", "professional"]
PriorityType = Literal["hi", "med", "lo"]

LIST_TYPE_TO_TABLE = {
    "shopping": TABLE_SHOPPING,
    "personal": TABLE_PERSONAL,
    "professional": TABLE_PROFESSIONAL,
}

TABLES_WITH_PRIORITY = {TABLE_PERSONAL, TABLE_PROFESSIONAL}

class ListManagerDB:
    def __init__(self, db_path: str = DATABASE_NAME):
        self._conn = connect(db_path, check_same_thread=False, cached_statements=100)
        self._lock = Lock()
        self._configure_database()
        self._create_tables()

    def _configure_database(self):
        with self._lock:
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
            self._conn.execute("PRAGMA cache_size = -10000;")
            self._conn.execute("PRAGMA temp_store = MEMORY;")

    def _create_tables(self):
        with self._lock:
            self._conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_SHOPPING} (
                    title TEXT PRIMARY KEY
                )
            """)
            self._conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_PERSONAL} (
                    title TEXT PRIMARY KEY,
                    priority TEXT CHECK(priority IN ('hi', 'med', 'lo')) NOT NULL
                )
            """)
            self._conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_PROFESSIONAL} (
                    title TEXT PRIMARY KEY,
                    priority TEXT CHECK(priority IN ('hi', 'med', 'lo')) NOT NULL
                )
            """)
            self._conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{TABLE_PERSONAL}_priority 
                ON {TABLE_PERSONAL} (priority, title)
            """)
            self._conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{TABLE_PROFESSIONAL}_priority 
                ON {TABLE_PROFESSIONAL} (priority, title)
            """)

    async def list_items(self, table_name: str) -> List[Dict[str, Any]]:
        with self._lock:
            cursor = self._conn.cursor()
            if table_name in TABLES_WITH_PRIORITY:
                cursor.execute(f"""
                    SELECT title, priority FROM {table_name}
                    ORDER BY CASE priority
                        WHEN 'hi' THEN 1
                        WHEN 'med' THEN 2
                        WHEN 'lo' THEN 3
                    END
                """)
                return [{"title": title, "priority": priority} for title, priority in cursor.fetchall()]
            elif table_name == TABLE_SHOPPING:
                cursor.execute(f"SELECT title FROM {table_name}")
                return [{"title": title, "priority": None} for title, in cursor.fetchall()]
            else:
                raise ValueError(f"Unknown table name: {table_name}")

    async def add_item(self, table_name: str, title: str, priority: Optional[PriorityType] = "med"):
        with self._lock, self._conn:
            if table_name in TABLES_WITH_PRIORITY:
                self._conn.execute(
                    f"INSERT OR REPLACE INTO {table_name} (title, priority) VALUES (?, ?)",
                    (title, priority or "med")
                )
            elif table_name == TABLE_SHOPPING:
                self._conn.execute(
                    f"INSERT OR REPLACE INTO {table_name} (title) VALUES (?)",
                    (title,)
                )
            else:
                raise ValueError(f"Cannot add item to unknown table: {table_name}")

    async def delete_item(self, table_name: str, title: str):
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"DELETE FROM {table_name} WHERE title=?",
                (title,)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Item '{title}' not found in table '{table_name}'.")

    async def update_item_priority(self, table_name: str, title: str, new_priority: PriorityType):
        if table_name not in TABLES_WITH_PRIORITY:
            raise ValueError(f"Table '{table_name}' does not support priorities.")
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"UPDATE {table_name} SET priority=? WHERE title=?",
                (new_priority, title)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Item '{title}' not found in table '{table_name}'.")

@dataclass
class ListManagerDeps:
    db: ListManagerDB

class ListItem(BaseModel):
    title: str = Field(..., description="Title of the item (task or shopping good)")
    priority: Optional[PriorityType] = Field(None, description="Priority ('hi', 'med', 'lo') for tasks, None for shopping")

async def tasks_agent():
    """
    Asynchronous coroutine that continuously listens for transcriptions and interacts
    with a database-backed tasks manager via a PydanticAI agent. Streams output chunks
    to a text queue for real-time TTS.
    """
    global audio_order

    logging.info("\nStarting Tasks Agent event listener...")

    # Define dependencies
    db = ListManagerDB(db_path="my_personal_database.db")
    deps = ListManagerDeps(db=db)

    # Create Agent
    tasks_agent = Agent(
        model="google-gla:gemini-2.0-flash",
        deps_type=ListManagerDeps,
        system_prompt=("""
Je beheert drie lijsten: boodschappen ('shopping'), dagelijkse/persoonlijke taken ('personal') en professionele taken ('professional') .
Je kunt items toevoegen, verwijderen, aanpassen en opvragen.

**STAPPEN BIJ VERZOEK TOT VERWIJDEREN:**
Als een gebruiker vraagt om iets te verwijderen, werk dan volgens deze stappen:
1) Haal de volledige lijst op
2) Vergelijk de gebruikersvraag met de items in de lijst
3) Kies het item dat het meest op de gebruikersvraag lijkt
4) Verwijder het gekozen item

Het is dus essentieel dat je geen exacte tekstvergelijking gebruikt.
Bijvoorbeeld: als de gebruiker zegt “verwijder het brood van mijn boodschappenlijst”, dan doe je:
1) de boodschappenlijst geheel ophalen > stel dat je ziet dat de lijst "bruin brood" bevat en geen andere items met 'brood'
2) de vraag was "verwijder het brood van mijn boodschappenlijst"
3) het item dat het meest op de vraag lijkt is "bruin brood" (aangezien het de enige 'brood' item is)
4) verwijder "bruin brood"

Boodschappen hebben geen prioriteit.
Taken hebben prioriteit: 'hi', 'med', 'lo'.     
Als bij een taak geen prioriteit wordt genoemd, gebruik dan 'med' als prioriteit.
Als de gebruiker niet zegt welke lijst, ga dan uit van de persoonlijke takenlijst.
Als je een lijst toont, gebruik dan streepjes en sorteer op prioriteit (bovenaan beginnen met de hoge prioriteit).
Laat prioriteit alleen zien als het relevant is.
                       """
        )
    )

    # Register Tools
    def get_table_name(list_type: ListType) -> str:
        return LIST_TYPE_TO_TABLE[list_type]

    @tasks_agent.tool
    async def list_items(ctx: RunContext[ListManagerDeps], list_type: ListType) -> List[ListItem]:
        table_name = get_table_name(list_type)
        data = await ctx.deps.db.list_items(table_name)
        if table_name in TABLES_WITH_PRIORITY:
            priority_map = {"hi": 0, "med": 1, "lo": 2}
            data.sort(key=lambda item: priority_map.get(item["priority"], 3))
        return [ListItem(**d) for d in data]

    @tasks_agent.tool
    async def add_item(ctx: RunContext[ListManagerDeps], list_type: ListType, title: str, priority: Optional[PriorityType] = "med") -> str:
        table_name = get_table_name(list_type)
        eff_priority = priority if table_name in TABLES_WITH_PRIORITY else None
        try:
            await ctx.deps.db.add_item(table_name, title, eff_priority)
            return f"Added '{title}' to {list_type} list."
        except Exception as e:
            return f"Error adding '{title}': {e}"

    @tasks_agent.tool
    async def delete_item(ctx: RunContext[ListManagerDeps], list_type: ListType, title: str) -> str:
        table_name = get_table_name(list_type)
        try:
            await ctx.deps.db.delete_item(table_name, title)
            return f"Deleted '{title}' from {list_type} list."
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error deleting '{title}': {e}"

    @tasks_agent.tool
    async def update_task_priority(ctx: RunContext[ListManagerDeps], list_type: ListType, title: str, new_priority: PriorityType) -> str:
        table_name = get_table_name(list_type)
        if table_name not in TABLES_WITH_PRIORITY:
            return f"Priority not supported for {list_type} list."
        try:
            await ctx.deps.db.update_item_priority(table_name, title, new_priority)
            return f"Updated priority of '{title}' to {new_priority}."
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error updating priority: {e}"

    # Main transcription + streaming loop
    while True:
        user_input = await whisper_transcriber.transcript_to_tasks_agent()
        logging.info(f"TASKS_AGENT: Received transcription: '{user_input}'")
        if not user_input:
            logging.warning("TASKS_AGENT: Empty transcription received, skipping.")
            continue

        audio_order = 0
        audio_segments.clear()
        numbered_sentences.clear()
        midi_commands.clear()

        print("\r>>>>>> Receiving... <<<<<<", end="")

        try:
            async with tasks_agent.run_stream(user_input, deps=deps) as result:
                async for chunk in result.stream_text(delta=True):
                    if chunk:
                        await text_chunk_queue.put({"type": "text", "content": chunk})

            logging.info("TASKS_AGENT: Finished streaming response.")

        except Exception as e:
            logging.error(f"TASKS_AGENT: Error during agent run: {e}", exc_info=True)
            await text_chunk_queue.put({"type": "text", "content": f"\n[Agent Error: {e}]"})
        finally:
            print("\r" + " " * 40 + "\r", end="")
            await text_chunk_queue.put({"type": "finalize"})
            logging.debug("TASKS_AGENT: Sent finalize signal to text queue.")
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

# async def get_dynamic_context(filename="dynamic_context.txt"):
#     summary = await communication_manager.get_summary()
#     try:
#         async with global_http_session.get(
#             'http://192.168.178.144:5000/read-file',
#             params={'filename': filename}, 
#             timeout=2
#             ) as response:
#                 if response.status == 200:
#                     data = await response.json()
#                     content = data.get('content', '') # use .get for safety
                    
#                     # Optional placeholder replacements
#                     now = datetime.now()
#                     content = content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
#                     content = content.replace("{local_time}", now.strftime("%H:%M:%S"))
#                     content = content.replace("{summary}", summary)
                    
#                     return [
#                         {"role": "user", "content": content},
#                         {"role": "assistant", "content": "OK!"}
#                     ]
#                 else:
#                     logging.warning(f"Dynamic context server error: {response.status} - {await response.text()}") # Use warning, not error yet
#     except (aiohttp.ClientError, asyncio.TimeoutError) as e:
#         logging.warning(f"Failed to fetch dynamic context from server, trying local file: {e}") # Use warning

#     # Fallback to local file if server fetch failed or returned non-200
#     try:
#         script_dir = os.path.dirname(os.path.abspath(__file__))
#         file_path = os.path.join(script_dir, filename)
#         async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
#             content = await file.read()
#             now = datetime.now()
#             content = content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
#             content = content.replace("{local_time}", now.strftime("%H:%M:%S"))
#             content = content.replace("{summary}", summary)
#             logging.info("Fetched dynamic context from local file") # Use info or print
#             dynamic_context = [
#                 {"role": "user", "content": content},
#                 {"role": "assistant", "content": "OK!"}
#             ]
#             # prompt_manager.set_default_dynamic_context(dynamic_context) # This line is redundant here and can be removed
#             # **** FIX: Add the return statement ****
#             return dynamic_context
#     except IOError as e:
#         logging.error(f"Failed to read local dynamic_context file '{filename}': {e}")
#         # **** FIX: Return an empty list instead of a string ****
#         # This signifies no dynamic context could be loaded, but prevents the TypeError
#         return []
#     except Exception as e:
#         # Catch any other unexpected errors during local file processing
#         logging.error(f"Unexpected error processing local dynamic context file '{filename}': {e}")
#         return [] # Return empty list on unexpected errors too


def reset_chat_history():
    global audio_order, audio_segments, numbered_sentences
    audio_order = 0
    audio_segments.clear()
    numbered_sentences.clear()
    # empty_messages = []
    # communication_manager.set_messages_sync(empty_messages)
    communication_manager.set_messages_sync([])
    # system_prompt = await get_system_prompt("system_prompt.txt") # gaat niet, want dit is een sync functie
    # dynamic_context = await get_dynamic_context("dynamic_context.txt") # gaat niet, want dit is een sync functie
    print("Chat history reset.")

keyboard.add_hotkey('ctrl+shift+9', reset_chat_history)


def save_conversation_state() -> str:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    event_id = f"conversation_state_{timestamp}"

    summary = communication_manager.get_summary_sync()
    messages = communication_manager.get_messages_sync()
    message_upto_index = len(messages) - 1

    # Opslaan van messages-lijst als MessageList object in database
    messages_list_id = f"messages_{timestamp}"
    message_list = MessageList(id=messages_list_id, messages=messages)
    event_manager.save_list(message_list)

    # Modus en lineage
    last_mode = communication_manager.get_current_mode()
    parent_id = communication_manager.parent_conversation_id or event_id
    origin_event_id = communication_manager.origin_event_id or None


    # Bouw ConversationState object
    state = ConversationState(
        id=event_id,
        messages_list_file=messages_list_id,
        message_upto_index=message_upto_index,
        summary=summary,
        timestamp=timestamp,
        tags=[],
        links=[],
        last_mode=last_mode,
        parent_id=parent_id,
        origin_event_id=origin_event_id)

    # Serialiseer en sla ConversationState op in events-tabel
    content_json = orjson.dumps(state.model_dump(mode="json")).decode("utf-8")
    with event_manager.lock, connect(event_manager.db_path) as conn:
        conn.execute(
            "INSERT INTO events (event_id, type, content) VALUES (?, ?, ?)",
            (event_id, "ConversationState", content_json))
        conn.commit()

    # Update sessie-informatie
    communication_manager.parent_conversation_id = event_id

    # print(f"Conversation state opgeslagen in database met ID: {event_id}")
    print(f"\nConversatie bewaard")
    return event_id

# put this after the function definition, because it needs to be defined first
keyboard.add_hotkey('ctrl+shift+o', save_conversation_state)

def use_specific_conversation_state(event_id: str | None = None):
    if not event_id:
        event_id = event_manager.get_setting("specific_conversation_id")
        if not event_id:
            # overweeg een melding te geven en de laatste conversatie in te laden
            print("Geen specifieke conversation ID gevonden in settings.")
            return

    # print(f"Loading specific conversation state: {event_id}")
    result = event_manager.get_event_by_id(event_id)
    if not result:
        print(f"Geen geldig event gevonden voor ID: {event_id}")
        communication_manager.set_messages_sync([])
        prompt_manager.set_default_system_prompt("")
        prompt_manager.set_default_dynamic_context([])
        return

    event_type, model = result
    if event_type != "ConversationState":
        print(f"Event type '{event_type}' is geen ConversationState.")
        return

    state: ConversationState = model

    communication_manager.load_summary_sync(state.summary)
    

    messages = event_manager.load_list(state.messages_list_file)
    communication_manager.set_messages_sync(messages[:state.message_upto_index + 1])
    # print(f"{state.message_upto_index + 1} messages geladen.")

    prompt_manager.load_default_prompts_sync(state.last_mode)

    communication_manager.parent_conversation_id = state.id
    communication_manager.origin_event_id = state.origin_event_id
    communication_manager.current_mode = state.last_mode

    print(f"\n\n{state.id} geladen ({state.message_upto_index + 1} messages)")
    print(f"\nSummary: {state.summary}")

# Register the hotkey
keyboard.add_hotkey('ctrl+shift+0', use_specific_conversation_state)


def load_latest_conversation_state():
    print(f"\n" + colored("Loading latest conversation...", "blue"))
    result = event_manager.get_latest_event("ConversationState")
    if not result:
        print("Geen conversation state gevonden. Start met lege sessie.")
        communication_manager.set_messages_sync([])
        return

    event_id, model = result
    state: ConversationState = model

    # Laad summary
    communication_manager.load_summary_sync(state.summary)

    # Laad messages (tot en met index)
    messages = event_manager.load_list(state.messages_list_file)
    communication_manager.set_messages_sync(messages[:state.message_upto_index + 1])

    # Laad prompts op basis van opgeslagen modus     
    prompt_manager.load_default_prompts_sync(state.last_mode)

    # Update sessie state
    communication_manager.parent_conversation_id = state.id
    communication_manager.origin_event_id = state.origin_event_id
    communication_manager.current_mode = state.last_mode  # ✅ correct veld

    print(colored(f"{state.message_upto_index + 1} messages geladen.", "blue"))
    if state.summary:
        print(colored(f"\nSummary: \n{state.summary}", "yellow"))
    else:
        print(colored("Summary: leeg.", "yellow"))
    # print(f"Conversation state '{state.id}' geladen.")

keyboard.add_hotkey('ctrl+shift+r', load_latest_conversation_state)


async def save_idea_event():
    """
    Coroutine die continu luistert naar idea events (F9 key),
    en elk idee opslaat in de database én naar Obsidian stuurt."""
    global global_http_session
    logging.info("Starting idea event listener...")

    while True:
        user_input = await whisper_transcriber.idea_event()
        if not user_input:
            print("Lege transcription ontvangen, skip.")
            continue

        timestamp_id = datetime.now().strftime("%Y%m%d%H%M%S")
        pretty_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 1. Sla op in database
        event_data = {
            "event_id": timestamp_id,
            "type": "idea",
            "source": {"content": user_input}}
        event_id = event_manager.save_event("idea", event_data, event_id=timestamp_id)
        print(f"\nIdee opgeslagen in database met ID: {event_id}")

        # 2. Stuur naar Obsidian via globale sessie
        obsidian_markdown = f"""#idee

link:: idea_{timestamp_id}.json

{pretty_timestamp}

{user_input}"""
        obsidian_title = f"Inbox/idea_{timestamp_id}"
        obsidian_data = {
            "action": "create_note",
            "payload": {
                "title": obsidian_title,
                "text": obsidian_markdown}}
        try:
            async with global_http_session.post(
                "http://127.0.0.1:5005/process",
                json=obsidian_data,
                headers={'Content-Type': 'application/json'},
                timeout=5
            ) as response:
                if response.status == 200:
                    print(f"Idee ook naar Obsidian gestuurd: {obsidian_title}")
                else:
                    print(f"Fout bij sturen naar Obsidian. Status code: {response.status}")
        except Exception as e:
            print(f"Error bij sturen naar Obsidian: {e}")


async def save_journal_event():
    """
    Coroutine die continu luistert naar journal events (F7 key),
    en elk journal opslaat in de database én naar Obsidian stuurt."""
    global global_http_session
    logging.info("Starting journal event listener...")

    while True:
        user_input = await whisper_transcriber.journal_event()
        if not user_input:
            print("Lege transcription ontvangen, skip.")
            continue

        timestamp_id = datetime.now().strftime("%Y%m%d%H%M%S")
        pretty_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 1. Sla op in database
        event_data = {
            "event_id": timestamp_id,
            "type": "journal",
            "source": {"content": user_input}}
        event_id = event_manager.save_event("journal", event_data, event_id=timestamp_id)
        print(f"Journal event opgeslagen in database met ID: {event_id}")

        # 2. Stuur naar Obsidian via globale sessie
        obsidian_markdown = f"""#journal

link:: journal_{timestamp_id}.json

{pretty_timestamp}

{user_input}"""
        obsidian_title = f"Inbox/journal_{timestamp_id}"
        obsidian_data = {
            "action": "create_note",
            "payload": {
                "title": obsidian_title,
                "text": obsidian_markdown}}
        try:
            async with global_http_session.post(
                "http://127.0.0.1:5005/process",
                json=obsidian_data,
                headers={'Content-Type': 'application/json'},
                timeout=5
            ) as response:
                if response.status == 200:
                    print(f"Journal event ook naar Obsidian gestuurd: {obsidian_title}")
                else:
                    print(f"Fout bij sturen naar Obsidian. Status code: {response.status}")
        except Exception as e:
            print(f"Error bij sturen naar Obsidian: {e}")


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

# async def get_system_prompt(filename):

#     # Step 2: Fetch the Context
#     system_prompt_content = ""
#     try:
#         async with global_http_session.get(
#             'http://192.168.178.144:5000/read-file',
#             params={'filename': filename},
#             timeout=2
#         ) as response:
#                 if response.status == 200:
#                     data = await response.json()
#                     # logging.info(f"Context fetched from server: {data}")
#                     system_prompt_content = data.get('content', "")
#                 else:
#                     logging.warning(f"Context server error: {await response.text()}")
#     except (aiohttp.ClientError, asyncio.TimeoutError) as e:
#         logging.error(f"Failed to fetch context from server: {e}")
    
#     # If fetching from server failed, try reading from local file
#     if not system_prompt_content:
#         try:
#             script_dir = os.path.dirname(os.path.abspath(__file__))
#             system_prompt_path = os.path.join(script_dir, filename)
#             async with aiofiles.open(system_prompt_path, 'r', encoding='utf-8') as file:
#                 system_prompt_content = await file.read()
#                 # logging.info("Context fetched from local file.")
#         except IOError as e:
#             logging.error(f"Failed to read local system prompt file: {e}")
#             return "Failed to retrieve system prompt from both server and local file."

#     # Step 3: Replace Placeholders
#     try:
#         # Replace date and time placeholders
#         now = datetime.now()
#         system_prompt_content = system_prompt_content.replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
#         system_prompt_content = system_prompt_content.replace("{local_time}", now.strftime("%H:%M:%S"))
        
#         return system_prompt_content
    
#     except Exception as e:
#         logging.error(f"Error processing {filename} content: {e}")
#         return f"Failed to process {filename} content."
    
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
    voice_id = communication_manager.voice_id
    try:
        async with tts_semaphore:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
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
                    segment_ready_events[order] = asyncio.Event()
                    segment_ready_events[order].set()
                    
    except Exception as e:
        print(f"TTS API error for sentence {order} ({sentence}): {e}")
        # Make sure we don't block the audio playback queue by setting the event even on error
        # if order in segment_ready_events:
        #     segment_ready_events[order].set()

async def manage_audio_playback():
    global audio_order
    await audio_ready_event.wait()
    audio_ready_event.clear()
    # await segment_ready_events[0].wait()
    # segment_ready_events[0].clear()
    
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

        await asyncio.sleep(0.05)

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
    obsidian_agent_prompt = await prompt_manager.get_system_prompt("obsidian")


    logging.info("\nStarting idea event listener...")
    # obsidian_agent_client = AsyncCerebras(api_key=CEREBRAS_API_KEY)
    obsidian_agent_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
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
        messages = await communication_manager.get_messages()

        # take only up to the last 5 exchanges in the messages list
        last_exchanges = messages[-5:] if len(messages) >= 5 else messages[:]
        # print("got the last messages")      
        contextualised_user_input = last_exchanges + formatted_user_input
        
        messages_to_agent = [{"role": "system", "content": obsidian_agent_prompt}] + contextualised_user_input
        
        agent_response = await obsidian_agent_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages_to_agent,
            tools=[obsidian_notes_tool, obsidian_command_tool],
            tool_choice="auto",
            max_tokens=2000,
            temperature=0,
            top_p=0.1,
            stream=True
            )
        # agent_response = await obsidian_agent_client.chat.completions.create(
        #         model="llama-3.3-70b",
        #         messages=messages_to_agent,
        #         tools=[obsidian_notes_tool, obsidian_command_tool],
        #         tool_choice="auto",
        #         max_tokens=2500,
        #         temperature=0,
        #         top_p=0,
        #         stream=True
        #     )

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

    system_prompt = prompt_manager.get_current_system_prompt()
    dynamic_context = prompt_manager.get_current_dynamic_context()

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
        print(f"\r{' ' * len('>>>>>>  Receiving...  <<<<<<<')}\r📡🌎🔍: Searching the web...", end="")

        if isinstance(function_args, str):
            function_args = json.loads(function_args)
        search_query = function_args.get("search_query", "")
        response_text = await perplexity_request(search_query)
        await communication_manager.add_assistant_message(response_text)
        return

    if function_name == "n8n_tool":
        print(f"\r{' ' * len('>>>>>>  Receiving...  <<<<<<<')}\r🛠️ 📞: Calling your crew...", end="")
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

    print(f"\r{' ' * len('>>>>>>            Receiving...           <<<<<<<')}\rCalling Obsidian...", end='')

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
        self.voice_name: str = "Robert"  # Default stemnaam
        self.voice_id: str = "BtWabtumIemAotTjP5sk" # Default stem-code
        self._lock = asyncio.Lock()
        self.summary: str = ""

        # Conversatie-gerelateerde sessiegegevens    
        self.current_mode: str = "default"
        self.parent_conversation_id: str | None = None
        self.origin_event_id: str | None = None
    

    async def update_voice_id(self, voice_name: str):
        async with self._lock:
            try:
                async with aiosqlite.connect("modes_and_prompts.db") as db:
                    cursor = await db.execute(
                        "SELECT value FROM settings WHERE key = ?", ("voices",))
                    row = await cursor.fetchone()
                    await cursor.close()

                if not row:
                    print("Fout: geen voices gevonden in database.")
                    return

                voices_dict = json.loads(row[0])
                voice_code = voices_dict.get(voice_name)

                if not voice_code:
                    print(f"Fout: stem '{voice_name}' niet gevonden in voices-lijst.")
                    return

                self.voice_id = voice_code  # <-- de code      
                self.voice_name = voice_name  # <-- de naam
                print(f"Stem bijgewerkt naar {voice_name} ({voice_code})")

            except Exception as e:
                print(f"Fout bij updaten van voice_id: {e}")

    async def get_voices_dict(self) -> dict[str, str]:
        async with self._lock:
            try:
                async with aiosqlite.connect("modes_and_prompts.db") as db:
                    cursor = await db.execute(
                        "SELECT value FROM settings WHERE key = ?", ("voices",))
                    row = await cursor.fetchone()
                    await cursor.close()

                if not row:
                    print("Fout: geen voices gevonden in database.")
                    return {}

                voices_dict = json.loads(row[0])
                return voices_dict

            except Exception as e:
                print(f"Fout bij ophalen van voices-lijst: {e}")
                return {}
    async def handle_action(self, message: Message) -> str:
        async with self._lock:
            if message.action_type == ActionType.PUSH_SUMMARY:
                if message.payload:
                    self.summary = message.payload.get("text", "")
                    print(f"CommunicationManager: Summary updated to: '{self.summary}'")
                    return "summary updated"
                else:
                    print("CommunicationManager: Warning - Received UPDATE_SUMMARY action but payload was missing.")
                    return "warning - payload was missing"

            if message.action_type == ActionType.PUSH_CONVERSATION:
                if message.payload:
                    self.messages = message.payload.get("conversation", [])
                    print("CommunicationManager: Conversation updated ;-)")
                    return "conversation updated"
                else:
                    print("CommunicationManager: Warning - Received UPDATE_CONVERSATION action but payload was missing.")
                    return "warning - payload was missing"
                
    async def handle_trigger(self, message: Message):
        async with self._lock:
            if message.trigger_type == TriggerType.PULL_CONVERSATION:
                return self.messages
            if message.trigger_type == TriggerType.PULL_SUMMARY:
                return self.summary

    async def get_summary(self) -> str:
        async with self._lock:
            return self.summary

    async def load_summary(self, summary: str) -> None:
        async with self._lock:
            self.summary = summary

    async def add_user_message(self, user_input: str) -> None:
        async with self._lock:
            self.messages.append({"role": "user", "content": user_input})

    async def add_assistant_message(self, assistant_output: str) -> None:
        async with self._lock:
            self.messages.append({"role": "assistant", "content": assistant_output})

    async def get_messages(self) -> list[dict[str, str]]:
        async with self._lock:
            return list(self.messages)

    async def set_messages(self, new_messages: list[dict[str, str]]) -> None:
        async with self._lock:
            self.messages = new_messages

    async def update_obsidian_content(self, title: str, content: str) -> None:
        async with self._lock:
            self.obsidian_title = title
            self.obsidian_content = content
            note_received.set()

    async def update_midi_details(self, midi_details: str) -> None:
        async with self._lock:
            self.midi_details = midi_details

    async def process_incoming_message(self) -> None:
        async with self._lock:
            last_message = next((msg for msg in reversed(self.messages) if msg['role'] in ['user', 'assistant']), None)

            if self.obsidian_content and last_message:
                last_message['content'] += f"\n\n(Obsidian Note: {self.obsidian_title})\n{self.obsidian_content}"
                print(f"Obsidian note added to last message: {self.obsidian_title}")
                self.obsidian_content = ""
                self.obsidian_title = ""

            if self.midi_details and last_message:   
                last_message['content'] += f"\n\nMIDI Details:\n{self.midi_details}"
                print(f"MIDI details added to last message: {self.midi_details}")
                self.midi_details = ""
            # Clipboard
            clipboard_text = await asyncio.to_thread(pyperclip.paste)
            if clipboard_text.strip() and last_message:
                last_message['content'] += f"\n\n(Pasted clipboard content:)\n{clipboard_text.strip()}"
                await asyncio.to_thread(pyperclip.copy, "")  # Leegmaken
                print("Clipboard content added to last message.")

    async def set_current_mode_async(self, mode: str):
        async with self._lock:
            self.current_mode = mode
            await prompt_manager.load_default_prompts(mode)
            voice_name = await prompt_manager.get_profile_voice(mode)
            if voice_name:
                await self.update_voice_id(voice_name)
                await generate_model_audio_segments()

    async def get_current_mode_async(self) -> str:
        async with self._lock:
            return self.current_mode

    def get_messages_sync(self) -> list[dict[str, str]]:
        return self.messages.copy()

    def get_summary_sync(self) -> str:
        return self.summary

    def get_current_mode(self) -> str:
        return self.current_mode

    def set_messages_sync(self, new_messages: list[dict[str, str]]) -> None:
        self.messages = new_messages

    def load_summary_sync(self, summary: str) -> None:
        self.summary = summary

    def set_current_mode(self, mode: str):
        self.current_mode = mode


class EventManager:
    def __init__(self, db_path="event_store.db"):
        self.db_path = db_path
        self.lock = Lock()
        self._init_db()

    def _init_db(self):
        with connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE,
                    type TEXT,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            # Settings-tabel toevoegen
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT)""")
            # lists-tabel toevoegen
            conn.execute("""
                CREATE TABLE IF NOT EXISTS lists (
                    id TEXT PRIMARY KEY,
                    content TEXT)""")
            conn.commit()

    def save_event(self, event_type: str, content: dict, event_id: str = None):
        if event_id is None:
            event_id = datetime.now().strftime("%Y%m%d%H%M%S")
        content_json = orjson.dumps(content).decode('utf-8')
        with self.lock, connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO events (event_id, type, content)
                VALUES (?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    type=excluded.type,
                    content=excluded.content
            """, (event_id, event_type, content_json))
            conn.commit()
        return event_id


    def get_latest_event(self, event_type: str) -> tuple[str, BaseModel] | None:
        with self.lock, connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT event_id, content FROM events WHERE type = ? ORDER BY created_at DESC LIMIT 1",
                (event_type,))
            row = cursor.fetchone()

        if row:
            event_id, content_json = row
            try:
                content_dict = orjson.loads(content_json)
                model_cls = EVENT_TYPE_TO_MODEL.get(event_type)
                if not model_cls:
                    print(f"Onbekend event_type '{event_type}' voor laatste event")
                    return None
                validated = model_cls.model_validate(content_dict)
                return event_id, validated
            except Exception as e:
                print(f"Fout bij valideren {event_type} voor laatste event: {e}")
                return None
        return None



# Je kunt deze functie nu gebruiken voor:
# event_manager.list_events("ConversationState")
# event_manager.list_events("idea")
# event_manager.list_events("journal")
    def list_events(self, event_type: str) -> list[tuple[str, BaseModel]]:
        results = []
        model_cls = EVENT_TYPE_TO_MODEL.get(event_type)
        if not model_cls:
            print(f"Onbekend event_type '{event_type}' in list_events()")
            return []

        with self.lock, connect(self.db_path) as conn:   
            cursor = conn.execute(
                "SELECT event_id, content FROM events WHERE type = ? ORDER BY created_at DESC",
                (event_type,))
            rows = cursor.fetchall()

        for event_id, content_json in rows:
            try:
                content_dict = orjson.loads(content_json)
                validated = model_cls.model_validate(content_dict)
                results.append((event_id, validated))
            except Exception as e:
                print(f"Fout bij valideren {event_type} voor ID '{event_id}': {e}")
                continue

        return results

    def delete_event(self, event_id: str) -> bool:
        with self.lock, connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
            conn.commit()
            return cursor.rowcount > 0  # True als iets verwijderd is

    def save_list(self, message_list: MessageList):
        content_json = orjson.dumps(message_list.model_dump(mode="json")).decode("utf-8")
        with self.lock, connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO lists (id, content) VALUES (?, ?)",
                (message_list.id, content_json))
            conn.commit()

    def load_list(self, list_id: str) -> list[dict[str, str]]:
        with self.lock, connect(self.db_path) as conn:
            cursor = conn.execute("SELECT content FROM lists WHERE id = ?", (list_id,))
            row = cursor.fetchone()

        if row:
            try:
                content_dict = orjson.loads(row[0])
                message_list = MessageList.model_validate(content_dict)
                return message_list.messages
            except Exception as e:
                print(f"Fout bij valideren MessageList '{list_id}': {e}")
                return []
        return []

    def delete_list(self, list_id: str) -> bool:
        with self.lock, connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM lists WHERE id = ?", (list_id,))
            conn.commit()
            return cursor.rowcount > 0

    def list_event_ids_by_date(
        self,
        date: str,  # formaat: "YYYY-MM-DD"
        event_type: str | None = None
    ) -> list[str]:
        query = "SELECT event_id FROM events WHERE DATE(created_at) = ?"
        params = [date]

        if event_type:
            query += " AND type = ?"
            params.append(event_type)

        with self.lock, connect(self.db_path) as conn:   
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()

        return [row[0] for row in rows]

    def list_event_ids_by_range(
            self,
            start_date: str,  # formaat: "YYYY-MM-DD"
            end_date: str,    # formaat: "YYYY-MM-DD"
            event_type: str | None = None
        ) -> list[str]:
        query = "SELECT event_id FROM events WHERE DATE(created_at) >= ? AND DATE(created_at) <= ?"
        params = [start_date, end_date]
        if event_type:
            query += " AND type = ?"
            params.append(event_type)
        with self.lock, connect(self.db_path) as conn:
            cursor = conn.execute(query, tuple(params))
            rows = cursor.fetchall()
        return [row[0] for row in rows]

    def get_event_by_id(self, event_id: str) -> tuple[str, BaseModel] | None:
        with self.lock, connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT type, content FROM events WHERE event_id = ?",
                (event_id,))
            row = cursor.fetchone()

        if row:
            event_type, content_json = row
            try:
                content_dict = orjson.loads(content_json)
                model_cls = EVENT_TYPE_TO_MODEL.get(event_type)
                if not model_cls:
                    print(f"Onbekend event_type '{event_type}' voor ID '{event_id}'")
                    return None
                validated = model_cls.model_validate(content_dict)
                return event_type, validated
            except Exception as e:
                print(f"Fout bij valideren {event_type} voor ID '{event_id}': {e}")
                return None
        return None
    
    def set_setting(self, key: str, value: str):
        with self.lock, connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))
            conn.commit()

    def get_setting(self, key: str) -> str | None:       
        with self.lock, connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value FROM settings WHERE key = ?",
                (key,))
            row = cursor.fetchone()
        if row:
            return row[0]
        return None
    

PROMPT_DB_PATH = 'modes_and_prompts.db'

class PromptManager:
    def __init__(self, db_path=PROMPT_DB_PATH):
        self.db_path = db_path
        self.system_prompt = ""
        self.dynamic_context = []
        self._lock = asyncio.Lock()

    # --- Synchronous methods for hotkey handlers ---
    def get_system_prompt_sync(self, prompt_name: str) -> str:
        try:
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute(
                    "SELECT system_prompt FROM prompts WHERE prompt_name = ?", (prompt_name,))
                row = cursor.fetchone()
            if row:
                content = row[0]
                now = datetime.now()
                return (content
                        .replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
                        .replace("{local_time}", now.strftime("%H:%M:%S")))
            else:
                logging.error(f"No system prompt found in DB for '{prompt_name}'")
                return f"System prompt '{prompt_name}' not found."
        except Exception as e:
            logging.error(f"DB error in get_system_prompt_sync: {e}")
            return "Error retrieving system prompt."

    def get_dynamic_context_sync(self, prompt_name="dynamic_context", summary="") -> list:
        try:
            with sqlite3.connect(self.db_path) as db:
                cursor = db.execute(
                    "SELECT dynamic_context FROM prompts WHERE prompt_name = ?", (prompt_name,))
                row = cursor.fetchone()
            if row:
                content = row[0]
                now = datetime.now()
                content = (content
                           .replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
                           .replace("{local_time}", now.strftime("%H:%M:%S"))
                           .replace("{summary}", summary))
                # print("dynamic context loaded")
                return [
                    {"role": "user", "content": content},
                    {"role": "assistant", "content": "OK!"}
                ]
            else:
                logging.error(f"No dynamic context found in DB for '{prompt_name}'")
                return []
        except Exception as e:
            logging.error(f"DB error in get_dynamic_context_sync: {e}")
            return []

    async def get_profile_voice(self, profile_name: str) -> str | None:   
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    cursor = await db.execute(
                        "SELECT voice FROM prompts WHERE prompt_name = ?", (profile_name,))
                    row = await cursor.fetchone()
                    await cursor.close()
                if row:
                    return row[0]
                return None
            except Exception as e:
                logging.error(f"DB error in get_profile_voice_async: {e}")      
                return None

    def load_default_prompts_sync(self, profile_name="default"):
        self.system_prompt = self.get_system_prompt_sync(profile_name)
        self.dynamic_context = self.get_dynamic_context_sync(profile_name)

    # --- Asynchronous methods for FastAPI endpoints ---
    async def load_default_prompts(self, profile_name="default"):
        print("load_default_prompts methode aangeroepen")
        # async with self._lock:
        self.system_prompt = await self.get_system_prompt(profile_name)
        self.dynamic_context = await self.get_dynamic_context(profile_name)
        print("system_prompt en dynamic_context geladen")


    async def list_prompt_names(self) -> list[str]:
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("SELECT prompt_name FROM prompts")
                rows = await cursor.fetchall()
                await cursor.close()
            return [row[0] for row in rows]
        
    async def get_raw_prompt_profile(self, prompt_name: str) -> dict[str, str]:
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "SELECT system_prompt, dynamic_context, voice FROM prompts WHERE prompt_name = ?",
                    (prompt_name,))
                row = await cursor.fetchone()
                await cursor.close()
            if row:
                return {
                    "system_prompt": row[0],
                    "dynamic_context": row[1],
                    "voice": row[2]
    }
            return {"system_prompt": "", "dynamic_context": "", "voice": None}
        
    async def delete_prompt(self, prompt_name: str):
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("DELETE FROM prompts WHERE prompt_name = ?", (prompt_name,))
                await db.commit()
            print(f"Prompt-profiel '{prompt_name}' verwijderd uit database.")

        
    async def get_system_prompt(self, prompt_name: str) -> str:
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    cursor = await db.execute(
                        "SELECT system_prompt FROM prompts WHERE prompt_name = ?", (prompt_name,))
                    row = await cursor.fetchone()
                    await cursor.close()
                if row:
                    content = row[0]
                    now = datetime.now()
                    # print(content)
                    return (content
                            .replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
                            .replace("{local_time}", now.strftime("%H:%M:%S")))
                else:
                    logging.error(f"No system prompt found async for '{prompt_name}'")
                    return f"System prompt '{prompt_name}' not found."
            except Exception as e:
                logging.error(f"DB error in get_system_prompt (async): {e}")
                return "Error retrieving system prompt."

    async def get_dynamic_context(self, prompt_name="dynamic_context", summary="") -> list:
        async with self._lock:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    cursor = await db.execute(
                        "SELECT dynamic_context FROM prompts WHERE prompt_name = ?", (prompt_name,))
                    row = await cursor.fetchone()
                    await cursor.close()
                if row:
                    content = row[0] or ""
                    now = datetime.now()
                    content = (content
                            .replace("{local_date}", now.strftime("%A, %Y-%m-%d"))
                            .replace("{local_time}", now.strftime("%H:%M:%S"))
                            .replace("{summary}", summary))
                    return [
                        {"role": "user", "content": content},
                        {"role": "assistant", "content": "OK!"}
                    ]
                else:
                    logging.error(f"No dynamic context found async for '{prompt_name}'")
                    return []
            except Exception as e:
                logging.error(f"DB error in get_dynamic_context (async): {e}")
                return []

    async def save_prompt_profile(self, profile: PromptProfile):
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO prompts (prompt_name, system_prompt, dynamic_context, voice)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(prompt_name) DO UPDATE SET
                        system_prompt=excluded.system_prompt,
                        dynamic_context=excluded.dynamic_context,
                        voice=excluded.voice  
                """, (profile.name, profile.system_prompt, profile.dynamic_context, profile.voice))
                await db.commit()
                print(f"Prompt-profiel '{profile.name}' opgeslagen in database.")


    async def set_default_system_prompt(self, new_system_prompt: str):
        async with self._lock:
            self.system_prompt = new_system_prompt
            # Optioneel: ook direct in de database opslaan
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute(
                    "UPDATE prompts SET system_prompt = ? WHERE prompt_name = ?",
                    (new_system_prompt, "default"))
                    await db.commit()
            except Exception as e:
                logging.error(f"DB error in set_default_system_prompt (async): {e}")

    async def set_default_dynamic_context(self, new_dynamic_context: list):
        async with self._lock:
            self.dynamic_context = new_dynamic_context
            # Optioneel: ook direct in de database opslaan
            try:
                # Sla op als string (bijvoorbeeld JSON)
                import json
                dynamic_context_str = json.dumps(new_dynamic_context)
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute(
                        "UPDATE prompts SET dynamic_context = ? WHERE prompt_name = ?",
                        (dynamic_context_str, "default"))
                    await db.commit()
            except Exception as e:
                logging.error(f"DB error in set_default_dynamic_context (async): {e}")

    def set_default_system_prompt(self, new_system_prompt: str):
        self.system_prompt = new_system_prompt

    def set_default_dynamic_context(self, new_dynamic_context: list):
        self.dynamic_context = new_dynamic_context

    def get_current_system_prompt(self):
        return self.system_prompt

    def get_current_dynamic_context(self):
        return self.dynamic_context
    
# === Voice UI ===
voices = {
    "Martin_int": "a5n9pJUnAhX4fn7lx3uo",
    "Frank": "gFwlAMshRYWaSeoMt2md",
    "Robert": "BtWabtumIemAotTjP5sk",
    "George": "Yko7PKHZNXotIFUBG7I9",
    "Educational_Elias": "bYS7cEY0uRew5lIOkGCu",
    "Will": "bIHbv24MWmeRgasZH58o",
    "David_conversational": "EozfaQ3ZX0esAp1cW5nG",
    "Harrison": "fCxG8OHm4STbIsWe4aT9"
}

    
async def main():
    
    os.system("cls")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    
    # Start de taak bij het opstarten
    asyncio.create_task(generate_model_audio_segments())

    whisper_transcriber.setup_key_handlers()  # Set up all key handlers once
    
    await initialize()

    try:
        while not shutdown_event.is_set() and not priority_input_event.is_set():
            user_input = await whisper_transcriber.start()
            await communication_manager.add_user_message(user_input)
            await communication_manager.process_incoming_message()

            print("\n>>>>>>  Thinking...  <<<<<<", end='')
            response_text = await chat_with_llm(client, await communication_manager.get_messages())
            await communication_manager.add_assistant_message(response_text)

    finally:
        logging.warning("Main loop finished.")

async def start_uvicorn():
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=5001, log_level="error")
    server = uvicorn.Server(config)
    await server.serve()

# Add this near the end of your file, before the if __name__ == "__main__": block
async def http_session_shutdown():
    if 'global_http_session' in globals() and not global_http_session.closed:
        await global_http_session.close()

def start_voice_ui():
    global root
    root = tk.Tk()
    voice_ui_app = VoiceUI(root, voices, communication_manager, prompt_manager, event_manager)
    root.mainloop()
    
if __name__ == "__main__":
    winloop.install()
    whisper_transcriber = WhisperTranscriber()
    communication_manager = CommunicationManager()
    prompt_manager = PromptManager()
    prompt_manager.load_default_prompts_sync()
    event_manager = EventManager()
    # Start GUI in aparte thread
    threading.Thread(target=start_voice_ui, daemon=True).start()
    
    
    async def run_all():
        await initialize_http_session()
        server = asyncio.create_task(start_uvicorn())
        main_task = asyncio.create_task(main())
        playback_task = asyncio.create_task(manage_audio_playback())
        tasks_agent_task = asyncio.create_task(tasks_agent())
        obsidian_agent_task = asyncio.create_task(obsidian_agent())
        save_idea_event_task = asyncio.create_task(save_idea_event())
        save_journal_event_task = asyncio.create_task(save_journal_event())
        text_consumer_task = asyncio.create_task(text_processor())
        tool_consumer_task = asyncio.create_task(tool_processor())
        async def shutdown_gui_when_done():
            await shutdown_event.wait()
            if root:
                await asyncio.to_thread(root.destroy)

        gui_shutdown_task = asyncio.create_task(shutdown_gui_when_done())

        await shutdown_event.wait()

        # Cancel alle taken
        server.cancel()
        playback_task.cancel()
        obsidian_agent_task.cancel()
        save_idea_event_task.cancel()
        save_journal_event_task.cancel()
        tasks_agent_task.cancel()
        main_task.cancel()
        text_consumer_task.cancel()
        tool_consumer_task.cancel()
        gui_shutdown_task.cancel()

        await http_session_shutdown()
        await asyncio.gather(
            server, playback_task, obsidian_agent_task, tasks_agent_task,
            main_task, text_consumer_task, tool_consumer_task, gui_shutdown_task,
            return_exceptions=True
    )
        sys.exit(0)
    asyncio.run(run_all())