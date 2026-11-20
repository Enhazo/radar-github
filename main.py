from __future__ import annotations

import csv
import io
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'radar.db').as_posix()}")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class TrackedRepo(Base):
    __tablename__ = "tracked_repositories"
    __table_args__ = (UniqueConstraint("owner", "name", name="uq_repo_owner_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner: Mapped[str] = mapped_column(String(39), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(300))
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    open_issues: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String(80), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Snapshot(Base):
    __tablename__ = "repo_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo_id: Mapped[int] = mapped_column(Integer, index=True)
    stars: Mapped[int] = mapped_column(Integer)
    forks: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


app = FastAPI(title="Radar GitHub", description="Acompanhe métricas públicas de repositórios com histórico próprio", version="1.0.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')


def get_db():
    with SessionLocal() as db:
        yield db


async def github_get(path: str, params: dict | None = None):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "RadarGitHub/1.0 educational-portfolio"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), headers=headers) as client:
        try:
            response = await client.get(f"https://api.github.com{path}", params=params)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail="Não foi possível acessar a API do GitHub.") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Perfil ou repositório público não encontrado.")
    if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
        raise HTTPException(status_code=429, detail="Limite da API pública atingido. Tente novamente mais tarde ou configure um token de leitura.")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="O GitHub retornou um erro ao consultar os dados.")
    return response.json()


def serialize_repo(repo: TrackedRepo, snapshots: list[Snapshot]):
    ordered = sorted(snapshots, key=lambda item: item.captured_at)
    delta = ordered[-1].stars - ordered[-2].stars if len(ordered) >= 2 else None
    return {"id": repo.id, "owner": repo.owner, "name": repo.name, "description": repo.description, "url": repo.url, "stars": repo.stars, "forks": repo.forks, "open_issues": repo.open_issues, "language": repo.language, "updated_at": repo.updated_at.isoformat(), "history": [{"stars": row.stars, "forks": row.forks, "captured_at": row.captured_at.isoformat()} for row in ordered], "star_change": delta}


class TrackRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=39, pattern=r"^[A-Za-z0-9-]+$")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")


@app.get('/health')
def health():
    return {"status": "ok"}


@app.get('/api/search')
async def search_repositories(q: str = Query(min_length=2, max_length=100)):
    payload = await github_get('/search/repositories', {"q": q.strip(), "sort": "stars", "order": "desc", "per_page": 8})
    return {"total_count": payload.get("total_count", 0), "items": [{"owner": item["owner"]["login"], "name": item["name"], "description": item.get("description") or "", "url": item["html_url"], "stars": item["stargazers_count"], "language": item.get("language") or ""} for item in payload.get("items", [])]}


@app.post('/api/repos', status_code=201)
async def track_repository(payload: TrackRequest, db: Session = Depends(get_db)):
    owner, name = payload.owner.strip(), payload.name.strip()
    data = await github_get(f'/repos/{owner}/{name}')
    repo = db.scalar(select(TrackedRepo).where(TrackedRepo.owner == data['owner']['login'], TrackedRepo.name == data['name']))
    now = datetime.now(UTC)
    if repo is None:
        repo = TrackedRepo(owner=data['owner']['login'], name=data['name'], url=data['html_url'])
        db.add(repo)
        db.flush()
    repo.description = (data.get('description') or '')[:500]
    repo.url = data['html_url']
    repo.stars = data['stargazers_count']
    repo.forks = data['forks_count']
    repo.open_issues = data['open_issues_count']
    repo.language = data.get('language') or ''
    repo.updated_at = now
    latest = db.scalar(select(Snapshot).where(Snapshot.repo_id == repo.id).order_by(Snapshot.captured_at.desc()).limit(1))
    if latest is None or latest.stars != repo.stars or latest.forks != repo.forks:
        db.add(Snapshot(repo_id=repo.id, stars=repo.stars, forks=repo.forks, captured_at=now))
    db.commit()
    db.refresh(repo)
    snapshots = db.scalars(select(Snapshot).where(Snapshot.repo_id == repo.id)).all()
    return serialize_repo(repo, snapshots)


@app.get('/api/repos')
def list_repositories(db: Session = Depends(get_db)):
    repos = db.scalars(select(TrackedRepo).order_by(TrackedRepo.stars.desc())).all()
    return [serialize_repo(repo, db.scalars(select(Snapshot).where(Snapshot.repo_id == repo.id)).all()) for repo in repos]


@app.post('/api/repos/{repo_id}/refresh')
async def refresh_repository(repo_id: int, db: Session = Depends(get_db)):
    repo = db.get(TrackedRepo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail='Repositório não monitorado.')
    data = await github_get(f'/repos/{repo.owner}/{repo.name}')
    now = datetime.now(UTC)
    previous = db.scalar(select(Snapshot).where(Snapshot.repo_id == repo.id).order_by(Snapshot.captured_at.desc()).limit(1))
    repo.description = (data.get('description') or '')[:500]
    repo.url = data['html_url']
    repo.stars = data['stargazers_count']
    repo.forks = data['forks_count']
    repo.open_issues = data['open_issues_count']
    repo.language = data.get('language') or ''
    repo.updated_at = now
    if previous is None or previous.stars != repo.stars or previous.forks != repo.forks:
        db.add(Snapshot(repo_id=repo.id, stars=repo.stars, forks=repo.forks, captured_at=now))
    db.commit()
    db.refresh(repo)
    return serialize_repo(repo, db.scalars(select(Snapshot).where(Snapshot.repo_id == repo.id)).all())


@app.delete('/api/repos/{repo_id}', status_code=204)
def remove_repository(repo_id: int, db: Session = Depends(get_db)):
    repo = db.get(TrackedRepo, repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail='Repositório não monitorado.')
    for snapshot in db.scalars(select(Snapshot).where(Snapshot.repo_id == repo.id)).all():
        db.delete(snapshot)
    db.delete(repo)
    db.commit()


@app.get('/api/export.csv')
def export_csv(db: Session = Depends(get_db)):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['proprietario', 'repositorio', 'estrelas', 'forks', 'issues_abertas', 'linguagem', 'url', 'coletado_em'])
    def safe_cell(value):
        text = str(value)
        return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
    for repo in db.scalars(select(TrackedRepo).order_by(TrackedRepo.owner, TrackedRepo.name)):
        writer.writerow([safe_cell(repo.owner), safe_cell(repo.name), repo.stars, repo.forks, repo.open_issues, safe_cell(repo.language), safe_cell(repo.url), repo.updated_at.isoformat()])
    content = '\ufeff' + output.getvalue()
    return StreamingResponse(iter([content]), media_type='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="radar-github.csv"'})


@app.get('/', response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request, 'index.html', {})
