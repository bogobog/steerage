import logging
from twisted.python import log

class LevelFileLogObserver( log.FileLogObserver ):

    def __init__( self, file, level = logging.INFO ):
        log.FileLogObserver.__init__( self, file )

        self.log_level = level

    def emit( self, event_dict ):

        if event_dict['isError']:
            level = logging.ERROR
        elif 'level' in event_dict:
            level = event_dict['level']
        else:
            level = logging.INFO

        if level >= self.log_level:
            event_dict["message"] = ( logging.getLevelName( level ), ) + event_dict["message"]
            log.FileLogObserver.emit( self, event_dict )
