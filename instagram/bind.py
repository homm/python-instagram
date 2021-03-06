from __future__ import absolute_import

from .oauth2 import OAuth2Request
import re
from .json_import import simplejson

import six
from six.moves.urllib.parse import quote


re_path_template = re.compile('{\w+}')


def encode_string(value):
    if isinstance(value, bytes):
        return value

    if not isinstance(value, six.text_type):
        value = six.text_type(value)

    return value.encode('utf-8')


class InstagramClientError(Exception):
    def __init__(self, error_message):
        self.error_message = error_message

    def __str__(self):
        return self.error_message


class InstagramAPIError(Exception):

    def __init__(self, status_code, error_type, error_message, *args, **kwargs):
        self.status_code = status_code
        self.error_type = error_type
        self.error_message = error_message

    def __str__(self):
        return "(%s) %s-%s" % (self.status_code, self.error_type, self.error_message)


def bind_method(**config):

    class InstagramAPIMethod(object):

        path = config['path']
        method = config.get('method', 'GET')
        accepts_parameters = config.get("accepts_parameters", [])
        requires_target_user = config.get('requires_target_user', False)
        paginates = config.get('paginates', False)
        pagination_key = config.get('pagination_key', 'max_id')
        root_class = config.get('root_class', None)
        response_type = config.get("response_type", "list")
        include_secret = config.get("include_secret", False)
        objectify_response = config.get("objectify_response", True)

        def __init__(self, api, *args, **kwargs):
            self.api = api
            self.as_generator = kwargs.pop("as_generator", False)
            self.return_json = kwargs.pop("return_json", False)
            if not kwargs.pop("return_pagination_id", False):
                self.pagination_key = 'url'
            self.max_pages = kwargs.pop("max_pages", 3)
            self.parameters = {}
            self._build_parameters(args, kwargs)
            self._build_path()

        def _build_parameters(self, args, kwargs):
            # via tweepy https://github.com/joshthecoder/tweepy/
            for index, value in enumerate(args):
                if value is None:
                    continue

                try:
                    self.parameters[self.accepts_parameters[index]] = encode_string(value)
                except IndexError:
                    raise InstagramClientError("Too many arguments supplied")

            for key, value in kwargs.items():
                if value is None:
                    continue
                if key in self.parameters:
                    raise InstagramClientError("Parameter %s already supplied" % key)
                self.parameters[key] = encode_string(value)

            # Parameter 'pagination_id' is alias to self.pagination_key
            if self.paginates and self.pagination_key not in self.parameters \
               and kwargs.get('pagination_id') is not None:
                self.parameters[self.pagination_key] = kwargs['pagination_id']

            if 'user_id' in self.accepts_parameters and 'user_id' not in self.parameters \
               and not self.requires_target_user:
                self.parameters['user_id'] = 'self'

        def _build_path(self):
            for variable in re_path_template.findall(self.path):
                name = variable.strip('{}')

                try:
                    value = quote(self.parameters[name])
                except KeyError:
                    raise Exception('No parameter value found for path variable: %s' % name)
                del self.parameters[name]

                self.path = self.path.replace(variable, value)
            self.path = self.path + '.%s' % self.api.format

        def _do_api_request(self, url, method="GET", body=None, headers=None):
            headers = headers or {}
            response, content = OAuth2Request(self.api).make_request(url, method=method, body=body, headers=headers)
            if response['status'] in ('429', '503'):
                raise InstagramAPIError(response['status'], "Rate limited", "Your client is making too many request per second")

            try:
                content_obj = simplejson.loads(content)
            except ValueError:
                raise InstagramClientError('Unable to parse response, not valid JSON.')

            api_responses = []
            status_code = content_obj['meta']['code']
            if status_code == 200:
                if not self.objectify_response:
                    return content_obj, None

                if self.response_type == 'list':
                    for entry in content_obj['data']:
                        if self.return_json:
                            api_responses.append(entry)
                        else:
                            obj = self.root_class.object_from_dictionary(entry)
                            api_responses.append(obj)
                elif self.response_type == 'entry':
                    data = content_obj['data']
                    if self.return_json:
                        api_responses = data
                    else:
                        api_responses = self.root_class.object_from_dictionary(data)
                elif self.response_type == 'empty':
                    pass
                return api_responses, content_obj.get('pagination', {})
            else:
                raise InstagramAPIError(status_code, content_obj['meta']['error_type'], content_obj['meta']['error_message'])

        def _paginator_with_url(self, url, method="GET", body=None, headers=None):
            headers = headers or {}
            pages_read = 0
            while url and pages_read < self.max_pages:
                api_responses, pagination = self._do_api_request(url, method, body, headers)
                pages_read += 1
                url = pagination.get('next_url')
                yield api_responses, pagination.get('next_' + self.pagination_key)
            return

        def execute(self):
            url, method, body, headers = OAuth2Request(self.api).prepare_request(self.method,
                                                                                 self.path,
                                                                                 self.parameters,
                                                                                 include_secret=self.include_secret)
            if self.as_generator:
                return self._paginator_with_url(url, method, body, headers)
            else:
                content, pagination = self._do_api_request(url, method, body, headers)
            if self.paginates:
                return content, pagination.get('next_' + self.pagination_key)
            else:
                return content

    def _call(api, *args, **kwargs):
        method = InstagramAPIMethod(api, *args, **kwargs)
        return method.execute()

    return _call
