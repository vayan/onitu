import os

from path import path

from onitu.plug import Plug, DriverError, ServiceError
from onitu.escalator.client import EscalatorClosed
from onitu.utils import IS_WINDOWS, u

if IS_WINDOWS:
    import threading

    import win32api
    import win32file
    import win32con
else:
    import pyinotify

TMP_EXT = '.onitu-tmp'

plug = Plug()
root = None


def to_tmp(filename):
    filename = path(filename)
    return filename.parent / ('.' + filename.name + TMP_EXT)


def update(metadata, abs_path, mtime=None):
    try:
        metadata.size = abs_path.size
        metadata.extra['revision'] = mtime if mtime else abs_path.mtime
    except (IOError, OSError) as e:
        raise ServiceError(
            u"Error updating file '{}': {}".format(metadata.path, e)
        )
    else:
        plug.update_file(metadata)


def delete(metadata, _):
    plug.delete_file(metadata)


def move(old_metadata, old_path, new_path):
    new_filename = root.relpathto(new_path)
    new_metadata = plug.move_file(old_metadata, new_filename)
    new_metadata.extra['revision'] = path(root / new_path).mtime
    new_metadata.write()


def check_changes():
    expected_files = set()

    for folder in plug.folders.values():
        expected_files.update(folder.join(f) for f in plug.list(folder).keys())

    for abs_path in root.walkfiles():
        if abs_path.ext == TMP_EXT:
            continue

        filename = abs_path.relpath(root).normpath()

        expected_files.discard(filename)

        metadata = plug.get_metadata(filename)
        revision = metadata.extra.get('revision', 0.)

        try:
            mtime = abs_path.mtime
        except (IOError, OSError) as e:
            raise ServiceError(
                u"Error updating file '{}': {}".format(filename, e)
            )
            mtime = 0.

        if mtime > revision:
            update(metadata, abs_path, mtime)

    for filename in expected_files:
        metadata = plug.get_metadata(filename)
        plug.delete_file(metadata)


@plug.handler()
def get_chunk(metadata, offset, size):
    try:
        with open(metadata.path, 'rb') as f:
            f.seek(offset)
            return f.read(size)
    except (IOError, OSError) as e:
        raise ServiceError(
            u"Error getting file '{}': {}".format(metadata.path, e)
        )


@plug.handler()
def start_upload(metadata):
    tmp_file = to_tmp(metadata.path)

    try:
        if not tmp_file.exists():
            tmp_file.dirname().makedirs_p()

        tmp_file.open('wb').close()

        if IS_WINDOWS:
            win32api.SetFileAttributes(
                tmp_file, win32con.FILE_ATTRIBUTE_HIDDEN)
    except IOError as e:
        raise ServiceError(
            u"Error creating file '{}': {}".format(tmp_file, e)
        )


@plug.handler()
def upload_chunk(metadata, offset, chunk):
    tmp_file = to_tmp(metadata.path)

    try:
        with open(tmp_file, 'r+b') as f:
            f.seek(offset)
            f.write(chunk)
    except (IOError, OSError) as e:
        raise ServiceError(
            u"Error writting file '{}': {}".format(tmp_file, e)
        )


@plug.handler()
def end_upload(metadata):
    tmp_file = to_tmp(metadata.path)

    try:
        if IS_WINDOWS:
            # On Windows we can't move a file
            # if dst exists
            path(metadata.path).unlink_p()
        tmp_file.move(metadata.path)
        mtime = os.path.getmtime(metadata.path)

        if IS_WINDOWS:
            win32api.SetFileAttributes(
                metadata.path, win32con.FILE_ATTRIBUTE_NORMAL)
    except (IOError, OSError) as e:
        raise ServiceError(
            u"Error for file '{}': {}".format(metadata.path, e)
        )

    metadata.extra['revision'] = mtime
    metadata.write()


@plug.handler()
def abort_upload(metadata):
    tmp_file = to_tmp(metadata.path)
    try:
        tmp_file.unlink()
    except (IOError, OSError) as e:
        raise ServiceError(
            u"Error deleting file '{}': {}".format(tmp_file, e)
        )


@plug.handler()
def delete_file(metadata):
    try:
        os.unlink(metadata.path)
    except (IOError, OSError) as e:
        raise ServiceError(
            u"Error deleting file '{}': {}".format(metadata.path, e)
        )


@plug.handler()
def move_file(old_metadata, new_metadata):
    old_path = path(old_metadata.path)
    new_path = path(new_metadata.path)

    parent = new_path.dirname()
    if not parent.exists():
        parent.makedirs_p()

    try:
        old_path.rename(new_path)
    except (IOError, OSError) as e:
        raise ServiceError(
            u"Error moving file '{}': {}".format(old_path, e)
        )


if IS_WINDOWS:
    FILE_LIST_DIRECTORY = 0x0001

    def win32watcherThread(root, file_lock):
        dirHandle = win32file.CreateFile(
            root,
            FILE_LIST_DIRECTORY,
            win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_FLAG_BACKUP_SEMANTICS,
            None
        )

        actions_names = {
            1: 'create',
            2: 'delete',
            3: 'write',
            4: 'delete',
            5: 'write'
        }

        while True:
            results = win32file.ReadDirectoryChangesW(
                dirHandle,
                1024,
                True,
                win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
                win32con.FILE_NOTIFY_CHANGE_DIR_NAME |
                win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES |
                win32con.FILE_NOTIFY_CHANGE_SIZE |
                win32con.FILE_NOTIFY_CHANGE_LAST_WRITE |
                win32con.FILE_NOTIFY_CHANGE_SECURITY,
                None
            )

            for action, file_ in results:
                abs_path = root / file_

                if (abs_path.isdir() or abs_path.ext == TMP_EXT or
                    not (win32api.GetFileAttributes(abs_path)
                         & win32con.FILE_ATTRIBUTE_NORMAL)):
                    continue

                with file_lock:
                    if actions_names.get(action) == 'write':
                        filename = root.relpathto(abs_path)

                        try:
                            metadata = plug.get_metadata(filename)
                            update(metadata, abs_path)
                        except EscalatorClosed:
                            return

    def watch_changes():
        file_lock = threading.Lock()
        notifier = threading.Thread(target=win32watcherThread,
                                    args=(root.abspath(), file_lock))
        notifier.setDaemon(True)
        notifier.start()
else:
    class Watcher(pyinotify.ProcessEvent):
        def process_IN_CLOSE_WRITE(self, event):
            self.process_event(event.pathname, update)

        def process_IN_DELETE(self, event):
            print("DELETION", event.pathname)
            self.process_event(event.pathname, delete)

        def process_IN_MOVED_TO(self, event):
            if event.dir:
                for new in path(event.pathname).walkfiles():
                    old = new.replace(event.pathname, event.src_pathname)
                    self.process_event(old, move, u(new))
            else:
                self.process_event(event.src_pathname, move, u(event.pathname))

        def process_event(self, abs_path, callback, *args):
            abs_path = path(u(abs_path))

            if abs_path.ext == TMP_EXT:
                return

            filename = root.relpathto(abs_path)

            try:
                metadata = plug.get_metadata(filename)
                callback(metadata, abs_path, *args)
            except EscalatorClosed:
                return

    def watch_changes():
        manager = pyinotify.WatchManager()
        notifier = pyinotify.ThreadedNotifier(manager, Watcher())
        notifier.daemon = True
        notifier.start()

        mask = (pyinotify.IN_CREATE | pyinotify.IN_CLOSE_WRITE |
                pyinotify.IN_DELETE | pyinotify.IN_MOVED_TO |
                pyinotify.IN_MOVED_FROM)
        manager.add_watch(root, mask, rec=True, auto_add=True)


def start():
    global root
    root = path(plug.root)

    if not root.access(os.W_OK | os.R_OK):
        raise DriverError(u"The root '{}' is not accessible".format(root))

    watch_changes()
    check_changes()
    plug.listen()
