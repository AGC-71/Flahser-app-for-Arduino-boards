# --- IMPORTS COMUNES ---
import csv
import json
import subprocess
import sys
import threading
import time
import os
from pathlib import Path
import serial
import serial.tools.list_ports

# --- 1. DETECCIÓN DE PLATAFORMA ---
try:
    # Try to import Pi libraries
    import RPi.GPIO as GPIO
    from RPLCD.i2c import CharLCD
    RUN_MODE = "PI"
except (ImportError, RuntimeError):
    # If it fails, we are on a PC
    RUN_MODE = "PC"

# --- 2. IMPORTS CONDICIONALES (BASADOS EN PLATAFORMA) ---
if RUN_MODE == "PC":
    # Libraries for the PC GUI
    import ttkbootstrap as ttk
    from ttkbootstrap.constants import *
    from ttkbootstrap.constants import INFO, SECONDARY, SUCCESS
    from PIL import Image, ImageTk
    from tkinter import messagebox, filedialog, scrolledtext, BOTH, END, LEFT, RIGHT, X, Y, WORD, NORMAL, DISABLED
else:
    # GPIO Pins (YOU MUST ADJUST THESE NUMBERS!)
    PIN_LCD_SDA = 2  # I2C SDA Pin
    PIN_LCD_SCL = 3  # I2C SCL Pin
    PIN_BTN_UP = 17    # Up Button
    PIN_BTN_DOWN = 27  # Down Button
    PIN_BTN_OK = 22    # OK/Enter Button
    PIN_BTN_BACK = 23  # Back/Cancel Button


# --- 3. CONFIGURACIÓN GLOBAL Y UTILIDADES ---

def get_base_path():
    """ Gets the base path, works for development and PyInstaller """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    else:
        return Path(__file__).parent

BASE_PATH = get_base_path()
SETTINGS_FILE = Path.home() / "dual_uploader_settings.json"

def load_settings():
    """Loads settings from a JSON file."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except json.JSONDecodeError: return {}
    return {}

def save_settings(settings):
    """Saves settings to the JSON file."""
    with open(SETTINGS_FILE, "w") as f: json.dump(settings, f, indent=4)

# Load settings first
settings = load_settings()

# Define default paths (platform-dependent)
if RUN_MODE == "PC":
    default_cli_path = BASE_PATH / "arduino-cli" / "arduino-cli.exe"
else:
    # On Pi/Linux, the executable has no .exe
    default_cli_path = BASE_PATH / "arduino-cli" / "arduino-cli"

default_log_path = Path.home() / "upload_log.csv"

# Use settings paths or defaults
ARDUINO_CLI_PATH = Path(settings.get("arduino_cli_path", default_cli_path))
LOG_CSV_PATH = Path(settings.get("log_csv_path", default_log_path))
DEFAULT_FQBN = "arduino:avr:nano"

# --- Utility Functions (Global) ---
def get_arduino_ports():
    """Detects and returns a list of Arduino ports."""
    ports_found = []
    known_vids = [0x2341, 0x1A86, 0x0403, 0x10C4]
    for port in serial.tools.list_ports.comports():
        if port.vid in known_vids or "Arduino" in port.description or "CH340" in port.description:
            ports_found.append(port.device)
    return sorted(ports_found)

def log_to_csv(data_row):
    """Appends a row to the CSV log."""
    file_exists = LOG_CSV_PATH.exists()
    with open(LOG_CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        # Use semicolon for better Excel compatibility in some regions
        writer = csv.writer(f, delimiter=';') 
        if not file_exists:
            # Headers corrected for separate Date/Time
            writer.writerow(["Date", "Time", "Port", "Sketch", "UploadStatus", "ValueRead", "Details"])
        writer.writerow(data_row)

# --- 4. THE "ENGINE" (BACKEND) ---
class UploaderCore:
    """
    Contains all compile and upload logic.
    Knows nothing about GUIs or LCDs.
    """
    def __init__(self, logger_callback, status_callback):
        self.settings = {}
        self.log = logger_callback      # Function to send logs (to GUI or LCD)
        self.set_status = status_callback # Function to report status (STARTING, SUCCESS, FAIL)

    def load_app_settings(self):
        """Loads settings from the global file."""
        self.settings = load_settings()
        # Ensure default values
        self.settings.setdefault("default_sketch_path", "Default sketch not set")
        self.settings.setdefault("custom_sketch_path", "")
        self.settings.setdefault("baud_rate", "9600")
        self.settings.setdefault("port", "")
        self.settings.setdefault("fqbn", DEFAULT_FQBN)
        self.settings.setdefault("arduino_cli_path", str(ARDUINO_CLI_PATH))
        self.settings.setdefault("log_csv_path", str(LOG_CSV_PATH))

    def save_app_settings(self):
        """Saves current settings to the file."""
        global ARDUINO_CLI_PATH, LOG_CSV_PATH
        # Update global variables if they were changed
        ARDUINO_CLI_PATH = Path(self.settings["arduino_cli_path"])
        LOG_CSV_PATH = Path(self.settings["log_csv_path"])
        save_settings(self.settings)

    def start_compile_and_upload(self, sketch_path, port, baud_rate, fqbn):
        """
        Target function for the Thread. Executes the whole process.
        """
        self.set_status("UPLOADING")
        sketch_name = Path(sketch_path).name

        # --- 0. Validation ---
        if "No ports" in port or not baud_rate.isdigit():
            self.log("ERROR: Port and Baud Rate not configured.")
            self.set_status("FAIL")
            return

        # --- 1. Compile ---
        compile_ok, compile_details = self._compile_sketch(sketch_path, fqbn)
        
        upload_ok = False
        upload_details = "N/A"
        read_value = "N/A"

        # --- 2. Upload ---
        if compile_ok:
            upload_ok, upload_details = self._upload_sketch(sketch_path, port, fqbn)
        else:
            upload_details = "Upload skipped due to compilation failure."
            
        # --- 3. Read Value ---
        if upload_ok:
            read_value = self._read_from_serial(port, baud_rate)
        
        # --- 4. Log to CSV (with separate Date/Time) ---
        current_date = time.strftime('%Y-%m-%d')
        current_time = time.strftime('%H:%M:%S')
        log_to_csv([
            current_date, current_time, port, sketch_name,
            "SUCCESS" if upload_ok else "FAIL", read_value,
            f"{compile_details} | {upload_details}".replace("\r", " ").replace("\n", " ")
        ])
        
        self.log(f"Process completed. Log saved.")
        self.set_status("SUCCESS" if upload_ok else "FAIL")

    def _compile_sketch(self, sketch_path, fqbn):
        """Compiles the sketch and returns status."""
        sketch_name = Path(sketch_path).name
        compile_cmd = [str(ARDUINO_CLI_PATH), "compile", "--fqbn", fqbn, sketch_path]
        success = self._run_command_realtime(compile_cmd, log_prefix=f"Compiling {sketch_name}")

        if success:
            self.log("Compile successful.")
            return True, "Compile OK."
        else:
            self.log("ERROR: Compile failed.")
            return False, "Compile FAIL."

    def _upload_sketch(self, sketch_path, port, fqbn):
        """Uploads the sketch, trying new and old bootloaders."""
        upload_cmd = [str(ARDUINO_CLI_PATH), "upload", "-p", port, "--fqbn", fqbn, sketch_path]
        success = self._run_command_realtime(upload_cmd, log_prefix=f"Uploading to {port}")

        if success:
            self.log("Upload successful!")
            return True, "Upload OK."

        # Retry with old bootloader
        self.log("Upload failed. Retrying with old bootloader...")
        fqbn_old = f"{fqbn}:cpu=atmega328old"
        upload_cmd_old = [str(ARDUINO_CLI_PATH), "upload", "-p", port, "--fqbn", fqbn_old, sketch_path]
        success_old = self._run_command_realtime(upload_cmd_old, log_prefix="Uploading (old bootloader)")

        if success_old:
            self.log("Upload successful (old bootloader)!")
            return True, "Upload OK (old bootloader)."
        else:
            self.log("ERROR: Upload failed on all attempts.")
            return False, "Upload FAIL."

    def _read_from_serial(self, port, baud_rate):
        """Reads one line from the serial port."""
        self.log(f"Reading from {port} at {baud_rate} baud...")
        try:
            with serial.Serial(port, int(baud_rate), timeout=2.0) as sp:
                time.sleep(2)  # Wait for reset
                sp.reset_input_buffer()
                line = sp.readline().decode('utf-8').strip()
                if line:
                    self.log(f"Data received: {line}")
                    return line
                else:
                    self.log("Warning: No data received from serial.")
                    return "No data"
        except Exception as e:
            self.log(f"ERROR: Could not read from serial: {e}")
            return "Read ERROR"

    def _run_command_realtime(self, command, log_prefix=""):
        """Executes a command and sends its output to the log callback."""
        self.log(f"{log_prefix}...")
        # Flags to prevent console window on Windows
        creation_flags = subprocess.CREATE_NO_WINDOW if RUN_MODE == "PC" else 0
        
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', creationflags=creation_flags)
        
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                self.log(output.strip()) # Send to logger
        
        return process.poll() == 0

# --- 5. PC INTERFACE (TKINTER / TTKBOOTSTRAP) ---
if RUN_MODE == "PC":
    class WindowsGuiApp(ttk.Window):
        def __init__(self, theme="superhero"):
            super().__init__(themename=theme)
            self.title("Dual-Mode Arduino Uploader")
            self.geometry("632x650")

            # Create the engine and connect it to this GUI's functions
            self.core = UploaderCore(
                logger_callback=self.gui_log,
                status_callback=self.gui_status_update
            )
            self.core.load_app_settings()

            # --- Load Tkinter Variables from Core ---
            self.default_sketch_path_var = ttk.StringVar(value=self.core.settings["default_sketch_path"])
            self.custom_sketch_path_var = ttk.StringVar(value=self.core.settings["custom_sketch_path"])
            self.baud_rate_var = ttk.StringVar(value=self.core.settings["baud_rate"])
            self.port_var = ttk.StringVar(value=self.core.settings["port"])
            self.fqbn_var = ttk.StringVar(value=self.core.settings["fqbn"])
            self.first_port_check_done = False # Fix for double-scan on startup

            self._load_icons()
            self._create_widgets()

            self.refresh_ports()
            self.periodic_port_check()
            self.protocol("WM_DELETE_WINDOW", self.on_closing)

        def _load_icons(self):
            """Loads icons for the buttons."""
            try:
                img_settings = Image.open(BASE_PATH / "icons/settings.png").resize((16, 16))
                self.settings_icon = ImageTk.PhotoImage(img_settings)
                img_browse = Image.open(BASE_PATH / "icons/folder.png").resize((16, 16))
                self.browse_icon = ImageTk.PhotoImage(img_browse)
                img_log = Image.open(BASE_PATH / "icons/log.png").resize((16, 16))
                self.log_icon = ImageTk.PhotoImage(img_log)
                img_clear = Image.open(BASE_PATH / "icons/clear.png").resize((16, 16))
                self.clear_icon = ImageTk.PhotoImage(img_clear)
                img_about = Image.open(BASE_PATH / "icons/about.png").resize((16, 16))
                self.about_icon = ImageTk.PhotoImage(img_about)
            except Exception as e:
                print(f"Error loading icons: {e}. Buttons will be text-only.")
                self.settings_icon = None
                self.browse_icon = None
                self.log_icon = None
                self.clear_icon = None
                self.about_icon = None

        def _create_widgets(self):
            """Creates and lays out all GUI widgets."""
            
            # --- Frames ---
            quick_frame = ttk.LabelFrame(self, text="1. Quick Upload (Color Sensor)", padding=(10, 10))
            quick_frame.pack(fill=X, padx=10, pady=10)

            custom_frame = ttk.LabelFrame(self, text="2. Custom Upload (Other sketch)", padding=(10, 10))
            custom_frame.pack(fill=X, padx=10, pady=5)

            log_frame = ttk.LabelFrame(self, text="Upload Log", padding=(10, 10))
            log_frame.pack(fill=BOTH, expand=True, padx=10, pady=(5, 10))

            # --- Quick Upload Widgets ---
            ttk.Label(quick_frame, text="Default Sketch Path:").grid(row=0, column=0, columnspan=4, sticky="w")
            ttk.Label(quick_frame, textvariable=self.default_sketch_path_var, bootstyle=INFO, wraplength=500, justify=LEFT).grid(row=1, column=0, columnspan=3, sticky="w")
            ttk.Button(quick_frame, text="Set/Change", command=self.set_default_sketch, image=self.browse_icon, compound=LEFT, bootstyle=SECONDARY).grid(row=1, column=3, padx=10, sticky="e")

            ttk.Label(quick_frame, text="COM Port:").grid(row=2, column=0, sticky="w", pady=(10, 0))
            ttk.Label(quick_frame, text="Baud Rate:").grid(row=2, column=1, sticky="w", padx=10, pady=(10, 0))

            self.port_menu = ttk.OptionMenu(quick_frame, self.port_var, "No ports")
            self.port_menu.grid(row=3, column=0, sticky="ew", padx=(0, 10))
            ttk.Entry(quick_frame, textvariable=self.baud_rate_var, width=10).grid(row=3, column=1, sticky="w", padx=10)
            ttk.Button(quick_frame, text="Refresh Ports", command=self.refresh_ports, bootstyle=SECONDARY).grid(row=3, column=2, sticky="w", padx=10)

            self.quick_upload_button = ttk.Button(quick_frame, text="Upload Color Sensor Sketch", command=lambda: self.start_upload_thread(use_default=True), bootstyle=SUCCESS)
            self.quick_upload_button.grid(row=4, column=0, columnspan=4, pady=15, sticky="ew")

            # --- Custom Upload Widgets ---
            ttk.Label(custom_frame, text="Sketch to Upload:").grid(row=0, column=0, sticky="w")
            ttk.Entry(custom_frame, textvariable=self.custom_sketch_path_var, width=80).grid(row=1, column=0, sticky="ew")
            ttk.Button(custom_frame, text="Browse...", command=self.select_custom_sketch, image=self.browse_icon, compound=LEFT).grid(row=1, column=1, padx=5)
            self.custom_upload_button = ttk.Button(custom_frame, text="Upload Selected Sketch", command=lambda: self.start_upload_thread(use_default=False))
            self.custom_upload_button.grid(row=2, column=0, columnspan=2, pady=10, sticky="ew")

            # --- Log Frame ---
            log_button_frame = ttk.Frame(log_frame)
            log_button_frame.pack(fill=X)
            
            ttk.Button(log_button_frame, text="About", command=self.show_about_dialog, image=self.about_icon, compound=LEFT, bootstyle=SECONDARY).pack(side=LEFT, pady=(0, 5), padx=(0, 5))
            ttk.Button(log_button_frame, text="Clear Log", command=self.clear_log_display, image=self.clear_icon, compound=LEFT, bootstyle=SECONDARY).pack(side=LEFT, pady=(0, 5), padx=5)
            ttk.Button(log_button_frame, text="View Log (.csv)", command=self.open_log_file, image=self.log_icon, compound=LEFT, bootstyle=SECONDARY).pack(side=LEFT, pady=(0, 5), padx=5)
            ttk.Label(log_button_frame, text="").pack(side=LEFT, expand=True) # Spacer
            ttk.Button(log_button_frame, text="Config...", command=self.open_settings_window, image=self.settings_icon, compound=LEFT, bootstyle=SECONDARY).pack(side=RIGHT, pady=(0, 5))

            self.log_area = scrolledtext.ScrolledText(log_frame, wrap=WORD, height=10)
            self.log_area.pack(fill=BOTH, expand=True)
        
        # --- Callbacks for the Core ---
        def gui_log(self, msg):
            """Function the Core uses to send logs to the GUI. (FIXED)"""
            
            if "ERROR" in msg:
                print(msg) # Also print errors to console
            
            # --- Single Insertion Logic ---
            
            # Messages from _run_command_realtime (like "Compiling", 
            # "Uploading", etc.) are noisy and shouldn't get a timestamp.
            # 'msg' is already stripped of newlines by the Core.
            if "Compiling" in msg or "Uploading" in msg or "Writing" in msg or "Reading" in msg:
                 self.log_area.insert(END, msg + "\n") 
                 self.update_idletasks() # Force update for live view
            else:
                 # All other logs (Scanning, Error, Success, etc.)
                 # get a timestamp.
                 msg_with_time = f"{time.strftime('%H:%M:%S')} - {msg}\n"
                 self.log_area.insert(END, msg_with_time)
            
            self.log_area.see(END) # Move auto-scroll to the end


        def gui_status_update(self, status):
            """Function the Core uses to change GUI state."""
            if status == "UPLOADING":
                self.quick_upload_button.config(state=DISABLED)
                self.custom_upload_button.config(state=DISABLED)
            else: # "SUCCESS" or "FAIL"
                self.quick_upload_button.config(state=NORMAL)
                self.custom_upload_button.config(state=NORMAL)
                if status == "FAIL":
                    messagebox.showerror("Upload Failed", "Upload failed. Check the log for details.")

        # --- GUI Functions ---
        def on_closing(self):
            """Saves settings on close."""
            self.core.settings["default_sketch_path"] = self.default_sketch_path_var.get()
            self.core.settings["custom_sketch_path"] = self.custom_sketch_path_var.get()
            self.core.settings["baud_rate"] = self.baud_rate_var.get()
            self.core.settings["port"] = self.port_var.get()
            self.core.settings["fqbn"] = self.fqbn_var.get()
            self.core.save_app_settings()
            self.destroy()

        def set_default_sketch(self):
            path = filedialog.askopenfilename(title="Select default COLOR-SENSOR.ino", filetypes=[("Arduino Files", "*.ino")])
            if path:
                self.default_sketch_path_var.set(path)
                self.gui_log(f"New default sketch: {path}")

        def select_custom_sketch(self):
            path = filedialog.askopenfilename(title="Select custom Arduino Sketch", filetypes=[("Arduino Files", "*.ino")])
            if path:
                self.custom_sketch_path_var.set(path)
                self.gui_log(f"Custom sketch selected: {path}")

        def refresh_ports(self):
            self.gui_log("Scanning COM ports...")
            ports = get_arduino_ports()
            menu = self.port_menu["menu"]
            menu.delete(0, END)
            last_port = self.port_var.get()
            if ports:
                for port in ports:
                    menu.add_command(label=port, command=lambda p=port: self.port_var.set(p))
                self.port_var.set(last_port if last_port in ports else ports[0])
                self.gui_log(f"Ports found: {', '.join(ports)}")
            else:
                self.port_var.set("No ports")
                self.gui_log("No compatible ports detected.")

        def start_upload_thread(self, use_default=False):
            """Prepares and starts the Core's upload thread."""
            self.log_area.delete('1.0', END)
            sketch_path = self.default_sketch_path_var.get() if use_default else self.custom_sketch_path_var.get()
            
            if not Path(sketch_path).is_file():
                messagebox.showerror("Error", f"Sketch file not found:\n{sketch_path}")
                return
            
            # Pass current values to the Core for execution
            threading.Thread(
                target=self.core.start_compile_and_upload,
                args=(
                    sketch_path,
                    self.port_var.get(),
                    self.baud_rate_var.get(),
                    self.fqbn_var.get()
                ),
                daemon=True
            ).start()
        
        def periodic_port_check(self):
            """Periodically checks for port changes."""
            
            # Fix for double-scan on startup
            if not self.first_port_check_done:
                self.first_port_check_done = True
                self.after(2000, self.periodic_port_check)
                return
            
            try:
                menu = self.port_menu["menu"]
                ports_in_menu = []
                if menu.index("end") is not None:
                    ports_in_menu = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
                current_ports = get_arduino_ports()
                if sorted(ports_in_menu) != sorted(current_ports):
                    self.gui_log("Port change detected! Refreshing...")
                    self.refresh_ports()
                self.after(2000, self.periodic_port_check)
            except Exception as e:
                print(f"Error during port check: {e}")

        def open_settings_window(self):
            settings_win = ttk.Toplevel(self)
            settings_win.title("Configure Paths")
            settings_win.geometry("550x250")

            cli_path_var = ttk.StringVar(value=self.core.settings["arduino_cli_path"])
            log_path_var = ttk.StringVar(value=self.core.settings["log_csv_path"])
            fqbn_var = ttk.StringVar(value=self.core.settings["fqbn"])

            def select_cli_path():
                path = filedialog.askopenfilename(title="Select arduino-cli")
                if path: cli_path_var.set(path)
            
            def select_log_path():
                path = filedialog.asksaveasfilename(title="Select Log CSV", defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
                if path: log_path_var.set(path)

            def save_paths():
                self.core.settings["arduino_cli_path"] = cli_path_var.get()
                self.core.settings["log_csv_path"] = log_path_var.get()
                self.core.settings["fqbn"] = fqbn_var.get()
                self.fqbn_var.set(fqbn_var.get()) # Update main GUI var
                self.core.save_app_settings()
                messagebox.showinfo("Saved", "Paths have been updated.", parent=settings_win)
                settings_win.destroy()

            ttk.Label(settings_win, text="Arduino CLI Path:").pack(pady=(10, 0))
            cli_frame = ttk.Frame(settings_win)
            cli_frame.pack(fill=X, padx=10)
            ttk.Entry(cli_frame, textvariable=cli_path_var).pack(side=LEFT, expand=True, fill=X)
            ttk.Button(cli_frame, text="Browse...", command=select_cli_path).pack(side=RIGHT)

            ttk.Label(settings_win, text="Log CSV Path:").pack(pady=(10, 0))
            log_frame_settings = ttk.Frame(settings_win)
            log_frame_settings.pack(fill=X, padx=10)
            ttk.Entry(log_frame_settings, textvariable=log_path_var).pack(side=LEFT, expand=True, fill=X)
            ttk.Button(log_frame_settings, text="Browse...", command=select_log_path).pack(side=RIGHT)

            ttk.Label(settings_win, text="Default FQBN:").pack(pady=(10, 0))
            ttk.Entry(settings_win, textvariable=fqbn_var).pack(fill=X, padx=10)

            ttk.Button(settings_win, text="Save and Close", command=save_paths, bootstyle=SUCCESS).pack(pady=15)

        def open_log_file(self):
            """Opens the CSV log file."""
            if LOG_CSV_PATH.exists():
                self.gui_log(f"Opening log: {LOG_CSV_PATH}")
                try:
                    os.startfile(LOG_CSV_PATH) # Windows
                except AttributeError:
                    subprocess.run(['open', LOG_CSV_PATH]) # macOS
            else:
                self.gui_log("Log file does not exist.")
                messagebox.showinfo("Info", "Log file does not exist. Upload a sketch to create it.")

        def clear_log_display(self):
            self.log_area.delete('1.0', END)

        def show_about_dialog(self):
            messagebox.showinfo(
                "About Dual-Mode Arduino Uploader",
                "Dual-Mode Arduino Uploader\nVersion 2.0 (Refactored)\nAuthor: Diego Gallegos\n\n© 2024"
            )

# --- 6. RASPBERRY PI INTERFACE (LCD & BUTTONS) ---
elif RUN_MODE == "PI":
    class PiHardwareApp:
        def __init__(self):
            self.is_busy = False # To ignore buttons while uploading
            self.core = UploaderCore(
                logger_callback=self.lcd_log,
                status_callback=self.lcd_status_update
            )
            self.core.load_app_settings()

            # Configure Hardware
            self.setup_gpio()
            try:
                self.lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1,
                                   cols=16, rows=2, charmap='A00',
                                   auto_linebreaks=True)
                self.lcd.clear()
                self.lcd.write_string("Uploader Ready!")
            except Exception as e:
                print(f"Fatal Error: Could not init I2C LCD at 0x27.")
                print(f"Ensure it is connected and the address is correct.")
                print(f"Error: {e}")
                sys.exit(1)

            # Menu Logic
            self.menus = {
                "main": {
                    "title": "Main Menu",
                    "items": [
                        ("Quick Upload", self.action_quick_upload),
                        ("Select Port", self.action_menu_ports),
                        ("View Info", self.action_menu_info),
                        ("Shutdown Pi", self.action_shutdown)
                    ]
                },
                "ports": {
                    "title": "Select COM Port",
                    "items": [] # Will be filled dynamically
                },
                "info": {
                    "title": "System Info",
                    "items": [
                        (f"FQBN: {self.core.settings['fqbn'][:16]}", None),
                        (f"CLI: {Path(self.core.settings['arduino_cli_path']).name}", None),
                        ("Back", self.action_menu_main)
                    ]
                }
            }
            self.menu_stack = ["main"]
            self.current_selection = 0
            time.sleep(1)

        def setup_gpio(self):
            """Configures GPIO pins for buttons."""
            GPIO.setmode(GPIO.BCM)
            # Use internal PULL_UP resistors. Button should connect pin to GND.
            GPIO.setup(PIN_BTN_UP, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(PIN_BTN_DOWN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(PIN_BTN_OK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(PIN_BTN_BACK, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            # Add event detection (interrupts)
            GPIO.add_event_detect(PIN_BTN_UP, GPIO.FALLING, callback=self.on_button_press, bouncetime=300)
            GPIO.add_event_detect(PIN_BTN_DOWN, GPIO.FALLING, callback=self.on_button_press, bouncetime=300)
            GPIO.add_event_detect(PIN_BTN_OK, GPIO.FALLING, callback=self.on_button_press, bouncetime=300)
            GPIO.add_event_detect(PIN_BTN_BACK, GPIO.FALLING, callback=self.on_button_press, bouncetime=300)

        # --- Callbacks for the Core ---
        def lcd_log(self, msg):
            """Displays a log message on the LCD."""
            # Clean up "noisy" messages
            if "Writing" in msg or "Leaving" in msg or "Done" in msg:
                return
            
            print(f"[LOG] {msg}") # Always log to the Pi's console
            
            # Show on LCD (simplified)
            self.lcd.clear()
            if "Compiling" in msg:
                self.lcd.write_string("Compiling...")
            elif "Uploading" in msg:
                self.lcd.write_string("Uploading...")
            elif "Reading" in msg:
                self.lcd.write_string("Reading serial...")
            elif "ERROR" in msg:
                self.lcd.write_string("Error!")
                time.sleep(1)
                self.lcd.crlf()
                self.lcd.write_string(msg.split(":")[-1][:16]) # Show last 16 chars of error
            else:
                self.lcd.write_string(msg[:16]) # Show first 16 chars
            
            time.sleep(0.1) # Small pause to make it readable

        def lcd_status_update(self, status):
            """Updates the LCD based on Core status."""
            self.is_busy = (status == "UPLOADING")
            
            if status == "SUCCESS":
                self.lcd.clear()
                self.lcd.write_string("Success!")
                time.sleep(2)
                self.display_menu() # Back to menu
            elif status == "FAIL":
                self.lcd.clear()
                self.lcd.write_string("Failed!")
                self.lcd.crlf()
                self.lcd.write_string("Check csv log")
                time.sleep(3)
                self.display_menu() # Back to menu
            
        # --- Menu & Button Logic ---
        def display_menu(self):
            """Displays the current menu on the LCD."""
            if self.is_busy: return

            menu_key = self.menu_stack[-1] # Get current menu
            menu = self.menus[menu_key]
            items = menu["items"]
            
            if not items:
                self.lcd.clear()
                self.lcd.write_string(menu["title"])
                self.lcd.crlf()
                self.lcd.write_string("No items!")
                return
            
            # Ensure selection is within bounds
            self.current_selection = self.current_selection % len(items)
            
            item_text = items[self.current_selection][0]
            
            self.lcd.clear()
            # Row 1: Title or the item with a '>'
            self.lcd.write_string(f">{item_text[:15]}")
            
            # Row 2: Next item (if it exists)
            if self.current_selection + 1 < len(items):
                next_item_text = items[self.current_selection + 1][0]
                self.lcd.crlf()
                self.lcd.write_string(f" {next_item_text[:15]}")

        def on_button_press(self, pin):
            """Interrupt callback for ALL buttons."""
            if self.is_busy:
                print("Action ignored, uploader busy.")
                return

            menu_key = self.menu_stack[-1]
            items = self.menus[menu_key]["items"]

            if pin == PIN_BTN_DOWN:
                self.current_selection = (self.current_selection + 1) % len(items)
            
            elif pin == PIN_BTN_UP:
                self.current_selection = (self.current_selection - 1) % len(items)
            
            elif pin == PIN_BTN_BACK:
                if len(self.menu_stack) > 1:
                    self.menu_stack.pop() # Go to previous menu
                    self.current_selection = 0
            
            elif pin == PIN_BTN_OK:
                # Execute the selected item's action
                action = items[self.current_selection][1]
                if action:
                    action()
            
            self.display_menu() # Refresh screen

        # --- Menu Actions ---
        def action_menu_main(self):
            self.menu_stack = ["main"]
            self.current_selection = 0
        
        def action_menu_ports(self):
            self.lcd.clear()
            self.lcd.write_string("Scanning...")
            ports = get_arduino_ports()
            if not ports:
                ports = ["No ports found"]
            
            # Create menu items ("Port", callback_function)
            # The lambda function "captures" the value of 'p'
            port_items = [(p, lambda p=p: self.action_set_port(p)) for p in ports]
            port_items.append(("Back", self.action_menu_main))
            
            self.menus["ports"]["items"] = port_items
            self.menu_stack.append("ports")
            self.current_selection = 0

        def action_menu_info(self):
            self.menu_stack.append("info")
            self.current_selection = 0

        def action_set_port(self, port):
            if port != "No ports found":
                self.core.settings["port"] = port
                self.core.save_app_settings()
                self.lcd.clear()
                self.lcd.write_string(f"Port set:")
                self.lcd.crlf()
                self.lcd.write_string(port)
                time.sleep(2)
            self.menu_stack.pop() # Go back to main menu
            self.current_selection = 0
            self.display_menu()

        def action_quick_upload(self):
            """Starts the Quick Upload process."""
            self.lcd.clear()
            self.lcd.write_string("Starting...")
            
            # Start the upload in a thread to avoid blocking buttons
            threading.Thread(
                target=self.core.start_compile_and_upload,
                args=(
                    self.core.settings["default_sketch_path"],
                    self.core.settings["port"],
                    self.core.settings["baud_rate"],
                    self.core.settings["fqbn"]
                ),
                daemon=True
            ).start()
        
        def action_shutdown(self):
            self.lcd.clear()
            self.lcd.write_string("Shutting down...")
            GPIO.cleanup()
            subprocess.run(["sudo", "shutdown", "-h", "now"])
            sys.exit()

        def run(self):
            """Main loop for the Pi app (keeps script alive)."""
            self.display_menu()
            try:
                while True:
                    time.sleep(1) # Work is done in interrupts
            except KeyboardInterrupt:
                print("Closing...")
            finally:
                self.lcd.clear()
                GPIO.cleanup()


# --- 7. ENTRY POINT (THE "LAUNCHER") ---
if __name__ == "__main__":
    if not ARDUINO_CLI_PATH.exists():
        err_msg = f"Fatal Error: arduino-cli not found at:\n{ARDUINO_CLI_PATH}\n\n" \
                  f"Please ensure it is in the 'arduino-cli' folder " \
                  f"next to the executable, or configure the path in " \
                  f"'{SETTINGS_FILE}'."
        
        if RUN_MODE == "PC":
            # Use ttkbootstrap for the error if possible
            try:
                root = ttk.Window()
                root.withdraw() # Hide main window
                messagebox.showerror("Fatal Error", err_msg)
            except:
                print(err_msg) # Fallback to console
        else:
            print(err_msg) # On Pi, just print to console
        
        sys.exit(1)

    # --- Launch the correct application ---
    if RUN_MODE == "PC":
        print("Starting in PC (GUI) mode...")
        # Use a professional dark theme "superhero"
        app = WindowsGuiApp(theme="superhero") 
        app.mainloop()
    
    elif RUN_MODE == "PI":
        print("Starting in Raspberry Pi (LCD/Button) mode...")
        app = PiHardwareApp()
        app.run()