import io
import requests
import hashlib

from xml.etree.ElementTree import fromstring, ElementTree
from requests_toolbelt import MultipartEncoder
from requests_oauthlib import OAuth1

from onitu.plug import Plug, ServiceError

plug = Plug()
root = None
flickr = None

# ############################## OAUTH ######################################


class Flickr():
    def __init__(self, client_key, client_secret, oauth_token,
                 oauth_token_secret, root):
        self.client_key = client_key
        self.client_secret = client_secret
        self.oauth_token = oauth_token
        self.oauth_token_secret = oauth_token_secret
        self.root = root
        self.photoset_id = None

        self.oauth = OAuth1(client_key,
                            client_secret=client_secret,
                            resource_owner_key=oauth_token,
                            resource_owner_secret=oauth_token_secret)

        self.rest_url = 'https://api.flickr.com/services/rest/'
        self.upload_url = 'https://up.flickr.com/services/upload/'
        self.replace_url = 'https://up.flickr.com/services/replace/'
        # Used as tag to found onitu files on the flickr account
        # (Do not remove it from your files)
        self.onitu_tag = 'ONITU_TAG/'

        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'method': 'flickr.test.login'
        }

        r = self.call(requests.get, self.rest_url, params=params,
                      auth=self.oauth)
        self.user_id = r.json()['user']['id']

# ############################## UTILS ######################################

    def create_tag(self, metadata):
        return '{}{}/{}'.format(
            self.onitu_tag, self.root, hashlib.md5(
                metadata.filename + str(metadata.size)
            ).hexdigest()
        )

    def load_tag_id(self, metadata):
        return self.get_tag_id(self.load_photo_id(metadata),
                               metadata.extra['tag'])

    def load_photo_id(self, metadata):
        if 'id' in metadata.extra:
            return metadata.extra['id']
        return self.search_file(metadata)

    def call(self, func, url, **kwargs):
        try:
            r = func(url, **kwargs)
        except requests.exceptions.RequestException:
            raise ServiceError('Impossible to join Flickr api')

        if r.status_code // 100 != 2:
            raise ServiceError(
                'Call: Status code {} received.'.format(r.status_code)
            )
        return r

    def do_upload(self, url, content, params=None):
        """Performs a file upload to the given URL with
        the given parameters, signed with OAuth."""

        # work-around for Flickr expecting 'photo' to be excluded
        # from the oauth signature:
        #   1. create a dummy request without 'photo'
        #   2. create real request and use auth headers from the dummy one
        dummy_req = requests.Request('POST', url, data=params,
                                     auth=self.oauth)

        prepared = dummy_req.prepare()
        headers = prepared.headers

        fileobj = io.BytesIO(content)
        params['photo'] = (params['title'], fileobj)

        m = MultipartEncoder(fields=params)
        auth = {'Authorization': headers.get('Authorization'),
                'Content-Type': m.content_type}

        return self.call(requests.post, url, data=m, headers=auth)

    def search_file(self, metadata):
        """ Return None if no file or many files are found.
        return file id otherwise """
        tag = self.create_tag(metadata)

        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'user_id': self.user_id,
            'method': 'flickr.photos.search',
            'tags': tag
        }

        r = self.call(requests.get, self.rest_url, params=params,
                      auth=self.oauth)
        json = r.json()

        res_nb = len(json['photos']['photo'])
        if (res_nb == 0) or (res_nb > 1):
            return None
        else:
            return json['photos']['photo'][0]['id']

# ############################## FLICKR ######################################

    def upload_file(self, metadata, content):

        photo_id = self.load_photo_id(metadata)
        tag = metadata.extra['tag']
        title = metadata.filename

        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'photo_id': photo_id,  # only used for replacement
            'title': title,
            'description': 'Uploaded by onitu',
            'tags': tag,
            'is_public': '0',
            'is_friend': '0',
            'is_family': '0',
            'safety_level': '1',
            'hidden': '1'
        }

        params = {k: v for k, v in params.items() if v is not None}

        url = self.replace_url if photo_id else self.upload_url
        r = self.do_upload(url, content, params=params).content

        tree = ElementTree(fromstring(r)).getroot()
        photo_id = tree.find('photoid').text
        r = self.list_photosets()

        if self.photoset_id is None:
            photoset_list = r.json()['photosets']['photoset']
            for p in photoset_list:
                if (p['title']['_content'] == root and
                        p['description']['_content'] == 'onitu'):
                    self.photoset_id = p['id']
                    break

        if self.photoset_id is not None:
            self.add_photo_to_photoset(photo_id, self.photoset_id)
        else:
            r = self.create_photoset(root, photo_id, 'onitu')
            self.photoset_id = r.json()['photoset']['id']

        metadata.extra['id'] = photo_id
        metadata.write()

    def get_file(self, metadata):
        """ Return the file content """

        photo_id = self.load_photo_id(metadata)
        if photo_id:
            params = {
                'format': 'json',
                'nojsoncallback': '1',
                'method': 'flickr.photos.getSizes',
                'photo_id': photo_id
            }

            r = self.call(requests.get, self.rest_url, params=params,
                          auth=self.oauth)

            # 5 = Original size
            url = r.json()['sizes']['size'][5]['source']
            r = self.call(requests.get, url)
            return r.content

    def delete_file(self, metadata):

        photo_id = self.load_photo_id(metadata)
        if photo_id:
            params = {
                'format': 'json',
                'nojsoncallback': '1',
                'method': 'flickr.photos.delete',
                'photo_id': photo_id
            }

            self.call(requests.get, self.rest_url, params=params,
                      auth=self.oauth)

    def get_tag_id(self, photo_id, tag_name):
        try:
            tags = self.get_file_info(photo_id)['photo']['tags']['tag']
        except KeyError:
            plug.logger.warning(
                "get_tag_id: Cannot find tag id of tag '{}'".format(tag_name))
            return None
        for tag in tags:
            if tag['raw'] == tag_name:
                return tag['id']
        return None

    def move_file(self, old, new):

        photo_id = self.load_photo_id(old)
        new_tag = self.create_tag(new)

        if photo_id:
            self.rename_file(photo_id, new.filename)
            tag_id = self.load_tag_id(old)
            if tag_id:
                self.remove_tag(tag_id)
                self.add_tags(photo_id, new_tag)
                new.extra['tag'] = new_tag
                new.write()

        if not photo_id or not tag_id:
            plug.logger.warning(
                "move_file: Cannot move file '{}'".format(old.filename))

    def get_file_info(self, photo_id):
        """ Return a json with photo infos """

        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'method': 'flickr.photos.getInfo',
            'photo_id': photo_id
        }

        r = self.call(requests.get, self.rest_url, params=params,
                      auth=self.oauth)
        return r.json()

    def remove_tag(self, tag_id):

        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'method': 'flickr.photos.removeTag',
            'tag_id': tag_id
        }

        self.call(requests.post, self.rest_url, params=params, auth=self.oauth)

    def add_tags(self, photo_id, tags):

        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'method': 'flickr.photos.addTags',
            'photo_id': photo_id,
            'tags': tags
        }

        self.call(requests.post, self.rest_url, params=params, auth=self.oauth)

    def rename_file(self, photo_id, title):

        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'method': 'flickr.photos.setMeta',
            'photo_id': photo_id,
            'title': title,
            'description': 'Uploaded by onitu'  # required parameter
        }

        self.call(requests.post, self.rest_url, params=params, auth=self.oauth)

# ############################# PHOTOSETS ###################################

    def list_photosets(self):
        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'user_id': self.user_id,
            'method': 'flickr.photosets.getList'
        }

        return self.call(requests.get, self.rest_url, params=params,
                         auth=self.oauth)

    def add_photo_to_photoset(self, photo_id, photoset_id):
        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'photoset_id': photoset_id,
            'photo_id': photo_id,
            'method': 'flickr.photosets.addPhoto'
        }

        return self.call(requests.post, self.rest_url, params=params,
                         auth=self.oauth)

    def create_photoset(self, title, primary_photo_id, description=None):
        params = {
            'format': 'json',
            'nojsoncallback': '1',
            'title': title,
            'description': description,
            'method': 'flickr.photosets.create',
            'primary_photo_id': primary_photo_id
        }

        params = {k: v for k, v in params.items() if v is not None}

        return self.call(requests.get, self.rest_url, params=params,
                         auth=self.oauth)


# ############################# ONITU BASIC ###################################


@plug.handler()
def move_file(old_metadata, new_metadata):
    flickr.move_file(old_metadata, new_metadata)


@plug.handler()
def get_file(metadata):
    flickr.get_file(metadata)


@plug.handler()
def start_upload(metadata):
    metadata.extra['tag'] = flickr.create_tag(metadata)


@plug.handler()
def upload_file(metadata, content):
    flickr.upload_file(metadata, content)


@plug.handler()
def delete_file(metadata):
    flickr.delete_file(metadata)


def start():
    # Clean the root
    global root
    root = plug.options['root']
    if root.startswith('/'):
        root = root[1:]
    if root.endswith('/'):
        root = root[:-1]

    onitu_client_id = plug.options['onitu_client_id']
    onitu_client_secret = plug.options['onitu_client_secret']

    global flickr
    flickr = Flickr(onitu_client_id, onitu_client_secret,
                    plug.options['oauth_token'],
                    plug.options['oauth_token_secret'], root)

    plug.listen()
