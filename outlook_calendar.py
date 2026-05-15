import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Body, Depends, HTTPException, status

from schemas import (
    OccupiedSlot,
    OutlookReservationResponse,
    ReservationCancel,
    ReservationRecord,
    ReservationCreate,
)
from security import get_current_user
from services import (
    check_time_slot_conflict,
    get_user_by_id,
    get_user_reservation_record,
    list_all_active_reservation_records,
    list_user_reservation_records,
    save_reservation_record,
    update_reservation_record,
    update_user_microsoft_tokens,
)

load_dotenv()

router = APIRouter(prefix="/outlook", tags=["outlook"])

CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"


def _ensure_microsoft_auth(current_user: dict) -> dict:
    microsoft_auth = current_user.get("microsoft_auth") or {}
    access_token = microsoft_auth.get("access_token")
    refresh_token = microsoft_auth.get("refresh_token")

    if not access_token or not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "El usuario no ha concedido acceso suficiente a Microsoft Calendar. "
                "Debe volver a iniciar sesion y aceptar los permisos."
            ),
        )

    return microsoft_auth


def _token_is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return True

    try:
        expires_at_dt = datetime.fromisoformat(expires_at)
    except ValueError:
        return True

    if expires_at_dt.tzinfo is None:
        expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)

    return expires_at_dt <= datetime.now(timezone.utc) + timedelta(minutes=2)


async def _refresh_microsoft_token(current_user: dict) -> dict:
    microsoft_auth = _ensure_microsoft_auth(current_user)
    refresh_token = microsoft_auth["refresh_token"]

    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Faltan variables de entorno de Microsoft",
        )

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo renovar el token de Microsoft",
        )

    token_data = response.json()
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    updated_user = update_user_microsoft_tokens(
        current_user["id"],
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at.isoformat(),
        scope=token_data.get("scope", microsoft_auth.get("scope", "")),
    )

    if not updated_user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return updated_user


async def _get_valid_user(current_user: dict) -> dict:
    if _token_is_expired((current_user.get("microsoft_auth") or {}).get("expires_at")):
        refreshed_user = await _refresh_microsoft_token(current_user)
        return refreshed_user

    return current_user


def _format_graph_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    return value.isoformat(timespec="seconds")


def _build_event_payload(reservation: ReservationCreate) -> dict:
    attendees = [
        {
            "emailAddress": {"address": attendee},
            "type": "required",
        }
        for attendee in reservation.attendees
    ]

    event_payload = {
        "subject": reservation.title,
        "body": {
            "contentType": "text",
            "content": reservation.description or "Reservacion creada desde DoDate.",
        },
        "start": {
            "dateTime": _format_graph_datetime(reservation.start),
            "timeZone": reservation.timezone,
        },
        "end": {
            "dateTime": _format_graph_datetime(reservation.end),
            "timeZone": reservation.timezone,
        },
    }

    if reservation.location:
        event_payload["location"] = {"displayName": reservation.location}

    if attendees:
        event_payload["attendees"] = attendees

    return event_payload


async def _graph_request(
    current_user: dict,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
) -> tuple[dict, dict | None]:
    user_with_valid_token, response = await _graph_request_response(
        current_user,
        method,
        path,
        json_body=json_body,
    )

    _raise_graph_http_error(response)

    if response.content:
        return user_with_valid_token, response.json()

    return user_with_valid_token, None


async def _graph_request_response(
    current_user: dict,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
) -> tuple[dict, httpx.Response]:
    user_with_valid_token = await _get_valid_user(current_user)
    access_token = user_with_valid_token["microsoft_auth"]["access_token"]

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.request(
            method,
            f"{GRAPH_BASE_URL}{path}",
            json=json_body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )

    if response.status_code == 401:
        user_with_valid_token = await _refresh_microsoft_token(user_with_valid_token)
        access_token = user_with_valid_token["microsoft_auth"]["access_token"]

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(
                method,
                f"{GRAPH_BASE_URL}{path}",
                json=json_body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )

    return user_with_valid_token, response


def _raise_graph_http_error(response: httpx.Response) -> None:
    if response.status_code < 400:
        return

    raise HTTPException(
        status_code=response.status_code,
        detail={
            "message": "Microsoft Graph rechazo la operacion",
            "microsoft_response": response.text,
        },
    )


def _build_event_path(event_id: str) -> str:
    return f"/me/calendar/events/{quote(str(event_id), safe='')}"


@router.get(
    "/reservations/occupied",
    response_model=list[OccupiedSlot],
)
async def list_occupied_slots(
    current_user: dict = Depends(get_current_user),
):
    return list_all_active_reservation_records()


@router.get(
    "/reservations",
    response_model=list[ReservationRecord],
)
async def list_outlook_reservations(
    current_user: dict = Depends(get_current_user),
):
    current_user = get_user_by_id(current_user["id"]) or current_user
    return list_user_reservation_records(current_user["id"])


@router.post(
    "/reservations",
    response_model=OutlookReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_outlook_reservation(
    reservation: ReservationCreate,
    current_user: dict = Depends(get_current_user),
):
    current_user = get_user_by_id(current_user["id"]) or current_user
    _ensure_microsoft_auth(current_user)

    if reservation.location and check_time_slot_conflict(
        location=reservation.location,
        start=reservation.start.isoformat(),
        end=reservation.end.isoformat(),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El espacio ya tiene una reservacion activa en ese horario.",
        )

    reservation_id = reservation.reservation_id or str(uuid4())
    event_payload = _build_event_payload(reservation)
    current_user, created_event = await _graph_request(
        current_user,
        "POST",
        "/me/calendar/events",
        json_body=event_payload,
    )

    save_reservation_record(
        {
            "reservation_id": reservation_id,
            "user_id": current_user["id"],
            "user_email": current_user.get("email"),
            "event_id": created_event["id"],
            "web_link": created_event.get("webLink"),
            "title": reservation.title,
            "description": reservation.description,
            "start": reservation.start.isoformat(),
            "end": reservation.end.isoformat(),
            "timezone": reservation.timezone,
            "location": reservation.location,
            "attendees": reservation.attendees,
            "status": "created",
        }
    )

    return OutlookReservationResponse(
        reservation_id=reservation_id,
        event_id=created_event["id"],
        web_link=created_event.get("webLink"),
        message="Reservacion agregada al calendario de Outlook",
    )


@router.delete(
    "/reservations/{reservation_id}",
    response_model=OutlookReservationResponse,
)
async def cancel_outlook_reservation(
    reservation_id: str,
    cancellation: ReservationCancel | None = Body(default=None),
    current_user: dict = Depends(get_current_user),
):
    current_user = get_user_by_id(current_user["id"]) or current_user
    _ensure_microsoft_auth(current_user)

    stored_reservation = get_user_reservation_record(current_user["id"], reservation_id)
    if not stored_reservation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe una reservacion asociada a ese identificador",
        )

    event_path = _build_event_path(stored_reservation["event_id"])

    current_user, delete_response = await _graph_request_response(
        current_user,
        "DELETE",
        event_path,
    )
    if delete_response.status_code != status.HTTP_404_NOT_FOUND:
        _raise_graph_http_error(delete_response)

    update_reservation_record(
        reservation_id,
        {
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "cancellation_reason": cancellation.reason if cancellation else None,
        },
    )

    return OutlookReservationResponse(
        reservation_id=reservation_id,
        event_id=stored_reservation["event_id"],
        web_link=stored_reservation.get("web_link"),
        message="Reservacion cancelada en Outlook",
    )
