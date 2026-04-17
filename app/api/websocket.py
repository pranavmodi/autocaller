"""WebSocket handlers for real-time voice and dashboard updates."""
import asyncio
import json
import base64
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.call_orchestrator import get_orchestrator
from app.services.dispatcher import get_dispatcher
from app.providers import get_queue_provider, get_call_log_provider
from app.models import CallOutcome

logger = logging.getLogger(__name__)

router = APIRouter()


# Connected dashboard clients for broadcasting updates
dashboard_clients: Set[WebSocket] = set()

# Connected voice clients (for web call mode)
voice_clients: Set[WebSocket] = set()


async def broadcast_to_dashboards(message: dict):
    """Broadcast a message to all connected dashboard clients."""
    if not dashboard_clients:
        return

    message_str = json.dumps(message)
    disconnected = set()

    for client in dashboard_clients:
        try:
            await client.send_text(message_str)
        except Exception:
            disconnected.add(client)

    # Remove disconnected clients
    dashboard_clients.difference_update(disconnected)


@router.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """WebSocket endpoint for dashboard real-time updates."""
    await websocket.accept()
    dashboard_clients.add(websocket)

    try:
        # Send initial state
        queue_provider = get_queue_provider()
        call_log_provider = get_call_log_provider()

        active_call = await call_log_provider.get_active_call()
        statistics = await call_log_provider.get_statistics()

        await websocket.send_json({
            "type": "initial_state",
            "queue_state": queue_provider.get_state().to_dict(),
            "active_call": active_call.to_dict() if active_call else None,
            "statistics": statistics,
        })

        # Keep connection alive and handle any incoming messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)

                # Handle ping/pong for keepalive
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    finally:
        dashboard_clients.discard(websocket)


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """WebSocket endpoint for voice call audio streaming."""
    await websocket.accept()
    voice_clients.add(websocket)

    orchestrator = get_orchestrator()
    audio_buffer = bytearray()

    # Set up callbacks to forward to WebSocket
    async def on_call_started(call):
        get_dispatcher().notify_call_started(call.patient_id)
        try:
            await websocket.send_json({
                "type": "call_started",
                "call": call.to_dict(),
            })
        except Exception:
            logger.warning("Voice WS send failed on call_started (client may have disconnected)")
        await broadcast_to_dashboards({
            "type": "call_started",
            "call": call.to_dict(),
        })

    async def on_call_ended(call):
        get_dispatcher().notify_call_ended()
        try:
            await websocket.send_json({
                "type": "call_ended",
                "call": call.to_dict(),
            })
        except Exception:
            logger.warning("Voice WS send failed on call_ended (client may have disconnected)")
        await broadcast_to_dashboards({
            "type": "call_ended",
            "call": call.to_dict(),
        })

    async def on_transcript_update(speaker, text):
        try:
            await websocket.send_json({
                "type": "transcript",
                "speaker": speaker,
                "text": text,
            })
        except Exception:
            pass
        # Only broadcast complete transcripts to dashboard
        if speaker in ("ai", "patient"):
            await broadcast_to_dashboards({
                "type": "transcript",
                "speaker": speaker,
                "text": text,
            })

    async def on_audio_output(audio_data):
        # Send audio as base64
        try:
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")
            await websocket.send_json({
                "type": "audio",
                "data": audio_b64,
            })
        except Exception:
            pass

    async def on_status_update(status):
        try:
            await websocket.send_json({
                "type": "status",
                "status": status,
            })
        except Exception:
            pass
        await broadcast_to_dashboards({
            "type": "status_update",
            "status": status,
        })

    async def on_error(error):
        try:
            await websocket.send_json({
                "type": "error",
                "message": error,
            })
        except Exception:
            pass

    # Attach callbacks
    orchestrator.on_call_started = on_call_started
    orchestrator.on_call_ended = on_call_ended
    orchestrator.on_transcript_update = on_transcript_update
    orchestrator.on_audio_output = on_audio_output
    orchestrator.on_status_update = on_status_update
    orchestrator.on_error = on_error

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "start_call":
                    patient_id = data.get("patient_id")
                    from app.providers import get_settings_provider
                    settings_provider = get_settings_provider()
                    settings = await settings_provider.get_settings()
                    call_mode = settings.call_mode or "web"
                    print(f"[WS] start_call: call_mode={call_mode} (from DB)")
                    if patient_id:
                        await orchestrator.start_call(patient_id, call_mode=call_mode)

                elif msg_type == "end_call":
                    outcome_str = data.get("outcome", "completed")
                    try:
                        outcome = CallOutcome(outcome_str)
                    except ValueError:
                        outcome = CallOutcome.COMPLETED
                    await orchestrator.end_call(outcome)

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

            elif "bytes" in message:
                # Binary audio data from browser
                audio_data = message["bytes"]
                if not hasattr(voice_websocket, '_audio_received_logged'):
                    voice_websocket._audio_received_logged = True
                    print(f"[WebSocket] Received audio from browser: {len(audio_data)} bytes")
                await orchestrator.send_audio(audio_data)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        # Track disconnect
        voice_clients.discard(websocket)
        # Clean up callbacks
        orchestrator.on_call_started = None
        orchestrator.on_call_ended = None
        orchestrator.on_transcript_update = None
        orchestrator.on_audio_output = None
        orchestrator.on_status_update = None
        orchestrator.on_error = None

        # End any active call
        if orchestrator.is_call_active:
            await orchestrator.end_call(CallOutcome.FAILED)


@router.websocket("/ws/twilio-media/{stream_id}")
async def twilio_media_websocket(websocket: WebSocket, stream_id: str):
    """WebSocket endpoint for Twilio media streams.

    Twilio connects here after our TwiML <Connect><Stream> instruction.
    We bridge the audio to/from the OpenAI RealtimeVoiceService.
    """
    from app.services.twilio_voice_service import pop_bridge

    await websocket.accept()
    logger.info(f"Twilio media stream connected: stream_id={stream_id}")

    bridge = pop_bridge(stream_id)
    if not bridge:
        logger.error(f"No pending bridge for stream_id={stream_id}")
        await websocket.close(code=4000, reason="No pending bridge")
        return

    disconnect_reason = "unknown"
    try:
        await bridge.handle_twilio_ws(websocket)
        disconnect_reason = "stream_ended_normally"
    except WebSocketDisconnect as e:
        disconnect_reason = f"websocket_disconnect (code={e.code})"
        print(f"[TwilioMedia] Stream disconnected: stream_id={stream_id}, code={e.code}")
    except Exception as e:
        disconnect_reason = f"error: {type(e).__name__}: {e}"
        print(f"[TwilioMedia] Stream error: stream_id={stream_id}, {disconnect_reason}")
    finally:
        from app.services.call_orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        if orchestrator.is_call_active:
            print(f"[TwilioMedia] Stream closed while call active — reason={disconnect_reason}, stream_id={stream_id}")
            await orchestrator.end_call(CallOutcome.DISCONNECTED)
        else:
            print(f"[TwilioMedia] Stream closed (call already ended) — reason={disconnect_reason}, stream_id={stream_id}")


@router.websocket("/ws/telnyx-media/{stream_id}")
async def telnyx_media_websocket(websocket: WebSocket, stream_id: str):
    """WebSocket endpoint for Telnyx media streams.

    Telnyx connects here after our TeXML <Connect><Stream> instruction.
    Parallel to the Twilio handler above; uses TelnyxMediaBridge which
    understands Telnyx's slightly-different JSON frame fields.
    """
    from app.services.telnyx_voice_service import pop_bridge

    await websocket.accept()
    logger.info(f"Telnyx media stream connected: stream_id={stream_id}")

    bridge = pop_bridge(stream_id)
    if not bridge:
        logger.error(f"No pending Telnyx bridge for stream_id={stream_id}")
        await websocket.close(code=4000, reason="No pending bridge")
        return

    disconnect_reason = "unknown"
    try:
        await bridge.handle_carrier_ws(websocket)
        disconnect_reason = "stream_ended_normally"
    except WebSocketDisconnect as e:
        disconnect_reason = f"websocket_disconnect (code={e.code})"
        print(f"[TelnyxMedia] Stream disconnected: stream_id={stream_id}, code={e.code}")
    except Exception as e:
        disconnect_reason = f"error: {type(e).__name__}: {e}"
        print(f"[TelnyxMedia] Stream error: stream_id={stream_id}, {disconnect_reason}")
    finally:
        from app.services.call_orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
        if orchestrator.is_call_active:
            print(f"[TelnyxMedia] Stream closed while call active — reason={disconnect_reason}, stream_id={stream_id}")
            await orchestrator.end_call(CallOutcome.DISCONNECTED)
        else:
            print(f"[TelnyxMedia] Stream closed (call already ended) — reason={disconnect_reason}, stream_id={stream_id}")


@router.websocket("/ws/listen/{call_id}")
async def listen_websocket(websocket: WebSocket, call_id: str):
    """Listen-only stream of the current live call's audio.

    Sends 16-bit PCM little-endian mono @ 8kHz as binary frames. The browser
    decodes with AudioContext and plays through the speakers. Closes as soon
    as the call ends or a different call_id is active.
    """
    from app.services.call_orchestrator import get_orchestrator

    await websocket.accept()

    orchestrator = get_orchestrator()
    current_call = orchestrator.current_call
    bridge = orchestrator._twilio_bridge  # type: ignore[attr-defined]

    if not current_call or not bridge or current_call.call_id != call_id:
        await websocket.send_json({
            "type": "error",
            "error": "no_active_call",
            "message": "No active call with that ID right now.",
        })
        await websocket.close(code=4004, reason="no active call")
        return

    await websocket.send_json({
        "type": "ready",
        "call_id": call_id,
        "sample_rate": 8000,
        "encoding": "pcm_s16le",
        "channels": 1,
        "note": "Binary frames follow. Each frame is raw PCM16 little-endian mono @ 8kHz.",
    })

    bridge.add_listener(websocket)
    logger.info(f"Listener attached to call {call_id} (total={bridge.listener_count})")

    try:
        # Keep the connection open. We don't expect client messages, but
        # receive() lets us detect disconnects promptly.
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # Ignore whatever the client sends (keepalives allowed).
                if msg == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Idle. Send a text ping so the socket stays warm.
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"Listener error on call {call_id}: {type(e).__name__}: {e}")
    finally:
        bridge.remove_listener(websocket)
        logger.info(f"Listener detached from call {call_id} (remaining={bridge.listener_count})")
