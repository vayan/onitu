import os
import json

from plyvel import destroy_db

from onitu.utils import TMPDIR, b, get_random_string

from .launcher import Launcher


class Setup(object):
    def __init__(self, folders=None):
        self.services = {}
        if folders is None:
            folders = {}
        self.folders = folders

        self._json = None

        self.name = get_random_string(15)
        self.filename = os.path.join(TMPDIR, "{}.json".format(self.name))

    def add(self, service):
        service.connect(self.name)
        self.services[service.name] = service

        for folder in service.folders.keys():
            if folder not in self.folders:
                self.folders[folder] = {}

        return self

    def clean(self, services=True):
        if services:
            for service in self.services.values():
                service.close()

        try:
            os.unlink(self.filename)
            destroy_db(u'dbs/{}'.format(self.name))
        except (OSError, IOError):
            pass

    @property
    def dump(self):
        setup = {}
        if self.name:
            setup['name'] = self.name
        setup['services'] = {name: e.dump for name, e in self.services.items()}
        setup['folders'] = self.folders
        return setup

    @property
    def json(self):
        if not self._json:
            self._json = json.dumps(self.dump, indent=2, ensure_ascii=False)

        return self._json

    @json.setter
    def json(self, content):
        self._json = content

    def save(self):
        print('Setup:')
        print(self.json)

        with open(self.filename, 'wb+') as f:
            f.write(b(self.json))

    def get_launcher(self):
        return Launcher(self)
