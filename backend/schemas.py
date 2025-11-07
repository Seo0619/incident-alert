from pydantic import BaseModel, Field
from datetime import datetime

from pydantic import BaseModel
from typing import Optional

class PostCreate(BaseModel):
    text: str
    is_simulated: Optional[bool] = False
    persona: Optional[str] = None
    seed_post_id: Optional[int] = None
    lang: Optional[str] = None
    hashtags: Optional[str] = None

class PostOut(BaseModel):
    id: int
    text: str
    created_at: datetime   # ★ str → datetime 로 변경
    processed: bool
    is_simulated: bool
    persona: Optional[str] = None
    seed_post_id: Optional[int] = None
    lang: Optional[str] = None
    hashtags: Optional[str] = None

    class Config:
        from_attributes = True  # 그대로 두시면 됩니다 (v2도 호환)

class SimulateBurstRequest(BaseModel):
    seed_post_id: int                      # 씨앗 글
    n_posts: int = 50                      # 생성 개수
    burst_minutes: int = 20                # 분산 시간(분)
    language_mix: dict[str, float] = {"ko": 1.0}
    hashtags: list[str] = []


class PostRead(BaseModel):
    id: int
    text: str
    created_at: datetime
    processed: bool

    class Config:
        from_attributes = True  # allow ORM -> Pydantic

        
class ConfirmedIncidentCreate(BaseModel):
    post_id: int
    incident_type: Optional[str] = None
    confidence: int = 0
    country: Optional[str] = None
    city_or_area: Optional[str] = None
    summary: Optional[str] = None

class ConfirmedIncidentOut(BaseModel):
    id: int
    post_id: int
    incident_type: Optional[str] = None
    confidence: int
    country: Optional[str] = None
    city_or_area: Optional[str] = None
    summary: Optional[str] = None
    created_at: datetime     # ★ str → datetime 로 변경

    class Config:
        from_attributes = True