import time
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from master.app import create_app
from master.security import BusinessError
from tests import test_master as fixtures


class SessionTests(unittest.TestCase):
    setUp = fixtures.MasterTests.setUp
    tearDown = fixtures.MasterTests.tearDown
    register = fixtures.MasterTests.register

    def test_new_login_is_one_hour_and_background_reads_do_not_renew(self):
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            result = client.post('/api/login', json={'username': 'admin', 'password': 'admin-test'})
            token = result.json()['token']
            with self.db.connect() as db:
                initial = db.execute('SELECT expire_time FROM sessions WHERE token=?', (token,)).fetchone()[0]
            self.assertAlmostEqual(3600, result.json()['expires_at'] - result.json()['server_time'])
            self.assertIn('Max-Age=3600', result.headers['set-cookie'])
            with patch('master.service.time.time', return_value=initial - 1):
                for path in ['/api/session', '/api/admin/data', '/api/admin/data']:
                    self.assertEqual(200, client.get(path).status_code)
            with self.db.connect() as db:
                self.assertEqual(initial, db.execute('SELECT expire_time FROM sessions WHERE token=?', (token,)).fetchone()[0])
            with patch('master.service.time.time', return_value=initial):
                expired = client.get('/api/admin/data', headers={'Authorization': token})
                self.assertEqual(401, expired.status_code)

    def test_real_activity_renews_cookie_and_expired_token_cannot_be_revived(self):
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            token = client.post('/api/login', json={'username': 'admin', 'password': 'admin-test'}).json()['token']
            with self.db.connect() as db:
                initial = db.execute('SELECT expire_time FROM sessions WHERE token=?', (token,)).fetchone()[0]
            now = initial - 20
            with patch('master.service.time.time', return_value=now):
                renewed = client.post('/api/session/activity', json={}, headers={'Origin': 'http://testserver'})
                self.assertEqual(200, renewed.status_code)
                self.assertEqual(now + 3600, renewed.json()['expires_at'])
                self.assertIn('Max-Age=3600', renewed.headers['set-cookie'])
                self.assertIn('HttpOnly', renewed.headers['set-cookie'])
            with patch('master.service.time.time', return_value=now + 3600):
                expired = client.post('/api/session/activity', json={}, headers={'Authorization': token})
                self.assertEqual(401, expired.status_code)
            with self.db.connect() as db:
                self.assertEqual(now + 3600, db.execute('SELECT expire_time FROM sessions WHERE token=?', (token,)).fetchone()[0])

    def test_rejected_activity_does_not_renew(self):
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            token = client.post('/api/login', json={'username': 'admin', 'password': 'admin-test'}).json()['token']
            with self.db.connect() as db:
                expiry = db.execute('SELECT expire_time FROM sessions WHERE token=?', (token,)).fetchone()[0]
            for headers in [{}, {'Origin': 'http://evil.example'}, {'Origin': 'http://testserver', 'Sec-Fetch-Site': 'cross-site'}]:
                self.assertEqual(403, client.post('/api/session/activity', json={}, headers=headers).status_code)
            with self.db.connect() as db:
                self.assertEqual(expiry, db.execute('SELECT expire_time FROM sessions WHERE token=?', (token,)).fetchone()[0])

    def test_account_expiry_blocks_activity(self):
        user = self.register()
        with self.db.connect(write=True) as db:
            token = db.execute('SELECT token FROM sessions WHERE username=?', (user['username'],)).fetchone()[0]
            db.execute('UPDATE users SET expire_time=? WHERE username=?', (time.time() - 1, user['username']))
        with self.assertRaisesRegex(BusinessError, 'Account expired'):
            self.service.session(token, activity=True)

    def test_throttled_activity_uses_event_time_and_stale_tab_cannot_shorten_deadline(self):
        with TestClient(create_app(self.config, self.remote, background=False)) as client:
            token = client.post('/api/login', json={'username': 'admin', 'password': 'admin-test'}).json()['token']
            with self.db.connect() as db:
                initial = db.execute('SELECT expire_time FROM sessions WHERE token=?', (token,)).fetchone()[0]
            now = initial - 20
            headers = {'Origin': 'http://testserver'}
            with patch('master.service.time.time', return_value=now):
                result = client.post('/api/session/activity', json={'age_ms': 12000}, headers=headers)
                self.assertEqual(now + 3588, result.json()['expires_at'])
                fresh = client.post('/api/session/activity', json={}, headers=headers)
                self.assertEqual(now + 3600, fresh.json()['expires_at'])
                stale = client.post('/api/session/activity', json={'age_ms': 15000}, headers=headers)
                self.assertEqual(now + 3600, stale.json()['expires_at'])
            for age in [-1, 60001, 'future', None]:
                self.assertEqual(400, client.post('/api/session/activity', json={'age_ms': age}, headers=headers).status_code)

    def test_restart_caps_legacy_sessions_without_extending_new_sessions(self):
        with self.db.connect(write=True) as db:
            old = time.time() + 604800
            short = time.time() + 120
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('old', 'admin', 'admin', old))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('short', 'admin', 'admin', short))
        self.db.initialize()
        with self.db.connect() as db:
            capped = db.execute('SELECT expire_time FROM sessions WHERE token=?', ('old',)).fetchone()[0]
            self.assertLessEqual(capped, time.time() + 3600)
            self.assertGreater(capped, time.time() + 3595)
            self.assertEqual(short, db.execute('SELECT expire_time FROM sessions WHERE token=?', ('short',)).fetchone()[0])
