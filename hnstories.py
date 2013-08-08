#!/usr/bin/env python
import re
import os
import time
import pprint
import sqlite3
from datetime import datetime, timedelta

import requests
import html5lib
from html5lib import sanitizer, treebuilders
from lxml import etree, html
from lxml.cssselect import CSSSelector


parser = html5lib.HTMLParser(
            tokenizer=sanitizer.HTMLSanitizer,
            tree=treebuilders.getTreeBuilder("lxml"))


sel_link = CSSSelector('a')
sel_span = CSSSelector('span')
sel_story = CSSSelector('td.title')
sel_comment = CSSSelector('td.default')
sel_hidden = CSSSelector('input[type="hidden"]')

more_link_re = re.compile('/x\?fnid=.*$')
meta_link_re = re.compile('(user|item)\?id=(.*)$')
points_re = re.compile('(\d+)\s+points?')
age_re = re.compile('(\d+)\s+(minute|hour|day)s?\s+ago')


DB_FILE = os.path.join(os.path.dirname(__file__), 'stories.db')


def parse_age(num, unit):
    '''Approximate the posting date. Don't really worry about 'to the minute/hour' accuracy.
    The returned date is in UTC timezone.'''
    date = datetime.utcnow()
    num = int(num)
    if unit == 'minute':
        date -= timedelta(0, num * 60)
    elif unit == 'hour':
        date -= timedelta(0, num * 3600)
    elif unit == 'day':
        date -= timedelta(num)
    return date.strftime('%Y-%m-%d')


def get_document(page):
    '''Returns a valid HTML document.
    @param page: A file-like object or a string'''
    tree = parser.parse(page)
    return html.fromstring(etree.tostring(tree))


def get_story_info(title_node):
    '''Returns attributes of a story, or the 'more' link if the title_node is for 'more'.'''
    title = title_node.text_content().strip()
    link = title_node.get('href')
    # Test that it's not the "More" link.
    if title.strip() == 'More' and more_link_re.match(link):
        return {'type': 'more', 'link': link}

    d = {'type': 'story',
         'title': title,
         'link': link}
    meta = title_node.xpath("parent::*/parent::*/following-sibling::tr[1]/td[@class='subtext']")
    if meta:
        subtext = meta[0]
        for link_node in sel_link(subtext):
            href = link_node.get('href')
            # Match the user or the item id
            meta_m = meta_link_re.match(href)
            if meta_m:
                key, value = meta_m.groups()
                if key == 'item':
                    key = 'id'
                d[key] = value
        for span_node in sel_span(subtext):
            m = points_re.match(span_node.text_content())
            if m:
                d['points'] = int(m.group(1))
        age_m = age_re.search(subtext.text_content())
        if age_m:
            d['posted'] = parse_age(*age_m.groups())
    return d


def get_stories(page):
    '''Returns the list of stories on a page.'''
    doc = get_document(page)
    result = {
        'items': []
    }
    for row in sel_story(doc):
        try:
            title_node = sel_link(row)[0]
        except IndexError:
            continue
        d = get_story_info(title_node)
        if d and d['type'] == 'more':
            result['more'] = d['link']
        elif d and d['type'] == 'story':
            del d['type']
            result['items'].append(d)
    return result


def get_comments(page):
    '''Get the comments on a page.'''
    doc = get_document(page)
    comments = {
        'items': []
    }
    raise NotImplementedError("Still have to do this")


def init_db(filename):
    '''Create the database filename if it doesn't exist.'''
    db = sqlite3.connect(filename)
    cursor = db.cursor()
    cursor.executescript('CREATE TABLE stories(id, title, link, posted, user, points, description);'
                         'CREATE INDEX story_date ON stories(posted);'
                         'CREATE UNIQUE INDEX story_id ON stories(id);'
                         'CREATE INDEX points ON stories(points);')
    db.commit()
    db.close()


def get_saved_stories(user, session):
    '''Gets all of a user's saved stories and stores them in a SQLite3 database'''
    if not os.path.isfile(DB_FILE):
        init_db(DB_FILE)
    db = sqlite3.connect(DB_FILE)
    cursor = db.cursor()
    url = 'https://news.ycombinator.com/saved?id=%s' % user
    try:
        while 1:
            print "Saving stories from", url
            r = session.get(url)
            result = get_stories(r.content)
            for item in result['items']:
                fields = []
                values = []
                for key, value in item.iteritems():
                    fields.append(key)
                    values.append(value)
                keys_fmt = ', '.join(fields)
                values_fmt = ','.join(['?'] * len(values))
                cursor.execute('REPLACE INTO stories (%s) VALUES (%s)' % (
                                keys_fmt, values_fmt), values)
                db.commit()
            pprint.pprint(result)
            if result.get('more'):
                url = 'https://news.ycombinator.com' + result['more']
                time.sleep(5)  # See http://news.ycombinator.com/robots.txt
            else:
                break
    finally:
        db.close()


def login(user, passwd):
    '''Login to HN. Returns a requests.sessions.Session object'''
    sess = requests.session()
    res = sess.get('https://news.ycombinator.com/newslogin')
    doc = get_document(res.content)
    params = {'u': user, 'p': passwd}
    for hidden in sel_hidden(doc):
        if hidden.name == 'fnid':
            params['fnid'] = hidden.value
            break
    r = sess.post('https://news.ycombinator.com/y', params=params)
    assert r.status_code == 200, "Unexpected status code: %s" % r.status_code
    return sess


def fetch():
    raise NotImplementedError("Still have to do this")


if __name__ == '__main__':
    import sys
    import getpass
    try:
        user = sys.argv[1]
    except IndexError:
        print >> sys.stderr, "Usage: %s username" % sys.argv[0]
        exit(1)
    session = login(user, getpass.getpass("Password: "))
    get_saved_stories(user, session)

