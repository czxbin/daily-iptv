"""M3U parsing and fair, bounded selection. Never execute playlist directives."""
from dataclasses import dataclass, asdict
from collections import defaultdict
import hashlib
import re
from urllib.parse import urlsplit

CATEGORIES = ('央视', '卫视', '港澳台', '海外', '其他中文')
ATTR = re.compile(r'([\w-]+)="([^"\r\n]*)"')

@dataclass
class Channel:
    name: str
    url: str
    tvg_id: str = ''
    logo: str = ''
    category: str = ''
    region: str = ''
    source: str = ''
    rights: str = 'unknown; community-listed public endpoint, not a license grant'
    def to_dict(self):
        return asdict(self)

def clean(value):
    return re.sub(r'[\x00-\x1f\x7f"]', ' ', str(value)).strip()

def valid_url_shape(url):
    try:
        p = urlsplit(url)
        return (p.scheme in ('http', 'https') and bool(p.hostname) and
                not p.username and not p.password and not p.fragment and
                not any(ord(c) < 33 or c in '|\\' for c in url))
    except ValueError:
        return False

def classify(name, tvg_id, region):
    if region.upper() in ('HK', 'MO', 'TW'):
        return '港澳台'
    if region.upper() == 'CN' and re.search(r'cctv|央视|中央电视', name + tvg_id, re.I):
        return '央视'
    if region.upper() == 'CN' and (re.search(r'卫视|衛視|satellite', name + tvg_id, re.I) or tvg_id.split('.')[0] in {'HunanTV','DragonTV','DragonTVInternational','SoutheastTV','ShenzhenTV','ZhejiangTV','BeijingTV','JiangsuTV','ShandongTV','AnhuiTV','HenanTV','JiangxiTV','HubeiTV','SichuanTV','GuangxiTV','GuangdongTV','HebeiTV','HainanTV','HeilongjiangTV','JilinTV','LiaoningTV','GansuTV','QinghaiTV','NingxiaTV','ShaanxiTV','ShanxiTV','ChongqingTV','GuizhouTV','YunnanTV','TibetTV','XinjiangTV','InnerMongoliaTV','TianjinTV','XiamenStarTV','StraitTV'}):
        return '卫视'
    return '其他中文' if region.upper() == 'CN' else '海外'

def parse_m3u(text, source, region=''):
    result = []
    pending = None
    for line in text.lstrip('\ufeff').splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # The metadata/name separator must not be inside quoted attributes.
            split = re.search(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', line)
            pending = (dict(ATTR.findall(line[:split.start()])), line[split.end():]) if split else None
        elif line and not line.startswith('#'):
            if pending and valid_url_shape(line):
                attrs, name = pending
                tvg = attrs.get('tvg-id','')
                suffix = tvg.split('@')[0].rsplit('.',1)[-1].upper() if '.' in tvg else ''
                actual_region = suffix if len(suffix) == 2 else region.upper()
                logo = attrs.get('tvg-logo','')
                result.append(Channel(clean(name), line, clean(tvg), logo if valid_url_shape(logo) else '', classify(name,tvg,actual_region), actual_region or 'UNKNOWN', source))
            pending = None
    return result

def select_candidates(channels, quotas, day, variants=2):
    # Rotate channels every day; don't spend the whole budget on the first source.
    unique = {}
    for c in channels:
        unique.setdefault(c.url,c)
    groups = defaultdict(lambda:defaultdict(list))
    for c in unique.values():
        key = c.tvg_id.split('@')[0] or re.sub(r'\s*\([^)]*\)|\s*\[[^]]*\]', '',c.name).casefold()
        groups[c.category][key].append(c)
    def score(value):
        return hashlib.sha256((str(day)+value).encode()).hexdigest()
    result = []
    for category in CATEGORIES:
        keys = sorted(groups[category], key=score)
        count = 0
        for variant in range(variants):
            for key in keys:
                choices = sorted(groups[category][key],key=lambda c:score(c.url))
                if variant < len(choices) and count < quotas.get(category,0):
                    result.append(choices[variant]); count += 1
    return result

def render_m3u(channels, checked_at):
    lines = ['#EXTM3U', '# Generated UTC: '+clean(checked_at), '# Validation: one locally decoded video frame; playback depends on region and network.']
    for c in sorted(channels,key=lambda c:(CATEGORIES.index(c.category),c.name,c.url)):
        lines.append(f'#EXTINF:-1 tvg-id="{clean(c.tvg_id)}" tvg-logo="{clean(c.logo)}" group-title="{clean(c.category)}",{clean(c.name)}')
        lines.append(c.url)
    return '\n'.join(lines)+'\n'
