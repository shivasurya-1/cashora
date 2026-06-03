"""
One-shot FCM push test script.
Usage:
    python test_push.py <device_token>

The script reads Firebase credentials from the .env file the same way the
app does, so no extra configuration is needed.

Examples:
    python test_push.py  eXaMpLeTokEn123...
"""

import asyncio
import os
import sys

# ── load .env before importing app config ──────────────────────────────────
from pathlib import Path

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)
else:
    print("WARNING: .env not found — make sure Firebase env vars are set manually.")

# ── resolve token from CLI arg or prompt ──────────────────────────────────
if len(sys.argv) >= 2:
    TOKEN = sys.argv[1].strip()
else:
    TOKEN = input("Paste device FCM token: ").strip()

if not TOKEN:
    print("ERROR: no token provided.")
    sys.exit(1)

# ── build Firebase app (mirrors push_service._get_firebase_app) ───────────
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
except ImportError:
    print("ERROR: firebase-admin is not installed. Run:  pip install firebase-admin")
    sys.exit(1)

FCM_ENABLED = os.getenv("FCM_ENABLED", "false").lower() in ("1", "true", "yes")
if not FCM_ENABLED:
    print("ERROR: FCM_ENABLED is not True in .env — set FCM_ENABLED=True first.")
    sys.exit(1)


def _init_app():
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    project_id    = os.getenv("FIREBASE_PROJECT_ID")
    client_email  = os.getenv("FIREBASE_CLIENT_EMAIL")
    private_key   = os.getenv("FIREBASE_PRIVATE_KEY", "").replace("\\n", "\n")

    if project_id and client_email and private_key:
        cert = {
            "type": "service_account",
            "project_id": project_id,
            "private_key": private_key,
            "client_email": client_email,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        return firebase_admin.initialize_app(credentials.Certificate(cert))

    sa_file = os.getenv("FCM_SERVICE_ACCOUNT_FILE")
    if sa_file and Path(sa_file).exists():
        return firebase_admin.initialize_app(credentials.Certificate(sa_file))

    print("ERROR: No Firebase credentials found. Provide FIREBASE_PROJECT_ID + "
          "FIREBASE_CLIENT_EMAIL + FIREBASE_PRIVATE_KEY, or FCM_SERVICE_ACCOUNT_FILE.")
    sys.exit(1)


app = _init_app()

# ── send test message ─────────────────────────────────────────────────────
message = messaging.Message(
    token=TOKEN,
    notification=messaging.Notification(
        title="Test Push ✅",
        body="Hello from Cashora backend — push is working!",
    ),
    data={
        "event_type": "expense_approved",
        "expense_id": "1",
        "request_id": "TEST-00000001",
    },
    android=messaging.AndroidConfig(
        priority="high",
        notification=messaging.AndroidNotification(
            channel_id="cashora_push_channel",
            sound="default",
            click_action="FLUTTER_NOTIFICATION_CLICK",
        ),
    ),
)

print(f"Sending to token: {TOKEN[:20]}...")
try:
    response = messaging.send(message)
    print(f"SUCCESS — message ID: {response}")
except messaging.UnregisteredError:
    print("FAILED — token is no longer registered on Firebase (device uninstalled app or token rotated).")
    sys.exit(1)
except Exception as e:
    print(f"FAILED — {type(e).__name__}: {e}")
    sys.exit(1)
