import os
import sys
import argparse
import threading
import datetime
import ast
import signal
import Queue
import socket
import select
import msvcrt

_run = True

def sigint_handler(signal, frame):
    global RTT_Listener
    global _run

    print "Caught SIGINT"
    RTT_Listener.close()
    _run = False
    
def queue_reader(queue):
    global _run
    
    print "Started queue reader"
    
    while _run:
        try:
            event = queue.get(False, 1)
            if event.data != None and len(event.data) > 0:
                print event.data    
        except Exception as e:
            # print e
            pass
        
    print "Stopped queue reader"
    
def queue_writer(queue):
    global _run
    
    print "Started queue writer"
    print "Press 1 to start audio. Press 0 to stop audio"
    
    while _run:
        i = msvcrt.getch()
        if i == "1":
            print "Sending audio start command"
            queue.put("1")
        elif i == "0":
            print "Sending audio stop command"
            queue.put("0")
        elif i == "q":
            RTT_Listener.close()
            _run = False
            
        elif i == "Q":
            RTT_Listener.close()
            _run = False
            
    print "Stopped queue writer"
        
    
signal.signal(signal.SIGINT, sigint_handler)

class RTTError(Exception):
    """Subclass for reporting errors."""
    pass


class RTTEvent(object):
    """A simple object for use when passing data between threads in a queue."""

    EVENT_TYPES = {
    0: 'RTT_EVENT_STARTUP',
    1: 'RTT_EVENT_CONNECTED',
    2: 'RTT_EVENT_RX',
    3: 'RTT_EVENT_IDLE',
    4: 'RTT_EVENT_ERROR'
    }

    EVENT_TYPES_REVERSE = {
    'RTT_EVENT_STARTUP': 0,
    'RTT_EVENT_CONNECTED': 1,
    'RTT_EVENT_RX': 2,
    'RTT_EVENT_IDLE': 3,
    'RTT_EVENT_ERROR': 4
    }

    def __init__(self, event_type):
        """Creates a new object with the given event type."""
        if (isinstance(event_type, str)):
            self.event_type = self.EVENT_TYPES_REVERSE[event_type]
        else:
            self.event_type = event_type
        self.err_str = None
        self.data = None

    def is_type(self, event_type_str):
        """A convenience method for comparing types."""
        return (self.event_type == self.EVENT_TYPES_REVERSE[event_type_str])

class RTTThread(threading.Thread):
    """Creates a simple interface to the telnet socket that is created by
    SEGGER's RTT-enabled J-Link drivers. See
    https://www.segger.com/jlink-rtt.html for more information.

    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 19021
    DEFAULT_READ_LEN = 1024
    DEFAULT_TIMEOUT_S = 0.1

    def __init__(self, rx_queue, tx_queue, host=DEFAULT_HOST, port=DEFAULT_PORT):
        """Creates a new object but does not start the thread."""
        super(RTTThread, self).__init__()
        self.daemon = True

        self.rxQueue = rx_queue
        self.txQueue = tx_queue

        self._host = host
        self._port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._stop = threading.Event()

    def run(self):
        """Interacts with the socket until the semaphore is set."""
        try:
            self._sock.connect((self._host, self._port))

            read_socks = ([self._sock],
                [],
                [self._sock],
                self.DEFAULT_TIMEOUT_S)
            all_socks = ([self._sock],
                [self._sock],
                [self._sock],
                self.DEFAULT_TIMEOUT_S)

            while(not self._stop.is_set()):
                idle = True
                if (self.txQueue.empty()):
                    readable, writable, errored = select.select(*read_socks)
                else:
                    readable, writable, errored = select.select(*all_socks)

                if readable:
                    idle = False
                    r_str = self._sock.recv(self.DEFAULT_READ_LEN)
                    if (r_str):
                        event = RTTEvent('RTT_EVENT_RX')
                        event.data = r_str
                        self.rxQueue.put(event)

                if writable:
                    if (self.txQueue.not_empty):
                        if (0 == self._sock.send(self.txQueue.get())):
                            event = RTTEvent('RTT_EVENT_ERROR')
                            event.err_str = 'Socket connection broken.'
                            self.rxQueue.put(event)
                            self.close()

                if (idle):
                   self.rxQueue.put(RTTEvent('RTT_EVENT_IDLE'))

                if (errored):
                    event = RTTEvent('RTT_EVENT_ERROR')
                    event.err_str = 'Select exception'
                    self.rxQueue.put(event)

        except socket.error as err:
            event = RTTEvent('RTT_EVENT_ERROR')
            event.err_str = err.strerror
            self.rxQueue.put(event)
            self.close()

        self._sock.close()

    def close(self):
        """Sets the semaphore to instruct the thread to close."""
        self._stop.set()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Run RTT socket interaction test')
    parser.add_argument('-s',
        '--serial_number',
        required=True,
        dest='serial_number',
        type=int,
        help='the serial number of the J-Link debugger')

    # args = parser.parse_args()
    
    rxQueue = Queue.Queue()
    txQueue = Queue.Queue()
    
    # Start reader thread
    t = threading.Thread(target=queue_reader, args=(rxQueue,))
    t.start()
    
    # Start writer thread
    t2 = threading.Thread(target=queue_writer, args=(txQueue,))
    t2.start()

    # Open RTT socket. Blocks until SIGINT is caught
    print "Starting socket listen"
    RTT_Listener = RTTThread(rxQueue, txQueue)
    RTT_Listener.start()
    
    t.join()
    t2.join()
    RTT_Listener.join()
	