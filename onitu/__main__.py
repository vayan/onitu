"""
This module starts Onitu. It does the following:

- parse the command line options
- configure the logger
- parse the setup
- clean the database
- launch the different elements using the Circus library
"""

import sys
import argparse

import circus

from itertools import chain

from logbook import Logger, INFO, DEBUG, NullHandler, NestedSetup
from logbook.queues import ZeroMQHandler, ZeroMQSubscriber
from logbook.more import ColorizedStderrHandler
from tornado import gen


from .escalator.client import Escalator
from .utils import get_logs_uri, IS_WINDOWS, get_stats_endpoint
from .utils import get_circusctl_endpoint, get_pubsub_endpoint, u

# Time given to each process (Drivers, Referee, API...) to
# exit before being killed. This avoid any hang during
# shutdown
GRACEFUL_TIMEOUT = 1.

session = None
setup = None
logger = None
arbiter = None
majordomo_req_uri = None
majordomo_rep_uri = None
majordomo_keys_dir = None
majordomo_server_key = None


@gen.coroutine
def start_setup(*args, **kwargs):
    """Parse the setup JSON file, clean the database,
    and start the :class:`.Referee` and the drivers.
    """
    escalator = Escalator(session, create_db=True)

    with escalator.write_batch() as batch:
        # TODO: handle folders from previous run
        for name, options in setup.get('folders', {}).items():
            batch.put(u'folder:{}'.format(name), options)

    services = setup.get('services', {})
    escalator.put('services', list(services.keys()))

    yield start_watcher("Referee", 'onitu.referee')

    for service, conf in services.items():
        yield load_service(escalator, service, conf)

    logger.debug("Services loaded")

    yield start_watcher("Rest API", 'onitu.api')

    majordomo = arbiter.add_watcher(
        "Majordomo",
        sys.executable,
        args=('-m', 'onitu.majordomo', session,
              majordomo_req_uri, majordomo_rep_uri,
              majordomo_keys_dir, majordomo_server_key),
        copy_env=True,
        graceful_timeout=GRACEFUL_TIMEOUT
    )

    yield majordomo.start()


@gen.coroutine
def load_service(escalator, service, conf):
    logger.debug("Loading service {}", service)

    if ':' in service:
        logger.error("Illegal character ':' in service {}", service)
        return

    if 'driver' not in conf:
        logger.error("Service {} does not specify a driver.", service)
        return

    escalator.put(u'service:{}:driver'.format(service), conf['driver'])
    escalator.put(u'service:{}:root'.format(service), conf.get('root', ''))

    if 'options' in conf:
        escalator.put(
            u'service:{}:options'.format(service), conf['options']
        )

    folders = conf.get('folders', {})
    escalator.put(u'service:{}:folders'.format(service), list(folders.keys()))

    for name, options in folders.items():
        if not escalator.exists(u'folder:{}'.format(name)):
            logger.warning(
                'Unknown folder {} in service {}', name, service
            )
            continue

        if type(options) != dict:
            path = options
            options = {}
        else:
            path = options.pop('path', '/')

        escalator.put(
            u'service:{}:folder:{}:path'.format(service, name), path
        )
        escalator.put(
            u'service:{}:folder:{}:options'.format(service, name), options
        )

    yield start_watcher(service, 'onitu.service', conf['driver'], service)


@gen.coroutine
def start_watcher(name, module, *args, **kwargs):
    watcher = arbiter.add_watcher(
        name,
        sys.executable,
        args=list(chain(['-m', module, session], args)),
        copy_env=True,
        graceful_timeout=GRACEFUL_TIMEOUT,
        **kwargs
    )
    yield watcher.start()


def get_logs_dispatcher(uri, debug=False):
    """Configure the dispatcher that will print the logs received
    on the ZeroMQ channel.
    """
    handlers = []

    if not debug:
        handlers.append(NullHandler(level=DEBUG))

    handlers.append(ColorizedStderrHandler(level=INFO))

    subscriber = ZeroMQSubscriber(uri, multi=True)
    return subscriber.dispatch_in_background(setup=NestedSetup(handlers))


def get_setup(setup_file):
    if setup_file.endswith('.yml') or setup_file.endswith('.yaml'):
        try:
            import yaml
        except ImportError:
            logger.error(
                "You provided a YAML setup file, but PyYAML was not found on "
                "your system."
            )
        loader = lambda f: yaml.load(f.read())
    elif setup_file.endswith('.json'):
        import json
        loader = json.load
    else:
        logger.error(
            "The setup file must be either in JSON or YAML."
        )
        return

    try:
        with open(setup_file) as f:
            return loader(f)
    except Exception as e:
        logger.error(
            "Error parsing '{}' : {}", setup_file, e
        )


def main():
    global session, setup, logger, arbiter
    global majordomo_req_uri, majordomo_rep_uri
    global majordomo_keys_dir, majordomo_server_key

    logger = Logger("Onitu")

    parser = argparse.ArgumentParser("onitu")
    parser.add_argument(
        '--setup', default='setup.yml', type=u,
        help="A YAML or JSON file with Onitu's configuration "
             "(defaults to setup.yml)"
    )
    parser.add_argument(
        '--no-dispatcher', action='store_true',
        help="Use this flag to disable the log dispatcher"
    )
    parser.add_argument(
        '--majordomo_req_uri',
        help="The ZMQ REQ socket where clients should connect",
        default='tcp://*:20001'
    )
    parser.add_argument(
        '--majordomo_rep_uri',
        help="The ZMQ REP socket where clients should connect",
        default='tcp://*:20003'
    )
    parser.add_argument(
        '--majordomo_keys_dir',
        help="Directory where clients' public keys are stored",
        default='authorized_keys'
    )
    parser.add_argument(
        '--majordomo_server_key',
        help="Server's secret key file",
        default='server.key_secret'
    )
    parser.add_argument(
        '--debug', action='store_true', help="Enable debugging logging"
    )
    args = parser.parse_args()

    majordomo_req_uri = args.majordomo_req_uri
    majordomo_rep_uri = args.majordomo_rep_uri
    majordomo_keys_dir = args.majordomo_keys_dir
    majordomo_server_key = args.majordomo_server_key

    setup = get_setup(args.setup)
    if not setup:
        return 1

    session = setup.get('name')

    logs_uri = get_logs_uri(session)
    if not args.no_dispatcher:
        dispatcher = get_logs_dispatcher(debug=args.debug, uri=logs_uri)
    else:
        dispatcher = None

    with ZeroMQHandler(logs_uri, multi=True):
        try:
            arbiter = circus.get_arbiter(
                (
                    {
                        'name': 'Escalator',
                        'cmd': sys.executable,
                        'args': ('-m', 'onitu.escalator.server', session),
                        'copy_env': True,
                        'graceful_timeout': GRACEFUL_TIMEOUT
                    },
                ),
                proc_name="Onitu",
                controller=get_circusctl_endpoint(session),
                pubsub_endpoint=get_pubsub_endpoint(session),
                stats_endpoint=get_stats_endpoint(session),
                loglevel='WARNING',
                statsd=True
            )

            arbiter.start(cb=start_setup)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            if dispatcher and dispatcher.running:
                dispatcher.stop()

            if IS_WINDOWS:
                from .utils import delete_sock_files
                delete_sock_files()


if __name__ == '__main__':
    sys.exit(main())
