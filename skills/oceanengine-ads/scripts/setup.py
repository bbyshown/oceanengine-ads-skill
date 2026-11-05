"""Configure this machine without committing or displaying the management key."""
import argparse
import getpass
import json
from pathlib import Path
import os

import settings


def write_config(path,config,overwrite=False):
    settings.validate(config);path=Path(path)
    if path.exists() and not overwrite:raise ValueError('Configuration already exists; inspect it before using --overwrite.')
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:f.write(json.dumps(config,ensure_ascii=False,indent=2))
    temporary.chmod(0o600);temporary.replace(path)


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    c=s.add_parser('configure');c.add_argument('--base-url',required=True);c.add_argument('--account',action='append',required=True,help='Alias=account_id; repeat for each account.')
    c.add_argument('--default-account',required=True);c.add_argument('--access',choices=['read_only','operator'],default='read_only')
    c.add_argument('--key-file',type=Path,help='Administrator-provided local key file; otherwise use a hidden terminal prompt.')
    c.add_argument('--config',type=Path,default=settings.config_path());c.add_argument('--overwrite',action='store_true')
    s.add_parser('doctor')
    s.add_parser('accounts',help='List provider-authorized accounts and gateway registration state.')
    a=s.add_parser('add-account',help='Register an authorized account and save its local alias after readback.')
    a.add_argument('entry',help='alias=account_id');a.add_argument('--run-id',required=True)
    a.add_argument('--dry-run',action='store_true')
    m=s.add_parser('monitor-config');m.add_argument('--account');m.add_argument('--project',required=True)
    m.add_argument('--promotion-id',type=int);m.add_argument('--overwrite',action='store_true')
    args=p.parse_args()
    if args.command=='configure':
        entries={}
        for pair in args.account:
            alias,sep,identifier=pair.partition('=')
            if not sep or alias in entries:raise ValueError('Use distinct Alias=account_id pairs.')
            entries[alias]={'id':identifier}
        key=args.key_file.read_text().strip() if args.key_file else getpass.getpass('Management pairing key (hidden): ').strip()
        cfg={'base_url':args.base_url,'key':key,'accounts':entries,'default_account':args.default_account,'access_mode':args.access}
        write_config(args.config,cfg,args.overwrite)
        print('Local configuration written with mode0600. No advertising settings changed.')
    elif args.command=='accounts':
        import ads
        print(json.dumps(ads.read('discover_accounts')['data'],ensure_ascii=False,indent=2))
    elif args.command=='add-account':
        import account_access
        print(json.dumps(account_access.add_account(args.entry,args.run_id,dry_run=args.dry_run),ensure_ascii=False,indent=2))
    elif args.command=='monitor-config':
        import ads
        selected=settings.select_account(args.account)
        inv=ads.read('inventory',client=ads.SelectedClient(selected))['data']
        project=ads.resolve(inv,args.project)
        candidates=ads.ads_for(inv,[project['project_id']])
        if args.promotion_id is not None:candidates=[a for a in candidates if a['promotion_id']==args.promotion_id]
        if len(candidates)!=1:raise ValueError('Choose one ad with --promotion-id.')
        example=Path(__file__).resolve().parent.parent/'references/monitor-policy.example.json'
        policy=json.loads(example.read_text());policy.update(account=str(selected),advertiser_id=selected,
            project_id=project['project_id'],promotion_id=candidates[0]['promotion_id'])
        target=settings.workspace_state()/'monitor-policy.json'
        if target.exists() and not args.overwrite:raise ValueError('Monitor policy exists; inspect it before --overwrite.')
        ads.save(target,policy)
        print(json.dumps({'monitor_policy':str(target),'mode':'read_only_alerts','automatic_pause':False,'account_id':selected},ensure_ascii=False))
    else:
        import ads
        cfg=settings.load();selected=settings.select_account()
        r=ads.read('status',client=ads.SelectedClient(selected))
        if r.get('account_id')!=selected:raise ValueError('Gateway returned a different account.')
        if r.get('version',0)<8:raise ValueError('A compatible management gateway version8 or later is required.')
        print(json.dumps({'configured':True,'selected_account_id':selected,'access_mode':cfg['access_mode'],
            'gateway_version':r.get('version'),'operations':r.get('operations',[])},ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as e:
        print(type(e).__name__+': '+str(e));raise SystemExit(1)
