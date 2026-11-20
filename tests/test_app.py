import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = main.create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(main, 'engine', engine)
    main.SessionLocal.configure(bind=engine)
    main.Base.metadata.create_all(engine)
    with TestClient(main.app) as test_client:
        yield test_client
    main.Base.metadata.drop_all(engine)
    engine.dispose()


def test_health(client):
    assert client.get('/health').json() == {'status': 'ok'}


def test_search_validation(client):
    assert client.get('/api/search?q=x').status_code == 422


def test_track_persists_snapshot_and_retrack_does_not_duplicate(monkeypatch, client):
    async def fake_get(path, params=None):
        return {'owner': {'login': 'octocat'}, 'name': 'hello-world', 'description': 'Example', 'html_url': 'https://github.com/octocat/hello-world', 'stargazers_count': 100, 'forks_count': 10, 'open_issues_count': 2, 'language': 'Python'}
    monkeypatch.setattr(main, 'github_get', fake_get)
    payload = {'owner': 'octocat', 'name': 'hello-world'}
    first = client.post('/api/repos', json=payload)
    second = client.post('/api/repos', json=payload)
    assert first.status_code == 201
    assert second.json()['id'] == first.json()['id']
    assert len(client.get('/api/repos').json()) == 1
    assert len(client.get('/api/repos').json()[0]['history']) == 1


def test_unknown_refresh_and_delete_return_404(client):
    assert client.post('/api/repos/123/refresh').status_code == 404
    assert client.delete('/api/repos/123').status_code == 404


def test_csv_export_has_headers(client):
    response = client.get('/api/export.csv')
    assert response.status_code == 200
    assert 'proprietario,repositorio,estrelas' in response.text


def test_csv_export_neutralizes_formula_cells(client, monkeypatch):
    from main import TrackedRepo
    with main.SessionLocal() as db:
        db.add(TrackedRepo(owner='safe-owner', name='safe-repo', description='', url='https://github.com/safe-owner/safe-repo', stars=1, forks=0, open_issues=0, language='=1+1'))
        db.commit()
    response = client.get('/api/export.csv')
    assert "'=1+1" in response.text


def test_home_page(client):
    assert 'O que cresce' in client.get('/').text
