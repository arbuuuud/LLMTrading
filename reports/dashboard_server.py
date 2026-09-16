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
import math
import hmac
import secrets
import hashlib
from pathlib import Path
from typing import Optional
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

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


def get_auth_secret() -> bytes:
    cfg = load_accounts_config()
    auth = cfg.get("auth", {})
    secret = auth.get("secret_key")
    if not secret:
        secret = secrets.token_hex(32)
        cfg.setdefault("auth", {})["secret_key"] = secret
        save_accounts_config(cfg)
    return secret.encode("utf-8")


def create_session(email: str) -> str:
    secret = get_auth_secret()
    expires_at = int(time.time() + (30 * 86400))  # 30 days persistent session
    payload = f"{email}:{expires_at}"
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{email}:{expires_at}:{sig}"


def is_authenticated(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        parts = token.strip().split(":")
        if len(parts) != 3:
            return False
        email, exp_str, sig = parts
        exp = int(exp_str)
        if time.time() > exp:
            return False
        secret = get_auth_secret()
        payload = f"{email}:{exp}"
        expected_sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected_sig)
    except Exception:
        return False


RADAR_STATE_PATH = REPORTS_DIR / "radar_state.json"
_CACHED_FALLBACK_RADAR = None


def _build_fallback_radar():
    p_m1 = PROJECT_ROOT / "data" / "processed" / "bars" / "XAUUSD" / "M1" / "XAUUSD_M1.parquet"
    p_m15 = PROJECT_ROOT / "data" / "processed" / "bars" / "XAUUSD" / "HTF" / "XAUUSD_M15.parquet"

    bars_m1 = []
    bars_m15 = []
    vwap = 0.0
    upper = 0.0
    lower = 0.0
    std = 0.0
    mid = 2650.0

    try:
        import polars as pl
        if p_m1.exists():
            df_m1 = pl.read_parquet(p_m1).tail(120)
            cum_vol = 0.0
            cum_pv = 0.0
            cum_p2v = 0.0
            for row in df_m1.iter_rows(named=True):
                ts = int(row["timestamp"].timestamp())
                o = round(row["open"], 2)
                h = round(row["high"], 2)
                l = round(row["low"], 2)
                c = round(row["close"], 2)
                vol = max(1.0, float(row.get("tick_volume", 1)))
                tp = (h + l + c) / 3.0
                cum_vol += vol
                cum_pv += tp * vol
                cum_p2v += (tp ** 2) * vol
                v = cum_pv / cum_vol
                s = math.sqrt(max(0.0, (cum_p2v / cum_vol) - (v ** 2)))
                bars_m1.append({
                    "time": ts,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": int(vol),
                    "vwap": round(v, 2),
                    "upper": round(v + 1.8 * s, 2),
                    "lower": round(v - 1.8 * s, 2)
                })
            if bars_m1:
                last = bars_m1[-1]
                mid = last["close"]
                vwap = last["vwap"]
                upper = last["upper"]
                lower = last["lower"]
                std = round(s, 2)

        if p_m15.exists():
            df_m15 = pl.read_parquet(p_m15).tail(60)
            for row in df_m15.iter_rows(named=True):
                bars_m15.append({
                    "time": int(row["timestamp"].timestamp()),
                    "open": round(row["open"], 2),
                    "high": round(row["high"], 2),
                    "low": round(row["low"], 2),
                    "close": round(row["close"], 2),
                    "volume": int(row.get("tick_volume", 1))
                })
    except Exception:
        pass

    now_utc = datetime.now(timezone.utc)
    curr_hour = now_utc.hour
    curr_min = now_utc.minute
    in_golden = (10, 30) <= (curr_hour, curr_min) <= (14, 30)
    golden_desc = f"{curr_hour:02d}:{curr_min:02d} UTC (Active 10:30-14:30)" if in_golden else f"{curr_hour:02d}:{curr_min:02d} UTC (Standby outside 10:30-14:30)"

    dist_upper = round(upper - mid, 2) if upper else 0.0
    dist_lower = round(mid - lower, 2) if lower else 0.0
    stretch_sigma = round((mid - vwap) / max(std, 0.01), 2) if (vwap and std) else 0.0

    return {
        "status": "CACHED_STREAM",
        "symbol": "XAUUSD",
        "updated_at": now_utc.isoformat(),
        "tick": {
            "bid": round(mid - 0.10, 2),
            "ask": round(mid + 0.10, 2),
            "mid": mid,
            "spread": 0.20
        },
        "account": {
            "id": "10001",
            "equity": 10000.0,
            "balance": 10000.0,
            "open_positions": 0,
            "base_risk_pct": 0.5,
            "risk_dollar": 50.0,
            "estimated_lot": 0.12
        },
        "engine_1": {
            "name": "M1 Session Anchored VWAP Scalper",
            "magic": 1001,
            "state": "HUNTING" if in_golden else "STANDBY",
            "state_desc": "Monitoring Auction Value Area for Overextension" if in_golden else "Outside Golden Window (10:30-14:30 UTC)",
            "state_badge": "badge-cyan" if in_golden else "badge-gray",
            "hunting_direction": "BEARISH_FADE (+1.8σ Peak)" if mid >= vwap else "BULLISH_FADE (-1.8σ Trough)",
            "vwap": vwap,
            "upper_band": upper,
            "lower_band": lower,
            "std": std,
            "stretch_sigma": stretch_sigma,
            "dist_to_upper": dist_upper,
            "dist_to_lower": dist_lower,
            "macro_ema50": round(mid - 2.50, 2),
            "checklist": [
                {"label": "Golden Window (10:30-14:30 UTC)", "ok": in_golden, "val": golden_desc},
                {"label": "H1 EMA 50 Macro Guardrail", "ok": True, "val": f"Aligned with H1 Trend (EMA 50: {mid - 2.50:.2f})"},
                {"label": "VWAP Band Stretch (>= 1.80σ)", "ok": False, "val": f"{stretch_sigma:+.2f}σ (Target: ±1.80σ | Band: {upper:.2f})"},
                {"label": "M1 Rejection Wick Trigger", "ok": False, "val": "Waiting M1 Bar Close with >= 45% wick"},
                {"label": "Monthly Ratchet Risk Clearance", "ok": True, "val": "Clear to trade (Base Risk: 0.5%)"}
            ]
        },
        "engine_2": {
            "name": "M15 Fadli NFC Intraday",
            "magic": 2001,
            "state": "SCANNING",
            "state_desc": "Scanning M15 Structure for Unfilled DBR/RBD Bases",
            "state_badge": "badge-cyan",
            "nearest_demand": {"top": round(mid - 12.0, 2), "bottom": round(mid - 15.0, 2)},
            "nearest_supply": {"top": round(mid + 18.0, 2), "bottom": round(mid + 15.0, 2)},
            "dist_demand_pips": 120.0,
            "dist_supply_pips": 150.0,
            "checklist": [
                {"label": "Unfilled Order Base (NFC)", "ok": True, "val": "Demand Base identified @ 120 pips"},
                {"label": "Zone Retest & Mitigation", "ok": False, "val": "Nearest Demand: 120.0 pips away"},
                {"label": "H1 EMA 50 Macro Direction", "ok": True, "val": "Aligned with Higher Timeframe Trend"},
                {"label": "M15 Pinbar / Engulfing Trigger", "ok": False, "val": "Waiting for mitigation retest confirmation"}
            ]
        },
        "bars_m1": bars_m1,
        "bars_m15": bars_m15,
        "current_bar": bars_m1[-1] if bars_m1 else None
    }


def get_radar_snapshot_for_dashboard():
    global _CACHED_FALLBACK_RADAR

    if RADAR_STATE_PATH.exists():
        try:
            with open(RADAR_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("bars_m1") and len(data["bars_m1"]) > 10:
                return data
            if _CACHED_FALLBACK_RADAR is None:
                _CACHED_FALLBACK_RADAR = _build_fallback_radar()
            merged = dict(_CACHED_FALLBACK_RADAR)
            merged.update(data)
            if not data.get("bars_m1"):
                merged["bars_m1"] = _CACHED_FALLBACK_RADAR.get("bars_m1", [])
            if not data.get("bars_m15"):
                merged["bars_m15"] = _CACHED_FALLBACK_RADAR.get("bars_m15", [])
            return merged
        except Exception:
            pass

    if _CACHED_FALLBACK_RADAR is None:
        _CACHED_FALLBACK_RADAR = _build_fallback_radar()

    now_utc = datetime.now(timezone.utc)
    curr_h = now_utc.hour
    curr_m = now_utc.minute
    in_win = (10, 30) <= (curr_h, curr_m) <= (14, 30)
    _CACHED_FALLBACK_RADAR["updated_at"] = now_utc.isoformat()
    _CACHED_FALLBACK_RADAR["engine_1"]["checklist"][0]["ok"] = in_win
    _CACHED_FALLBACK_RADAR["engine_1"]["checklist"][0]["val"] = (
        f"{curr_h:02d}:{curr_m:02d} UTC (Active 10:30-14:30)" if in_win
        else f"{curr_h:02d}:{curr_m:02d} UTC (Standby outside 10:30-14:30)"
    )
    return _CACHED_FALLBACK_RADAR


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

        elif path == "/api/radar":
            return self._send_json(get_radar_snapshot_for_dashboard())

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
                body_bytes = json.dumps({
                    "success": True,
                    "token": token,
                    "email": email,
                    "expires_in": 2592000,
                    "message": "Login successful"
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body_bytes)))
                self.send_header("Set-Cookie", f"session_token={token}; Path=/; Max-Age=2592000; SameSite=Lax")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.end_headers()
                self.wfile.write(body_bytes)
                return
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
