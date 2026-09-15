from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

ROOT = Path("/home/user")
PAGE = Path("/home/user/dl/index.html")
FILES = {
    "HelpCSL-project.zip": ROOT / "HelpCSL-project.zip",
    "HelpCSL-Setup.exe": ROOT / "HelpCSL-Setup-1.11.17.exe",
    "HelpCSL-Setup.msi": ROOT / "HelpCSL-Setup-1.11.17.msi",
    "HelpCSL.exe": ROOT / "HelpCSL-1.11.17.exe",
    "HelpCSL-1.11.17.exe": ROOT / "HelpCSL-1.11.17.exe",
    "HelpCSL-Setup-1.11.17.exe": ROOT / "HelpCSL-Setup-1.11.17.exe",
    "HelpCSL-Setup-1.11.17.msi": ROOT / "HelpCSL-Setup-1.11.17.msi",
    "HelpCSL-web.zip": ROOT / "HelpCSL-web.zip",
}

class H(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            data = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path.startswith("/files/"):
            name = path[len("/files/"):].split("?", 1)[0]
            fp = FILES.get(name)
            if fp and fp.is_file():
                data = fp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        self.send_error(404)

    def log_message(self, fmt, *args):
        return

if __name__ == "__main__":
    httpd = ThreadingHTTPServer(("0.0.0.0", 8080), H)
    print("Help CSL downloads  http://0.0.0.0:8080/", flush=True)
    httpd.serve_forever()
