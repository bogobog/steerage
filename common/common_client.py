from twisted.words.protocols.jabber import jid, xmlstream, client, sasl, error
from twisted.internet import protocol
from twisted.words.xish.xmlstream import XmlStreamFactory
from twisted.words.xish import domish
from twisted.python import log
from wokkel import xmppim, subprotocols, data_form, muc, disco
import random

from presence_triggered_action import PresenceTriggeredAction
import globals

# lets make the unique ids a bit more random
domish.Element._idCounter = random.randint( 1000, 9999 )

class CommonClientFactory( XmlStreamFactory ):
    protocol = xmlstream.XmlStream
    maxDelay = globals.COMMON_CLIENT_MAX_RECONNECT_INTERVAL_SECS

    def __init__(self, my_parent, password ):
        self.my_parent = my_parent 
        self.password = password
        
        self.authenticator = client.XMPPAuthenticator(self.my_parent.jid, self.password)
        super( CommonClientFactory, self ).__init__( self.authenticator )
        #XmlStreamFactoryMixin.__init__(self, self.authenticator)
       
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
        print 'init failed'
        reason.trap( sasl.SASLAuthError )
        if reason.value.condition == 'not-authorized':
            print 'not authorized'
            self.registerUser()
        elif reason.value.condition == 'malformed-request':
            self.factory.authenticator.initializeStream()
            
    def registerUser( self ):
        
        def register_submit( iq ):
            print 'register_submit'
            self.factory.authenticator.initializeStream()
            
        def register_submit_error( reason ):
            print 'register_submit_error'
            reason.trap( error.StanzaError )
            if reason.value.condition == 'conflict':
                print 'user already registered'
            
        def register_response( iq ):
            print 'register_response'
            
            iq = xmlstream.IQ( self.xmlstream, 'set' )
            q = iq.addElement( ( 'jabber:iq:register', 'query') )
            q.addElement( 'username', content = self.factory.my_parent.jid.user )
            q.addElement( 'password', content = self.factory.password )
            iq.send().addCallback( register_submit ).addErrback( register_submit_error )
            
        iq = xmlstream.IQ( self.xmlstream, 'get' )
        iq.addElement( ( 'jabber:iq:register', 'query') )
        iq.send().addCallback( register_response )
        
class CommonMessageProtocol( xmppim.MessageProtocol ):

    def __init__(self, my_parent):
        xmppim.MessageProtocol.__init__( self )
        
        self.my_parent = my_parent
        
    def sendMessage(self, recipient, message):
        
        msg = domish.Element( (None, 'message') )
        msg['type'] = 'normal'
        msg['to'] = recipient.userhost()
        msg['from'] = self.my_parent.jid.full()
        
        msg.addElement('body', None, message)
        self.send( msg )
        #self.addElement('subject', None, subject)
        
class CommonPresenceProtocol( xmppim.PresenceClientProtocol ):
    received_statuses = {}
    presence_triggers = {}
    
    def __init__(self, my_parent):
        xmppim.PresenceClientProtocol.__init__( self )
        
        self.my_parent = my_parent
        
    def subscribedReceived(self, entity):
        print 'subscribedReceived'
        
    def subscribeReceived(self, subscriber):
        
        def rosterAddResponse( response ):
            print 'rosterAddResponse'
            
            self.subscribed( subscriber )
            
            # subscribe to subscriber
            user_status = self.my_parent.rtr_client.getUserStatus( subscriber )
            if not user_status or ( not user_status == 'both' and not user_status == 'to' ):
                self.my_parent.rtr_client.addItem( subscriber.userhostJID() ).addCallback( addSubscriberToRosterResponse ).addErrback( log.err )

        def addSubscriberToRosterResponse( response ):
            print 'addSubscriberToRosterResponse'
            
            if response.attributes['type'] == 'result':
                self.my_parent.pre_client.subscribe( subscriber.userhostJID() )
            
        self.my_parent.rtr_client.addItem( subscriber ).addCallback( rosterAddResponse )
        
    def availableReceived(self, entity, show=None, statuses=None, priority=0):
        print 'availableReceived'
        
        # ignore if self
        if entity.full() == self.my_parent.jid.full():
            return
        
        self.received_statuses[ entity.full() ] = 'available'
        
        if entity.full() in self.presence_triggers and self.presence_triggers[ entity.full() ].status == 'available':
            self.presence_triggers[ entity.full() ].action()
        
    def addPresenceTrigger(self, entity, status, action ):
        self.presence_triggers[ entity.full() ] = PresenceTriggeredAction( entity, status, action )
        print self.presence_triggers
        
class CommonRosterProtocol( xmppim.RosterClientProtocol ):
    my_roster = {}
    
    def __init__(self, my_parent):
        xmppim.RosterClientProtocol.__init__( self )
        
        self.my_parent = my_parent
    
    def onRosterSet(self, item):
        print 'roster set received'
        
        self.my_roster[ item.jid.full() ] = item
        print self.my_roster

    def connectionInitialized(self):
        xmppim.RosterClientProtocol.connectionInitialized(self)
                    
        self.getRoster().addCallback( self.getRosterResponse )
        
    def getRosterResponse(self, roster):
        print 'roster received'
        
        self.my_roster = roster
        
    def addItem(self, entity):
        iq = xmlstream.IQ( self.xmlstream, 'set' )
        iq.addElement( ( xmppim.NS_ROSTER, 'query' ) )
        item = iq.query.addElement( 'item' )
        item['jid'] = entity.full()
        return iq.send()

    def _onRosterSet(self, iq):
        if iq.handled or iq.hasAttribute('from') and iq['from'] != self.my_parent.jid.full():
            return

        iq.handled = True

        itemElement = iq.query.item

        if unicode(itemElement['subscription']) == 'remove':
            self.onRosterRemove(jid.JID(itemElement['jid']))
        else:
            item = self._parseRosterItem(iq.query.item)
            self.onRosterSet(item)

    def getUserStatus(self, jid):
        if jid.userhost() in self.my_roster:
            ritem = self.my_roster[jid.userhost()]
            if ritem.subscriptionTo and ritem.subscriptionFrom:
                return 'both'
            elif ritem.subscriptionTo:
                return 'to'
            elif ritem.subscriptionFrom:
                return 'from'
            else:
                return 'none'
        else:
            return None
        
class CommonDiscoProtocol( disco.DiscoClientProtocol ):
    pass
        
class CommonMucProtocol( muc.MUCClient ):
    history_options = muc.HistoryOptions( maxStanzas = 0 )
    
    def __init__(self, my_parent):
        muc.MUCClient.__init__( self )
        
        self.my_parent = my_parent
        #self.rooms = []
        
    def connectionInitialized(self):
        super( CommonMucProtocol, self ).connectionInitialized()
        
        self.xmlstream.addObserver("/message[@type='normal']/x[@xmlns='%s']/invite" % muc.NS_MUC_USER, self.receivedRoomInviteMessage )
        self.xmlstream.addObserver("/presence[@type='unavailable' and @to='%s']/x[@xmlns='%s']/status[@code='307']" % ( self.my_parent.jid.full(), muc.NS_MUC_USER ), self.receivedRoomKickMessage )
        self.xmlstream.addObserver("/presence[@to='%s']/x[@xmlns='%s']/status[@code='110']" % ( self.my_parent.jid.full(), muc.NS_MUC_USER ), self.roomJoined )
    
    def connectionLost(self, reason):
        print 'connectionLost'
        for room in self.rooms.values():
            self._removeRoom( room.entity_id )
        
    def createRoom(self, room):
        
        def roomConfigured( response ):
            print 'roomConfigured'
            return response
            
        def configureRoom( room ):
            print 'configureRoom'
            
            fields = [ data_form.Field( var='muc#roomconfig_roomname', value=room ),
                      data_form.Field( var='muc#roomconfig_persistentroom', value='0'),
                      data_form.Field( var='muc#roomconfig_publicroom', value='1'),
                      data_form.Field( var='public_list', value='1'),
                      data_form.Field( var='muc#roomconfig_passwordprotectedroom', value='0'),
                      data_form.Field( var='muc#roomconfig_whois', value='anyone'),
                      data_form.Field( var='muc#roomconfig_membersonly', value='0'),
                      data_form.Field( var='muc#roomconfig_moderatedroom', value='0'),
                      data_form.Field( var='muc#roomconfig_changesubject', value='0'),
                      data_form.Field( var='allow_private_messages', value='1'),
                      data_form.Field( var='allow_query_users', value='1'),
                      data_form.Field( var='muc#roomconfig_allowinvites', value='1'),
                      data_form.Field( var='muc#roomconfig_allowvisitorstatus', value='0'),
                      data_form.Field( var='muc#roomconfig_allowvisitornickchange', value='0'), 
                      data_form.Field( var='muc#roomconfig_maxusers', value='500'),
                      ]
            
            return self.configure( room['from'], fields ).addCallback( roomConfigured ).addErrback( log.err )
        
        def roomJoined( room ):
            print 'roomJoined'
            """
            if room.status == 201:
                print 'room created; configuring'
            """
            
            return self.getConfigureForm( room.entity_id.userhost() ).addCallback( configureRoom ).addErrback( log.err )
            
        return self.join('conference.' + self.my_parent.server, room, self.my_parent.jid.user ).addCallback( roomJoined ).addErrback( log.err )

    def receivedGroupChat(self, room, user, body):
        print 'received group chat'
        print body
        
    def inviteEntity(self, entity, room):
        print 'inviteEntity'
        self.invite( room.userhost(), None, entity.full() )
        
    def receivedRoomInviteMessage(self, message):
        print 'receivedRoomInviteMessage'
        
        def response_roomJoined( room ):
            print 'response_roomJoined'
            
        if message['from'].lower() in self.rooms:
            return
        
        room, server = message['from'].split( '@' )
        self.join( server, room, self.my_parent.jid.user, self.history_options ).addCallback( response_roomJoined ).addErrback( log.err )

    def receivedRoomKickMessage(self, message):
        print 'receivedRoomKickMessage'
        room_jid = jid.JID( message['from'].lower() ).userhostJID()
        self._removeRoom( room_jid )
     
    def roomJoined( self, message ):
        print 'roomJoined'