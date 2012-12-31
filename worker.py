#!/usr/bin/env python

from twisted.python import log
from twisted.internet import reactor
import sys

import worker

log.startLogging( sys.stdout )
wclient = worker.WorkerClient()
reactor.run()