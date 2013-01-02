
import pyinotify
from twisted.python import log
from twisted.internet import reactor

from config import worker_config

class INotifyHandler( object ):
    
    def __init__( self, triggers ):
        self.wm = pyinotify.WatchManager()
        self.event_handler = FilesystemEventHandler()
        self.notifier = pyinotify.Notifier( self.wm, self.event_handler, timeout = 10 )
        self.paths = {}
        self.wds = []
        
        self.check_interval = int( worker_config.get( 'worker', 'filesystem_trigger_check_interval', 10 ) )
        
        for trigger in triggers:
            log.msg( trigger.name )
            path = trigger.path
            
            if not path in self.paths:
                self.paths[ path ] = []
                
            for et in trigger.event_types:
                if not et in self.paths[ path ]:
                    self.paths[ path ].append( et )
                
            self.event_handler.registerTrigger( trigger ) 
            
        for path in self.paths:
            mask = 0
            for et in self.paths[ path ]:
                mask |= et
            
            wd = self.wm.add_watch( path, mask )
            self.wds.append( wd )
            
        reactor.callLater( self.check_interval, self.checkForEvents )
        
    def checkForEvents( self ):
        log.msg( 'checkFileSystem' )
        assert self.notifier._timeout is not None, 'Filesystem notifier must be constructed with a short timeout.'
        self.notifier.process_events()
        while self.notifier.check_events():
            self.notifier.read_events()
            self.notifier.process_events()        
    
        reactor.callLater( self.check_interval, self.checkForEvents )
        
class FilesystemEventHandler( pyinotify.ProcessEvent ):
    
    def my_init( self ):
        log.msg( 'Filesystem my_init' )
        self.my_paths = {}
    
    def process_IN_CREATE( self, event ):
        log.msg( 'Filesystem Event: Create' )
        log.msg( str( event ) )
        
        if not event.path in self.my_paths:
            return
        
        for trigger in self.my_paths[ event.path ]:
            log.msg( 'Testing trigger %s' % str( trigger ) )
            if not trigger.mask & pyinotify.IN_CREATE:
                log.msg( 'Mask does not match' )
                continue
            
            if not trigger.path == event.path:
                log.msg( 'Path does not match' )
                continue
            
            trigger.run()
        
    def process_IN_DELETE( self, event ):
        log.msg( 'Filesystem Event: Delete' )
        log.msg( str( event ) )

        if not event.path in self.my_paths:
            return
        
        for trigger in self.my_paths[ event.path ]:
            log.msg( 'Testing trigger %s' % str( trigger ) )
            if not trigger.mask & pyinotify.IN_DELETE:
                log.msg( 'Mask does not match' )
                continue
            
            if not trigger.path == event.path:
                log.msg( 'Path does not match' )
                continue
            
            trigger.run()
                    
    def process_IN_MODIFY( self, event ):
        log.msg( 'Filesystem Event: Modify' )
        log.msg( str( event ) )

        if not event.path in self.my_paths:
            return
        
        for trigger in self.my_paths[ event.path ]:
            log.msg( 'Testing trigger %s' % str( trigger ) )
            if not trigger.mask & pyinotify.IN_MODIFY:
                log.msg( 'Mask does not match' )
                continue
            
            if not trigger.path == event.path:
                log.msg( 'Path does not match' )
                continue
            
            trigger.run()
                    
    def registerTrigger( self, trigger ):
        log.msg( 'Registering trigger: %s' % trigger.name )
        path = trigger.path
        
        if not path in self.my_paths:
            self.my_paths[ path ] = []
            
        self.my_paths[ path ].append( trigger )
        
    def unregisterTrigger( self, trigger ):
        path = trigger.path
        
        if not path in self.my_paths or not trigger in self.my_paths[ path ]:
            return
        
        del self.my_paths[ path ][ trigger ]