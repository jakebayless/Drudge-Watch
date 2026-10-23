#!/usr/bin/env python3
"""One-shot Drudge comparator. Python 3.10+, standard library only."""
import argparse, datetime as dt, email.utils, fcntl, hashlib, html, json, logging
import os, re, sqlite3, tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

SOURCE = 'https://drudgereport.com/'

def identity(url):
    p = urlsplit(url)
    query = [(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith('utm_') and k.lower() not in {'fbclid','gclid','smid','unlocked_article_code'}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, urlencode(query), ''))

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.logo = False; self.column = 0; self.in_column = False
        self.stopped = False; self.anchor = None; self.items = {}; self.columns = set()
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'img' and re.search(r'/logo[^/]*\.(gif|png|jpg)', a.get('src',''), re.I):
            self.logo = True
        if tag == 'td':
            self.in_column = self.logo and a.get('width','').strip() == '33%'
            if self.in_column:
                self.column += 1; self.columns.add(self.column); self.stopped = False
        if tag == 'a':
            self.anchor = [a.get('href',''), [], 'headlines' if not self.logo else 'news',
                           not self.logo or (self.in_column and not self.stopped)]
        if tag == 'br' and self.anchor: self.anchor[1].append(' ')
    def handle_data(self, data):
        if self.anchor: self.anchor[1].append(data)
    def handle_endtag(self, tag):
        if tag == 'td': self.in_column = False
        if tag != 'a' or not self.anchor: return
        href, parts, section, allowed = self.anchor; self.anchor = None
        title = ' '.join(''.join(parts).split())
        # Explicit directory sentinels; fail closed if these disappear.
        if self.logo and title in {'LIVE: TRENDING...', 'ABCNEWS', 'AFRICAN NEWS', 'AGENCE FRANCE-PRESSE'}:
            self.stopped = True; return
        url = urljoin(SOURCE, href); p = urlsplit(url)
        if not allowed or not title or p.scheme not in {'https','http'}: return
        host = (p.hostname or '').lower()
        if host == 'drudgereport.com' or host.endswith('.drudgereport.com'): return
        key = identity(url)
        if key not in self.items: self.items[key] = dict(url=url,title=title,section=section)
    def handle_comment(self, data):
        normalized = re.sub(r'\s+', '', data).upper()
        if self.logo and normalized.startswith('LINK'): self.stopped = True

def parse_page(text):
    p = Parser(); p.feed(text)
    counts = {s:sum(x['section']==s for x in p.items.values()) for s in ('headlines','news')}
    if not p.logo or len(p.columns)!=3 or not counts['headlines'] or counts['news']<10:
        raise ValueError('Page structure validation failed; preserving previous state and feeds')
    return p.items

def atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f: f.write(data)
        os.chmod(name,0o644); os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

def update(db, items, now):
    db.executescript('''CREATE TABLE IF NOT EXISTS links (key TEXT PRIMARY KEY, url TEXT, title TEXT, section TEXT, first_seen TEXT, last_seen TEXT, active INTEGER);
    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, key TEXT, url TEXT, title TEXT, section TEXT, kind TEXT, detected TEXT, previous_check TEXT);
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);''')
    previous = db.execute("SELECT value FROM meta WHERE key='checked'").fetchone()
    old = {r['key']:r for r in db.execute('SELECT * FROM links')}
    def event(key,item,kind):
        db.execute('INSERT INTO events(key,url,title,section,kind,detected,previous_check) VALUES(?,?,?,?,?,?,?)',
                   (key,item['url'],item['title'],item['section'],kind,now,previous[0] if previous else None))
    with db:
        for key,item in items.items():
            before = old.get(key)
            if previous:
                if before is None: event(key,item,'new')
                else:
                    if not before['active']: event(key,item,'returned')
                    if before['section'] != item['section']: event(key,item,'moved')
                    if before['title'] != item['title']: event(key,item,'edited')
            db.execute('INSERT OR REPLACE INTO links VALUES(?,?,?,?,?,?,1)',
                       (key,item['url'],item['title'],item['section'],before['first_seen'] if before else now,now))
        for key,before in old.items():
            if before['active'] and key not in items:
                event(key,before,'removed'); db.execute('UPDATE links SET active=0 WHERE key=?',(key,))
        db.execute("INSERT OR REPLACE INTO meta VALUES('checked',?)",(now,))
    return previous is None

def publish(db,out,base,now):
    events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY detected DESC,id DESC LIMIT 1000')]
    for section in ('headlines','news','all'):
        root = ET.Element('rss',version='2.0'); ch = ET.SubElement(root,'channel')
        for tag,value in [('title',f'Drudge Watch — {section}'),('link',SOURCE),('description','New links first detected on Drudge. Unofficial; timestamps are observation times.'),('ttl','10'),('lastBuildDate',email.utils.format_datetime(dt.datetime.fromisoformat(now)))]:
            ET.SubElement(ch,tag).text=value
        chosen = [e for e in events if (e['kind']=='new' or (e['kind']=='moved' and e['section']=='headlines')) and (section=='all' or e['section']==section)][:50]
        for e in chosen:
            node = ET.SubElement(ch,'item')
            values = {'title':e['title'],'link':e['url'],'pubDate':email.utils.format_datetime(dt.datetime.fromisoformat(e['detected'])),'description':f"{e['section'].title()} · {e['kind']} · First detected {e['detected']}. Previous successful check: {e['previous_check']}.",'category':e['section']}
            for tag,value in values.items(): ET.SubElement(node,tag).text=value
            ET.SubElement(node,'guid',isPermaLink='false').text=base.rstrip('/')+'/event/'+str(e['id'])
        atomic(Path(out)/f'drudge-{section}.xml',ET.tostring(root,encoding='unicode',xml_declaration=True))
    atomic(Path(out)/'changes.json',json.dumps({'checked':now,'events':events},indent=2))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default='state/drudge.sqlite3'); ap.add_argument('--out',default='output'); ap.add_argument('--base-url',default='https://empirereport.org/feeds/drudge'); ap.add_argument('--html',help='Offline fixture instead of HTTP')
    args=ap.parse_args(); Path(args.db).parent.mkdir(parents=True,exist_ok=True)
    with open(args.db+'.lock','w') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        if args.html: text=Path(args.html).read_text()
        else:
            req=Request(SOURCE,headers={'User-Agent':'EmpireReport-DrudgeWatch/0.1 (+https://empirereport.org/)'})
            with urlopen(req,timeout=30) as response:
                if 'html' not in response.headers.get('Content-Type',''): raise ValueError('Expected HTML')
                text=response.read(2_000_001)
                if len(text)>2_000_000: raise ValueError('Response too large')
                text=text.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
        items=parse_page(text); now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        db=sqlite3.connect(args.db); db.row_factory=sqlite3.Row
        try:
            baseline=update(db,items,now); publish(db,args.out,args.base_url,now)
            logging.info('%s: %d links; feeds written', 'Baseline' if baseline else 'Checked',len(items))
        finally: db.close()
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try: main()
    except Exception: logging.exception('Check failed'); raise SystemExit(1)
