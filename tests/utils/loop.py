from time import time, sleep

from . import env


class TimeoutError(BaseException):
    pass


class EventLoop(object):
    def run(self, timeout=None, step=0.001):
        if timeout is not None:
            timeout *= env.time_unit
            start = time()
        while self.condition():
            if timeout is not None:
                if time() - start >= timeout:
                    self.timeout()
            sleep(step)

    def timeout(self, *args):
        raise TimeoutError(*args)


class BooleanLoop(EventLoop):
    def __init__(self):
        self._running = True

    def condition(self):
        return self._running

    def stop(self):
        self._running = False

    def restart(self):
        self._running = True


class CounterLoop(EventLoop):
    def __init__(self, count):
        self.total = count
        self.count = count

    def condition(self):
        return self.count > 0

    def check(self):
        self.count -= 1

    def timeout(self, *args):
        msg = "CounterLoop : {} on {} done.".format(self.total - self.count,
                                                    self.total)
        super(CounterLoop, self).timeout(msg, *args)
