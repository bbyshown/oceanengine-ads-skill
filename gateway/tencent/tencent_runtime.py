"""Tencent Marketing API v3.0 transport and isolated OAuth storage. No ad defaults."""
import contextlib
import fcntl
import hashlib
import http.client
import ipaddress
import socket
import json
import os
import re
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler
import uuid


class Rejected(ValueError):
    pass


class OAuthRejected(Rejected):
    def __init__(self, provider_code, diagnostic=None):
        self.diagnostic = diagnostic or {}
        code = str(provider_code)
        self.provider_code = int(code) if re.fullmatch(r'-?[0-9]{1,10}', code) else None
        super().__init__(f'Tencent OAuth rejected: {self.provider_code}' if self.provider_code is not None
                         else 'Tencent OAuth rejected without a numeric error code.')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


def token_host(cfg):
    host = cfg.get('oauth_token_host', 'api.e.qq.com')
    if host not in ('api.e.qq.com', 'developers.e.qq.com'):
        raise Rejected('Use an approved Tencent OAuth token hostname.')
    return host


def token_remote_ip(cfg):
    value = cfg.get('oauth_token_remote_ip')
    if value is None: return None
    try:
        address = ipaddress.ip_address(value)
        if not address.is_global: raise ValueError()
    except (ValueError, TypeError):
        raise Rejected('Tencent OAuth remote address must be a verified public IP.') from None
    return str(address)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to an owner-verified node; HTTPSConnection retains domain SNI/TLS checks."""
    def __init__(self, host, *, remote_ip, **kwargs):
        if host not in ('api.e.qq.com', 'developers.e.qq.com'): raise Rejected('OAuth pinning is limited to the Tencent token host.')
        super().__init__(host, **kwargs)
        self._create_connection = lambda address, timeout, source_address: socket.create_connection(
            (remote_ip, 443), timeout, source_address)


class PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, remote_ip):
        super().__init__()
        self.remote_ip = remote_ip

    def https_open(self, request):
        if urlsplit(request.full_url).path != '/oauth/token':
            raise Rejected('OAuth pinning is limited to the Tencent token endpoint.')
        return self.do_open(lambda host, **kw: PinnedHTTPSConnection(
            host, remote_ip=self.remote_ip, **kw), request,
            context=self._context, check_hostname=self._check_hostname)


def save(path, value):
    path = Path(path);path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f: json.dump(value, f, ensure_ascii=False)
    temp.replace(path)


def profile_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{3,47}', value):
        raise Rejected('Use a 4–48 character lowercase Tencent authorization profile ID.')
    return value


def directory(root, cfg=None, *, profile_id=None):
    profile_id = profile_id or (cfg or {}).get('_profile_id')
    base = Path(root) / 'private/tencent'
    return base / 'profiles' / profile_name(profile_id) if profile_id else base


def load_config(root, *, require_accounts=True, profile_id=None):
    path = directory(root, profile_id=profile_id) / 'config.json'
    if not path.exists(): raise Rejected('Tencent API is not configured; obtain developer permissions and account authorization first.')
    if path.stat().st_mode & 0o077: raise Rejected('Tencent configuration must have permissions 0600.')
    cfg = json.loads(path.read_text())
    if not str(cfg.get('client_id', '')).isdigit() or not cfg.get('client_secret'): raise Rejected('Tencent application credentials are incomplete.')
    url = urlsplit(cfg.get('redirect_uri', ''))
    if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment or url.port:
        raise Rejected('Tencent callback must be HTTPS without credentials, an explicit port, query or fragment.')
    if url.path != '/manage/v1/tencent/oauth/callback': raise Rejected('Use the installed Tencent callback path.')
    token_remote_ip(cfg)
    token_host(cfg)
    accounts = cfg.get('accounts', {})
    if not isinstance(accounts, dict) or (require_accounts and not accounts): raise Rejected('Configure Tencent account/game allowlists.')
    for key, account in accounts.items():
        if not str(key).isdigit() or int(key) <= 0: raise Rejected('Tencent account IDs must be positive integers.')
        if not isinstance(account, dict): raise Rejected('Tencent account configuration must be an object.')
        games = account.get('mini_game_ids')
        if not isinstance(games, list) or not games or any(not isinstance(g, str) or not g.startswith('wx') for g in games):
            raise Rejected('Each Tencent account requires its authorized WeChat mini-game IDs.')
    operators = cfg.get('operators', {})
    if not isinstance(operators, dict): raise Rejected('Tencent operators must be an object.')
    for name, value in operators.items():
        operator_name(name)
        if not isinstance(value, dict): raise Rejected('Tencent operator must be an object.')
    for account in accounts.values():
        if 'operator_id' in account:
            operator_name(account['operator_id'])
            if account['operator_id'] not in operators: raise Rejected('Tencent account references an unknown operator.')
    if profile_id: cfg['_profile_id'] = profile_name(profile_id)
    elif '_profile_id' in cfg: raise Rejected('Profile selection must be explicit.')
    return cfg


def provision_profile(root, profile_id, *, client_id, client_secret, redirect_uri):
    """Owner-only file provisioning; deliberately not a public gateway operation."""
    profile_name(profile_id)
    if (not str(client_id).isdigit() or not isinstance(client_secret, str)
            or not 1 <= len(client_secret.encode()) <= 256 or any(c.isspace() for c in client_secret)):
        raise Rejected('Malformed Tencent application credentials; values withheld.')
    url = urlsplit(redirect_uri)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.port
            or url.query or url.fragment or url.path != '/manage/v1/tencent/oauth/callback'):
        raise Rejected('Use the installed HTTPS Tencent callback URL.')
    cfg = {'client_id': str(client_id), 'client_secret': client_secret, 'redirect_uri': redirect_uri,
           'application_type': 'third_party', 'accounts': {}, 'write_enabled': False}
    selected = dict(cfg, _profile_id=profile_id)
    with locked(root, selected) as path:
        file = path / 'config.json'
        if file.exists():
            old = json.loads(file.read_text())
            if any(old.get(k) != cfg[k] for k in ('client_id', 'client_secret', 'redirect_uri')):
                raise Rejected('Tencent profile already has different credentials; existing identity preserved.')
        else: save(file, cfg)
    return {'profile_id': profile_id, 'client_id': str(client_id), 'configured': True,
            'management_enabled': False, 'write_enabled': False}


def scrub(value, cfg, tokens=None):
    banned = {'client_secret', 'access_token', 'refresh_token', 'authorization_code', 'user_token', 'authorization'}
    hidden = [cfg.get('client_secret', '')]
    hidden += [v for k, v in (tokens or {}).items() if k in banned and isinstance(v, str)]
    hidden += [a.get('user_token', '') for a in cfg.get('accounts', {}).values()]
    hidden += [a.get('user_token', '') for a in cfg.get('operators', {}).values()]
    def clean(v):
        if isinstance(v, dict): return {k: clean(x) for k, x in v.items() if str(k).lower() not in banned}
        if isinstance(v, list): return [clean(x) for x in v]
        if isinstance(v, str):
            for token in hidden:
                if token: v = v.replace(token, '[redacted]')
        return v
    return clean(value)


def fetch_json(request, *, remote_ip=None):
    # Never propagate urllib exceptions, whose URL includes OAuth credentials.
    try:
        handlers = [NoRedirect()]
        if remote_ip:
            handlers.extend([ProxyHandler({}), PinnedHTTPSHandler(remote_ip)])
        with build_opener(*handlers).open(request, timeout=45) as response: return json.load(response)
    except Exception:
        raise RuntimeError('Tencent transport failed; URL and credentials withheld. Inspect the original job before retrying a write.') from None


def token_request(cfg, grant):
    query = dict(grant, client_id=int(cfg['client_id']), client_secret=cfg['client_secret'])
    request = Request('https://' + token_host(cfg) + '/oauth/token?' + urlencode(query))
    remote_ip = token_remote_ip(cfg)
    result = fetch_json(request, remote_ip=remote_ip) if remote_ip else fetch_json(request)
    if result.get('code') != 0:
        # Keep selected business diagnostics, never the raw response or request URL.
        diagnostic = {}
        for key in ('message', 'message_cn', 'trace_id', 'request_id'):
            value = result.get(key)
            if not isinstance(value, str):
                continue
            value = scrub(value, cfg, grant)
            value = re.sub(r'https?://[^\s]+', '[url withheld]', value)
            value = re.sub(r'[A-Za-z0-9_+-]{24,}', '[identifier withheld]', value) if key.startswith('message') else value
            if key in ('trace_id', 'request_id') and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
                continue
            diagnostic[key] = value[:500]
        raise OAuthRejected(result.get('code'), diagnostic)
    token = result.get('data') or {}
    for field in ('access_token', 'refresh_token', 'access_token_expires_in', 'refresh_token_expires_in'):
        if not token.get(field): raise RuntimeError('Tencent OAuth returned incomplete token data; inspect the original exchange before retrying.')
    return dict(token, received_at=time.time())


@contextlib.contextmanager
def locked(root, cfg=None):
    path = directory(root, cfg);path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path / 'oauth.lock', os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield path


def access_token(root, cfg):
    with locked(root, cfg) as path:
        file = path / 'tokens.json'
        if not file.exists(): raise Rejected('Tencent account authorization has not completed.')
        token = json.loads(file.read_text())
        if token.get('client_id') is not None and str(token['client_id']) != str(cfg['client_id']):
            raise Rejected('Tencent token belongs to another application.')
        if time.time() < token['received_at'] + token['access_token_expires_in'] - 600: return token['access_token']
        marker = path / 'refresh-pending.json'
        if marker.exists(): raise Rejected('Previous Tencent token refresh is uncertain; inspect it before reauthorization.')
        if time.time() >= token['received_at'] + token['refresh_token_expires_in']: raise Rejected('Tencent authorization expired; authorize again.')
        save(marker, {'started_at': time.time()})
        try: fresh = token_request(cfg, {'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']})
        except Rejected:
            marker.unlink();raise
        fresh['client_id'] = str(cfg['client_id'])
        save(file, fresh);marker.unlink()
        return fresh['access_token']


def stage_private_tokens(root, token_pair, not_before):
    """Owner-only provisioning helper, never exposed over the management HTTP API."""
    cfg = load_config(root, require_accounts=False)
    if not isinstance(token_pair, dict) or set(token_pair) != {'access_token', 'refresh_token'}:
        raise Rejected('Provide the private application token pair only.')
    if any(not isinstance(v, str) or not v or len(v) > 4096 or any(c.isspace() for c in v)
           for v in token_pair.values()):
        raise Rejected('Private token input is malformed; values withheld.')
    if type(not_before) not in (int, float) or not time.time() <= not_before <= time.time() + 3600:
        raise Rejected('Use a future activation check within one hour.')
    fingerprint = hashlib.sha256(json.dumps(token_pair, sort_keys=True).encode()).hexdigest()
    with locked(root) as path:
        if (path / 'tokens.json').exists():
            raise Rejected('An active Tencent token file already exists; inspect it before importing another identity.')
        file = path / 'private-token-import.json'
        if file.exists():
            old = json.loads(file.read_text())
            if old.get('import_id') != fingerprint or old.get('client_id') != str(cfg['client_id']):
                raise Rejected('A different private token import already exists; it was preserved.')
            return {'staged': True, 'not_before': old['not_before'], 'already_staged': True}
        save(file, dict(token_pair, import_id=fingerprint, client_id=str(cfg['client_id']),
                        not_before=not_before, staged_at=time.time()))
        return {'staged': True, 'not_before': not_before, 'already_staged': False}


def finish_private_token_import(root):
    """Exchange once after propagation, using returned lifetimes instead of guessing expiry."""
    cfg = load_config(root, require_accounts=False)
    with locked(root) as path:
        file = path / 'private-token-import.json'
        if not file.exists(): raise Rejected('No pending private token import.')
        pending = json.loads(file.read_text())
        if pending.get('client_id') != str(cfg['client_id']): raise Rejected('Private token import belongs to another application.')
        active = path / 'tokens.json'
        marker = path / 'private-token-refresh-pending.json'
        if active.exists():
            token = json.loads(active.read_text())
            if token.get('private_import_id') != pending['import_id']:
                raise Rejected('Another active Tencent identity exists; it was preserved.')
            marker.unlink(missing_ok=True)
            return {'imported': True, 'already_imported': True, 'received_at': token['received_at'],
                    'access_token_expires_in': token['access_token_expires_in'],
                    'refresh_token_expires_in': token['refresh_token_expires_in']}
        if time.time() < pending['not_before']:
            return {'imported': False, 'status': 'waiting_for_activation', 'not_before': pending['not_before']}
        if marker.exists() or pending.get('refresh_attempted'):
            raise Rejected('Private token refresh already attempted; inspect the saved outcome before another exchange.')
        pending['refresh_attempted'] = True
        save(file, pending)
        save(marker, {'started_at': time.time(), 'import_id': pending['import_id']})
        try:
            token = token_request(cfg, {'grant_type': 'refresh_token', 'refresh_token': pending['refresh_token']})
        except Rejected as error:
            pending.update(status='rejected', error=str(error));save(file, pending)
            marker.unlink();raise
        token['private_import_id'] = pending['import_id']
        save(active, token)
        pending.update(status='imported', received_at=token['received_at'])
        save(file, pending);marker.unlink()
        (path / 'oauth-state.json').unlink(missing_ok=True)
        return {'imported': True, 'already_imported': False, 'received_at': token['received_at'],
                'access_token_expires_in': token['access_token_expires_in'],
                'refresh_token_expires_in': token['refresh_token_expires_in']}


def authorize_url(root, cfg):
    with locked(root, cfg) as path:
        if (path / 'tokens.json').exists(): raise Rejected('Tencent profile is already authorized; its credentials were preserved. Use a new identity profile.')
        file = path / 'oauth-state.json'
        previous = json.loads(file.read_text()) if file.exists() else {}
        if previous.get('status') in ('exchange_pending', 'uncertain'):
            raise Rejected('Previous Tencent exchange is uncertain; inspect it before issuing another link.')
        if previous.get('status', 'issued') == 'issued' and time.time() < previous.get('expires_at', 0):
            raise Rejected('Tencent profile already has a live link; retrieve the original job.')
        prefix = 'txp1_' + cfg['_profile_id'] + '.' if cfg.get('_profile_id') else ''
        state = prefix + secrets.token_urlsafe(32)
        save(file, {'state_hash': hashlib.sha256(state.encode()).hexdigest(), 'expires_at': time.time() + 1800,
                    'client_id': str(cfg['client_id']), 'status': 'issued',
                    'token_remote_ip': token_remote_ip(cfg), 'token_host': token_host(cfg)})
    query = {'client_id': cfg['client_id'], 'redirect_uri': cfg['redirect_uri'], 'state': state}
    return 'https://developers.e.qq.com/oauth/authorize?' + urlencode(query)


def callback(root, query):
    if set(query) - {'state', 'authorization_code', 'error', 'error_description'}: raise Rejected('Unexpected Tencent callback fields.')
    given = query.get('state', '')
    profile_id = None
    if given.startswith('txp1_'):
        profile_id = profile_name(given[5:].split('.', 1)[0])
        if '.' not in given: raise Rejected('Invalid Tencent profile state.')
    cfg = load_config(root, require_accounts=False, profile_id=profile_id)
    with locked(root, cfg) as path:
        file = path / 'oauth-state.json'
        if not file.exists(): raise Rejected('No pending Tencent authorization; request a fresh link.')
        state = json.loads(file.read_text())
        digest = hashlib.sha256(given.encode()).hexdigest()
        if time.time() > state['expires_at'] or not secrets.compare_digest(digest, state['state_hash']): raise Rejected('Tencent state invalid or expired.')
        if state.get('client_id', str(cfg['client_id'])) != str(cfg['client_id']): raise Rejected('Tencent application changed after link creation.')
        if state.get('token_host', 'api.e.qq.com') != token_host(cfg):
            raise Rejected('Tencent OAuth token host changed after link creation; request a fresh link.')
        if state.get('token_remote_ip') != token_remote_ip(cfg):
            raise Rejected('Tencent OAuth remote address changed after link creation; request a fresh link.')
        if state.get('status', 'issued') != 'issued' or (path / 'tokens.json').exists():
            raise Rejected('Tencent state was already consumed; existing credentials were preserved.')
        if query.get('error') or not query.get('authorization_code'):
            state['status'] = 'denied';save(file, state)
            raise Rejected('Tencent authorization was not granted.')
        state['status'] = 'exchange_pending';save(file, state)
        try:
            token = token_request(cfg, {'grant_type': 'authorization_code', 'authorization_code': query['authorization_code'], 'redirect_uri': cfg['redirect_uri']})
        except Rejected as error:
            state['status'] = 'rejected'
            if isinstance(error, OAuthRejected):
                state['provider_error_code'] = error.provider_code
                state['provider_diagnostic'] = error.diagnostic
                state['exchange_completed_at'] = time.time()
            save(file, state)
            raise
        except Exception:
            state['status'] = 'uncertain';save(file, state);raise
        token['client_id'] = str(cfg['client_id'])
        save(path / 'tokens.json', token)
        state['status'] = 'authorized';save(file, state)
        (path / 'refresh-pending.json').unlink(missing_ok=True)
    return {'authorized': True, 'provider': 'tencent', 'profile_id': profile_id,
            'management_enabled': bool(cfg.get('accounts')),
            'message': 'Authorization completed. Tokens saved in the selected profile; existing profiles preserved. Return to the chat to verify accounts.'}


def operator_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{2,47}', value):
        raise Rejected('Use a local operator ID of 3-48 lowercase letters, digits, underscore or hyphen.')
    return value


def operator_credential(cfg, account_id=None, operator_id=None):
    account = cfg.get('accounts', {}).get(str(account_id), {})
    selected = operator_id if operator_id is not None else account.get('operator_id')
    if selected is not None:
        operator_name(selected)
        credential = cfg.get('operators', {}).get(selected)
        if not credential: raise Rejected('Tencent operator is not configured in the selected profile.')
    else:
        credential = account  # Legacy per-account credentials remain readable; never guess another account.
    return credential


def valid_operator(credential):
    return bool(credential.get('user_token')) and (credential.get('user_token_expires_at') is None or credential['user_token_expires_at'] > time.time())


def require_organization(result, account_ids):
    data = result.get('data') or {}; rows = data.get('list')
    if result.get('code') != 0 or not isinstance(rows, list):
        raise Rejected('Tencent operator organization verification failed; no permission fallback.')
    if (len(rows) != len(account_ids) or {r.get('account_id') for r in rows} != set(account_ids)
            or any(r.get('authentication_status') != 'AUTHENTICATION_STATUS_AUTHENTICATED' for r in rows)):
        raise Rejected('Tencent operator is not organization-authenticated for every selected account.')


def operator_authorize_url(root, cfg, operator_id):
    operator_name(operator_id)
    return user_authorize_url(root, cfg, operator_id=operator_id)


def user_authorize_url(root, cfg, account_id=None, *, operator_id=None):
    """Owner-only link issuance for an already scoped account; no advertising write."""
    if not cfg.get('_profile_id'):
        raise Rejected('Select an explicit Tencent identity profile.')
    account_id = str(account_id) if account_id is not None else None
    if operator_id is not None: operator_name(operator_id)
    if operator_id is None and account_id not in cfg.get('accounts', {}):
        raise Rejected('Tencent user authorization account is outside scope.')
    with locked(root, cfg) as path:
        if not (path / 'tokens.json').exists():
            raise Rejected('Complete Tencent application OAuth first.')
        file = path / 'user-authorization.json'
        previous = json.loads(file.read_text()) if file.exists() else {}
        if previous.get('status') == 'issued' and previous.get('expires_at', 0) > time.time():
            raise Rejected('A live user authorization link exists; retrieve the owner receipt.')
        state = 'txu1_' + cfg['_profile_id'] + '.' + secrets.token_urlsafe(32)
        callback_url = cfg['redirect_uri'].replace('/oauth/callback', '/user/callback')
        expires_at = int(time.time()) + 1800
        save(file, {'state_hash': hashlib.sha256(state.encode()).hexdigest(),
                    'expires_at': expires_at, 'client_id': str(cfg['client_id']),
                    **({'operator_id': operator_id} if operator_id is not None else {'account_id': account_id}), 'status': 'issued'})
    return {'authorization_url': 'https://ad.qq.com/account-center/single/user-authorize?' +
            urlencode({'redirect_uri': callback_url, 'state': state}), 'expires_at': expires_at,
            'profile_id': cfg['_profile_id'], **({'operator_id': operator_id} if operator_id is not None else {'account_id': account_id})}


def user_callback(root, query):
    """Receive Tencent's operator credential without returning it or enabling writes."""
    if set(query) - {'state', 'user_status', 'user_token', 'expire_time', 'wx_id'}:
        raise Rejected('Unexpected Tencent user callback fields.')
    given = query.get('state', '')
    if not isinstance(given, str) or not given.startswith('txu1_') or '.' not in given:
        raise Rejected('Invalid Tencent user callback state.')
    profile_id = profile_name(given[5:].split('.', 1)[0])
    cfg = load_config(root, profile_id=profile_id)
    with locked(root, cfg) as path:
        file = path / 'user-authorization.json'
        if not file.exists(): raise Rejected('No pending Tencent user authorization.')
        state = json.loads(file.read_text())
        if (state.get('status') != 'issued' or time.time() > state.get('expires_at', 0)
                or state.get('client_id') != str(cfg['client_id'])
                or not secrets.compare_digest(hashlib.sha256(given.encode()).hexdigest(), state.get('state_hash', ''))
                or (not state.get('operator_id') and state.get('account_id') not in cfg['accounts'])):
            raise Rejected('Tencent user state expired, consumed or mismatched.')
        status = query.get('user_status')
        if status not in ('0', '1', '2'): raise Rejected('Invalid Tencent user verification status.')
        if status != '2':
            state.update(status='incomplete', user_status=int(status), completed_at=time.time())
            save(file, state)
            return {'user_authorized': False, 'user_status': int(status), 'profile_id': profile_id,
                    'message': 'Tencent operator verification is incomplete. Complete verification and request a fresh link.'}
        token = query.get('user_token', '')
        expiry = query.get('expire_time', '')
        if (not isinstance(token, str) or not 1 <= len(token.encode()) <= 128
                or any(not 33 <= ord(c) <= 126 for c in token)
                or not isinstance(expiry, str) or not re.fullmatch(r'[0-9]{1,12}', expiry)
                or int(expiry) <= time.time()):
            raise Rejected('Tencent operator credential is missing, malformed or expired.')
        # Read current configuration under the same lock; preserve account scope and write switch.
        current = json.loads((path / 'config.json').read_text())
        if state.get('operator_id'):
            name = operator_name(state['operator_id'])
            credential = current.setdefault('operators', {}).setdefault(name, {})
        else:
            credential = current['accounts'][state['account_id']]
        credential.update(user_token=token, user_token_expires_at=int(expiry))
        save(path / 'config.json', current)
        state.update(status='authorized', user_status=2, completed_at=time.time(), token_expires_at=int(expiry))
        save(file, state)
    return {'user_authorized': True, 'user_status': 2, 'provider': 'tencent', 'profile_id': profile_id,
            **({'operator_id': state['operator_id']} if state.get('operator_id') else {'account_id': state['account_id']}), 'expires_at': int(expiry),
            'message': 'Operator credential saved securely. Return to the chat to continue the paused advertisement test.'}


class API:
    def __init__(self, root, cfg): self.root, self.cfg = Path(root), cfg

    def organization_authentication(self, operator_id, account_ids):
        return self('user_organization_authentication/get', {'account_id_list': account_ids,
            'fields': ['account_id', 'authentication_status']}, operator_id=operator_id)

    def __call__(self, endpoint, params, post=False, upload=None, *, operator_id=None):
        allowed = {'adgroups/get', 'adgroups/add', 'adgroups/update', 'adgroups/delete',
                   'dynamic_creatives/get', 'dynamic_creatives/add', 'dynamic_creatives/update', 'dynamic_creatives/delete',
                   'daily_reports/get', 'hourly_reports/get', 'funds/get', 'advertiser/get',
                   'images/add', 'videos/add', 'images/get', 'videos/get', 'conversions/get', 'user_organization_authentication/get', 'organization_account_relation/get'}
        if endpoint not in allowed: raise Rejected('Tencent endpoint is not enabled.')
        token = access_token(self.root, self.cfg)
        common = {'access_token': token, 'timestamp': int(time.time()), 'nonce': uuid.uuid4().hex}
        headers = {};body = None;data = dict(params)
        if endpoint == 'user_organization_authentication/get':
            if post or operator_id is None or 'user_token' in data: raise Rejected('Select an operator without passing credentials.')
            credential = operator_credential(self.cfg, operator_id=operator_id)
            if not valid_operator(credential): raise Rejected('Tencent operator credential missing or expired; verify the operator once.')
            data['user_token'] = credential['user_token']
        if post:
            account = self.cfg['accounts'][str(params['account_id'])]
            credential = operator_credential(self.cfg, params['account_id'])
            if account.get('operator_id'):
                if not valid_operator(credential): raise Rejected('Tencent operator credential missing or expired; verify the operator once.')
                require_organization(self.organization_authentication(account['operator_id'], [params['account_id']]), [params['account_id']])
            if credential.get('user_token'):
                if not valid_operator(credential): raise Rejected('Tencent operator credential expired; request fresh operator verification.')
                common['user_token'] = credential['user_token']
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
