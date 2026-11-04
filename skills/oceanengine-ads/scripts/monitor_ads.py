"""Read-only monitoring. This entrypoint never submits an advertising mutation."""
import argparse
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import ads

ROOT=ads.ROOT
POLICY=ROOT/'monitor-policy.json'
STORE=ROOT/'data/monitor'
READS={'inventory','report'}


def read(op,args,client):
    if op not in READS:raise ValueError('Monitor is restricted to inventory/report reads.')
    return ads.read(op,args,client=client)


def number(metrics,key):
    if key not in metrics or metrics[key] in (None,'','--'):raise ValueError('Metric unavailable: '+key)
    try:value=Decimal(str(metrics[key]))
    except InvalidOperation:raise ValueError('Invalid metric: '+key)
    if not value.is_finite() or value<0:raise ValueError('Invalid metric: '+key)
    return float(value)


def fetch(policy,client,now):
    inv=read('inventory',{},client)['data']
    if inv['advertiser_id']!=policy['advertiser_id']:raise ValueError('Monitor account mismatch.')
    project=next((p for p in inv['projects'] if p['project_id']==policy['project_id']),None)
    ad=next((a for a in inv['ads'] if a['promotion_id']==policy['promotion_id']),None)
    if project is None or ad is None:
        return {'date':now.date().isoformat(),'checked_at':now.isoformat(),'target_missing':True}
    if ad['project_id']!=project['project_id']:raise ValueError('Monitor project/ad mismatch.')
    day=now.date().isoformat()
    request={'data_topic':'BASIC_DATA','dimensions':['cdp_project_id','cdp_promotion_id','stat_time_day'],
        'metrics':['stat_cost','show_cnt','click_cnt','active','attribution_micro_game_0d_ltv','attribution_micro_game_0d_roi'],
        'filters':[{'field':'cdp_promotion_id','type':2,'operator':7,'values':[str(policy['promotion_id'])]}],
        'start_time':day+' 00:00:00','end_time':day+' 23:59:59',
        'order_by':[{'field':'stat_time_day','type':'ASC'}],'page':1,'page_size':100}
    report=read('report',request,client)
    data=report.get('data') or {};metrics=data.get('total_metrics')
    if not isinstance(metrics,dict):raise ValueError('Report total_metrics missing; not treating a failed report as zero.')
    if data.get('page_info',{}).get('total_page',0)>1:raise ValueError('Unexpected monitor report pagination.')
    for row in data.get('rows',[]):
        dims=row.get('dimensions',{})
        if str(dims.get('cdp_project_id'))!=str(policy['project_id']) or str(dims.get('cdp_promotion_id'))!=str(policy['promotion_id']):
            raise ValueError('Report returned a different ad.')
    snap={'date':day,'checked_at':now.isoformat(),'target_missing':False,
        'cost':number(metrics,'stat_cost'),'impressions':number(metrics,'show_cnt'),
        'clicks':number(metrics,'click_cnt'),'activations':number(metrics,'active'),
        'revenue':number(metrics,'attribution_micro_game_0d_ltv'),
        'roi':number(metrics,'attribution_micro_game_0d_roi'),
        'project_switch':project['opt_status'],'ad_switch':ad['opt_status'],
        'ad_status':ad.get('status'),'status_reasons':ad.get('status_second') or [],
        'daily_budget':(project.get('delivery_setting') or {}).get('budget'),
        'roi_coefficient':(project.get('delivery_setting') or {}).get('roi_goal'),
        'request_id':report.get('request_id')}
    return snap


def evaluate(policy,previous,snapshot,stamp):
    state=dict(previous);prior=previous.get('last_snapshot')
    state.setdefault('started_at',stamp);state['read_failures']=0
    old=set(previous.get('active_alerts',[]));events={};a=policy['alerts']
    def add(key,message):events[key]=message
    if snapshot.get('target_missing'):
        add('target_missing','监控目标已不在账户列表中，请确认是否删除或变更；不会自动转移到其他广告。')
    else:
        enabled=snapshot['project_switch']=='ENABLE' and snapshot['ad_switch']=='ENABLE'
        no_delivery=enabled and snapshot['impressions']==0 and snapshot['cost']==0
        since=previous.get('no_delivery_since')
        if no_delivery:
            since=stamp if since is None else since
            if stamp-since>=a['no_delivery_hours']*3600:
                add('no_delivery',f"连续观察至少{a['no_delivery_hours']}小时仍未记录曝光和消耗，需要排查起量条件。")
        else:since=None
        state['no_delivery_since']=since
        if prior and not prior.get('target_missing'):
            same_day=prior['date']==snapshot['date']
            if same_day and prior['impressions']==0 and prior['cost']==0 and (snapshot['impressions']>0 or snapshot['cost']>0):
                add('delivery_started','开始记录曝光或消耗，本轮起量情况有变化。')
            if (prior.get('project_switch'),prior.get('ad_switch'),prior.get('ad_status'))!=(snapshot['project_switch'],snapshot['ad_switch'],snapshot['ad_status']):
                add('status_changed','项目、广告开关或审核/投放状态发生变化，请查看当前状态。')
            if prior.get('roi_coefficient')!=snapshot.get('roi_coefficient') or prior.get('daily_budget')!=snapshot.get('daily_budget'):
                add('settings_changed','项目的预算或ROI系数发生变化，监控已记录新设置。')
        if enabled and snapshot.get('ad_status') not in ('OK',None):
            add('delivery_blocked','广告当前存在投放/审核状态提示：'+str(snapshot.get('ad_status')))
        if snapshot['cost']>=a['spend_without_activation_yuan'] and snapshot['activations']==0:
            add('spend_without_activation',f"当日消耗已达{a['spend_without_activation_yuan']}元但仍未记录激活，需要人工复核效果及回传。")
        eligible=(stamp-state['started_at']>=a['low_roi_min_observation_hours']*3600
            and snapshot['cost']>=a['low_roi_min_cost_yuan'] and snapshot['activations']>=a['low_roi_min_activations']
            and snapshot['roi']<a['low_roi_ratio'])
        same_day=prior is not None and prior.get('date')==snapshot['date']
        spaced=stamp-previous.get('last_success_at',0)>=25*60
        hits=previous.get('low_roi_hits',0) if same_day else 0
        if not eligible:hits=0
        elif not hits or spaced:hits+=1
        state['low_roi_hits']=hits
        if eligible and hits>=a['low_roi_consecutive_checks']:
            add('low_roi',f"消耗和样本达到观察线后，首日ROI连续{a['low_roi_consecutive_checks']}次偏低；需结合回传时效人工评估。")
        budget=snapshot.get('daily_budget')
        if budget and budget>0 and snapshot['cost']>=float(budget)*a['budget_used_ratio']:
            add('budget_near',f"当日消耗达到项目日预算{a['budget_used_ratio']:.0%}，请关注预算使用情况。")
    state['last_snapshot']=snapshot;state['last_success_at']=stamp
    # A single change is reported once. Ongoing conditions are re-armed only after resolution.
    changes={'delivery_started','status_changed','settings_changed'}
    alerts=[{'code':k,'message':v} for k,v in events.items() if k not in old or k in changes]
    state['active_alerts']=sorted(set(events)-changes)
    return state,alerts


def run(policy_path=POLICY,store=STORE,client=None,now=None):
    policy=json.loads(Path(policy_path).read_text())
    if policy.get('mode')!='read_only_alerts' or policy.get('automatic_pause') is not False:raise ValueError('Only read-only monitoring is installed.')
    if policy['advertiser_id']!=ads.select_account(policy['account']):raise ValueError('Monitor policy account mismatch.')
    now=now or datetime.now(ZoneInfo(policy['timezone']));stamp=now.timestamp()
    client=client or ads.SelectedClient(policy['advertiser_id'])
    store=Path(store);state_path=store/('state-'+str(policy['account'])+'-'+str(policy['promotion_id'])+'.json')
    previous=json.loads(state_path.read_text()) if state_path.exists() else {}
    try:
        snap=fetch(policy,client,now);state,alerts=evaluate(policy,previous,snap,stamp)
        result={'status':'ok','mode':'read_only_alerts','advertiser_id':policy['advertiser_id'],
            'project_id':policy['project_id'],'promotion_id':policy['promotion_id'],'checked_at':now.isoformat(),
            'snapshot':snap,'alerts':alerts,'should_report':bool(alerts),'baseline_created':not previous,'ad_mutations_performed':False}
    except Exception as error:
        state=dict(previous);state['read_failures']=previous.get('read_failures',0)+1
        alerted=previous.get('read_failure_alerted',False)
        notify=state['read_failures']>=policy['alerts']['consecutive_read_failures'] and not alerted
        state['read_failure_alerted']=alerted or notify
        result={'status':'read_failed','checked_at':now.isoformat(),'mode':'read_only_alerts','advertiser_id':policy['advertiser_id'],
            'error_type':type(error).__name__,'error':str(error),'consecutive_failures':state['read_failures'],
            'alerts':[{'code':'read_failed','message':f"连续{state['read_failures']}次监控读取失败，需要检查服务、授权或网络；保留上次成功数据。"}] if notify else [],
            'should_report':notify,'ad_mutations_performed':False}
    if result['status']=='ok':state['read_failure_alerted']=False
    ads.save(state_path,state)
    log=store/now.date().isoformat()/(now.strftime('%H%M%S')+'-'+str(policy['account'])+'.json');ads.save(log,result)
    ads.save(store/'latest.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true',required=True)
    parser.add_argument('--policy',type=Path,default=POLICY);args=parser.parse_args()
    print(json.dumps(run(args.policy),ensure_ascii=False,indent=2))
