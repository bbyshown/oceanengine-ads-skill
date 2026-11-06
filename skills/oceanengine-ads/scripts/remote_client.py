"""Signed management-gateway transport. Local read-only mode is a client guard, not server RBAC."""
import hashlib
import hmac
import json
import time
import uuid
from urllib.request import Request, build_opener, HTTPRedirectHandler

import settings

READS={'status','inventory','accounts','workbench','projects','promotions','avatar','game_links',
       'report_config','report','cover','aweme_auth','goals','deep_bid','account_preflight',
       'account_budget','change_history','creation_status','discover_accounts','oauth_profile_status'}
WRITES={'new_project','new_ad','new_campaign','resume_creation','create_paused_ad','update_paused_ad',
        'set_project_status','set_ad_status','set_project_budget','set_ad_budget','set_account_budget',
        'set_project_bid','set_ad_bid','set_project_schedule','set_ad_schedule','set_project_dates',
        'update_ad','delete_ads','delete_projects','upload_image','upload_video','upload_avatar','upload_audio','create_carousel',
        'submit_avatar','set_click_tracking','ensure_game_asset','ensure_game_events','register_account','oauth_profile_authorize'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def request(route,payload):
    cfg=settings.load()
    if route not in ('jobs','job'):raise ValueError('Only signed job submission and job inspection are supported.')
    if route=='jobs':
        if set(payload)!={'op','args','idempotency_key'} or payload['op'] not in READS|WRITES:raise ValueError('Unsupported management operation.')
        if cfg['access_mode']=='read_only' and payload['op'] not in READS:
            raise PermissionError('Local profile is read_only. An authorized administrator must configure operator access for edits.')
        if not isinstance(payload['args'],dict):raise ValueError('Operation args must be an object.')
        args=dict(payload['args']);selected=settings.select_account(args.get('account_id'),cfg)
        if payload['op'] in {'discover_accounts','register_account','oauth_profile_authorize','oauth_profile_status'}:
            # Installation-level enrollment must work before the first account is selected server-side.
            args.pop('account_id',None)
        else:args['account_id']=selected
        payload=dict(payload,args=args)
    elif set(payload)!={'job_id'}:raise ValueError('Use job_id only.')
    path='/manage/v1/'+route
    body=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    if len(body) > 140 * 1024 * 1024:raise ValueError('Request exceeds the 140 MiB gateway body limit.')
    stamp,nonce=str(int(time.time())),uuid.uuid4().hex
    message=('POST\n'+path+'\n'+stamp+'\n'+nonce+'\n'+hashlib.sha256(body).hexdigest()).encode()
    signature=hmac.new(bytes.fromhex(cfg['key']),message,hashlib.sha256).hexdigest()
    req=Request(cfg['base_url'].rstrip('/')+path,data=body,method='POST',headers={
        'Content-Type':'application/json','X-Manage-Time':stamp,'X-Manage-Nonce':nonce,'X-Manage-Signature':signature})
    with build_opener(NoRedirect()).open(req,timeout=45) as response:return json.load(response)


def submit(op,args,key=None):
    return request('jobs',{'op':op,'args':args,'idempotency_key':key or uuid.uuid4().hex})
