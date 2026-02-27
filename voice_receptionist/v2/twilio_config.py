"""
twilio_config.py — Symphony Smart Homes Voice Receptionist
Complete Twilio configuration and webhook management for Bob the Conductor.

Covers:
  - TwiML application setup and management
  - Webhook endpoint routing
  - Phone number provisioning
  - Recording settings (compliance, storage)
  - Transcription pipeline
  - SMS follow-up after calls
  - Status callback handling
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

logger = logging.getLogger(__name__)

# ─── Environment Variables ──────────────────────────────────────────────────────────

ACCOUNT_SID   = os.getenv("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
PHONE_NUMBER  = os.getenv("TWILIO_PHONE_NUMBER", "")        # E.164 format
TWIML_APP_SID = os.getenv("TWILIO_TWIML_APP_SID", "")      # Optional: pre-created TwiML app
SERVER_URL    = os.getenv("SERVER_BASE_URL", "https://your-server.ngrok.io")  # Webhook base URL

# Recording / transcription
RECORDING_ENABLED     = os.getenv("RECORDING_ENABLED", "true").lower() == "true"
TRANSCRIPTION_ENABLED = os.getenv("TRANSCRIPTION_ENABLED", "true").lower() == "true"
RECORDING_STORAGE     = os.getenv("RECORDING_STORAGE", "twilio")   # 'twilio' | 's3'
S3_RECORDINGS_BUCKET  = os.getenv("S3_RECORDINGS_BUCKET", "")


# ─── Twilio Client ──────────────────────────────────────────────────────────────

def get_twilio_client() -> Client:
    """Return an authenticated Twilio REST client."""
    if not ACCOUNT_SID or not AUTH_TOKEN:
        raise EnvironmentError(
            "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set."
        )
    return Client(ACCOUNT_SID, AUTH_TOKEN)


# ─── TwiML App Management ──────────────────────────────────────────────────────

def get_or_create_twiml_app(
    app_name: str = "Symphony Voice Receptionist",
) -> str:
    """
    Retrieve the TwiML app SID, or create a new one if it doesn't exist.

    Returns:
        TwiML App SID string.
    """
    client = get_twilio_client()

    # Check if a SID was pre-configured
    if TWIML_APP_SID:
        try:
            app = client.applications(TWIML_APP_SID).fetch()
            logger.info(f"Using existing TwiML app: {app.sid}")
            return app.sid
        except Exception as e:
            logger.warning(f"Pre-configured app SID not found ({e}), creating new app.")

    # Search for existing app by friendly name
    apps = client.applications.list(friendly_name=app_name)
    if apps:
        logger.info(f"Found existing TwiML app '{app_name}': {apps[0].sid}")
        return apps[0].sid

    # Create a new app
    app = client.applications.create(
        friendly_name=app_name,
        voice_url=f"{SERVER_URL}/voice/incoming",
        voice_method="POST",
        voice_fallback_url=f"{SERVER_URL}/voice/fallback",
        voice_fallback_method="POST",
        status_callback=f"{SERVER_URL}/voice/status",
        status_callback_method="POST",
    )
    logger.info(f"Created new TwiML app '{app_name}': {app.sid}")
    return app.sid


def update_twiml_app_urls(app_sid: str) -> dict:
    """
    Update webhook URLs on an existing TwiML app.
    Useful when the server URL changes (e.g., new ngrok tunnel).
    """
    client = get_twilio_client()
    app = client.applications(app_sid).update(
        voice_url=f"{SERVER_URL}/voice/incoming",
        voice_method="POST",
        voice_fallback_url=f"{SERVER_URL}/voice/fallback",
        voice_fallback_method="POST",
        status_callback=f"{SERVER_URL}/voice/status",
        status_callback_method="POST",
    )
    logger.info(f"Updated TwiML app {app_sid} URLs")
    return {
        "sid": app.sid,
        "voice_url": app.voice_url,
        "status_callback": app.status_callback,
    }


# ─── Phone Number Management ───────────────────────────────────────────────────

def configure_phone_number(
    phone_number: str,
    app_sid: str,
) -> dict:
    """
    Bind a Twilio phone number to the TwiML application.

    Args:
        phone_number: E.164 format (e.g., '+13035551234')
        app_sid: TwiML App SID

    Returns:
        dict with number SID and configuration.
    """
    client = get_twilio_client()

    # Find the number in our account
    numbers = client.incoming_phone_numbers.list(phone_number=phone_number)
    if not numbers:
        raise ValueError(f"Phone number {phone_number} not found in Twilio account.")

    number = numbers[0]
    updated = client.incoming_phone_numbers(number.sid).update(
        voice_application_sid=app_sid,
        sms_url=f"{SERVER_URL}/sms/incoming",
        sms_method="POST",
    )

    logger.info(f"Configured {phone_number} → TwiML app {app_sid}")
    return {
        "sid": updated.sid,
        "phone_number": updated.phone_number,
        "voice_application_sid": updated.voice_application_sid,
        "sms_url": updated.sms_url,
    }


def list_phone_numbers() -> list[dict]:
    """Return all phone numbers in the Twilio account."""
    client = get_twilio_client()
    numbers = client.incoming_phone_numbers.list()
    return [
        {
            "sid": n.sid,
            "phone_number": n.phone_number,
            "friendly_name": n.friendly_name,
            "voice_url": n.voice_url,
            "voice_application_sid": n.voice_application_sid,
        }
        for n in numbers
    ]


def purchase_phone_number(
    area_code: str = "303",
    country_code: str = "US",
) -> dict:
    """
    Purchase a new phone number with the given area code.

    Returns:
        dict with new number details.
    """
    client = get_twilio_client()

    available = client.available_phone_numbers(country_code).local.list(
        area_code=area_code,
        voice_enabled=True,
        sms_enabled=True,
        limit=1,
    )
    if not available:
        raise RuntimeError(f"No numbers available in area code {area_code}.")

    purchased = client.incoming_phone_numbers.create(
        phone_number=available[0].phone_number,
    )
    logger.info(f"Purchased new number: {purchased.phone_number}")
    return {
        "sid": purchased.sid,
        "phone_number": purchased.phone_number,
    }


# ─── TwiML Response Builders ────────────────────────────────────────────────────

def build_stream_twiml(
    websocket_url: str,
    stream_name: str = "BobStream",
    recording: bool = True,
) -> str:
    """
    Build a TwiML response that connects the call to an OpenAI Realtime WebSocket.

    Args:
        websocket_url: Full WSS URL for the OpenAI Realtime stream.
        stream_name:   Friendly name for the stream (for logging).
        recording:     Whether to record the call.

    Returns:
        TwiML XML string.
    """
    response = VoiceResponse()

    if recording and RECORDING_ENABLED:
        response.record(
            action=f"{SERVER_URL}/voice/voicemail-done",
            method="POST",
            max_length=3600,
            play_beep=False,
            recording_status_callback=f"{SERVER_URL}/voice/recording-status",
            recording_status_callback_method="POST",
            transcribe=TRANSCRIPTION_ENABLED,
            transcribe_callback=f"{SERVER_URL}/voice/transcription" if TRANSCRIPTION_ENABLED else None,
        )

    connect = Connect()
    stream = Stream(url=websocket_url, name=stream_name)
    stream.parameter(name="callSid", value="{{CallSid}}")
    stream.parameter(name="from", value="{{From}}")
    stream.parameter(name="to", value="{{To}}")
    connect.append(stream)
    response.append(connect)

    return str(response)


def build_fallback_twiml(message: str = None) -> str:
    """
    Build a simple TwiML response for fallback (when the WebSocket fails).
    """
    response = VoiceResponse()
    text = message or (
        "Thank you for calling Symphony Smart Homes. "
        "We're experiencing a technical issue. "
        "Please call back in a few minutes or leave a message after the tone."
    )
    response.say(text, voice="Polly.Joanna", language="en-US")
    response.record(
        action=f"{SERVER_URL}/voice/voicemail-done",
        method="POST",
        max_length=120,
        play_beep=True,
        transcribe=True,
        transcribe_callback=f"{SERVER_URL}/voice/transcription",
    )
    return str(response)


def build_voicemail_twiml(prompt: str = None) -> str:
    """TwiML for standard voicemail drop."""
    response = VoiceResponse()
    text = prompt or (
        "You've reached Symphony Smart Homes. "
        "We're unable to take your call right now. "
        "Please leave your name, number, and a brief message, "
        "and we'll return your call on the next business day."
    )
    response.say(text, voice="Polly.Joanna", language="en-US")
    response.record(
        action=f"{SERVER_URL}/voice/voicemail-done",
        method="POST",
        max_length=120,
        play_beep=True,
        transcribe=True,
        transcribe_callback=f"{SERVER_URL}/voice/transcription",
    )
    return str(response)


# ─── Webhook Handlers ────────────────────────────────────────────────────────────

def handle_incoming_call(
    from_number: str,
    to_number: str,
    call_sid: str,
    websocket_base_url: str,
) -> str:
    """
    Entry point for the /voice/incoming webhook.

    Builds the TwiML that connects the call to the OpenAI Realtime stream.

    Args:
        from_number:        Caller's phone number (E.164).
        to_number:          Your Twilio number (E.164).
        call_sid:           Twilio CallSid for this call.
        websocket_base_url: Base WSS URL for the OpenAI Realtime endpoint.

    Returns:
        TwiML XML string.
    """
    logger.info(f"Incoming call: {from_number} → {to_number} (SID: {call_sid})")

    # Construct the full WebSocket URL with call metadata
    ws_url = f"{websocket_base_url}?callSid={call_sid}&from={from_number}"

    try:
        twiml = build_stream_twiml(
            websocket_url=ws_url,
            stream_name=f"Bob_{call_sid[-6:]}",
            recording=RECORDING_ENABLED,
        )
        return twiml
    except Exception as e:
        logger.error(f"Error building stream TwiML for {call_sid}: {e}")
        return build_fallback_twiml()


def handle_status_callback(
    call_sid: str,
    call_status: str,
    from_number: str,
    to_number: str,
    call_duration: Optional[str] = None,
) -> dict:
    """
    Process the status callback from Twilio after a call ends.

    Args:
        call_sid:      Twilio CallSid.
        call_status:   Final status (completed, no-answer, busy, failed).
        from_number:   Caller's number.
        to_number:     Our number.
        call_duration: Duration in seconds (if available).

    Returns:
        dict with logged status details.
    """
    duration = int(call_duration) if call_duration else 0
    logger.info(
        f"Call status: {call_sid} | {call_status} | "
        f"{from_number} → {to_number} | {duration}s"
    )

    return {
        "call_sid": call_sid,
        "status": call_status,
        "from": from_number,
        "to": to_number,
        "duration_seconds": duration,
        "logged_at": datetime.utcnow().isoformat() + "Z",
    }


def handle_voicemail_done(
    call_sid: str,
    recording_url: str,
    recording_duration: str,
) -> dict:
    """
    Handle the action callback after a voicemail recording completes.

    Returns:
        dict with recording details for storage.
    """
    logger.info(f"Voicemail recorded for {call_sid}: {recording_url} ({recording_duration}s)")
    return {
        "call_sid": call_sid,
        "recording_url": recording_url,
        "duration": int(recording_duration) if recording_duration else 0,
        "recorded_at": datetime.utcnow().isoformat() + "Z",
    }


def handle_transcription_callback(
    call_sid: str,
    transcription_text: str,
    transcription_status: str,
    recording_url: str,
) -> dict:
    """
    Handle the transcription callback from Twilio.

    Returns:
        dict with transcription data for CRM storage.
    """
    logger.info(
        f"Transcription for {call_sid}: status={transcription_status}, "
        f"{len(transcription_text)} chars"
    )
    return {
        "call_sid": call_sid,
        "transcription_text": transcription_text,
        "transcription_status": transcription_status,
        "recording_url": recording_url,
        "received_at": datetime.utcnow().isoformat() + "Z",
    }


def handle_recording_status(
    call_sid: str,
    recording_sid: str,
    recording_status: str,
    recording_url: str,
    recording_duration: str,
) -> dict:
    """
    Handle the recording status callback (fires when recording is ready).
    """
    logger.info(f"Recording ready: {recording_sid} for call {call_sid}")
    return {
        "call_sid": call_sid,
        "recording_sid": recording_sid,
        "status": recording_status,
        "url": recording_url,
        "duration": int(recording_duration) if recording_duration else 0,
        "ready_at": datetime.utcnow().isoformat() + "Z",
    }


def handle_incoming_sms(
    from_number: str,
    body: str,
    message_sid: str,
) -> str:
    """
    Handle an inbound SMS. Returns TwiML (MessagingResponse) XML.
    Basic implementation — logs and optionally auto-replies.
    """
    from twilio.twiml.messaging_response import MessagingResponse

    logger.info(f"Inbound SMS from {from_number}: {body[:100]}")

    # Detect keywords for follow-up actions
    from call_routing import detect_intent, score_emergency  # noqa: F401

    response = MessagingResponse()

    # Auto-reply for common keywords
    body_lower = body.lower().strip()
    if body_lower in ("stop", "unsubscribe"):
        pass  # Twilio handles opt-out automatically
    elif body_lower in ("help", "info", "info?"):
        response.message(
            "Symphony Smart Homes: For support, call us at our main line. "
            "Reply STOP to opt out."
        )
    else:
        # Log for manual follow-up; no auto-reply for general inquiries
        response.message(
            "Thanks for your message! A member of the Symphony team will follow up shortly."
        )

    return str(response)


# ─── Security ──────────────────────────────────────────────────────────────────

def validate_twilio_signature(
    request_url: str,
    post_params: dict,
    signature: str,
) -> bool:
    """
    Validate that a webhook request genuinely came from Twilio.

    Args:
        request_url:  Full URL the webhook was sent to.
        post_params:  POST body parameters as a dict.
        signature:    Value of the X-Twilio-Signature header.

    Returns:
        True if valid, False otherwise.
    """
    from twilio.request_validator import RequestValidator
    validator = RequestValidator(AUTH_TOKEN)
    return validator.validate(request_url, post_params, signature)


# ─── Recording Settings ──────────────────────────────────────────────────────────

def get_recording_settings() -> dict:
    """Return current recording configuration as a dict."""
    return {
        "recording_enabled": RECORDING_ENABLED,
        "transcription_enabled": TRANSCRIPTION_ENABLED,
        "storage": RECORDING_STORAGE,
        "s3_bucket": S3_RECORDINGS_BUCKET if RECORDING_STORAGE == "s3" else None,
    }


# ─── Setup / Health Check ────────────────────────────────────────────────────────

def run_setup_check() -> dict:
    """
    Validate that the Twilio environment is fully configured.
    Returns a dict of check results — suitable for a /health endpoint.
    """
    checks: dict = {}

    # Credentials check
    checks["account_sid_set"] = bool(ACCOUNT_SID)
    checks["auth_token_set"] = bool(AUTH_TOKEN)
    checks["phone_number_set"] = bool(PHONE_NUMBER)
    checks["server_url_set"] = SERVER_URL != "https://your-server.ngrok.io"

    if ACCOUNT_SID and AUTH_TOKEN:
        try:
            client = get_twilio_client()
            account = client.api.accounts(ACCOUNT_SID).fetch()
            checks["account_active"] = account.status == "active"
            checks["account_name"] = account.friendly_name
        except Exception as exc:
            checks["account_active"] = False
            checks["account_error"] = str(exc)

        if PHONE_NUMBER:
            try:
                numbers = client.incoming_phone_numbers.list(phone_number=PHONE_NUMBER)
                checks["phone_number_exists"] = bool(numbers)
            except Exception as exc:
                checks["phone_number_exists"] = False
                checks["phone_number_error"]  = str(exc)

    checks["recording_configured"] = get_recording_settings()
    checks["timestamp"]            = datetime.utcnow().isoformat() + "Z"

    return checks


if __name__ == "__main__":
    """Run setup check when executed directly."""
    import json
    results = run_setup_check()
    print(json.dumps(results, indent=2))
