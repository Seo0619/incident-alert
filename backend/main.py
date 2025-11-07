# backend/main.py (상단 import 정리)
from fastapi import FastAPI, Depends, Request, Form, HTTPException, Header, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import os

from .database import SessionLocal, engine
from . import models, schemas, crud
from .models import Base   # ★ Base는 models에서만!
from .worker import SCGWorker, WorkerConfig  # 👈 추가

# 모델이 import된 상태에서 create_all
Base.metadata.create_all(bind=engine)


app = FastAPI()
templates = Jinja2Templates(directory="backend/templates")

# import os
# print("[server] ADMIN_TOKEN =", repr(os.getenv("ADMIN_TOKEN")))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.state.worker = None

@app.on_event("startup")
def startup():
    # 자동 시작 여부
    if os.getenv("SCG_AUTOSTART", "0") == "1":
        if not app.state.worker:
            cfg = WorkerConfig()
            app.state.worker = SCGWorker(cfg)
            app.state.worker.start()
            print("[scg] embedded worker started")

@app.on_event("shutdown")
def shutdown():
    if app.state.worker:
        app.state.worker.stop()


# ----------------------------
#  페이지 라우트
# ----------------------------
@app.get("/feed")
def feed(request: Request):
    with SessionLocal() as db:
        posts = db.query(models.UserPost).order_by(models.UserPost.id.desc()).limit(50).all()
    return templates.TemplateResponse("feed.html", {"request": request, "posts": posts})

@app.get("/report")
def report_form(request: Request):
    return templates.TemplateResponse("report.html", {"request": request})

@app.post("/report")
def submit_report(text: str = Form(...)):
    with SessionLocal() as db:
        post = crud.create_post(db, schemas.PostCreate(text=text, is_simulated=False))
        seed_id = post.id
    # 새 글이 들어오면 워커에 작업 enqueue
    if app.state.worker:
        app.state.worker.enqueue(seed_id)
    return RedirectResponse(url="/feed", status_code=303)

# ----------------------------
#  API (추가)
# ----------------------------

# 최신 '실제(비모의)' 글 1건을 돌려주는 고정 경로
@app.get("/api/posts/latest_real")
def get_latest_real_post(db: Session = Depends(get_db)):
    post = (
        db.query(models.UserPost)
        .filter(models.UserPost.is_simulated == False)
        .order_by(models.UserPost.created_at.desc())
        .first()
    )
    if not post:
        raise HTTPException(status_code=404, detail="No real posts yet")
    return {"id": post.id, "text": post.text}


# (A) 단건 조회: 워커가 씨앗 글 본문을 가져갈 때 사용
@app.get("/api/posts/{post_id}")
def api_get_post(post_id: int, db: Session = Depends(get_db)):
    obj = db.query(models.UserPost).filter(models.UserPost.id == post_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="not found")
    return schemas.PostOut.model_validate(obj)

# (B) 미처리 글 조회: 기본적으로 시뮬 글은 제외
@app.get("/api/unprocessed")
def api_unprocessed(
    db: Session = Depends(get_db),
    include_simulated: bool = Query(False, description="시뮬레이션 글 포함 여부"),
    limit: int = Query(50, ge=1, le=200),
):
    rows = crud.get_unprocessed_posts(db, limit=limit, include_simulated=include_simulated)
    return [schemas.PostOut.model_validate(r) for r in rows]

# 예: /api/user_posts
@app.post("/api/user_posts")
def api_create_user_post(
    post: schemas.PostCreate,
    db: Session = Depends(get_db),
    x_admin_token: str = Header(None),
):
    admin_token = os.getenv("ADMIN_TOKEN")
    if admin_token:  # 보호 사용 중
        if not x_admin_token or x_admin_token.strip() != admin_token.strip():
            raise HTTPException(status_code=401, detail="Unauthorized")
    obj = crud.create_post(db, post)
    return schemas.PostOut.model_validate(obj)

# (D) (선택) 시뮬 배치 트리거(큐가 없다면 알림만)
@app.post("/api/simulate/burst")
def api_simulate_burst(
    req: schemas.SimulateBurstRequest,
    x_admin_token: str = Header(None)
):
    admin_token = os.getenv("ADMIN_TOKEN")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"status": "accepted", "seed_post_id": req.seed_post_id}

@app.get("/api/posts/latest_real", response_model=schemas.PostOut)
def api_latest_real_post(db: Session = Depends(get_db)):
    obj = crud.get_latest_real_post(db)
    if not obj:
        raise HTTPException(status_code=404, detail="no real post yet")
    return obj