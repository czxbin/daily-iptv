"""Bounded public network reads and actual video-frame decoding of local samples."""
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlsplit
import http.client
import ssl
import sys
import ipaddress
import json
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from .playlist import valid_url_shape

MAX_MEDIA = 6 * 1024 * 1024
MAX_MANIFEST = 512 * 1024
class ProbeError(Exception):
    pass

def public_addresses(url):
    if not valid_url_shape(url):
        raise ProbeError('unsafe_url')
    p = urlsplit(url)
    try:
        port = p.port or (443 if p.scheme == 'https' else 80)
        addresses = sorted(set(x[4][0] for x in socket.getaddrinfo(p.hostname,port,type=socket.SOCK_STREAM)))
    except (ValueError, OSError) as exc:
        raise ProbeError('dns_error') from exc
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ProbeError('non_public_address')
    return addresses

def bounded_addresses(url, timeout):
    # getaddrinfo itself has no portable timeout. Isolate it in a killable child.
    try:
        result=subprocess.run([sys.executable,'-c',
            'import json,sys; from iptv.probe import public_addresses; print(json.dumps(public_addresses(sys.argv[1])))',url],
            capture_output=True,timeout=min(3,timeout),check=False)
    except subprocess.TimeoutExpired as exc: raise ProbeError('dns_timeout') from exc
    if result.returncode:
        if b'non_public_address' in result.stderr: raise ProbeError('non_public_address')
        if b'unsafe_url' in result.stderr: raise ProbeError('unsafe_url')
        raise ProbeError('dns_error')
    return json.loads(result.stdout)

def open_connection(url, addresses, timeout):
    """Pin TCP to a validated address while preserving HTTPS hostname verification."""
    p=urlsplit(url); port=p.port or (443 if p.scheme=='https' else 80)
    host=p.hostname.encode('idna').decode('ascii')
    connection=http.client.HTTPConnection(host,port,timeout=timeout)
    sock=None
    # Prefer IPv4 where both are present; validation covered every returned address.
    address=sorted(addresses,key=lambda a:':' in a)[0]
    try:
        sock=socket.create_connection((address,port),timeout=timeout)
        if p.scheme=='https':
            sock=ssl.create_default_context().wrap_socket(sock,server_hostname=host)
        connection.sock=sock
        return connection
    except Exception:
        if sock is not None: sock.close()
        raise

def fetch(url, limit, deadline=None):
    """Bounded direct connections; proxy variables are deliberately not used."""
    deadline=deadline or time.monotonic()+15
    for _ in range(4):
        remaining=deadline-time.monotonic()
        if remaining<=0: raise ProbeError('time_budget_exceeded')
        addresses=bounded_addresses(url,remaining)
        remaining=deadline-time.monotonic()
        if remaining<=0: raise ProbeError('time_budget_exceeded')
        conn=None
        try:
            conn=open_connection(url,addresses,min(5,remaining))
            p=urlsplit(url)
            path=p.path or '/'
            if p.query: path+='?'+p.query
            conn.request('GET',path,headers={'User-Agent':'daily-iptv-checker/1.0','Accept-Encoding':'identity'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308) and response.getheader('Location'):
                url=urljoin(url,response.getheader('Location'))
                continue
            if response.status not in (200,206): raise ProbeError('http_'+str(response.status))
            data=bytearray()
            while len(data)<limit:
                remaining=deadline-time.monotonic()
                if remaining<=0: raise ProbeError('time_budget_exceeded')
                if conn.sock: conn.sock.settimeout(min(5,remaining))
                # read1 avoids waiting to fill the entire block on a live/slow stream.
                chunk=response.read1(min(65536,limit-len(data)))
                if not chunk: break
                data.extend(chunk)
            return bytes(data),url
        except (TimeoutError,socket.timeout) as exc: raise ProbeError('network_timeout') from exc
        except (OSError,http.client.HTTPException,ValueError) as exc: raise ProbeError('network_error') from exc
        finally:
            if conn is not None: conn.close()
    raise ProbeError('too_many_redirects')

def hls_target(text, base):
    lines = [line.strip() for line in text.lstrip('\ufeff').splitlines() if line.strip()]
    if not lines or lines[0] != '#EXTM3U': raise ProbeError('not_hls')
    if '#EXT-X-ENDLIST' in lines: raise ProbeError('not_live_playlist')
    for line in lines:
        if line.startswith('#EXT-X-KEY:') and not re.search(r'(?:^|[:,])METHOD=NONE(?:,|$)',line):
            raise ProbeError('encrypted_stream_skipped')
        if line.startswith('#EXT-X-BYTERANGE'):
            raise ProbeError('byterange_unsupported')
    variants=[]; segments=[]; init=None; pending_variant=None; pending_segment=False
    for line in lines:
        if line.startswith('#EXT-X-STREAM-INF:'):
            match=re.search(r'(?:[:,])BANDWIDTH=(\d+)',line)
            pending_variant=int(match.group(1)) if match else 999999999
        elif line.startswith('#EXT-X-MAP:'):
            match=re.search(r'URI="([^"]+)"',line)
            if 'BYTERANGE=' in line: raise ProbeError('byterange_unsupported')
            if match: init=urljoin(base,match.group(1))
        elif line.startswith('#EXTINF:'):
            pending_segment=True
        elif not line.startswith('#'):
            if pending_variant is not None:
                variants.append((pending_variant,urljoin(base,line))); pending_variant=None
            elif pending_segment:
                segments.append((urljoin(base,line),init)); pending_segment=False
    if variants: return 'playlist',min(variants)[1],None
    if segments:
        target,mapping=segments[-2 if len(segments)>1 else -1]
        return 'media',target,mapping
    raise ProbeError('empty_hls')

def media_format(data):
    if len(data)>376 and data[0]==0x47 and data[188]==0x47 and data[376]==0x47:
        return 'mpegts'
    if len(data)>12 and data[4:8] in (b'ftyp',b'styp',b'moof',b'moov'):
        return 'mov'
    raise ProbeError('not_supported_media')

def decode_sample(data):
    """No remote URLs or playlists enter FFmpeg; only restricted local containers."""
    fmt=media_format(data)
    with tempfile.TemporaryDirectory(prefix='iptv-') as tmp:
        path=Path(tmp)/('sample.ts' if fmt=='mpegts' else 'sample.mp4')
        path.write_bytes(data)
        common=['-v','error','-protocol_whitelist','file,pipe','-f',fmt]
        try:
            meta=subprocess.run(['ffprobe',*common,'-show_streams','-of','json',str(path)],capture_output=True,timeout=6,check=False)
            streams=json.loads(meta.stdout or b'{}').get('streams',[])
            video=next((s for s in streams if s.get('codec_type')=='video'),None)
            if not video: raise ProbeError('no_video_stream')
            process=subprocess.run(['ffmpeg','-nostdin',*common,'-threads','1','-i',str(path),'-map','0:v:0','-frames:v','1','-f','null','-','-progress','pipe:1'],capture_output=True,timeout=8,check=False)
            frames=[int(x) for x in re.findall(rb'(?:^|\n)frame=(\d+)',process.stdout)]
            if process.returncode!=0 or not frames or max(frames)<1:
                raise ProbeError('video_decode_failed')
            return {'codec':video.get('codec_name'),'width':video.get('width'),'height':video.get('height'),'decoded_frames':max(frames),'sample_bytes':len(data)}
        except subprocess.TimeoutExpired as exc: raise ProbeError('decode_timeout') from exc
        except (json.JSONDecodeError,FileNotFoundError) as exc: raise ProbeError('decoder_unavailable_or_invalid') from exc

@dataclass
class Result:
    channel: dict
    ok: bool
    reason: str
    elapsed_ms: int
    media: dict
    def to_dict(self): return asdict(self)

def probe(channel, seconds=18):
    started=time.monotonic(); deadline=started+seconds
    try:
        url=channel.url
        for depth in range(4):
            data,actual=fetch(url,MAX_MANIFEST,deadline)
            if not data.lstrip(b'\xef\xbb\xbf \r\n').startswith(b'#EXTM3U'):
                info=decode_sample(data)
                break
            mode,target,init=hls_target(data.decode('utf-8-sig',errors='replace'),actual)
            if mode=='playlist':
                url=target
                continue
            prefix=fetch(init,MAX_MANIFEST,deadline)[0] if init else b''
            data=fetch(target,MAX_MEDIA,deadline)[0]
            info=decode_sample(prefix+data)
            break
        else: raise ProbeError('hls_depth_exceeded')
        return Result(channel.to_dict(),True,'decoded_video_frame',int((time.monotonic()-started)*1000),info)
    except ProbeError as exc:
        return Result(channel.to_dict(),False,str(exc),int((time.monotonic()-started)*1000),{})
    except Exception as exc:
        return Result(channel.to_dict(),False,'unexpected_'+type(exc).__name__,int((time.monotonic()-started)*1000),{})
