# Drudge Watch — Raspberry Pi prototype

A lightweight Python 3.10+ scraper/comparator with no third-party dependencies. Designed for Ubuntu on Raspberry Pi. This package has not been installed on your server.

## Behavior

- Headlines: text links above the Drudge logo.
- News: story links in the three columns below it, stopping at each column's directory section. Image-only links, ads, navigation, permanent media directories, and utility links are excluded.
- First run creates a baseline and empty feeds. It cannot determine when existing links originally appeared.
- Subsequent checks add newly observed URLs to RSS. Moving an existing news link above the logo also creates a headline RSS item. Moving it down, editing its text, removing it, or returning a previously seen link is recorded only in changes.json and SQLite.
- RSS retains the most recent 50 qualifying items per feed within the latest 1,000 change events, including links subsequently removed from Drudge. The local database retains all history.
- Timestamps mean first detected, not publication time. Under normal operation, additions occurred between the previous successful check and the detection time. Outages widen that interval; changes that appear and disappear between checks are invisible.
- UTC is stored internally. RSS readers can display local time.
- Identity uses the destination URL, strips fragments and selected tracking parameters, and preserves meaningful query parameters. Different URL aliases can still count as different stories. No destination articles are fetched.
- Missing logo, missing columns, or too few stories aborts the check. Previous feeds survive HTTP/parsing failures. Structural checks reduce but cannot eliminate misclassification after site redesigns.
- Feed writes are atomic per file; overlapping checks are locked out. If publishing fails after a database commit, the next successful run regenerates feeds from recorded events.

## Install via SSH

Copy this directory to your Pi at `/opt/empirereport-feeds/drudge-watch` alongside the existing scraper project. Then, as your ordinary SSH user:

```bash
sudo mkdir -p /var/www/html/feeds/drudge
sudo chown jakebayless:www-data /var/www/html/feeds/drudge
cd /opt/empirereport-feeds/drudge-watch
python3 -m unittest -v
python3 drudge_watch.py --out /var/www/html/feeds/drudge
```

The project directory must be writable by the cron user so SQLite can create `state/`. State stays outside the public web directory. Back up `state/drudge.sqlite3`; deleting it resets the baseline and history.

Add this line using `crontab -e` under the same user. Use this dedicated schedule OR integrate the command into the existing runner, not both. The existing eight-minute scraper schedule differs from this requested ten-minute interval.

```cron
*/10 * * * * cd /opt/empirereport-feeds/drudge-watch && /usr/bin/python3 drudge_watch.py --out /var/www/html/feeds/drudge >> /opt/empirereport-feeds/drudge-watch/drudge.log 2>&1
```

Rotate `drudge.log` with your existing logging setup. Each successful run logs the number of parsed links. Failures exit nonzero and log a traceback; cron does not provide alerting unless you configure it.

## Public feed URLs

Assuming your existing nginx `/feeds/` mapping serves `/var/www/html/feeds/`:

- https://empirereport.org/feeds/drudge/drudge-headlines.xml
- https://empirereport.org/feeds/drudge/drudge-news.xml
- https://empirereport.org/feeds/drudge/drudge-all.xml
- https://empirereport.org/feeds/drudge/changes.json

If `/feeds/` is not already mapped in the Empire Report server block, add:

```nginx
location /feeds/drudge/ {
    alias /var/www/html/feeds/drudge/;
    autoindex off;
    add_header Cache-Control "public, max-age=300";
}
```

After any nginx edit, run `sudo nginx -t` before `sudo systemctl reload nginx`. Check the actual public feed URL with `curl -I`. Existing feed files keep their previous timestamps during an outage, so check the log or changes.json's `checked` field to verify freshness.

## WordPress homepage

Use two RSS widgets/blocks in Mission News Pro: “Drudge — Headlines” (5 items) and “Drudge — New Links” (10 items), using the separate feed URLs above. Enable item dates if supported and disable excerpts for a compact list. Links open the original article. WordPress may cache RSS; your existing five-minute RSS cache setting adds a little delay beyond polling. Native RSS widgets may show dates without precise times; exact local times would require a small custom widget.

Open `preview.html` for an illustrative visual mockup. Its example stories and times are fictional; it is not a live feed or deployed dashboard.

## Offline check

```bash
python3 drudge_watch.py --html saved-drudge.html --db /tmp/drudge-offline.sqlite3 --out /tmp/drudge-offline-output
```

Use a separate test database for saved HTML. The parser was also checked against a live HTML download on October 23, 2026: 47 story links were recognized across the two sections. This is an unofficial personal-use prototype; it does not copy article bodies or images.
