import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import paramiko
import re
from datetime import datetime
import time
import os
import threading
from concurrent.futures import ThreadPoolExecutor

COMMANDS = [
    "date",
    "show version",
    "show platform chassis",
    "show platform linecard 1 detail",
    "show platform environment",
    "show platform power-supply detail",
    "info from state system ntp",
    "show interface brief",
    "show network-instance summary",
    "show network-instance protocols bgp neighbor",
    "show network-instance * interfaces",
    "show network-instance * bridge-table mac-table summary",
    "show interface brief | grep enable | grep down",
    "show interface detail | as table | filter fields ifdetail/summary/description ifdetail/summary/oper-state ifdetail/summary/last-change",
    "show system application",
    "show system lldp neighbor",
    "bash df -hT",
    "bash free -h"
]

def clean_output(text, cmd):
    if not text:
        return ""

    text = re.sub(r'\x1B\[[0-?]*[ -/]*[@-~]', '', text)
    text = re.sub(r'\x1B\[\?2004[hl]', '', text)
    text = re.sub(r'[^\x09\x0A\x20-\x7E]', '', text)

    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line = line.strip()

        if not line:
            continue

        if cmd in line:
            continue

        if re.match(r'.*[#>$]$', line) and len(line) < 50:
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


def extract_hostname(text):
    m = re.search(r'Hostname\s*:\s*(\S+)', text, re.I)
    return m.group(1) if m else None


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Nokia Log Collector")
        self.root.geometry("1000x750")

        self.dark_mode = False
        self.output_dir = os.getcwd()

        self.success = 0
        self.fail = 0

        self.build_ui()

    def build_ui(self):
        self.header = tk.Frame(self.root, bg="#f5f5f5")
        self.header.pack(fill=tk.X)

        try:
            path = os.path.join(os.path.dirname(__file__), "nokia_logo.png")
            img = tk.PhotoImage(file=path)
            lbl = tk.Label(self.header, image=img, bg="#f5f5f5")
            lbl.image = img
            lbl.pack(side=tk.LEFT, padx=10)
        except:
            tk.Label(self.header, text="NOKIA",
                     font=("Arial", 20, "bold"),
                     fg="blue").pack(side=tk.LEFT)

        tk.Label(self.header,
                 text="Prepared by: A S M Kawsar Harun",
                 bg="#f5f5f5").pack(side=tk.RIGHT, padx=10)

        ctrl = tk.Frame(self.root)
        ctrl.pack(fill=tk.X, pady=5)

        tk.Button(ctrl, text="Select Output Folder",
                  command=self.select_folder).pack(side=tk.LEFT, padx=5)

        tk.Button(ctrl, text="Toggle Dark Mode",
                  command=self.toggle_theme).pack(side=tk.LEFT)

        self.progress = ttk.Progressbar(ctrl, length=300)
        self.progress.pack(side=tk.RIGHT, padx=10)

        self.status = tk.Label(ctrl, text="Idle")
        self.status.pack(side=tk.RIGHT)

        self.content = tk.Frame(self.root)
        self.content.pack(fill=tk.BOTH, expand=True)

        self.build_screen()

    def build_screen(self):
        for w in self.content.winfo_children():
            w.destroy()

        self.ip_text = scrolledtext.ScrolledText(self.content, height=10)
        self.ip_text.pack(fill=tk.X, padx=10)

        self.user = tk.Entry(self.content)
        self.user.insert(0, "admin")
        self.user.pack()

        self.pw = tk.Entry(self.content, show="*")
        self.pw.pack()

        self.cmd_text = scrolledtext.ScrolledText(self.content)
        self.cmd_text.pack(fill=tk.BOTH, expand=True)

        for c in COMMANDS:
            self.cmd_text.insert(tk.END, c + "\n")

        tk.Button(self.content, text="START",
                  command=self.start).pack(pady=10)

        self.log = scrolledtext.ScrolledText(self.content, height=10)
        self.log.pack(fill=tk.BOTH)

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        bg = "#2b2b2b" if self.dark_mode else "white"
        self.root.configure(bg=bg)
        self.content.configure(bg=bg)

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_dir = folder
            self.write_log(f"Output folder: {folder}")

    def write_log(self, msg):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.root.update()

    def create_progress_window(self, total):
        self.progress_win = tk.Toplevel(self.root)
        self.progress_win.title("Collection Progress")
        self.progress_win.geometry("900x600")

        self.progress_text = scrolledtext.ScrolledText(
            self.progress_win,
            font=("Consolas", 10)
        )
        self.progress_text.pack(fill=tk.BOTH, expand=True)

        self.write_progress(f"Starting collection from {total} nodes...\n")

    def write_progress(self, msg):
        self.progress_text.insert(tk.END, msg + "\n")
        self.progress_text.see(tk.END)
        self.root.update()

    def start(self):
        ips = re.split(r"[,\s]+", self.ip_text.get("1.0", tk.END))
        ips = [i for i in ips if "." in i]

        cmds = [c.strip() for c in self.cmd_text.get("1.0", tk.END).splitlines() if c.strip()]

        if not ips:
            messagebox.showwarning("Error", "No IPs found")
            return

        self.progress["maximum"] = len(ips)
        self.progress["value"] = 0

        self.success = 0
        self.fail = 0

        # ✅ Create progress window
        self.create_progress_window(len(ips))

        threading.Thread(target=self.run, args=(ips, cmds)).start()

    def run(self, ips, cmds):
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for idx, ip in enumerate(ips, 1):
                futures.append(executor.submit(self.collect, ip, cmds, idx, len(ips)))

            for f in futures:
                f.result()

    def collect(self, ip, cmds, idx, total):
        try:
            self.write_progress(f"\n[{idx}/{total}] Connecting to {ip} ...")
    
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
            client.connect(ip,
                        username=self.user.get(),
                        password=self.pw.get(),
                        timeout=10,
                        look_for_keys=False)
    
            chan = client.invoke_shell()
            time.sleep(1)
    
            # Clear banner / initial prompt
            if chan.recv_ready():
                chan.recv(65535)
    
            results = {}
    
            for cmd in cmds:
                self.write_progress(f"   running: {cmd}")
    
                chan.send(cmd + "\n")
    
                output = ""
                start_time = time.time()
                timeout = 30  # seconds
    
                while True:
                    if chan.recv_ready():
                        data = chan.recv(65535).decode(errors="ignore")
                        output += data
    
                    # Detect prompt (IMPORTANT FIX)
                    tail = output[-200:]
    
                    if (
                        "#" in tail
                        or ">" in tail
                        or "$" in tail
                        or "A:" in tail
                    ):
                        break
    
                    time.sleep(0.3)
    
                cleaned = clean_output(output, cmd)
                results[cmd] = cleaned
    
            client.close()
    
            hostname = extract_hostname(
                results.get("show version", "")
            ) or f"node_{ip.replace('.', '_')}"
    
            filename = os.path.join(self.output_dir, f"{hostname}.txt")
    
            with open(filename, "w", encoding="utf-8") as f:
                for cmd, out in results.items():
                    f.write(f"\n===== {cmd} =====\n")
                    f.write(out.strip() + "\n")
    
            self.success += 1
            self.write_progress(f"→ OK (saved as {hostname})")
    
        except Exception as e:
            self.fail += 1
            self.write_progress(f"→ FAILED: {ip} ({e})")
    
        finally:
            self.progress["value"] += 1
            self.status.config(text=f"Success: {self.success}  Fail: {self.fail}")

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
