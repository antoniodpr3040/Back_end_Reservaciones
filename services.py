import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

_TMP = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
DB_FILE = os.path.join(_TMP, "users.json")
RESERVATIONS_FILE = os.path.join(_TMP, "reservations.json")


def read_users():
    if not os.path.exists(DB_FILE):
        return []

    with open(DB_FILE, "r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return []


def write_users(users):
    with open(DB_FILE, "w", encoding="utf-8") as file:
        json.dump(users, file, indent=4, ensure_ascii=False)


def read_reservations():
    if not os.path.exists(RESERVATIONS_FILE):
        return []

    with open(RESERVATIONS_FILE, "r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return []


def write_reservations(reservations):
    with open(RESERVATIONS_FILE, "w", encoding="utf-8") as file:
        json.dump(reservations, file, indent=4, ensure_ascii=False)


def get_user_by_email(email):
    users = read_users()

    for user in users:
        if user["email"].lower() == email.lower():
            return user

    return None


def create_user(name, email, provider="microsoft", role="user"):
    users = read_users()

    new_id = 1
    if users:
        new_id = max(user["id"] for user in users) + 1

    new_user = {
        "id": new_id,
        "name": name,
        "email": email,
        "provider": provider,
        "role": role,
    }

    users.append(new_user)
    write_users(users)

    return new_user


def get_or_create_user(name, email, provider="microsoft"):
    existing_user = get_user_by_email(email)

    if existing_user:
        return existing_user

    role = "admin" if email.lower() == "diego.perez@keyinstitute.edu.sv" else "user"

    return create_user(
        name=name,
        email=email,
        provider=provider,
        role=role,
    )


def get_user_by_id(user_id):
    users = read_users()

    for user in users:
        if str(user["id"]) == str(user_id):
            return user

    return None


def update_user(user_id, updates: dict[str, Any]):
    users = read_users()

    for index, user in enumerate(users):
        if str(user["id"]) != str(user_id):
            continue

        updated_user = {**user, **updates}
        users[index] = updated_user
        write_users(users)
        return updated_user

    return None


def update_user_microsoft_tokens(
    user_id,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_at: str,
    scope: str,
):
    user = get_user_by_id(user_id)
    if not user:
        return None

    existing_auth = user.get("microsoft_auth", {})
    microsoft_auth = {
        **existing_auth,
        "access_token": access_token,
        "expires_at": expires_at,
        "scope": scope,
    }

    if refresh_token:
        microsoft_auth["refresh_token"] = refresh_token

    return update_user(user_id, {"microsoft_auth": microsoft_auth})


def save_reservation_record(reservation_data: dict[str, Any]):
    reservations = read_reservations()
    timestamp = datetime.now(timezone.utc).isoformat()
    reservation_id = str(reservation_data["reservation_id"])

    for index, existing in enumerate(reservations):
        if str(existing.get("reservation_id")) != reservation_id:
            continue

        reservations[index] = {
            **existing,
            **reservation_data,
            "updated_at": timestamp,
        }
        write_reservations(reservations)
        return reservations[index]

    new_reservation = {
        **reservation_data,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    reservations.append(new_reservation)
    write_reservations(reservations)
    return new_reservation


def update_reservation_record(reservation_id: str, updates: dict[str, Any]):
    reservations = read_reservations()
    timestamp = datetime.now(timezone.utc).isoformat()

    for index, reservation in enumerate(reservations):
        if str(reservation.get("reservation_id")) != str(reservation_id):
            continue

        updated_reservation = {
            **reservation,
            **updates,
            "updated_at": timestamp,
        }
        reservations[index] = updated_reservation
        write_reservations(reservations)
        return updated_reservation

    return None


def get_user_reservation_record(user_id, reservation_id: str):
    reservations = read_reservations()

    for reservation in reservations:
        if str(reservation.get("reservation_id")) != str(reservation_id):
            continue

        if str(reservation.get("user_id")) != str(user_id):
            continue

        return reservation

    return None


def list_user_reservation_records(user_id):
    reservations = read_reservations()
    user_reservations = [
        reservation
        for reservation in reservations
        if str(reservation.get("user_id")) == str(user_id)
    ]
    user_reservations.sort(
        key=lambda reservation: reservation.get("created_at", ""),
        reverse=True,
    )
    return user_reservations
