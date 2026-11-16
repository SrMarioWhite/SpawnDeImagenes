import ctypes
from ctypes import wintypes
import json
import os
import random
import tkinter as tk
from tkinter import filedialog, messagebox
import winsound
from PIL import Image, ImageTk

# Configuración de DPI en Windows para coordenadas exactas en pantalla
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
winmm = ctypes.windll.winmm

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
VK_F8 = 0x77
VK_F9 = 0x78

IGNORED_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow",
    "Progman",
    "WorkerW",
    "TaskListThumbnailWnd",
    "XamlExplorerHostIslandWindow",
    "ForegroundStaging",
    "MultitaskingViewFrame",
    "Windows.UI.Core.CoreWindow",
    "ControlCenterWindow",
    "TopLevelWindowForOverflowXamlIsland",
}

SIZE_LIMITS = {
    "sm": 220,
    "md": 320,
    "lg": 450,
    "xl": 600,
}


def get_window_info(hwnd: int) -> tuple[int, str, str, str]:
    """Devuelve (pid, exe_name, window_title, class_name) de un HWND."""
    if not hwnd:
        return 0, "", "", ""

    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    pid_val = pid.value

    length = user32.GetWindowTextLengthW(hwnd)
    title = ""
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()

    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)
    class_name = class_buf.value.strip()

    exe_name = ""
    if pid_val > 0:
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid_val)
        if h_proc:
            try:
                exe_buf = ctypes.create_unicode_buffer(512)
                size = wintypes.DWORD(512)
                if kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buf, ctypes.byref(size)):
                    exe_name = os.path.basename(exe_buf.value)
            finally:
                kernel32.CloseHandle(h_proc)

    return pid_val, exe_name, title, class_name


class OkPanaSpawnerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Meme & Image Spawner - Panel Personalizado")
        self.root.geometry("480x810")
        self.root.resizable(False, False)
        self.root.configure(bg="#18181b")

        self.own_pid = os.getpid()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.assets_dir = os.path.join(self.base_dir, "assets")
        self.config_path = os.path.join(self.base_dir, "config.json")

        self.default_image_path = os.path.join(self.assets_dir, "ok_pana.jpg")
        if not os.path.exists(self.default_image_path):
            self.default_image_path = os.path.join(self.assets_dir, "ok_pana.png")

        self.default_sound_path = os.path.join(self.assets_dir, "default_pop.wav")

        # Estado del detector
        self.is_active = True
        self.spawn_count = 0
        self.active_popups: list[tk.Toplevel] = []
        self.popup_photo_refs: dict[tk.Toplevel, ImageTk.PhotoImage] = {}

        self.last_external_key = None
        self.f8_was_down = False
        self.f9_was_down = False

        # Listas de imágenes y sonidos personalizados
        self.image_paths: list[str] = [self.default_image_path]
        self.selected_index = 0

        self.sound_paths: list[str] = (
            [self.default_sound_path] if os.path.exists(self.default_sound_path) else []
        )
        self.selected_sound_index = 0

        # Variables de configuración
        self.size_var = tk.StringVar(value="md")
        self.mode_var = tk.StringVar(value="app")
        self.autoclose_var = tk.IntVar(value=0)
        self.sound_var = tk.BooleanVar(value=True)
        self.volume_var = tk.IntVar(value=85)
        self.random_image_var = tk.BooleanVar(value=False)
        self.random_sound_var = tk.BooleanVar(value=False)
        self.max_popups_var = tk.IntVar(value=15)

        self.thumb_photo = None
        self._image_cache: dict[tuple[str, str], ImageTk.PhotoImage] = {}

        self._load_config()
        self._build_ui()
        self._refresh_image_list_ui()
        self._refresh_sound_list_ui()
        self._update_preview()

        # Inicializar app actual
        hwnd = user32.GetForegroundWindow()
        pid, exe_name, _, _ = get_window_info(hwnd)
        if pid != self.own_pid and exe_name:
            self.last_external_key = self._make_key(hwnd, pid, exe_name)

        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.root.bind("<Escape>", lambda e: self.clear_all_popups())
        self._poll_loop()

    def _load_config(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Imágenes
            saved_paths = [p for p in data.get("image_paths", []) if os.path.exists(p)]
            if self.default_image_path not in saved_paths and os.path.exists(self.default_image_path):
                saved_paths.insert(0, self.default_image_path)
            if saved_paths:
                self.image_paths = saved_paths
            self.selected_index = min(data.get("selected_index", 0), len(self.image_paths) - 1)

            # Sonidos
            saved_sounds = [p for p in data.get("sound_paths", []) if os.path.exists(p)]
            if self.default_sound_path not in saved_sounds and os.path.exists(self.default_sound_path):
                saved_sounds.insert(0, self.default_sound_path)
            if saved_sounds:
                self.sound_paths = saved_sounds
            if self.sound_paths:
                self.selected_sound_index = min(
                    data.get("selected_sound_index", 0), len(self.sound_paths) - 1
                )

            self.size_var.set(data.get("size", "md"))
            self.mode_var.set(data.get("mode", "app"))
            self.autoclose_var.set(data.get("autoclose", 0))
            self.sound_var.set(data.get("sound", True))
            self.volume_var.set(data.get("volume", 85))
            self.random_image_var.set(data.get("random_image", False))
            self.random_sound_var.set(data.get("random_sound", False))
        except Exception:
            pass

    def _save_config(self):
        try:
            data = {
                "image_paths": self.image_paths,
                "selected_index": self.selected_index,
                "sound_paths": self.sound_paths,
                "selected_sound_index": self.selected_sound_index,
                "size": self.size_var.get(),
                "mode": self.mode_var.get(),
                "autoclose": self.autoclose_var.get(),
                "sound": self.sound_var.get(),
                "volume": self.volume_var.get(),
                "random_image": self.random_image_var.get(),
                "random_sound": self.random_sound_var.get(),
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def _get_scaled_photo(self, path: str, size_key: str) -> ImageTk.PhotoImage | None:
        cache_key = (path, size_key)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        if not os.path.exists(path):
            return None

        try:
            pil_img = Image.open(path)
            pil_img = pil_img.convert("RGBA")
            max_dim = SIZE_LIMITS.get(size_key, 320)
            w, h = pil_img.size
            if size_key != "xl" or max(w, h) > max_dim:
                ratio = min(max_dim / max(w, 1), max_dim / max(h, 1))
                new_w = max(40, int(w * ratio))
                new_h = max(40, int(h * ratio))
                pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            photo = ImageTk.PhotoImage(pil_img)
            self._image_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    def play_sound_file(self, sound_path: str | None = None):
        """Reproduce archivos .mp3, .wav, .m4a, .wma con control de volumen nativo en Windows."""
        if sound_path is None:
            sound_path = self._choose_active_sound_path()

        if not sound_path or not os.path.exists(sound_path):
            try:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
            return

        vol = max(0, min(100, self.volume_var.get()))
        mci_vol = vol * 10  # Escala MCI: 0 a 1000

        try:
            winmm.mciSendStringW("close spawner_snd", None, 0, None)
            err = winmm.mciSendStringW(
                f'open "{sound_path}" type mpegvideo alias spawner_snd', None, 0, None
            )
            if err == 0:
                winmm.mciSendStringW(
                    f"setaudio spawner_snd volume to {mci_vol}", None, 0, None
                )
                winmm.mciSendStringW("play spawner_snd from 0", None, 0, None)
                return
        except Exception:
            pass

        # Respaldo directo para archivos .wav si MCI falla
        if sound_path.lower().endswith(".wav"):
            try:
                winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                return
            except Exception:
                pass

        try:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    def _build_ui(self):
        # Encabezado con miniatura en vivo
        header = tk.Frame(self.root, bg="#27272a", padx=12, pady=10)
        header.pack(fill="x", padx=12, pady=(10, 6))

        self.preview_lbl = tk.Label(
            header,
            bg="#18181b",
            width=92,
            height=86,
            bd=1,
            relief="solid",
        )
        self.preview_lbl.pack(side="left", padx=(0, 12))

        title_frame = tk.Frame(header, bg="#27272a")
        title_frame.pack(side="left", fill="both", expand=True)

        tk.Label(
            title_frame,
            text="Xd ok pana Spawner",
            font=("Segoe UI", 13, "bold"),
            fg="#fafafa",
            bg="#27272a",
            anchor="w",
        ).pack(fill="x")

        self.status_lbl = tk.Label(
            title_frame,
            text="● ACTIVO - Vigilando cambio de apps",
            font=("Segoe UI", 9, "bold"),
            fg="#4ade80",
            bg="#27272a",
            anchor="w",
        )
        self.status_lbl.pack(fill="x", pady=(1, 1))

        self.counter_lbl = tk.Label(
            title_frame,
            text="Spawneados: 0  |  En pantalla: 0",
            font=("Segoe UI", 9),
            fg="#a1a1aa",
            bg="#27272a",
            anchor="w",
        )
        self.counter_lbl.pack(fill="x")

        self.current_img_lbl = tk.Label(
            title_frame,
            text="Imagen: ok_pana.jpg",
            font=("Segoe UI", 8),
            fg="#38bdf8",
            bg="#27272a",
            anchor="w",
        )
        self.current_img_lbl.pack(fill="x", pady=(1, 0))

        self.current_snd_lbl = tk.Label(
            title_frame,
            text="Sonido: default_pop.wav",
            font=("Segoe UI", 8),
            fg="#a78bfa",
            bg="#27272a",
            anchor="w",
        )
        self.current_snd_lbl.pack(fill="x")

        # Botones principales
        btn_frame = tk.Frame(self.root, bg="#18181b")
        btn_frame.pack(fill="x", padx=12, pady=4)

        self.toggle_btn = tk.Button(
            btn_frame,
            text="⏸ Pausar (F8)",
            command=self.toggle_active,
            font=("Segoe UI", 9, "bold"),
            bg="#eab308",
            fg="#18181b",
            activebackground="#ca8a04",
            relief="flat",
            padx=8,
            pady=6,
            cursor="hand2",
        )
        self.toggle_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        test_btn = tk.Button(
            btn_frame,
            text="⚡ Spawnear (F9)",
            command=lambda: self.spawn_popup("Prueba manual"),
            font=("Segoe UI", 9, "bold"),
            bg="#3b82f6",
            fg="#ffffff",
            activebackground="#2563eb",
            relief="flat",
            padx=8,
            pady=6,
            cursor="hand2",
        )
        test_btn.pack(side="left", fill="x", expand=True, padx=4)

        clear_btn = tk.Button(
            btn_frame,
            text="🧹 Limpiar",
            command=self.clear_all_popups,
            font=("Segoe UI", 9, "bold"),
            bg="#ef4444",
            fg="#ffffff",
            activebackground="#dc2626",
            relief="flat",
            padx=8,
            pady=6,
            cursor="hand2",
        )
        clear_btn.pack(side="left", fill="x", expand=True, padx=(4, 0))

        # Selector de Imágenes Personalizadas
        img_frame = tk.LabelFrame(
            self.root,
            text=" 🖼️ Selector de Imágenes Personalizadas ",
            font=("Segoe UI", 9, "bold"),
            fg="#d4d4d8",
            bg="#18181b",
            bd=1,
            padx=10,
            pady=6,
        )
        img_frame.pack(fill="x", padx=12, pady=4)

        list_container = tk.Frame(img_frame, bg="#18181b")
        list_container.pack(fill="x")

        scrollbar = tk.Scrollbar(list_container, orient="vertical")
        self.img_listbox = tk.Listbox(
            list_container,
            height=3,
            bg="#27272a",
            fg="#fafafa",
            selectbackground="#3b82f6",
            selectforeground="#ffffff",
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=1,
            highlightbackground="#3f3f46",
            exportselection=False,
            yscrollcommand=scrollbar.set,
        )
        scrollbar.config(command=self.img_listbox.yview)
        self.img_listbox.pack(side="left", fill="x", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.img_listbox.bind("<<ListboxSelect>>", self._on_select_image)

        img_btns = tk.Frame(img_frame, bg="#18181b")
        img_btns.pack(fill="x", pady=(5, 2))

        tk.Button(
            img_btns,
            text="📂 Añadir Imagen(es)...",
            command=self.add_custom_images,
            font=("Segoe UI", 8, "bold"),
            bg="#10b981",
            fg="#ffffff",
            activebackground="#059669",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            img_btns,
            text="🗑 Quitar",
            command=self.remove_selected_image,
            font=("Segoe UI", 8),
            bg="#3f3f46",
            fg="#fafafa",
            activebackground="#52525b",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            img_btns,
            text="↺ Original",
            command=self.reset_default_image,
            font=("Segoe UI", 8),
            bg="#3f3f46",
            fg="#fafafa",
            activebackground="#52525b",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left")

        tk.Checkbutton(
            img_frame,
            text="🎲 Imagen aleatoria de mi lista al spawnear",
            variable=self.random_image_var,
            command=self._save_config,
            bg="#18181b",
            fg="#e4e4e7",
            selectcolor="#27272a",
            activebackground="#18181b",
            activeforeground="#fafafa",
            font=("Segoe UI", 8),
        ).pack(anchor="w")

        # Selector de Sonidos Personalizados
        snd_frame = tk.LabelFrame(
            self.root,
            text=" 🔊 Selector de Sonido Personalizado ",
            font=("Segoe UI", 9, "bold"),
            fg="#d4d4d8",
            bg="#18181b",
            bd=1,
            padx=10,
            pady=6,
        )
        snd_frame.pack(fill="x", padx=12, pady=4)

        top_snd_row = tk.Frame(snd_frame, bg="#18181b")
        top_snd_row.pack(fill="x", pady=(0, 4))

        tk.Checkbutton(
            top_snd_row,
            text="Activar sonido al spawnear",
            variable=self.sound_var,
            command=self._save_config,
            bg="#18181b",
            fg="#4ade80",
            selectcolor="#27272a",
            activebackground="#18181b",
            activeforeground="#4ade80",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        vol_box = tk.Frame(top_snd_row, bg="#18181b")
        vol_box.pack(side="right")
        tk.Label(vol_box, text="Vol:", fg="#a1a1aa", bg="#18181b", font=("Segoe UI", 8)).pack(
            side="left", padx=(0, 4)
        )
        vol_slider = tk.Scale(
            vol_box,
            from_=0,
            to=100,
            orient="horizontal",
            variable=self.volume_var,
            command=lambda _v: self._save_config(),
            bg="#18181b",
            fg="#fafafa",
            highlightthickness=0,
            troughcolor="#27272a",
            activebackground="#8b5cf6",
            length=110,
            sliderlength=14,
            font=("Segoe UI", 7),
        )
        vol_slider.pack(side="left")

        snd_list_container = tk.Frame(snd_frame, bg="#18181b")
        snd_list_container.pack(fill="x")

        snd_scroll = tk.Scrollbar(snd_list_container, orient="vertical")
        self.snd_listbox = tk.Listbox(
            snd_list_container,
            height=3,
            bg="#27272a",
            fg="#fafafa",
            selectbackground="#8b5cf6",
            selectforeground="#ffffff",
            font=("Segoe UI", 9),
            bd=0,
            highlightthickness=1,
            highlightbackground="#3f3f46",
            exportselection=False,
            yscrollcommand=snd_scroll.set,
        )
        snd_scroll.config(command=self.snd_listbox.yview)
        self.snd_listbox.pack(side="left", fill="x", expand=True)
        snd_scroll.pack(side="right", fill="y")
        self.snd_listbox.bind("<<ListboxSelect>>", self._on_select_sound)

        snd_btns = tk.Frame(snd_frame, bg="#18181b")
        snd_btns.pack(fill="x", pady=(5, 2))

        tk.Button(
            snd_btns,
            text="🎵 Añadir Sonido(s)...",
            command=self.add_custom_sounds,
            font=("Segoe UI", 8, "bold"),
            bg="#8b5cf6",
            fg="#ffffff",
            activebackground="#7c3aed",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            snd_btns,
            text="▶ Probar",
            command=lambda: self.play_sound_file(self._get_selected_sound_path()),
            font=("Segoe UI", 8, "bold"),
            bg="#3b82f6",
            fg="#ffffff",
            activebackground="#2563eb",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            snd_btns,
            text="🗑 Quitar",
            command=self.remove_selected_sound,
            font=("Segoe UI", 8),
            bg="#3f3f46",
            fg="#fafafa",
            activebackground="#52525b",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            snd_btns,
            text="↺ Pop Original",
            command=self.reset_default_sound,
            font=("Segoe UI", 8),
            bg="#3f3f46",
            fg="#fafafa",
            activebackground="#52525b",
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side="left")

        tk.Checkbutton(
            snd_frame,
            text="🎲 Sonido aleatorio de mi lista al spawnear",
            variable=self.random_sound_var,
            command=self._save_config,
            bg="#18181b",
            fg="#e4e4e7",
            selectcolor="#27272a",
            activebackground="#18181b",
            activeforeground="#fafafa",
            font=("Segoe UI", 8),
        ).pack(anchor="w")

        # Ajustes de Comportamiento
        settings = tk.LabelFrame(
            self.root,
            text=" ⚙️ Configuración de Comportamiento ",
            font=("Segoe UI", 9, "bold"),
            fg="#d4d4d8",
            bg="#18181b",
            bd=1,
            padx=10,
            pady=5,
        )
        settings.pack(fill="x", padx=12, pady=4)

        tk.Label(settings, text="Detectar:", fg="#e4e4e7", bg="#18181b", font=("Segoe UI", 9)).grid(
            row=0, column=0, sticky="w", pady=1
        )
        mode_box = tk.Frame(settings, bg="#18181b")
        mode_box.grid(row=0, column=1, sticky="w", pady=1)
        tk.Radiobutton(
            mode_box,
            text="Cambio de App (.exe)",
            variable=self.mode_var,
            value="app",
            command=self._save_config,
            bg="#18181b",
            fg="#fafafa",
            selectcolor="#27272a",
            activebackground="#18181b",
            activeforeground="#fafafa",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=(0, 8))
        tk.Radiobutton(
            mode_box,
            text="Cualquier ventana",
            variable=self.mode_var,
            value="window",
            command=self._save_config,
            bg="#18181b",
            fg="#fafafa",
            selectcolor="#27272a",
            activebackground="#18181b",
            activeforeground="#fafafa",
            font=("Segoe UI", 8),
        ).pack(side="left")

        tk.Label(settings, text="Tamaño:", fg="#e4e4e7", bg="#18181b", font=("Segoe UI", 9)).grid(
            row=1, column=0, sticky="w", pady=1
        )
        size_box = tk.Frame(settings, bg="#18181b")
        size_box.grid(row=1, column=1, sticky="w", pady=1)
        for label_txt, val in [("Pequeño", "sm"), ("Mediano", "md"), ("Grande", "lg"), ("Extra", "xl")]:
            tk.Radiobutton(
                size_box,
                text=label_txt,
                variable=self.size_var,
                value=val,
                command=self._save_config,
                bg="#18181b",
                fg="#fafafa",
                selectcolor="#27272a",
                activebackground="#18181b",
                activeforeground="#fafafa",
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(0, 4))

        tk.Label(settings, text="Cierre:", fg="#e4e4e7", bg="#18181b", font=("Segoe UI", 9)).grid(
            row=2, column=0, sticky="w", pady=1
        )
        close_box = tk.Frame(settings, bg="#18181b")
        close_box.grid(row=2, column=1, sticky="w", pady=1)
        for label_txt, val in [("Al hacer clic", 0), ("3 seg", 3), ("5 seg", 5)]:
            tk.Radiobutton(
                close_box,
                text=label_txt,
                variable=self.autoclose_var,
                value=val,
                command=self._save_config,
                bg="#18181b",
                fg="#fafafa",
                selectcolor="#27272a",
                activebackground="#18181b",
                activeforeground="#fafafa",
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(0, 8))

        # Registro de última app detectada
        log_frame = tk.Frame(self.root, bg="#27272a", padx=10, pady=5)
        log_frame.pack(fill="x", padx=12, pady=(4, 2))

        tk.Label(
            log_frame,
            text="Última aplicación detectada:",
            font=("Segoe UI", 8, "bold"),
            fg="#a1a1aa",
            bg="#27272a",
            anchor="w",
        ).pack(fill="x")

        self.last_app_lbl = tk.Label(
            log_frame,
            text="Esperando que abras o cambies a otra ventana...",
            font=("Consolas", 9),
            fg="#38bdf8",
            bg="#27272a",
            anchor="w",
        )
        self.last_app_lbl.pack(fill="x", pady=(1, 0))

        footer = tk.Label(
            self.root,
            text="💡 Clic en la imagen para cerrarla  |  F8: Pausar y limpiar todo  |  F9: Spawnear prueba",
            font=("Segoe UI", 8),
            fg="#71717a",
            bg="#18181b",
        )
        footer.pack(pady=(2, 4))

    def _refresh_image_list_ui(self):
        self.img_listbox.delete(0, tk.END)
        for path in self.image_paths:
            name = os.path.basename(path)
            if os.path.abspath(path) == os.path.abspath(self.default_image_path):
                display = f"⭐ {name} (Por defecto)"
            else:
                display = f"🖼️ {name}"
            self.img_listbox.insert(tk.END, display)

        if 0 <= self.selected_index < len(self.image_paths):
            self.img_listbox.selection_set(self.selected_index)
            self.img_listbox.see(self.selected_index)

    def _refresh_sound_list_ui(self):
        self.snd_listbox.delete(0, tk.END)
        for path in self.sound_paths:
            name = os.path.basename(path)
            if os.path.abspath(path) == os.path.abspath(self.default_sound_path):
                display = f"🔔 {name} (Pop por defecto)"
            else:
                display = f"🎵 {name}"
            self.snd_listbox.insert(tk.END, display)

        if 0 <= self.selected_sound_index < len(self.sound_paths):
            self.snd_listbox.selection_set(self.selected_sound_index)
            self.snd_listbox.see(self.selected_sound_index)
        self._update_sound_label()

    def _update_sound_label(self):
        path = self._get_selected_sound_path()
        if path:
            self.current_snd_lbl.config(text=f"Sonido: {os.path.basename(path)}")
        else:
            self.current_snd_lbl.config(text="Sonido: Beep del sistema")

    def _on_select_image(self, _event=None):
        sel = self.img_listbox.curselection()
        if not sel:
            return
        self.selected_index = sel[0]
        self._update_preview()
        self._save_config()

    def _on_select_sound(self, _event=None):
        sel = self.snd_listbox.curselection()
        if not sel:
            return
        self.selected_sound_index = sel[0]
        self._update_sound_label()
        self._save_config()

    def _update_preview(self):
        if not self.image_paths:
            return
        idx = min(max(0, self.selected_index), len(self.image_paths) - 1)
        path = self.image_paths[idx]
        name = os.path.basename(path)
        self.current_img_lbl.config(text=f"Imagen: {name}")

        try:
            pil_img = Image.open(path).convert("RGBA")
            pil_img.thumbnail((88, 82), Image.Resampling.LANCZOS)
            self.thumb_photo = ImageTk.PhotoImage(pil_img)
            self.preview_lbl.config(image=self.thumb_photo, text="")
        except Exception:
            self.preview_lbl.config(image="", text="Sin vista\nprevia", fg="#a1a1aa")

    def add_custom_images(self):
        files = filedialog.askopenfilenames(
            title="Seleccionar imagen(es) para spawnear",
            filetypes=[
                ("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not files:
            return

        for f in files:
            norm_f = os.path.normpath(f)
            if norm_f not in [os.path.normpath(p) for p in self.image_paths]:
                self.image_paths.append(norm_f)

        self.selected_index = len(self.image_paths) - 1
        self._refresh_image_list_ui()
        self._update_preview()
        self._save_config()

    def remove_selected_image(self):
        if len(self.image_paths) <= 1:
            messagebox.showinfo("Aviso", "Debe quedar al menos una imagen en la lista.")
            return
        sel = self.img_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.image_paths.pop(idx)
        self.selected_index = max(0, min(idx, len(self.image_paths) - 1))
        self._refresh_image_list_ui()
        self._update_preview()
        self._save_config()

    def reset_default_image(self):
        if os.path.exists(self.default_image_path):
            if os.path.normpath(self.default_image_path) not in [
                os.path.normpath(p) for p in self.image_paths
            ]:
                self.image_paths.insert(0, self.default_image_path)
            self.selected_index = 0
            self.random_image_var.set(False)
            self._refresh_image_list_ui()
            self._update_preview()
            self._save_config()

    def add_custom_sounds(self):
        files = filedialog.askopenfilenames(
            title="Seleccionar archivo(s) de sonido para el spawn",
            filetypes=[
                ("Archivos de audio", "*.mp3 *.wav *.m4a *.wma *.aac"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not files:
            return

        for f in files:
            norm_f = os.path.normpath(f)
            if norm_f not in [os.path.normpath(p) for p in self.sound_paths]:
                self.sound_paths.append(norm_f)

        self.selected_sound_index = len(self.sound_paths) - 1
        self.sound_var.set(True)
        self._refresh_sound_list_ui()
        self._save_config()
        # Reproducir vista previa del nuevo sonido cargado
        self.play_sound_file(self._get_selected_sound_path())

    def remove_selected_sound(self):
        if len(self.sound_paths) <= 1:
            messagebox.showinfo("Aviso", "Debe quedar al menos un sonido en la lista.")
            return
        sel = self.snd_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.sound_paths.pop(idx)
        self.selected_sound_index = max(0, min(idx, len(self.sound_paths) - 1))
        self._refresh_sound_list_ui()
        self._save_config()

    def reset_default_sound(self):
        if os.path.exists(self.default_sound_path):
            if os.path.normpath(self.default_sound_path) not in [
                os.path.normpath(p) for p in self.sound_paths
            ]:
                self.sound_paths.insert(0, self.default_sound_path)
            self.selected_sound_index = 0
            self.random_sound_var.set(False)
            self._refresh_sound_list_ui()
            self._save_config()
            self.play_sound_file(self.default_sound_path)

    def _get_selected_sound_path(self) -> str | None:
        if not self.sound_paths:
            return None
        idx = min(max(0, self.selected_sound_index), len(self.sound_paths) - 1)
        return self.sound_paths[idx]

    def _choose_active_sound_path(self) -> str | None:
        valid_sounds = [p for p in self.sound_paths if os.path.exists(p)]
        if not valid_sounds:
            return None
        if self.random_sound_var.get() and len(valid_sounds) > 1:
            return random.choice(valid_sounds)
        selected = self._get_selected_sound_path()
        return selected if (selected and os.path.exists(selected)) else valid_sounds[0]

    def _make_key(self, hwnd: int, pid: int, exe_name: str):
        if self.mode_var.get() == "window":
            return f"hwnd:{hwnd}"
        return f"app:{exe_name.lower()}:{pid}"

    def toggle_active(self):
        self.is_active = not self.is_active
        if self.is_active:
            hwnd = user32.GetForegroundWindow()
            pid, exe_name, _, _ = get_window_info(hwnd)
            if pid != self.own_pid and exe_name:
                self.last_external_key = self._make_key(hwnd, pid, exe_name)
            self.status_lbl.config(text="● ACTIVO - Vigilando cambio de apps", fg="#4ade80")
            self.toggle_btn.config(text="⏸ Pausar (F8)", bg="#eab308", fg="#18181b")
        else:
            self.status_lbl.config(text="⏸ PAUSADO - No spawneará imágenes", fg="#f87171")
            self.toggle_btn.config(text="▶ Reanudar (F8)", bg="#22c55e", fg="#18181b")

    def clear_all_popups(self):
        for popup in list(self.active_popups):
            self.popup_photo_refs.pop(popup, None)
            try:
                popup.destroy()
            except Exception:
                pass
        self.active_popups.clear()
        self._update_counters()

    def _update_counters(self):
        self.active_popups = [p for p in self.active_popups if p.winfo_exists()]
        self.counter_lbl.config(
            text=f"Spawneados: {self.spawn_count}  |  En pantalla: {len(self.active_popups)}"
        )

    def _choose_active_image_path(self) -> str:
        valid_paths = [p for p in self.image_paths if os.path.exists(p)]
        if not valid_paths:
            return self.default_image_path
        if self.random_image_var.get() and len(valid_paths) > 1:
            return random.choice(valid_paths)
        idx = min(max(0, self.selected_index), len(self.image_paths) - 1)
        chosen = self.image_paths[idx]
        return chosen if os.path.exists(chosen) else valid_paths[0]

    def spawn_popup(self, _app_label: str = ""):
        self.active_popups = [p for p in self.active_popups if p.winfo_exists()]
        if len(self.active_popups) >= self.max_popups_var.get():
            oldest = self.active_popups.pop(0)
            self.popup_photo_refs.pop(oldest, None)
            try:
                oldest.destroy()
            except Exception:
                pass

        img_path = self._choose_active_image_path()
        size_key = self.size_var.get()
        photo = self._get_scaled_photo(img_path, size_key)
        if not photo:
            return

        w = photo.width()
        h = photo.height()

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        max_x = max(20, sw - w - 20)
        max_y = max(20, sh - h - 70)
        x = random.randint(20, max_x)
        y = random.randint(20, max_y)

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#18181b")
        popup.geometry(f"{w + 4}x{h + 4}+{x}+{y}")

        self.popup_photo_refs[popup] = photo

        lbl = tk.Label(
            popup,
            image=photo,
            bg="#fafafa",
            bd=2,
            relief="solid",
            cursor="hand2",
        )
        lbl.pack(fill="both", expand=True)

        def close_this(_event=None):
            if popup in self.active_popups:
                self.active_popups.remove(popup)
            self.popup_photo_refs.pop(popup, None)
            try:
                popup.destroy()
            except Exception:
                pass
            self._update_counters()

        lbl.bind("<Button-1>", close_this)
        lbl.bind("<Button-3>", close_this)
        popup.bind("<Escape>", close_this)

        try:
            popup.update_idletasks()
            hwnd_popup = user32.GetParent(popup.winfo_id()) or popup.winfo_id()
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = user32.GetWindowLongW(hwnd_popup, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd_popup, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass

        self.active_popups.append(popup)
        self.spawn_count += 1
        self._update_counters()

        if self.sound_var.get():
            self.play_sound_file()

        autoclose_sec = self.autoclose_var.get()
        if autoclose_sec > 0:
            popup.after(autoclose_sec * 1000, close_this)

    def _check_global_hotkeys(self):
        f8_state = user32.GetAsyncKeyState(VK_F8)
        is_f8_down = (f8_state & 0x8000) != 0
        if is_f8_down and not self.f8_was_down:
            self.clear_all_popups()
            self.toggle_active()
        self.f8_was_down = is_f8_down

        f9_state = user32.GetAsyncKeyState(VK_F9)
        is_f9_down = (f9_state & 0x8000) != 0
        if is_f9_down and not self.f9_was_down:
            self.spawn_popup("Atajo F9")
        self.f9_was_down = is_f9_down

    def _poll_loop(self):
        try:
            self._check_global_hotkeys()

            if self.is_active:
                hwnd = user32.GetForegroundWindow()
                pid, exe_name, title, class_name = get_window_info(hwnd)

                if (
                    hwnd
                    and pid != 0
                    and pid != self.own_pid
                    and class_name not in IGNORED_CLASSES
                    and exe_name.lower()
                    not in (
                        "searchhost.exe",
                        "shellexperiencehost.exe",
                        "startmenuexperiencehost.exe",
                        "lockapp.exe",
                    )
                    and (title or exe_name)
                ):
                    current_key = self._make_key(hwnd, pid, exe_name)
                    if self.last_external_key is None:
                        self.last_external_key = current_key
                    elif current_key != self.last_external_key:
                        self.last_external_key = current_key
                        display_title = title[:32] + "..." if len(title) > 32 else title
                        app_info = f"{exe_name} ({display_title})" if display_title else exe_name
                        self.last_app_lbl.config(text=app_info)
                        self.spawn_popup(app_info)
        except Exception:
            pass

        self.root.after(150, self._poll_loop)

    def quit_app(self):
        try:
            winmm.mciSendStringW("close spawner_snd", None, 0, None)
        except Exception:
            pass
        self._save_config()
        self.clear_all_popups()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = OkPanaSpawnerApp(root)
    root.mainloop()
