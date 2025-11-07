# backend/main.py (상단 import 정리)
from fastapi import FastAPI, Depends, Request, Form, HTTPException, Header, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import os

from .database import SessionLocal, engine
from . import models, schemas, crud
from .models import Base   # ★ Base는 models에서만!

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

# ----------------------------
#  페이지 라우트
# ----------------------------
@app.get("/feed", response_class=HTMLResponse)
def feed(request: Request, db: Session = Depends(get_db)):
    posts = crud.get_recent_posts(db, limit=100)
    return templates.TemplateResponse(
        "feed.html", {"request": request, "posts": posts}
    )

@app.get("/report", response_class=HTMLResponse)
def report_form(request: Request):
    return templates.TemplateResponse("report.html", {"request": request})

@app.post("/report")
def submit_report(text: str = Form(...), db: Session = Depends(get_db)):
    crud.create_post(db, schemas.PostCreate(text=text, is_simulated=False))
    return RedirectResponse(url="/feed", status_code=303)

# ----------------------------
#  API (추가)
# ----------------------------

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