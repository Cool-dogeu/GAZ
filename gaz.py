#!/usr/bin/env python3
# gaz2.py — sender for ALGE GAZ (HEAD format)
# Port: 2400 8N1 ASCII, terminated with CR
# Start number:  "A" + xxx + 8x space + CR
# Time HEAD: "  0   .       " + (S.DD | SS.DD | H SS.DD) + " 00" + CR

import tkinter as tk
from tkinter import ttk, messagebox
import serial
from serial.tools import list_ports
import re
import time

BAUD = 2400
BYTESIZE = serial.EIGHTBITS
PARITY = serial.PARITY_NONE
STOPBITS = serial.STOPBITS_ONE

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("GAZ")
        self.ser = None

        # Top bar
        top = ttk.Frame(root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Port:").pack(side=tk.LEFT)
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=36, state="readonly")
        self.port_combo.pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side=tk.LEFT)
        self.btn_connect = ttk.Button(top, text="Connect", command=self.connect)
        self.btn_connect.pack(side=tk.LEFT, padx=(6,0))
        self.btn_disconnect = ttk.Button(top, text="Disconnect", command=self.disconnect, state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT)

        ttk.Label(root, padding=(8,2), text=f"Parameters: {BAUD} 8N1 ASCII + CR").pack(anchor="w")

        # Start number
        frm_num = ttk.LabelFrame(root, text="Start number Axxx", padding=8)
        frm_num.pack(fill=tk.X, padx=8, pady=(4,0))
        ttk.Label(frm_num, text="xxx:").grid(row=0, column=0, sticky="w")
        self.num_var = tk.StringVar(value="1")
        ttk.Entry(frm_num, textvariable=self.num_var, width=8).grid(row=0, column=1, sticky="w")
        ttk.Button(frm_num, text="Send number", command=self.send_number).grid(row=0, column=2, padx=(8,0))

        # Time — one field SSS.DD
        frm_time = ttk.LabelFrame(root, text="Time SSS.DD (HEAD)", padding=8)
        frm_time.pack(fill=tk.X, padx=8, pady=(6,0))
        ttk.Label(frm_time, text="Example: 6.23 or 123.07:").grid(row=0, column=0, sticky="w")
        self.time_var = tk.StringVar(value="6.23")
        ttk.Entry(frm_time, textvariable=self.time_var, width=16).grid(row=0, column=1, sticky="w")
        ttk.Button(frm_time, text="Send time", command=self.send_time).grid(row=0, column=2, padx=(8,0))

        # Preview/edit time frame
        frm_prev = ttk.LabelFrame(root, text="Preview/edit time frame (CR will be added automatically)", padding=8)
        frm_prev.pack(fill=tk.X, padx=8, pady=(6,0))
        self.time_preview_var = tk.StringVar()
        ttk.Entry(frm_prev, textvariable=self.time_preview_var, width=64).grid(row=0, column=0, sticky="we")
        frm_prev.columnconfigure(0, weight=1)
        ttk.Button(frm_prev, text="Build from SSS.DD", command=self.build_time_to_preview).grid(row=0, column=1, padx=(8,0))
        ttk.Button(frm_prev, text="Send from field", command=self.send_time_preview).grid(row=0, column=2, padx=(8,0))

        # Log
        ttk.Label(root, padding=(8,2), text="Log:").pack(anchor="w")
        self.log = tk.Text(root, height=12, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

        # Status
        self.status_var = tk.StringVar(value="Not connected")
        ttk.Label(root, textvariable=self.status_var, anchor="w", padding=6, relief=tk.SUNKEN).pack(fill=tk.X)

        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # Ports
    def refresh_ports(self):
        ports = list_ports.comports()
        items = [f"{p.device} {p.description}" for p in ports]
        self.port_combo["values"] = items
        if items:
            self.port_var.set(items[0])
        self.log_info("Port list refreshed")

    def _selected_device(self):
        val = self.port_var.get()
        return val.split(" ")[0] if val else None

    # Connection
    def connect(self):
        if self.ser and self.ser.is_open:
            self.log_info("Already connected")
            return
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning("No port", "Select port")
            return
        try:
            self.ser = serial.Serial(dev, baudrate=BAUD, bytesize=BYTESIZE, parity=PARITY, stopbits=STOPBITS, timeout=1)
        except Exception as e:
            messagebox.showerror("Connection error", str(e))
            self.status_var.set("Connection error")
            self.log_err(f"Error: {e}")
            return
        self.status_var.set(f"Connected to {dev}")
        self.btn_connect.config(state=tk.DISABLED)
        self.btn_disconnect.config(state=tk.NORMAL)
        self.log_info(f"Connected to {dev}")

    def disconnect(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        self.status_var.set("Not connected")
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.log_info("Disconnected")

    # Frames
    @staticmethod
    def build_number(n: int) -> str:
        # Axxx + 8 spaces (as in sniffed data)
        return f"A{n:03d}" + " " * 8

    @staticmethod
    def build_time_head(sec: int, cen: int) -> str:
        head_lt100 = "  0   .       "  # 14 chars (7 spaces after dot)
        head_ge100 = "  0   .     "    # 12 chars (5 spaces after dot)
        if sec >= 100:
            H = str(sec // 100)
            SS = f"{sec % 100:02d}"
            body = f"{H} {SS}.{cen:02d} 00"
            return head_ge100 + body
        else:
            sec_str = f" {sec}" if sec < 10 else str(sec)
            body = f"{sec_str}.{cen:02d} 00"
            return head_lt100 + body

    # Sending
    def send_payload(self, payload: str) -> bool:
        if not self.ser or not self.ser.is_open:
            messagebox.showwarning("Not connected", "Connect to port first")
            return False
        try:
            self.ser.write((payload + "\r").encode("ascii"))
            try:
                self.ser.flush()
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Send error", str(e))
            self.log_err(f"Send error: {e}")
            return False
        self.log_info(f"Sent: {repr(payload)} + CR")
        return True

    # GUI actions
    def send_number(self):
        raw = ''.join(ch for ch in self.num_var.get() if ch.isdigit()) or "0"
        n = int(raw)
        if n < 0 or n > 999:
            messagebox.showwarning("Bad number", "0..999 allowed")
            return False
        ok = self.send_payload(self.build_number(n))
        if not ok:
            return False
        # send two empty frames as in sniffed data
        time.sleep(0.08)
        self.send_payload(" " * 11)
        time.sleep(0.08)
        self.send_payload(" " * 15)
        return True

    def send_time(self):
        txt = self.time_var.get().strip()
        if '.' in txt:
            left, right = txt.split('.', 1)
        else:
            left, right = txt, None
        if not left.isdigit() or len(left) == 0 or len(left) > 3:
            messagebox.showwarning("Bad format", "Use SSS.DD, e.g. 6.23, 33 or 123.4")
            return False
        sec = int(left)
        if right is None or right == "":
            cen = 0
        else:
            if not right.isdigit() or len(right) > 2:
                messagebox.showwarning("Bad format", "Fraction part max 2 digits")
                return False
            if len(right) == 1:
                cen = int(right) * 10
            else:
                cen = int(right)
        if not (0 <= sec <= 999):
            messagebox.showwarning("Bad seconds", "0..999")
            return False
        if not (0 <= cen <= 99):
            messagebox.showwarning("Bad hundredths", "0..99")
            return False
        return self.send_payload(self.build_time_head(sec, cen))

    # Preview actions
    def build_time_to_preview(self):
        txt = self.time_var.get().strip()
        if '.' in txt:
            left, right = txt.split('.', 1)
        else:
            left, right = txt, None
        if not left.isdigit() or len(left) == 0 or len(left) > 3:
            messagebox.showwarning("Bad format", "Use SSS.DD, e.g. 6.23, 33 or 123.4")
            return False
        sec = int(left)
        if right is None or right == "":
            cen = 0
        else:
            if not right.isdigit() or len(right) > 2:
                messagebox.showwarning("Bad format", "Fraction part max 2 digits")
                return False
            if len(right) == 1:
                cen = int(right) * 10
            else:
                cen = int(right)
        if not (0 <= sec <= 999 and 0 <= cen <= 99):
            messagebox.showwarning("Out of range", "Seconds 0..999, hundredths 0..99")
            return False
        frame = self.build_time_head(sec, cen)
        self.time_preview_var.set(frame)
        self.log_info(f"Built to field: {repr(frame)}")
        return True

    def send_time_preview(self):
        s = self.time_preview_var.get() or ""
        if s == "":
            return False
        t = s.replace("␣", " ")
        t = t.replace("<CR>", "")
        t = t.replace("\\r", "")
        t = t.replace("\\n", "")
        t = t.rstrip("\r\n")
        return self.send_payload(t)

    # Log
    def log_info(self, text: str):
        self._append_log(text)
    def log_err(self, text: str):
        self._append_log(text)
    def _append_log(self, text: str):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def on_close(self):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
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
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()

