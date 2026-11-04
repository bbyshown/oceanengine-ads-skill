"""Tencent Marketing API v3.0 transport and isolated OAuth storage. No ad defaults."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import uuid


class Rejected(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def save(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(value, f, ensure_ascii=False)
    temp.replace(path)


def load_config(root):
    path = Path(root) / 'private/tencent/config.json'
    if not path.exists(): raise Rejected('Tencent API is not configured; obtain developer permissions and account authorization first.')
    if path.stat().st_mode & 0o077: raise Rejected('Tencent configuration must have permissions 0600.')
    cfg = json.loads(path.read_text())
    if not str(cfg.get('client_id', '')).isdigit() or not cfg.get('client_secret'): raise Rejected('Tencent application credentials are incomplete.')
    url = urlsplit(cfg.get('redirect_uri', ''))
    if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment or url.port:
        raise Rejected('Tencent callback must be HTTPS without credentials, an explicit port, query or fragment.')
    if url.path != '/manage/v1/tencent/oauth/callback': raise Rejected('Use the installed Tencent callback path.')
    if not isinstance(cfg.get('accounts'), dict) or not cfg['accounts']: raise Rejected('Configure Tencent account/game allowlists.')
    for key, account in cfg['accounts'].items():
        if not str(key).isdigit() or int(key) <= 0: raise Rejected('Tencent account IDs must be positive integers.')
        games = account.get('mini_game_ids')
        if not isinstance(games, list) or not games or any(not isinstance(g, str) or not g.startswith('wx') for g in games):
            raise Rejected('Each Tencent account requires its authorized WeChat mini-game IDs.')
    return cfg


def scrub(value, cfg, tokens=None):
    banned = {'client_secret', 'access_token', 'refresh_token', 'authorization_code', 'user_token', 'authorization'}
    hidden = [cfg.get('client_secret', '')]
    hidden += [v for k, v in (tokens or {}).items() if k in banned and isinstance(v, str)]
    hidden += [a.get('user_token', '') for a in cfg.get('accounts', {}).values()]
    def clean(v):
        if isinstance(v, dict): return {k: clean(x) for k, x in v.items() if str(k).lower() not in banned}
        if isinstance(v, list): return [clean(x) for x in v]
        if isinstance(v, str):
            for token in hidden:
                if token: v = v.replace(token, '[redacted]')
        return v
    return clean(value)


def fetch_json(request):
    # Never propagate urllib exceptions, whose URL includes OAuth credentials.
    try:
        with build_opener(NoRedirect()).open(request, timeout=45) as response: return json.load(response)
    except Exception:
        raise RuntimeError('Tencent transport failed; URL and credentials withheld. Inspect the original job before retrying a write.') from None


def token_request(cfg, grant):
    query = dict(grant, client_id=int(cfg['client_id']), client_secret=cfg['client_secret'])
    result = fetch_json(Request('https://api.e.qq.com/oauth/token?' + urlencode(query)))
    if result.get('code') != 0: raise Rejected('Tencent OAuth rejected: ' + str(result.get('code')))
    token = result.get('data') or {}
    for field in ('access_token', 'refresh_token', 'access_token_expires_in', 'refresh_token_expires_in'):
        if not token.get(field): raise Rejected('Tencent OAuth returned incomplete token data.')
    return dict(token, received_at=time.time())


@contextlib.contextmanager
def locked(root):
    path = Path(root) / 'private/tencent';path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path / 'oauth.lock', os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield path


def access_token(root, cfg):
    with locked(root) as path:
        file = path / 'tokens.json'
        if not file.exists(): raise Rejected('Tencent account authorization has not completed.')
        token = json.loads(file.read_text())
        if time.time() < token['received_at'] + token['access_token_expires_in'] - 600: return token['access_token']
        marker = path / 'refresh-pending.json'
        if marker.exists(): raise Rejected('Previous Tencent token refresh is uncertain; inspect it before reauthorization.')
        if time.time() >= token['received_at'] + token['refresh_token_expires_in']: raise Rejected('Tencent authorization expired; authorize again.')
        save(marker, {'started_at': time.time()})
        try: fresh = token_request(cfg, {'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']})
        except Rejected:
            marker.unlink();raise
        save(file, fresh);marker.unlink()
        return fresh['access_token']


def authorize_url(root, cfg):
    with locked(root) as path:
        state = secrets.token_urlsafe(32)
        save(path / 'oauth-state.json', {'state_hash': hashlib.sha256(state.encode()).hexdigest(), 'expires_at': time.time() + 1800})
    query = {'client_id': cfg['client_id'], 'redirect_uri': cfg['redirect_uri'], 'state': state}
    return 'https://developers.e.qq.com/oauth/authorize?' + urlencode(query)


def callback(root, query):
    cfg = load_config(root)
    if set(query) - {'state', 'authorization_code', 'error', 'error_description'}: raise Rejected('Unexpected Tencent callback fields.')
    with locked(root) as path:
        file = path / 'oauth-state.json'
        if not file.exists(): raise Rejected('No pending Tencent authorization; request a fresh link.')
        state = json.loads(file.read_text());given = query.get('state', '')
        digest = hashlib.sha256(given.encode()).hexdigest()
        if time.time() > state['expires_at'] or not secrets.compare_digest(digest, state['state_hash']): raise Rejected('Tencent state invalid or expired.')
        file.unlink()  # Consume before token exchange; a failed exchange needs a fresh code.
        if query.get('error') or not query.get('authorization_code'): raise Rejected('Tencent authorization was not granted.')
        token = token_request(cfg, {'grant_type': 'authorization_code', 'authorization_code': query['authorization_code'], 'redirect_uri': cfg['redirect_uri']})
        save(path / 'tokens.json', token)
        (path / 'refresh-pending.json').unlink(missing_ok=True)
    return {'authorized': True, 'provider': 'tencent', 'message': 'Authorization completed. Tokens saved on the server.'}


class API:
    def __init__(self, root, cfg): self.root, self.cfg = Path(root), cfg

    def __call__(self, endpoint, params, post=False, upload=None):
        allowed = {'adgroups/get', 'adgroups/add', 'adgroups/update', 'adgroups/delete',
                   'dynamic_creatives/get', 'dynamic_creatives/add', 'dynamic_creatives/update', 'dynamic_creatives/delete',
                   'daily_reports/get', 'hourly_reports/get', 'funds/get', 'advertiser/get',
                   'images/add', 'videos/add', 'images/get', 'videos/get', 'conversions/get'}
        if endpoint not in allowed: raise Rejected('Tencent endpoint is not enabled.')
        token = access_token(self.root, self.cfg)
        common = {'access_token': token, 'timestamp': int(time.time()), 'nonce': uuid.uuid4().hex}
        headers = {};body = None;data = dict(params)
        if post:
            account = self.cfg['accounts'][str(params['account_id'])]
            if account.get('user_token') and upload is None: data['user_token'] = account['user_token']
            if upload:
                field, filename, raw = upload;boundary = uuid.uuid4().hex
                parts = []
                for k, v in data.items():
                    value = v if isinstance(v, str) else json.dumps(v, separators=(',', ':'))
                    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{value}\r\n'.encode())
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
                body = b''.join(parts) + raw + f'\r\n--{boundary}--\r\n'.encode()
                headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
            else:
                body = json.dumps(data, ensure_ascii=False).encode();headers['Content-Type'] = 'application/json'
        else:
            common.update({k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, separators=(',', ':')) for k, v in data.items()})
        result = fetch_json(Request('https://api.e.qq.com/v3.0/' + endpoint + '?' + urlencode(common), data=body, headers=headers, method='POST' if post else 'GET'))
        return scrub(result, self.cfg, {'access_token': token})
