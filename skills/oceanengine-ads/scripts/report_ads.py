"""Fetch a scoped daily/hourly game report using metadata supplied by the gateway."""
import argparse
from datetime import datetime
import json
import time
from zoneinfo import ZoneInfo

import ads
import settings

WANTED=['stat_cost','show_cnt','click_cnt','ctr','cpc_platform','active','active_cost',
        'active_rate','attribution_convert_cnt','attribution_micro_game_0d_ltv',
        'attribution_micro_game_0d_roi','attribution_micro_game_7d_roi']


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--full-output',action='store_true');p.add_argument('--account');p.add_argument('--project',required=True)
    p.add_argument('--promotion-id',type=int);p.add_argument('--date',help='YYYY-MM-DD; defaults to today in the chosen timezone.')
    p.add_argument('--timezone',default='Asia/Shanghai');p.add_argument('--hourly',action='store_true');args=p.parse_args()
    tz=ZoneInfo(args.timezone);day=args.date or datetime.now(tz).date().isoformat()
    if datetime.strptime(day,'%Y-%m-%d').date().isoformat()!=day:raise ValueError('Use YYYY-MM-DD.')
    selected=settings.select_account(args.account);client=ads.SelectedClient(selected)
    inv=ads.read('inventory',client=client)['data'];project=ads.resolve(inv,args.project)
    if args.promotion_id is not None and not any(a['promotion_id']==args.promotion_id for a in ads.ads_for(inv,[project['project_id']])):
        raise ValueError('Ad does not belong to the selected project/account.')
    cache=ads.ROOT/'data'/('report-config-'+str(selected)+'.json')
    stored=json.loads(cache.read_text()) if cache.exists() else {}
    if time.time()-stored.get('checked_at',0)>86400:
        metadata=ads.read('report_config',{'data_topics':['BASIC_DATA']},client=client)
        stored={'checked_at':time.time(),'metadata':metadata};ads.save(cache,stored)
    topic=next(t for t in stored['metadata']['data']['list'] if t['data_topic']=='BASIC_DATA')
    names={m['field']:m for m in topic['metrics']};metrics=[m for m in WANTED if m in names]
    if not {'stat_cost','show_cnt','click_cnt','active'}<=set(metrics):raise ValueError('Core metrics unavailable; do not replace missing fields with zeros.')
    calendar='stat_time_hour' if args.hourly else 'stat_time_day'
    filters=[{'field':'cdp_project_id','type':2,'operator':7,'values':[str(project['project_id'])]}]
    if args.promotion_id is not None:filters.append({'field':'cdp_promotion_id','type':2,'operator':7,'values':[str(args.promotion_id)]})
    query={'data_topic':'BASIC_DATA','dimensions':['cdp_project_id','cdp_promotion_id',calendar],
        'metrics':metrics,'filters':filters,'start_time':day+' 00:00:00','end_time':day+' 23:59:59',
        'order_by':[{'field':calendar,'type':'ASC'}],'page':1,'page_size':100}
    rows=[];response=None
    for page in range(1,1001):
        query['page']=page;response=ads.read('report',query,client=client)
        data=response.get('data') or {}
        if not isinstance(data.get('total_metrics'),dict):raise ValueError('Report totals missing; not treating failure as zero.')
        for row in data.get('rows',[]):
            dims=row.get('dimensions',{})
            if str(dims.get('cdp_project_id'))!=str(project['project_id']):raise ValueError('Report returned a different project.')
            if args.promotion_id is not None and str(dims.get('cdp_promotion_id'))!=str(args.promotion_id):raise ValueError('Report returned a different ad.')
            rows.append(row)
        if page>=data.get('page_info',{}).get('total_page',0):break
    else:raise ValueError('Report pagination limit reached.')
    result={'account_id':selected,'project_id':project['project_id'],'date':day,'timezone':args.timezone,
        'rows':rows,'total_metrics':response['data']['total_metrics'],'request_id':response.get('request_id'),
        'metric_definitions':{k:{x:names[k].get(x) for x in ('name','description')} for k in metrics}}
    target=ads.ROOT/'data/reports'/str(selected)/day/('hourly.json' if args.hourly else 'daily.json')
    ads.save(target,result)
    output = result if args.full_output else {k:v for k,v in result.items() if k != 'metric_definitions'}
    ads.operation_output.print_json(dict(output, details_file=str(target)), args.full_output)


if __name__=='__main__':
    try:main()
    except Exception as e:print(type(e).__name__+': '+str(e));raise SystemExit(1)
