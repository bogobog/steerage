from twisted.words.protocols.jabber import jid, xmlstream
from twisted.internet import reactor
from twisted.python import log
from wokkel import muc
import socket, os
from subprocess import Popen, PIPE

import common

class WorkerMucProtocol( common.CommonMucProtocol ):
    
    def __init__(self, *args, **kwargs):
        super( WorkerMucProtocol, self ).__init__( *args, **kwargs )
        
        self.default_rooms_check = None

    def connectionInitialized(self):
        super( WorkerMucProtocol, self ).connectionInitialized()
        self.joinDefaultRooms()
    
    def joinDefaultRooms(self):
        log.msg( 'joinDefaultRooms' )
        
        if not len( self.my_parent.initial_room_list ):
            return True
        
        room_list = list( self.my_parent.initial_room_list )
        current_rooms = list( key.user for key in self._rooms.keys() )
                
        for room in room_list:
            if not room in current_rooms:
                self.join( jid.JID( '%s@conference.%s' % ( room, self.my_parent.server ) ), self.my_parent.jid.user )
        
        self.default_rooms_check = reactor.callLater( common.WORKER_DEFAULT_ROOM_CHECK_INTERVAL_SECS, self.joinDefaultRooms )
        
    def connectionLost(self, reason):
        log.msg( 'connectionLost' )
        if self.default_rooms_check:
            self.default_rooms_check.cancel()
        
        
class WorkerMessageProtocol( common.CommonMessageProtocol ):
    pass

class WorkerPresenceProtocol( common.CommonPresenceProtocol ):
    pass

class WorkerRPCProtocol( common.RPCProtocol ):
    pass
        
class WorkerRosterProtocol( common.CommonRosterProtocol ):
    pass

    """
    def getRosterResponse(self, roster):
        super( WorkerRosterProtocol, self ).getRosterResponse( roster )
        
        user_status = self.my_parent.rtr_client.getUserStatus( jid.JID( manager_user + '@' + self.my_parent.jid.host ) )
        if not user_status or ( not user_status == 'both' and not user_status == 'from' ):
            self.subscribeToManager()   
        
    def subscribeToManager(self):
        # add manager to roster
        
        def addManagerResponse( response ):
            print 'addManagerResponse received'
            
            if response.attributes['type'] == 'result':
                self.my_parent.pre_client.subscribe( jid.JID( manager_user + '@' + self.my_parent.jid.host ) )
        
        self.addItem( jid.JID( manager_user + '@' + self.my_parent.jid.host ) ).addCallback( addManagerResponse ).addErrback( log.err )
    """
    
class WorkerClient( object ):
                
    def __init__( self, user, resource, password, server, port = 5222, trigger_config = False, room_list = [] ):
        
        self.server = server
        self.port = int( port )
        
        self.assigned_service = {}
       
        self.jid = jid.JID( user + '@' + server + "/" + resource )
        self.factory = common.CommonClientFactory(self, password)
        self.factory.streamManager.logTraffic = True
    
        self.initial_room_list = room_list
    
        self.muc_client = WorkerMucProtocol( self )
        self.muc_client.setHandlerParent( self.factory.streamManager )
        
        self.msg_client = WorkerMessageProtocol( self )
        self.msg_client.setHandlerParent( self.factory.streamManager )
    
        self.pre_client = WorkerPresenceProtocol( self )
        self.pre_client.setHandlerParent( self.factory.streamManager )
        self.pre_client.available()
        #self.pre_client.addPresenceTrigger( self.manager_jid, 'available', self.registerWithManager )
        
        self.rtr_client = WorkerRosterProtocol( self )
        self.rtr_client.setHandlerParent( self.factory.streamManager )
        
        self.rpc_client = WorkerRPCProtocol( self )
        self.rpc_client.setHandlerParent( self.factory.streamManager )
        #self.rpc_client.subscribeMethod( 'assignService', self.rpc_assignService )
        
        if trigger_config:
            self.trigger_handler = common.TriggerHandler( self, trigger_config )
            self.trigger_handler.setHandlerParent( self.factory.streamManager )
                        
        reactor.connectTCP( self.server, self.port, self.factory )
        