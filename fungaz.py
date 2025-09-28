#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GAZ GUI — send characters to a 7‑segment display

- The display has 5 visible character positions
- Each position is a 7‑segment digit
- We send only characters that can be drawn on 7‑segment
- Space means blank position
- Serial: 2400 baud, 8N1, ASCII
- Each frame ends with CR (0x0D)
- Frame format: HEAD + content + CR
  HEAD: "  0   .     "  (11 chars)
  Content uses 7 slots built from 5 inputs: a _ b c _ d e
  where slots 2 and 5 are always spaces (blocked)
  The final string is: a␣bc␣de␣00 appended to HEAD
"""

import tkinter as tk
from tkinter import ttk, messagebox

try:
    import serial
    import serial.tools.list_ports
except Exception:
    serial = None  # local/log mode only

# Allowed glyphs that the device can show
LETTER_MAP = {
    # big letters
    'A': 'A', 'C': 'C', 'E': 'E', 'F': 'F', 'G': 'G', 'H': 'H',
    'I': 'I', 'J': 'J', 'L': 'L', 'P': 'P', 'S': 'S', 'U': 'U',
    # 7-seg specific lowercase variants
    'b': 'b', 'd': 'd', 'o': 'o',
    # digits
    '0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',
    # symbols
    '-':'-', '_':'_', ' ':' ',
}

# Fixed head per spec for >=100 s variant (we use it for letters too)
HEADER = "  0   .     "  # 11 characters

class Sender:
    def __init__(self, port: str, baud: int = 2400):
        self.port = port
        self.baud = baud
        self.ser = None
        if serial is not None and port and port != "no ports":
            try:
                # 8N1 is default for pyserial when bytesize=EIGHTBITS, parity=PARITY_NONE, stopbits=ONE
                self.ser = serial.Serial(port, baud, timeout=1)
            except Exception as e:
                print(f"[WARN] cannot open port {port}: {e}")
        else:
            print("[WARN] pyserial unavailable or no port. Using local mode.")

    def send_ascii_cr(self, text: str):
        data = text.encode("ascii") + b"\r"
        if self.ser:
            try:
                self.ser.write(data)
            except Exception as e:
                print(f"[ERR] serial write failed: {e}")
        else:
            print(f"[LOCAL SEND] {data!r}")

    def close(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GAZ — 7‑seg letter sender")
        self.geometry("560x420")

        # connection
        self.var_port = tk.StringVar()
        self.sender = None

        # 5 input fields for a, b, c, d, e
        self.var_a = tk.StringVar()
        self.var_b = tk.StringVar()
        self.var_c = tk.StringVar()
        self.var_d = tk.StringVar()
        self.var_e = tk.StringVar()

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # Connection UI
        conn = ttk.LabelFrame(root, text="Connection")
        conn.pack(fill="x", pady=6)
        ttk.Label(conn, text="Port").pack(side="left", padx=5)
        self.combo_ports = ttk.Combobox(conn, textvariable=self.var_port, width=26, state="readonly")
        self.combo_ports.pack(side="left", padx=5)
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).pack(side="left", padx=5)
        ttk.Button(conn, text="Connect (2400 8N1)", command=self.connect).pack(side="left", padx=5)

        # Allowed characters
        allowed = ttk.LabelFrame(root, text="Allowed characters")
        allowed.pack(fill="x", pady=6)
        ttk.Label(allowed, text=" ".join(LETTER_MAP.keys())).pack(padx=6, pady=6)

        # Inputs a _ b c _ d e
        enter = ttk.LabelFrame(root, text="Enter letters: a  b  c  d  e")
        enter.pack(fill="x", pady=6)
        row = ttk.Frame(enter)
        row.pack(pady=6)

        def mk(label, var):
            box = ttk.Frame(row)
            box.pack(side="left", padx=6)
            ttk.Label(box, text=label).pack()
            ent = ttk.Entry(box, textvariable=var, font=("Courier", 18), width=2, justify="center")
            ent.pack()
            return ent

        self.ent_a = mk("a", self.var_a)
        ttk.Label(row, text="␣").pack(side="left", padx=4)  # blocked pos2
        self.ent_b = mk("b", self.var_b)
        self.ent_c = mk("c", self.var_c)
        ttk.Label(row, text="␣").pack(side="left", padx=4)  # blocked pos5
        self.ent_d = mk("d", self.var_d)
        self.ent_e = mk("e", self.var_e)

        ttk.Button(enter, text="Send", command=self.send_letters).pack(pady=5)

        # Status
        self.lbl_status = ttk.Label(root, text="")
        self.lbl_status.pack(pady=6)

        # Live frame preview
        prev = ttk.LabelFrame(root, text="Frame preview")
        prev.pack(fill="x", pady=6)
        self.lbl_ascii = ttk.Label(prev, text="ASCII:")
        self.lbl_ascii.pack(anchor="w", padx=6, pady=2)
        self.lbl_hex = ttk.Label(prev, text="HEX:")
        self.lbl_hex.pack(anchor="w", padx=6, pady=2)

        self.refresh_ports()

        # validator: block disallowed and keep 1 char per field
        vcmd = (self.register(self._validate_char), "%P", "%S", "%W")
        for ent in (self.ent_a, self.ent_b, self.ent_c, self.ent_d, self.ent_e):
            ent.config(validate="key", validatecommand=vcmd)

        # key guards
        for ent, var in (
            (self.ent_a, self.var_a), (self.ent_b, self.var_b), (self.ent_c, self.var_c),
            (self.ent_d, self.var_d), (self.ent_e, self.var_e)
        ):
            ent.bind("<KeyPress>", lambda e, v=var: self._block_extra_key(e, v))
            ent.bind("<KeyRelease>", lambda e, v=var: (self._auto_advance(e, v), self._smart_backspace(e, v)))
            ent.bind("<<Paste>>", lambda e, v=var: self._on_paste(e, v))

        # initial preview
        self.update_preview()

    # ---------- Ports ----------
    def refresh_ports(self):
        ports = []
        if serial is not None:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = ["no ports"]
        self.combo_ports["values"] = ports
        self.var_port.set(ports[0])

    def connect(self):
        port = self.var_port.get().strip()
        if port == "no ports":
            messagebox.showwarning("Error", "No serial devices found")
            return
        if self.sender:
            self.sender.close()
        self.sender = Sender(port, 2400)
        self.lbl_status.config(text=f"Connected to {port} (2400 baud)")

    # ---------- Mapping & validation ----------
    def _map_input_char(self, ch: str, widget=None):
        """Map a raw input char to allowed glyphs.
        - All letters are treated case-insensitively (converted to upper)
        - B/D/O use 7‑seg variants b/d/o
        - Dash '-' is disallowed in the first field (a)
        """
        if not ch:
            return ' '
        s = ch[:1]
        if s.isalpha():
            up = s.upper()
            if up == 'B':
                m = 'b'
            elif up == 'D':
                m = 'd'
            elif up == 'O':
                m = 'o'
            else:
                m = up
        else:
            m = s
        if m == '-' and widget is not None and widget == self.ent_a:
            return None
        return m if m in LETTER_MAP else None

    def _validate_char(self, proposed, inserted, widget_name):
        """Tk validatecommand: allow only 1 char and only allowed glyphs."""
        if inserted == '':  # deletion
            return True
        if proposed is None or len(proposed) > 1:
            return False
        # find which entry
        w = str(widget_name)
        widget = None
        for ent in (self.ent_a, self.ent_b, self.ent_c, self.ent_d, self.ent_e):
            if str(ent) == w:
                widget = ent
                break
        mapped = self._map_input_char(inserted, widget)
        return mapped is not None

    # ---------- Build content/frame ----------
    def collect_letters(self) -> str:
        vals = []
        for v in (self.var_a, self.var_b, self.var_c, self.var_d, self.var_e):
            raw = (v.get() or ' ')[:1]
            mapped = self._map_input_char(raw)
            if mapped is None:
                vals.append(' ')
            else:
                vals.append(LETTER_MAP.get(mapped, ' '))
        return ''.join(vals)

    def make_frame(self, letters: str) -> str:
        # letters has 5 characters (already normalized)
        a, b, c, d, e = list(letters.ljust(5))[:5]
        content = f"{a} {b}{c} {d}{e} 00"
        return HEADER + content

    # ---------- Keyboard helpers ----------
    def _focus_next(self, current):
        order = [self.ent_a, self.ent_b, self.ent_c, self.ent_d, self.ent_e]
        try:
            i = order.index(current)
        except ValueError:
            return
        if i < len(order) - 1:
            order[i+1].focus_set()

    def _focus_prev(self, current):
        order = [self.ent_a, self.ent_b, self.ent_c, self.ent_d, self.ent_e]
        try:
            i = order.index(current)
        except ValueError:
            return
        if i > 0:
            order[i-1].focus_set()

    def _route_to_next(self, current_widget, ch):
        order = [self.ent_a, self.ent_b, self.ent_c, self.ent_d, self.ent_e]
        vars_ = [self.var_a, self.var_b, self.var_c, self.var_d, self.var_e]
        try:
            i = order.index(current_widget)
        except ValueError:
            return
        if i < len(order) - 1:
            nxt = order[i+1]
            nxt_var = vars_[i+1]
            nxt_var.set((ch or ' ')[:1])
            nxt.focus_set()
            self.update_preview()

    def _auto_advance(self, event, var):
        if len(var.get()) == 1 and len(event.char) == 1:
            self._focus_next(event.widget)

    def _smart_backspace(self, event, var):
        if event.keysym == "BackSpace" and not var.get():
            self._focus_prev(event.widget)

    def _block_extra_key(self, event, var):
        key = event.keysym
        allowed_keys = {"BackSpace","Delete","Left","Right","Home","End","Tab","Shift_L","Shift_R","Control_L","Control_R","Alt_L","Alt_R"}
        if key in allowed_keys:
            return
        # reject disallowed chars
        if len(event.char) == 1 and event.char.isprintable():
            mapped = self._map_input_char(event.char, event.widget)
            if mapped is None:
                self.bell()
                return "break"
        # allow overwrite if there is selection
        try:
            has_sel = event.widget.index('sel.last') > event.widget.index('sel.first')
        except Exception:
            has_sel = False
        if has_sel:
            return
        # route 2nd printable char to the next entry
        txt = var.get() or ''
        if len(txt) >= 1 and len(event.char) == 1 and event.char.isprintable():
            mapped = self._map_input_char(event.char, event.widget)
            if mapped is None:
                self.bell()
                return "break"
            self._route_to_next(event.widget, mapped)
            return "break"

    def _on_paste(self, event, var):
        try:
            data = event.widget.clipboard_get() or ''
        except Exception:
            data = ''
        order = [self.ent_a, self.ent_b, self.ent_c, self.ent_d, self.ent_e]
        vars_ = [self.var_a, self.var_b, self.var_c, self.var_d, self.var_e]
        try:
            i = order.index(event.widget)
        except ValueError:
            i = 0
        for ch in data:
            mapped = self._map_input_char(ch, event.widget)
            if mapped is None:
                continue
            if i >= len(vars_):
                break
            vars_[i].set(mapped)
            i += 1
        last = min(i-1, len(order)-1) if i > 0 else order.index(event.widget)
        order[last].focus_set()
        self.update_preview()
        return "break"

    # ---------- Preview ----------
    def update_preview(self, *_):
        letters = self.collect_letters()
        frame = self.make_frame(letters)
        ascii_vis = frame.replace(" ", "␣") + "\\r"
        hex_vis = " ".join(f"{b:02X}" for b in (frame + "\\r").encode("ascii"))
        self.lbl_ascii.config(text=f"ASCII: {ascii_vis}")
        self.lbl_hex.config(text=f"HEX:   {hex_vis}")

    # ---------- Actions ----------
    def send_letters(self):
        if not self.sender:
            messagebox.showwarning("Error", "Not connected to a device")
            return
        letters = self.collect_letters()
        frame = self.make_frame(letters)
        self.sender.send_ascii_cr(frame)
        self.lbl_status.config(text=f"Sent: '{letters}' as frame")
        self.update_preview()

    def on_close(self):
        if self.sender:
            self.sender.close()
        self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()

if __name__ == "__main__":
    main()
