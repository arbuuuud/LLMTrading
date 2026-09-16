"""
LLMTrading Institutional Web Dashboard & Multi-Account Risk Management Server.
Handles:
- User Authentication (arief.setiabudi2010@gmail.com / P@ssw0rd!)
- Multi-Account MT5 Management
- Dynamic Risk Profile Assignment (Prop Firm, Sweet Spot, Aggressive, YOLO)
- Live Static File Serving (Canvas Visualizer, Charts, Reports)
- Hot-reloading of configs/accounts.yaml
"""

import sys
import os
import socket
import json
import yaml
import time
import secrets
import hashlib
from pathlib import Path
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_ROOT / "configs"
ACCOUNTS_CONFIG_PATH = CONFIGS_DIR / "accounts.yaml"
REPORTS_DIR = PROJECT_ROOT / "reports"

# In-memory active sessions: token -> {email, expires_at}
ACTIVE_SESSIONS = {}


def load_accounts_config():
    if not ACCOUNTS_CONFIG_PATH.exists():
        return {"auth": {}, "risk_profiles": {}, "accounts": {}, "default_profile": "sweet_spot"}
    with open(ACCOUNTS_CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_accounts_config(cfg):
    with open(ACCOUNTS_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def verify_login(email, password):
    cfg = load_accounts_config()
    auth = cfg.get("auth", {})
    admin_email = auth.get("admin_email", "")
    target_hash = auth.get("password_hash", "")

    if email.strip().lower() != admin_email.strip().lower():
        return False

    computed_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return computed_hash == target_hash


def create_session(email):
    token = secrets.token_hex(24)
    ACTIVE_SESSIONS[token] = {
        "email": email,
        "expires_at": time.time() + (24 * 3600)  # 24 hours
    }
    return token


def is_authenticated(token):
    if not token:
        return False
    session = ACTIVE_SESSIONS.get(token)
    if not session:
        return False
    if time.time() > session["expires_at"]:
        del ACTIVE_SESSIONS[token]
        return False
    return True


class InstitutionalDashboardHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _get_token_from_header(self):
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        # Also check cookie
        cookie_header = self.headers.get("Cookie", "")
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("session_token="):
                return part.split("=", 1)[1].strip()
        return None

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API Endpoints
        if path == "/api/status":
            token = self._get_token_from_header()
            if not is_authenticated(token):
                return self._send_json({"error": "Unauthorized"}, 401)

            cfg = load_accounts_config()
            return self._send_json({
                "status": "online",
                "timestamp": datetime.now().isoformat(),
                "bridge_status": "listening",
                "total_accounts": len(cfg.get("accounts", {})),
                "profiles": cfg.get("risk_profiles", {})
            })

        elif path == "/api/accounts":
            token = self._get_token_from_header()
            if not is_authenticated(token):
                return self._send_json({"error": "Unauthorized"}, 401)

            cfg = load_accounts_config()
            return self._send_json({
                "accounts": cfg.get("accounts", {}),
                "profiles": cfg.get("risk_profiles", {}),
                "default_profile": cfg.get("default_profile", "sweet_spot")
            })

        elif path == "/api/profiles":
            cfg = load_accounts_config()
            return self._send_json({
                "profiles": cfg.get("risk_profiles", {})
            })

        elif path == "/api/portfolios":
            port_file = REPORTS_DIR / "four_risk_profiles_comparison.json"
            if port_file.exists():
                with open(port_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._send_json(data)
            return self._send_json({"error": "Portfolio data not found"}, 404)

        # 2. Static File Serving (Dashboard, Visualizer, Reports)
        if path in ("/", "/index.html", "/dashboard"):
            filepath = REPORTS_DIR / "index.html"
        else:
            rel = path.lstrip("/")
            filepath = REPORTS_DIR / rel

        if filepath.exists() and filepath.is_file():
            # Determine content type
            ext = filepath.suffix.lower()
            ct = "text/plain"
            if ext == ".html": ct = "text/html"
            elif ext == ".js": ct = "application/javascript"
            elif ext == ".css": ct = "text/css"
            elif ext == ".json": ct = "application/json"
            elif ext in (".png", ".jpg", ".jpeg"): ct = f"image/{ext[1:]}"

            try:
                with open(filepath, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                self.send_error(500, f"Error reading file: {e}")
                return
        else:
            self.send_error(404, "File Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Read JSON body
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length)
        try:
            body = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            body = {}

        # 1. Login Endpoint
        if path == "/api/login":
            email = body.get("email", "")
            password = body.get("password", "")
            if verify_login(email, password):
                token = create_session(email)
                return self._send_json({
                    "success": True,
                    "token": token,
                    "email": email,
                    "expires_in": 86400,
                    "message": "Login successful"
                })
            else:
                return self._send_json({
                    "success": False,
                    "error": "Email atau password salah. Silakan coba lagi."
                }, 401)

        # Require auth for all other POST endpoints
        token = self._get_token_from_header()
        if not is_authenticated(token):
            return self._send_json({"error": "Unauthorized"}, 401)

        # 2. Update Risk Profile for Account
        if path == "/api/account/profile":
            account_id = str(body.get("account_id", "")).strip()
            new_profile = body.get("profile", "").strip()

            cfg = load_accounts_config()
            profiles = cfg.get("risk_profiles", {})
            if new_profile not in profiles:
                return self._send_json({"error": f"Invalid profile: {new_profile}"}, 400)

            accounts = cfg.get("accounts", {})
            if account_id in accounts:
                accounts[account_id]["profile"] = new_profile
                accounts[account_id]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                accounts[account_id] = {
                    "account_id": account_id,
                    "label": f"MT5 Account {account_id}",
                    "broker": "Auto-Registered",
                    "profile": new_profile,
                    "active": True,
                    "balance": 10000.0,
                    "equity": 10000.0,
                    "currency": "USD",
                    "notes": "Added via Dashboard",
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }

            cfg["accounts"] = accounts
            save_accounts_config(cfg)
            return self._send_json({
                "success": True,
                "account_id": account_id,
                "profile": new_profile,
                "profile_details": profiles[new_profile],
                "message": f"Akun {account_id} berhasil diubah ke profil {profiles[new_profile]['name']}!"
            })

        # 3. Add or Edit Account
        elif path == "/api/account/save":
            account_id = str(body.get("account_id", "")).strip()
            if not account_id:
                return self._send_json({"error": "account_id is required"}, 400)

            profile = body.get("profile", "sweet_spot")
            label = body.get("label", f"Account {account_id}")
            broker = body.get("broker", "Generic-MT5")
            notes = body.get("notes", "")

            cfg = load_accounts_config()
            accounts = cfg.get("accounts", {})
            acc = accounts.get(account_id, {})
            acc.update({
                "account_id": account_id,
                "label": label,
                "broker": broker,
                "profile": profile,
                "notes": notes,
                "active": True,
                "balance": acc.get("balance", 10000.0),
                "equity": acc.get("equity", 10000.0),
                "currency": acc.get("currency", "USD"),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            accounts[account_id] = acc
            cfg["accounts"] = accounts
            save_accounts_config(cfg)

            return self._send_json({
                "success": True,
                "account": acc,
                "message": f"Akun {account_id} ({label}) berhasil disimpan!"
            })

        # 4. Delete Account
        elif path == "/api/account/delete":
            account_id = str(body.get("account_id", "")).strip()
            cfg = load_accounts_config()
            accounts = cfg.get("accounts", {})
            if account_id in accounts:
                del accounts[account_id]
                cfg["accounts"] = accounts
                save_accounts_config(cfg)
                return self._send_json({"success": True, "message": f"Akun {account_id} dihapus."})
            return self._send_json({"error": "Account not found"}, 404)

        # 5. Logout Endpoint
        elif path == "/api/logout":
            if token in ACTIVE_SESSIONS:
                del ACTIVE_SESSIONS[token]
            return self._send_json({"success": True, "message": "Logged out"})

        return self._send_json({"error": "Unknown POST endpoint"}, 404)


class DualStackServer(ThreadingHTTPServer):
    """
    Dual-stack HTTP server that listens on both IPv4 (127.0.0.1 / 0.0.0.0)
    and IPv6 (::1 / ::) simultaneously.
    This resolves the common ngrok issue on macOS: 'dial tcp [::1]:8888: connection refused'.
    """
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def run_server(port=8888):
    try:
        httpd = DualStackServer(("::", port), InstitutionalDashboardHandler)
        listen_desc = f"http://0.0.0.0:{port} (Dual-Stack IPv4 + IPv6)"
    except Exception as e:
        # Fallback to standard IPv4 ThreadingHTTPServer if IPv6 dual-stack is not permitted
        httpd = ThreadingHTTPServer(("0.0.0.0", port), InstitutionalDashboardHandler)
        listen_desc = f"http://0.0.0.0:{port} (IPv4 Only)"

    print("=" * 80)
    print(f"🚀 Institutional Dashboard Server running on {listen_desc}")
    print(f"🔑 Admin Login: arief.setiabudi2010@gmail.com")
    print(f"📁 Managing config: {ACCOUNTS_CONFIG_PATH.resolve()}")
    print("=" * 80)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    run_server(port)
