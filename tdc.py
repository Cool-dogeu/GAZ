#!/usr/bin/env python3
# RS232 sniffer GUI dla ALGE GAZ
# Podsłuch tylko do odczytu. 2400 8N1. ASCII + podgląd hex.

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import serial
from serial.tools import list_ports
from datetime import datetime

BAUD = 2400
BYTESIZE = serial.EIGHTBITS
PARITY = serial.PARITY_NONE
STOPBITS = serial.STOPBITS_ONE

class SnifferApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GAZ sniffer")
        self.ser = None
        self.read_job = None
        self.log_file = None

        # Pasek górny
        top = ttk.Frame(root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Port:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=36, state="readonly")
        self.port_combo.pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Odśwież", command=self.refresh_ports).pack(side=tk.LEFT)
        self.btn_connect = ttk.Button(top, text="Połącz", command=self.connect)
        self.btn_connect.pack(side=tk.LEFT, padx=(6,0))
        self.btn_disconnect = ttk.Button(top, text="Rozłącz", command=self.disconnect, state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=(6,0))

        ttk.Label(root, padding=(8,2), text=f"Parametry: {BAUD} 8N1 tylko odczyt").pack(anchor="w")

        # Opcje
        opts = ttk.Frame(root, padding=(8,0))
        opts.pack(fill=tk.X)
        self.show_hex = tk.BooleanVar(value=True)
        self.show_ascii = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="HEX", variable=self.show_hex).pack(side=tk.LEFT)
        ttk.Checkbutton(opts, text="ASCII", variable=self.show_ascii).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(opts, text="Zapis do pliku...", command=self.choose_log_file).pack(side=tk.LEFT, padx=(12,0))
        ttk.Button(opts, text="Wyczyść log", command=self.clear_log).pack(side=tk.LEFT, padx=(6,0))

        # Log wyjścia
        self.text = tk.Text(root, height=20, state=tk.DISABLED)
        self.text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Status
        self.status_var = tk.StringVar(value="Nie połączono")
        ttk.Label(root, textvariable=self.status_var, anchor="w", padding=6, relief=tk.SUNKEN).pack(fill=tk.X)

        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def refresh_ports(self):
        ports = list_ports.comports()
        items = [f"{p.device} {p.description}" for p in ports]
        self.port_combo["values"] = items
        if items:
            self.port_var.set(items[0])
        self.log_line("Odświeżono listę portów")

    def _selected_device(self):
        val = self.port_var.get()
        return val.split(" ")[0] if val else None

    def connect(self):
        if self.ser and self.ser.is_open:
            self.log_line("Już połączono")
            return
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning("Brak portu", "Wybierz port")
            return
        try:
            # Tylko odczyt. DTR i RTS ustawiamy w dół
            self.ser = serial.Serial(dev, baudrate=BAUD, bytesize=BYTESIZE,
                                     parity=PARITY, stopbits=STOPBITS, timeout=0.1)
            try:
                self.ser.setDTR(False)
                self.ser.setRTS(False)
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Błąd połączenia", str(e))
            self.status_var.set("Błąd połączenia")
            self.log_line(f"Błąd: {e}")
            return
        self.status_var.set(f"Połączono z {dev}")
        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.NORMAL)
        self.read_loop()

    def disconnect(self):
        if self.read_job is not None:
            try:
                self.root.after_cancel(self.read_job)
            except Exception:
                pass
            self.read_job = None
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        self.status_var.set("Nie połączono")
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.log_line("Rozłączono")

    def choose_log_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".log", filetypes=[("Logi", "*.log"), ("Wszystkie", "*.*")])
        if not path:
            return
        try:
            self.log_file = open(path, 'a', encoding='utf-8')
            self.log_line(f"Logowanie do pliku: {path}")
        except Exception as e:
            messagebox.showerror("Błąd pliku", str(e))
            self.log_file = None

    def clear_log(self):
        self.text.configure(state=tk.NORMAL)
        self.text.delete('1.0', tk.END)
        self.text.configure(state=tk.DISABLED)

    def log_line(self, line: str):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        full = f"{ts}  {line}"
        self.text.configure(state=tk.NORMAL)
        self.text.insert(tk.END, full + "\n")
        self.text.see(tk.END)
        self.text.configure(state=tk.DISABLED)
        if self.log_file:
            try:
                self.log_file.write(full + "\n")
                self.log_file.flush()
            except Exception:
                pass

    def read_loop(self):
        if not self.ser or not self.ser.is_open:
            return
        try:
            data = self.ser.read(256)
        except Exception as e:
            self.log_line(f"Błąd odczytu: {e}")
            self.disconnect()
            return
        if data:
            parts = []
            if self.show_hex.get():
                parts.append('HEX: ' + ' '.join(f'{b:02X}' for b in data))
            if self.show_ascii.get():
                try:
                    s = data.decode('ascii', errors='replace')
                except Exception:
                    s = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
                # pokaż CR i LF
                s_vis = s.replace('\r', '<CR>').replace('\n', '<LF>')
                parts.append(f'ASCII: "{s_vis}"')
            self.log_line('  '.join(parts))
        self.read_job = self.root.after(50, self.read_loop)

    def on_close(self):
        try:
            if self.read_job is not None:
                self.root.after_cancel(self.read_job)
            if self.ser and self.ser.is_open:
                self.ser.close()
            if self.log_file:
                self.log_file.close()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except Exception:
        pass
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    SnifferApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

