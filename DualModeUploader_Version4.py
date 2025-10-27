import csv
import json
import subprocess
import sys
import threading
import time
import os
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

# Define the base path
#BASE_PATH = get_base_path()

#DEFAULT_FQBN = "arduino:avr:nano"
#SETTINGS_FILE = Path.home() / "dual_uploader_settings.json"
# Update ARDUINO_CLI_PATH to be relative to the base path
#ARDUINO_CLI_PATH = BASE_PATH / "arduino-cli" / "arduino-cli.exe"
#LOG_CSV_PATH = Path.home() / "upload_log.csv"

# ... (después de BASE_PATH = get_base_path())

DEFAULT_FQBN = "arduino:avr:nano"
SETTINGS_FILE = Path.home() / "dual_uploader_settings.json"

# Cargar settings primero
settings = load_settings()

# Definir BASE_PATH antes de usarlo
BASE_PATH = get_base_path()

# Definir rutas por defecto
default_cli_path = BASE_PATH / "arduino-cli" / "arduino-cli.exe"
default_log_path = Path.home() / "upload_log.csv"

# Usar rutas de settings si existen, si no, usar las de por defecto
ARDUINO_CLI_PATH = Path(settings.get("arduino_cli_path", default_cli_path))
LOG_CSV_PATH = Path(settings.get("log_csv_path", default_log_path))

# --- Settings Management ---
def load_settings():
    """Loads last-used settings from a JSON file."""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r") as f: return json.load(f)
        except json.JSONDecodeError: return {}
/    return {}

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
            writer.writerow([" Timestamp ", " Port ", " Sketch ", " UploadStatus ", " ValueRead ", " Details "])
        writer.writerow(data_row)

# --- Main GUI Application ---
class DualModeUploaderApp:
    def __init__(self, master):
        self.master = master
        master.title("Dual-Mode Arduino Uploader")
        master.geometry("632x650")

        # --- Load Settings ---
        self.settings = load_settings()
        self.default_sketch_path_var = tk.StringVar(value=self.settings.get("default_sketch_path", "Default sketch not set"))
        self.custom_sketch_path_var = tk.StringVar(value=self.settings.get("custom_sketch_path", ""))
        self.baud_rate_var = tk.StringVar(value=self.settings.get("baud_rate", "9600"))
        self.port_var = tk.StringVar(value=self.settings.get("port", ""))
        self.fqbn_var = tk.StringVar(value=self.settings.get("fqbn", "arduino:avr:nano"))

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
        self.port_menu.grid(row=3, column=0, sticky="ew", padx=(0, 10))

        # --- Quick Upload Widgets ---
        tk.Label(quick_frame, text="Default Sketch Path:").grid(row=0, column=0, columnspan=4, sticky="w")
        tk.Label(quick_frame, textvariable=self.default_sketch_path_var, fg="blue", wraplength=500, justify=tk.LEFT).grid(row=1, column=0, columnspan=3, sticky="w")
        tk.Button(quick_frame, text="Set/Change Default Sketch", command=self.set_default_sketch).grid(row=1, column=3, padx=10, sticky="e")

        # Fila 2: Etiquetas de Puerto y Baud Rate
        tk.Label(quick_frame, text="COM Port:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        tk.Label(quick_frame, text="Baud Rate:").grid(row=2, column=1, sticky="w", padx=10, pady=(10, 0))

        # Fila 3: Menú de Puerto, Campo de Baud Rate y Botón de Refrescar
        self.port_menu = tk.OptionMenu(quick_frame, self.port_var, "No ports")
        self.port_menu.grid(row=3, column=0, sticky="ew", padx=(0, 10))

        # Fila 4: Botón principal de Upload
        self.quick_upload_button = tk.Button(quick_frame, text="Upload Color Sensor Sketch", command=lambda: self.start_upload_thread(use_default=True), bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), height=2)
        self.quick_upload_button.grid(row=4, column=0, columnspan=4, pady=15, sticky="ew")

        #tk.Label(quick_frame, text="COM Port:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        #self.port_menu = tk.OptionMenu(quick_frame, self.port_var, "No ports")
        #self.port_menu.grid(row=3, column=0, sticky="ew")

        tk.Label(quick_frame, text="Baud Rate:").grid(row=3, column=1, sticky="w", padx=10, pady=(10, 0))
        tk.Entry(quick_frame, textvariable=self.baud_rate_var).grid(row=4, column=1, sticky="ew", padx=10)
        tk.Button(quick_frame, text="Refresh Ports", command=self.refresh_ports).grid(row=4, column=2, sticky="w")
        self.port_menu.grid(row=4, column=0, sticky="ew")  # Mover esto a la fila 4

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
        # Frame para botones del log
        log_button_frame = tk.Frame(log_frame)
        log_button_frame.pack(fill=tk.X)
        tk.Button(log_button_frame, text="About", command=self.show_about_dialog).pack(side=tk.LEFT, pady=(0, 5), padx=(5,0))

        tk.Label(log_button_frame, text="").pack(side=tk.LEFT, expand=True) # Spacer
        tk.Button(log_button_frame, text="Config Paths...", command=self.open_settings_window).pack(side=tk.RIGHT, pady=(0, 5))

        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # Frame para botones del log
        #log_button_frame = tk.Frame(log_frame)
        #log_button_frame.pack(fill=tk.X)

        # Botón para abrir el CSV
        tk.Label(log_button_frame, text="").pack(side=tk.LEFT, expand=True) # Spacer
        tk.Button(log_button_frame, text="Ver Log (.csv)", command=self.open_log_file).pack(side=tk.LEFT, pady=(0, 5))
        
        # Botón que ya tenías
        #tk.Button(log_button_frame, text="Config Paths...", command=self.open_settings_window).pack(side=tk.RIGHT, pady=(0, 5))
        #self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10)
        #self.log_area.pack(fill=tk.BOTH, expand=True)

        #self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10)
        #self.log_area.pack(fill=tk.BOTH, expand=True)

        #self.refresh_ports()
        #master.protocol("WM_DELETE_WINDOW", self.on_closing)

        tk.Button(log_button_frame, text="Limpiar Log", command=self.clear_log_display).pack(side=tk.LEFT, pady=(0, 5))        

# ... (al final de __init__)
        self.refresh_ports()
        self.periodic_port_check() # <--- AÑADE ESTA LÍNEA
        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        """Saves settings and closes the application."""
        self.settings["default_sketch_path"] = self.default_sketch_path_var.get()
        self.settings["custom_sketch_path"] = self.custom_sketch_path_var.get()
        self.settings["baud_rate"] = self.baud_rate_var.get()
        self.settings["port"] = self.port_var.get()
        self.settings["fqbn"] = self.fqbn_var.get()
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
        """La lógica principal para compilar, subir y leer un valor."""
        port = self.port_var.get()
        baud_rate = self.baud_rate_var.get()
        sketch_name = Path(sketch_path).name
        
        # --- 0. Validación ---
        if "No ports" in port or not baud_rate.isdigit():
            self.log("ERROR: El puerto y el Baud Rate deben estar configurados.")
            messagebox.showerror("Error", "El puerto y el Baud Rate deben estar configurados correctamente.")
            return

        # Deshabilitar botones
        self.quick_upload_button.config(state=tk.DISABLED)
        self.custom_upload_button.config(state=tk.DISABLED)

        # --- 1. Compilar ---
        compile_ok, compile_details = self._compile_sketch(sketch_path)
        
        upload_ok = False
        upload_details = "N/A"
        read_value = "N/A"

        # --- 2. Subir (solo si la compilación fue exitosa) ---
        if compile_ok:
            upload_ok, upload_details = self._upload_sketch(sketch_path, port)
        else:
            upload_details = "Carga omitida debido a fallo de compilación."
            
        # --- 3. Leer Valor (solo si la subida fue exitosa) ---
        if upload_ok:
            read_value = self._read_from_serial(port, baud_rate)
        
        # --- 4. Registrar en CSV ---
        log_to_csv([
            time.strftime('%Y-%m-%d %H:%M:%S'), port, sketch_name,
            "SUCCESS" if upload_ok else "FAIL", read_value,
            f"{compile_details} | {upload_details}".replace("\r", " ").replace("\n", " ")
        ])

        # --- 4. Registrar en CSV ---
        #current_date = time.strftime('%Y-%m-%d')
        #current_time = time.strftime('%H:%M:%S')
        #log_to_csv([
        #    current_date, current_time, port, sketch_name,
        #    "SUCCESS" if upload_ok else "FAIL", read_value,
        #    f"{compile_details} | {upload_details}".replace("\r", " ").replace("\n", " ")
        #])
        
        self.log(f"Proceso finalizado. Resultados registrados en {LOG_CSV_PATH.name}")
        
        # Habilitar botones
        self.quick_upload_button.config(state=tk.NORMAL)
        self.custom_upload_button.config(state=tk.NORMAL)

    def _compile_sketch(self, sketch_path):
        """Compiles the sketch and returns status and details."""
        sketch_name = Path(sketch_path).name
        fqbn = self.fqbn_var.get()
        compile_cmd = [str(ARDUINO_CLI_PATH), "compile", "--fqbn", fqbn, sketch_path]

        success = self._run_command_realtime(compile_cmd, log_prefix=f"Compiling {sketch_name}")

        if success:
            self.log("Compile successful.")
            return True, "Compile OK."
        else:
            self.log("ERROR: Compile failed! Check logs above for details.")
            return False, "Compile FAIL."

    def _upload_sketch(self, sketch_path, port):
        """Uploads the sketch, trying both new and old bootloaders."""
        fqbn = self.fqbn_var.get()
        upload_cmd = [str(ARDUINO_CLI_PATH), "upload", "-p", port, "--fqbn", fqbn, sketch_path]

        # Try with standard bootloader
        success = self._run_command_realtime(upload_cmd, log_prefix=f"Uploading to {port}")

        if success:
            self.log("Upload successful!")
            return True, "Upload OK."

        # If it failed, try with the old bootloader
        self.log("Upload failed. Trying with old bootloader...")
        fqbn_old = f"{fqbn}:cpu=atmega328old"
        upload_cmd_old = [str(ARDUINO_CLI_PATH), "upload", "-p", port, "--fqbn", fqbn_old, sketch_path]

        success_old = self._run_command_realtime(upload_cmd_old, log_prefix="Uploading with old bootloader")

        if success_old:
            self.log("Upload successful with old bootloader!")
            return True, "Upload OK (old bootloader)."
        else:
            self.log("ERROR: Upload failed on all attempts! Check logs above.")
            return False, "Upload FAIL."

    def _read_from_serial(self, port, baud_rate):
        """Reads a single line from the specified serial port."""
        self.log(f"Attempting to read from {port} at {baud_rate} baud...")
        try:
            with serial.Serial(port, int(baud_rate), timeout=2.0) as sp:
                time.sleep(2)  # Wait for the board to reset
                sp.reset_input_buffer()
                line = sp.readline().decode('utf-8').strip()
                if line:
                    self.log(f"Data received: {line}")
                    return line
                else:
                    self.log("Warning: No data received from serial port.")
                    return "No data"
        except Exception as e:
            self.log(f"ERROR: Could not read from serial port: {e}")
            return "Read ERROR"

    def periodic_port_check(self):
        """Periodically checks for COM port changes and refreshes the list if necessary."""
        try:
            # Get the list of ports currently displayed in the OptionMenu
            menu = self.port_menu["menu"]
            ports_in_menu = []
            if menu.index("end") is not None:
                ports_in_menu = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]

            # Get the actual list of ports from the system
            current_ports = get_arduino_ports()

            # If the sorted lists are different, it means a device was added or removed
            if sorted(ports_in_menu) != sorted(current_ports):
                self.log("Cambio de puerto detectado! Actualizando lista...")
                self.refresh_ports()

            # Schedule this function to run again after 2 seconds (2000 ms)
            self.master.after(2000, self.periodic_port_check)
        except Exception as e:
            # This will prevent a crash if the window is closed while a check is pending
            print(f"Error during periodic port check: {e}")

    def _run_command_realtime(self, command, log_prefix=""):
        """Executes a command and logs its output to the GUI in real-time."""
        self.log(f"{log_prefix}...")
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)

        # Read the output line by line as it is generated
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                self.log_area.insert(tk.END, output)  # Insert directly to show raw output
                self.log_area.see(tk.END)  # Auto-scroll
                self.master.update_idletasks()  # Keep the GUI responsive

        return process.poll() == 0  # Return True if exit code is 0 (success), else False

    def open_settings_window(self):
        # Create a new top-level window
        settings_win = tk.Toplevel(self.master)
        settings_win.title("Configure Paths")
        settings_win.geometry("550x250")

        # --- Variables ---
        cli_path_var = tk.StringVar(value=str(ARDUINO_CLI_PATH))
        log_path_var = tk.StringVar(value=str(LOG_CSV_PATH))
        fqbn_var = tk.StringVar(value=self.fqbn_var.get()) # <-- Añadir esta

        # --- Functions ---
        def select_cli_path():
            path = filedialog.askopenfilename(title="Select arduino-cli.exe")
            if path:
                cli_path_var.set(path)

        def select_log_path():
            path = filedialog.asksaveasfilename(title="Select Log CSV File", defaultextension=".csv",
                                                filetypes=[("CSV files", "*.csv")])
            if path:
                log_path_var.set(path)

        def save_paths():
            global ARDUINO_CLI_PATH, LOG_CSV_PATH
            ARDUINO_CLI_PATH = Path(cli_path_var.get())
            LOG_CSV_PATH = Path(log_path_var.get())
            # Save these paths to the main settings file
            self.settings["arduino_cli_path"] = str(ARDUINO_CLI_PATH)
            self.settings["log_csv_path"] = str(LOG_CSV_PATH)
            self.fqbn_var.set(fqbn_var.get()) 
            self.settings["fqbn"] = self.fqbn_var.get() 
            messagebox.showinfo("Saved", "Paths have been updated.", parent=settings_win)
            settings_win.destroy()
            save_settings(self.settings)

        # --- Widgets ---
        tk.Label(settings_win, text="Arduino CLI Path:").pack(pady=(10, 0))
        cli_frame = tk.Frame(settings_win)
        cli_frame.pack(fill=tk.X, padx=10)
        tk.Entry(cli_frame, textvariable=cli_path_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(cli_frame, text="Browse...", command=select_cli_path).pack(side=tk.RIGHT)

        tk.Label(settings_win, text="Log CSV Path:").pack(pady=(10, 0))
        log_frame_settings = tk.Frame(settings_win)
        log_frame_settings.pack(fill=tk.X, padx=10)
        tk.Entry(log_frame_settings, textvariable=log_path_var).pack(side=tk.LEFT, expand=True, fill=tk.X)
        tk.Button(log_frame_settings, text="Browse...", command=select_log_path).pack(side=tk.RIGHT)

        tk.Label(settings_win, text="Default FQBN (Tipo de Placa):").pack(pady=(10, 0))
        tk.Label(settings_win, text="(ej: arduino:avr:nano, arduino:avr:uno)").pack(pady=(0, 0))
        tk.Entry(settings_win, textvariable=fqbn_var).pack(fill=tk.X, padx=10)

        tk.Button(settings_win, text="Save and Close", command=save_paths).pack(pady=15)
        
    def open_log_file(self):
        """Abre el archivo de log CSV con la aplicación por defecto."""
        if LOG_CSV_PATH.exists():
            self.log(f"Abriendo archivo de log: {LOG_CSV_PATH}")
            try:
                os.startfile(LOG_CSV_PATH) # Para Windows
            except AttributeError:
                subprocess.run(['open', LOG_CSV_PATH]) # Para macOS
        else:
            self.log("El archivo de log aún no existe.")
            messagebox.showinfo("Info", "El archivo de log no existe. Sube un sketch para crearlo.")

    def clear_log_display(self):
        """Borra el texto del área de log en la GUI."""
        self.log_area.delete('1.0', tk.END)

    def show_about_dialog(self):
        """Displays an About dialog with version and author information."""
        messagebox.showinfo(
            "About Dual-Mode Arduino Uploader",
            "Dual-Mode Arduino Uploader\nVersion 1.4.1\nAuthor: Diego Gallegos\nLocation: CME Department\n\nUpload sketches to Arduino Nano/Uno boards easily.\n© 2024"
        )

if __name__ == "__main__":
    if not ARDUINO_CLI_PATH.exists():
        messagebox.showerror("Fatal Error", f"Arduino CLI not found at:\n{ARDUINO_CLI_PATH}\nPlease check the path in the script.")
    else:
        root = tk.Tk()
        app = DualModeUploaderApp(root)
        root.mainloop()
