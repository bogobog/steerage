from django.db import models

class Host( models.Model ):
    hostname = models.CharField( max_length = 100 )
    ip = models.IPAddressField()

    location = models.ForeignKey( 'HostLocation', related_name = 'hosts' )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return self.hostname
    
class HostLocation( models.Model ):
    name = models.CharField( max_length = 32 )
    meta  = models.TextField()
    room = models.CharField( max_length = 32 )

    provider = models.ForeignKey( 'HostProvider', related_name = 'host_locations' )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return self.name
    
class HostType( models.Model ):
    name = models.CharField( max_length = 32 )
    meta = models.TextField()
    room = models.CharField( max_length = 32 )

    provider = models.ForeignKey( 'HostProvider', related_name = 'host_types' )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return self.name

class HostImage( models.Model ):
    name = models.CharField( max_length = 32 )
    meta = models.TextField()
    room = models.CharField( max_length = 32 )
    
    provider = models.ForeignKey( 'HostProvider', related_name = 'host_images' )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return self.name
    
class HostProvider( models.Model ):
    name = models.CharField( max_length = 32 )
    module = models.CharField( max_length = 32 )
    meta = models.TextField( blank = True, null = True )
    room = models.CharField( max_length = 32 )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return self.name
    
class Service( models.Model ):
    name = models.CharField( max_length = 32 )
    room = models.CharField( max_length = 32 )
    package_url = models.CharField( max_length = 100 )

    start_command   = models.CharField( max_length = 100 )
    stop_command    = models.CharField( max_length = 100 )
    check_command   = models.CharField( max_length = 100 )
    
    category = models.ForeignKey( 'ServiceCategory', related_name = 'services' )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return self.name
    
class ServiceProfile( models.Model ):
    provider = models.ForeignKey( 'HostProvider', related_name = 'profiles' )
    meta = models.TextField( blank = True, null = True )
    
    type = models.ForeignKey( 'HostType', related_name = 'profiles' )
    image = models.ForeignKey( 'HostImage', related_name = 'profiles' )
    location = models.ForeignKey( 'HostLocation', related_name = 'profiles' )
    
    service = models.ForeignKey( 'Service', related_name = 'profiles' )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return "%s - %s" % ( self.service.name, self.provider.name )
      
class ServiceCategory( models.Model ):
    name = models.CharField( max_length = 32 )
    room = models.CharField( max_length = 32 )

    class Meta:
        app_label = 'steerage'
        
    def __unicode__(self):
        return self.name