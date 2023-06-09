import time

class Dump:
    def __init__(self):
        self.prev_stamp = None
        self.block = None

    def timestamp(self):
        current = time.time()
        if (self.block == None):
            self.block = 0
            self.prev_stamp = current
        stamp = current - self.prev_stamp
        with open("./testing/results.txt", "a") as f:
            f.write(str(self.block)+', '+str(current)+', ' + str(stamp)+'\n')
        self.block += 1
        self.prev_stamp = current