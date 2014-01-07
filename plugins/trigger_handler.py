import ConfigParser, subprocess, os, time
from twisted.python import log
from twisted.internet import threads, defer, reactor
from wokkel.subprotocols import XMPPHandler
from datetime import datetime
from twisted.words.protocols.jabber import jid
from twisted.words.xish import domish
from lxml import etree
import pyinotify, logging, re

from plugins.inotify_handler import INotifyHandler
from common import CommonClientManager

TRIGGER_CONFIG_FILE_DEFAULT = 'triggers.ini'

class TriggerException( Exception ):
    pass

class TriggerHandler( XMPPHandler ):
    scheduled_triggers = []
    timed_triggers = []
    event_triggers = []
    xpath_triggers = []
    fs_triggers = []
    triggering_events = []

    def __init__(self, client, trigger_config = TRIGGER_CONFIG_FILE_DEFAULT ):
        super( TriggerHandler, self ).__init__()

        self.my_client = client

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
        my_fs          = config_triggers.get( 'filesystem', [] )

        log.msg( my_fs, level = logging.DEBUG )

        for trigger in scheduled:
            self.scheduled_triggers.append( ScheduledTrigger( self, trigger, scheduled[ trigger ] ) )

        for trigger in timed:
            self.timed_triggers.append( TimedTrigger( self, trigger, timed[ trigger ] ) )

        for trigger in event:
            self.event_triggers.append( EventTrigger( self, trigger, event[ trigger ] ) )

        for trigger in xpath:
            self.xpath_triggers.append( XpathTrigger( self, trigger, xpath[ trigger ] ) )

        for trigger in my_fs:
            self.fs_triggers.append( FilesystemTrigger( self, trigger, my_fs[ trigger ] ) )

        if len( self.scheduled_triggers ):
            reactor.callLater( 60, self.checkScheduled )

        if len( self.timed_triggers ):
            reactor.callLater( 60, self.checkTimed )

        if len( self.fs_triggers ):
            self.inotify_handler = INotifyHandler( self.fs_triggers )

    def connectionInitialized(self):
        log.msg( 'trigger_handler: connectionInitialized', level = logging.DEBUG )

        utilized_event_types = []
        for trigger in self.event_triggers:
            log.msg( 'init checkEvent %s' % trigger.name, level = logging.DEBUG )
            log.msg( trigger.event.type, level = logging.DEBUG )

            if not trigger.event.type in utilized_event_types and trigger.event_type in EVENT_TYPES:
                utilized_event_types.append( trigger.event_type )

        if len( utilized_event_types ):
            for event_type in utilized_event_types:
                self.xmlstream.addObserver('/' + event_type, self.checkEvent, event_type = event_type )

        if len( self.xpath_triggers ):
            self.xmlstream.addObserver( '/*', self.checkXpathEvent )

    def checkEvent( self, element, event_type ):
        if not len( self.event_triggers ):
            return

        def checkResponse( response ):
            log.msg( 'checkResponse: %s' % trigger.name, level = logging.DEBUG )
            trigger.check_running = False
            if response:
                trigger.run( element, response )

        for trigger in self.event_triggers:
            if trigger.event_type == event_type and not trigger.check_running:
                trigger.check_running = True
                trigger.check( element ).addCallback( checkResponse )

    def checkXpathEvent(self, element):
        if not len( self.xpath_triggers ):
            return

        def checkResponse( response, trigger ):
            log.msg( 'checkResponse: %s' % trigger.name, level = logging.DEBUG )
            trigger.check_running = False
            log.msg( response, level = logging.DEBUG )
            if response:
                trigger.run( element )

        for trigger in self.xpath_triggers:
            if not trigger.check_running:
                trigger.check_running = True
                trigger.check( element ).addCallback( checkResponse, trigger )

    def checkScheduled(self):

        def checkResponse( response, trigger ):
            log.msg( 'checkResponse', level = logging.DEBUG )
            trigger.check_running = False
            if response:
                trigger.run( None )

        for trigger in self.scheduled_triggers:
            if not trigger.check_running:
                trigger.check_running = True
                trigger.check( None ).addCallback( checkResponse, trigger )

        reactor.callLater( 60, self.checkScheduled )

    def checkTimed(self):

        def checkResponse( response, trigger ):
            log.msg( 'checkResponse', level = logging.DEBUG )
            trigger.check_running = False
            if response:
                trigger.run( None )

        for trigger in self.timed_triggers:
            if not trigger.check_running:
                trigger.check_running = True
                trigger.check( None ).addCallback( checkResponse, trigger )

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

        if not self.config.get( 'action_type', '' ) in ACTION_TYPES:
            raise TriggerException( 'invalid trigger type' )

        self.action = ACTION_TYPES[ self.config['action_type'] ]( self )

    def check( self, element ):
        raise NotImplementedError

    def run( self, element ):
        raise NotImplementedError

class ScheduledTrigger( Trigger ):

    def __init__(self, handler, name, config):
        log.msg( 'ScheduledTrigger: init', level = logging.DEBUG )
        Trigger.__init__(self, handler, name, config)

        if not 'schedule' in config:
            raise TriggerException( 'not schedule found' )

        try:
            self.min, self.hour, self.day, self.month, self.year = config['schedule'].split(' ')
        except:
            raise TriggerException( 'invalid schedule' )

    def check(self, element):
        log.msg( 'ScheduledTrigger: check', level = logging.DEBUG )
        if self.ran and not self.repeat:
            return defer.succeed( False )

        my_now = datetime.now()

        year_match, mon_match, day_match, hour_match, min_match = [ True ] * 5

        if self.year and ( self.year != '*' and self.year != my_now.year ):
            year_match = False

        if self.month and ( self.month != '*' and self.month != my_now.mon ):
            mon_match = False

        if self.day and ( self.day != '*' and self.day != my_now.day ):
            day_match = False

        if self.hour and ( self.hour != '*' and self.hour != my_now.hour ):
            hour_match = False

        if self.min and ( self.min != '*' and self.min != my_now.min ):
            min_match = False

        if [ year_match, mon_match, day_match, hour_match, min_match ] == [ True ] * 5:
            return defer.succeed( True )

        return defer.succeed( False )

    def run( self, element ):
        log.msg( 'ScheduledTrigger: run', level = logging.DEBUG )
        self.ran = True
        return self.action.run()

class TimedTrigger( Trigger ):

    def __init__(self, hanler, name, config):
        log.msg( 'TimedTrigger: init', level = logging.DEBUG )
        Trigger.__init__(self, hanler, name, config)

        if not 'delay' in config:
            raise TriggerException( 'not schedule found' )

        self.start = time.time()
        self.last_run = self.start
        self.delay = float( config['delay'] )

    def check(self, element):
        log.msg( 'TimedTrigger: check', level = logging.DEBUG )
        if self.ran and not self.repeat:
            return defer.succeed( False )

        if ( time.time() - self.last_run ) > self.delay:
            return defer.succeed( True )

        return defer.succeed( False )

    def run( self, element ):
        log.msg( 'TimedTrigger: run', level = logging.DEBUG )
        self.ran = True
        self.last_run = time.time()
        return self.action.run()

class EventTrigger( Trigger ):

    def __init__(self, handler, name, config):
        log.msg( 'EventTrigger: init', level = logging.DEBUG )
        log.msg( 'EventTrigger name: %s' % name, level = logging.DEBUG )
        Trigger.__init__(self, handler, name, config)

        self.event_type = config['event_type']
        self.event = EVENT_TYPES[ self.event_type ]( config )

    def check(self, element):
        log.msg( 'EventTrigger: check', level = logging.DEBUG )
        if self.ran and not self.repeat:
            return defer.succeed( False )

        def matchElementResponse( response ):
            log.msg( 'matchElementResponse', level = logging.DEBUG )
            if not response:
                return False

            return response

        return self.event.matchElement( element ).addCallback( matchElementResponse )

    def run(self, element, check_response ):
        log.msg( 'EventTrigger: run', level = logging.DEBUG )
        self.ran = True
        return self.action.run( triggering_element = element, check_response = check_response )

class XpathTrigger( Trigger ):

    def __init__(self, handler, name, config):
        log.msg( 'XpathTrigger: init', level = logging.DEBUG )
        Trigger.__init__(self, handler, name, config)

        self.xpath = unicode( config['xpath'] )
        self.xquery = etree.ETXPath( config['xpath'] )

    def check(self, element):
        log.msg( 'XpathTrigger: check', level = logging.DEBUG )
        if self.ran and not self.repeat:
            return defer.succeed( False )

        if not self.xquery( etree.XML( element.toXml() ) ):
            return defer.succeed( False )

        return defer.succeed( True )

    def run(self, element):
        log.msg( 'XpathTrigger: run', level = logging.DEBUG )
        self.ran = True
        return self.action.run()

class FilesystemTrigger( Trigger ):
    filesystem_event_types = { 'create': pyinotify.IN_CREATE, 'delete': pyinotify.IN_DELETE, 'modify': pyinotify.IN_MODIFY, 'attrib': pyinotify.IN_ATTRIB }

    def __init__(self, handler, name, config):
        Trigger.__init__(self, handler, name, config)

        self.path = config['path']
        self.last_run = 0

        #fs_event_types = config.get( 'filesystem_event_types', 'create,delete,modify' ).split(',')
        self.event_types = list( FilesystemTrigger.filesystem_event_types[ etype ] for etype in EVENT_TYPES if etype in FilesystemTrigger.filesystem_event_types )
        self.mask = 0
        for et in self.event_types:
            self.mask = self.mask | et

    def run(self, element):
        log.msg( 'FilesystemTrigger: run', level = logging.DEBUG )
        self.ran = True
        self.last_run = time.time()
        return self.action.run()

TRIGGER_TYPES = { 'scheduled': ScheduledTrigger, 'timed': TimedTrigger, 'event': EventTrigger, 'xpath': XpathTrigger, 'filesystem': FilesystemTrigger, }

class Action( object ):

    def __init__(self, trigger):
        self.trigger = trigger
        self.content_type = self.trigger.config['action_content_type']

        if not self.content_type in CONTENT_TYPES:
            raise TriggerException( 'Invalid content type.' )

        self.content_handler = CONTENT_TYPES[ self.content_type ]( self.trigger.config['action_content_value'] )

    def run(self, *args, **kwargs):
        raise NotImplementedError

class MessageActionExceptionNoTriggeringElement( Exception ):
    pass

class MessageAction( Action ):

    def __init__(self, trigger):
        super( MessageAction, self ).__init__( trigger )

        self.recipient = self.trigger.config['action_recipient']
        self.message_type = self.trigger.config['action_message_type']

    def run(self, *args, **kwargs):
        log.msg( 'MessageAction: run', level = logging.DEBUG )

        if self.recipient == "##event_source##":
            print kwargs.keys()

            if not 'triggering_element' in kwargs:
                raise MessageActionExceptionNoTriggeringElement()

            triggering_element = kwargs[ 'triggering_element' ]
            log.msg( 'Triggering Element: %s' % triggering_element, level = logging.DEBUG )

            my_recipient_jid = jid.JID( triggering_element[ 'from' ] )
        else:
            my_recipient_jid = jid.JID( self.recipient )

        if self.message_type == "groupchat":
            log.msg( 'MessageAction Type: groupchat')
            muc_client = CommonClientManager.getHandler( 'muc', self.trigger.handler.my_client )

            if not muc_client._getRoom( my_recipient_jid ):
                log.msg( 'not in room', level = logging.DEBUG )
                return False

        def getContentResponse( response ):
            log.msg( 'MessageAction: getContentResponse', level = logging.DEBUG )
            msg = domish.Element( (None, 'message') )
            msg['type'] = self.message_type
            msg['to'] = my_recipient_jid.full()

            processed_response = response
            if 'check_response' in kwargs:
                print kwargs['check_response']
                processed_response = response.format( **kwargs[ 'check_response' ].groupdict() )

            log.msg( 'processed_response: %s' % processed_response )
            msg.addElement('body', None, processed_response )
            self.trigger.handler.xmlstream.send( msg )

        self.content_handler.getContent().addCallback( getContentResponse )

ACTION_TYPES = { 'message': MessageAction }

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

        self.exec_path = value.split()
        self.timeout = timeout

        log.msg( 'ExternalTriggerContent self.exec_path %s' % self.exec_path, level = logging.DEBUG )

    def getContent(self):
        if not os.path.exists( self.exec_path[0] ) or not os.access( self.exec_path[0], os.X_OK ):
            return defer.succeed( 'command not accessible' )

        proc = subprocess.Popen( [ '/bin/sh', '-c', ' '.join( self.exec_path ) ], stdout = subprocess.PIPE, stderr = subprocess.PIPE )

        def getExternalContentCallback( response ):
            log.msg( 'getExternalContentCallback', level = logging.DEBUG )
            if response:
                log.err( 'External process returned abnormally' )
                log.err( proc.stderr.read() )

            return str( proc.stdout.read() )

        return threads.deferToThread( proc.wait ).addCallback( getExternalContentCallback ).addErrback( log.err )

CONTENT_TYPES = { 'text': TextTriggerContent, 'file': FileTriggerContent, 'external': ExternalTriggerContent, }

class EventType( object ):

    def __init__(self, config):
        self.type = config['event_type']
        self.value = config['content_value']

        if not self.type in EVENT_TYPES:
            raise TriggerException( 'invalid event type' )

    def matchElement(self, element):
        raise NotImplementedError

class MessageEventType( EventType ):

    def __init__(self, config):
        super( MessageEventType, self ).__init__( config )

        self.source_entity = jid.JID( config['event_source'] )
        self.content_type = False
        self.content_handler = False

        if 'content_type' in config:
            self.content_type = config['content_type']

            if not self.content_type in CONTENT_TYPES:
                raise TriggerException( 'Invalid content type.' )

            self.content_handler = CONTENT_TYPES[ self.content_type ]( self.value )

    def matchElement(self, element):
        log.msg( 'matchElement', level = logging.DEBUG )
        log.msg( 'name: %s' % element.name, level = logging.DEBUG )
        log.msg( 'type: %s' % self.type, level = logging.DEBUG )
        log.msg( 'from: %s' % element['from'], level = logging.DEBUG )
        log.msg( 'source: %s' % self.source_entity, level = logging.DEBUG )

        from_jid = jid.JID( element['from'] )

        if not self.source_entity == from_jid and not self.source_entity == from_jid.userhostJID() and not self.source_entity.full() == from_jid.host:
            return defer.succeed( False )

        def getContentResponse( response ):
            log.msg( 'getContentResponse', level = logging.DEBUG )
            log.msg( 'response: %s' % response, level = logging.DEBUG )
            log.msg( 'body: %s' % element.body, level = logging.DEBUG )
            response_match = re.match( response, str( element.body ) )
            if response_match:
                log.msg( 'matched', level = logging.DEBUG )
                return response_match

            return False

        if self.content_handler:
            return self.content_handler.getContent().addCallback( getContentResponse )

        return defer.succeed( True )

class PresenceEventType( EventType ):

    def __init__(self, config):
        super( PresenceEventType, self ).__init__( config )

        self.source_entity = jid.JID( config['event_source'] )
        self.content_type = False
        self.content_handler = False

        if 'content_type' in config:
            self.content_type = config['content_type']

            if not self.content_type in CONTENT_TYPES:
                raise TriggerException( 'Invalid content type.' )

            self.content_handler = CONTENT_TYPES[ self.content_type ]( self.value )

    def matchElement(self, element):
        log.msg( 'PresenceEventType matchElement', level = logging.DEBUG )
        log.msg( 'name: %s' % element.name, level = logging.DEBUG )
        log.msg( 'type: %s' % self.type, level = logging.DEBUG )
        if element.name != self.type:
            return defer.succeed( False )

        # validate presence message source
        log.msg( 'from: %s' % element['from'], level = logging.DEBUG )
        log.msg( 'source: %s' % self.source_entity, level = logging.DEBUG )

        from_jid = jid.JID( element['from'] )

        if not self.source_entity == from_jid and not self.source_entity == from_jid.userhostJID():
            return defer.succeed( False )

        # validate presece message type
        if 'type' in element.attributes:
            presence_type = element['type']
        else:
            presence_type = 'available'

        def getContentResponse( response ):
            log.msg( 'getContentResponse', level = logging.DEBUG )
            log.msg( 'response: %s' % response, level = logging.DEBUG )
            log.msg( 'type: %s' % presence_type, level = logging.DEBUG )
            response_match = re.match( response, presence_type )
            if response_match:
                log.msg( 'matched', level = logging.DEBUG )
                return response_match

            return False

        if self.content_handler:
            return self.content_handler.getContent().addCallback( getContentResponse )

        return defer.succeed( True )

EVENT_TYPES = { 'message': MessageEventType, 'presence': PresenceEventType }

CommonClientManager.addHandler( 'trigger', TriggerHandler )
