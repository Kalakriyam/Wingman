import tkinter as tk
import tkinter.ttk as ttk
import tkinter.messagebox as messagebox
import tkinter.font as tkfont # Import font module
import tkinter.simpledialog as simpledialog
import requests
import orjson
import json
import asyncio
import copy # Needed for deep copy
import re
from sqlite3 import connect
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional
# from OAI_OAI_11LABS import update_voice_id, generate_model_audio_segments

# --- Classes ---
class MessageList(BaseModel):
    id: str
    messages: list[dict[str, str]]

class PromptProfile(BaseModel):       
    name: str
    system_prompt: str
    dynamic_context: str
    voice: Optional[str] = None

# --- Configuration ---
SERVER_BASE_URL = "http://127.0.0.1:5001"
UPDATE_VOICE_ENDPOINT = "/update_voice"
RELOAD_PROMPTS_ENDPOINT = "/reload_default_prompts"
MESSAGE_ENDPOINT = "/message" # Used for summary pull/push and message pull/push
PROMPT_CACHE_PATH = "prompt_profiles.json"
MODES_CACHE_PATH = "available_modes.json"

# --- Consistent Sender/Recipient Names ---
SENDER_NAME = "voice_ui"
RECIPIENT_NAME = "conversation_script"

# --- Consistent Action Types ---
ACTION_PULL_SUMMARY = "pull_summary"
ACTION_PULL_CONVERSATION = "pull_conversation"
ACTION_PUSH_SUMMARY = "push_summary" # Renamed
ACTION_PUSH_CONVERSATION = "push_conversation" # New

# --- UI ---

class VoiceUI:
    def __init__(self, root, communication_manager, prompt_manager, event_manager, settings_manager):
        self.root = root
        self.root.title("Voice UI")

        # --- GEOMETRY ATTEMPT 5: wm_manage ---
        self.root.update_idletasks()

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = screen_width // 2
        window_height = screen_height

        # 1. Withdraw the window initially to prevent flickering
        self.root.withdraw()

        # 2. Set the desired geometry (still asking for +0+0)
        initial_geometry = f"{window_width}x{window_height}+0+0"
        print(f"Setting geometry: {initial_geometry}")
        self.root.geometry(initial_geometry)

        # 3. Ask Tk to manage the window placement
        # This might interact differently with the window manager
        self.root.update_idletasks()
        # No explicit 'wm_manage', geometry + deiconify handles it.

        # 4. Deiconify (show) the window
        # The window manager places it based on the request
        self.root.deiconify()
        self.root.update_idletasks()

        # 5. Measure *after* showing
        actual_screen_x = self.root.winfo_rootx()
        print(f"Measured final X position: {actual_screen_x}")
        if actual_screen_x > 0:
             print(f"Note: Window manager still placed window at X={actual_screen_x}, creating a gap.")
             # At this point, attempting a negative offset failed before,
             # so we likely have to accept this gap or use platform tools.

        # --- End GEOMETRY ATTEMPT 5 ---
    
        self.communication_manager = communication_manager
        self.prompt_manager = prompt_manager
        self.event_manager = event_manager
        self.settings_manager = settings_manager
        # --- Load voices from settings ---
        self.voices = asyncio.run(self.settings_manager.get_all_voices())
        self.voice_names = list(self.voices.keys())

        if not self.voice_names:
            self.voice_names = ["(No Voices Found)"]
            self.voices = {"(No Voices Found)": "dummy_voice_id"}
        self.current_index = 0
        self.summary_text = None
        self.summary_scrollbar = None
        self.browse_status_label = None
        self.event_list_scrollbar = None
        self.specific_conversation_id = None

        self.prompts = {
        "default": {
            "name": "default",
            "original": {"system": "", "dynamic": ""},
            "current": {"system": "", "dynamic": ""},
            "modified": False,
            "voice": "Martin_int"},
        "obsidian": {
            "name": "obsidian",
            "original": {"system": "", "dynamic": ""},
            "current": {"system": "", "dynamic": ""},
            "modified": False,
            "voice": "George"},
        "code": {
            "name": "code",
            "original": {"system": "", "dynamic": ""},
            "current": {"system": "", "dynamic": ""},
            "modified": False,
            "voice": "Frank"}
            }

        self.style = ttk.Style()
        self.style.theme_use("clam") # Or another theme like 'vista', 'xpnative' if preferred

        # --- Message Data Storage ---
        self.original_messages: list[dict[str, str]] | None = None
        self.current_messages: list[dict[str, str]] | None = None
        self.messages_modified_flag: bool = False
        self.messages_window: tk.Toplevel | None = None
        self.messages_text_widget: tk.Text | None = None # Reference to widget in messages window

        # --- Main Frame ---
        self.main_frame = ttk.Frame(root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        try:
            # Try Segoe UI first - Increase sizes by ~1.5x
            default_size = 17 # Was 11
            header_size = 21  # Was 14
            editor_size = 17  # Was 11
            self.default_font = tkfont.Font(family="Segoe UI", size=default_size)
            self.header_font = tkfont.Font(family="Segoe UI", size=header_size, weight="bold")
            self.editor_font = tkfont.Font(family="Segoe UI", size=editor_size)
            print(f"Using Segoe UI font. Sizes: Default={default_size}, Header={header_size}, Editor={editor_size}")
        except tk.TclError:
            # Fallback to Verdana - Increase sizes by ~1.5x
            print("Segoe UI not found, falling back to Verdana.")
            default_size = 15 # Was 10
            header_size = 18  # Was 12
            editor_size = 15  # Was 10
            self.default_font = tkfont.Font(family="Verdana", size=default_size)
            self.header_font = tkfont.Font(family="Verdana", size=header_size, weight="bold")
            self.editor_font = tkfont.Font(family="Verdana", size=editor_size)
            print(f"Using Verdana font. Sizes: Default={default_size}, Header={header_size}, Editor={editor_size}")

        # --- Configure ttk Styles ---
        # Styles will inherit the new default_font size automatically
        self.style.configure(".", font=self.default_font)
        self.style.configure("TButton", font=self.default_font)
        self.style.configure("TLabel", font=self.default_font)
        self.style.configure("TEntry", font=self.default_font)

        # Prompt Editor State
        self.prompts_window: tk.Toplevel | None = None
        self.system_text_widget: tk.Text | None = None
        self.dynamic_text_widget: tk.Text | None = None
        self.prompts_modified_flag: bool = False
        self.current_prompt_profile: str = "default"  # actief profiel

        # --- Apply Specific Fonts ---
        # Voice Display (Use Header Font)
        self.voice_label = ttk.Label(self.main_frame, text=self.voice_names[self.current_index], font=self.header_font) # Apply header font
        self.voice_label.pack(pady=10)

        # Up/Down Buttons (Will use default style)
        self.button_frame = ttk.Frame(self.main_frame)
        self.button_frame.pack()
        self.up_button = ttk.Button(self.button_frame, text="▲", command=self.scroll_up, width=3)
        self.up_button.pack(side=tk.LEFT, padx=5)
        self.down_button = ttk.Button(self.button_frame, text="▼", command=self.scroll_down, width=3)
        self.down_button.pack(side=tk.LEFT, padx=5)


        # Send Button (Will use default style + Accent)
        self.send_button = ttk.Button(self.main_frame, text="Send Voice", command=self.send_current_voice, style="Accent.TButton") # Style includes font
        self.send_button.pack(pady=20)

        # Error & Status Labels (Use default style)
        self.error_label = ttk.Label(self.main_frame, text="", foreground="red", wraplength=400) # Increased wraplength?
        self.error_label.pack()
        self.status_label = ttk.Label(self.main_frame, text="", foreground="green", wraplength=400)
        self.status_label.pack()

        # --- Separator ---
        self.separator1 = ttk.Separator(self.main_frame, orient='horizontal')
        self.separator1.pack(fill='x', pady=10)

        # --- Modus-sectie ---
        self.modus_frame = ttk.Frame(self.main_frame)
        self.modus_frame.pack(pady=(10, 10))

        self.modus_label = ttk.Label(self.modus_frame, text="Modus:")
        self.modus_label.pack(side=tk.LEFT, padx=(0, 5))

        self.modus_var = tk.StringVar()
        self.modus_dropdown = ttk.Combobox(
            self.modus_frame,
            textvariable=self.modus_var,
            values=list(self.prompts.keys()),  # Gebruik promptprofielen
            state="readonly",
            width=20
        )
        self.modus_var.set(self.current_prompt_profile)  # Zet default

        self.modus_dropdown.pack(side=tk.LEFT, padx=(0, 5))        

        self.switch_modus_button = ttk.Button(self.modus_frame, text="Switch Mode", command=self._switch_modus)
        self.switch_modus_button.pack(side=tk.LEFT, padx=(0, 5))

        self.pull_modus_button = ttk.Button(self.modus_frame, text="Pull Curr. Mode", command=self._pull_current_mode)
        self.pull_modus_button.pack(side=tk.LEFT, padx=(5, 0))

        self.add_modus_button = ttk.Button(self.modus_frame, text="Add Mode", command=self._add_modus)      
        self.add_modus_button.pack(side=tk.LEFT, padx=(5, 0))

        self._refresh_available_modes()
        self._pull_current_mode()

        # --- Separator ---
        self.separator_browse = ttk.Separator(self.main_frame, orient='horizontal')
        self.separator_browse.pack(fill='x', pady=10)

        # --- Browse Section ---
        self.browse_label = ttk.Label(self.main_frame, text="Browse Events", font=self.header_font)
        self.browse_label.pack(pady=(10, 5))

        self.browse_frame = ttk.Frame(self.main_frame)
        self.browse_frame.pack(pady=(0, 10))

        self.browse_conversations_button = ttk.Button(
            self.browse_frame, text="Conversations",
            command=lambda: self.open_browse_window("ConversationState"))
        self.browse_conversations_button.pack(side=tk.LEFT, padx=5)

        self.browse_ideas_button = ttk.Button(     
            self.browse_frame, text="Ideas",
            command=lambda: self.open_browse_window("IdeaEvent"))
        self.browse_ideas_button.pack(side=tk.LEFT, padx=5)

        self.browse_journal_button = ttk.Button(   
            self.browse_frame, text="Journal Events",
            command=lambda: self.open_browse_window("JournalEvent"))
        self.browse_journal_button.pack(side=tk.LEFT, padx=5)
        # --- Separator ---
        self.separator1 = ttk.Separator(self.main_frame, orient='horizontal')
        self.separator1.pack(fill='x', pady=10)

        # --- Prompts Control Section ---
        self.prompts_control_frame = ttk.Frame(self.main_frame)
        self.prompts_control_frame.pack(pady=(0, 5))

        # Pull Prompts Button
        self.pull_prompts_button = ttk.Button(
            self.prompts_control_frame,
            text="Pull Prompts",
            command=self._handle_pull_prompts
        )
        self.pull_prompts_button.pack(side=tk.LEFT, padx=5)

        # Edit Prompts Button
        self.edit_prompts_button = ttk.Button(
            self.prompts_control_frame,
            text="Edit Prompts",
            command=self.edit_prompt_profile,  # Verbind direct met de nieuwe functie
            state=tk.NORMAL  # Zorg dat de knop altijd beschikbaar is
        )
        self.edit_prompts_button.pack(side=tk.LEFT, padx=5)

        self.push_prompts_button = ttk.Button(self.prompts_control_frame, text="Push Prompts", command=self._push_and_close_prompt, state=tk.DISABLED)
        self.push_prompts_button.pack(side=tk.LEFT, padx=5)

        self.refresh_modus_button = ttk.Button(self.prompts_control_frame, text="Trigger Refresh", command=self.reload_prompts)
        self.refresh_modus_button.pack(side=tk.LEFT)

        # Dropdown voor prompt-profielen
        self.prompt_profile_var = tk.StringVar()
        self.prompt_profile_dropdown = ttk.Combobox(
            self.prompts_control_frame,
            textvariable=self.prompt_profile_var,
            values=list(self.prompts.keys()),
            state="readonly",
            width=20
        )
        self.prompt_profile_dropdown.set(self.current_prompt_profile)
        self.prompt_profile_dropdown.bind("<<ComboboxSelected>>", self._on_prompt_profile_selected)
        self.prompt_profile_dropdown.pack(side=tk.LEFT, padx=5, pady=5)
        self._refresh_prompt_profiles()

        # --- Prompt Status Label ---
        self.prompts_status_label = ttk.Label(self.main_frame, text="Prompts: None")
        self.prompts_status_label.pack(pady=(0, 10))

        # --- Separator for Messages ---
        self.separator2 = ttk.Separator(self.main_frame, orient='horizontal')
        self.separator2.pack(fill='x', pady=10)

        # --- Message Control Section ---
        self.message_control_frame = ttk.Frame(self.main_frame) # Buttons use default style
        self.message_control_frame.pack(pady=(10, 5))

        self.pull_messages_button = ttk.Button(self.message_control_frame, text="Pull Messages", command=self.pull_messages)
        self.pull_messages_button.pack(side=tk.LEFT, padx=5)

        self.edit_messages_button = ttk.Button(self.message_control_frame, text="Edit Messages", command=self.edit_messages, state=tk.DISABLED)
        self.edit_messages_button.pack(side=tk.LEFT, padx=5)

        # Renamed command to push_main_messages
        self.push_messages_button = ttk.Button(self.message_control_frame, text="Push Messages", command=self.push_main_messages, state=tk.DISABLED)
        self.push_messages_button.pack(side=tk.LEFT, padx=5)

        self.clear_messages_button = ttk.Button(self.message_control_frame, text="Clear Messages", command=self.clear_local_messages, state=tk.DISABLED)
        self.clear_messages_button.pack(side=tk.LEFT, padx=5)

        # --- Message Status Label ---
        self.messages_status_label = ttk.Label(self.main_frame, text="Messages: None") # Will use default style
        self.messages_status_label.pack(pady=(0, 10))


        # --- Separator for Summary ---
        self.summary_separator = ttk.Separator(self.main_frame, orient='horizontal')
        self.summary_separator.pack(fill='x', pady=(15, 5))

        # --- Summary Section ---
        self.summary_label = ttk.Label(self.main_frame, text="Conversation Summary:") # Will use default style
        self.summary_label.pack(pady=(5, 2))

        # --- NEW: Use tk.Text for Summary ---
        self.summary_frame = ttk.Frame(self.main_frame) # Frame to hold text and scrollbar
        self.summary_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.summary_scrollbar = ttk.Scrollbar(self.summary_frame)
        self.summary_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.summary_entry = tk.Text( # Changed from tk.Entry
            self.summary_frame,
            height=4, # Set initial height (adjust as needed)
            wrap=tk.WORD, # Enable word wrapping
            font=self.default_font, # Apply the larger font
            yscrollcommand=self.summary_scrollbar.set
        )
        self.summary_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.summary_scrollbar.config(command=self.summary_entry.yview)
        # --- End NEW ---

        self.summary_button_frame = ttk.Frame(self.main_frame) # Buttons use default style
        self.summary_button_frame.pack()
        self.pull_summary_button = ttk.Button(self.summary_button_frame, text="Pull Summary", command=self.pull_summary)
        self.pull_summary_button.pack(side=tk.LEFT, padx=(0, 5))

        # --- ADDED Summarize Button ---
        self.summarize_button = ttk.Button(self.summary_button_frame, text="Summarize Messages", command=self._summarize_messages_placeholder, state=tk.DISABLED)
        self.summarize_button.pack(side=tk.LEFT, padx=5)
        # --- END ADDED ---

        self.push_summary_button = ttk.Button(self.summary_button_frame, text="Push Summary", command=self.push_summary)
        self.push_summary_button.pack(side=tk.LEFT, padx=(5, 0))

        # --- Configure Accent Style ---
        self.style.configure("Accent.TButton", background="#4CAF50", foreground="white") # Font already set by root style "."
        self.style.map("Accent.TButton",
                       background=[("active", "#388E3C"), ("pressed", "#2E7D32")],
                       foreground=[("active", "white"), ("pressed", "white")])

        # Initialize display and button states
        self.update_voice_display()
        self._update_messages_status_and_buttons() # Initial update for message buttons/status

    def is_prompt_loaded(self, profile_name: str) -> bool:
        return profile_name in self.prompts
    
    # --- Mode Controls ---
    def _switch_modus(self):
        self._clear_messages()
        selected_modus = self.modus_var.get()
        if not selected_modus:
            self.error_label.config(text="Geen modus geselecteerd.")
            return

        try:
            asyncio.run(self.communication_manager.set_current_mode_async(selected_modus))
            self.status_label.config(text=f"Modus gewisseld naar '{selected_modus}'")
        except Exception as e:
            self.error_label.config(text=f"Fout bij wisselen modus: {e}")

    def open_browse_window(self, event_type: str):
        print("open_browse_window aangeroepen")
        # Sluit bestaand browse venster als het er is
        if hasattr(self, 'browse_window') and self.browse_window and self.browse_window.winfo_exists():
            self.browse_window.destroy()

        # --- Create the necessary Tkinter variables FIRST ---
        # Event type dropdown variable
        self.event_type_options = [
            ("Conversations", "ConversationState"),
            ("Ideas", "IdeaEvent"),
            ("Journal Events", "JournalEvent")
        ]
        event_type_labels = [label for label, _ in self.event_type_options]
        # Determine the default value based on the incoming event_type parameter
        default_label = "Conversations" # Fallback default
        for label, val in self.event_type_options:
            if val == event_type:
                default_label = label
                break
        self.event_type_var = tk.StringVar(value=default_label)

        # Periode dropdown variable
        self.period_options = ["Today", "2 Days", "3 Days", "1 Week", "Pick Date", "Pick Range"]
        self.period_var = tk.StringVar(value=self.period_options[0]) # Default to "Today"

        ## --- NOW call load_events, as the variables exist ---
        ## Note: We call load_events *before* creating the window to ensure data is ready
        ## This might feel slightly backwards, but avoids the AttributeError
        ## self.load_events() # Initial load call happens after variables are set

        ## # --- Create the Browse Window ---
        ## self.browse_window = tk.Toplevel(self.root)
        ## self.browse_window.title(f"Browse {event_type}")
        ## self.browse_window.geometry("1100x800+0+0")

        # 1 ─ create the window but keep it hidden
        self.browse_window = tk.Toplevel(self.root)
        self.browse_window.withdraw()                 # don’t flash an incorrectly-sized window
        self.browse_window.title(f"Browse {event_type}")
        self.browse_window.update_idletasks()         # make geometry information valid

        # 2 ─ measure decorations (border + title-bar)
        border_px = self.browse_window.winfo_rootx() - self.browse_window.winfo_x()
        title_px  = self.browse_window.winfo_rooty() - self.browse_window.winfo_y()

        # 3 ─ screen size
        screen_w  = self.browse_window.winfo_screenwidth()
        screen_h  = self.browse_window.winfo_screenheight()

        # 4 ─ target client size = 50 % width, 100 % height minus decorations
        target_w  = screen_w // 2 - border_px * 2
        target_h  = screen_h - title_px - border_px   # title on top, border at bottom

        # 5 ─ apply geometry and show the window
        self.browse_window.geometry(f"{target_w}x{target_h}+0+0")
        self.browse_window.deiconify()
        self.browse_window.focus_force()


        # Titel
        title_label = ttk.Label(self.browse_window, text=f"Browse {event_type}", font=self.header_font)
        title_label.pack(pady=(10, 10))

        # --- Dropdowns Frame ---
        dropdowns_frame = ttk.Frame(self.browse_window)
        dropdowns_frame.pack(fill=tk.X, pady=(10, 10), padx=10)

        # --- Linker controls (dropdowns + refresh) ---
        left_controls_frame = ttk.Frame(dropdowns_frame)
        left_controls_frame.pack(side=tk.LEFT)

        # Periode dropdown widget (uses the pre-created self.period_var)
        period_dropdown = ttk.Combobox(
            left_controls_frame, textvariable=self.period_var, values=self.period_options, state="readonly", width=12
        )
        period_dropdown.pack(side=tk.LEFT, padx=(0, 10))
        # Bind trace *after* combobox creation if needed, but load_events already called once
        self.period_var.trace_add("write", lambda *args: self.load_events())


        # Event type dropdown widget (uses the pre-created self.event_type_var)
        event_type_dropdown = ttk.Combobox(
            left_controls_frame, textvariable=self.event_type_var, values=event_type_labels, state="readonly", width=16
        )
        event_type_dropdown.pack(side=tk.LEFT)
        # Bind trace *after* combobox creation if needed
        self.event_type_var.trace_add("write", lambda *args: self.load_events())


        self.refresh_events_button = ttk.Button(
            left_controls_frame,
            text="Refresh",
            command=self.load_events  # Command directly calls load_events
        )
        self.refresh_events_button.pack(side=tk.LEFT, padx=(10, 0))

        # --- Rechterkant: Exit knop ---
        self.exit_browse_button = ttk.Button(dropdowns_frame, text="Exit", command=self._close_browse_window)
        self.exit_browse_button.pack(side=tk.RIGHT, padx=(10, 0))

        # --- Button Row ---
        button_row = ttk.Frame(self.browse_window)
        button_row.pack(fill=tk.X, padx=10, pady=(0, 10))

        # --- Knoppen in button_row ---
        self.set_specific_button = ttk.Button(
            button_row,
            text="Set Specific",
            command=self._set_specific_state,
            state=tk.DISABLED
        )
        self.set_specific_button.pack(side=tk.LEFT, padx=(0, 5))

        self.open_event_button = ttk.Button(button_row, text="Open", command=self._open_event)
        self.open_event_button.pack(side=tk.LEFT, padx=(0, 5))

        self.delete_event_button = ttk.Button(button_row, text="Delete", command=self._delete_event)
        self.delete_event_button.pack(side=tk.LEFT, padx=(0, 5))

        self.save_summary_button = ttk.Button(button_row, text="Save Summary", command=self._save_summary)
        self.save_summary_button.pack(side=tk.LEFT, padx=(10, 5))

        self.undo_details_button = ttk.Button(button_row, text="Undo Changes", command=self._undo_changes_to_summary)
        self.undo_details_button.pack(side=tk.LEFT, padx=(5, 0))


        # --- statuslabel ---
        self.browse_status_label = ttk.Label(self.browse_window, text="", foreground="green")
        self.browse_status_label.pack(anchor="w", padx=10, pady=(0, 5))


        # --- Main Split Frame ---
        main_split = ttk.Frame(self.browse_window)
        main_split.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Event ID List (links) ---
        event_list_frame = ttk.Frame(main_split)
        event_list_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), expand=False)

        event_list_label = ttk.Label(event_list_frame, text="Event IDs")
        event_list_label.pack(anchor="w")

        # Initialize event_id_listbox and scrollbar *before* load_events populates it
        self.event_id_listbox = tk.Listbox(event_list_frame, width=17, height=30)
        self.event_id_listbox.pack(side=tk.LEFT, fill=tk.Y, expand=True)

        self.event_list_scrollbar = ttk.Scrollbar(event_list_frame, orient=tk.VERTICAL, command=self.event_id_listbox.yview)
        self.event_id_listbox.config(yscrollcommand=self.event_list_scrollbar.set)
        self.event_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.event_id_listbox.config(font=self.editor_font)
        self.event_id_listbox.bind("<<ListboxSelect>>", self.show_event_details)

        # --- Event Details (rechts) ---
        details_frame = ttk.Frame(main_split)
        details_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        details_label = ttk.Label(details_frame, text="Event Details")
        details_label.pack(anchor="w")

        # --- Summary Frame boven messages ---
        self.summary_frame = ttk.Frame(details_frame) # Re-use the attribute name, that's fine
        self.summary_frame.pack(fill=tk.X, pady=(0, 10))

        # Initialize summary_text and scrollbar *before* load_events tries to clear it
        summary_scrollbar_browse = ttk.Scrollbar(self.summary_frame, orient=tk.VERTICAL) # Use a distinct variable name if needed
        summary_scrollbar_browse.pack(side=tk.RIGHT, fill=tk.Y)

        self.summary_text = tk.Text( # This will be the one used by load_events/show_details
            self.summary_frame,
            height=3,
            wrap=tk.WORD,
            font=self.editor_font,
            yscrollcommand=summary_scrollbar_browse.set,
            state=tk.DISABLED
        )
        self.summary_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        summary_scrollbar_browse.config(command=self.summary_text.yview)


        # Initialize event_details_text and scrollbar *before* load_events tries to clear it
        self.event_details_text = tk.Text(details_frame, wrap=tk.WORD, height=30, font=self.editor_font)
        self.details_scrollbar = ttk.Scrollbar(details_frame, orient=tk.VERTICAL, command=self.event_details_text.yview)
        self.event_details_text.config(yscrollcommand=self.details_scrollbar.set)
        self.details_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.event_details_text.pack(fill=tk.BOTH, expand=True)

        # --- Call load_events AGAIN here to populate the listbox and reset fields ---
        # This ensures the widgets exist before population/resetting occurs
        self.load_events()

    def _close_browse_window(self):
        if hasattr(self, 'browse_window') and self.browse_window and self.browse_window.winfo_exists():
            self.browse_window.destroy()
            self.browse_window = None


        # --- Event ophalen en tonen ---
    def load_events(self):
        """Load events directly from the EventManager."""
        print("--- load_events CALLED ---") # Start marker

        # Ensure browse window and listbox exist before proceeding
        if not hasattr(self, 'browse_window') or not self.browse_window or not self.browse_window.winfo_exists() or \
           not hasattr(self, 'event_id_listbox') or not self.event_id_listbox:
            print("load_events: Browse window or listbox not ready. Aborting.")
            return

        # Haal de specifieke conversation ID op
        try:
            self.specific_conversation_id = self.event_manager.get_setting("specific_conversation_id")
            print(f"Specific Conversation ID loaded: {self.specific_conversation_id}")
        except Exception as e:
            print(f"Kon specifieke conversatie niet ophalen: {e}")
            self.specific_conversation_id = None

        self.event_id_map = {}  # display_id → full_id

        # Haal gekozen event_type op
        try:
            event_type_label = self.event_type_var.get()
            # Find the corresponding value ('ConversationState', 'IdeaEvent', etc.)
            event_type = next((val for label, val in self.event_type_options if label == event_type_label), None)
            if not event_type:
                 print(f"ERROR: Could not find event type value for label: {event_type_label}")
                 return # Stop if type is invalid
            print(f"Selected Event Type Label: {event_type_label}, Value: {event_type}")
        except Exception as e:
            print(f"ERROR reading event_type_var: {e}")
            # Optionally set a default or return
            event_type = "ConversationState" # Fallback example
            print(f"Falling back to event_type: {event_type}")
            # return # Or maybe just return here

        # Bepaal de datums op basis van de periode-dropdown
        try:
            period = self.period_var.get()
            print(f"Selected Period: {period}")
            today = datetime.today().date()

            if period == "Today":
                dates = [today.strftime("%Y-%m-%d")]
            elif period == "2 Days":
                # Correct range includes today and yesterday
                dates = [(today - timedelta(days=1)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
            elif period == "3 Days":
                 # Correct range includes today and two days prior
                dates = [(today - timedelta(days=2)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
            elif period == "1 Week":
                 # Correct range includes today and six days prior
                dates = [(today - timedelta(days=6)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
            # Add handling for "Pick Date" and "Pick Range" if implemented later
            else: # Default/fallback
                dates = [today.strftime("%Y-%m-%d")]
            print(f"Calculated Date(s): {dates}")
        except Exception as e:
            print(f"ERROR reading period_var or calculating dates: {e}")
            dates = [datetime.today().date().strftime("%Y-%m-%d")] # Fallback
            print(f"Falling back to dates: {dates}")
            # return # Or return

        event_ids = [] # Initialize
        try:
            print(f"Calling EventManager with dates: {dates}, event_type: {event_type}")
            # Directe aanroep van de EventManager
            if len(dates) == 1:
                event_ids = self.event_manager.list_event_ids_by_date(dates[0], event_type)
            elif len(dates) == 2:
                event_ids = self.event_manager.list_event_ids_by_range(dates[0], dates[1], event_type)
            else: # Should not happen with current logic, but good practice
                event_ids = []
            print(f"EventManager returned event IDs: {event_ids}") # <<< IMPORTANT PRINT
            if event_ids is None: # Explicitly check for None return
                 print("WARNING: EventManager returned None for event IDs. Treating as empty list.")
                 event_ids = []

        except Exception as e:
            print(f"!!! EXCEPTION during EventManager.list_event_ids: {e}")
            # Optionally display this error in the UI status label
            if hasattr(self, 'browse_status_label') and self.browse_status_label:
                 self.browse_status_label.config(text=f"Error loading events: {e}", foreground="red")
            event_ids = []

        # Update de UI met de opgehaalde events
        print("Clearing event_id_listbox...")
        self.event_id_listbox.delete(0, tk.END)
        print(f"Populating listbox with {len(event_ids)} items...")
        if not event_ids:
             print("No event IDs found to display.")
        else:
            for event_id in event_ids:
                if not event_id or not isinstance(event_id, str):
                    print(f"  Skipping invalid event_id: {event_id}")
                    continue

                # --- CORRECTED display_id generation ---
                # Assuming the timestamp is always the last 14 characters
                display_id = event_id[-14:] if len(event_id) >= 14 else event_id
                # --- End Correction ---

                if event_id == self.specific_conversation_id:
                    display_id += " ★"
                    print(f"  Adding display_id: {display_id} (Specific) from Full ID: {event_id}")
                else:
                    print(f"  Adding display_id: {display_id} from Full ID: {event_id}")

                self.event_id_map[display_id] = event_id # Store mapping
                self.event_id_listbox.insert(tk.END, display_id)

        # Reset de details en summary velden
        print("Resetting detail/summary text fields...")
        try:
            if hasattr(self, 'event_details_text') and self.event_details_text:
                # Details text should be editable when cleared, then disabled? Usually populated on selection.
                self.event_details_text.config(state=tk.NORMAL)
                self.event_details_text.delete("1.0", tk.END)
                self.event_details_text.config(state=tk.DISABLED) # Disable until selection
            else: print("event_details_text widget not found for reset.")

            if hasattr(self, 'summary_text') and self.summary_text:
                self.summary_text.config(state=tk.NORMAL)
                self.summary_text.delete("1.0", tk.END)
                self.summary_text.config(state=tk.DISABLED) # Disable until selection
            else: print("summary_text widget not found for reset.")
            print("Detail/summary fields reset.")
        except tk.TclError as e:
            print(f"TclError resetting text fields (might be closing): {e}")
        except Exception as e:
             print(f"ERROR resetting text fields: {e}")
        print("--- load_events FINISHED ---")

    def show_specific_conversation_state(self, event_id: str):
        """Toon een specifieke ConversationState direct via de EventManager."""
        print("show_specific_conversation_state aangeroepen")

        try:
            # Haal het event-object direct op via de EventManager
            result = self.event_manager.get_event_by_id(event_id)
            if not result:
                self.error_label.config(text=f"Event met ID '{event_id}' niet gevonden.")
                return

            event_type, event_obj = result
            if event_type != "ConversationState":
                self.error_label.config(text=f"Event met ID '{event_id}' is geen ConversationState.")
                return

            # Toon de summary als die er is
            summary = event_obj.summary
            self.summary_text.config(state=tk.NORMAL)
            self.summary_text.delete("1.0", tk.END)
            self.summary_text.insert("1.0", summary)
            self._adjust_summary_height(summary)
            self.summary_text.config(state=tk.NORMAL)

            # Haal de messages op via de EventManager    
            list_id = event_obj.messages_list_file
            if list_id:
                messages = self.event_manager.load_list(list_id)
                formatted = self._format_messages_for_display(messages)
            else:
                formatted = "(Geen messages_list_file gevonden in ConversationState)"

        except Exception as e:
            formatted = f"Fout bij ophalen details: {e}"

        # Update de event details in de UI
        self.event_details_text.config(state=tk.NORMAL)
        self.event_details_text.delete("1.0", tk.END)
        self.event_details_text.insert("1.0", formatted)
        self.event_details_text.config(state=tk.DISABLED)
        self.event_details_text.see(tk.END)

    def show_event_details(self, event):
        """Toon de details van een geselecteerd event rechtstreeks via de EventManager."""
        print("\n--- show_event_details CALLED ---") # Start marker

        # Ensure necessary widgets exist
        if not hasattr(self, 'event_id_listbox') or not self.event_id_listbox or \
           not hasattr(self, 'event_details_text') or not self.event_details_text or \
           not hasattr(self, 'summary_text') or not self.summary_text:
            print("show_event_details: Widgets not ready. Aborting.")
            return

        selection = self.event_id_listbox.curselection()
        if not selection:
            print("No item selected in listbox.")
            return

        try:
            selected_index = selection[0]
            display_id = self.event_id_listbox.get(selected_index)
            print(f"Selected Display ID: {display_id}")

            # Retrieve full ID, handle potential missing key robustly
            event_id = self.event_id_map.get(display_id)
            if not event_id:
                # Maybe the star needs stripping if it wasn't removed?
                display_id_stripped = display_id.removesuffix(" ★").strip()
                event_id = self.event_id_map.get(display_id_stripped)
                if not event_id:
                    print(f"ERROR: Full event ID not found in map for display_id: '{display_id}'")
                    if hasattr(self, 'browse_status_label') and self.browse_status_label:
                        self.browse_status_label.config(text=f"Error: Cannot find full ID for {display_id}", foreground="red")
                    return
                else:
                    print(f"Found full ID after stripping star: {event_id}")
            else:
                print(f"Retrieved Full Event ID: {event_id}")


            event_type_label = self.event_type_var.get()
            event_type_from_dropdown = next((val for label, val in self.event_type_options if label == event_type_label), None) # Use a different variable name
            print(f"Event type from dropdown: {event_type_from_dropdown}") # See what dropdown thinks type is

            # Get the event object using the full ID
            print(f"Calling EventManager.get_event_by_id for: {event_id}")
            result = self.event_manager.get_event_by_id(event_id)

            if not result:
                print(f"ERROR: EventManager.get_event_by_id returned None for ID: {event_id}")
                if hasattr(self, 'browse_status_label') and self.browse_status_label:
                     self.browse_status_label.config(text=f"Error: Event {event_id} not found.", foreground="red")
                # Clear fields if event not found
                self.summary_text.config(state=tk.NORMAL)
                self.summary_text.delete("1.0", tk.END)
                self.summary_text.config(state=tk.DISABLED)
                self.event_details_text.config(state=tk.NORMAL)
                self.event_details_text.delete("1.0", tk.END)
                self.event_details_text.config(state=tk.DISABLED)
                return

            # Unpack result
            actual_event_type, event_obj = result
            print(f"EventManager returned event type: {actual_event_type}")
            # print(f"Event Object (type {type(event_obj)}): {event_obj}") # Can be verbose

            # Store original data for undo (if needed)
            # Be careful with deep copies if objects are large or complex
            try:
                self.original_event_data = event_obj.model_dump() if hasattr(event_obj, 'model_dump') else vars(event_obj).copy()
                print("Stored original event data for undo.")
            except Exception as copy_e:
                print(f"Warning: Could not store original event data: {copy_e}")
                self.original_event_data = None

            self.current_event_id = event_id # Store current ID

            # --- Update Summary Text ---
            summary = ""
            if hasattr(event_obj, "summary"):
                summary = event_obj.summary
                print(f"Found summary: '{summary}'")
            else:
                print("Event object has no 'summary' attribute.")

            self.summary_text.config(state=tk.NORMAL)
            self.summary_text.delete("1.0", tk.END)
            if summary: # Only insert if not empty
                self.summary_text.insert("1.0", summary)
            self.summary_text.config(state=tk.NORMAL) # Keep NORMAL for now if needed for _adjust_summary_height
            # self._adjust_summary_height(summary) # Call adjustment if needed
            # self.summary_text.config(state=tk.DISABLED) # Disable AFTER potential adjustment


            # --- Update Event Details Text ---
            formatted = ""
            if actual_event_type == "ConversationState":
                print("Event is ConversationState. Looking for messages_list_file.")
                list_id = getattr(event_obj, "messages_list_file", None)
                if list_id:
                    print(f"Found messages_list_file ID: {list_id}. Loading list...")
                    try:
                        messages = self.event_manager.load_list(list_id)
                        if messages is not None:
                            print(f"Loaded {len(messages)} messages.")
                            formatted = self._format_messages_for_display(messages)
                            # print(f"Formatted Messages:\n{formatted[:500]}...") # Print start of formatted text
                        else:
                            print("EventManager.load_list returned None.")
                            formatted = f"(Could not load messages for list ID: {list_id})"
                    except Exception as load_e:
                        print(f"!!! EXCEPTION loading list '{list_id}': {load_e}")
                        formatted = f"(Error loading messages: {load_e})"
                else:
                    print("No messages_list_file attribute found in ConversationState object.")
                    formatted = "(No messages_list_file found in ConversationState)"
            else:
                print(f"Event is '{actual_event_type}'. Formatting as JSON.")
                try:
                    # Use model_dump if available (Pydantic), otherwise vars or repr
                    if hasattr(event_obj, 'model_dump_json'):
                         formatted = event_obj.model_dump_json(indent=2)
                    elif hasattr(event_obj, 'model_dump'):
                         formatted = json.dumps(event_obj.model_dump(), indent=2, ensure_ascii=False)
                    else:
                         formatted = json.dumps(vars(event_obj), indent=2, default=str, ensure_ascii=False) # Fallback
                    # print(f"Formatted JSON:\n{formatted[:500]}...") # Print start of JSON
                except Exception as json_e:
                     print(f"!!! EXCEPTION formatting event object as JSON: {json_e}")
                     formatted = f"(Error formatting event details: {json_e})"

            # Update the UI text widget
            print("Updating event_details_text widget...")
            self.event_details_text.config(state=tk.NORMAL)
            self.event_details_text.delete("1.0", tk.END)
            self.event_details_text.insert("1.0", formatted)
            self.event_details_text.config(state=tk.DISABLED) # Disable after inserting
            self.event_details_text.see("1.0") # Scroll to top
            print("event_details_text widget updated.")

            # Activate the Set Specific-knop als er een geldige selectie is
            if hasattr(self, 'set_specific_button'):
                self.set_specific_button.config(state=tk.NORMAL)
                print("Set Specific button enabled.")

        except tk.TclError as e:
             # Can happen if the listbox/window is destroyed during selection
             print(f"TclError in show_event_details (likely widget destroyed): {e}")
        except Exception as e:
            print(f"!!! UNEXPECTED EXCEPTION in show_event_details: {e}")
            import traceback
            traceback.print_exc() # Print full traceback for unexpected errors
            if hasattr(self, 'browse_status_label') and self.browse_status_label:
                self.browse_status_label.config(text=f"Error displaying details: {e}", foreground="red")

        print("--- show_event_details FINISHED ---")


    def _set_specific_state(self):
        """Set a specific conversation state directly via EventManager."""
        selection = self.event_id_listbox.curselection()
        if not selection:
            self.status_label.config(text="Geen event geselecteerd.")
            return

        display_id = self.event_id_listbox.get(selection[0])
        full_event_id = self.event_id_map.get(display_id)
        if not full_event_id:
            self.error_label.config(text="Kon volledige event ID niet vinden.")
            return

        try:
            # Directe aanroep van de EventManager
            self.event_manager.set_setting("specific_conversation_id", full_event_id)
            self.status_label.config(text=f"Specifieke conversatie ingesteld op {full_event_id}")
            self.load_events()
            self.show_specific_conversation_state(full_event_id)
        except Exception as e:
            self.error_label.config(text=f"Fout bij instellen specifieke state: {e}")
    def _adjust_summary_height(self, text: str):
        lines = text.count("\n") + 1
        lines = min(max(lines, 3), 5)  # minimaal 3, maximaal 5
        self.summary_text.config(height=lines)


    def _delete_event(self):
        """Delete an event directly via EventManager."""
        selection = self.event_id_listbox.curselection()
        if not selection:
            messagebox.showwarning("Geen selectie", "Selecteer eerst een event om te verwijderen.")
            return

        display_id = self.event_id_listbox.get(selection[0])
        event_id = self.event_id_map.get(display_id, display_id)

        response = messagebox.askyesnocancel("Bevestig verwijderen", f"Weet je zeker dat je '{event_id}' wilt verwijderen?", parent=self.browse_window)

        if response is None or response is False:  
            return

        try:
            # Directe aanroep van de EventManager
            success = self.event_manager.delete_event(event_id)
            if success:
                if self.browse_status_label:
                    self.browse_status_label.config(text=f"Event '{event_id}' is verwijderd.") 
                self.current_event_id = None
                self.load_events()  # Refresh lijst
                self.event_details_text.config(state=tk.NORMAL)
                self.event_details_text.delete("1.0", tk.END)
                self.event_details_text.config(state=tk.DISABLED)
            else:
                messagebox.showerror("Fout", f"Event '{event_id}' kon niet worden verwijderd.", parent=self.browse_window)
        except Exception as e:
            messagebox.showerror("Fout", f"Verwijderen mislukt: {e}", parent=self.browse_window)
            
    def _format_messages_for_display(self, messages: list[dict[str, str]]) -> str:
        output = []
        for msg in messages:
            role = msg.get("role", "").upper()
            content = msg.get("content", "").strip()
            output.append(f"--- {role}: ---\n{content}\n")
        return "\n".join(output)
    
    # --- Voice Controls ---
    def scroll_up(self):
        self.current_index = (self.current_index - 1) % len(self.voice_names)
        self.update_voice_display()

    def scroll_down(self):
        self.current_index = (self.current_index + 1) % len(self.voice_names)
        self.update_voice_display()

    def update_voice_display(self):
        # self.voice_label.config(text=f"{self.voice_names[self.current_index]}: {self.voices[self.voice_names[self.current_index]]}")
        self.voice_label.config(text=f"{self.voice_names[self.current_index]}")

    def _clear_messages(self):
        """Clears status and error messages."""
        self.error_label.config(text="")
        self.status_label.config(text="")

    def send_current_voice(self):
        self._clear_messages()
        voice_name = self.voice_names[self.current_index]

        try:
            asyncio.run(self.communication_manager.push_voice_update(voice_name))
            self.status_label.config(text=f"Stem bijgewerkt naar {voice_name}")
        except Exception as e:
            self.error_label.config(text=f"Fout bij bijwerken stem: {e}")

             
    def _refresh_available_modes(self):
        """Refresh the list of available modes directly from the PromptManager."""
        self._clear_messages()
        try:
            # Directe aanroep van de asynchrone PromptManager methode
            modes = asyncio.run(self.prompt_manager.list_prompt_names())

            # Update de dropdowns
            self.modus_dropdown['values'] = modes
            if self.modus_var.get() not in modes:
                self.modus_var.set(modes[0] if modes else "")
            with open(MODES_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(modes, f)

            self.status_label.config(text="Modi succesvol vernieuwd.")
        except Exception as e:
            self.error_label.config(text=f"Fout bij vernieuwen modi: {e}")
            try:
                # Fallback: laad modi uit de lokale cache
                with open(MODES_CACHE_PATH, "r", encoding="utf-8") as f:
                    modes = json.load(f)
                self.modus_dropdown['values'] = modes
                if self.modus_var.get() not in modes:
                    self.modus_var.set(modes[0] if modes else "")
                self.status_label.config(text="Modi geladen uit lokale cache.")
            except Exception as e2:
                self.error_label.config(text="Geen verbinding en geen lokale modi beschikbaar.")

    # --- Prompt Controls ---
    def _on_prompt_profile_selected(self, event=None):
        selected_profile = self.prompt_profile_var.get()
        if selected_profile in self.prompts:
            self.current_prompt_profile = selected_profile
            self._update_prompts_status_label()
            # Eventueel: laad direct het profiel, of activeer knoppen
            self.edit_prompts_button.config(state=tk.NORMAL)
            self.push_prompts_button.config(state=tk.NORMAL)
        else:
            self.edit_prompts_button.config(state=tk.DISABLED)
            self.push_prompts_button.config(state=tk.DISABLED)
            
    def reload_prompts(self):
        """Reload prompts directly via the PromptManager."""
        self._clear_messages()
        try:
            # Disable de knop tijdens het laden
            self.refresh_modus_button.config(state=tk.DISABLED)

            # Directe aanroep van de PromptManager       
            self.prompt_manager.load_default_prompts_sync(self.current_prompt_profile)

            # Update de status
            self.status_label.config(text="Prompts reloaded successfully.")
            print(f"Prompts reloaded for profile '{self.current_prompt_profile}'.")

        except Exception as e:
            self.error_label.config(text=f"Error reloading prompts: {e}")
            print(f"Error reloading prompts directly: {e}")

        finally:
            # Re-enable de knop
            self.refresh_modus_button.config(state=tk.NORMAL)

    def edit_prompt_profile(self):
        """Haalt de huidige prompts op van de PromptManager en opent de editor."""
        self._clear_messages()

        # Vraag de huidige prompts op van de PromptManager
        try:
            current_system_prompt = self.prompt_manager.get_current_system_prompt()
            current_dynamic_context = self.prompt_manager.get_current_dynamic_context()
        except Exception as e:
            self.error_label.config(text=f"Fout bij ophalen prompts: {e}")
            return

        # Open de editor met de opgehaalde prompts
        self._open_prompt_editor(
            system_prompt=current_system_prompt,
            dynamic_context=current_dynamic_context)

    def _open_prompt_editor(self, system_prompt, dynamic_context):
        # Haal alleen de content van de role 'user' uit de dynamic_context
        if isinstance(dynamic_context, list):
            user_content = next(
                (item["content"] for item in dynamic_context if item.get("role") == "user"),"")
        else:
            user_content = dynamic_context  # fallback als het toch een string is

        # Nu kun je user_content gebruiken zoals je wilt, bijvoorbeeld:
        dynamic_context_lines = user_content.split("\n")      
        # Sluit bestaande editor als die open is
        if self.prompts_window and self.prompts_window.winfo_exists():
            self.prompts_window.destroy()

        # Maak een nieuw venster voor de editor
        self.prompts_window = tk.Toplevel(self.root)
        self.prompts_window.title("Edit Current Prompts")

        # Geometrie instellen: linkerhelft van het scherm
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.prompts_window.geometry(f"{screen_width // 2}x{screen_height}+0+0")

        main_frame = ttk.Frame(self.prompts_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # System Prompt
        system_label = ttk.Label(main_frame, text="System Prompt:")
        system_label.pack(anchor="w")

        system_frame = ttk.Frame(main_frame)
        system_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        system_scrollbar = ttk.Scrollbar(system_frame)
        system_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.system_text_widget = tk.Text(system_frame, height=10, wrap=tk.WORD, font=self.editor_font, yscrollcommand=system_scrollbar.set)
        self.system_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.system_text_widget.insert("1.0", system_prompt)
        system_scrollbar.config(command=self.system_text_widget.yview)

        # Dynamic Context
        dynamic_label = ttk.Label(main_frame, text="Dynamic Context:")
        dynamic_label.pack(anchor="w")

        dynamic_frame = ttk.Frame(main_frame)
        dynamic_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        dynamic_scrollbar = ttk.Scrollbar(dynamic_frame)
        dynamic_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.dynamic_text_widget = tk.Text(dynamic_frame, height=10, wrap=tk.WORD, font=self.editor_font, yscrollcommand=dynamic_scrollbar.set)
        self.dynamic_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Verwerk nieuwe regels correct
        dynamic_context_lines = user_content.split("\n")
        for line in dynamic_context_lines:
            self.dynamic_text_widget.insert(tk.END, line + "\n")

        dynamic_scrollbar.config(command=self.dynamic_text_widget.yview)

        # Knoppen
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="Back", command=self._handle_prompt_back).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Push & Close", command=self._push_and_close_prompt).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Undo All Changes", command=self._undo_all_prompt_changes).pack(side=tk.LEFT, padx=5)
        
    def _pull_current_mode(self):
        self._clear_messages()
        try:
            current_mode = asyncio.run(self.communication_manager.get_current_mode_async())
            self.modus_var.set(current_mode)
            self.status_label.config(text=f"Huidige modus: '{current_mode}'")
        except Exception as e:
            self.error_label.config(text=f"Fout bij ophalen huidige modus: {e}")

    def _save_prompt_as(self):
        """Save the current prompt profile under a new name directly via the PromptManager."""
        # Vraag om een nieuwe naam
        new_name = simpledialog.askstring("Save Prompt As", "Nieuwe profielnaam:", parent=self.prompts_window)
        if not new_name:
            return  # Gebruiker annuleerde

        # Haal de huidige inhoud op
        system_content = self.system_text_widget.get("1.0", tk.END).strip()
        dynamic_content = self.dynamic_text_widget.get("1.0", tk.END).strip()
        voice = self.prompts[self.current_prompt_profile].get("voice")

        # Bouw het nieuwe PromptProfile object
        new_profile = PromptProfile(
            name=new_name,
            system_prompt=system_content,
            dynamic_context=dynamic_content,
            voice=voice
    )

        try:
            # Directe aanroep van de asynchrone PromptManager methode
            asyncio.run(self.prompt_manager.save_prompt_profile(new_profile))

            # Voeg het nieuwe profiel toe aan de dropdown (optioneel, maar handig)
            if new_name not in self.prompts:
                self.prompts[new_name] = {
                    "name": new_name,
                    "original": {"system": system_content, "dynamic": dynamic_content},
                    "current": {"system": system_content, "dynamic": dynamic_content},
                    "modified": False,
                    "voice": voice
    }
                self.prompt_profile_dropdown['values'] = list(self.prompts.keys())
                self.prompt_profile_var.set(new_name)
                self.current_prompt_profile = new_name
                self._update_prompts_status_label()

            self.status_label.config(text=f"Prompt-profiel '{new_name}' succesvol opgeslagen.")
            print(f"Prompt-profiel '{new_name}' succesvol opgeslagen.")
        except Exception as e:
            self.error_label.config(text=f"Fout bij opslaan: {e}")
            print(f"Fout bij opslaan van prompt-profiel '{new_name}': {e}")

    def _delete_prompt_profile(self):
        """Delete a prompt profile directly via PromptManager."""
        profile_name = self.current_prompt_profile
        if not profile_name:
            return

        # Bevestiging vragen aan de gebruiker
        confirm = messagebox.askyesno(
            "Bevestig verwijderen",
            f"Weet je zeker dat je '{profile_name}' wilt verwijderen?",
            parent=self.prompts_window
        )
        
        if not confirm:
            return

        try:
            # Directe aanroep van de PromptManager
            self.prompt_manager.delete_prompt(profile_name)
            self.status_label.config(text=f"Prompt-profiel '{profile_name}' verwijderd.")

            # Refresh de dropdowns en UI
            self._refresh_prompt_profiles()
        except Exception as e:
            self.error_label.config(text=f"Fout bij verwijderen: {e}")

    def _refresh_prompt_profiles(self):
        """Refresh the list of prompt profiles directly from the PromptManager."""
        try:
            # Gebruik asyncio.run om de asynchrone methode aan te roepen
            profiles = asyncio.run(self.prompt_manager.list_prompt_names())

            # Update de dropdowns
            self.prompt_profile_dropdown['values'] = profiles
            self.modus_dropdown['values'] = profiles  #  ✅ update modus-dropdown ook

            if self.current_prompt_profile not in profiles:
                self.prompt_profile_var.set(profiles[0] if profiles else "")
                self.current_prompt_profile = self.prompt_profile_var.get()

            if self.modus_var.get() not in profiles:     
                self.modus_var.set(profiles[0] if profiles else "")

            self.status_label.config(text="Profielen succesvol vernieuwd.")
        except Exception as e:
            self.error_label.config(text=f"Fout bij vernieuwen profielen: {e}")
            
    def _update_prompts_status_label(self):
            profile = self.prompts.get(self.current_prompt_profile)
            if not profile:
                status = "Prompts: None"
            else:
                name = profile["name"]
                modified = profile["modified"]
                status = f"Prompts: {name}" + (" (Modified)" if modified else "")
            self.prompts_status_label.config(text=status)
            self.root.update_idletasks()

    def _save_summary(self):
        """Save the updated summary directly via EventManager."""
        if not self.current_event_id:
            messagebox.showwarning("Geen selectie", "Selecteer eerst een event om te bewaren.")
            return

        new_summary = self.summary_text.get("1.0", tk.END).strip()

        try:
            with self.event_manager.lock, connect(self.event_manager.db_path) as conn:
                cursor = conn.execute(
                    "SELECT content FROM events WHERE event_id = ? AND type = ?",
                    (self.current_event_id, "ConversationState"))
                row = cursor.fetchone()
                if not row:
                    messagebox.showerror("Fout", "Event niet gevonden in de database.")
                    return

                content = orjson.loads(row[0])
                content['summary'] = new_summary
                content_json = orjson.dumps(content).decode('utf-8')

                conn.execute(
                    "UPDATE events SET content = ? WHERE event_id = ? AND type = ?",
                    (content_json, self.current_event_id, "ConversationState"))
                conn.commit()

            self.browse_status_label.config(text="Summary saved.")
            self.save_summary_button.config(state=tk.DISABLED)
        except Exception as e:
            messagebox.showerror("Fout", f"Opslaan mislukt: {e}")

    def _on_prompt_modified(self, event=None):
        """Zet modified-flag alleen als er echt iets gewijzigd is door de gebruiker."""
        modified = False

        if self.system_text_widget and self.system_text_widget.edit_modified():
            modified = True
            self.system_text_widget.edit_modified(False)

        if self.dynamic_text_widget and self.dynamic_text_widget.edit_modified():
            modified = True
            self.dynamic_text_widget.edit_modified(False)

        if modified:
            self.prompts_modified_flag = True

    def _keep_prompt_changes(self) -> bool:
        """Bewaar wijzigingen uit het edit-venster naar self.prompts."""        
        if not (self.system_text_widget and self.dynamic_text_widget):
            return False

        system_content = self.system_text_widget.get("1.0", tk.END).strip()     
        dynamic_content = self.dynamic_text_widget.get("1.0", tk.END).strip()   

        profile = self.prompts[self.current_prompt_profile]
        profile["current"]["system"] = system_content
        profile["current"]["dynamic"] = dynamic_content
        profile["modified"] = False
        self.prompts_modified_flag = False

        self.status_label.config(text=f"Wijzigingen in '{self.current_prompt_profile}' bewaard.")
        print(f"Prompt-profiel '{self.current_prompt_profile}' wijzigingen bewaard.")
        self._update_prompts_status_label()
        return True

    def _undo_all_prompt_changes(self):
        """Zet wijzigingen terug naar de laatst opgehaalde versie."""
        profile = self.prompts[self.current_prompt_profile]
        original_system = profile["original"]["system"]
        original_dynamic = profile["original"]["dynamic"]

        if self.system_text_widget:       
            self.system_text_widget.delete("1.0", tk.END)
            self.system_text_widget.insert("1.0", original_system)

        if self.dynamic_text_widget:      
            self.dynamic_text_widget.delete("1.0", tk.END)
            self.dynamic_text_widget.insert("1.0", original_dynamic)

        profile["current"]["system"] = original_system
        profile["current"]["dynamic"] = original_dynamic
        profile["modified"] = False
        self.prompts_modified_flag = False

        self.status_label.config(text=f"Wijzigingen in '{self.current_prompt_profile}' ongedaan gemaakt.")
        print(f"Prompt-profiel '{self.current_prompt_profile}' teruggezet naar origineel.")
        self._update_prompts_status_label()

    def _handle_prompt_back(self):
        """Sluit het prompts-editvenster netjes af, met check op wijzigingen."""
        if self.prompts_modified_flag:
            response = messagebox.askyesnocancel(
                "Unsaved Changes",
                "Wil je de wijzigingen bewaren voordat je sluit?",
                parent=self.prompts_window)
            if response is True:
                if not self._keep_prompt_changes():
                    return  # Bij fout niet sluiten
            elif response is None:
                return  # Cancel gedrukt, niet sluiten
            # False = doorgaan zonder bewaren

        if self.prompts_window and self.prompts_window.winfo_exists():
            self.prompts_window.destroy()

        self.prompts_window = None        
        self.system_text_widget = None
        self.dynamic_text_widget = None
        self.prompts_modified_flag = False
        self._update_prompts_status_label()

    def _push_and_close_prompt(self):
        """Sends the current prompt profile to the PromptManager and closes the window upon success."""       
        if not self._keep_prompt_changes():
            return  # Als het bewaren van wijzigingen mislukt, niet verdergaan.

        profile = self.prompts[self.current_prompt_profile]

        try:
            # Directe aanroep van de asynchrone PromptManager methode
            asyncio.run(self.prompt_manager.save_prompt_profile(PromptProfile(
                name=profile["name"],
                system_prompt=profile["current"]["system"],
                dynamic_context=profile["current"]["dynamic"],
                voice=profile.get("voice"))))

            self.status_label.config(text=f"Prompt-profiel '{profile['name']}' succesvol opgeslagen.")        
            print(f"Prompt-profiel '{profile['name']}' succesvol gepusht naar PromptManager.")

            # Sluit het venster na succesvolle push      
            if self.prompts_window and self.prompts_window.winfo_exists():
                self.prompts_window.destroy()

            self.prompts_window = None
            self.system_text_widget = None
            self.dynamic_text_widget = None
            self.prompts_modified_flag = False
            self._update_prompts_status_label()

        except Exception as e:
            self.error_label.config(text=f"Fout bij opslaan van prompt-profiel: {e}")
            print(f"Fout bij opslaan van prompt-profiel: {e}")

    def edit_prompts(self):
        self._clear_messages()
        self.status_label.config(text="Edit Prompts: nog niet geïmplementeerd.")

    def push_prompts(self):
        self._clear_messages()
        self.status_label.config(text="Push Prompts: nog niet geïmplementeerd.")

    def pull_prompt_profile(self, profile_name="default"):
        """Pull a prompt profile directly from the PromptManager."""
        self._clear_messages()
        try:
            # Gebruik asyncio.run om de asynchrone functie aan te roepen
            raw_profile = asyncio.run(self.prompt_manager.get_raw_prompt_profile(profile_name))

            if profile_name not in self.prompts:
                self.prompts[profile_name] = {
                    "name": profile_name,
                    "original": {"system": "", "dynamic": ""},
                    "current": {"system": "", "dynamic": ""},
                    "modified": False,
                    "voice": raw_profile.get("voice")}

            self.prompts[profile_name]["original"]["system"] = raw_profile.get("system_prompt", "")
            self.prompts[profile_name]["original"]["dynamic"] = raw_profile.get("dynamic_context", "")
            self.prompts[profile_name]["current"]["system"] = raw_profile.get("system_prompt", "")
            self.prompts[profile_name]["current"]["dynamic"] = raw_profile.get("dynamic_context", "")
            self.prompts[profile_name]["modified"] = False

            self.edit_prompts_button.config(state=tk.NORMAL)
            self.push_prompts_button.config(state=tk.NORMAL)

            self.status_label.config(text=f"Prompt-profiel '{profile_name}' opgehaald.")
            self._update_prompts_status_label()
        except Exception as e:
            self.error_label.config(text=f"Error pulling prompt profile: {e}")

    def _add_modus(self):
        """Voegt een nieuwe modus (prompt-profiel) toe via de PromptManager."""
        self._clear_messages()
        modus_naam = simpledialog.askstring("Nieuwe Modus", "Voer de naam in voor de nieuwe modus (prompt-profiel):", parent=self.root)
        if not modus_naam:
            self.error_label.config(text="Toevoegen geannuleerd of geen naam ingevoerd.")
            return

        # Gebruik huidige prompt als basis
        current_mode = self.prompts.get(self.current_prompt_profile)
        if not current_mode:
            self.error_label.config(text="Huidige modus niet gevonden.")
            return

        system_prompt = current_mode["current"]["system"]
        dynamic_context = current_mode["current"]["dynamic"]
        voice = current_mode.get("voice")

        try:
            # Directe aanroep van de PromptManager om een nieuw profiel op te slaan
            new_mode = {
                "name": modus_naam,
                "system_prompt": system_prompt,
                "dynamic_context": dynamic_context,
                "voice": voice
            }
            asyncio.run(self.prompt_manager.add_mode(new_mode))

            # Update de UI
            self.status_label.config(text=f"Nieuwe modus '{modus_naam}' toegevoegd als prompt-profiel.")      
            self._refresh_prompt_profiles()
            print(f"Nieuwe modus '{modus_naam}' succesvol toegevoegd.")

        except Exception as e:
            self.error_label.config(text=f"Fout bij toevoegen modus: {e}")
            print(f"Fout bij toevoegen modus '{modus_naam}': {e}")

    # --- In Summary Controls ---
    def push_summary(self):
        """Sends the summary text directly to the CommunicationManager."""
        self._clear_messages()
        # Haal de tekst op uit de UI
        summary_text = self.summary_entry.get("1.0", tk.END).strip()

        if not summary_text:
            self.error_label.config(text="Error: Summary cannot be empty to push.")
            return

        try:
            # Directe aanroep van de CommunicationManager
            self.communication_manager.load_summary_sync(summary_text)
            self.summary_entry.delete("1.0", tk.END)  # Leegmaken na push
            self.status_label.config(text="Summary pushed successfully.")
            print("Summary pushed directly to CommunicationManager.")
        except Exception as e:
            self.error_label.config(text=f"Error pushing summary: {e}")
            print(f"Error pushing summary directly: {e}")


    def pull_summary(self):
        """Fetches the current summary directly from the CommunicationManager."""
        self._clear_messages()
        try:
            # Directe aanroep van de CommunicationManager
            summary_text = self.communication_manager.get_summary_sync()

            # Update de UI met de opgehaalde summary     
            self.summary_entry.delete("1.0", tk.END)
            self.summary_entry.insert("1.0", summary_text)
            self.status_label.config(text="Summary pulled successfully.")
            print("Summary pulled directly from CommunicationManager.")
        except Exception as e:
            self.error_label.config(text=f"Error pulling summary: {e}")
            print(f"Error pulling summary directly: {e}")


    # --- Message Controls (Main Window) ---

    def _update_messages_status_and_buttons(self):
        """Updates the message status label and enables/disables related buttons."""
        if self.current_messages is None: # Check current_messages now
            status_text = "Messages: None"
            edit_state = tk.DISABLED
            push_state = tk.DISABLED
            clear_state = tk.DISABLED
            summarize_state = tk.DISABLED
        else:
            # Use the length of the potentially modified current_messages list
            count = len(self.current_messages) # <<< USE self.current_messages
            modified_text = " (Modified)" if self.messages_modified_flag else ""
            status_text = f"Messages: Loaded ({count}){modified_text}" # Show current count
            edit_state = tk.NORMAL
            push_state = tk.NORMAL
            clear_state = tk.NORMAL
            summarize_state = tk.NORMAL
            # Disable push if modified? Maybe not, push pushes the kept state.

        self.messages_status_label.config(text=status_text)
        self.edit_messages_button.config(state=edit_state)
        self.push_messages_button.config(state=push_state) # Main push button
        self.clear_messages_button.config(state=clear_state)
        self.summarize_button.config(state=summarize_state)
        # self.root.update_idletasks() # Ensure UI updates immediately

    def pull_messages(self):
        """Fetches messages directly from the CommunicationManager."""
        self._clear_messages()

        # Controleer of het editorvenster open is en vraag bevestiging om door te gaan
        if self.messages_window and self.messages_window.winfo_exists():
            response = messagebox.askyesno(
                "Confirm Pull",
                "This will discard current editor content (if any) and pull fresh messages.\n\nProceed?",     
                parent=self.root
            )
            if not response:
                self.status_label.config(text="Pull operation cancelled.")
                return

            # Sluit het editorvenster als de gebruiker doorgaat
            self.messages_window.destroy()
            self.messages_window = None
            self.messages_text_widget = None

        try:
            # Directe aanroep van de CommunicationManager
            messages = self.communication_manager.get_messages_sync()

            if not isinstance(messages, list):
                self.error_label.config(text="Error: Expected list from CommunicationManager, got different format.")
                print(f"Unexpected response format pulling messages. Expected list, got {type(messages)}")
                self.clear_local_messages()
                return

            # Sla de opgehaalde berichten op
            self.original_messages = copy.deepcopy(messages)
            self.current_messages = messages
            self.messages_modified_flag = False
            self.status_label.config(text=f"Messages pulled ({len(messages)}).")
            print(f"Successfully pulled {len(messages)} messages.")
            self._update_messages_status_and_buttons()

            # Open of vernieuw het editorvenster
            if self.messages_window and self.messages_window.winfo_exists():
                self._reformat_messages_display()
                self.messages_window.lift()
                self.messages_window.focus_force()
            else:
                self._display_messages()

        except Exception as e:
            self.error_label.config(text=f"Error pulling messages: {e}")
            print(f"Error pulling messages directly: {e}")


    def edit_messages(self):
        """Opens the message editor window if messages are loaded."""
        self._clear_messages()
        if self.original_messages is None:
            self.status_label.config(text="Pull messages first before editing.")
            return

        # Check if window exists and is withdrawn/iconified, bring it back
        if self.messages_window and self.messages_window.winfo_exists():
             if self.messages_window.state() == 'withdrawn' or self.messages_window.state() == 'iconic':
                 self.messages_window.deiconify()
             self.messages_window.lift()
             self.messages_window.focus_force()
        elif not self.messages_window: # Only open if not already open
            self._display_messages()
        else: # Window exists and is likely visible
             self.messages_window.lift()
             self.messages_window.focus_force()


    def clear_local_messages(self):
        """Clears messages stored locally in the UI."""
        self._clear_messages()
        if self.messages_window and self.messages_window.winfo_exists():
            # Ask if modified? For simplicity now, just close.
            # Could potentially integrate _handle_back_button logic here if needed.
             self.messages_window.destroy()
             self.messages_window = None
             self.messages_text_widget = None

        self.original_messages = None
        self.current_messages = None
        self.messages_modified_flag = False
        self._update_messages_status_and_buttons()
        self.status_label.config(text="Local messages cleared.")
        print("Local messages cleared.")

    def push_main_messages(self):
        """Pushes the currently stored messages directly to the CommunicationManager."""
        self._clear_messages()
        if self.current_messages is None:
            self.error_label.config(text="Error: No messages loaded to push.")
            return

        try:
            # Directe aanroep van de CommunicationManager
            self.communication_manager.set_messages_sync(self.current_messages)
            self.messages_modified_flag = False  # Reset de modified flag
            self._update_messages_status_and_buttons()
            self.status_label.config(text=f"Messages ({len(self.current_messages)}) pushed successfully.")
            print(f"Messages ({len(self.current_messages)}) pushed directly to CommunicationManager.")
        except Exception as e:
            self.error_label.config(text=f"Error pushing messages: {e}")
            print(f"Error pushing messages directly: {e}")

    # --- Message Editor Window and Logic ---

    def _parse_text_to_messages(self, text_content: str) -> list[dict[str, str]] | None:
        """
        Parses text content formatted with '--- USER: ---' or '--- ASSISTANT: ---' separators
        into a list of message dictionaries.
        Ignores other '--- ... ---' lines.

        Returns:
        A list of dictionaries [{'role': 'user'|'assistant', 'content': '...'}, ...]
        or None if a parsing error occurs.
        """
        messages = []
        # Normalize line endings and strip leading/trailing whitespace
        text_content = text_content.replace('\r\n', '\n').strip()

        # Regex pattern to find all valid message blocks 
        pattern = r"--- (USER|ASSISTANT): ---\n"
        splits = re.split(pattern, text_content)

        # re.split returns: [pre, role1, content1, role2, content2, ...]
        if len(splits) < 3:
            return [] if not text_content else None  # Empty or invalid format

        # Skip the first element (pre-content before first match)
        for i in range(1, len(splits) - 1, 2):
            role = splits[i].strip().lower()  # 'user' or 'assistant'
            content = splits[i + 1].strip()
            messages.append({"role": role, "content": content})

        return messages

    def _display_messages(self):
        """Displays messages in a separate Toplevel window for editing."""
        if self.current_messages is None:
            self.status_label.config(text="No messages to display.")
            return

        # Prevent multiple windows / Bring existing to front
        if self.messages_window and self.messages_window.winfo_exists():
            self.messages_window.lift()
            self.messages_window.focus_force()
            return

        self.messages_window = tk.Toplevel(self.root)
        self.messages_window.title("Edit Conversation Messages")
        # Double the height from 500 to 1000
        self.messages_window.geometry("750x1000") # <--- INCREASED HEIGHT
        self.messages_window.protocol("WM_DELETE_WINDOW", self._handle_back_button)

        # Create the main frame INSIDE the Toplevel window
        main_frame = ttk.Frame(self.messages_window, padding="10") # <<< CRITICAL: Parent is self.messages_window
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Button Frame --- (Packed at the bottom of main_frame)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        back_button = ttk.Button(button_frame, text="Back", command=self._handle_back_button)
        back_button.pack(side=tk.RIGHT, padx=5, pady=5)
        keep_button = ttk.Button(button_frame, text="Keep Changes", command=self._keep_message_changes)
        keep_button.pack(side=tk.LEFT, padx=5, pady=5)
        undo_button = ttk.Button(button_frame, text="Undo All Changes", command=self._undo_all_message_changes)
        undo_button.pack(side=tk.LEFT, padx=5, pady=5)
        push_close_button = ttk.Button(button_frame, text="Push & Close", command=self._push_and_close_messages)
        push_close_button.pack(side=tk.LEFT, padx=5, pady=5)
        self.push_close_button_ref = push_close_button

        # --- Messages Frame --- (Packed above button_frame in main_frame)
        messages_frame = ttk.Frame(main_frame)
        messages_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(messages_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.messages_text_widget = tk.Text(
            messages_frame, # Parent is messages_frame
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            undo=True,
            font=self.editor_font
        )
        self.messages_text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.messages_text_widget.yview)

        # --- Define and Configure Tags --- <<< NEW
        self.messages_text_widget.tag_configure(
            "bold_caps",
            font=tkfont.Font(family=self.editor_font.cget('family'), size=self.editor_font.cget('size'), weight='bold')
        )
        # --- End Define Tags ---


        # --- Modification Tracking ---
        self.messages_text_widget.bind("<<Modified>>", self._on_message_text_modified)

        # --- Populate Initial Content ---
        self._reformat_messages_display() # Will now use the new format


    def _reformat_messages_display(self):
        """Helper to clear and populate the text widget from self.current_messages."""
        if not self.messages_text_widget or not self.messages_window or not self.messages_window.winfo_exists():
            return # Safety check

        # --- Temporarily disable binding --- Doesnt seem reliable enough
        # self.messages_text_widget.unbind("<<Modified>>")

        self.messages_text_widget.config(state=tk.NORMAL) # Ensure editable
        self.messages_text_widget.delete(1.0, tk.END)

        if self.current_messages is not None:
            for i, msg in enumerate(self.current_messages):
                role_upper = msg.get('role', 'unknown').upper() # Get role and uppercase
                content = msg.get('content', '').strip() # <<< Strip content here for cleaner display

                # --- NEW FORMAT ---
                separator_start = "--- "
                separator_end = ": ---\n"
                content_body = f"{content}\n\n" # Actual content starts here, add spacing

                # Insert the start of the separator
                self.messages_text_widget.insert(tk.END, separator_start)
                # Insert the role with the bold_caps tag
                self.messages_text_widget.insert(tk.END, f"{role_upper}", ("bold_caps",))
                # Insert the end of the separator
                self.messages_text_widget.insert(tk.END, separator_end)
                # Insert the content body
                self.messages_text_widget.insert(tk.END, content_body)
                # --- END NEW FORMAT ---

        self.messages_text_widget.config(state=tk.NORMAL) # Ensure state is normal
        # Crucially, reset the widget's internal flag *after* inserting text
        self.messages_text_widget.edit_modified(False)

        # --- Re-enable binding ---
        # self.messages_text_widget.bind("<<Modified>>", self._on_message_text_modified)

        # Ensure cursor is at the start, not end
        self.messages_text_widget.mark_set("insert", "1.0")
        self.messages_text_widget.see("1.0")
        # Reset undo stack after programmatic change
        self.messages_text_widget.edit_reset()


    def _on_message_text_modified(self, event=None):
        """Callback when the message text widget is modified."""
        # Check if the widget still exists
        if not self.messages_text_widget or not self.messages_text_widget.winfo_exists():
            return

        # The <<Modified>> event fires *before* the modification flag is set,
        # and *again* after it's set to True. We only care when it's about to be True.
        # So, we check the flag *inside* the callback. If it's already True, ignore.
        # Then, set our app's flag and reset the widget's flag.

        try:
            # Check the widget's internal flag
            is_modified = self.messages_text_widget.edit_modified()

            if is_modified:
                # This means an actual user edit likely occurred.
                self.messages_modified_flag = True # Set our application flag
                self._update_messages_status_and_buttons() # Update main UI status

                # Reset the widget's internal flag so this callback doesn't
                # immediately fire again and only fires once per edit sequence.
                self.messages_text_widget.edit_modified(False)

        except tk.TclError:
             # Handle cases where the widget might be destroyed during the callback
             print("TclError caught in _on_message_text_modified, likely widget destroyed.")


    def _keep_message_changes(self) -> bool:
        """Parses text, updates current_messages if valid, resets modified flag."""
        if not self.messages_text_widget: return False
        self._clear_messages() # Clear main window status

        text_content = self.messages_text_widget.get(1.0, tk.END)
        parsed_messages = self._parse_text_to_messages(text_content)

        if parsed_messages is not None:
            self.current_messages = parsed_messages
            self.messages_modified_flag = False
            if self.messages_text_widget and self.messages_text_widget.winfo_exists():
                 self.messages_text_widget.edit_modified(False) # Reset widget flag
            self._update_messages_status_and_buttons()
            self.status_label.config(text="Changes kept.") # Update main status
            print("Message changes kept.")
            return True
        else:
            # Show error in the messages window
            if self.messages_window and self.messages_window.winfo_exists():
                 messagebox.showerror("Parsing Error",
                                      "Could not parse the messages. Please check the format:\n"
                                      "- Each message starts with '--- <ROLE>: ---'\n"
                                      "- <ROLE> is either 'USER' or 'ASSISTANT'\n"
                                      "- <CONTENT> is the message content\n"
                                      "Changes not kept.",
                                      parent=self.messages_window) # Make modal to editor
            else: # Fallback if window somehow closed
                 self.error_label.config(text="Parsing Error: Could not save message changes.")
            return False

    def _undo_all_message_changes(self):
        """Resets the editor display to the initially pulled messages."""
        self._clear_messages()
        if self.original_messages is None:
             if self.messages_window and self.messages_window.winfo_exists():
                  messagebox.showwarning("Undo Error", "No original messages found to undo to.", parent=self.messages_window)
             return

        # Reset current_messages from original
        self.current_messages = copy.deepcopy(self.original_messages)
        # Update the display
        self._reformat_messages_display() # This handles clearing/populating/resetting flag

        # Ensure flags and status are correct
        self.messages_modified_flag = False
        self._update_messages_status_and_buttons()
        self.status_label.config(text="Changes reverted to last pulled state.")
        print("Message changes undone.")


    def _handle_back_button(self):
        """Handles closing the message editor window, prompting if modified."""
        close_window = True
        if self.messages_modified_flag:
            # Prompt within the messages window
            response = messagebox.askyesnocancel("Unsaved Changes",
                                                 "Keep the current changes before closing?",
                                                 parent=self.messages_window)
            if response is True: # Yes
                keep_success = self._keep_message_changes()
                if not keep_success:
                    close_window = False # Don't close if keeping failed (e.g., parse error)
            elif response is False: # No
                # Discard changes - just proceed to close
                self.messages_modified_flag = False # Reset flag as we are discarding
                self._update_messages_status_and_buttons()
            else: # Cancel
                close_window = False

        if close_window:
            if self.messages_window and self.messages_window.winfo_exists():
                 self.messages_window.destroy()
            self.messages_window = None
            self.messages_text_widget = None
            # Optional: Update status? Usually not needed if flags handled correctly.

    # --- In Message Editor Window and Logic ---
    def _push_and_close_messages(self):
        """Parses editor, potentially asks about summary, pushes messages,
           potentially pushes summary, and closes window only if messages push succeeds."""
        if not self.messages_text_widget: return
        self._clear_messages()

        text_content = self.messages_text_widget.get(1.0, tk.END)
        parsed_messages = self._parse_text_to_messages(text_content)

        if parsed_messages is None:
            # Show error and stop (same as before)
            if self.messages_window and self.messages_window.winfo_exists():
                 messagebox.showerror("Parsing Error", "Could not parse messages for pushing...", parent=self.messages_window)
            else: self.error_label.config(text="Parsing Error: Could not push messages.")
            return

        # --- Check for summary and ask initial question ---
        summary_text = self.summary_entry.get("1.0", tk.END).strip() # <<< CORRECTED: Added arguments for tk.Text.get()
        push_summary_flag = False
        if summary_text:
            if self.messages_window and self.messages_window.winfo_exists():
                push_summary_flag = messagebox.askyesno(
                    "Push Summary?",
                    "Summary field is not empty.\\nPush the summary as well after pushing messages?",
                    parent=self.messages_window
                )
            else: return # Should not happen, but safety check

        # --- Proceed with Message API Call ---
        url = f"{SERVER_BASE_URL}{MESSAGE_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        payload_data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": ACTION_PUSH_CONVERSATION, # Corrected action type
            "payload": {"conversation": parsed_messages}
        }

        message_push_success = False
        try:
            # Disable button during request
            if hasattr(self, 'push_close_button_ref') and self.push_close_button_ref:
                 self.push_close_button_ref.config(state=tk.DISABLED)
            self.root.update_idletasks()

            response = requests.post(url, headers=headers, data=json.dumps(payload_data), timeout=15)
            response.raise_for_status()

            # --- Message Push Success ---
            message_push_success = True
            self.current_messages = parsed_messages
            self.messages_modified_flag = False
            self._update_messages_status_and_buttons()
            self._handle_api_success_response(response, f"Messages ({len(self.current_messages)}) pushed")

            # --- Handle potential summary push ---
            summary_pushed_or_not_attempted = True # Assume success if not attempted
            if push_summary_flag:
                print("Proceeding to push summary after successful message push...")
                # Call push_summary and check its return value (optional check)
                summary_pushed_or_not_attempted = self.push_summary()
                if not summary_pushed_or_not_attempted:
                     print("Summary push failed after message push succeeded.")
                     # Decide if you want to show another error or just rely on push_summary's message

            # --- Close window ONLY if message push succeeded ---
            if self.messages_window and self.messages_window.winfo_exists():
                self.messages_window.destroy()
            self.messages_window = None
            self.messages_text_widget = None
            self.push_close_button_ref = None # Clear reference

        except requests.exceptions.Timeout:
            error_msg = "Error: Message push (from editor) timed out."
            print(error_msg)
            if self.messages_window and self.messages_window.winfo_exists():
                 messagebox.showerror("Push Error", error_msg, parent=self.messages_window)
            else: self.error_label.config(text=error_msg)
        except requests.exceptions.RequestException as e:
            error_details = self._format_request_error(e)
            print(f"Error sending message push (from editor) request: {e}")
            error_msg = f"Message Push Error: {error_details}"
            if self.messages_window and self.messages_window.winfo_exists():
                 messagebox.showerror("Push Error", error_msg, parent=self.messages_window)
            else: self.error_label.config(text=error_msg)

        finally:
            # --- Handle summary push if message push FAILED ---
            if not message_push_success and push_summary_flag:
                 if self.messages_window and self.messages_window.winfo_exists():
                     push_anyway = messagebox.askyesno(
                         "Push Summary?",
                         "Message push failed. Do you still want to try pushing the summary?",
                         parent=self.messages_window
                     )
                     if push_anyway:
                         print("Attempting to push summary after message push failed...")
                         self.push_summary()
                 # Do NOT close window here

            # Re-enable button if window still exists
            if hasattr(self, 'push_close_button_ref') and self.push_close_button_ref and self.push_close_button_ref.winfo_exists():
                 self.push_close_button_ref.config(state=tk.NORMAL)
            self._update_messages_status_and_buttons() # Refresh status

    # --- Placeholder for Summarize Messages --- <-- ADDED
    def _summarize_messages_placeholder(self): # <-- ADDED
        """Placeholder function for the Summarize Messages button.""" # <-- ADDED
        print("Placeholder: Summarize Messages button clicked.") # <-- ADDED
        self._clear_messages() # <-- ADDED
        self.status_label.config(text="Summarize functionality not yet implemented.") # <-- ADDED
    # --- End Placeholder --- <-- ADDED

    # --- Utility Methods ---
    def _format_request_error(self, e: requests.exceptions.RequestException) -> str:
        """Formats RequestException details for display."""
        error_details = str(e)
        if hasattr(e, 'response') and e.response is not None:
            status = e.response.status_code
            try:
                # Try to get JSON error message from response body
                body_json = e.response.json()
                if isinstance(body_json, dict) and 'detail' in body_json:
                    body = body_json['detail']
                else:
                    body = e.response.text[:200] # Limit length
            except json.JSONDecodeError:
                 body = e.response.text[:200] # Limit length if not JSON
            error_details += f" | Status: {status} | Body: {body}..."
        return error_details

    def _handle_pull_prompts(self):
        selected_profile = self.prompt_profile_var.get()
        self.pull_prompt_profile(selected_profile)

    def _open_event(self):
        selection = self.event_id_listbox.curselection()
        if not selection:
            self.browse_status_label.config(text="Geen event geselecteerd om te openen.") 
            return

        display_id = self.event_id_listbox.get(selection[0])
        full_event_id = self.event_id_map.get(display_id)
        if not full_event_id:
            self.error_label.config(text="Kon volledige event ID niet vinden.")
            return

        url = "http://127.0.0.1:5001/events"   
        headers = {"Content-Type": "application/json"}
        data = {
            "action_type": "open_event",
            "payload": {"event_id": full_event_id}
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            result = response.json()
            if result.get("status") == "ok":
                self.browse_status_label.config(text=f"Event '{full_event_id}' geopend.") 
            else:
                self.error_label.config(text="Server gaf geen bevestiging terug bij openen.")
        except Exception as e:
            self.error_label.config(text=f"Fout bij openen event: {e}")

    def _save_event_details(self):
        """Save updated event details and summary directly via EventManager."""
        if not hasattr(self, 'current_event_id') or not self.current_event_id:
            messagebox.showwarning("No Event", "No event selected to save.", parent=self.browse_window)       
            return

        updated_summary = self.summary_text.get("1.0", tk.END).strip()
        updated_details = self.event_details_text.get("1.0", tk.END).strip()

        try:
            # Haal het bestaande event op
            result = self.event_manager.get_event_by_id(self.current_event_id)
            if not result:
                messagebox.showerror("Save Error", "Event not found in EventManager.", parent=self.browse_window)
                return

            event_type, event_obj = result
            event_updated = False  # Flag om te checken of we het event moeten opslaan

            # Update de summary als die bestaat
            if hasattr(event_obj, "summary") and updated_summary is not None:
                event_obj.summary = updated_summary
                event_updated = True

            # Update de messages_list_file als het een ConversationState is
            if event_type == "ConversationState" and hasattr(event_obj, "messages_list_file"):
                list_id = event_obj.messages_list_file
                if list_id and updated_details is not None:
                    # Parse de details terug naar messages
                    messages = []
                    pattern = r"--- (USER|ASSISTANT): ---\n"
                    splits = re.split(pattern, updated_details)
                    for i in range(1, len(splits) - 1, 2):
                        role = splits[i].strip().lower()
                        content = splits[i + 1].strip()
                        messages.append({"role": role, "content": content})

                    message_list = MessageList(id=list_id, messages=messages)
                    self.event_manager.save_list(message_list)
                    event_updated = True  # ✅ ook hier!

            # Alleen opslaan als er echt iets veranderd is
            if event_updated:
                self.event_manager.save_event(event_type, event_obj.model_dump(), event_id=self.current_event_id)
                self.browse_status_label.config(text="Event details saved.")
            else:
                self.browse_status_label.config(text="No changes detected to save.")

        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save event: {e}", parent=self.browse_window)
    def _undo_changes_to_summary(self):
        if not hasattr(self, 'original_event_data') or not self.original_event_data:
            messagebox.showwarning("No Original", "No original data to undo to.", parent=self.browse_window)
            return

        self.summary_text.config(state=tk.NORMAL)
        self.summary_text.delete("1.0", tk.END)
        self.summary_text.insert("1.0", self.original_event_data.get("summary", ""))
        self._adjust_summary_height(self.original_event_data.get("summary", ""))
        self.summary_text.config(state=tk.NORMAL)

    def _handle_api_success_response(self, response: requests.Response, base_success_message: str):
        """Parses common success responses (JSON dict/str, 204) and updates status label."""
        status_text = f"{base_success_message} successfully"
        try:
            if response.status_code == 204: # No Content
                status_text += " (No Content)"
                print(f"{base_success_message}. Status: 204 No Content")
            elif response.content:
                 response_data = response.json()
                 if isinstance(response_data, str):
                      status_text = response_data # Use server message directly
                      print(f"{base_success_message}, Response: {response_data}")
                 elif isinstance(response_data, dict):
                      msg = response_data.get('message', status_text)
                      status_text = msg
                      print(f"{base_success_message}, Response: {response_data}")
                 else:
                      status_text += " (Unknown JSON Format)"
                      print(f"{base_success_message}. Response type: {type(response_data)}")
            else: # Empty body, not 204
                 status_text += " (Empty Response Body)"
                 print(f"{base_success_message}. Status: {response.status_code}")

            self.status_label.config(text=status_text)

        except json.JSONDecodeError:
            status_text += " (non-JSON response)"
            self.status_label.config(text=status_text)
            print(f"{base_success_message}. Status: {response.status_code}, Non-JSON Response: {response.text[:100]}...")
        except Exception as e: # Catch unexpected errors during handling
             print(f"Error handling success response: {e}")
             self.error_label.config(text="Error processing server response.")

