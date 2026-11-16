"""Run locally on the management server as its service user. Never prints credentials."""
import argparse
import json
import os
from pathlib import Path
import tencent_runtime as runtime


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    sub=p.add_subparsers(dest='op',required=True)
    issue=sub.add_parser('issue');issue.add_argument('member');issue.add_argument('--template-profile',required=True)
    issue.add_argument('--out',type=Path,required=True)
    revoke=sub.add_parser('revoke');revoke.add_argument('member')
    a=p.parse_args()
    if a.op=='issue':
        fd=os.open(a.out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w') as out:
                json.dump(runtime.provision_member(a.root,a.member,template_profile=a.template_profile),out)
        except Exception:
            a.out.unlink(missing_ok=True)
            raise
        print('Personal connection saved to the specified private file.')
    else:
        runtime.member_key(a.root,a.member)
        with runtime.locked(a.root,{'_profile_id':a.member}) as folder:
            (folder/'member.key.json').unlink()
        print('Member connection revoked; queued jobs will recheck access.')


if __name__=='__main__':main()
