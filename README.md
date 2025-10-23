# Flahser-app-for-Arduino-boards

---

### 1. Resumen General

Este script crea una aplicación de escritorio con **Tkinter** que sirve como una interfaz gráfica (GUI) amigable para la herramienta de línea de comandos `arduino-cli.exe`.

El objetivo principal es permitir a un usuario compilar y cargar *sketches* (programas) de Arduino a una placa (como un Nano o Uno) sin tener que usar el IDE de Arduino. Además, es capaz de leer un valor de vuelta desde el puerto serial después de la carga y guarda un registro de cada operación en un archivo **CSV**.

---

### 2. Importaciones (`import ...`)

Estas son las "cajas de herramientas" que tu programa utiliza:

* **`csv`, `json`, `os`, `sys`, `time`**: Herramientas estándar de Python.
    * `csv`: Para escribir tu archivo de log `upload_log.csv`.
    * `json`: Para guardar y cargar tus configuraciones (como la ruta del sketch) en un archivo `.json`.
    * `os`: Para interactuar con el sistema operativo, específicamente para abrir el archivo de log (`os.startfile`).
    * `sys`: Para la función `get_base_path`, que ayuda a encontrar archivos cuando la app está compilada con PyInstaller.
    * `time`: Para poner marcas de tiempo (`strftime`) en el log y para pausas (`sleep`).
* **`subprocess`**: **¡Clave!** Esta es la librería que te permite ejecutar `arduino-cli.exe` desde Python y capturar su salida.
* **`threading`**: **¡Crítico!** Se usa para ejecutar el proceso de compilación y carga en un "hilo" separado. Esto evita que la interfaz gráfica se "congele" o se ponga blanca mientras el `arduino-cli` está trabajando.
* **`tkinter`**: Es la librería completa para construir la interfaz gráfica (ventanas, botones, etiquetas, etc.).
* **`pathlib` (Path)**: Una forma moderna y fácil de manejar rutas de archivos y carpetas, sin importar si estás en Windows, Mac o Linux.
* **`serial` y `serial.tools.list_ports`**:
    * `list_ports`: Para escanear la computadora en busca de puertos COM.
    * `serial`: Para conectarse al puerto COM después de la carga y leer el valor (`_read_from_serial`).

---

### 3. Configuración y Gestión de Ajustes (Settings) 

Esta sección es muy inteligente y clave para que tu app sea "portable" (funcione en otras PCs).

* **`get_base_path()`**: Una función vital para PyInstaller. Comprueba si el script se está ejecutando como un `.exe` "congelado" (`sys.frozen`).
    * Si es `.exe`, la base es una carpeta temporal (`sys._MEIPASS`).
    * Si es un script `.py`, la base es la carpeta del script.
* **Lógica de Carga de Rutas (Líneas 47-67)**: Este es el "cerebro" de tu configuración.
    1.  Define el archivo de ajustes (`SETTINGS_FILE`) en la carpeta del usuario.
    2.  **Carga los ajustes (`load_settings()`) PRIMERO.** Intenta leer el `.json` para ver si el usuario ya había configurado rutas personalizadas.
    3.  Define las **rutas por defecto**:
        * `default_cli_path`: Busca `arduino-cli.exe` *dentro* de la carpeta de la aplicación (usando `BASE_PATH`). Esto es lo que permite que tu `.exe` compilado incluya `arduino-cli`.
        * `default_log_path`: En la carpeta del usuario.
    4.  **Establece las rutas FINALES (`ARDUINO_CLI_PATH`, `LOG_CSV_PATH`)**: Usa la ruta del archivo de *settings* si existe; si no, usa la ruta *por defecto*.

* **`load_settings()` y `save_settings()`**: Simplemente leen y escriben en el archivo `.json` para guardar las preferencias del usuario.

---

### 4. Funciones de Backend (Las "Obreras") 

Estas son funciones que hacen trabajo pero no son parte de la GUI.

* **`get_arduino_ports()`**: Es más que un simple escáner. Filtra los puertos COM buscando "VIDs" (Vendor IDs) conocidos de Arduino (como `0x2341`) o descripciones como "Arduino" o "CH340". Por eso es tan preciso.
* **`log_to_csv()`**: Escribe una nueva fila en tu archivo de log. Importante: comprueba si el archivo existe. Si no, escribe primero la fila de encabezados ("Timestamp", "Port", etc.).

---

### 5. La Clase Principal: `DualModeUploaderApp` 

Esta clase es tu aplicación completa.

#### `__init__(self, master)` (El Constructor)
Este es el "arquitecto" que construye toda la ventana cuando se inicia la app.
1.  **Carga Ajustes:** Carga las preferencias (rutas, baud rate, FQBN) en variables de Tkinter (`tk.StringVar`). Estas variables actúan como un "puente": si cambias la variable, el widget (ej. `Entry`) se actualiza, y viceversa.
2.  **Crea Frames (`LabelFrame`)**: Divide la app en 3 secciones: "Quick Upload", "Custom Upload" y "Upload Log".
3.  **Crea Widgets (Botones, Etiquetas, etc.)**: Coloca cada elemento en su lugar usando `.grid()` (para los frames de upload) y `.pack()` (para el log).
4.  **Inicia Procesos Clave**:
    * `self.refresh_ports()`: Llena la lista de puertos COM la primera vez.
    * `self.periodic_port_check()`: **¡Función clave!** Inicia un bucle que cada 2 segundos revisa si se ha conectado o desconectado un Arduino (lo explicamos más abajo).
    * `master.protocol("WM_DELETE_WINDOW", self.on_closing)`: Le dice a Tkinter que, si el usuario hace clic en la 'X' para cerrar, debe llamar a tu función `on_closing` primero.

#### `on_closing(self)`
La "función de limpieza". Antes de cerrar, toma los valores actuales de la GUI (puerto, baud rate, etc.) y los guarda en el archivo de *settings* usando `save_settings()`.

#### Funciones de Log y Diálogos
* **`log(self, msg)`**: Añade texto al `ScrolledText` (el área de log) con una marca de tiempo y se asegura de que siempre se vea la última línea (`self.log_area.see(tk.END)`).
* **`clear_log_display(self)`**: Borra todo el texto del área de log.
* **`show_about_dialog(self)`**: Muestra la ventana de "Acerca de" que creaste.
* **`open_log_file(self)`**: Usa `os.startfile` para abrir el archivo `.csv` con el programa predeterminado (Excel, etc.).

#### Gestión de Puertos COM 🔌
* **`refresh_ports(self)`**: El trabajo pesado de actualizar el menú desplegable. Borra la lista vieja, obtiene la nueva lista de `get_arduino_ports()`, y vuelve a llenar el menú. Inteligentemente, intenta mantener seleccionado el puerto que estaba antes, si es que sigue existiendo.
* **`periodic_port_check(self)`**: El "guardia". Cada 2 segundos, compara la lista de puertos *del sistema* con la lista de puertos *en el menú*. Si no coinciden (alguien conectó o desconectó algo), llama a `refresh_ports()` para actualizar la GUI.

#### El Proceso de Carga (El Corazón de la App) 
Este es el flujo más complejo, dividido en varias funciones:

1.  **`start_upload_thread(self, ...)`** (El "Gerente")
    * Se llama al hacer clic en "Upload".
    * Limpia el log de la GUI.
    * Valida que el archivo `.ino` exista.
    * **Lo más importante:** Crea un **`threading.Thread`** (hilo) y le asigna la tarea `self.run_upload_and_read`. Esto libera a la GUI para que siga respondiendo.

2.  **`run_upload_and_read(self, ...)`** (El "Trabajador")
    * Esta función se ejecuta en el *hilo secundario*.
    * **Valida** que el puerto y el baud rate estén configurados.
    * **Deshabilita** los botones de "Upload" para evitar clics duplicados.
    * Ejecuta la secuencia: **Compilar -> Subir -> Leer**.
    * **Compilar:** Llama a `_compile_sketch()`.
    * **Subir:** *Si* la compilación fue exitosa, llama a `_upload_sketch()`.
    * **Leer:** *Si* la subida fue exitosa, llama a `_read_from_serial()`.
    * **Registrar:** Llama a `log_to_csv()` con todos los resultados.
    * **Habilita** los botones de "Upload" nuevamente.

3.  **`_compile_sketch(self, ...)`**
    * Construye el comando `arduino-cli compile ...` usando el FQBN (tipo de placa) de los *settings*.
    * Ejecuta el comando usando `_run_command_realtime()`.
    * Devuelve `True` o `False` dependiendo del éxito.

4.  **`_upload_sketch(self, ...)`**
    * Construye el comando `arduino-cli upload ...`.
    * Lo ejecuta. Si falla, **tiene un truco**: lo intenta de nuevo con el FQBN del "viejo bootloader" (`cpu=atmega328old`). Esta es una característica muy robusta que soluciona el 90% de los problemas de carga con Nanos clonados.

5.  **`_read_from_serial(self, ...)`**
    * Usa `serial.Serial()` para abrir el puerto.
    * `time.sleep(2)`: Espera 2 segundos cruciales para que el Arduino se reinicie después de la carga.
    * `sp.readline()`: Lee una sola línea de datos que el Arduino envíe.
    * Devuelve los datos o un mensaje de error.

6.  **`_run_command_realtime(self, ...)`** (La "Magia" del Log)
    * Esta es la función que te permite ver la salida de `arduino-cli` en *tiempo real*.
    * Usa `subprocess.Popen` (que no bloquea el hilo).
    * Entra en un bucle `while True` que lee la salida del proceso *línea por línea* (`process.stdout.readline()`).
    * Cada línea que lee, la inserta *directamente* en el `log_area` de la GUI y fuerza a la GUI a actualizarse (`self.master.update_idletasks()`).
    * Cuando el proceso termina (`process.poll()` deja de ser `None`), el bucle se rompe.
    * Devuelve `True` si el código de salida fue 0 (éxito).

#### `open_settings_window(self)`
* Crea una *nueva ventana* (`tk.Toplevel`) que se muestra encima de la principal.
* Tiene sus propios widgets para seleccionar las rutas (`arduino-cli.exe`, `upload_log.csv`) y editar el FQBN.
* La función interna `save_paths` es la que actualiza las variables globales y guarda los *settings* cuando se presiona "Save".

---

### 6. Punto de Entrada (`if __name__ == "__main__":`)

Esta es la sección final que se ejecuta cuando corres tu archivo `.py`.

1.  Hace una comprobación de seguridad: `if not ARDUINO_CLI_PATH.exists()`. Si no puede encontrar `arduino-cli.exe` (basado en la lógica de *settings*), muestra un error fatal y se cierra, porque la app no puede funcionar.
2.  Si todo está bien, crea la ventana raíz (`root = tk.Tk()`).
3.  Crea una instancia de tu aplicación (`app = DualModeUploaderApp(root)`).
4.  Inicia la aplicación (`root.mainloop()`), que pone la ventana en pantalla y espera a que el usuario interactúe.
