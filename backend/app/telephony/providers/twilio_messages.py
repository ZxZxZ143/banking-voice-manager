"""Bounded inbound Twilio protocol. Unknown optional Twilio fields are ignored."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

CallSid = Annotated[str, Field(pattern=r"^CA[0-9a-fA-F]{32}$")]
StreamSid = Annotated[str, Field(pattern=r"^MZ[0-9a-fA-F]{32}$")]
AccountSid = Annotated[str, Field(pattern=r"^AC[0-9a-fA-F]{32}$")]
Sequence = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,11}$")]


class Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class Connected(Model):
    event: Literal["connected"]
    protocol: Literal["Call"]
    version: Literal["1.0.0"]


class Sequenced(Model):
    sequenceNumber: Sequence
    streamSid: StreamSid


class MediaFormat(Model):
    encoding: Literal["audio/x-mulaw"]
    sampleRate: Literal[8000]
    channels: Literal[1]


class StartData(Model):
    accountSid: AccountSid
    callSid: CallSid
    streamSid: StreamSid
    tracks: list[Literal["inbound"]] = Field(min_length=1, max_length=1)
    mediaFormat: MediaFormat


class Start(Sequenced):
    event: Literal["start"]
    start: StartData


class MediaData(Model):
    track: Literal["inbound"]
    chunk: Sequence
    timestamp: Annotated[str, Field(pattern=r"^[0-9]{1,12}$")]
    payload: str = Field(min_length=4, max_length=1068)


class Media(Sequenced):
    event: Literal["media"]
    media: MediaData


class MarkData(Model):
    name: str = Field(min_length=1, max_length=128)


class Mark(Sequenced):
    event: Literal["mark"]
    mark: MarkData


class StopData(Model):
    accountSid: AccountSid
    callSid: CallSid


class Stop(Sequenced):
    event: Literal["stop"]
    stop: StopData


class DtmfData(Model):
    track: Literal["inbound_track"]
    digit: Annotated[str, Field(pattern=r"^[0-9*#A-D]$")]


class Dtmf(Sequenced):
    event: Literal["dtmf"]
    dtmf: DtmfData


message_adapter = TypeAdapter(
    Annotated[Connected | Start | Media | Mark | Stop | Dtmf, Field(discriminator="event")]
)
