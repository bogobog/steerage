from twisted.words.xish import domish, xpath
from twisted.words.protocols.jabber import xmlstream, jid
from twisted.python import log
from twisted.internet import threads, defer, reactor
from wokkel.subprotocols import XMPPHandler
from datetime import datetime
from lxml import etree
from functools import wraps
import pyinotify
import time, os, subprocess, ConfigParser

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
            
        scheduled   = config_triggers[ 'scheduled' ]
        timed       = config_triggers[ 'timed' ]
        event       = config_triggers[ 'event' ]
        xpath       = config_triggers[ 'xpath' ]
        fs          = config_triggers[ 'filesystem' ]
        
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
                trigger.run()
        
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
        
def MessageAction( trigger ):
    target_entity = jid.JID( trigger.config['action_recipient'] )
    message_type = trigger.config['action_message_type']
    
    if message_type == "groupchat":
        muc_client = trigger.parent.my_parent.muc_client
        
        if not muc_client._getRoom( target_entity ):
            log.msg( 'not in room' )
            return False
        
    content = ParseActionContent( trigger.config )
    
    def getContentResponse( response ):
        log.msg( 'getContentResponse' )
        msg = domish.Element( (None, 'message') )
        msg['type'] = message_type
        msg['to'] = target_entity.full()
            
        msg.addElement('body', None, response )
        trigger.parent.xmlstream.send( msg )
            
    content.getContent().addCallback( getContentResponse )
    
def FunctionAction( trigger ):
    target_function = trigger.action['function']
    
    if 'args' in trigger.action:
        target_function( trigger, *trigger.action['args'] )
    else:
        target_function( trigger )

    
def ParseTriggerContent( config ):

    if not 'content_type' in config:
        return False
    
    ttype = config['content_type']
        
    if ttype == 'text':
        return TextTriggerContent( config['content_value'] )
    elif ttype == 'file':
        return FileTriggerContent( config['content_value'] )
    elif ttype == 'external':
        args = [ config['content_value'], ]
        if 'content_timeout' in config:
            args.append( int( config['content_timeout'] ) )
            return ExternalTriggerContent( *args )
        
    return False
            
def ParseActionContent( config ):

    if not 'action_content_type' in config:
        return False
    
    ttype = config['action_content_type']
        
    if ttype == 'text':
        return TextTriggerContent( config['action_content_value'] )
    elif ttype == 'file':
        return FileTriggerContent( config['action_content_value'] )
    elif ttype == 'external':
        args = [ config['action_content_value'], ]
        
        if 'action_content_timeout' in config:
            args.append( int( config['action_content_timeout'] ) )
            
        return ExternalTriggerContent( *args )
        
    return False
    
def ParseEvent( config ):
    type = config['event_type']
    
    if not type in EventType.event_types:
        return False
    
    event_class = eval( '%sEventType' % type.capitalize() )
    
    return event_class( config )
    
class Trigger( object ):
    action_types = { 'message': MessageAction }
    ran = False
    check_running = False
    
    def __init__(self, parent, name, config):

        self.parent = parent
        self.name = name
        self.config = config
        
        self.repeat = self.config.get( 'repeat', False )
        
        self.allowed_role = self.config.get( 'allowed_role', 'any' )
        
        if self.allowed_role not in [ 'any', 'user', 'admin' ]:
            self.allowed_role = 'any'
    
        if not self.config.get( 'action_type', '' ) in self.action_types:
            raise TriggerException( 'invalid trigger type' )
        
        self.action = self.action_types[ self.config['action_type'] ]
        
    def check(self):
        raise NotImplementedError
    
    def run(self):
        raise NotImplementedError
        
class ScheduledTrigger( Trigger ):
    
    def __init__(self, parent, name, config):
        Trigger.__init__(self, parent, name, config)
        
        if not 'schedule' in config:
            raise TriggerException( 'not schedule found' )
        
        try:
            self.min, self.hour, self.day, self.month, self.year = config['schedule'].split(' ')
        except:
            raise TriggerException( 'invalid schedule' )
    
    def check(self):
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
        self.ran = True
        return self.action( self )
                                    
class TimedTrigger( Trigger ):
    
    def __init__(self, parent, name, config):
        Trigger.__init__(self, parent, name, config)
        
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
        return self.action( self )
    
class EventTrigger( Trigger ):
    event_types = [ 'message', 'presence', 'iq' ]
    
    def __init__(self, parent, name, config):
        Trigger.__init__(self, parent, name, config)
        
        self.event = ParseEvent( config )

    def check(self, element):
        if self.ran and not self.repeat:
            return defer.succeed( False )
        
        def matchElementResponse( response ):
            log.msg( 'matchElementResponse' )
            if not response:
                return False
            
            return True
        
        return self.event.matchElement( element ).addCallback( matchElementResponse )
    
    def run(self):
        self.ran = True
        return self.action( self )
    
class XpathTrigger( Trigger ):
    action_types = { 'message': MessageAction, 'function': FunctionAction }
    
    def __init__(self, parent, name, config):
        Trigger.__init__(self, parent, name, config)
        
        self.xpath = unicode( config['xpath'] )
        self.xquery = etree.ETXPath( config['xpath'] )

        self.content = False
        
        if 'content' in config:
            self.content = ParseTriggerContent( config )
            
    def check(self, element):
        if self.ran and not self.repeat:
            return defer.succeed( False )
        
        if not self.xquery( etree.XML( element.toXml() ) ):
            return defer.succeed( False )       
        
        """
        def getContentResponse( response ):
            log.msg( 'getContentResponse' )
            if response == str( element.body ):
                return True
            
            return False
        
        if self.content:
            return self.content.getContent().addCallback( getContentResponse )
        """
        
        return defer.succeed( True ) 
 
    def run(self):
        self.ran = True
        return self.action( self )
                                               
class FilesystemTrigger( Trigger ):
    filesystem_event_types = { 'create': pyinotify.IN_CREATE, 'delete': pyinotify.IN_DELETE, 'modify': pyinotify.IN_MODIFY, 'attrib': pyinotify.IN_ATTRIB }
    
    def __init__(self, parent, name, config):
        Trigger.__init__(self, parent, name, config)
        
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
        return self.action( self )
                                               
class TriggerContent( object ):

    def __init__(self, value):
        self.value = value
        
    def getContent(self):
        pass
    
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
    
class EventType( object ):
    event_types = [ 'message', 'xpath' ]
    
    def __init__(self, config):
        self.type = config['event_type']
        
        if not self.type in self.event_types:
            raise TriggerException( 'invalid event type' )
        
    def matchElement(self, element):
        raise NotImplementedError
        
class MessageEventType( EventType ):
    
    def __init__(self, config):
        EventType.__init__(self, config)
        
        self.source_entity = config['event_source']
        self.content = False
        
        if 'content_type' in config:
            self.content = ParseTriggerContent(config)
        
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
        
        if self.content:
            return self.content.getContent().addCallback( getContentResponse ) 
        
        return defer.succeed( True )
