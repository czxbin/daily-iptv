"""Atomic artifacts and per-category last-known-good protection."""
from collections import Counter
from pathlib import Path
from dataclasses import replace
import json
import os
from .playlist import CATEGORIES, Channel, render_m3u

FILES={'央视':'cctv.m3u','卫视':'satellite.m3u','港澳台':'hmt.m3u','海外':'international.m3u','其他中文':'other-chinese.m3u'}

def write_atomic(path, text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(text,encoding='utf-8')
    os.replace(tmp,path)

def save_json(path,value):
    write_atomic(path,json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def read_json(path,default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError): return default

def publish(output, results, sources, checked_at, discovered):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    previous=read_json(output/'status.json',{})
    previous_channels=[Channel(**c) for c in read_json(output/'published_channels.json',[])]
    passed=[Channel(**r.channel) for r in results if r.ok]
    last_count=previous.get('playlist_count',0)
    source_ok=sum(bool(s.get('ok')) for s in sources)
    reason=''
    if not passed: reason='no_valid_streams'
    elif sources and source_ok/len(sources)<0.5: reason='source_outage'
    elif last_count>=10 and len(passed)<last_count*0.3: reason='large_count_drop'
    updated=not reason
    counts=dict(Counter(c.category for c in passed))
    category_status={}; combined=[]; display=[]
    for category,filename in FILES.items():
        old=[c for c in previous_channels if c.category==category]
        fresh=[c for c in passed if c.category==category]
        old_status=previous.get('category_status',{}).get(category,{})
        hold=reason
        if not hold and old and not fresh: hold='no_valid_streams_in_category'
        if not hold and len(old)>=5 and len(fresh)<len(old)*0.3: hold='large_category_drop'
        chosen=old if hold else fresh
        last_success=old_status.get('last_success_utc') if hold else (checked_at if fresh else None)
        stale=bool(hold and old)
        category_status[category]={'current_passed':len(fresh),'playlist_count':len(chosen),'last_success_utc':last_success,'stale':stale,'hold_reason':hold,'missing':not chosen}
        combined.extend(chosen)
        display.extend([replace(c,name=f'{c.name}（旧源，最后验证 {last_success}）') for c in chosen] if stale else chosen)
        # Leave a held category file byte-for-byte unchanged.
        if updated and not hold: write_atomic(output/filename,render_m3u(chosen,checked_at))
    if updated:
        write_atomic(output/'live.m3u',render_m3u(display,checked_at))
        save_json(output/'published_channels.json',[c.to_dict() for c in combined])
    stale=bool(reason) or any(s['stale'] for s in category_status.values())
    published_counts=dict(Counter(c.category for c in combined)) if updated else previous.get('published_category_counts',{})
    report={
        'schema_version':1,'checked_at_utc':checked_at,
        'last_success_utc':checked_at if updated else previous.get('last_success_utc'),
        'published':updated,'stale':stale,'hold_reason':reason,
        'discovered_unique':discovered,'tested':len(results),'passed':len(passed),
        'playlist_count':len(combined) if updated else last_count,
        'category_counts':counts,'published_category_counts':published_counts,'category_status':category_status,
        'missing_categories':[c for c in CATEGORIES if not counts.get(c)],
        'failure_reasons':dict(Counter(r.reason for r in results if not r.ok)),
        'sources':sources,
        'verification':'A video frame decoded from a bounded media sample. Not a continuous playback, licensing, or user-network guarantee.',
        'probe_location':'GitHub-hosted runner' if os.environ.get('GITHUB_ACTIONS')=='true' else 'Local/cloud development network',
        'rights_notice':'Community URLs; redistribution/viewing rights unknown unless independently verified. No media is stored or redistributed.',
        'source_dependency':'All configured directories currently share iptv-org as upstream; they are not independent redundancy or a whole-web search.',
    }
    save_json(output/'status.json',report)
    save_json(output/'results.json',[r.to_dict() for r in results])
    stamp=checked_at.replace(':','').replace('-','')
    save_json(output/'history'/f'{stamp}.json',report)
    for path in sorted((output/'history').glob('*.json'))[:-30]: path.unlink()
    summary=['# 每日检测状态','',f'检测时间（UTC）：{checked_at}',f'最近更新列表时间（UTC）：{report["last_success_utc"] or "尚无"}',f'当前订阅条目：{report["playlist_count"]}',f'本次通过 / 检测：{len(passed)} / {len(results)}',f'状态：{"已更新" if updated else "保留上一份列表"}{"，包含未重新通过的旧源" if stale else ""}',f'整体保留原因：{reason or "无"}','', '## 分类覆盖与时效']
    for category,status in category_status.items():
        summary.append(f'- {category}：本次通过 {status["current_passed"]}，订阅保留 {status["playlist_count"]}，最后通过 {status["last_success_utc"] or "尚无"}，状态 {"旧源/可能过期" if status["stale"] else ("暂无可用" if status["missing"] else "本次已验证")}')
    summary += ['', '检测环境：'+report['probe_location'], '', '仅表示取到媒体并实际解出一帧；不保证持续流畅、节目身份、观看授权、地区及你的网络可用。清单 HTTP 200 不作为成功。', '央视和卫视公开源可能不完整；无可用源时不编造、不绕过限制。', '所有默认目录来自同一社区上游 iptv-org，不是独立容灾来源，也不是全网搜索。', '', '详细结果见 status.json / results.json；历史摘要保留最近 30 次运行。']
    write_atomic(output/'STATUS.md','\n'.join(summary)+'\n')
    return report
