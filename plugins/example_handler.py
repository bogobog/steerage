from twisted.python import log
from twisted.words.xish import domish
from twisted.words.protocols.jabber import jid
from wokkel.subprotocols import XMPPHandler
import logging, re

from common import CommonClientManager

class ExampleHandler( XMPPHandler ):
    subscribed_methods = {}

    def __init__( self, client ):
        super( ExampleHandler, self ).__init__()

        self.my_client = client

    def connectionInitialized(self):
        self.xmlstream.addObserver( "/message[@type='groupchat']" , self.onGroupchatMessage )

    def onGroupchatMessage(self, message):
        log.msg( 'onGroupchatMessage', level = logging.DEBUG )

        from_jid = jid.JID( message.getAttribute( 'from' ) )

        if from_jid.resource == self.my_client.user:
            return

        if not re.search( '(^(?=(thanks|thank you))|(thanks|thank you)(?=$))', str( message.body ), flags = re.IGNORECASE ):
            return

        msg = domish.Element( ( None, 'message' ) )
        msg['type'] = 'groupchat'
        msg['to'] = from_jid.userhost()
        msg.addElement( 'body', None, 'no, thank you, %s' % from_jid.resource )
        print msg
        self.xmlstream.send( msg )

CommonClientManager.addHandler( 'example', ExampleHandler )
