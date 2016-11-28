#!/usr/bin/env python
"""
Example application views.

Note that `render_template` is wrapped with `make_response` in all application
routes. While not necessary for most Flask apps, it is required in the
App Template for static publishing.
"""

import app_config
import json
import oauth
import static
import re
import string

from PIL import Image
from flask import Flask, make_response, render_template
from render_utils import make_context, smarty_filter, urlencode_filter
from werkzeug.debug import DebuggedApplication

app = Flask(__name__)
app.debug = app_config.DEBUG

app.add_template_filter(smarty_filter, name='smarty')
app.add_template_filter(urlencode_filter, name='urlencode')


@app.route('/')
@oauth.oauth_required
def index():
    """
    Example view demonstrating rendering a simple HTML page.
    """
    context = make_context()

    with open('data/featured.json') as f:
        context['featured'] = json.load(f)

     # Read the books JSON into the page.
    with open('www/static-data/books.json', 'rb') as readfile:
        context['books_js'] = readfile.read()

    return make_response(render_template('index.html', **context))


@app.route('/share/<slug>.html')
def share(slug):
    featured_book = None
    context = make_context()
    with open('www/static-data/books.json', 'rb') as f:
        books = json.load(f)
        for book in books:
            if book.get('slug') == slug:
                featured_book = book
                break

    if not featured_book:
        return 404

    featured_book['thumb'] = "%sassets/cover/%s.jpg" % (context['SHARE_URL'], featured_book['slug'])
    try:
        book_image = Image.open('www/assetsdss/cover/%s.jpg' % featured_book['slug'])
        width, height = book_image.size
        context['thumb_width'] = width
        context['thumb_height'] = height
    except IOError:
        context['thumb_width'] = None
        context['thumb_height'] = None

    context['twitter_handle'] = 'nprbooks'
    context['book'] = featured_book

    return make_response(render_template('share.html', **context))


@app.route('/seamus')
def seamus():
    """
    Preview for Seamus page
    """
    context = make_context()

    # Read the books JSON into the page.
    with open('www/static-data/books.json', 'rb') as readfile:
        books_data = json.load(readfile)
        books = sorted(books_data, key=lambda k: k['title'])

    # Harvest long tag names
    for book in books:
        tag_list = []
        for tag in book['tags']:
            tag_list.append(context['COPY']['tags'][tag]['value'])
        book['tag_list'] = tag_list

    context['books'] = books

    return render_template('seamus-preview.html', **context)

app.register_blueprint(static.static)
app.register_blueprint(oauth.oauth)

# Enable Werkzeug debug pages
if app_config.DEBUG:
    wsgi_app = DebuggedApplication(app, evalex=False)
else:
    wsgi_app = app

# Catch attempts to run the app directly
if __name__ == '__main__':
    print 'This command has been removed! Please run "fab app" instead!'


@app.route('/coming-soon')
def coming_soon():

    context = make_context()
    
    with open('data/featured.json') as f:
        context['featured'] = json.load(f)

    return make_response(render_template('coming-soon.html', **context))
