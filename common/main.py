import ConfigParser
from twisted.words.protocols.jabber import jid, xmlstream, client, sasl, error
from twisted.internet import reactor
from twisted.words.xish.xmlstream import XmlStreamFactory
from twisted.words.xish import domish
from twisted.python import log
from wokkel import subprotocols
import random, logging

CLIENT_CONFIG_FILE_DEFAULT = 'config.ini'

# lets make the unique ids a bit more random
domish.Element._idCounter = random.randint( 1000, 9999 )

class CommonClientManagerException( Exception ):
    pass

class CommonClientManagerExceptionHandlerNameExists( CommonClientManagerException ):
    pass

class CommonClientManagerExceptionHandlerNameNotFound( CommonClientManagerException ):
    pass

class CommonClientManagerExceptionClientNotDefined( CommonClientManagerException ):
    pass

class CommonClientManagerExceptionInvalidHandlerClass( CommonClientManagerException ):
    pass

class CommonClientFactory( XmlStreamFactory ):
    protocol = xmlstream.XmlStream
    #maxDelay = globals.COMMON_CLIENT_MAX_RECONNECT_INTERVAL_SECS

    def __init__( self, my_parent ):
        self.my_parent = my_parent

        self.authenticator = client.XMPPAuthenticator( self.my_parent.jid, self.my_parent.password )
        super( CommonClientFactory, self ).__init__( self.authenticator )

        self.streamManager = CommonClientStreamManager(self)
        self.addHandler( subprotocols.XMPPHandler() )

    def addHandler(self, handler):
        """
        Add a subprotocol handler to the stream manager.
        """
        self.streamManager.addHandler(handler)

    def removeHandler(self, handler):
        """
        Add a subprotocol handler to the stream manager.
        """
        self.streamManager.removeHandler(handler)

class CommonClientStreamManager( subprotocols.StreamManager ):

    def initializationFailed(self, reason):
        log.msg( 'init failed', level = logging.DEBUG )
        reason.trap( sasl.SASLAuthError )
        if reason.value.condition == 'not-authorized':
            log.msg( 'not authorized', level = logging.DEBUG )
            self.registerUser()
        elif reason.value.condition == 'malformed-request':
            self.factory.authenticator.initializeStream()

    def registerUser( self ):

        def register_submit( iq ):
            log.msg(  'register_submit', level = logging.DEBUG )
            self.factory.authenticator.initializeStream()

        def register_submit_error( reason ):
            log.msg(  'register_submit_error', level = logging.DEBUG )
            reason.trap( error.StanzaError )
            if reason.value.condition == 'conflict':
                log.msg(  'user already registered', level = logging.DEBUG )

        def register_response( iq ):
            log.msg( 'register_response', level = logging.DEBUG )

            iq = xmlstream.IQ( self.xmlstream, 'set' )
            q = iq.addElement( ( 'jabber:iq:register', 'query') )
            q.addElement( 'username', content = self.factory.my_parent.jid.user )
            q.addElement( 'password', content = self.factory.my_parent.password )
            iq.send().addCallback( register_submit ).addErrback( register_submit_error )

        iq = xmlstream.IQ( self.xmlstream, 'get' )
        iq.addElement( ( 'jabber:iq:register', 'query') )
        iq.send().addCallback( register_response )

class CommonClient( object ):

    def __init__( self, config_file = CLIENT_CONFIG_FILE_DEFAULT ):

        self.config = ConfigParser.ConfigParser()
    	self.config.read( config_file )

        self.user = self.config.get( 'general', 'user' )
        self.password = self.config.get( 'general', 'password' )

        self.resource = self.config.get( 'general', 'resource' )
        self.server = self.config.get( 'general', 'server_ip' )
        self.port = int( self.config.get( 'general', 'server_port' ) )

        self.jid = jid.JID( self.user + '@' + self.server + "/" + self.resource )
        self.factory = CommonClientFactory( self )
        self.factory.streamManager.logTraffic = True

        self.custom_handlers = {}

        reactor.connectTCP( self.server, self.port, self.factory )

class CommonClientManager( object ):
    common_client = None

    @classmethod
    def newClient( cls, config_file = CLIENT_CONFIG_FILE_DEFAULT, register_as_global_client = True ):
        new_client = CommonClient( config_file )

        if register_as_global_client:
            cls.common_client = new_client

        return new_client

    @classmethod
    def getMyClient( cls, client ):
        if client != None:
            return client
        elif cls.common_client != None:
            return cls.common_client
        else:
            raise CommonClientManagerExceptionClientNotDefined()

    @classmethod
    def getCommonClient( cls ):
        my_client = cls.getMyClient( None )

        if not my_client:
            raise CommonClientManagerExceptionClientNotDefined()

        return my_client

    @classmethod
    def addHandler( cls, name, klass, client = None ):

        my_client = cls.getMyClient( client )

        if 'name' in my_client.custom_handlers:
            raise CommonClientManagerExceptionHandlerNameExists( name )

        new_handler = klass( my_client )
        new_handler.setHandlerParent( my_client.factory.streamManager )

        my_client.custom_handlers[ name ] = new_handler

    @classmethod
    def removeHandler( cls, name, client = None ):
        my_client = cls.getMyClient( client )

        if not name in my_client.custom_handlers:
            raise CommonClientManagerExceptionHandlerNameNotFound( name )

        del my_client.custom_handlers[ name ]

    @classmethod
    def getHandlers( cls, client = None ):
        my_client = cls.getMyClient( client )
        return my_client.custom_handlers.keys()

    @classmethod
    def getHandler( cls, handler_name, client = None ):
        my_client = cls.getMyClient( client )

        if not handler_name in my_client.custom_handlers:
            return None

        return my_client.custom_handlers[ handler_name ]
