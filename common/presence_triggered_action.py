
class PresenceTriggeredAction( object ):
    
    def __init__(self, entity, status, action):
        self.entity = entity.full()
        self.status = str( status )
        self.action = action