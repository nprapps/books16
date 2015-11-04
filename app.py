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

def _title_sorter(book):
    title = book['title']
    if title.startswith('The'):
        title = book['title'][4:]
    return title

def _make_teaser(book):
    """
    Calculate a teaser
    """
    tag_stripper = re.compile(r'<.*?>')

    try:
        img = Image.open('www/assets/cover/%s.jpg' % book['slug'])
        width, height = img.size

        # Poor man's packing algorithm. How much text will fit?
        chars = height / 25 * 7
    except IOError:
        chars = 140

    text = tag_stripper.sub('', book['text'])

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
        books = json.loads(context['books_js'])
        books_text_only = books[:]
        books_text_only = sorted(books, key=_title_sorter)

    for book in books:
        if not book['text']:
            book['teaser'] = None
        else:
            book['teaser'] = _make_teaser(book)

    context['books'] = books
    context['books_text_only'] = books_text_only

    return make_response(render_template('index.html', **context))

@app.route('/comments/')
def comments():
    """
    Full-page comments view.
    """
    return make_response(render_template('comments.html', **make_context()))

@app.route('/widget.html')
def widget():
    """
    Embeddable widget example page.
    """
    return make_response(render_template('widget.html', **make_context()))

@app.route('/test_widget.html')
def test_widget():
    """
    Example page displaying widget at different embed sizes.
    """
    return make_response(render_template('test_widget.html', **make_context()))

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
