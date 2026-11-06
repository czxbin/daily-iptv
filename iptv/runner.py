"""Daily discovery -> bounded probes -> protected atomic publication."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
from .playlist import CATEGORIES, Channel, parse_m3u, select_candidates
from .probe import fetch, probe, ProbeError, Result
from .publish import publish

SOURCE_LIMIT=8*1024*1024

def bounded_config(config):
    workers=config.get('workers',8)
    quotas=config.get('quotas',{})
    if type(workers) is not int or not 1<=workers<=12: raise ValueError('workers must be 1..12')
    if any(k not in CATEGORIES or type(v) is not int or not 0<=v<=200 for k,v in quotas.items()):
        raise ValueError('unknown category or invalid quota')
    if not 1<=sum(quotas.values())<=420: raise ValueError('total daily candidate budget must be 1..420')
    if not 1<=len(config.get('sources',[{}]))<=20: raise ValueError('sources must be 1..20')
    return config

def load_source(source):
    report={'name':source['name'],'url':source['url'],'region':source.get('region',''),'ok':False,'count':0,'rights':'unknown; community-listed URLs'}
    try:
        data,_=fetch(source['url'],SOURCE_LIMIT)
        if len(data)>=SOURCE_LIMIT: raise ProbeError('source_too_large')
        text=data.decode('utf-8-sig',errors='replace')
        if not text.lstrip().startswith('#EXTM3U'): raise ProbeError('invalid_source_playlist')
        channels=parse_m3u(text,source['url'],source.get('region',''))
        if not channels: raise ProbeError('empty_source')
        report.update(ok=True,count=len(channels))
        return channels,report
    except (ProbeError,KeyError,ValueError) as exc:
        report['error']=str(exc)
        return [],report

def bounded_probe(channel):
    # A hard process wall clock also covers slow HTTP headers and partial reads.
    code='import json,sys; from iptv.playlist import Channel; from iptv.probe import probe; print(json.dumps(probe(Channel(**json.load(sys.stdin))).to_dict()))'
    try:
        process=subprocess.run([sys.executable,'-c',code],input=json.dumps(channel.to_dict()).encode(),capture_output=True,timeout=35,check=False)
        if process.returncode: raise ValueError('probe child failed')
        return Result(**json.loads(process.stdout))
    except subprocess.TimeoutExpired:
        return Result(channel.to_dict(),False,'probe_wall_timeout',35000,{})
    except (OSError,ValueError,TypeError):
        return Result(channel.to_dict(),False,'probe_child_error',0,{})

def run(config,output):
    for tool in ('ffmpeg','ffprobe'):
        if not shutil.which(tool): raise RuntimeError(f'{tool} is required')
    bounded_config(config)
    now=datetime.now(timezone.utc)
    checked_at=now.isoformat(timespec='seconds').replace('+00:00','Z')
    channels=[]; sources=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(load_source,s) for s in config['sources']]
        for future in as_completed(futures):
            items,report=future.result()
            channels.extend(items); sources.append(report)
            print(f'Source {report["name"]}: {len(items)} candidates; ok={report["ok"]}',flush=True)
    channels.sort(key=lambda c:(c.source,c.url))
    sources.sort(key=lambda s:s['name'])
    chosen=select_candidates(channels,config['quotas'],now.date(),2)
    print(f'Discovered {len(set(c.url for c in channels))} URLs; checking {len(chosen)}.',flush=True)
    results=[]; observed=set()
    with ThreadPoolExecutor(max_workers=config.get('workers',8)) as pool:
        futures=[pool.submit(bounded_probe,c) for c in chosen]
        try:
            for future in as_completed(futures,timeout=20*60):
                result=future.result(); results.append(result); observed.add(future)
                if len(results)%20==0 or len(results)==len(chosen):
                    print(f'Checked {len(results)}/{len(chosen)}; passed {sum(r.ok for r in results)}',flush=True)
        except FuturesTimeout:
            cancelled=sum(f.cancel() for f in futures if f not in observed)
            print(f'Batch time budget reached; {cancelled} queued probes skipped.',flush=True)
    # Running children finish within 35 seconds; cancelled ones were not tested.
    for future in futures:
        if future not in observed and not future.cancelled(): results.append(future.result())
    results.sort(key=lambda r:(r.channel['category'],r.channel['name'],r.channel['url']))
    report=publish(Path(output),results,sources,checked_at,len(set(c.url for c in channels)))
    print(json.dumps({k:report[k] for k in ('published','hold_reason','tested','passed','category_counts','playlist_count')},ensure_ascii=False),flush=True)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='config/sources.json')
    parser.add_argument('--output',default='public')
    args=parser.parse_args()
    try:
        report=run(json.loads(Path(args.config).read_text(encoding='utf-8')),args.output)
    except Exception as exc:
        print(f'Fatal: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 1
    # Exit 2 signals degraded/held publication; workflow commits diagnostic reports first.
    return 0 if report['published'] else 2

if __name__=='__main__': raise SystemExit(main())
