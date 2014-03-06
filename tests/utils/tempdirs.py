import tempfile
from shutil import rmtree


class TempDirs(object):
    def __init__(self):
        self.dirs = set()

    def __del__(self):
        self.delete_all()

    def create(self):
        d = tempfile.mkdtemp()
        self.dirs.add(d)
        return d

    def delete(self, d):
        if d in self.dirs:
            rmtree(d)
            self.dirs.remove(d)

    def delete_all(self):
        for d in self.dirs:
            rmtree(d)

        self.dirs = set()

dirs = TempDirs()