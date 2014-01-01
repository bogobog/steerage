#!/usr/bin/env python

from twisted.python import log
from twisted.internet import reactor
import sys, logging

import common

level_logger = common.LevelFileLogObserver( sys.stdout, logging.DEBUG )
log.startLoggingWithObserver( level_logger.emit )

client = common.CommonClientManager.newClient()

from plugins import *

reactor.run()
