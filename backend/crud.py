from sqlalchemy.orm import Session
from . import models, schemas

def create_post(db: Session, post: schemas.PostCreate) -> models.UserPost:
    db_obj = models.UserPost(
        text=post.text,
        is_simulated=bool(post.is_simulated),
        persona=post.persona,
        seed_post_id=post.seed_post_id,
        lang=post.lang,
        hashtags=post.hashtags,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

def get_recent_posts(db: Session, limit: int = 50):
    return (
        db.query(models.UserPost)
        .order_by(models.UserPost.created_at.desc())
        .limit(limit)
        .all()
    )

def get_unprocessed_posts(db: Session, limit: int = 50, include_simulated: bool = False):
    q = db.query(models.UserPost).filter(models.UserPost.processed == False)
    if not include_simulated:
        q = q.filter(models.UserPost.is_simulated == False)
    return q.order_by(models.UserPost.created_at.asc()).limit(limit).all()

def mark_post_processed(db: Session, post_id: int) -> models.UserPost | None:
    post = db.query(models.UserPost).filter(models.UserPost.id == post_id).first()
    if not post:
        return None
    post.processed = True
    db.commit()
    db.refresh(post)
    return post

def create_confirmed_incident(db: Session, incident: schemas.ConfirmedIncidentCreate) -> models.ConfirmedIncident:
    db_obj = models.ConfirmedIncident(
        source_post_id=incident.source_post_id,
        incident_type=incident.incident_type,
        summary=incident.summary,
        confidence=incident.confidence,
        location_country=incident.location_country,
        location_area=incident.location_area,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


def get_recent_incidents(db: Session, limit: int = 50):
    return (
        db.query(models.ConfirmedIncident)
        .order_by(models.ConfirmedIncident.created_at.desc())
        .limit(limit)
        .all()
    )

def get_latest_real_post(db: Session):
    return (
        db.query(models.UserPost)
        .filter(models.UserPost.is_simulated == False)
        .order_by(models.UserPost.created_at.desc())
        .first()
    )
