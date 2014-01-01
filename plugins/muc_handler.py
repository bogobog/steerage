from twisted.words.protocols.jabber import jid
from twisted.python import log
from wokkel import muc, data_form
import logging

from common import CommonClientManager

class CommonMucHandler( muc.MUCClient ):
    history_options = muc.HistoryOptions( maxStanzas = 0 )

    def __init__(self, client ):
        super( CommonMucHandler, self ).__init__()

        self.my_client = client
        #self.rooms = []

    def connectionInitialized(self):
        super( CommonMucHandler, self ).connectionInitialized()

        self.xmlstream.addObserver("/message[@type='normal']/x[@xmlns='%s']/invite" % muc.NS_MUC_USER, self.receivedRoomInviteMessage )
        self.xmlstream.addObserver("/presence[@type='unavailable' and @to='%s']/x[@xmlns='%s']/status[@code='307']" % ( self.my_client.jid.full(), muc.NS_MUC_USER ), self.receivedRoomKickMessage )
        self.xmlstream.addObserver("/presence[@to='%s']/x[@xmlns='%s']/status[@code='110']" % ( self.my_client.jid.full(), muc.NS_MUC_USER ), self.roomJoined )

    def connectionLost(self, reason):
        log.msg( 'connectionLost', level = logging.DEBUG )
        for room in self._rooms.values():
            self._removeRoom( room.entity_id )

    def createRoom(self, room):

        def roomConfigured( response ):
            log.msg( 'roomConfigured', level = logging.DEBUG )
            return response

        def configureRoom( room ):
            log.msg( 'configureRoom', level = logging.DEBUG )

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
            log.msg( 'roomJoined', level = logging.DEBUG )
            """
            if room.status == 201:
                log.msg( 'room created; configuring', level = logging.DEBUG )
            """

            return self.getConfigureForm( room.entity_id.userhost() ).addCallback( configureRoom ).addErrback( log.err )

        return self.join('conference.' + self.my_client.server, room, self.my_client.jid.user ).addCallback( roomJoined ).addErrback( log.err )

    def receivedGroupChat(self, room, user, body):
        log.msg( 'received group chat', level = logging.DEBUG )
        log.msg( body, level = logging.DEBUG )

    def inviteEntity(self, entity, room):
        log.msg( 'inviteEntity', level = logging.DEBUG )
        self.invite( room.userhost(), None, entity.full() )

    def receivedRoomInviteMessage(self, message):
        log.msg( 'receivedRoomInviteMessage', level = logging.DEBUG )

        def response_roomJoined( room ):
            log.msg( 'response_roomJoined', level = logging.DEBUG )

        if message['from'].lower() in self._rooms:
            return

        room, server = message['from'].split( '@' )
        self.join( server, room, self.my_client.jid.user, self.history_options ).addCallback( response_roomJoined ).addErrback( log.err )

    def receivedRoomKickMessage(self, message):
        log.msg( 'receivedRoomKickMessage', level = logging.DEBUG )
        room_jid = jid.JID( message['from'].lower() ).userhostJID()
        self._removeRoom( room_jid )

    def roomJoined( self, message ):
        log.msg( 'roomJoined', level = logging.DEBUG )

CommonClientManager.addHandler( 'muc', CommonMucHandler )
