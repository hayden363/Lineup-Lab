"""
PUSH NOTIFICATIONS (iOS app) — Apple Push Notification service, HTTP/2 + token auth
====================================================================================
The iOS app registers its APNs device token (POST /api/push/register); this module sends to it.

Auth is Apple's token-based scheme: one .p8 "APNs auth key" from the developer account signs a short-lived ES256 JWT
(cached ~50 minutes; Apple refuses tokens older than an hour or refreshed more than every 20 minutes). Configure with
environment variables, nothing in git:
    APNS_KEY_ID        the key's 10-character ID
    APNS_TEAM_ID       the developer team ID
    APNS_PRIVATE_KEY   the .p8 file's contents (BEGIN/END lines included; literal "\\n" sequences are accepted)
    APNS_TOPIC         the app's bundle ID (default com.haydenjohnstonwoods.lineuplab)
Unset = push is off (every call is a quiet no-op), so the server runs exactly as before.

What is sent (version 1): the daily "today's Daily Drive is live" reminder, once a day at REMINDER_HOUR_ET, only to
devices that keep it on and only if that account hasn't played today. Lineup-alert pushes are the next step.
"""
import datetime as dt
import os
import threading
import time

import jwt

APNS_KEY_ID = os.environ.get("APNS_KEY_ID")
APNS_TEAM_ID = os.environ.get("APNS_TEAM_ID")
APNS_PRIVATE_KEY = (os.environ.get("APNS_PRIVATE_KEY") or "").replace("\\n", "\n") or None
APNS_TOPIC = os.environ.get("APNS_TOPIC", "com.haydenjohnstonwoods.lineuplab")
HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}
REMINDER_HOUR_ET = 11            # 11am Eastern: after the 12am rollover, before most people's lunch
TOKEN_TTL = 50 * 60

_token = {"value": None, "at": 0.0}
_lock = threading.Lock()


def configured():
    return bool(APNS_KEY_ID and APNS_TEAM_ID and APNS_PRIVATE_KEY)


def _auth_token(now=None):
    now = now or time.time()
    with _lock:
        if _token["value"] and now - _token["at"] < TOKEN_TTL:
            return _token["value"]
        tok = jwt.encode({"iss": APNS_TEAM_ID, "iat": int(now)}, APNS_PRIVATE_KEY, algorithm="ES256",
                         headers={"kid": APNS_KEY_ID})
        _token.update(value=tok, at=now)
        return tok


def payload(title, body, url=None, thread=None):
    aps = {"alert": {"title": title, "body": body}, "sound": "default"}
    if thread:
        aps["thread-id"] = thread
    out = {"aps": aps}
    if url:
        out["url"] = url                 # the app opens this path in the right tab when the notification is tapped
    return out


def send(device, body_json, client=None, collapse_id=None):
    """Send one notification. device = {token, environment}. Returns "ok", "gone" (token no longer valid: caller should
    delete it) or "error". Never raises."""
    if not configured():
        return "error"
    import httpx
    url = f"{HOSTS.get(device.get('environment'), HOSTS['production'])}/3/device/{device['token']}"
    headers = {"authorization": f"bearer {_auth_token()}", "apns-topic": APNS_TOPIC, "apns-push-type": "alert",
               "apns-priority": "10"}
    if collapse_id:
        headers["apns-collapse-id"] = collapse_id
    own = client is None
    try:
        client = client or httpx.Client(http2=True, timeout=10)
        r = client.post(url, json=body_json, headers=headers)
        if r.status_code == 200:
            return "ok"
        reason = ""
        try:
            reason = r.json().get("reason", "")
        except Exception:
            pass
        if r.status_code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
            return "gone"
        print(f"[push] APNs {r.status_code} {reason}")
        return "error"
    except Exception as e:
        print(f"[push] send failed: {type(e).__name__}")
        return "error"
    finally:
        if own and client is not None:
            client.close()


# ---------------------------------------------------------------- the daily Daily Drive reminder ----
def reminder_targets(devices, played_user_ids):
    """Devices to remind: every reminder device whose account hasn't played today."""
    return [d for d in devices if d.get("user_id") not in played_user_ids]


def send_drive_reminder(today_iso, db):
    """Remind everyone who hasn't played `today_iso`. Returns {sent, gone, errors}."""
    out = {"sent": 0, "gone": 0, "errors": 0}
    if not configured():
        return out
    import httpx
    devices = reminder_targets(db.push_devices_for_reminder(), db.users_who_played(today_iso))
    body = payload("Today's Daily Drive is live", "7 plays, 700 yards. Keep your streak going.", url="/play",
                   thread="daily-drive")
    with httpx.Client(http2=True, timeout=10) as client:
        for d in devices:
            res = send(d, body, client=client, collapse_id=f"drive-{today_iso}")
            if res == "ok":
                out["sent"] += 1
            elif res == "gone":
                out["gone"] += 1
                try:
                    db.delete_push_device(d["token"])
                except Exception:
                    pass
            else:
                out["errors"] += 1
    return out


def seconds_until_next_reminder(now_utc=None):
    """Seconds from now to the next REMINDER_HOUR_ET:00 US Eastern."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("America/New_York")
    now = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(tz)
    nxt = now.replace(hour=REMINDER_HOUR_ET, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += dt.timedelta(days=1)
    return (nxt - now).total_seconds()


def start_reminder_loop(db, today_fn):
    """Background thread: sleeps until 11am ET, sends the reminder, repeats. Only starts when APNs is configured."""
    if not configured():
        print("[push] APNs not configured — push notifications off")
        return None

    def loop():
        while True:
            time.sleep(max(60.0, seconds_until_next_reminder()))
            try:
                day = today_fn().isoformat()
                print(f"[push] Daily Drive reminder {day}: {send_drive_reminder(day, db)}")
            except Exception as e:
                print(f"[push] reminder run failed: {type(e).__name__}: {e}")

    t = threading.Thread(target=loop, name="push-reminder", daemon=True)
    t.start()
    print(f"[push] Daily Drive reminder scheduled daily at {REMINDER_HOUR_ET}:00 ET")
    return t
