import os
import re
import mimetypes
import functools

import zmq

from logbook import Logger

from onitu.escalator.client import Escalator, EscalatorClosed
from onitu.utils import get_events_uri

from .cmd import UP, DEL, MOV, CONFIG


class Referee(object):

    def __init__(self, escalator_uri, session):
        super(Referee, self).__init__()

        self.logger = Logger("Referee")
        self.context = zmq.Context.instance()
        self.escalator = Escalator(escalator_uri, session)
        self.get_events_uri = functools.partial(
            get_events_uri, session, self.escalator)

        self.update_config()

        self.handlers = {
            CONFIG: self._handle_config,
            UP: self._handle_update,
            DEL: self._handle_deletion,
            MOV: self._handle_move,
        }

    def listen(self):
        """Listen to all the events, and handle them
        """

        self.logger.info("started")

        try:
            listener = self.context.socket(zmq.PULL)
            listener.bind(self.get_events_uri('referee'))

            while True:
                events = self.escalator.range(prefix='referee:event:')

                for key, args in events:
                    cmd = args[0]
                    if cmd in self.handlers:
                        fid = key.decode().split(':')[-1]
                        self.handlers[cmd](fid, *args[1:])
                    self.escalator.delete(key)

                listener.recv()

        except zmq.ZMQError as e:
            if e.errno != zmq.ETERM:
                raise
        except EscalatorClosed:
            pass
        finally:
            listener.close()

    def close(self):
        self.escalator.close()
        self.context.term()

    # HELPERS

    def dir_common_root(self, dirs):

        common = []

        for components in zip(*(d.split(os.path.sep) for d in dirs)):
            if any(c != components[0] for c in components):
                break
            common.append(components[0])

        return os.path.join(*common)

    def compute_folders(self, folders):
        """
        Returns a list of affected folders for actions on a fid.

        folders is a dictionary mapping folders to paths, this functions
        takes at least one such mapping as a starting point.
        """

        bridged = folders
        folders = {}

        for folder, fpath in bridged.items():
            folders[folder] = fpath

            for service in self.services:

                # If this service acts like a bridge between the current
                # folder and another one we compute the path in the new
                # folders and add it to the list of list of bridged folders.

                currentmount = service['folders'][folder]['mount']
                spath = os.path.normpath(currentmount + os.path.sep + fpath)

                for otherfolder in service['folders']:
                    if otherfolder == folder:
                        continue

                    # check if spath is in other folder.
                    # if so, this is a bridge.

                    # We might need to consider other constraints (size, filetype)



        metadata = self.escalator.get('file:{}'.format(fid))

        expandto = set(metadata['folders'].keys())
        affected = set()

        while expandto:


            expanded = False

            for service in affected:




        pass

        # Ok this is gonna be hackish.
        # The new format has folders, onitu doesn't. (yet)
        #
        # What should be done:
        #     - plugs should add 'folder' to metadata based on
        #       their service/folder configuration.
        #     - rules should be applied on a per folder basis.
        #     - forward 'fid' to new owners, they'll now where
        #       to put it based on 'folder' + other metadata.
        #
        # How we could emulate this behaviour:
        #     - plugs don't know about folders, they send the
        #       filename.
        #     - look at 'path' option in all service/folder
        #       options and match it with filename, use this
        #       as the folder.
        #     - apply rules based on the folder
        #     - for all owners, check their 'path' for the folder
        #       raise an error if it isn't the same. (don't handle
        #       folders mounted at different paths yet)
        #
        #     In addition to this, the referee *will* add 'folder' to the
        #     metadata and a 'folder_filepath' which should be used
        #     by drivers suporting the folder mechanism. Of course if a
        #     driver sends metadata with 'folder' and 'folder_filepath'
        #     that will be used instead of the above hack.
        #     'folder_filepath' is like 'path' but relative to the folder.
        #


    def update_config(self):
        self.services = self.escalator.get('services')
        self.folders = self.escalator.get('folders')

    def notify(self, services, cmd, fid, *args):
        if not services:
            return

        publisher = self.context.socket(zmq.PUSH)
        publisher.linger = 1000

        for name in services:
            self.escalator.put('entry:{}:event:{}'.format(name, fid),
                               (cmd, args))
            publisher.connect(self.get_events_uri(name))

        try:
            publisher.send(b'')
        except zmq.ZMQError as e:
            publisher.close(linger=0)
            if e.errno != zmq.ETERM:
                raise
        else:
            publisher.close()


    # HANDLERS

    def _handle_config(self):
        self.update_config()

        # TODO:
        #  - Add a command/handler for forced update
        #    in which case we should recompute everything.


    def _handle_update(self, fid, service):
        pass

    def _handle_deletion(self, fid, service):
        pass

    def _handle_move(self, old_fid, service, new_fid):
        pass
