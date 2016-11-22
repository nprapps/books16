#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Commands that update or process the application data.
"""
import app_config
import codecs
import copytext
import csv
import json
import locale
import os
import re
import requests
import sys
import string
import xlrd
import logging
import time
import shutil
from urllib import urlencode

# Wrap sys.stdout into a StreamWriter to allow writing unicode. See http://stackoverflow.com/a/4546129
sys.stdout = codecs.getwriter(locale.getpreferredencoding())(sys.stdout)

from PIL import Image
from bs4 import BeautifulSoup
from datetime import datetime
from fabric.api import task
from facebook import GraphAPI
from twitter import Twitter, OAuth
from csvkit.py2 import CSVKitDictReader, CSVKitDictWriter

logging.basicConfig(format=app_config.LOG_FORMAT)
logger = logging.getLogger(__name__)
logger.setLevel(app_config.LOG_LEVEL)

ITUNES_URL_ID_REGEX = re.compile(r'id(\d+)\??')

TAGS_TO_SLUGS = {}
SLUGS_TO_TAGS = {}

# Promotion image constants
IMAGE_COLUMNS = 30
TOTAL_IMAGES = 313
PROMOTION_IMAGE_WIDTH = 1200

def _make_teaser(book):
    """
    Calculate a teaser
    """
    tag_stripper = re.compile(r'<.*?>')

    try:
        img = Image.open('www/assets/cover/%s.jpg' % book.slug)
        width, height = img.size

        # Poor man's packing algorithm. How much text will fit?
        chars = height / 25 * 7
    except IOError:
        chars = 140

    text = tag_stripper.sub('', book.text)

    if len(text) <= chars:
        return text

    i = chars

    # Walk back to last full word
    while text[i] != ' ':
        i -= 1

    # Like strip, but decrements the counter
    if text.endswith(' '):
        i -= 1

    # Kill trailing punctuation
    exclude = set(string.punctuation)
    if text[i-1] in exclude:
        i -= 1

    return '&#8220;' + text[:i] + ' ...&#8221;'

@task(default=True)
def update():
    """
    Load books and covers
    """
    #update_featured_social()
    logger.setLevel(app_config.LOG_LEVEL)
    load_books()
    load_images()
    #make_promotion_thumb()

@task
def update_featured_social():
    """
    Update featured tweets
    """
    COPY = copytext.Copy(app_config.COPY_PATH)
    secrets = app_config.get_secrets()

    # Twitter
    print 'Fetching tweets...'

    twitter_api = Twitter(
        auth=OAuth(
            secrets['TWITTER_API_OAUTH_TOKEN'],
            secrets['TWITTER_API_OAUTH_SECRET'],
            secrets['TWITTER_API_CONSUMER_KEY'],
            secrets['TWITTER_API_CONSUMER_SECRET']
        )
    )

    tweets = []

    for i in range(1, 4):
        tweet_url = COPY['share']['featured_tweet%i' % i]

        if isinstance(tweet_url, copytext.Error) or unicode(tweet_url).strip() == '':
            continue

        tweet_id = unicode(tweet_url).split('/')[-1]

        tweet = twitter_api.statuses.show(id=tweet_id)

        creation_date = datetime.strptime(tweet['created_at'],'%a %b %d %H:%M:%S +0000 %Y')
        creation_date = '%s %i' % (creation_date.strftime('%b'), creation_date.day)

        tweet_url = 'http://twitter.com/%s/status/%s' % (tweet['user']['screen_name'], tweet['id'])

        photo = None
        html = tweet['text']
        subs = {}

        for media in tweet['entities'].get('media', []):
            original = tweet['text'][media['indices'][0]:media['indices'][1]]
            replacement = '<a href="%s" target="_blank" onclick="_gaq.push([\'_trackEvent\', \'%s\', \'featured-tweet-action\', \'link\', 0, \'%s\']);">%s</a>' % (media['url'], app_config.PROJECT_SLUG, tweet_url, media['display_url'])

            subs[original] = replacement

            if media['type'] == 'photo' and not photo:
                photo = {
                    'url': media['media_url']
                }

        for url in tweet['entities'].get('urls', []):
            original = tweet['text'][url['indices'][0]:url['indices'][1]]
            replacement = '<a href="%s" target="_blank" onclick="_gaq.push([\'_trackEvent\', \'%s\', \'featured-tweet-action\', \'link\', 0, \'%s\']);">%s</a>' % (url['url'], app_config.PROJECT_SLUG, tweet_url, url['display_url'])

            subs[original] = replacement

        for hashtag in tweet['entities'].get('hashtags', []):
            original = tweet['text'][hashtag['indices'][0]:hashtag['indices'][1]]
            replacement = '<a href="https://twitter.com/hashtag/%s" target="_blank" onclick="_gaq.push([\'_trackEvent\', \'%s\', \'featured-tweet-action\', \'hashtag\', 0, \'%s\']);">%s</a>' % (hashtag['text'], app_config.PROJECT_SLUG, tweet_url, '#%s' % hashtag['text'])

            subs[original] = replacement

        for original, replacement in subs.items():
            html =  html.replace(original, replacement)

        # https://dev.twitter.com/docs/api/1.1/get/statuses/show/%3Aid
        tweets.append({
            'id': tweet['id'],
            'url': tweet_url,
            'html': html,
            'favorite_count': tweet['favorite_count'],
            'retweet_count': tweet['retweet_count'],
            'user': {
                'id': tweet['user']['id'],
                'name': tweet['user']['name'],
                'screen_name': tweet['user']['screen_name'],
                'profile_image_url': tweet['user']['profile_image_url'],
                'url': tweet['user']['url'],
            },
            'creation_date': creation_date,
            'photo': photo
        })

    # Facebook
    print 'Fetching Facebook posts...'

    fb_api = GraphAPI(secrets['FACEBOOK_API_APP_TOKEN'])

    facebook_posts = []

    for i in range(1, 4):
        fb_url = COPY['share']['featured_facebook%i' % i]

        if isinstance(fb_url, copytext.Error) or unicode(fb_url).strip() == '':
            continue

        fb_id = unicode(fb_url).split('/')[-1]

        post = fb_api.get_object(fb_id)
        user  = fb_api.get_object(post['from']['id'])
        user_picture = fb_api.get_object('%s/picture' % post['from']['id'])
        likes = fb_api.get_object('%s/likes' % fb_id, summary='true')
        comments = fb_api.get_object('%s/comments' % fb_id, summary='true')
        #shares = fb_api.get_object('%s/sharedposts' % fb_id)

        creation_date = datetime.strptime(post['created_time'],'%Y-%m-%dT%H:%M:%S+0000')
        creation_date = '%s %i' % (creation_date.strftime('%b'), creation_date.day)

        # https://developers.facebook.com/docs/graph-api/reference/v2.0/post
        facebook_posts.append({
            'id': post['id'],
            'message': post['message'],
            'link': {
                'url': post['link'],
                'name': post['name'],
                'caption': (post['caption'] if 'caption' in post else None),
                'description': post['description'],
                'picture': post['picture']
            },
            'from': {
                'name': user['name'],
                'link': user['link'],
                'picture': user_picture['url']
            },
            'likes': likes['summary']['total_count'],
            'comments': comments['summary']['total_count'],
            #'shares': shares['summary']['total_count'],
            'creation_date': creation_date
        })

    # Render to JSON
    output = {
        'tweets': tweets,
        'facebook_posts': facebook_posts
    }

    with open('data/featured.json', 'w') as f:
        json.dump(output, f)

class Book(object):
    """
    A single book instance.
    __init__ cleans the data.
    """
    isbn = None
    isbn13 = None
    hide_ibooks = False
    title = None
    author = None
    genre = None
    reviewer = None
    text = None
    slug = None
    tags = None
    book_seamus_id = None
    itunes_id = None
    author_seamus_id = None
    author_seamus_headline = None

    review_seamus_id = None
    review_seamus_headline = None

    def __unicode__(self):
        """
        Returns a pretty value.
        """
        return self.title

    def __init__(self, **kwargs):
        """
        Process all fields for row in the spreadsheet for serialization
        """
        self.title = self._process_text(kwargs['title'])
        logger.debug('Processing %s' % self.title)
        self.book_seamus_id = kwargs['book_seamus_id']
        self.slug = self._slugify(kwargs['title'])

        self.author = self._process_text(kwargs['author'])
        self.hide_ibooks = kwargs['hide_ibooks']
        self.text = self._process_text(kwargs['text'])
        self.reviewer = self._process_text(kwargs['reviewer'])
        self.reviewer_id = self._process_text(kwargs['reviewer id'])
        self.reviewer_link = self._process_text(kwargs['reviewer link'])

        self.teaser = _make_teaser(self)

        if kwargs['html text']:
            self.html_text = True
        else:
            self.html_text = False

        self.isbn = self._process_text(kwargs['isbn'])
        if self.isbn:
            try:
                int(self.isbn[:8])
                self.isbn13 = self._process_isbn13(self.isbn)
            except ValueError:
                # Take into account ebooks as the unique format
                if self.isbn != kwargs['asin']:
                    msg = 'ISBN is not valid'
                    raise Exception(msg)
        else:
            msg = 'No ISBN'
            raise Exception(msg)
        if kwargs['oclc']:
            self.oclc = self._process_text(kwargs['oclc'])

        # ISBN redirection is broken use search API to retrieve itunes_id
        self.itunes_id = self._process_itunes_reference(kwargs['title'])
        self.links = self._process_links(kwargs['book_seamus_id'])
        self.tags = self._process_tags(kwargs['tags'])

    def _process_text(self, value):
        """
        Clean text field by replacing smart quotes and removing extra spaces
        """
        value = value.replace(u'“','"').replace(u'”','"')
        value = value.replace(u'’', "'")
        value = value.strip()
        return value

    def _process_tags(self, value):
        """
        Turn comma separated string of tags into list
        """
        item_list = []

        for item in value.split(','):
            if item != '':
                # Clean.
                item = self._process_text(item).replace(' and ', ' & ')

                # Look up from our map.
                tag_slug = TAGS_TO_SLUGS.get(item.lower(), None)

                # Append if the tag exists.
                if tag_slug:
                    item_list.append(tag_slug)
                else:
                    logger.warning('%s: Unknown tag "%s"' % (self.title, item))

        # Sort items by order in spreadsheet
        copy = copytext.Copy(app_config.COPY_PATH)

        ordered_items = []
        slugs = [tag['key'].__str__() for tag in copy['tags']]

        # Add slugs to new list in order from tags spreadsheet, not input order
        for slug in slugs:
            if slug in item_list:
                ordered_items.append(slug)

        return ordered_items

    def _process_links(self, value):
        """
        Get links for a book from NPR.org book page
        """
        book_page_url = 'http://www.npr.org/%s' % value
        logger.debug('%s: Getting links from %s' % (self.title, book_page_url))
        r = requests.get(book_page_url)
        soup = BeautifulSoup(r.content, 'html.parser')
        items = soup.select('.storylist article.item')
        item_list = []
        urls = []
        for item in items:
            link = {
                'category': '',
                'title': item.select('.title')[0].text.strip(),
                'url': item.select('.title a')[0].attrs.get('href'),
            }
            if link['url'] not in urls:
                category_elements = item.select('.slug')
                if len(category_elements):
                    category = category_elements[0].text.strip()
                    if category in app_config.LINK_CATEGORY_MAP.keys():
                        link['category'] = app_config.LINK_CATEGORY_MAP.get(category)
                    else:
                        link['category'] = app_config.LINK_CATEGORY_DEFAULT

                urls.append(link['url'])
                item_list.append(link)
                logger.debug('%s: Adding link %s - %s (%s)' % (self.title, link['category'], link['title'], link['url']))
            else:
                logger.info('%s: Duplicate link %s on %s' % (self.title, link['title'], link['url']))

        first_read = soup.select('.readexcerpt a')
        if len(first_read):
            link = {
                'category': 'Read an excerpt',
                'url': '%s#excerpt' % book_page_url,
                'title': '',
            }
            item_list.append(link)
            logger.debug('%s: Adding link %s - %s (%s)' % (self.title, link['category'], link['title'], link['url']))

        return item_list

    def _process_isbn13(self, value):
        """
        Calculate ISBN-13, see: http://www.ehow.com/how_5928497_convert-10-digit-isbn-13.html
        """
        if value.startswith('978'):
            return value
        else:
            isbn = '978%s' % value[:9]
            sum_even = 3 * sum(map(int, [isbn[1], isbn[3], isbn[5], isbn[7], isbn[9], isbn[11]]))
            sum_odd = sum(map(int, [isbn[0], isbn[2], isbn[4], isbn[6], isbn[8], isbn[10]]))
            remainder = (sum_even + sum_odd) % 10
            check = 10 - remainder if remainder else 0
            isbn13 = '%s%s' % (isbn, check)
            return isbn13

    def _slugify(self, value):
        """
        Slugify book title
        """
        slug = value.strip().lower()
        slug = re.sub(r"[^\w\s]", '', slug)
        slug = re.sub(r"\s+", '-', slug)
        slug = slug[:254]
        return slug

    def _process_itunes_reference(self, title):
        """
        Use itunes search API
        """
        itunes_id = None
        search_api_tpl = 'https://itunes.apple.com/search'
        main_title = title.split(':')[0]
        params = {
            'term': main_title,
            'country': 'US',
            'media': 'ebook',
            'attribute': 'titleTerm',
            'explicit': 'No'
        }
        query_string = urlencode(params)

        search_api_url = '%s?%s' % (search_api_tpl, query_string)
        logger.info('url: %s' % search_api_url)

        # Get search api results.
        r = requests.get(search_api_url, params=params)
        if r.status_code == 200:
            results = r.json()
            numResults = results['resultCount']
            if numResults:
                if numResults > 1:
                    logger.warning('More than one result for %s, picking first' % main_title)
                itunes_url = results['results'][0]['trackViewUrl']
                m = ITUNES_URL_ID_REGEX.search(itunes_url)
                if m:
                    itunes_id = m.group(1)
                    logger.info('itunes_id: %s' % itunes_id)
                else:
                    logger.warning('Did not find ibook id in %s' % itunes_url)
            else:
                logger.warning('no results found for %s' % main_title)
        else:
            logger.warning('did not receive a 200 when using itunes search api')
        return itunes_id




def get_books_csv():
    """
    Downloads the books CSV from google docs.
    """
    csv_url = 'https://docs.google.com/spreadsheets/d/%s/pub?gid=0&single=true&output=csv' % (
        app_config.DATA_GOOGLE_DOC_KEY)
    logger.debug(csv_url)
    r = requests.get(csv_url)
    if r.headers['content-type'] != 'text/csv':
        logger.error('Unexpected Content-type: %s. Are you sure the spreadsheet is published as csv?' % r.headers['content-type'])
        if app_config.LOCAL_CSV_PATH:
            shutil.copy(app_config.LOCAL_CSV_PATH, 'data/books.csv')
    else:
        with open('data/books.csv', 'wb') as writefile:
            writefile.write(r.content)

def get_tags():
    """
    Extract tags from COPY doc.
    """
    print 'Extracting tags from COPY'

    book = xlrd.open_workbook(app_config.COPY_PATH)

    sheet = book.sheet_by_name('tags')

    for i in range(1, sheet.nrows):
        slug, tag = sheet.row_values(i)

        slug = slug.strip()
        tag = tag.replace(u'’', "'").strip()

        SLUGS_TO_TAGS[slug] = tag
        TAGS_TO_SLUGS[tag.lower()] = slug

def parse_books_csv():
    """
    Parses the books CSV to JSON.
    Creates book objects which are cleaned and then serialized to JSON.
    """
    get_tags()

    # Open the CSV.
    with open('data/books.csv', 'r') as readfile:
        reader = CSVKitDictReader(readfile, encoding='utf-8')
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
        books = list(reader)

    logger.info("Start parse_books_csv(): %i rows." % len(books))

    book_list = []

    tags = {}

    for book in books:

        # Skip books with no title or ISBN
        if book['title'] == "":
            continue

        if book['isbn'] == "":
            logger.error('no isbn for title: %s' % book['title'])
            continue

        # Init a book class, passing our data as kwargs.
        # The class constructor handles cleaning of the data.
        try:
            b = Book(**book)
            time.sleep(1)
        except Exception, e:
            logger.error("Exception while parsing book: %s. Cause %s" % (
                book['title'],
                e))
            continue

        for tag in b.tags:
            if not tags.get(tag):
                tags[tag] = 1
            else:
                tags[tag] += 1

        # Grab the dictionary representation of a book.
        book_list.append(b.__dict__)

    # Dump the list to JSON.
    with open('www/static-data/books.json', 'wb') as writefile:
        writefile.write(json.dumps(book_list))

    with open('data/test-itunes-equiv.csv', 'w') as fout:
        writer = CSVKitDictWriter(fout,
                                  fieldnames=['title', 'isbn',
                                              'isbn13', 'itunes_id'],
                                  extrasaction='ignore')
        writer.writeheader()
        writer.writerows(book_list)

    with open('data/tag-audit.csv', 'w') as f:
        writer = csv.writer(f)
        writer.writerow(['tag', 'slug', 'count'])
        for slug, count in tags.items():
            writer.writerow([slug, SLUGS_TO_TAGS[slug], count])
    logger.info("End.")


@task
def load_books():
    """
    Loads/reloads just the book data.
    Does not save image files.
    """
    logger.info("start load_books")
    logger.info("get books csv")
    get_books_csv()
    logger.info("start parse_books_csv")
    parse_books_csv()
    logger.info("end load_books")


@task
def load_images():
    """
    Downloads images from Baker and Taylor.
    Eschews the API for a magic URL pattern, which is faster.
    """

    # Secrets.
    secrets = app_config.get_secrets()

    # Open the books JSON.
    with open('www/static-data/books.json', 'rb') as readfile:
        books = json.loads(readfile.read())

    print "Start load_images(): %i books." % len(books)

    # Loop.
    for book in books:

        # Skip books with no title or ISBN.
        if book['title'] == "":
            logger.warning('found book with no title')
            continue

        if 'isbn' not in book or book['isbn'] == "":
            logger.warning('This book has no isbn: %s' % book['title'])
            continue

        # Construct the URL with secrets and the ISBN.
        book_url = "http://imagesa.btol.com/ContentCafe/Jacket.aspx"

        params = {
            'UserID': secrets['BAKER_TAYLOR_USERID'],
            'Password': secrets['BAKER_TAYLOR_PASSWORD'],
            'Value': book['isbn'],
            'Return': 'T',
            'Type': 'L'
        }

        # Request the image.
        r = requests.get(book_url, params=params)

        path = 'www/assets/cover'
        if not os.path.exists(path):
            os.makedirs(path)

        imagepath = '%s/%s.jpg' % (path, book['slug'])

        if os.path.exists(imagepath):
            logger.debug('image already downloaded for: %s' % book['slug'])

        # Write the image to www using the slug as the filename.
        with open(imagepath, 'wb') as writefile:
            writefile.write(r.content)

        file_size = os.path.getsize(imagepath)
        if file_size < 10000:
            logger.info('(%s): Image not available from Baker and Taylor, using NPR book page' % book['title'])
            url = 'http://www.npr.org/%s' % book['book_seamus_id']
            npr_r = requests.get(url)
            soup = BeautifulSoup(npr_r.content, 'html.parser')
            try:
                if book['title'] == 'The Three-Body Problem':
                    alt_img_url = 'http://media.npr.org/assets/bakertaylor/covers/t/the-three-body-problem/9780765377067_custom-d83e0e334f348e6c52fe5da588ec3448921af64f-s600-c85.jpg'
                else:
                    alt_img_url = soup.select('.bookedition .image img')[0].attrs.get('src').replace('s99', 's400')
                logger.info('LOG (%s): Getting alternate image from %s' % (book['title'], alt_img_url))
                alt_img_resp = requests.get(alt_img_url)
                with open(imagepath, 'wb') as writefile:
                    writefile.write(alt_img_resp.content)
            except IndexError:
                logger.info('ERROR (%s): Image not available on NPR book page either (%s)' % (book['title'], url))

        image = Image.open(imagepath)
        image.save(imagepath, optimize=True, quality=75)

    logger.info("Load Images End.")


@task
def make_promotion_thumb():
    images_per_column = TOTAL_IMAGES / IMAGE_COLUMNS
    image_width = PROMOTION_IMAGE_WIDTH / IMAGE_COLUMNS
    max_height = int(image_width * images_per_column * 1.5)
    thumb_size = [image_width, image_width]
    image = Image.new('RGB', [PROMOTION_IMAGE_WIDTH, max_height])

    # Open the books JSON.
    with open('www/static-data/books.json', 'rb') as readfile:
        books = json.loads(readfile.read())

    coordinates = [0, 0]
    last_y = 0
    total_height = 0
    min_height = None
    column_multiplier = 0

    for i, book in enumerate(books[:TOTAL_IMAGES]):
        if i % images_per_column == 0:
            if not min_height or total_height < min_height:
                min_height = total_height
            coordinates[0] = column_multiplier * image_width
            coordinates[1] = 0
            last_y = 0
            column_multiplier +=1
            total_height = 0

        path = 'www/assets/cover/%s.jpg' % book['slug']
        book_image = Image.open(path)
        width, height = book_image.size
        ratio = width / float(image_width)
        new_height = int(height / ratio)
        resized = book_image.resize((image_width, new_height), Image.ANTIALIAS)
        coordinates[1] = coordinates[1] + last_y
        image.paste(resized, tuple(coordinates))
        last_y = new_height
        total_height += new_height

    min_prop_width = min_height * 16 / float(9)
    # Make the proportion fit the highest full thumbnail width
    # that complies with the proportion
    final_width = int(min_prop_width / image_width) * 40
    cropped = image.crop((0, 0, final_width, min_height))
    cropped.save('www/assets/img/covers.jpg')


def _scrape_page(url):
    """
    scrape a book review archive page
    return list of found reviews and the last date
    """
    reviews = []
    r = requests.get(url)
    if r.status_code == 200:
        soup = BeautifulSoup(r.content, 'html.parser')
        archivelist =  soup.find('div', class_="archivelist")
        items = archivelist.findAll('article', class_="item")
        logger.info(len(items))
        for item in items:
            review = {}
            t = item.find('time')
            if t:
                published_date = t['datetime']
            else:
                published_date = None
            logger.debug('published_date: %s' % published_date)
            review['published_date'] = published_date
            a = item.find('h2', class_='title').find('a')
            if a:
                book_review = a['href']
            else:
                book_review = None
            logger.debug('review_link: %s' % book_review)
            review['review_link'] = book_review
            review['review_seamus_id'] = book_review.split('/')[6]
            reviews.append(review)
        return reviews, published_date
    else:
        return None, None

@task
def scrape_book_reviews():
    """
    Loads/reloads just the book data.
    Does not save image files.
    """
    HEADER = ["published_date", "review_link", "review_seamus_id"]
    logger.info("start scrape books")
    reviews_url_tpl = 'http://www.npr.org/sections/book-reviews/archive?date=%s%s'
    reviews = []
    with open('data/book_reviews.csv', 'w') as fout:
        writer = CSVKitDictWriter(fout, fieldnames=HEADER)
        writer.writeheader()
        for month in reversed(range(1, 13)):
            # Initialize first iteration for the month
            last_date = '2016-%s-31' % month
            bits = last_date.split('-')
            scrape_month = int(bits[1])
            while scrape_month == month:
                time.sleep(2)
                new_date_suffix = '-%s-%s' % (bits[2], bits[0])
                url = reviews_url_tpl % (scrape_month, new_date_suffix)
                rows, last_date = _scrape_page(url)
                if rows:
                    reviews.extend(rows)
                bits = last_date.split('-')
                scrape_month = int(bits[1])
                logger.info('last_date: %s' % last_date)
        unique_reviews = [dict(t) for t in set([tuple(d.items()) for d in reviews])]
        sorted_reviews = sorted(unique_reviews, key=lambda k: k['published_date'], reverse=True)
        writer.writerows(sorted_reviews)


    logger.info("end scrape books")
