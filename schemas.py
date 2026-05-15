from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class MicrosoftCallbackQuery(BaseModel):
    code: str
    state: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    provider: str = "microsoft"
    role: str = "user"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ReservationCreate(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "Reserva de aula 201",
                "description": "Clase de ingles intermedio",
                "start": "2026-04-05T09:00:00",
                "end": "2026-04-05T10:30:00",
                "location": "Edificio A, Aula 201",
                "timezone": "Central America Standard Time",
                "attendees": [
                    "coordinacion@keyinstitute.edu.sv",
                    "docente@keyinstitute.edu.sv",
                ],
            }
        }
    )
    reservation_id: Optional[str] = Field(default=None, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    start: datetime
    end: datetime
    timezone: str = Field(default="Central America Standard Time", min_length=1, max_length=120)
    location: Optional[str] = Field(default=None, max_length=200)
    attendees: list[EmailStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.end <= self.start:
            raise ValueError("La fecha de fin debe ser mayor que la fecha de inicio")
        return self


class OutlookReservationResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reservation_id": "4c0e2bb6-f8df-4d80-bacb-c79d0f0af3b2",
                "event_id": "AAMkAGI2TAAA=",
                "web_link": "https://outlook.office.com/calendar/item/123",
                "message": "Reservacion agregada al calendario de Outlook",
            }
        }
    )
    reservation_id: str
    event_id: str
    web_link: Optional[str] = None
    message: str


class OccupiedSlot(BaseModel):
    reservation_id: str
    title: str
    location: Optional[str] = None
    start: datetime
    end: datetime
    status: str


class ReservationCancel(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reason": "Se suspendio la clase por feriado institucional",
            }
        }
    )
    reason: str = Field(min_length=1, max_length=500)


class ReservationRecord(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reservation_id": "4c0e2bb6-f8df-4d80-bacb-c79d0f0af3b2",
                "user_id": 2,
                "user_email": "usuario@keyinstitute.edu.sv",
                "event_id": "AAMkAGI2TAAA=",
                "web_link": "https://outlook.office.com/calendar/item/123",
                "title": "Reserva de aula 201",
                "description": "Clase de ingles intermedio",
                "start": "2026-04-05T09:00:00",
                "end": "2026-04-05T10:30:00",
                "timezone": "Central America Standard Time",
                "location": "Edificio A, Aula 201",
                "attendees": [
                    "coordinacion@keyinstitute.edu.sv",
                    "docente@keyinstitute.edu.sv",
                ],
                "status": "created",
                "created_at": "2026-04-04T21:10:00+00:00",
                "updated_at": "2026-04-04T21:10:00+00:00",
                "cancelled_at": None,
                "cancellation_reason": None,
            }
        }
    )
    reservation_id: str
    user_id: int
    user_email: Optional[EmailStr] = None
    event_id: str
    web_link: Optional[str] = None
    title: str
    description: Optional[str] = None
    start: datetime
    end: datetime
    timezone: str
    location: Optional[str] = None
    attendees: list[EmailStr] = Field(default_factory=list)
    status: str
    created_at: datetime
    updated_at: datetime
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
