# This file is part of the MapProxy project.
# Copyright (C) 2010 Omniscale <http://omniscale.de>
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
# 
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Service responses.
"""

import os
import hashlib
import mimetypes
from mapproxy.util.times import format_httpdate, parse_httpdate, timestamp
from mapproxy.wsgiapp import ctx

class Response(object):
    charset = 'utf-8'
    default_content_type = 'text/plain'
    block_size = 1024 * 32
    
    def __init__(self, response, status=None, content_type=None, mimetype=None):
        self.response = response
        if status is None:
            status = 200
        self.status = status
        self._timestamp = None
        self.headers = {}
        if mimetype:
            if mimetype.startswith('text/'):
                content_type = mimetype + '; charset=' + self.charset
            else:
                content_type = mimetype
        if content_type is None:
            content_type = self.default_content_type
        self.headers['Content-type'] = content_type
    
    def _status_set(self, status):
        if isinstance(status, (int, long)):
            status = status_code(status)
        self._status = status
    
    def _status_get(self):
        return self._status
    
    status = property(_status_get, _status_set)
    
    def _last_modified_set(self, date):
        if not date: return
        self._timestamp = timestamp(date)
        self.headers['Last-modified'] = format_httpdate(self._timestamp)
    def _last_modified_get(self):
        return self.headers.get('Last-modified', None)

    last_modified = property(_last_modified_get, _last_modified_set)
    
    def _etag_set(self, value):
        self.headers['ETag'] = value
    
    def _etag_get(self):
        return self.headers.get('ETag', None)
    
    etag = property(_etag_get, _etag_set)
    
    def cache_headers(self, timestamp=None, etag_data=None, max_age=None):
        """
        Set cache-related headers.
        
        :param timestamp: local timestamp of the last modification of the
            response content
        :param etag_data: list that will be used to build an ETag hash.
            calls the str function on each item.
        :param max_age: the maximum cache age in seconds 
        """
        self.last_modified = timestamp
        if etag_data:
            hash_src = ''.join((str(x) for x in etag_data))
            self.etag = hashlib.md5(hash_src).hexdigest()
        if (timestamp or etag_data) and max_age is not None:
            self.headers['Cache-control'] = 'max-age=%d public' % max_age
    
    def make_conditional(self, environ):
        """
        Make the response conditional to the HTTP headers in the CGI/WSGI `environ`.
        Checks for ``If-none-match`` and ``If-modified-since`` headers and compares
        to the etag and timestamp of this response. If the content was not modified
        the repsonse will changed to HTTP 304 Not Modified.
        """
        not_modified = False
        
        if self.etag == environ.get('HTTP_IF_NONE_MATCH', -1):
            not_modified = True        
        elif self._timestamp is not None:
            date = environ.get('HTTP_IF_MODIFIED_SINCE', None)
            timestamp = parse_httpdate(date)
            if timestamp is not None and self._timestamp <= timestamp:
                not_modified = True
        
        if not_modified:
            self.status = 304
            self.response = []
            if 'Content-type' in self.headers:
                del self.headers['Content-type']
    
    @property
    def content_length(self):
        return int(self.headers.get('Content-length', 0))
    
    @property
    def content_type(self):
        return self.headers['Content-type']
    
    @property
    def data(self):
        if hasattr(self.response, 'read'):
            return self.response.read()
        else:
            return ''.join(chunk.encode() for chunk in self.response)
    
    @property
    def fixed_headers(self):
        headers = []
        for key, value in self.headers.iteritems():
            headers.append((key, value.encode()))
        return headers
    
    def __call__(self, environ, start_response):
        if hasattr(self.response, 'read'):
            if ((not hasattr(self.response, 'ok_to_seek') or 
                self.response.ok_to_seek) and
               (hasattr(self.response, 'seek') and
                hasattr(self.response, 'tell'))):
                self.response.seek(0, 2) # to EOF
                self.headers['Content-length'] = str(self.response.tell())
                self.response.seek(0)
            if 'wsgi.file_wrapper' in environ:
                resp_iter = environ['wsgi.file_wrapper'](self.response, self.block_size)
            else:
                resp_iter = iter(lambda: self.response.read(self.block_size), '')
        else:
            if isinstance(self.response, basestring):
                self.headers['Content-length'] = str(len(self.response))
                self.response = [self.response]
            resp_iter = self.iter_encode(self.response)
        
        start_response(self.status, self.fixed_headers)
        return resp_iter

    def iter_encode(self, chunks):
        for chunk in chunks:
            if isinstance(chunk, unicode):
                chunk = chunk.encode(self.charset)
            yield chunk

def static_file_response(filename, max_age=None):
    """
    Create a Response for a file. Sets HTTP caching-headers (Last-modified and ETag)
    according to the file stats and the optional max_age (for Cache-control).
    
    :param max_age: ``Cache-control`` ``max-age`` in seconds.
    """
    content_type = mimetypes.guess_type(filename)[0]
    if content_type is None:
        content_type = 'text/plain'
    f = open(filename)
    mtime = os.lstat(filename).st_mtime
    size = os.stat(filename).st_size
    resp = Response(f, content_type=content_type)
    resp.cache_headers(mtime, etag_data=(mtime, size),
                       max_age=max_age)
    if hasattr(ctx, 'env'):
        resp.make_conditional(ctx.env)
    return resp

# http://www.faqs.org/rfcs/rfc2616.html
_status_codes = {
    100: 'Continue',
    101: 'Switching Protocols',
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary Redirect',
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Time-out',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Request Entity Too Large',
    414: 'Request-URI Too Large',
    415: 'Unsupported Media Type',
    416: 'Requested range not satisfiable',
    417: 'Expectation Failed',
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Time-out',
    505: 'HTTP Version not supported',
}

def status_code(code):
    return str(code) + ' ' + _status_codes[code]
    