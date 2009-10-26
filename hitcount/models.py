import datetime

from django.db import models
from django.conf import settings
from django.db.models import F
from django.db.models.signals import pre_delete

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import User
from django.contrib.contenttypes import generic

class HitCount(models.Model):
    '''
    Model that stores the hit totals for any content object.
    '''
    hits            = models.PositiveIntegerField(default=0)
    modified        = models.DateTimeField(default=datetime.datetime.utcnow)
    content_type    = models.ForeignKey(ContentType)
    object_id       = models.PositiveIntegerField()
    content_object  = generic.GenericForeignKey('content_type', 'object_id')

    class Meta:
        ordering = ('-hits',)
        unique_together = (("content_type", "object_id"),)
        get_latest_by = "modified"
        db_table = "hitcount_hit_count"
        verbose_name = "Hit Count"
        verbose_name_plural = "Hit Counts"

    def __unicode__(self):
        return u'%s' % self.content_object

    def save(self, *args, **kwargs):
        self.modified = datetime.datetime.utcnow()
        super(HitCount, self).save(*args, **kwargs)

    def hits_in_last(self, **kwargs):
        '''
        Returns hit count for an object during a given time period.

        This will only work for as long as hits are saved in the Hit database.
        If you are purging your database after 45 days, for example, that means
        that asking for hits in the last 60 days will return an incorrect
        number as that the longest period it can search will be 45 days.
        
        For example: hits_in_last(days=7).

        Accepts days, seconds, microseconds, milliseconds, minutes, 
        hours, and weeks.  It's creating a datetime.timedelta object.
        '''
        assert kwargs, "Must provide at least one timedelta arg (eg, days=1)"
        period = datetime.datetime.utcnow() - datetime.timedelta(**kwargs)
        return self.hit_set.filter(created__gte=period).count()


class HitManager(models.Manager):

    def filter_active(self, *args, **kwargs):
        '''
        Return only the 'active' hits.
        
        How you count a hit/view will depend on personal choice: Should the
        same user/visitor *ever* be counted twice?  After a week, or a month,
        or a year, should their view be counted again?

        The defaulf is to consider a visitor's hit still 'active' if they 
        return within a the last seven days..  After that the hit
        will be counted again.  So if one person visits once a week for a year,
        they will add 52 hits to a given object.

        Change how long the expiration is by adding to settings.py:

        HITCOUNT_KEEP_HIT_ACTIVE  = {'days' : 30, 'minutes' : 30}

        Accepts days, seconds, microseconds, milliseconds, minutes, 
        hours, and weeks.  It's creating a datetime.timedelta object.
        '''
        grace = getattr(settings, 'HITCOUNT_KEEP_HIT_ACTIVE', {'days':7})
        period = datetime.datetime.utcnow() - datetime.timedelta(**grace)

        queryset = self.get_query_set()
        queryset = queryset.filter(created__gte=period)
        return queryset.filter(*args, **kwargs)

class Hit(models.Model):
    '''
    Model captures a single Hit by a visitor.

    None of the fields are editable because they are all dynamically created.
    Browsing the Hit list in the Admin will allow one to blacklist both
    IP addresses and User Agents. Blacklisting simply causes those hits 
    to not be counted or recorded any more.

    Depending on how long you set the HITCOUNT_KEEP_HIT_ACTIVE , and how long
    you want to be able to use `HitCount.hits_in_last(days=30)` you should
    probably also occasionally clean out this database using a cron job.

    It could get rather large.
    '''
    created         = models.DateTimeField(editable=False)
    ip              = models.CharField(max_length=40, editable=False)
    session         = models.CharField(max_length=40, editable=False)
    user_agent      = models.CharField(max_length=255, editable=False)
    user            = models.ForeignKey(User,null=True, editable=False)
    hitcount        = models.ForeignKey(HitCount, editable=False)

    class Meta:
        ordering = ("created",)    
        get_latest_by = "created"
        order_with_respect_to = "hitcount"

    def __unicode__(self):
        return u'Hit: %s' % self.pk 

    def save(self, *args, **kwargs):
        '''
        The first time the object is created and saved, we increment 
        the associated HitCount object by one.  The opposite applies
        if the Hit is deleted.
        '''
        if not self.created:
            self.hitcount.hits = F('hits') + 1
            self.hitcount.save()
            self.created = datetime.datetime.utcnow()

        super(Hit, self).save(*args, **kwargs)

    objects = HitManager()


class BlacklistIP(models.Model):
    ip = models.CharField(max_length=40, unique=True)

    class Meta: 
        db_table = "hitcount_blacklist_ip"
        verbose_name = "Blacklisted IP"
        verbose_name_plural = "Blacklisted IPs"

    def __unicode__(self):
        return u'%s' % self.ip


class BlacklistUserAgent(models.Model):
    user_agent = models.CharField(max_length=255, unique=True)

    class Meta: 
        db_table = "hitcount_blacklist_user_agent"
        verbose_name = "Blacklisted User Agent"
        verbose_name_plural = "Blacklisted User Agents"

    def __unicode__(self):
        return u'%s' % self.user_agent

# Signal catching below.

def subtract_hit_count(sender, instance, **kwargs):
    '''
    When you delete a Hit, it will automatically subtract itself from the
    totals in the related HitCount object.
    '''
    instance.hitcount.hits = F('hits') - 1
    instance.hitcount.save()

pre_delete.connect(subtract_hit_count, sender=Hit)