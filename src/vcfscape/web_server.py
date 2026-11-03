"""
Local Web Server Launcher for VCFscape - VCF inspector part of vivaxGEN Project.
Serves the React/TypeScript surveillance web application locally using Python's
built-in standard library HTTP server without requiring Node.js or any external packages.
"""

import sys
import os
import json
import socket
import secrets
import argparse
import webbrowser
import urllib.parse
from http.cookies import SimpleCookie
from typing import Optional, Dict, Any, Tuple
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from vcfscape.core.vcf_reader import VcfReader
from vcfscape.core.cohorts import CohortManager

__version__ = "0.1.0"


def get_local_ip() -> str:
    """Detect the machine's primary local IP address."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # 10.255.255.255 doesn't need to be reachable; kernel picks the outgoing interface IP
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        if s:
            s.close()
    return ip


def get_fqdn() -> str:
    """Detect fully qualified domain name (FQDN)."""
    try:
        hostname = socket.gethostname()
        fqdn = socket.getfqdn(hostname)
        return fqdn if fqdn else hostname
    except Exception:
        return "localhost"


def load_vcf_payload(vcf_path: str) -> Dict[str, Any]:
    """Parse input VCF file and structure data matching the web interface schema."""
    if not os.path.exists(vcf_path):
        raise FileNotFoundError(f"VCF file not found: {vcf_path}")

    reader = VcfReader(vcf_path)
    records = reader.get_records()
    cohort_manager = CohortManager(reader.samples)

    variants_json = []
    for idx, r in enumerate(records):
        variants_json.append({
            "id": f"var_{idx}_{r.chrom}_{r.pos}",
            "chrom": r.chrom,
            "pos": r.pos,
            "varId": r.var_id or ".",
            "ref": r.ref,
            "alt": r.alt,
            "qual": r.qual if r.qual is not None else 0,
            "filter": r.filter,
            "gene": r.gene,
            "impact": r.impact,
            "mutation": r.mutation,
            "drug": r.drug if r.drug and r.drug != "." else None,
            "drugStatus": r.drug_annotation.status if r.drug_annotation else None,
            "drugDetails": r.drug_annotation.details if r.drug_annotation else None,
            "varType": r.var_type,
            "info": {str(k): str(v) for k, v in r.info.items()},
            "formatKeys": r.format_keys,
            "samples": {
                s: {
                    "GT": str(sdata.get("GT", "./.")),
                    "DP": int(sdata.get("DP", 0)) if isinstance(sdata.get("DP"), (int, float)) or str(sdata.get("DP", "")).isdigit() else 0,
                    "AD": str(sdata.get("AD", ".")),
                    "GQ": int(sdata.get("GQ", 0)) if isinstance(sdata.get("GQ"), (int, float)) or str(sdata.get("GQ", "")).isdigit() else 0,
                    "PL": str(sdata.get("PL", "")) if "PL" in sdata else None,
                }
                for s, sdata in r.sample_data.items()
            },
        })

    cohorts_json = [
        {
            "name": c.name,
            "sampleIds": c.sample_ids,
            "description": c.description,
            "active": c.active,
            "color": c.color,
        }
        for c in cohort_manager.cohorts.values()
    ]

    return {
        "filename": os.path.basename(vcf_path),
        "totalVariants": len(records),
        "totalSamples": len(reader.samples),
        "backend": reader.backend,
        "samples": reader.samples,
        "cohorts": cohorts_json,
        "variants": variants_json,
    }


def find_web_directory() -> str:
    """Locate bundled or built web static directory."""
    candidates = [
        # 1. Bundled inside package
        os.path.join(os.path.dirname(__file__), "web_dist"),
        # 2. Local workspace dist/
        os.path.join(os.getcwd(), "dist"),
        # 3. Workspace root relative to this file
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "dist")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "dist")),
    ]
    for c in candidates:
        if os.path.exists(c) and os.path.exists(os.path.join(c, "index.html")):
            return c
    return ""


class SpaStaticHTTPHandler(SimpleHTTPRequestHandler):
    """
    HTTP handler serving static assets with proper MIME types
    and fallback to index.html for Single Page Applications (SPA).
    Secured with optional/default cryptographically random access tokens.
    """

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "application/javascript",
        ".mjs": "application/javascript",
        ".css": "text/css",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".vcf": "text/plain; charset=utf-8",
        ".tsv": "text/tab-separated-values; charset=utf-8",
    }

    def _is_authenticated(self) -> Tuple[bool, bool]:
        """Check if incoming request provides the required security token.
        Returns: (is_authenticated, token_in_query)
        """
        expected_token = getattr(self.server, "auth_token", None)
        if not expected_token:
            return True, False  # Token authentication disabled

        # 1. Check query parameter ?token=...
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            query_token = qs.get("token", [None])[0]
            if query_token and secrets.compare_digest(query_token, expected_token):
                return True, True
        except Exception:
            pass

        # 2. Check session cookie
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            try:
                cookies = SimpleCookie()
                cookies.load(cookie_header)
                if "malaria_vcf_token" in cookies:
                    cookie_val = cookies["malaria_vcf_token"].value
                    if secrets.compare_digest(cookie_val, expected_token):
                        return True, False
            except Exception:
                pass

        # 3. Check Authorization header or X-Auth-Token
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            bearer_val = auth_header[7:].strip()
            if secrets.compare_digest(bearer_val, expected_token):
                return True, False

        x_token = self.headers.get("X-Auth-Token", "").strip()
        if x_token and secrets.compare_digest(x_token, expected_token):
            return True, False

        return False, False

    def end_headers(self):
        """Include session cookie when authenticated via query token."""
        if getattr(self, "_should_set_cookie", False):
            expected_token = getattr(self.server, "auth_token", None)
            if expected_token:
                self.send_header(
                    "Set-Cookie",
                    f"malaria_vcf_token={expected_token}; Path=/; SameSite=Lax",
                )
        super().end_headers()

    def _render_auth_required_page(self) -> str:
        """Render stylish HTML prompt when token is missing or invalid."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>401 - Authentication Required | VCFscape</title>
  <style>
    body {
      margin: 0;
      padding: 0;
      background-color: #0b0f17;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", monospace;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }
    .card {
      background-color: #161e2e;
      border: 1px solid #334155;
      border-radius: 8px;
      padding: 32px;
      max-width: 440px;
      width: 90%;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
      text-align: center;
    }
    .badge {
      display: inline-block;
      background: #0284c7;
      color: #ffffff;
      font-weight: 700;
      font-size: 11px;
      letter-spacing: 0.08em;
      padding: 3px 8px;
      border-radius: 4px;
      text-transform: uppercase;
      margin-bottom: 16px;
    }
    h1 {
      font-size: 20px;
      margin: 0 0 10px 0;
      color: #f8fafc;
    }
    p {
      font-size: 13px;
      color: #94a3b8;
      line-height: 1.5;
      margin: 0 0 24px 0;
    }
    .form-group {
      text-align: left;
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 11px;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 6px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    input[type="text"] {
      width: 100%;
      box-sizing: border-box;
      padding: 10px 12px;
      font-size: 14px;
      font-family: monospace;
      background: #0f172a;
      border: 1px solid #475569;
      border-radius: 6px;
      color: #f1f5f9;
      outline: none;
    }
    input[type="text"]:focus {
      border-color: #38bdf8;
      box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
    }
    button {
      width: 100%;
      padding: 10px 16px;
      font-size: 14px;
      font-weight: 600;
      background: #0284c7;
      color: #ffffff;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.15s ease;
    }
    button:hover {
      background: #0369a1;
    }
    .hint {
      margin-top: 20px;
      font-size: 12px;
      color: #64748b;
      line-height: 1.4;
      text-align: left;
      background: #0f172a;
      padding: 10px 12px;
      border-radius: 6px;
      border: 1px solid #1e293b;
    }
    .hint code {
      color: #38bdf8;
      font-family: monospace;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">VCFSCAPE &bull; VIVAXGEN PROJECT</div>
    <h1>Authentication Required</h1>
    <p>This VCFscape Web session is protected by a secure URL access token.</p>
    <form method="GET" action="/">
      <div class="form-group">
        <label for="tok">Security Access Token</label>
        <input id="tok" type="text" name="token" placeholder="Paste security token here..." autofocus required />
      </div>
      <button type="submit">Unlock VCFscape</button>
    </form>
    <div class="hint">
      <strong>How to get access:</strong><br />
      Check the terminal console where <code>vcfscape-web</code> or <code>vcfscape --web</code> was started. Copy the token or open one of the generated URLs directly.
    </div>
  </div>
</body>
</html>"""

    def do_GET(self):
        is_authed, token_in_query = self._is_authenticated()
        if token_in_query:
            self._should_set_cookie = True

        clean_path = self.path.split("?")[0].rstrip("/")

        # Check authentication before responding
        if not is_authed:
            if clean_path in ("/api/vcf-data", "/api/data") or clean_path.startswith("/api/"):
                resp = json.dumps({
                    "error": "Unauthorized",
                    "message": "Secure authentication token required or invalid. Provide ?token=<token> or Set-Cookie header.",
                }).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(resp)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(resp)
                return

            html = self._render_auth_required_page()
            resp = html.encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(resp)
            return

        # API endpoint providing the parsed VCF dataset from the command line
        if clean_path in ("/api/vcf-data", "/api/data"):
            payload = getattr(self.server, "vcf_payload", None)
            if payload is not None:
                resp = json.dumps({"hasCustomVcf": True, "data": payload}).encode("utf-8")
            else:
                resp = json.dumps({"hasCustomVcf": False}).encode("utf-8")

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(resp)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(resp)
            return

        # Resolve requested path relative to server directory
        path = self.translate_path(self.path)
        if not os.path.exists(path):
            # Fallback to index.html for SPA client-side routes
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, format, *args):
        # Concise terminal logging
        sys.stderr.write(f"[{self.log_date_time_string()}] {args[0]} -> {args[1]}\n")


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if TCP port is currently occupied."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False


def run_web_server(
    port: int = 3000,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    web_dir: str = "",
    vcf_path: Optional[str] = None,
    token: Optional[str] = None,
    no_token: bool = False,
):
    """Start local HTTP server serving the web interface."""
    target_dir = web_dir or find_web_directory()

    if not target_dir:
        sys.stderr.write("Error: Web simulator build directory not found.\n")
        sys.stderr.write("If developing from source, run 'npm install && npm run build' first.\n")
        sys.exit(1)

    vcf_payload = None
    if vcf_path:
        try:
            print(f"Reading input VCF: {vcf_path}...")
            vcf_payload = load_vcf_payload(vcf_path)
            print(f"Loaded {vcf_payload['totalVariants']} variants across {vcf_payload['totalSamples']} samples.")
        except Exception as e:
            sys.stderr.write(f"Error reading VCF file '{vcf_path}': {e}\n")
            sys.exit(1)

    # Determine security token
    if no_token:
        auth_token = None
    elif token is not None and token.strip():
        auth_token = token.strip()
    else:
        auth_token = secrets.token_hex(16)

    # Find available port if specified port is in use
    active_port = port
    while is_port_in_use(active_port, host) and active_port < port + 20:
        active_port += 1

    local_ip = get_local_ip()
    fqdn = get_fqdn()

    token_query = f"?token={auth_token}" if auth_token else ""
    local_url = f"http://127.0.0.1:{active_port}/{token_query}"
    ip_url = f"http://{local_ip}:{active_port}/{token_query}"
    fqdn_url = f"http://{fqdn}:{active_port}/{token_query}"

    def handler(*args, **kwargs):
        SpaStaticHTTPHandler(*args, directory=target_dir, **kwargs)

    try:
        server = ThreadingHTTPServer((host, active_port), handler)
        server.auth_token = auth_token
        server.vcf_payload = vcf_payload
    except OSError as e:
        sys.stderr.write(f"Failed to bind to {host}:{active_port}: {e}\n")
        sys.exit(1)

    # Export payload to static JSON if possible
    if vcf_payload is not None:
        try:
            json_file = os.path.join(target_dir, "vcf_data.json")
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump({"hasCustomVcf": True, "data": vcf_payload}, f)
        except Exception:
            pass

    print("=" * 72)
    print(f" VCFscape - VCF inspector part of vivaxGEN Project v{__version__}")
    print("=" * 72)
    print(f"  * Localhost URL:     {local_url}")
    print(f"  * Network IP URL:    {ip_url}")
    print(f"  * FQDN URL:          {fqdn_url}")
    if auth_token:
        print(f"  * Security Token:    {auth_token}")
    else:
        print(f"  * Security Token:    [Disabled - Open Access]")
    print(f"  * Serving Directory: {target_dir}")
    if vcf_payload:
        print(f"  * Loaded VCF:        {vcf_payload['filename']} ({vcf_payload['totalVariants']} variants, {vcf_payload['totalSamples']} samples)")
    else:
        print("  * Dataset:           Pf3D7 Surveillance Demo (Default)")
    print(f"  * Controls:          Press Ctrl+C to stop the server")
    print("=" * 72)

    if open_browser:
        try:
            webbrowser.open(local_url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down local web server...")
        server.shutdown()
        server.server_close()
        print("Server stopped.")


def main(args=None):
    """Entry point for vcfscape-web command."""
    parser = argparse.ArgumentParser(
        prog="vcfscape-web",
        description="Launch VCFscape Web Simulator on your local system.",
    )
    parser.add_argument(
        "vcf_file",
        nargs="?",
        default="",
        help="Path to input VCF file (.vcf or .vcf.gz) to inspect in the web version",
    )
    parser.add_argument(
        "--vcf",
        default="",
        help="Path to input VCF file (.vcf or .vcf.gz)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Security token to protect web access (default: auto-generates secure random token)",
    )
    parser.add_argument(
        "--no-token",
        action="store_true",
        help="Disable security token authentication (allow open access)",
    )
    parser.add_argument(
        "--port",
        "-p",
        default=3000,
        type=int,
        help="Port to bind the local web simulator server (default: 3000)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1; use 0.0.0.0 for LAN access)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically launch web browser on startup",
    )
    parser.add_argument(
        "--dir",
        dest="web_dir",
        default="",
        help="Custom directory containing static web build files (index.html, assets/)",
    )
    parsed = parser.parse_args(args)
    target_vcf = parsed.vcf or parsed.vcf_file or ""
    if target_vcf and not os.path.exists(target_vcf):
        sys.stderr.write(f"Error: VCF file '{target_vcf}' does not exist.\n")
        sys.exit(1)

    run_web_server(
        port=parsed.port,
        host=parsed.host,
        open_browser=not parsed.no_browser,
        web_dir=parsed.web_dir,
        vcf_path=os.path.abspath(target_vcf) if target_vcf else None,
        token=parsed.token,
        no_token=parsed.no_token,
    )


if __name__ == "__main__":
    main()
