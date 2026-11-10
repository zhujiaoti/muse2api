"""Keep upstream update checks from overwriting a customized deployment."""

from unittest.mock import Mock

from fastapi.testclient import TestClient
import requests

import app


def test_update_check_reports_change_without_launching_upgrade(monkeypatch, tmp_path):
    (tmp_path / 'installed-sha').write_text('0000000', encoding='utf-8')
    (tmp_path / 'upstream-commit.txt').write_text('1111111', encoding='utf-8')
    monkeypatch.setattr(app, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(app, '_installed_sha_file', lambda: str(tmp_path / 'installed-sha'))
    monkeypatch.setattr(app, '_read_local_version', lambda: {'version': '1.0.0'})
    monkeypatch.setattr(app, '_read_env_key', lambda _key: '')
    monkeypatch.setattr(app, '_UPDATE_CACHE', {'ts': 0, 'data': None})
    def get(url, **_kwargs):
        payload = {'version': '1.0.0'} if 'version.json' in url else [{
            'sha': '2222222', 'commit': {'message': 'new version', 'committer': {'date': ''}}
        }]
        return Mock(status_code=200, json=lambda: payload)
    monkeypatch.setattr(requests, 'get', get)
    thread = Mock(side_effect=AssertionError('an update check must never start a worker'))
    monkeypatch.setattr(app.threading, 'Thread', thread)
    result = app._check_update_sync(force=True, _auto_upgrade=True)
    assert result['has_update'] is True
    assert result['local_sha'] == '1111111'
    assert result['remote_sha'] == '2222222'
    thread.assert_not_called()


def test_live_upgrade_is_blocked_and_web_is_served(monkeypatch):
    app.app.dependency_overrides[app.auth] = lambda: None
    monkeypatch.setattr(app, '_upgrade_from_github_sync', Mock(side_effect=AssertionError('must not overwrite')))
    try:
        client = TestClient(app.app)
        for path in ('/admin/update/upgrade', '/admin/repo/pull'):
            response = client.post(path, json={'restart': True})
            assert response.status_code == 409
        response = client.get('/web')
        assert response.status_code == 200
        assert 'const combined=files.concat(selected)' in response.text
        app._upgrade_from_github_sync.assert_not_called()
    finally:
        app.app.dependency_overrides.clear()


def test_admin_does_not_trigger_live_upgrade():
    html = open('admin.html', encoding='utf-8').read()
    assert "api('/admin/update/upgrade'" not in html
