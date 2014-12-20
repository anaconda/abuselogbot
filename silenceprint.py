from functools import wraps
import sys

def silence_print(f):
    class DummyFile(object):
        def write(self, str):
            pass

    @wraps(f)
    def wrapper(*args, **kwds):
        stdout_backup = sys.stdout
        sys.stdout = DummyFile()
        result = f(*args, **kwds)
        sys.stdout = stdout_backup
        return result
    return wrapper
