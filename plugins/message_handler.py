from wokkel import xmppim
from twisted.words.xish import domish
from twisted.python import log
import logging

from common import CommonClientManager

class CommonMessageHandler( xmppim.MessageProtocol ):

    def __init__( self, client ):
        super( CommonMessageHandler, self ).__init__()

        self.my_client = client

    def sendMessage(self, recipient, message):

        msg = domish.Element( (None, 'message') )
        msg['type'] = 'normal'
        msg['to'] = recipient.userhost()
        msg['from'] = self.my_client.jid.full()

        msg.addElement('body', None, message)
        self.send( msg )
        #self.addElement('subject', None, subject)

    def onMessage( self, message ):
        log.msg( 'onMessage', level = logging.DEBUG )

CommonClientManager.addHandler( 'message', CommonMessageHandler )
