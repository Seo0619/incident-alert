from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy.orm import Session

from . import database, models, crud, schemas

# 테이블 없으면 생성
models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="Incident Board MVP")

app.mount("/static", StaticFiles(directory="backend/static"), name="static")
templates = Jinja2Templates(directory="backend/templates")


@app.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request, db: Session = Depends(database.get_db)):
    posts_db = crud.get_recent_posts(db, limit=50)
    return templates.TemplateResponse(
        "feed.html",
        {
            "request": request,
            "title": "Recent Reports",
            "posts": posts_db,
        }
    )


@app.get("/report", response_class=HTMLResponse)
def report_form(request: Request):
    return templates.TemplateResponse(
        "report.html",
        {
            "request": request,
            "title": "New Report",
        }
    )


@app.post("/report")
def submit_report(
    text: str = Form(...),
    db: Session = Depends(database.get_db),
):
    new_post = schemas.PostCreate(
        text=text.strip(),
    )
    crud.create_post(db, new_post)

    return RedirectResponse(url="/feed", status_code=303)


@app.get("/api/posts", response_model=list[schemas.PostRead])
def get_posts_api(db: Session = Depends(database.get_db), limit: int = 50):
    posts_db = crud.get_recent_posts(db, limit=limit)
    return posts_db


@app.get("/api/unprocessed", response_model=list[schemas.PostRead])
def get_unprocessed_posts_api(db: Session = Depends(database.get_db), limit: int = 50):
    posts_db = crud.get_unprocessed_posts(db, limit=limit)
    return posts_db


@app.post("/api/mark_processed/{post_id}", response_model=schemas.PostRead)
def mark_processed_api(post_id: int, db: Session = Depends(database.get_db)):
    post = crud.mark_post_processed(db, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@app.post("/api/incidents", response_model=schemas.ConfirmedIncidentRead)
def create_incident_api(
    incident: schemas.ConfirmedIncidentCreate,
    db: Session = Depends(database.get_db),
):
    created = crud.create_confirmed_incident(db, incident)
    return created


@app.get("/api/incidents", response_model=list[schemas.ConfirmedIncidentRead])
def list_incidents_api(db: Session = Depends(database.get_db), limit: int = 50):
    incidents_db = crud.get_recent_incidents(db, limit=limit)
    return incidents_db


@app.get("/incidents", response_class=HTMLResponse)
def incidents_page(request: Request, db: Session = Depends(database.get_db)):
    incidents_db = crud.get_recent_incidents(db, limit=50)
    return templates.TemplateResponse(
        "incidents.html",
        {
            "request": request,
            "title": "Detected Incidents",
            "incidents": incidents_db,
        }
    )