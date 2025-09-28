#!/usr/bin/env python3
# fds_to_gaz.py — FDS TBox → ALGE GAZ bridge (HEAD)
# GAZ: 2400 8N1 ASCII + CR
# Czas HEAD:
#   <100 s:  "  0   .       " + S lub SS + ".DD 00"
#   >=100 s: "  0   .     " + H + " " + SS + ".DD 00"  (spacja po setkach)
# W trybie bez DD dajemy po kropce trzy spacje: ".   00"
# FDS: start na C0 lub C0M. Po starcie kolejne C0 ignorujemy. Zatrzymanie tylko na małe c1 z czasem. C1 (duże) ignorujemy.

import tkinter as tk
from tkinter import ttk, messagebox
import serial
from serial.tools import list_ports
import threading
import time
import re

# Porty
GAZ_BAUD = 2400
FDS_BAUD_DEFAULT = 9600
BYTESIZE = serial.EIGHTBITS
PARITY = serial.PARITY_NONE
STOPBITS = serial.STOPBITS_ONE

# Tokeny
RE_C0 = re.compile(r"C0")          # C0 i warianty typu C0M
RE_c1 = re.compile(r"c1", re.ASCII)  # tylko małe c1

class BridgeApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FDS → GAZ bridge")

        # Porty
        self.ser_fds = None
        self.ser_gaz = None
        self.lock_gaz = threading.Lock()

        # Wątki
        self.reader_thread = None
        self.reader_stop = threading.Event()

        self.ticker_thread = None
        self.ticker_stop = threading.Event()
        self.start_monotonic = None
        self.last_sent_sec = -1

        # Timery
        self.clear_timer = None

        # Stan
        self.state = "IDLE"  # IDLE | RUN

        # UI górne: FDS i GAZ
        top = ttk.Frame(root, padding=8)
        top.pack(fill=tk.X)

        # FDS
        fdsf = ttk.LabelFrame(top, text="FDS TBox (input)", padding=8)
        fdsf.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,8))
        ttk.Label(fdsf, text="Port:").grid(row=0, column=0, sticky="w")
        self.fds_port = ttk.Combobox(fdsf, width=28, state="readonly")
        self.fds_port.grid(row=0, column=1, sticky="w", padx=(6,0))
        ttk.Label(fdsf, text="Baud:").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.fds_baud = ttk.Combobox(
            fdsf, width=10, state="readonly",
            values=["2400","4800","9600","19200","38400"]
        )
        self.fds_baud.set(str(FDS_BAUD_DEFAULT))
        self.fds_baud.grid(row=1, column=1, sticky="w", padx=(6,0), pady=(6,0))
        self.btn_fds_connect = ttk.Button(fdsf, text="Connect FDS", command=self.connect_fds)
        self.btn_fds_connect.grid(row=2, column=0, pady=(8,0), sticky="we")
        self.btn_fds_disconnect = ttk.Button(fdsf, text="Disconnect FDS", command=self.disconnect_fds, state=tk.DISABLED)
        self.btn_fds_disconnect.grid(row=2, column=1, pady=(8,0), sticky="we")

        # GAZ
        gazf = ttk.LabelFrame(top, text="GAZ (output)", padding=8)
        gazf.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(gazf, text="Port:").grid(row=0, column=0, sticky="w")
        self.gaz_port = ttk.Combobox(gazf, width=28, state="readonly")
        self.gaz_port.grid(row=0, column=1, sticky="w", padx=(6,0))
        ttk.Label(gazf, text="Baud:").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.gaz_baud = ttk.Combobox(
            gazf, width=10, state="readonly",
            values=["2400","4800","9600","19200","38400"]
        )
        self.gaz_baud.set(str(GAZ_BAUD))
        self.gaz_baud.grid(row=1, column=1, sticky="w", padx=(6,0), pady=(6,0))
        self.btn_gaz_connect = ttk.Button(gazf, text="Connect GAZ", command=self.connect_gaz)
        self.btn_gaz_connect.grid(row=2, column=0, pady=(8,0), sticky="we")
        self.btn_gaz_disconnect = ttk.Button(gazf, text="Disconnect GAZ", command=self.disconnect_gaz, state=tk.DISABLED)
        self.btn_gaz_disconnect.grid(row=2, column=1, pady=(8,0), sticky="we")

        # Przyciski globalne i testy
        btns = ttk.Frame(root, padding=(8,0))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Refresh ports", command=self.refresh_ports).pack(side=tk.LEFT)
        self.btn_connect = ttk.Button(btns, text="Connect both", command=self.connect)
        self.btn_connect.pack(side=tk.LEFT, padx=(8,0))
        self.btn_disconnect = ttk.Button(btns, text="Disconnect both", command=self.disconnect, state=tk.DISABLED)
        self.btn_disconnect.pack(side=tk.LEFT, padx=(8,0))
        ttk.Button(btns, text="Test: 49 no-DD", command=lambda: self.send_time_no_dd(49)).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Test: 49.00", command=lambda: self.send_time_with_dd(49,0)).pack(side=tk.RIGHT, padx=(8,0))

        # Log
        ttk.Label(root, padding=(8,4), text="Log:").pack(anchor="w")
        self.log = tk.Text(root, height=16, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

        # Hold po finiszu
        holdf = ttk.Frame(root, padding=(8,6))
        holdf.pack(fill=tk.X)
        ttk.Label(holdf, text="Hold final time (s):").pack(side=tk.LEFT)
        self.hold_var = tk.IntVar(value=7)
        self.hold_combo = ttk.Combobox(
            holdf, width=4, state="readonly",
            values=["5","6","7","8","9","10"]
        )
        self.hold_combo.set(str(self.hold_var.get()))
        self.hold_combo.pack(side=tk.LEFT, padx=(6,0))
        ttk.Label(holdf, text="(then clear to 0.00)").pack(side=tk.LEFT, padx=(8,0))

        # Status
        self.status = tk.StringVar(value="Not connected")
        ttk.Label(root, textvariable=self.status, relief=tk.SUNKEN, anchor="w", padding=6).pack(fill=tk.X)

        self.refresh_ports()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # Porty
    def refresh_ports(self):
        ports = [f"{p.device} {p.description}" for p in list_ports.comports()]
        def set_combo(combo, items):
            combo["values"] = items
            if items:
                combo.set(items[0])
        set_combo(self.fds_port, ports)
        set_combo(self.gaz_port, ports)
        self.log_info("Port list refreshed")

    def _pick_dev(self, combo):
        val = combo.get()
        return val.split(" ")[0] if val else None

    # Połączenie — per urządzenie i oba
    def connect_fds(self):
        if self.ser_fds and self.ser_fds.is_open:
            self.log_info("FDS already connected")
            return True
        dev_fds = self._pick_dev(self.fds_port)
        if not dev_fds:
            self.log_err("No FDS port selected")
            return False
        try:
            self.ser_fds = serial.Serial(
                dev_fds,
                baudrate=int(self.fds_baud.get()),
                bytesize=BYTESIZE, parity=PARITY, stopbits=STOPBITS,
                timeout=0.1
            )
        except Exception as e:
            messagebox.showerror("FDS connection error", str(e))
            self.log_err(f"FDS connection error: {e}")
            self.ser_fds = None
            return False
        if not (self.reader_thread and self.reader_thread.is_alive()):
            self.reader_stop.clear()
            self.reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.reader_thread.start()
        self.btn_fds_connect.config(state=tk.DISABLED)
        self.btn_fds_disconnect.config(state=tk.NORMAL)
        self.status.set(f"FDS connected {dev_fds} @ {self.fds_baud.get()}")
        self.log_info("FDS connected")
        return True

    def disconnect_fds(self):
        self._stop_ticker()
        self.reader_stop.set()
        if self.reader_thread and self.reader_thread.is_alive():
            try:
                self.reader_thread.join(timeout=1.0)
            except Exception:
                pass
        try:
            if self.ser_fds:
                self.ser_fds.close()
        except Exception:
            pass
        self.ser_fds = None
        self.btn_fds_connect.config(state=tk.NORMAL)
        self.btn_fds_disconnect.config(state=tk.DISABLED)
        self.log_info("FDS disconnected")
        return True

    def connect_gaz(self):
        if self.ser_gaz and self.ser_gaz.is_open:
            self.log_info("GAZ already connected")
            return True
        dev_gaz = self._pick_dev(self.gaz_port)
        if not dev_gaz:
            self.log_err("No GAZ port selected")
            return False
        try:
            self.ser_gaz = serial.Serial(
                dev_gaz,
                baudrate=int(self.gaz_baud.get()),
                bytesize=BYTESIZE, parity=PARITY, stopbits=STOPBITS,
                timeout=0
            )
        except Exception as e:
            messagebox.showerror("GAZ connection error", str(e))
            self.log_err(f"GAZ connection error: {e}")
            self.ser_gaz = None
            return False
        self.btn_gaz_connect.config(state=tk.DISABLED)
        self.btn_gaz_disconnect.config(state=tk.NORMAL)
        self.status.set(f"GAZ connected {dev_gaz} @ {self.gaz_baud.get()}")
        self.log_info("GAZ connected")
        return True

    def disconnect_gaz(self):
        try:
            if self.ser_gaz:
                self.ser_gaz.close()
        except Exception:
            pass
        self.ser_gaz = None
        self.btn_gaz_connect.config(state=tk.NORMAL)
        self.btn_gaz_disconnect.config(state=tk.DISABLED)
        self.log_info("GAZ disconnected")
        return True

    def connect(self):
        ok_fds = self.connect_fds()
        ok_gaz = self.connect_gaz()
        if ok_fds or ok_gaz:
            self.btn_connect.config(state=tk.DISABLED)
            self.btn_disconnect.config(state=tk.NORMAL)
            self.log_info("Connected (both)")
        else:
            self.log_err("Connect failed")

    def disconnect(self):
        self._stop_ticker()
        if self.clear_timer:
            try:
                self.clear_timer.cancel()
            except Exception:
                pass
            self.clear_timer = None
        self.reader_stop.set()
        self._close_ports()
        self.btn_connect.config(state=tk.NORMAL)
        self.btn_disconnect.config(state=tk.DISABLED)
        self.status.set("Not connected")
        self.log_info("Disconnected")

    def _close_ports(self):
        try:
            if self.ser_fds:
                self.ser_fds.close()
        except Exception:
            pass
        try:
            if self.ser_gaz:
                self.ser_gaz.close()
        except Exception:
            pass
        self.ser_fds = None
        self.ser_gaz = None

    # Reader
    def _reader_loop(self):
        buf = bytearray()
        while not self.reader_stop.is_set():
            try:
                chunk = self.ser_fds.read(256)
            except Exception as e:
                self.log_err(f"FDS read error: {e}")
                break
            if not chunk:
                continue
            buf.extend(chunk)
            # Linie z CR/LF
            while True:
                nl = buf.find(b"\n")
                cr = buf.find(b"\r")
                cut = -1
                if nl != -1 and cr != -1:
                    cut = min(nl, cr)
                elif nl != -1:
                    cut = nl
                elif cr != -1:
                    cut = cr
                if cut == -1:
                    break
                line = bytes(buf[:cut]).decode('ascii', errors='ignore')
                del buf[:cut+1]
                self._handle_line(line)
            # Skany bez końca linii
            if len(buf) > 128:
                s = buf.decode('ascii', errors='ignore')
                self._scan_tokens_inline(s)
                buf.clear()

    def _parse_fds_time(self, s: str):
        # "00004.4800" -> 4.48 (bierzemy dwie pierwsze po kropce)
        m = re.search(r"(\d{1,5})[.:](\d{2})(\d{2})", s)
        if m:
            sec = int(m.group(1).lstrip('0') or '0')
            dd = int(m.group(2))
            return sec, dd
        # fallback SSS.DD lub SSS.D
        m = re.search(r"(\d{1,3})[.:](\d{1,2})", s)
        if m:
            sec = int(m.group(1))
            dd_part = m.group(2)
            dd = int(dd_part) * 10 if len(dd_part) == 1 else int(dd_part)
            return sec, dd
        # same sekundy
        m = re.search(r"(\d{1,3})(?![\d.:])", s)
        if m:
            return int(m.group(1)), 0
        return None

    def _handle_line(self, line: str):
        s = line.strip("\r\n")
        if not s:
            return
        self.log_info(f"FDS: {s}")
        # Start tylko w IDLE, akceptuj C0 i C0M
        if self.state == "IDLE" and RE_C0.search(s):
            self.log_info("FDS: C0 → start ticking")
            self._start_ticker()
            self.state = "RUN"
            return
        # C0 w RUN ignoruj
        if self.state == "RUN" and RE_C0.search(s):
            self.log_info("FDS: C0 ignored (already running)")
            return
        # Stop tylko na małe c1 z czasem
        if RE_c1.search(s):
            parsed = self._parse_fds_time(s)
            if parsed:
                sec, dd = parsed
                self.log_info(f"FDS: c1 {sec}.{dd:02d} → stop + send final")
                self._send_final_and_stop(sec, dd)
                self.state = "IDLE"
            else:
                self.log_info("FDS: c1 found but no time parsed — ignored")
            return
        # Wielkie C1 ignoruj
        if "C1" in s:
            self.log_info("FDS: C1 ignored by rule")

    def _scan_tokens_inline(self, s: str):
        if self.state == "IDLE" and RE_C0.search(s):
            self.log_info("FDS token: C0 → start ticking")
            self._start_ticker()
            self.state = "RUN"
        elif self.state == "RUN" and RE_C0.search(s):
            self.log_info("FDS token: C0 ignored (already running)")
        if RE_c1.search(s):
            parsed = self._parse_fds_time(s)
            if parsed:
                sec, dd = parsed
                self.log_info(f"FDS token: c1 {sec}.{dd:02d} → stop + send final")
                self._send_final_and_stop(sec, dd)
                self.state = "IDLE"
        elif "C1" in s:
            self.log_info("FDS token: C1 ignored by rule")

    # Ticker
    def _start_ticker(self):
        self._stop_ticker()
        # anuluj ewentualny timer czyszczenia
        if self.clear_timer:
            try:
                self.clear_timer.cancel()
            except Exception:
                pass
            self.clear_timer = None
        self.start_monotonic = time.monotonic()
        self.last_sent_sec = -1
        self.ticker_stop.clear()
        self.ticker_thread = threading.Thread(target=self._ticker_loop, daemon=True)
        self.ticker_thread.start()

    def _stop_ticker(self):
        if self.ticker_thread and self.ticker_thread.is_alive():
            self.ticker_stop.set()
            self.ticker_thread.join(timeout=1.0)
        self.ticker_thread = None
        self.ticker_stop.clear()
        self.start_monotonic = None
        self.last_sent_sec = -1
        if self.clear_timer:
            try:
                self.clear_timer.cancel()
            except Exception:
                pass
            self.clear_timer = None

    def _ticker_loop(self):
        while not self.ticker_stop.is_set():
            elapsed = int(time.monotonic() - self.start_monotonic)
            if elapsed != self.last_sent_sec and elapsed >= 1:
                self.last_sent_sec = elapsed
                self.send_time_no_dd(elapsed)
            time.sleep(0.05)

    # Ramki GAZ
    @staticmethod
    def _head_lt100():
        return "  0   .       "  # 14 znaków
    @staticmethod
    def _head_ge100():
        return "  0   .     "    # 12 znaków

    def build_head_with_dd(self, sec: int, dd: int) -> str:
        if sec >= 100:
            H = str(sec // 100)
            SS = f"{sec % 100:02d}"
            return self._head_ge100() + f"{H} {SS}.{dd:02d} 00"
        else:
            S = f" {sec}" if sec < 10 else str(sec)
            return self._head_lt100() + f"{S}.{dd:02d} 00"

    def build_head_no_dd(self, sec: int) -> str:
        if sec >= 100:
            H = str(sec // 100)
            SS = f"{sec % 100:02d}"
            return self._head_ge100() + f"{H} {SS}.   00"
        else:
            S = f" {sec}" if sec < 10 else str(sec)
            return self._head_lt100() + f"{S}.   00"

    # Wysyłka do GAZ
    def _send_gaz(self, payload: str):
        if not self.ser_gaz or not self.ser_gaz.is_open:
            self.log_err("GAZ not connected")
            return False
        data = (payload + "\r").encode("ascii")
        with self.lock_gaz:
            try:
                self.ser_gaz.write(data)
                try:
                    self.ser_gaz.flush()
                except Exception:
                    pass
            except Exception as e:
                self.log_err(f"GAZ send error: {e}")
                return False
        self.log_info(f"Sent: {repr(payload)} + CR")
        return True

    # Publiczne helpery
    def send_time_no_dd(self, sec: int):
        frame = self.build_head_no_dd(sec)
        return self._send_gaz(frame)

    def send_time_with_dd(self, sec: int, dd: int):
        frame = self.build_head_with_dd(sec, dd)
        return self._send_gaz(frame)

    def _send_final_and_stop(self, sec: int, dd: int):
        self._stop_ticker()
        self.send_time_with_dd(sec, dd)
        # hold i czyszczenie
        try:
            hold_s = int(self.hold_combo.get())
        except Exception:
            hold_s = 7
        hold_s = max(5, min(10, hold_s))
        self.log_info(f"Hold final time for {hold_s}s, then clear to 0.00")
        if self.clear_timer:
            try:
                self.clear_timer.cancel()
            except Exception:
                pass
        self.clear_timer = threading.Timer(hold_s, self._clear_display)
        self.clear_timer.daemon = True
        self.clear_timer.start()

    # Czyszczenie na 0.00
    def _clear_display(self):
        self.send_time_with_dd(0, 0)
        self.log_info("Cleared display to 0.00")

    # Log
    def log_info(self, s: str):
        self._append_log(s)
    def log_err(self, s: str):
        self._append_log(s)
    def _append_log(self, s: str):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, s + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def on_close(self):
        self.disconnect()
        try:
            self.root.destroy()
        except Exception:
            pass

def main():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)
    except Exception:
        pass
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    BridgeApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()

