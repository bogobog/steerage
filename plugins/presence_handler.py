from twisted.python import log
from wokkel import xmppim
import logging

from common import CommonClientManager

class CommonPresenceHandler( xmppim.PresenceClientProtocol ):
    received_statuses = {}

    def __init__( self, client ):
        super( CommonPresenceHandler, self ).__init__()

        self.my_client = client

    def connectionInitialized(self):
        self.available()

    def subscribedReceived(self, entity):
        log.msg( 'subscribedReceived', level = logging.DEBUG )

    def subscribeReceived(self, subscriber):

        rtr_client = CommonClientManager.getHandler( 'roster', self.my_client )

        def rosterAddResponse( response ):
            log.msg( 'rosterAddResponse', level = logging.DEBUG )

            self.subscribed( subscriber )

            # subscribe to subscriber
            user_status = rtr_client.getUserStatus( subscriber )
            if not user_status or ( not user_status == 'both' and not user_status == 'to' ):
                rtr_client.addItem( subscriber.userhostJID() ).addCallback( addSubscriberToRosterResponse ).addErrback( log.err )

        def addSubscriberToRosterResponse( response ):
            log.msg( 'addSubscriberToRosterResponse', level = logging.DEBUG )

            if response.attributes['type'] == 'result':
                self.subscribe( subscriber.userhostJID() )

        rtr_client.addItem( subscriber ).addCallback( rosterAddResponse )

    def availableReceived(self, entity, show=None, statuses=None, priority=0):
        log.msg( 'availableReceived', level = logging.DEBUG )

        # ignore if self
        if entity.full() == self.my_client.jid.full():
            return

        self.received_statuses[ entity.full() ] = 'available'

CommonClientManager.addHandler( 'presence', CommonPresenceHandler )
