import csv
import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, filedialog, scrolledtext

import serial
import serial.tools.list_ports


# --- Configuration ---
#DEFAULT_FQBN = "arduino:avr:nano"
#SETTINGS_FILE = Path.home() / "dual_uploader_settings.json"
#ARDUINO_CLI_PATH = Path.home() / "arduino-cli" / "arduino-cli.exe"
#LOG_CSV_PATH = Path.home() / "upload_log.csv"

# --- Configuration ---

def get_base_path():
    """ Get the base path, works for development and for PyInstaller """
    if getattr(sys, 'frozen', False):
        # If the application is run as a bundle, the base path is the temp folder where PyInstaller extracts everything
        return Path(sys._MEIPASS)
    else:
        # If run as a script, the base path is the script's directory
        return Path(__file__).parent

# Define the base path
BASE_PATH = get_base_path()

DEFAULT_FQBN = "arduino:avr:nano"
SETTINGS_FILE = Path.home() / "dual_uploader_settings.json"
# Update ARDUINO_CLI_PATH to be relative to the base path
ARDUINO_CLI_PATH = Path.home() / "arduino-cli" / "arduino-cli.exe"
LOG_CSV_PATH = Path.home() / "upload_log.csv"

# ... the rest of your script continues here

# --- Settings Management ---
def load_settings():
    """Loads last-used settings from a JSON file."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except json.JSONDecodeError: return {}
    return {}

def save_settings(settings):
    """Saves settings to the JSON file."""
    with open(SETTINGS_FILE, "w") as f: json.dump(settings, f, indent=4)

# --- Backend Functions ---
def get_arduino_ports():
    """Detects and returns a list of potential Arduino ports."""
    ports_found = []
    known_vids = [0x2341, 0x1A86, 0x0403, 0x10C4]
    for port in serial.tools.list_ports.comports():
        if port.vid in known_vids or "Arduino" in port.description or "CH340" in port.description:
            ports_found.append(port.device)
    return sorted(ports_found)

def log_to_csv(data_row):
    """Appends a row to the CSV log file."""
    file_exists = LOG_CSV_PATH.exists()
    with open(LOG_CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Port", "Sketch", "UploadStatus", "ValueRead", "Details"])
        writer.writerow(data_row)

# --- Main GUI Application ---
class DualModeUploaderApp:
    def __init__(self, master):
        self.master = master
        master.title("Dual-Mode Arduino Uploader")
        master.geometry("750x650")
        
        # --- Load Settings ---
        self.settings = load_settings()
        self.default_sketch_path_var = tk.StringVar(value=self.settings.get("default_sketch_path", "Default sketch not set"))
        self.custom_sketch_path_var = tk.StringVar(value=self.settings.get("custom_sketch_path", ""))
        self.baud_rate_var = tk.StringVar(value=self.settings.get("baud_rate", "9600"))
        self.port_var = tk.StringVar(value=self.settings.get("port", ""))

        # --- GUI Frames ---
        quick_frame = tk.LabelFrame(master, text="1. Quick Upload (for Color Sensor)", padx=10, pady=10, font=("Arial", 10, "bold"))
        quick_frame.pack(fill=tk.X, padx=10, pady=10)
        
        custom_frame = tk.LabelFrame(master, text="2. Custom Upload (for any other sketch)", padx=10, pady=10)
        custom_frame.pack(fill=tk.X, padx=10, pady=5)
        
        log_frame = tk.LabelFrame(master, text="Upload Log", padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(5, 10))

        # --- Quick Upload Widgets ---
        tk.Label(quick_frame, text="Default Sketch Path:").grid(row=0, column=0, sticky="w")
        tk.Label(quick_frame, textvariable=self.default_sketch_path_var, fg="blue", wraplength=500, justify=tk.LEFT).grid(row=1, column=0, columnspan=3, sticky="w")
        
        tk.Button(quick_frame, text="Set/Change Default Sketch", command=self.set_default_sketch).grid(row=1, column=3, padx=10, sticky="e")

        tk.Label(quick_frame, text="COM Port:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.port_menu = tk.OptionMenu(quick_frame, self.port_var, "No ports")
        self.port_menu.grid(row=3, column=0, sticky="ew")
        
        tk.Label(quick_frame, text="Baud Rate:").grid(row=2, column=1, sticky="w", padx=10, pady=(10, 0))
        tk.Entry(quick_frame, textvariable=self.baud_rate_var).grid(row=3, column=1, sticky="ew", padx=10)
        tk.Button(quick_frame, text="Refresh Ports", command=self.refresh_ports).grid(row=3, column=2, sticky="w")
        
        self.quick_upload_button = tk.Button(quick_frame, text="Upload Color Sensor Sketch", command=lambda: self.start_upload_thread(use_default=True), bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), height=2)
        self.quick_upload_button.grid(row=4, column=0, columnspan=4, pady=15, sticky="ew")

        # --- Custom Upload Widgets ---
        tk.Label(custom_frame, text="Sketch to Upload:").grid(row=0, column=0, sticky="w")
        tk.Entry(custom_frame, textvariable=self.custom_sketch_path_var, width=80).grid(row=1, column=0, sticky="ew")
        tk.Button(custom_frame, text="Browse...", command=self.select_custom_sketch).grid(row=1, column=1, padx=5)
        self.custom_upload_button = tk.Button(custom_frame, text="Upload Selected Sketch", command=lambda: self.start_upload_thread(use_default=False))
        self.custom_upload_button.grid(row=2, column=0, columnspan=2, pady=10, sticky="ew")
        
        # --- Log Frame ---
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        self.refresh_ports()
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """Saves settings and closes the application."""
        self.settings["default_sketch_path"] = self.default_sketch_path_var.get()
        self.settings["custom_sketch_path"] = self.custom_sketch_path_var.get()
        self.settings["baud_rate"] = self.baud_rate_var.get()
        self.settings["port"] = self.port_var.get()
        save_settings(self.settings)
        self.master.destroy()

    def log(self, msg):
        self.log_area.insert(tk.END, f"{time.strftime('%H:%M:%S')} - {msg}\n")
        self.log_area.see(tk.END)

    def set_default_sketch(self):
        path = filedialog.askopenfilename(title="Select your default COLOR-SENSOR.ino sketch", filetypes=[("Arduino Files", "*.ino")])
        if path:
            self.default_sketch_path_var.set(path)
            self.log(f"New default sketch set: {path}")

    def select_custom_sketch(self):
        path = filedialog.askopenfilename(title="Select a custom Arduino Sketch", filetypes=[("Arduino Files", "*.ino")])
        if path:
            self.custom_sketch_path_var.set(path)
            self.log(f"Custom sketch selected: {path}")

    def refresh_ports(self):
        self.log("Scanning for COM ports...")
        ports = get_arduino_ports()
        # ... (rest of the function is the same)
        menu = self.port_menu["menu"]
        menu.delete(0, tk.END)
        last_port = self.port_var.get()
        if ports:
            for port in ports:
                menu.add_command(label=port, command=lambda p=port: self.port_var.set(p))
            self.port_var.set(last_port if last_port in ports else ports[0])
            self.log(f"Found ports: {', '.join(ports)}")
        else:
            self.port_var.set("No ports")
            self.log("No Arduino-compatible ports detected.")

    def start_upload_thread(self, use_default=False):
        """Starts the upload process in a background thread."""
        self.log_area.delete('1.0', tk.END)
        sketch_path = self.default_sketch_path_var.get() if use_default else self.custom_sketch_path_var.get()
        
        if not Path(sketch_path).is_file():
            messagebox.showerror("Error", f"Sketch file not found or not set:\n{sketch_path}")
            return
            
        threading.Thread(target=self.run_upload_and_read, args=(sketch_path,), daemon=True).start()
        
def run_upload_and_read(self, sketch_path):
        """The main logic for compiling, uploading, and reading a value."""
        port = self.port_var.get()
        baud_rate = self.baud_rate_var.get()

        if "No ports" in port or not baud_rate.isdigit():
            messagebox.showerror("Error", "Port and Baud Rate must be set correctly.")
            return

        self.quick_upload_button.config(state=tk.DISABLED)
        self.custom_upload_button.config(state=tk.DISABLED)
        
        # --- 1. Compile ---
        self.log(f"Starting compile for {Path(sketch_path).name} with FQBN '{DEFAULT_FQBN}'...")
        compile_cmd = [str(ARDUINO_CLI_PATH), "compile", "--fqbn", DEFAULT_FQBN, sketch_path]
        upload_details = ""
        try:
            # ADDED creationflags TO HIDE THE WINDOW
            subprocess.run(compile_cmd, capture_output=True, text=True, check=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
            self.log("Compile successful.")
            upload_details += f"Compile OK.\n"
        except subprocess.CalledProcessError as e:
            error_msg = f"ERROR: Compile failed!\n{e.stderr or e.stdout}"
            self.log(error_msg)
            log_to_csv([time.strftime('%Y-%m-%d %H:%M:%S'), port, Path(sketch_path).name, "FAIL", "N/A", error_msg])
            self.quick_upload_button.config(state=tk.NORMAL)
            self.custom_upload_button.config(state=tk.NORMAL)
            return

        # --- 2. Upload ---
        self.log(f"Starting upload to {port}...")
        upload_cmd = [str(ARDUINO_CLI_PATH), "upload", "-p", port, "--fqbn", DEFAULT_FQBN, sketch_path]
        upload_ok = False
        try:
            # ADDED creationflags TO HIDE THE WINDOW
            subprocess.run(upload_cmd, capture_output=True, text=True, check=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
            self.log("Upload successful!")
            upload_details += f"Upload OK.\n"
            upload_ok = True
        except subprocess.CalledProcessError:
            self.log("Upload failed. Trying with old bootloader...")
            upload_cmd_old = [str(ARDUINO_CLI_PATH), "upload", "-p", port, "--fqbn", f"{DEFAULT_FQBN}:cpu=atmega328old", sketch_path]
            try:
                # ADDED creationflags TO HIDE THE WINDOW
                subprocess.run(upload_cmd_old, capture_output=True, text=True, check=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
                self.log("Upload successful with old bootloader!")
                upload_details += f"Upload OK (old bootloader).\n"
                upload_ok = True
            except subprocess.CalledProcessError as e2:
                error_msg = f"ERROR: Upload failed on all attempts!\n{e2.stderr or e2.stdout}"
                self.log(error_msg)
                upload_details += error_msg

        # --- 3. Read Value ---
        read_value = "N/A"
        if upload_ok:
            self.log(f"Attempting to read from {port} at {baud_rate} baud...")
            try:
                with serial.Serial(port, int(baud_rate), timeout=2.0) as sp:
                    time.sleep(2)
                    sp.reset_input_buffer()
                    line = sp.readline().decode('utf-8').strip()
                    if line:
                        read_value = line
                        self.log(f"Data received: {read_value}")
                    else:
                        self.log("Warning: No data received from serial port.")
            except Exception as e:
                self.log(f"ERROR: Could not read from serial port: {e}")
                read_value = "ERROR"
        
        # --- 4. Log to CSV ---
        log_to_csv([
            time.strftime('%Y-%m-%d %H:%M:%S'), port, Path(sketch_path).name,
            "SUCCESS" if upload_ok else "FAIL", read_value,
            upload_details.replace("\r", " ").replace("\n", " ")
        ])
        self.log(f"Process finished. Results logged to {LOG_CSV_PATH.name}")
        self.quick_upload_button.config(state=tk.NORMAL)
        self.custom_upload_button.config(state=tk.NORMAL)

if __name__ == "__main__":
    if not ARDUINO_CLI_PATH.exists():
        messagebox.showerror("Fatal Error", f"Arduino CLI not found at:\n{ARDUINO_CLI_PATH}\nPlease check the path in the script.")
    else:
        root = tk.Tk()
        app = DualModeUploaderApp(root)
        root.mainloop()
