import tkinter as tk
import tkinter.ttk as ttk
import tkinter.messagebox as messagebox
import tkinter.font as tkfont # Import font module
import tkinter.simpledialog as simpledialog
import requests
import json
import asyncio
import copy # Needed for deep copy
import re
from datetime import datetime, timedelta
# from OAI_OAI_11LABS import update_voice_id, generate_model_audio_segments

# --- Data ---


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
    def __init__(self, root, voices, communication_manager, prompt_manager, event_manager):
        self.root = root
        self.communication_manager = communication_manager
        # --- Load voices dynamically ---
        self.voices = asyncio.run(self.communication_manager.get_voices_dict())
        self.voice_names = list(self.voices.keys())
        self.current_index = 0
        self.prompt_manager = prompt_manager
        self.event_manager = event_manager
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

        self.root.title("Voice UI")
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

        self.switch_modus_button = ttk.Button(self.modus_frame, text="Wissel Modus", command=self._switch_modus)
        self.switch_modus_button.pack(side=tk.LEFT, padx=(0, 5))

        self.pull_modus_button = ttk.Button(self.modus_frame, text="Pull Current Mode", command=self._pull_current_mode)
        self.pull_modus_button.pack(side=tk.LEFT, padx=(5, 0))

        self.add_modus_button = ttk.Button(self.modus_frame, text="Voeg Modus Toe", command=self._add_modus)      
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

        self.pull_prompts_button = ttk.Button(self.prompts_control_frame, text="Pull Prompts", command=self._handle_pull_prompts)
        self.pull_prompts_button.pack(side=tk.LEFT, padx=5)

        self.edit_prompts_button = ttk.Button(self.prompts_control_frame, text="Edit Prompts", command=lambda: self.edit_prompt_profile(self.prompt_profile_var.get()), state=tk.DISABLED)
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

        url = f"{SERVER_BASE_URL}/mode"        
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": "set_mode",
            "payload": {"name": selected_modus}
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            self.status_label.config(text=f"Modus gewisseld naar '{selected_modus}'")     
        except Exception as e:
            self.error_label.config(text=f"Fout bij wisselen modus: {e}")

    def open_browse_window(self, event_type: str):
        # Sluit bestaand browse venster als het er is
        if hasattr(self, 'browse_window') and self.browse_window and self.browse_window.winfo_exists():
            self.browse_window.destroy()

        self.browse_window = tk.Toplevel(self.root)
        self.browse_window.title(f"Browse {event_type}")
        self.browse_window.geometry("1100x800")

        # Titel
        title_label = ttk.Label(self.browse_window, text=f"Browse {event_type}", font=self.header_font)
        title_label.pack(pady=(10, 10))

        # --- Dropdowns Frame ---
        dropdowns_frame = ttk.Frame(self.browse_window)
        dropdowns_frame.pack(fill=tk.X, pady=(10, 10), padx=10)

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

        # --- Linker controls (dropdowns + refresh) ---
        left_controls_frame = ttk.Frame(dropdowns_frame)
        left_controls_frame.pack(side=tk.LEFT)

        # Periode dropdown
        self.period_options = ["Today", "2 Days", "3 Days", "1 Week", "Pick Date", "Pick Range"]
        self.period_var = tk.StringVar(value=self.period_options[0])
        period_dropdown = ttk.Combobox(
            left_controls_frame, textvariable=self.period_var, values=self.period_options, state="readonly", width=12
        )
        period_dropdown.pack(side=tk.LEFT, padx=(0, 10))

        # Event type dropdown
        self.event_type_options = [
            ("Conversations", "ConversationState"),
            ("Ideas", "IdeaEvent"),
            ("Journal Events", "JournalEvent")
        ]
        event_type_labels = [label for label, _ in self.event_type_options]
        self.event_type_var = tk.StringVar(value=event_type_labels[
            [et for et, val in self.event_type_options].index(
                {"ConversationState": "Conversations", "IdeaEvent": "Ideas", "JournalEvent": "Journal Events"}[event_type])
        ] if event_type in ["ConversationState", "IdeaEvent", "JournalEvent"] else event_type_labels[0])
        event_type_dropdown = ttk.Combobox(
            left_controls_frame, textvariable=self.event_type_var, values=event_type_labels, state="readonly", width=16
        )
        event_type_dropdown.pack(side=tk.LEFT)

        self.refresh_events_button = ttk.Button(
            left_controls_frame,
            text="Refresh",
            command=self.load_events
        )
        self.refresh_events_button.pack(side=tk.LEFT, padx=(10, 0))

        # --- Rechterkant: Exit knop ---
        self.exit_browse_button = ttk.Button(dropdowns_frame, text="Exit", command=self._close_browse_window)
        self.exit_browse_button.pack(side=tk.RIGHT, padx=(10, 0))


        # Bind dropdowns aan load_events
        self.period_var.trace_add("write", lambda *args: self.load_events())
        self.event_type_var.trace_add("write", lambda *args: self.load_events())

        # --- Main Split Frame ---
        main_split = ttk.Frame(self.browse_window)
        main_split.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # --- Event ID List (links) ---
        event_list_frame = ttk.Frame(main_split)
        event_list_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), expand=False)

        event_list_label = ttk.Label(event_list_frame, text="Event IDs")
        event_list_label.pack(anchor="w")

        self.event_id_listbox = tk.Listbox(event_list_frame, width=17, height=30)
        self.event_id_listbox.pack(side=tk.LEFT, fill=tk.Y, expand=True)

        self.event_list_scrollbar = ttk.Scrollbar(event_list_frame, orient=tk.VERTICAL, command=self.event_id_listbox.yview)
        self.event_id_listbox.config(yscrollcommand=self.event_list_scrollbar.set)
        self.event_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.event_id_listbox.config(font=self.editor_font)  # 👈 hier
        self.event_id_listbox.bind("<<ListboxSelect>>", self.show_event_details)
        # --- Event Details (rechts) ---
        details_frame = ttk.Frame(main_split)
        details_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        details_label = ttk.Label(details_frame, text="Event Details")
        details_label.pack(anchor="w")

        # --- Summary Frame boven messages ---
        self.summary_frame = ttk.Frame(details_frame)
        self.summary_frame.pack(fill=tk.X, pady=(0, 10))

        self.summary_scrollbar = ttk.Scrollbar(self.summary_frame, orient=tk.VERTICAL)        
        self.summary_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.summary_text = tk.Text(
            self.summary_frame,
            height=3,
            wrap=tk.WORD,
            font=self.editor_font,
            yscrollcommand=self.summary_scrollbar.set,
            state=tk.DISABLED
        )
        self.summary_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.summary_scrollbar.config(command=self.summary_text.yview)

        self.event_details_text = tk.Text(details_frame, wrap=tk.WORD, height=30, font=self.editor_font)
        self.details_scrollbar = ttk.Scrollbar(details_frame, orient=tk.VERTICAL, command=self.event_details_text.yview)      
        self.event_details_text.config(yscrollcommand=self.details_scrollbar.set)
        self.details_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.event_details_text.pack(fill=tk.BOTH, expand=True)

        self.load_events()

    def _close_browse_window(self):
        if hasattr(self, 'browse_window') and self.browse_window and self.browse_window.winfo_exists():
            self.browse_window.destroy()
            self.browse_window = None


    # --- Event ophalen en tonen ---
    def load_events(self):
        print("load_events aangeroepen")

        # Haal de specifieke conversation ID op
        try:
            url = "http://127.0.0.1:5001/events"
            headers = {"Content-Type": "application/json"}
            data = {
                "trigger_type": "get_specific_state",
                "action_type": None,
                "payload": None
        }
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            result = response.json()
            self.specific_conversation_id = result.get("event_id")
        except Exception as e:
            print(f"Kon specifieke conversatie niet ophalen: {e}")
            self.specific_conversation_id = None
        self.event_id_map = {}  # display_id → full_id
        # Haal gekozen event_type op
        event_type_label = self.event_type_var.get()
        event_type = next(val for label, val in self.event_type_options if label == event_type_label)

        # Bepaal de datums op basis van de periode-dropdown    
        period = self.period_var.get()
        today = datetime.today().date()

        if period == "Today":
            dates = [today.strftime("%Y-%m-%d")]
        elif period == "2 Days":
            dates = [(today - timedelta(days=1)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
        elif period == "3 Days":
            dates = [(today - timedelta(days=2)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
        elif period == "1 Week":
            dates = [(today - timedelta(days=6)).strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")]
        else:
            dates = [today.strftime("%Y-%m-%d")]  # fallback

        url = "http://127.0.0.1:5001/events"
        headers = {"Content-Type": "application/json"}
        data = {
            "action_type": "list_events",
            "payload": {
                "event_type": event_type,
                "dates": dates
    }
    }
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            event_ids = response.json()
        except Exception as e:
            print(f"Fout bij ophalen events: {e}")
            event_ids = []
        self.event_id_listbox.delete(0, tk.END)
        for event_id in event_ids:
            match = re.search(r"\d{4}", event_id)
            display_id = event_id[match.start():] if match else event_id

            if event_id == self.specific_conversation_id:    
                display_id += " ★"

            self.event_id_map[display_id] = event_id
            self.event_id_listbox.insert(tk.END, display_id)
        self.event_details_text.delete("1.0", tk.END)
        self.summary_text.config(state=tk.NORMAL)
        self.summary_text.delete("1.0", tk.END)
        self.summary_text.config(state=tk.DISABLED)

    def show_specific_conversation_state(self, event_id: str):      
        print("show_specific_conversation_state aangeroepen")       

        event_type = "ConversationState"  # We weten dat dit het type is

        url = "http://127.0.0.1:5001/events"
        headers = {"Content-Type": "application/json"}

        # Stap 1: haal het event-object op
        data = {
            "action_type": "get_event",
            "payload": {"event_id": event_id}
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            event_obj = response.json()

            # Toon summary als die er is
            summary = event_obj.get("summary", "")
            self.summary_text.config(state=tk.NORMAL)
            self.summary_text.delete("1.0", tk.END)
            self.summary_text.insert("1.0", summary)
            self._adjust_summary_height(summary)
            self.summary_text.config(state=tk.NORMAL)

            # Stap 2: haal messages op via get_list
            list_id = event_obj.get("messages_list_file")
            if list_id:
                list_data = {
                    "action_type": "get_list",
                    "payload": {"list_id": list_id}
    }
                list_response = requests.post(url, headers=headers, data=json.dumps(list_data), timeout=5)
                list_response.raise_for_status()
                messages = list_response.json()
                formatted = self._format_messages_for_display(messages)
            else:
                formatted = "(Geen messages_list_file gevonden in ConversationState)"

        except Exception as e:
            formatted = f"Fout bij ophalen details: {e}"

        self.event_details_text.delete("1.0", tk.END)
        self.event_details_text.insert("1.0", formatted)
        self.event_details_text.see(tk.END)

    def show_event_details(self, event):
        print("show_event_details aangeroepen")
        selection = self.event_id_listbox.curselection()
        if not selection:
            return
        display_id = self.event_id_listbox.get(selection[0])
        event_id = self.event_id_map.get(display_id, display_id)
        event_type_label = self.event_type_var.get()
        event_type = next(val for label, val in self.event_type_options if label == event_type_label)

        url = "http://127.0.0.1:5001/events"
        headers = {"Content-Type": "application/json"}

        # Stap 1: haal het event-object op
        data = {
            "action_type": "get_event",
            "payload": {
                "event_id": event_id
    }
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            event_obj = response.json()
            self.original_event_data = event_obj
            self.current_event_id = event_id

            # Toon summary als die er is
            summary = event_obj.get("summary", "")
            self.summary_text.config(state=tk.NORMAL)
            self.summary_text.delete("1.0", tk.END)
            self.summary_text.insert("1.0", summary)
            self._adjust_summary_height(summary)
            self.summary_text.config(state=tk.NORMAL)

            # Stap 2: als ConversationState, haal messages op via get_list
            if event_type == "ConversationState":
                list_id = event_obj.get("messages_list_file")
                if list_id:
                    list_data = {
                        "action_type": "get_list",
                        "payload": {"list_id": list_id}
    }
                    list_response = requests.post(url, headers=headers, data=json.dumps(list_data), timeout=5)
                    list_response.raise_for_status()
                    messages = list_response.json()
                    formatted = self._format_messages_for_display(messages)
                else:
                    formatted = "(Geen messages_list_file gevonden in ConversationState)"
            else:
                formatted = json.dumps(event_obj, indent=2, ensure_ascii=False)

        except Exception as e:
            formatted = f"Fout bij ophalen details: {e}"

        self.event_details_text.config(state=tk.NORMAL)  # <<< toevoegen
        self.event_details_text.delete("1.0", tk.END)
        self.event_details_text.insert("1.0", formatted)
        self.event_details_text.config(state=tk.DISABLED)
        self.event_details_text.see(tk.END)

        # Activeer de Set Specific-knop als er een geldige selectie is
        self.set_specific_button.config(state=tk.NORMAL)

    def _set_specific_state(self):
        selection = self.event_id_listbox.curselection()
        if not selection:
            self.status_label.config(text="Geen event geselecteerd.")
            return

        display_id = self.event_id_listbox.get(selection[0])
        full_event_id = self.event_id_map.get(display_id)
        if not full_event_id:
            self.error_label.config(text="Kon volledige event ID niet vinden.")
            return

        url = "http://127.0.0.1:5001/events"
        headers = {"Content-Type": "application/json"}
        data = {
            "action_type": "set_specific_state",
            "payload": {"event_id": full_event_id}
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            result = response.json()
            if result.get("status") == "ok":
                self.status_label.config(text=result.get("message", "Specifieke conversatie ingesteld."))
                self.load_events()
                self.show_specific_conversation_state(full_event_id)
            
            else:
                self.error_label.config(text="Server gaf geen bevestiging terug.")
        except Exception as e:
            self.error_label.config(text=f"Fout bij instellen specifieke state: {e}")

    def _adjust_summary_height(self, text: str):
        lines = text.count("\n") + 1
        lines = min(max(lines, 3), 5)  # minimaal 3, maximaal 5
        self.summary_text.config(height=lines)


    def _delete_event(self):
        selection = self.event_id_listbox.curselection()
        if not selection:
            messagebox.showwarning("Geen selectie", "Selecteer eerst een event om te verwijderen.")
            return

        display_id = self.event_id_listbox.get(selection[0])
        event_id = self.event_id_map.get(display_id, display_id)

        # confirm = messagebox.askyesno("Bevestig verwijderen", f"Weet je zeker dat je '{event_id}' wilt verwijderen?", parent=self.browse_window)
        response = messagebox.askyesnocancel("Bevestig verwijderen", f"Weet je zeker dat je '{event_id}' wilt verwijderen?", parent=self.browse_window)

        if response is None or response is False:  
            return
                
        url = "http://127.0.0.1:5001/events"   
        headers = {"Content-Type": "application/json"}
        data = {
            "action_type": "delete_event",
            "payload": {"event_id": event_id}
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            if self.browse_status_label:
                self.browse_status_label.config(text=f"Event '{event_id}' is verwijderd.") 
            self.load_events()  # Refresh lijst
            self.event_details_text.config(state=tk.NORMAL)
            self.event_details_text.delete("1.0", tk.END)
            self.event_details_text.config(state=tk.DISABLED)
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
            # Update voice in CommunicationManager
            asyncio.run(self.communication_manager.update_voice_id(voice_name))
            self.status_label.config(text=f"Stem bijgewerkt naar {voice_name}")
        except Exception as e:
            self.error_label.config(text=f"Fout bij bijwerken stem: {e}")

             
    def _refresh_available_modes(self):
        url = f"{SERVER_BASE_URL}/mode"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "trigger",
            "trigger_type": "list_modes",
            "action_type": None,
            "payload": None
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            modes = response.json()
            if isinstance(modes, list):
                self.modus_dropdown['values'] = modes
                if self.modus_var.get() not in modes:
                    self.modus_var.set(modes[0] if modes else "")
                with open(MODES_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(modes, f)
                return
        except Exception as e:
            print(f"Fout bij ophalen modi van server: {e}")
            try:
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
        self._clear_messages()
        url = f"{SERVER_BASE_URL}{RELOAD_PROMPTS_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        data = {
            "profile_name": "default"
        }

        try:
            # Disable button
            self.refresh_modus_button.config(state=tk.DISABLED)
            # self.root.update_idletasks()

            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()
            try:
                response_data = response.json()
                self.status_label.config(text=response_data.get('message', 'Prompts reloaded (No message)'))
                print(f"Successfully reloaded prompts, Response: {response_data}")
            except json.JSONDecodeError:
                self.status_label.config(text="Prompts reloaded successfully (non-JSON response)")
                print(f"Successfully reloaded prompts. Status: {response.status_code}, Response: {response.text}")

        except requests.exceptions.Timeout:
            self.error_label.config(text="Error: Prompt reload request timed out.")
            print(f"Error: Timeout requesting prompt reload from {url}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending prompt reload request: {e}")
            error_details = self._format_request_error(e)
            self.error_label.config(text=f"Prompt Reload Error: {error_details}")
        finally:
            # Re-enable button
            self.refresh_modus_button.config(state=tk.NORMAL)

    def edit_prompt_profile(self, profile_name="default"):
        """Opent het editvenster voor een prompt-profiel, maar sluit eerst andere vensters netjes af."""
        if not self.is_prompt_loaded(profile_name):
            self.error_label.config(text=f"Profiel '{profile_name}' is nog niet geladen.")
            return

        self._clear_messages()

        #  Check of messages-editor open is ---
        if self.messages_window and self.messages_window.winfo_exists():
            if self.messages_modified_flag:
                response = messagebox.askyesnocancel(
                    "Unsaved Message Changes",
                    "Je hebt wijzigingen in het messages-venster.\nWil je die bewaren voordat je verdergaat?",
                    parent=self.messages_window)
                if response is True:
                    if not self._keep_message_changes():
                        return  # Parse error, blijf in messages-venster
                elif response is None:
                    return  # Cancel gedrukt
                # False = doorgaan zonder bewaren

            self.messages_window.destroy()
            self.messages_window = None
            self.messages_text_widget = None

        #  Check of prompts-editor al open is ---
        if self.prompts_window and self.prompts_window.winfo_exists():
            if self.prompts_modified_flag:
                response = messagebox.askyesnocancel(
                    "Unsaved Prompt Changes",
                    "Je hebt wijzigingen in het prompts-venster.\nWil je die bewaren voordat je verdergaat?",
                    parent=self.prompts_window)
                if response is True:
                    if not self._keep_prompt_changes():
                        return  # Parse error, blijf in prompts-venster
                elif response is None:
                    return  # Cancel gedrukt
                # False = doorgaan zonder bewaren

            self.prompts_window.destroy()
            self.prompts_window = None
            self.system_text_widget = None
            self.dynamic_text_widget = None

        # Profiel ophalen ---
        if profile_name not in self.prompts:
            self.error_label.config(text=f"Profiel '{profile_name}' niet gevonden.")
            return

        self.current_prompt_profile = profile_name
        current_data = self.prompts[profile_name]["current"]
        system_text = current_data.get("system", "")
        dynamic_text = current_data.get("dynamic", "")

        #  Nieuw venster openen ---
        self.prompts_window = tk.Toplevel(self.root)
        self.prompts_window.title(f"Edit Prompt Profile: {profile_name}")
        self.prompts_window.geometry("800x800")
        self.prompts_window.protocol("WM_DELETE_WINDOW", self._handle_prompt_back)

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
        self.system_text_widget.insert("1.0", system_text)
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
        self.dynamic_text_widget.insert("1.0", dynamic_text)
        dynamic_scrollbar.config(command=self.dynamic_text_widget.yview)

        # Reset modified flags *na* vullen
        self.system_text_widget.edit_modified(False)
        self.dynamic_text_widget.edit_modified(False)

        # Bind wijzigingen *na* reset
        self.system_text_widget.bind("<<Modified>>", self._on_prompt_modified)
        self.dynamic_text_widget.bind("<<Modified>>", self._on_prompt_modified)

        # Knoppen
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))

        ttk.Button(button_frame, text="Back", command=self._handle_prompt_back).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="Push & Close", command=self._push_and_close_prompt).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Save As...", command=self._save_prompt_as).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Delete", command=self._delete_prompt_profile).pack(side=tk.LEFT, padx=5)
        # ttk.Button(button_frame, text="Keep Changes", command=self._keep_prompt_changes).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Undo All Changes", command=self._undo_all_prompt_changes).pack(side=tk.LEFT, padx=5)


        self.prompts_modified_flag = False

    def _pull_current_mode(self):
        self._clear_messages()
        url = f"{SERVER_BASE_URL}/mode"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "trigger",
            "trigger_type": "get_current_mode",
            "action_type": None,
            "payload": None}

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            result = response.json()
            current_mode = result.get("mode", "")
            if current_mode:
                self.modus_var.set(current_mode)
                self.status_label.config(text=f"Huidige modus: '{current_mode}'")
            else:
                self.error_label.config(text="Geen modus ontvangen van server.")
        except Exception as e:
            self.error_label.config(text=f"Fout bij ophalen huidige modus: {e}")

    def _save_prompt_as(self):
        # Vraag om een nieuwe naam
        new_name = simpledialog.askstring("Save Prompt As", "Nieuwe profielnaam:", parent=self.prompts_window)
        if not new_name:
            return  # Gebruiker annuleerde

        # Haal de huidige inhoud op
        system_content = self.system_text_widget.get("1.0", tk.END).strip()
        dynamic_content = self.dynamic_text_widget.get("1.0", tk.END).strip()
        voice = self.prompts[self.current_prompt_profile].get("voice")

        # Bouw de data voor de POST
        url = f"{SERVER_BASE_URL}/prompts"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": "push_prompts",
            "payload": {
                "name": new_name,
                "system_prompt": system_content,
                "dynamic_context": dynamic_content,
                "voice": voice}}

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()
            self.status_label.config(text=f"Huidig prompt-profiel: '{self.current_prompt_profile}'")
            print(f"Prompt-profiel '{new_name}' succesvol opgeslagen.")

            # Voeg het nieuwe profiel toe aan de dropdown (optioneel, maar handig)
            if new_name not in self.prompts:
                self.prompts[new_name] = {
                    "name": new_name,
                    "original": {"system": system_content, "dynamic": dynamic_content},
                    "current": {"system": system_content, "dynamic": dynamic_content},
                    "modified": False,
                    "voice": voice}
                self.prompt_profile_dropdown['values'] = list(self.prompts.keys())
                self.prompt_profile_var.set(new_name)
                self.current_prompt_profile = new_name
                self._update_prompts_status_label()

        except Exception as e:
            self.error_label.config(text=f"Fout bij opslaan: {e}")

    def _delete_prompt_profile(self):
        profile_name = self.current_prompt_profile
        if not profile_name:
            return
        confirm = messagebox.askyesno("Bevestig verwijderen", f"Weet je zeker dat je '{profile_name}' wilt verwijderen?", parent=self.prompts_window)
        if not confirm:
            return

        url = f"{SERVER_BASE_URL}/prompts"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": "delete_prompt",
            "payload": {"name": profile_name}}
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()
            self.status_label.config(text=f"Prompt-profiel '{profile_name}' verwijderd.")
            # Refresh dropdown
            self._refresh_prompt_profiles()
        except Exception as e:
            self.error_label.config(text=f"Fout bij verwijderen: {e}")

    def _refresh_prompt_profiles(self):
        url = f"{SERVER_BASE_URL}/prompts"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "trigger",
            "trigger_type": "list_prompts",
            "action_type": None,
            "payload": None
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            profiles = response.json()
            if isinstance(profiles, list):
                self.prompt_profile_dropdown['values'] = profiles
                self.modus_dropdown['values'] = profiles  # ✅ update modus-dropdown ook  

                if self.current_prompt_profile not in profiles:
                    self.prompt_profile_var.set(profiles[0] if profiles else "")
                    self.current_prompt_profile = self.prompt_profile_var.get()

                if self.modus_var.get() not in profiles:
                    self.modus_var.set(profiles[0] if profiles else "")

                with open(PROMPT_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(profiles, f)
                return
        except Exception as e:
            print(f"Fout bij ophalen profielen van server: {e}")
            try:
                with open(PROMPT_CACHE_PATH, "r", encoding="utf-8") as f:
                    profiles = json.load(f)
                self.prompt_profile_dropdown['values'] = profiles
                self.modus_dropdown['values'] = profiles  # ✅ ook bij fallback

                if self.current_prompt_profile not in profiles:
                    self.prompt_profile_var.set(profiles[0] if profiles else "")
                    self.current_prompt_profile = self.prompt_profile_var.get()

                if self.modus_var.get() not in profiles:
                    self.modus_var.set(profiles[0] if profiles else "")

                self.status_label.config(text="Profielen geladen uit lokale cache.")      
            except Exception as e2:
                self.error_label.config(text="Geen verbinding en geen lokale profielen beschikbaar.")


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
        selection = self.event_id_listbox.curselection()
        if not selection:
            messagebox.showwarning("Geen selectie", "Selecteer eerst een event om te bewaren.")
            return

        display_id = self.event_id_listbox.get(selection[0])
        event_id = self.event_id_map.get(display_id, display_id)

        new_summary = self.summary_text.get("1.0", tk.END).strip()

        url = "http://127.0.0.1:5001/events"   
        headers = {"Content-Type": "application/json"}
        save_data = {
            "action_type": "save_summary",
            "payload": {
                "event_id": event_id,
                "event_type": "ConversationState",
                "summary": new_summary
    }
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(save_data), timeout=5)
            response.raise_for_status()
            self.browse_status_label.config(text="Summary saved.")
            self.save_summary_button.config(state=tk.DISABLED)
        except Exception as e:
            self.browse_status_label.config(text=f"Error saving summary: {e}")


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
        """Stuurt het huidige prompt-profiel naar de server en sluit het venster bij succes."""
        if not self._keep_prompt_changes():
            return  # Als bewaren mislukt, niet pushen

        profile = self.prompts[self.current_prompt_profile]

        url = f"{SERVER_BASE_URL}/prompts"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": "push_prompts",
            "payload": {
                "name": profile["name"],
                "system_prompt": profile["current"]["system"],
                "dynamic_context": profile["current"]["dynamic"],
                "voice": profile.get("voice")
            }
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()
            response_data = response.json()

            self.status_label.config(text=f"Prompt-profiel '{profile['name']}' gepusht.")
            print(f"Prompt-profiel '{profile['name']}' succesvol gepusht: {response_data}")

            # Sluit venster na succesvolle push
            if self.prompts_window and self.prompts_window.winfo_exists():      
                self.prompts_window.destroy()

            self.prompts_window = None    
            self.system_text_widget = None
            self.dynamic_text_widget = None
            self.prompts_modified_flag = False
            self._update_prompts_status_label()

        except requests.exceptions.Timeout:
            self.error_label.config(text="Error: Push prompt-profiel timed out.")
        except requests.exceptions.RequestException as e:
            error_details = self._format_request_error(e)
            self.error_label.config(text=f"Push prompt-profiel fout: {error_details}")

    def edit_prompts(self):
        self._clear_messages()
        self.status_label.config(text="Edit Prompts: nog niet geïmplementeerd.")

    def push_prompts(self):
        self._clear_messages()
        self.status_label.config(text="Push Prompts: nog niet geïmplementeerd.")

    def pull_prompt_profile(self, profile_name="default"):
    
        self._clear_messages()
        url = f"{SERVER_BASE_URL}/prompts"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "trigger",
            "trigger_type": "pull_prompts",
            "action_type": None,
            "payload": {"name": profile_name}}

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()
            response_data = response.json()

            # Verwacht: {"system_prompt": "...", "dynamic_context": "...", "voice": "George"}
            system = response_data.get("system_prompt", "")
            dynamic_raw = response_data.get("dynamic_context", "")
            if isinstance(dynamic_raw, list):
                user_msg = next((msg.get("content", "") for msg in dynamic_raw if msg.get("role") == "user"), "")     
                dynamic = user_msg
            else:
                dynamic = dynamic_raw
            voice = response_data.get("voice", None)

            if profile_name not in self.prompts:
                self.prompts[profile_name] = {
                    "name": profile_name,
                    "original": {"system": "", "dynamic": ""},
                    "current": {"system": "", "dynamic": ""},
                    "modified": False,
                    "voice": voice}

            self.prompts[profile_name]["original"]["system"] = system
            self.prompts[profile_name]["original"]["dynamic"] = dynamic
            self.prompts[profile_name]["current"]["system"] = system
            self.prompts[profile_name]["current"]["dynamic"] = dynamic
            self.prompts[profile_name]["modified"] = False
            self.prompts[profile_name]["voice"] = voice

            self.status_label.config(text=f"Prompt-profiel '{profile_name}' opgehaald.")
            if self.is_prompt_loaded(profile_name):
                self.edit_prompts_button.config(state=tk.NORMAL)
                self.push_prompts_button.config(state=tk.NORMAL)
            print(f"Profiel '{profile_name}' geladen: voice={voice}")
            self._update_prompts_status_label()

        except requests.exceptions.Timeout:
            self.error_label.config(text="Error: Prompt-profiel ophalen timed out.")
        except requests.exceptions.RequestException as e:
            error_details = self._format_request_error(e)
            self.error_label.config(text=f"Prompt-profiel fout: {error_details}")

    def _add_modus(self):
        self._clear_messages()
        modus_naam = simpledialog.askstring("Nieuwe Modus", "Voer de naam in voor de nieuwe modus (prompt-profiel):", parent=self.root)
        if not modus_naam:
            self.error_label.config(text="Toevoegen geannuleerd of geen naam ingevoerd.") 
            return

        # Gebruik huidige prompt als basis     
        current_profile = self.prompts.get(self.current_prompt_profile)
        if not current_profile:
            self.error_label.config(text="Huidig prompt-profiel niet gevonden.")
            return

        system_prompt = current_profile["current"]["system"]
        dynamic_context = current_profile["current"]["dynamic"]
        voice = current_profile.get("voice")

        url = f"{SERVER_BASE_URL}/prompts"     
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": "push_prompts",
            "payload": {
                "name": modus_naam,
                "system_prompt": system_prompt,
                "dynamic_context": dynamic_context,
                "voice": voice
    }
    }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()
            self.status_label.config(text=f"Nieuwe modus '{modus_naam}' toegevoegd als prompt-profiel.")
            self._refresh_prompt_profiles()
        except Exception as e:
            self.error_label.config(text=f"Fout bij toevoegen modus: {e}")




    # --- In Summary Controls ---
    def push_summary(self) -> bool: # Add return type hint
        """Sends the summary text to the /message endpoint using PUSH_SUMMARY action. Returns True on success, False on failure."""
        self._clear_messages()
        # --- Get text from tk.Text widget ---
        summary_text = self.summary_entry.get("1.0", tk.END).strip() # Get text and remove leading/trailing whitespace

        if not summary_text:
            self.error_label.config(text="Error: Summary cannot be empty to push.")
            return False

        url = f"{SERVER_BASE_URL}{MESSAGE_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": ACTION_PUSH_SUMMARY,
            "payload": {"text": summary_text}
        }
        success = False # Flag for return value
        try:
            self.push_summary_button.config(state=tk.DISABLED)
            self.root.update_idletasks()

            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()
            self._handle_api_success_response(response, "Summary pushed")
            self.summary_entry.delete("1.0", tk.END)  # 🧹 Leegmaken na push
            success = True # Set flag on success

        except requests.exceptions.Timeout:
            self.error_label.config(text="Error: Summary push request timed out.")
            print(f"Error: Timeout sending summary push to {url}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending summary push request: {e}")
            error_details = self._format_request_error(e)
            self.error_label.config(text=f"Summary Push Error: {error_details}")
        finally:
            self.push_summary_button.config(state=tk.NORMAL)
            return success # Return the success flag

    def pull_summary(self):
        """Fetches the current summary via the /message POST endpoint using pull_summary trigger."""
        self._clear_messages()
        url = f"{SERVER_BASE_URL}{MESSAGE_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME, # Consistent name
            "recipient": RECIPIENT_NAME, # Consistent name
            "message_type": "trigger",
            "trigger_type": ACTION_PULL_SUMMARY, # Defined constant
            "action_type": None,
            "payload": None
        }

        try:
            # Disable button
            self.pull_summary_button.config(state=tk.DISABLED)
            self.root.update_idletasks()

            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()

            summary_text = ""
            try:
                # response.json() correctly handles JSON strings -> Python strings
                summary_text = response.json()
                if not isinstance(summary_text, str):
                    print(f"Warning: Expected string from summary pull, got {type(summary_text)}. Converting.")
                    summary_text = str(summary_text)

            except json.JSONDecodeError:
                print(f"Warning: Response from {url} for summary pull was not valid JSON. Using raw text.")
                summary_text = response.text
                # Optional: Try stripping quotes if it's non-JSON but looks like '"text"'
                if len(summary_text) >= 2 and summary_text.startswith('"') and summary_text.endswith('"'):
                    summary_text = summary_text[1:-1]

            self.summary_entry.delete("1.0", tk.END) # <<< Correct index for tk.Text
            self.summary_entry.insert("1.0", summary_text)
            self.status_label.config(text="Summary pulled successfully.")
            print(f"Successfully pulled summary via POST to {url}")

        except requests.exceptions.Timeout:
            self.error_label.config(text="Error: Summary pull request timed out.")
            print(f"Error: Timeout while POSTing for summary to {url}")
        except requests.exceptions.RequestException as e:
            print(f"Error pulling summary via POST: {e}")
            error_details = self._format_request_error(e)
            self.error_label.config(text=f"Summary Pull Error: {error_details}")
        finally:
            # Re-enable button
            self.pull_summary_button.config(state=tk.NORMAL)


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
        """Fetches messages, stores them, updates status, and opens/refreshes the editor.
           Prompts if editor is open."""
        self._clear_messages()

        # --- Check if editor is open ---
        # Prompt regardless of modification status if window exists
        if self.messages_window and self.messages_window.winfo_exists():
            response = messagebox.askyesno( # Changed to askyesno
                "Confirm Pull",
                "This will discard current editor content (if any) and pull fresh messages.\n\n"
                "Proceed?",
                parent=self.root
            )

            if response is True: # Yes - Discard/Close and Pull
                print("Discarding editor content (if any) and proceeding with pull.")
                # Force close the editor window
                if self.messages_window and self.messages_window.winfo_exists():
                    self.messages_window.destroy()
                self.messages_window = None
                self.messages_text_widget = None
                self.push_close_button_ref = None
                # Modified flag will be reset on successful pull below
                # Allow the code below to execute...

            else: # No or Closed Box
                self.status_label.config(text="Pull operation cancelled.")
                return # Cancel the pull operation

        # --- If window wasn't open OR user chose "Yes" (Discard), proceed to pull ---

        # --- Network Request Logic ---
        url = f"{SERVER_BASE_URL}{MESSAGE_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "trigger",
            "trigger_type": ACTION_PULL_CONVERSATION,
            "action_type": None,
            "payload": None
        }

        try:
            # Disable button during request
            self.pull_messages_button.config(state=tk.DISABLED)
            self.root.update_idletasks()

            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10)
            response.raise_for_status()

            # --- Process successful response ---
            try:
                messages = response.json()
                if not isinstance(messages, list):
                    self.error_label.config(text="Error: Expected list from server, got different format.")
                    print(f"Unexpected response format pulling messages. Expected list, got {type(messages)}")
                    self.clear_local_messages() # Reset state on bad data
                    return # Stop processing here

                # Success - Store messages
                self.original_messages = copy.deepcopy(messages)
                self.current_messages = messages
                self.messages_modified_flag = False # Reset modified flag on successful pull
                self.status_label.config(text=f"Messages pulled ({len(messages)}).")
                print(f"Successfully pulled {len(messages)} messages")
                self._update_messages_status_and_buttons() # Update count and buttons

                # --- Refresh or Open Editor ---
                if self.messages_window and self.messages_window.winfo_exists():
                    # Window exists, just update its content and bring to front
                    self._reformat_messages_display()
                    self.messages_window.lift()
                    self.messages_window.focus_force()
                    # Reset modified state just in case reformat triggered something
                    if self.messages_text_widget:
                         self.messages_text_widget.edit_modified(False)
                    self.messages_modified_flag = False
                    self._update_messages_status_and_buttons()
                else:
                    # Window doesn't exist, open a new one
                    self._display_messages()
                # --- End Editor Refresh/Open ---

            except json.JSONDecodeError:
                self.error_label.config(text="Error: Could not parse server response (messages).")
                print(f"Error: Invalid JSON in response pulling messages from {url}")
                self.clear_local_messages() # Reset state on bad data

        except requests.exceptions.Timeout:
            self.error_label.config(text="Error: Messages pull request timed out.")
            print(f"Error: Timeout while requesting messages from {url}")
            # Don't clear local messages on timeout, might be temporary
            self._update_messages_status_and_buttons() # Ensure button states are correct
        except requests.exceptions.RequestException as e:
            print(f"Error pulling messages: {e}")
            error_details = self._format_request_error(e)
            self.error_label.config(text=f"Messages Pull Error: {error_details}")
            # Don't clear local messages on request error
            self._update_messages_status_and_buttons() # Ensure button states are correct
        finally:
             # Re-enable button AFTER request finishes or fails
             self.pull_messages_button.config(state=tk.NORMAL)
             # Update status/buttons again in case state changed during error handling
             self._update_messages_status_and_buttons()


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
        """Pushes the currently stored self.current_messages to the server.
           Prompts to push summary if it exists."""
        self._clear_messages()
        if self.current_messages is None:
            self.error_label.config(text="Error: No messages loaded to push.")
            return
        # Push button already handles modified flag warning (implicitly pushes kept state)

        # --- Check for summary and ask initial question ---
        summary_text = self.summary_entry.get("1.0", tk.END).strip() # <<< CORRECTED: Added arguments for tk.Text.get()
        push_summary_flag = False
        if summary_text:
            push_summary_flag = messagebox.askyesno(
                "Push Summary?",
                "Summary field is not empty.\nPush the summary as well after pushing messages?",
                parent=self.root # Relative to main window
            )
        # --- End NEW ---

        url = f"{SERVER_BASE_URL}{MESSAGE_ENDPOINT}"
        headers = {"Content-Type": "application/json"}
        payload_data = {
            "sender": SENDER_NAME,
            "recipient": RECIPIENT_NAME,
            "message_type": "action_request",
            "trigger_type": None,
            "action_type": ACTION_PUSH_CONVERSATION,
            "payload": {
                "conversation": self.current_messages # Push the kept state
            }
        }

        message_push_success = False # Track success
        try:
            self.push_messages_button.config(state=tk.DISABLED)
            self.root.update_idletasks()

            response = requests.post(url, headers=headers, data=json.dumps(payload_data), timeout=15)
            response.raise_for_status()

            # --- Message Push Success ---
            message_push_success = True
            self._handle_api_success_response(response, f"Messages ({len(self.current_messages)}) pushed")
            # Note: Pushing main messages doesn't change modified flag itself

            # --- Handle potential summary push ---
            if push_summary_flag:
                print("Proceeding to push summary after successful message push...")
                self.push_summary() # Call push_summary (it handles its own status/errors)
            # --- End NEW ---

        except requests.exceptions.Timeout:
            self.error_label.config(text="Error: Message push request timed out.")
            print(f"Error: Timeout sending message push to {url}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending message push request: {e}")
            error_details = self._format_request_error(e)
            self.error_label.config(text=f"Message Push Error: {error_details}")
        finally:
            # --- Handle summary push if message push FAILED ---
            if not message_push_success and push_summary_flag:
                 push_anyway = messagebox.askyesno(
                     "Push Summary?",
                     "Message push failed. Do you still want to try pushing the summary?",
                     parent=self.root
                 )
                 if push_anyway:
                     print("Attempting to push summary after message push failed...")
                     self.push_summary()
            # --- End NEW ---

            # Re-enable button (only if messages still exist conceptually)
            if self.current_messages is not None:
                self.push_messages_button.config(state=tk.NORMAL)
            self._update_messages_status_and_buttons() # Refresh status/button states


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
        if not hasattr(self, 'current_event_id') or not self.current_event_id:
            messagebox.showwarning("No Event", "No event selected to save.", parent=self.browse_window)
            return

        updated_summary = self.summary_text.get("1.0", tk.END).strip()
        updated_details = self.event_details_text.get("1.0", tk.END).strip()

        url = "http://127.0.0.1:5001/events"
        headers = {"Content-Type": "application/json"}
        data = {
            "action_type": "update_event",
            "payload": {
                "event_id": self.current_event_id,
                "summary": updated_summary,
                "details": updated_details
            }
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=5)
            response.raise_for_status()
            self.browse_status_label.config(text="Event details saved.")
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


# if __name__ == "__main__":
#     root = tk.Tk()
#     app = VoiceUI(root, voices)
#     root.mainloop()