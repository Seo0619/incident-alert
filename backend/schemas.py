from pydantic import BaseModel, Field
from datetime import datetime

class PostCreate(BaseModel):
    text: str = Field(..., description="What happened?")

class PostRead(BaseModel):
    id: int
    text: str
    created_at: datetime
    processed: bool

    class Config:
        from_attributes = True  # allow ORM -> Pydantic

class ConfirmedIncidentCreate(BaseModel):
    source_post_id: int
    incident_type: str | None = None
    summary: str | None = None
    confidence: int
    location_country: str | None = None
    location_area: str | None = None


class ConfirmedIncidentRead(BaseModel):
    id: int
    source_post_id: int
    incident_type: str | None
    summary: str | None
    confidence: int
    location_country: str | None
    location_area: str | None
    created_at: datetime

    class Config:
        from_attributes = True
