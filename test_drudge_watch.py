import sqlite3, tempfile, unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from drudge_watch import parse_page, update, publish, identity

def fixture():
    return '<a href="https://example.com/top">Top</a><img src="/i/logo9.gif"><table><tr>'+''.join('<td width="33%">'+''.join(f'<a href="https://example.com/{c}/{i}">Story {c}-{i}</a>' for i in range(5))+'<!-- LINKS DIRECTORY --><a href="https://directory.test/">Directory</a></td>' for c in range(3))+'</tr></table>'
class Tests(unittest.TestCase):
    def test_boundaries(self):
        items=parse_page(fixture()); self.assertEqual(len(items),16)
        self.assertEqual(sum(x['section']=='headlines' for x in items.values()),1)
        with self.assertRaises(ValueError): parse_page('<html>Unavailable</html>')
    def test_events_and_rss(self):
        db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
        items=parse_page(fixture()); update(db,items,'2026-10-23T10:00:00+00:00')
        self.assertEqual(db.execute('select count(*) from events').fetchone()[0],0)
        update(db,items,'2026-10-23T10:10:00+00:00')
        self.assertEqual(db.execute('select count(*) from events').fetchone()[0],0)
        items['https://example.com/0/0']['section']='headlines'
        items['https://example.com/0/1']['title']='Changed & updated'
        items['https://example.com/new']={'url':'https://example.com/new','title':'New & noteworthy','section':'news'}
        removed=items.pop('https://example.com/0/2')
        update(db,items,'2026-10-23T10:20:00+00:00')
        self.assertEqual({r[0] for r in db.execute('select kind from events')},{'new','moved','edited','removed'})
        with tempfile.TemporaryDirectory() as out:
            publish(db,out,'https://example.com/feed','2026-10-23T10:20:00+00:00')
            self.assertEqual(len(ET.parse(Path(out)/'drudge-all.xml').findall('.//item')),2)
        items['https://example.com/0/2']=removed
        update(db,items,'2026-10-23T10:30:00+00:00')
        self.assertEqual(db.execute("select count(*) from events where kind='returned'").fetchone()[0],1)
    def test_tracking(self):
        self.assertEqual(identity('https://example.com/a?id=42&utm_source=x#top'),'https://example.com/a?id=42')
if __name__=='__main__': unittest.main()
