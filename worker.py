#!/usr/bin/env python

from twisted.python import log
from twisted.internet import reactor
import sys, socket, ConfigParser

import common, worker

# process arguments
room_list = sys.argv[1:]

worker_config = ConfigParser.ConfigParser()
worker_config.read( 'config.ini' )

wc_args = { 'user': 'worker', 
           'resource': worker_config.get( 'worker', 'resource' ), 
           'password': 'password', 
           'server': worker_config.get( 'worker', 'server_ip' ), 
           'port': worker_config.get( 'worker', 'server_port' ), 
           'trigger_config': ( worker_config.has_option( 'worker' , 'trigger_config' ) and worker_config.get( 'worker', 'trigger_config' ) ) or False,
           'room_list': room_list,
           }

log.startLogging( sys.stdout )
wclient = worker.WorkerClient( **wc_args )
reactor.run()