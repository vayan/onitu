"""
Start the Referee.

Launch it as : `python -m onitu.referee`
"""

import sys

from threading import Thread

from logbook.queues import ZeroMQHandler

from onitu.utils import at_exit, get_logs_uri, u

from .referee import Referee

if __name__ == '__main__':
    session = u(sys.argv[1])

    with ZeroMQHandler(get_logs_uri(session), multi=True).applicationbound():
        referee = Referee(session)

        at_exit(referee.close)

        # We run Referee.listen in another thread in order
        # to be able to interrupt it gently in the end
        thread = Thread(target=referee.start)
        thread.start()

        while thread.is_alive():
            thread.join(100)

        referee.logger.info("Exited")
