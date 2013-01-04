from wokkel.subprotocols import XMPPHandler
import ConfigParser, subprocess, os, time
from twisted.python import log
from twisted.internet import threads, defer, reactor
from datetime import datetime
from twisted.words.protocols.jabber import jid
from twisted.words.xish import domish
from lxml import etree
import pyinotify

from config import *
from inotify_handler import INotifyHandler

class TriggerException( Exception ): pass

class TriggerHandler( XMPPHandler ):
    scheduled_triggers = []
    timed_triggers = []
    event_triggers = []
    xpath_triggers = []
    fs_triggers = []
    triggering_events = []
    
    def __init__(self, parent, trigger_config):
        super( TriggerHandler, self ).__init__()
        
        self.my_parent = parent        
        
        config = ConfigParser.ConfigParser()
        config.read( trigger_config )
        
        config_triggers = {}
        for section in config.sections():
            options = dict( config.items( section ) )
            
            if not 'type' in options:
                continue
            
            if not options['type'] in config_triggers:
                config_triggers[ options['type'] ] = {}
                
            config_triggers[ options['type'] ][ section ] = options
            
        scheduled   = config_triggers.get( 'scheduled', [] )
        timed       = config_triggers.get( 'timed', [] )
        event       = config_triggers.get( 'event', [] )
        xpath       = config_triggers.get( 'xpath', [] )
        fs          = config_triggers.get( 'filesystem', [] )
        
        log.msg( fs )
        
        for trigger in scheduled:
            self.scheduled_triggers.append( ScheduledTrigger( self, trigger, scheduled[ trigger ] ) )
        
        for trigger in timed:
            self.timed_triggers.append( TimedTrigger( self, trigger, timed[ trigger ] ) )
        
        for trigger in event:
            self.event_triggers.append( EventTrigger( self, trigger, event[ trigger ] ) )
        
        for trigger in xpath:
            self.xpath_triggers.append( XpathTrigger( self, trigger, xpath[ trigger ] ) )
           
        for trigger in fs:
            self.fs_triggers.append( FilesystemTrigger( self, trigger, fs[ trigger ] ) )
  
        if len( self.scheduled_triggers ):
            reactor.callLater( 60, self.checkScheduled )
            
        if len( self.timed_triggers ):
            reactor.callLater( 60, self.checkTimed )

        if len( self.fs_triggers ):
            self.inotify_handler = INotifyHandler( self.fs_triggers )

    def connectionInitialized(self):
        log.msg( 'trigger_handler: connectionInitialized' )        
        for trigger in self.event_triggers:
            log.msg( 'init checkEvent' )
            log.msg( trigger.event.type )
            
            if trigger.event.type == 'message':
                self.xmlstream.addObserver('/' + trigger.event.type, self.checkEvent, trigger = trigger )
            
        #for trigger in self.xpath_triggers:
        if len( self.xpath_triggers ):
            self.xmlstream.addObserver( '/*', self.checkXpathEvent )
         
    def checkEvent(self, element, trigger):
        if not len( self.event_triggers ):
            return
        
        def checkResponse( response ):
            log.msg( 'checkResponse: %s' % trigger.name )
            trigger.check_running = False
            if response:
                trigger.run( element )
        
        if not trigger.check_running:
            trigger.check_running = True
            trigger.check( element ).addCallback( checkResponse )    
        
    def checkXpathEvent(self, element):
        if not len( self.xpath_triggers ):
            return
        
        def checkResponse( response, trigger ):
            log.msg( 'checkResponse: %s' % trigger.name )
            trigger.check_running = False
            log.msg( response )
            if response:
                trigger.run()
        
        for trigger in self.xpath_triggers:
            if not trigger.check_running:
                trigger.check_running = True
                trigger.check( element ).addCallback( checkResponse, trigger )
        
    def checkScheduled(self):
        
        def checkResponse( response, trigger ):
            log.msg( 'checkResponse' )
            trigger.check_running = False
            if response:
                trigger.run()  
        
        for trigger in self.scheduled_triggers:
            if not trigger.check_running:
                trigger.check_running = True
                trigger.check().addCallback( checkResponse, trigger )
            
        reactor.callLater( 60, self.checkScheduled )
                
    def checkTimed(self):   
                
        def checkResponse( response, trigger ):
            log.msg( 'checkResponse' )
            trigger.check_running = False
            if response:
                trigger.run()  
                
        for trigger in self.timed_triggers:
            if not trigger.check_running:
                trigger.check_running = True
                trigger.check().addCallback( checkResponse, trigger )
            
        reactor.callLater( 60, self.checkTimed )      
    
    def addXpathTrigger(self, trigger):
        if not isinstance( trigger, XpathTrigger ):
            raise TriggerException( 'trigger is not an XpathTrigger' )
        
        trigger.parent = self
        self.xpath_triggers.append( trigger )
        
        return True

class Trigger( object ):
    
    def __init__(self, handler, name, config):

        self.handler = handler
        self.name = name
        self.config = config
        self.ran = False
        self.check_running = False
        
        self.repeat = self.config.get( 'repeat', False )
        
        self.allowed_role = self.config.get( 'allowed_role', 'any' )
        
        if self.allowed_role not in [ 'any', 'user', 'admin' ]:
            self.allowed_role = 'any'
    
        if not self.config.get( 'action_type', '' ) in action_types:
            raise TriggerException( 'invalid trigger type' )
        
        self.action = action_types[ self.config['action_type'] ]( self )
        
    def check(self):
        raise NotImplementedError
    
    def run(self):
        raise NotImplementedError

class ScheduledTrigger( Trigger ):
    
    def __init__(self, handler, name, config):
        log.msg( 'ScheduledTrigger: init' )
        Trigger.__init__(self, handler, name, config)
        
        if not 'schedule' in config:
            raise TriggerException( 'not schedule found' )
        
        try:
            self.min, self.hour, self.day, self.month, self.year = config['schedule'].split(' ')
        except:
            raise TriggerException( 'invalid schedule' )
    
    def check(self):
        log.msg( 'ScheduledTrigger: check' )
        if self.ran and not self.repeat:
            return defer.succeed( False )
 
        time = datetime.now()
        
        year_match, mon_match, day_match, hour_match, min_match = [ True ] * 5  
        
        if self.year and ( self.year != '*' and self.year != time.year ):
            year_match = False
        
        if self.month and ( self.month != '*' and self.month != time.mon ):
            mon_match = False
            
        if self.day and ( self.day != '*' and self.day != time.day ):
            day_match = False
            
        if self.hour and ( self.hour != '*' and self.hour != time.hour ):
            hour_match = False
        
        if self.min and ( self.min != '*' and self.min != time.min ):
            min_match = False
            
        if [ year_match, mon_match, day_match, hour_match, min_match ] == [ True ] * 5:
            return defer.succeed( True )
        
        return defer.succeed( False )
    
    def run(self):
        log.msg( 'ScheduledTrigger: run' )
        self.ran = True
        return self.action.run()

class TimedTrigger( Trigger ):
    
    def __init__(self, hanler, name, config):
        log.msg( 'TimedTrigger: init' )
        Trigger.__init__(self, hanler, name, config)
        
        if not 'delay' in config:
            raise TriggerException( 'not schedule found' )
        
        self.start = time.time()
        self.last_run = self.start
        self.delay = float( config['delay'] )
        
    def check(self):
        log.msg( 'TimedTrigger: check' )
        if self.ran and not self.repeat:
            return defer.succeed( False )
        
        if ( time.time() - self.last_run ) > self.delay:
            return defer.succeed( True )
        
        return defer.succeed( False )
        
    def run(self):
        log.msg( 'TimedTrigger: run' )
        self.ran = True
        self.last_run = time.time()
        return self.action.run()

class EventTrigger( Trigger ):
    event_types = [ 'message', 'presence', 'iq' ]
    
    def __init__(self, handler, name, config):
        log.msg( 'EventTrigger: init' )
        Trigger.__init__(self, handler, name, config)
        
        self.event_type = config['event_type']
        self.event = event_types[ self.event_type ]( config )

    def check(self, element):
        log.msg( 'EventTrigger: check' )
        if self.ran and not self.repeat:
            return defer.succeed( False )
        
        def matchElementResponse( response ):
            log.msg( 'matchElementResponse' )
            if not response:
                return False
            
            return True
        
        return self.event.matchElement( element ).addCallback( matchElementResponse )
    
    def run(self, element):
        log.msg( 'EventTrigger: run' )
        self.ran = True
        return self.action.run()

class XpathTrigger( Trigger ):
    
    def __init__(self, handler, name, config):
        log.msg( 'XpathTrigger: init' )
        Trigger.__init__(self, handler, name, config)
        
        self.xpath = unicode( config['xpath'] )
        self.xquery = etree.ETXPath( config['xpath'] )

    def check(self, element):
        log.msg( 'XpathTrigger: check' )
        if self.ran and not self.repeat:
            return defer.succeed( False )
        
        if not self.xquery( etree.XML( element.toXml() ) ):
            return defer.succeed( False )       
        
        return defer.succeed( True ) 
 
    def run(self):
        log.msg( 'XpathTrigger: run' )
        self.ran = True
        return self.action.run()

class FilesystemTrigger( Trigger ):
    filesystem_event_types = { 'create': pyinotify.IN_CREATE, 'delete': pyinotify.IN_DELETE, 'modify': pyinotify.IN_MODIFY, 'attrib': pyinotify.IN_ATTRIB }
    
    def __init__(self, handler, name, config):
        Trigger.__init__(self, handler, name, config)
        
        self.path = config['path']
        
        event_types = config.get( 'filesystem_event_types', 'create,delete,modify' ).split(',')
        self.event_types = list( FilesystemTrigger.filesystem_event_types[ etype ] for etype in event_types if etype in FilesystemTrigger.filesystem_event_types )
        self.mask = 0
        for et in self.event_types:
            self.mask = self.mask | et
    
    def run(self):
        log.msg( 'FilesystemTrigger: run' )
        self.ran = True
        self.last_run = time.time()
        return self.action.run()
        
trigger_types = { 'scheduled': ScheduledTrigger, 'timed': TimedTrigger, 'event': EventTrigger, 'xpath': XpathTrigger, 'filesystem': FilesystemTrigger, }

class Action( object ):
    
    def __init__(self, trigger):
        self.trigger = trigger
        self.content_type = self.trigger.config['action_content_type']
        
        if not self.content_type in content_types:
            raise TriggerException( 'Invalid content type.' )
        
        self.content_handler = content_types[ self.content_type ]( self.trigger.config['action_content_value'] )
     
    def run(self):
        raise NotImplementedError
    
class MessageAction( Action ):
    
    def __init__(self, trigger):
        super( MessageAction, self ).__init__( trigger )
        
        self.recipient = self.trigger.config['action_recipient']
        self.recipient_jid = jid.JID( self.recipient )
        self.message_type = self.trigger.config['action_message_type']
        
    def run(self):
        log.msg( 'MessageAction: run')
        
        if self.message_type == "groupchat":
            muc_client = self.trigger.handler.my_parent.muc_client
            
            if not muc_client._getRoom( self.recipient_jid ):
                log.msg( 'not in room' )
                return False

        def getContentResponse( response ):
                log.msg( 'MessageAction: getContentResponse' )
                msg = domish.Element( (None, 'message') )
                msg['type'] = self.message_type
                msg['to'] = self.recipient_jid.full()
                    
                msg.addElement('body', None, response )
                self.trigger.handler.xmlstream.send( msg )
                        
        self.content_handler.getContent().addCallback( getContentResponse )     
            
def FunctionAction( Action ):
    
    def __init__(self, trigger):
        super( FunctionAction, self ).__init__( trigger )
        
        self.target_function = self.trigger.config['action_function']
        self.args = self.trigger.config['action_args']
    
    def run(self):
        if len( self.args ):
            self.target_function( self.trigger, *self.args )
        else:
            self.target_function( self.trigger )
        
action_types = { 'message': MessageAction }

class TriggerContent( object ):

    def __init__(self, value):
        self.value = value
        
    def getContent(self):
        """
        source user
        source host
        source resource
        source jid
        self jid
        source argument
        """
        raise NotImplementedError
    
class TextTriggerContent( TriggerContent ):
    
    def getContent(self):
        return defer.succeed( self.value ) 
        
class FileTriggerContent( TriggerContent ):
    
    def getContent(self):
        if not os.path.exists( self.value ) or not os.access( self.value, os.R_OK ):
            return 'file not found'
        
        fd = open( self.value )
        fd_raw = fd.read()
        fd.close()
        
        return defer.succeed( str( fd_raw ) )
    
class ExternalTriggerContent( TriggerContent ):
    
    def __init__(self, value, timeout = 300 ):
        TriggerContent.__init__(self, value)
        
        self.exec_path = value
        self.timeout = timeout
        
    def getContent(self):
        if not os.path.exists( self.exec_path ) or not os.access( self.exec_path, os.X_OK ):
            return defer.succeed( 'command not accessible' )
        
        proc = subprocess.Popen( [ '/bin/sh', '-c', os.path.abspath( self.exec_path ), ], stdout = subprocess.PIPE, stderr = subprocess.PIPE )

        def getExternalContentCallback( response ):
            log.msg( 'getExternalContentCallback' )
            if response:
                log.err( 'External process returned abnormally' )
                log.err( proc.stderr.read() )
            
            return str( proc.stdout.read() )
        
        return threads.deferToThread( proc.wait ).addCallback( getExternalContentCallback ).addErrback( log.err )    

content_types = { 'text': TextTriggerContent, 'file': FileTriggerContent, 'external': ExternalTriggerContent, }

class EventType( object ):
    
    def __init__(self, config):
        self.type = config['event_type']
        self.value = config['content_value']
        
        if not self.type in event_types:
            raise TriggerException( 'invalid event type' )
        
    def matchElement(self, element):
        raise NotImplementedError
        
class MessageEventType( EventType ):
    
    def __init__(self, config):
        super( MessageEventType, self ).__init__( config )
        
        self.source_entity = config['event_source']
        self.content_type = False
        self.content_handler = False
        
        if 'content_type' in config:
            self.content_type = config['content_type']
            
            if not self.content_type in content_types:
                raise TriggerException( 'Invalid content type.' )
            
            self.content_handler = content_types[ self.content_type ]( self.value )
        
    def matchElement(self, element):
        log.msg( 'matchElement' )
        log.msg( 'name: %s' % element.name )
        log.msg( 'type: %s' % self.type )
        if element.name != self.type:
            return defer.succeed( False )
        
        log.msg( 'from: %s' % element['from'] )
        log.msg( 'source: %s' % self.source_entity )
        
        if self.source_entity[0] == '@':
            from_jid = jid.JID( element['from'] )
            source_role = self.source_entity[1:]
            
            if source_role in worker_roles and from_jid.user in worker_user_roles and worker_user_roles[ from_jid.user ] in worker_roles:
                source_role_id = worker_roles_by_id[ source_role ]
                from_role_id = worker_user_roles[ from_jid.user ]
                
                if not from_role_id >= source_role_id:
                    return defer.succeed( False )   
            else:
                return defer.succeed( False )
                         
        elif not element['from'] == self.source_entity:             
            return defer.succeed( False )
        
        def getContentResponse( response ):
            log.msg( 'getContentResponse' )
            log.msg( 'response: %s' % response )
            log.msg( 'body: %s' % element.body )
            if response == str( element.body ):
                log.msg( 'matched' )
                return True
            
            return False
    
        if self.content_handler:
            return self.content_handler.getContent().addCallback( getContentResponse ) 
        
        return defer.succeed( True )
    
event_types = { 'message': MessageEventType, }