"""Bounded Vonage JSON controls; binary audio is validated separately."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from app.telephony.providers.vonage_audio import CONTENT_TYPE

CallUuid = Annotated[
    str,
    Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
]
PhoneNumber = Annotated[str, Field(pattern=r"^[1-9][0-9]{7,14}$")]


class Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)


class Answer(Model):
    uuid: CallUuid
    to: PhoneNumber
    from_number: PhoneNumber = Field(alias="from", repr=False)


class Connected(Model):
    event: Literal["websocket:connected"]
    content_type: Literal[CONTENT_TYPE] = Field(alias="content-type")
    call_uuid: CallUuid  # Our NCCO metadata, not a claim about an undocumented native field.


class NotifyPayload(Model):
    reply_id: str = Field(min_length=1, max_length=128)


class Notify(Model):
    event: Literal["websocket:notify"]
    payload: NotifyPayload


class Cleared(Model):
    event: Literal["websocket:cleared"]


class Dtmf(Model):
    event: Literal["websocket:dtmf"]
    digit: str = Field(pattern=r"^[0-9*#A-D]$")
    duration: int = Field(ge=0, le=60000)


class CallEvent(Model):
    uuid: CallUuid | None = None
    status: (
        Literal[
            "started",
            "ringing",
            "answered",
            "completed",
            "busy",
            "cancelled",
            "unanswered",
            "rejected",
            "failed",
            "timeout",
            "disconnected",
        ]
        | None
    ) = None
    type: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def meaningful_event(self):
        if self.status is None and self.type != "error":
            raise ValueError("Expected a lifecycle status or error event")
        if self.uuid is None and self.status != "rejected" and self.type != "error":
            raise ValueError("Expected a call UUID")
        return self


control_adapter = TypeAdapter(
    Annotated[Connected | Notify | Cleared | Dtmf, Field(discriminator="event")]
)
