from fnmatch import fnmatchcase


class Folder(object):
    def __init__(self, name, services, logger,
                 mimetypes=None, file_size=None,
                 blacklist=None, whitelist=None, **kwargs):
        self.name = name
        self.services = frozenset(services)
        self.logger = logger
        self.options = kwargs

        self.mimetypes = mimetypes

        if not file_size:
            file_size = {}

        self.min_size = self._to_bytes(file_size.get('min'))
        self.max_size = self._to_bytes(file_size.get('max'))

        self.blacklist = blacklist
        self.whitelist = whitelist

    def __str__(self):
        return self.name

    def __repr__(self):
        return u"<Folder {}: services={}, options={}>".format(
            self.name, list(self.services), self.options
        )

    @classmethod
    def get_folders(cls, escalator, services, logger):
        service_folders = {
            s: escalator.get(u'service:{}:folders'.format(s), default=[])
            for s in services
        }

        folders = {}

        for key, options in escalator.range('folder:'):
            name = key.split(':')[-1]
            dest = filter(lambda s: name in service_folders[s], services)
            folders[name] = cls(name, dest, logger, **options)

        return folders

    def targets(self, metadata, source):
        filename = metadata['filename']

        if not self.check_size(metadata['size']):
            self.logger.info(
                "Ignoring event for '{}' in folder {} due to its size: "
                "{} bytes",
                filename, self.name, metadata['size']
            )
            return

        if not self.check_mimetype(metadata['mimetype']):
            self.logger.info(
                "Ignoring event for '{}' in folder {} due to its mimetype: {}",
                filename, self.name, metadata['mimetype']
            )
            return

        if self.blacklisted(filename):
            self.logger.info(
                "Ignoring event for '{}' in folder {} because its filename "
                "is blacklisted",
                filename, self.name
            )
            return

        if not self.whitelisted(filename):
            self.logger.info(
                "Ignoring event for '{}' in folder {} because its filename "
                "is not whitelisted",
                filename, self.name
            )
            return

        return self.services - frozenset((source,))

    def check_size(self, size):
        if self.min_size is not None and size < self.min_size:
            return False

        if self.max_size is not None and size > self.max_size:
            return False

        return True

    def check_mimetype(self, mimetype):
        if self.mimetypes is None:
            return True

        return any(fnmatchcase(mimetype, c) for c in self.mimetypes)

    def blacklisted(self, filename):
        if self.blacklist is None:
            return False

        return any(fnmatchcase(filename, rule) for rule in self.blacklist)

    def whitelisted(self, filename):
        if self.whitelist is None:
            return True

        return any(fnmatchcase(filename, rule) for rule in self.whitelist)

    def _to_bytes(self, size):
        units = {
            '': 1e0,
            'b': 1e0,
            'o': 1e0,

            'k': 1e3,
            'ko': 1e3,
            'kb': 1e3,

            'm': 1e6,
            'mo': 1e6,
            'mb': 1e6,

            'g': 1e9,
            'go': 1e9,
            'gb': 1e9,

            't': 1e12,
            'to': 1e12,
            'tb': 1e12,

            'p': 1e15,
            'po': 1e15,
            'pb': 1e15,

            'ki': 2 ** 10,
            'mi': 2 ** 20,
            'gi': 2 ** 30,
            'ti': 2 ** 40,
            'pi': 2 ** 50,
        }

        if size is None:
            return None

        try:
            return int(size)
        except ValueError:
            pass

        size = size.replace(' ', '')
        unit = size.lstrip('0123456789.').lower()
        size = size[:-len(unit)] if len(unit) else size

        if unit not in units:
            return None

        try:
            return int(float(size) * units[unit])
        except ValueError:
            pass

        return None
