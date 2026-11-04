"""Machine-local connection and account selection. No production defaults."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def config_path():
    return Path(os.environ.get('OCEANENGINE_MANAGEMENT_CONFIG',
        str(Path.home()/'.config/oceanengine-ads/connection.json'))).expanduser()


def workspace_state():
    return Path(os.environ.get('OCEANENGINE_ADS_HOME',str(Path.cwd()/'.oceanengine-ads'))).expanduser().resolve()


def accounts(config):
    values=config.get('accounts')
    if not isinstance(values,dict) or not values:raise ValueError('Configure at least one account alias.')
    out={}
    for alias,row in values.items():
        if not isinstance(alias,str) or not alias.strip() or not isinstance(row,dict):raise ValueError('Invalid account alias.')
        value=row.get('id')
        if type(value) is bool or not re.fullmatch('[1-9][0-9]*',str(value or '')):raise ValueError('Account IDs must be positive decimal strings.')
        out[alias]=int(value)
    if len(set(out.values()))!=len(out):raise ValueError('Each account ID must have one unambiguous alias.')
    if config.get('default_account') not in out:raise ValueError('Choose a configured default_account alias.')
    return out


def validate(config):
    if not isinstance(config,dict):raise ValueError('Connection configuration must be a JSON object.')
    url=urlsplit(config.get('base_url',''))
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('','/'):
        raise ValueError('base_url must be an HTTPS origin without credentials, path, query or fragment.')
    if not re.fullmatch('[a-fA-F0-9]{64}',str(config.get('key',''))):raise ValueError('A 64-hex-character management pairing key is required.')
    if config.get('access_mode') not in ('read_only','operator'):raise ValueError('Choose read_only or operator access_mode.')
    accounts(config)
    return config


def load(path=None):
    p=Path(path) if path is not None else config_path()
    if not p.exists():raise ValueError('Connection not configured. Run scripts/setup.py configure; never paste keys into chat.')
    if os.name=='posix' and p.stat().st_mode & 0o077:
        raise ValueError('Connection file permissions must be 0600; run chmod 600 on the local configuration file.')
    return validate(json.loads(p.read_text()))


def select_account(ref=None, config=None):
    config=load() if config is None else config
    available=accounts(config)
    if ref is None:return available[config['default_account']]
    if str(ref) in available:return available[str(ref)]
    matches=[i for i in available.values() if str(i)==str(ref)]
    if len(matches)!=1:raise ValueError('Select one configured account alias or exact ID.')
    return matches[0]
