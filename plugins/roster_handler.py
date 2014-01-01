from twisted.words.protocols.jabber import xmlstream
from twisted.python import log
from wokkel import xmppim
import logging

from common import CommonClientManager

class CommonRosterHandler( xmppim.RosterClientProtocol ):
    my_roster = {}

    def __init__( self, client ):
        super( CommonRosterHandler, self ).__init__()

        self.my_client = client

    def onRosterSet(self, item):
        log.msg( 'roster set received', level = logging.DEBUG )

        self.my_roster[ item.jid.full() ] = item
        log.msg( self.my_roster, level = logging.DEBUG )

    def connectionInitialized(self):
        xmppim.RosterClientProtocol.connectionInitialized(self)

        self.getRoster().addCallback( self.getRosterResponse )

    def getRosterResponse(self, roster):
        log.msg( 'roster received', level = logging.DEBUG )

        self.my_roster = roster

    def addItem(self, entity):
        iq = xmlstream.IQ( self.xmlstream, 'set' )
        iq.addElement( ( xmppim.NS_ROSTER, 'query' ) )
        item = iq.query.addElement( 'item' )
        item['jid'] = entity.full()
        return iq.send()

    """
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
    """

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

CommonClientManager.addHandler( 'roster', CommonRosterHandler )
