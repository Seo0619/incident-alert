from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, func
from .database import Base

class UserPost(Base):
    __tablename__ = "user_posts"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed = Column(Boolean, nullable=False, server_default="0")


class ConfirmedIncident(Base):
    __tablename__ = "confirmed_incidents"

    id = Column(Integer, primary_key=True, index=True)

    # 어떤 신고(post)에서 나온 것인지 추적 가능하게 연결
    source_post_id = Column(Integer, nullable=False)

    # LLM 판단 결과
    incident_type = Column(String, nullable=True)         # 예: "explosion", "stabbing"
    summary = Column(String, nullable=True)               # 짧은 요약 (사람이 읽을용)
    confidence = Column(Integer, nullable=False)          # 0~100 정수

    # 위치 정보 (아직 좌표는 안 쓰지만 LLM이 말한 장소 텍스트 정도는 저장 가능)
    location_country = Column(String, nullable=True)      # 예: "South Korea"
    location_area = Column(String, nullable=True)         # 예: "Gangnam Station area"

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
