
import ConfigParser

worker_config = ConfigParser.ConfigParser()
worker_config.read( 'config.ini' )

worker_roles = []
worker_roles_by_id = {}
worker_user_roles = {}

if worker_config.has_option( 'worker', 'roles' ):
    worker_roles = worker_config.get( 'worker', 'roles' ).split(',')
    worker_roles_by_id = dict( ( worker_roles[x], x ) for x in xrange( 0, len( worker_roles ) ) )
        
if worker_config.has_section( 'roles' ):
    worker_user_roles = dict( ( name, role ) for name, role in worker_config.items( 'roles' ) if role in worker_roles )