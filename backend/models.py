from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class UserPost(Base):
    __tablename__ = "user_posts"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    processed = Column(Boolean, default=False, nullable=False)

    # 시뮬레이션 메타
    is_simulated = Column(Boolean, default=False, nullable=False)
    persona = Column(String, nullable=True)
    seed_post_id = Column(Integer, ForeignKey("user_posts.id"), nullable=True)
    lang = Column(String, nullable=True)
    hashtags = Column(String, nullable=True)

    seed_post = relationship("UserPost", remote_side=[id], uselist=False)

# ★ 추가: 확정 사건 테이블
class ConfirmedIncident(Base):
    __tablename__ = "confirmed_incidents"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("user_posts.id"), nullable=False)

    incident_type = Column(String, nullable=True)
    confidence = Column(Integer, nullable=False, default=0)

    country = Column(String, nullable=True)
    city_or_area = Column(String, nullable=True)

    summary = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)

    post = relationship("UserPost")
