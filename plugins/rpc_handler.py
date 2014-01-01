
from twisted.words.xish import domish
from twisted.words.protocols.jabber import xmlstream
from twisted.python import log
from wokkel.subprotocols import XMPPHandler
import xmlrpclib, xml.dom.minidom, logging

from common import CommonClientManager

NS_RPC = 'jabber:iq:rpc'

def removeWhitespaceNodes(dom):
    """
    This method is called recursively for each element within the submitted dom
    and is used to remove empty whitespace elements
    """
    for child in list( dom.childNodes ):
        if child.nodeType == child.TEXT_NODE and child.data.strip() == '':
            dom.removeChild(child)
        else:
            removeWhitespaceNodes(child)

class RPCProtocolHandler( XMPPHandler ):
    subscribed_methods = {}

    def __init__( self, client ):
        super( RPCProtocolHandler, self ).__init__()

        self.my_client = client

    def connectionInitialized(self):
        RPC_SET = "/iq[@type='set']/query[@xmlns='%s']" % NS_RPC
        self.xmlstream.addObserver(RPC_SET, self.onMethodCall)

    def onMethodCall(self, iq):
        log.msg( 'onMethodCall', level = logging.DEBUG )

        method_name = str( iq.query.methodName )

        if not method_name in self.subscribed_methods:
            # send error response
            err_iq = FaultResponse( self.xmlstream, 1, 'method not implemented' )
            err_iq['id'] = iq.getAttribute('id')
            err_iq['to'] = iq.getAttribute('from')
            err_iq.send()
            return

        log.msg( 'method found', level = logging.DEBUG )
        target_method = self.subscribed_methods[ method_name ]
        converted_data = xmlrpclib.loads( iq.query.params.toXml() )[0]

        log.msg( 'converted_data', level = logging.DEBUG )
        log.msg( iq.query.params.toXml(), level = logging.DEBUG )
        log.msg( converted_data, level = logging.DEBUG )
        method_result = target_method( iq, *converted_data )

        if isinstance( method_result, RPCFault ):
            response_iq = FaultResponse( self.xmlstream, method_result.error_code, method_result.error_string )
        else:
            response_iq = MethodResponse( self.xmlstream, method_result )

        response_iq['id'] = iq.getAttribute('id')
        response_iq['to'] = iq.getAttribute('from')
        response_iq.send()

    def callMethod(self, recipient, method_name, params ):

        new_iq = xmlstream.IQ( self.xmlstream, 'set' )
        new_iq['to'] = recipient.full()

        q = new_iq.addElement( ( NS_RPC, 'query') )
        q.addElement( (None, 'methodName' ), content = str( method_name ) )

        params_dom = xml.dom.minidom.parseString( xmlrpclib.dumps( tuple( params ), allow_none = True ) )
        removeWhitespaceNodes( params_dom )
        q.addRawXml( params_dom.documentElement.toxml( 'utf-8' ) )

        log.msg( 'callMethod', level = logging.DEBUG )
        log.msg( tuple( params ), level = logging.DEBUG )
        log.msg( xmlrpclib.dumps( tuple( params ), allow_none = True ), level = logging.DEBUG )

        return new_iq.send()

    def subscribeMethod(self, method_name, method ):
        self.subscribed_methods[ method_name ] = method

    def unsubscribeMethod(self, method_name):
        if method_name in self.subscribed_methods:
            del self.subscribed_methods[ method_name ]

class RPCFault( object ):

    def __init__(self, error_code, error_string):
        self.error_code = error_code
        self.error_string = error_string

class FaultResponse( xmlstream.IQ ):

    def __init__(self, stream, error_code, error_string ):
        xmlstream.IQ.__init__(self, stream, 'result')

        q = self.addElement( ( NS_RPC, 'query') )
        st = q.addElement( ( None, 'methodResponse') ).addElement( ( None, 'fault' ) ).addElement( ( None, 'value' ) ).addElement( ( None, 'struct' ) )

        cm = st.addElement( (None, 'member' ) )
        cm.addElement( (None, 'name'), content = 'faultCode' )
        cm.addElement( (None, 'value') ).addElement( (None, 'int'), content = str( error_code ) )

        sm = st.addElement( (None, 'member' ) )
        sm.addElement( (None, 'name'), content = 'faultString' )
        sm.addElement( (None, 'value') ).addElement( (None, 'string'), content = str( error_string ) )

class MethodResponse( xmlstream.IQ ):

    def __init__(self, stream, params ):
        xmlstream.IQ.__init__(self, stream, 'result')

        q = self.addElement( ( NS_RPC, 'query') )
        q.addElement( ( None, 'methodResponse') )

        params_dom = xml.dom.minidom.parseString( xmlrpclib.dumps( ( params, ), allow_none = True ) )
        removeWhitespaceNodes( params_dom )
        q.addRawXml( params_dom.documentElement.toxml( 'utf-8' ) )

def objectToElement( item ):

    if isinstance( item, type( () ) ) or isinstance( item, type( [] ) ) and len( item ):
        new_ele = domish.Element( (None, 'array') )
        d = new_ele.addElement( (None, 'data') )
        for x in item:
            d.addElement( (None, 'value') ).addChild( objectToElement( x ) )
    elif isinstance( item, type( {} ) ):
        new_ele = domish.Element( (None, 'struct') )
        for name, value in item.items():
            if not isinstance( name, type( str() ) ):
                continue
            m = new_ele.addElement( (None, 'member') )
            m.addElement( (None, 'name'), content = str( name ) )
            m.addElement( (None, 'value') ).addChild( objectToElement( value ) )
    elif item is True or item is False:
        new_ele = domish.Element( (None, 'boolean') )
        new_ele.addContent( ( item and '1' ) or '0' )
    elif isinstance( item, type( int() ) ):
        new_ele = domish.Element( (None, 'int') )
        new_ele.addContent( str( item ) )
    elif isinstance( item, type( float() ) ):
        new_ele = domish.Element( (None, 'double') )
        new_ele.addContent( str( item ) )
    else:
        new_ele = domish.Element( (None, 'string') )
        new_ele.addContent( str( item ) )

    return new_ele

CommonClientManager.addHandler( 'rpc', RPCProtocolHandler )
