'''
Project: Farnsworth

Author: Karandeep Singh Nagra
'''

from __future__ import unicode_literals, absolute_import

from django.contrib.auth.models import User
from django.conf import settings
from django.db import models
from django.utils.dateformat import time_format


from base.models import UserProfile
from utils.variables import ANONYMOUS_USERNAME
from managers.models import Manager
from workshift.fields import DayField
from workshift.templatetags.workshift_tags import wurl

WORKSHIFT_MANAGER_VERIFY = "W"
POOL_MANAGER_VERIFY = "P"
ANY_MANAGER_VERIFY = "M"
OTHER_VERIFY = "O"
SELF_VERIFY = "S"
AUTO_VERIFY = "A"

VERIFY_CHOICES = (
    (WORKSHIFT_MANAGER_VERIFY, "Workshift Managers only"),
    (POOL_MANAGER_VERIFY, "Pool Managers only"),
    (ANY_MANAGER_VERIFY, "Any Manager"),
    (OTHER_VERIFY, "Another member"),
    (SELF_VERIFY, "Any member (including self)"),
    (AUTO_VERIFY, "Automatically verified"),
    )

class Semester(models.Model):
    '''
    A semester instance, used to hold records, settings, and to separate
    workshifts into contained units.
    '''
    SPRING = "Sp"
    SUMMER = "Su"
    FALL = "Fa"
    SEASON_CHOICES = (
        (SPRING, 'Spring'),
        (SUMMER, 'Summer'),
        (FALL, 'Fall')
        )
    season = models.CharField(
        max_length=2,
        choices=SEASON_CHOICES,
        default=SPRING,
        help_text="Season of the year (spring, summer, fall) of this semester.",
        )
    year = models.PositiveSmallIntegerField(
        max_length=4,
        help_text="Year of this semester.",
        )
    workshift_managers = models.ManyToManyField(
        User,
        blank=True,
        help_text="The users who were/are Workshift Managers for this semester.",
        )
    rate = models.DecimalField(
        max_digits=7, # In case of inflation
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Workshift rate for this semester.",
        )
    policy = models.URLField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Link to the workshift policy for this semester.",
        )
    start_date = models.DateField(
        help_text="Start date of this semester.",
        )
    end_date = models.DateField(
        help_text="End date of this semester.",
        )
    preferences_open = models.BooleanField(
        default=False,
        help_text="Whether members can enter their workshift preferences.",
        )
    current = models.BooleanField(
        default=True,
        help_text="If this semester is the current semester.",
        )

    @property
    def sem_url(self):
        if self.current:
            return ""
        return self.season + str(self.year)

    def display_rate(self):
        """ Human readable format for rate. """
        return "${0}".format(self.rate)

    class Meta:
        unique_together = ("season", "year")
        ordering = ['-start_date']

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return "{0} {1}".format(self.get_season_display(), self.year)

    def is_semester(self):
        return True

    def get_view_url(self):
        return wurl("workshift:view_semester", sem_url=self.sem_url)

    def get_edit_url(self):
        return wurl("workshift:manage", sem_url=self.sem_url)

class WorkshiftPool(models.Model):
    title = models.CharField(
        max_length=100,
        default="Regular Workshift",
        help_text="The title of this workshift pool (i.e. HI Hours)",
        )
    semester = models.ForeignKey(
        Semester,
        help_text="The semester associated with this pool of workshift hours.",
        )
    managers = models.ManyToManyField(
        Manager,
        blank=True,
        help_text="Managers who are able to control this workshift category."
        )
    sign_out_cutoff = models.PositiveSmallIntegerField(
        default=settings.DEFAULT_SIGN_OUT_CUTOFF,
        help_text="Cutoff for signing out of workshifts without requiring "
        "a substitute, in hours.",
        )
    verify_cutoff = models.PositiveSmallIntegerField(
        default=settings.DEFAULT_VERIFY_CUTOFF,
        help_text="Cutoff for verifying a workshift after it has finished, "
        "in hours. After this cutoff, the shift will be marked as blown."
        )
    hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=settings.DEFAULT_WORKSHIFT_HOURS,
        help_text="Default hours required per member per period "
        "(e.g., 2 weeks per period and 2 hours required per period means 2 "
        "hours required every two weeks).",
        )
    weeks_per_period = models.PositiveSmallIntegerField(
        default=1,
        help_text="Number of weeks for requirement period "
        "(e.g., 2 weeks per period and 2 hours required per period means 2 "
        "hours required every two weeks). 0 makes this a semesterly requirement",
        )
    first_fine_date = models.DateField(
        null=True,
        blank=True,
        help_text="First fine date for this semester, optional.",
        )
    second_fine_date = models.DateField(
        null=True,
        blank=True,
        help_text="Second fine date for this semester, optional.",
        )
    third_fine_date = models.DateField(
        null=True,
        blank=True,
        help_text="Third fine date for this semester, optional.",
        )
    any_blown = models.BooleanField(
        default=False,
        help_text="If any member is allowed to mark a shift as blown.",
        )
    is_primary = models.BooleanField(
        default=False,
        help_text="Is the primary workshift pool for the house.",
        )

    class Meta:
        unique_together = ("semester", "title")

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return self.title

    def show_hours(self):
        if self.weeks_per_period == 0:
            ret = "{0} hour{1} per semester"
        elif self.weeks_per_period == 1:
            ret = "{0} hour{1} per week"
        else:
            ret = "{{0}} hour{{1}} per {0} weeks".format(self.weeks_per_period)
        return ret.format(
            self.hours, "s" if self.hours != 1 else "",
            )

    def get_view_url(self):
        return wurl("workshift:view_pool", pk=self.pk, sem_url=self.semester.sem_url)

    def get_edit_url(self):
        return wurl("workshift:edit_pool", pk=self.pk, sem_url=self.semester.sem_url)

    def is_workshift_pool(self):
        return True

class WorkshiftType(models.Model):
    '''
    A workshift type; for example, a "Pots" workshift type.
    '''
    title = models.CharField(
        blank=False,
        null=False,
        unique=True,
        max_length=255,
        help_text='The title of this workshift type (e.g., "Pots"), must be unique.',
        )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="A description for this workshift type.",
        )
    quick_tips = models.TextField(
        blank=True,
        null=True,
        help_text="Quick tips to the workshifter.",
        )
    rateable = models.BooleanField(
        default=True,
        help_text="Whether this workshift type is shown in preferences.",
        )
    AUTO_ASSIGN = 'A'
    MANUAL_ASSIGN = 'M'
    NO_ASSIGN = 'O'
    ASSIGNMENT_CHOICES = (
        (AUTO_ASSIGN, "Auto-assign"),
        (MANUAL_ASSIGN, "Manually assign"),
        (NO_ASSIGN, "No assignment")
        )
    assignment = models.CharField(
        max_length=1,
        choices=ASSIGNMENT_CHOICES,
        default=AUTO_ASSIGN,
        help_text="How assignment to this workshift works. This can be automatic, "
        "manual-only, or no assignment (i.e. Manager shifts, which are internally "
        "assigned.",
        )

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return self.title

    def is_workshift_type(self):
        return True

    def get_view_url(self):
        return wurl("workshift:view_type", pk=self.pk)

    def get_edit_url(self):
        return wurl("workshift:edit_type", pk=self.pk)

class TimeBlock(models.Model):
    '''
    A time block to represent member availability during a particular day.
    Used to reduce database size by creating references to existing time blocks for users.
    These objects should never be directly created on their own.  They be
    created and retrieved for use.
    '''
    BUSY = 0
    PREFERRED = 1
    PREFERENCE_CHOICES = (
        (BUSY, "Busy"),
        (PREFERRED, "Preferred"),
        )
    preference = models.PositiveSmallIntegerField(
        max_length=1,
        choices=PREFERENCE_CHOICES,
        default=BUSY,
        help_text="The user's preference for this time block.",
        )
    day = DayField(
        help_text="Day of the week for this time block.",
        )
    start_time = models.TimeField(
        help_text="Start time for this time block.",
        )
    end_time = models.TimeField(
        help_text="End time for this time block.",
        )

class WorkshiftRating(models.Model):
    '''
    A preference for a workshift type.  Used to reduce database size by creating
    references to existing ratings for users.

    These objects should never be directly created on their own.  They be
    created and retrieved for use.
    '''
    DISLIKE = 0
    INDIFFERENT = 1
    LIKE = 2
    RATING_CHOICES = (
        (DISLIKE, "Dislike"),
        (INDIFFERENT, "Indifferent"),
        (LIKE, "Like")
        )
    rating = models.PositiveSmallIntegerField(
        max_length=1,
        choices=RATING_CHOICES,
        default=INDIFFERENT,
        help_text="Rating for the workshift type.",
        )
    workshift_type = models.ForeignKey(
        WorkshiftType,
        help_text="The workshift type being rated.",
        )

class PoolHours(models.Model):
    """
    The hours that members owe for individual workshift pools. Also tracks
    workshift fines related to that pool.

    i.e. 5 hours per week to workshift, 2 hours per 6 weeks to humor shift.
    """
    pool = models.ForeignKey(
        WorkshiftPool,
        help_text="The pool associated with these hours.",
    )
    hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=settings.DEFAULT_WORKSHIFT_HOURS,
        help_text="Periodic hour requirement.",
    )
    assigned_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Total hours satisfied by periodic shifts.",
    )
    standing = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Current hours standing, below or above requirement.",
    )
    hour_adjustment = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Manual hour requirement adjustment.",
    )
    last_updated = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the last time the system updated this workshifter's standings.",
    )
    first_date_standing = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
        help_text="The hourly fines or repayment at the first fine date. "
        "Stored in a field for manual adjustment.",
    )
    second_date_standing = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
        help_text="The hourly fines or repayment at the second fine date. "
        "Stored in a field for manual adjustment.",
    )
    third_date_standing = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        default=0,
        help_text="The hourly fines or repayment at the third fine date. "
        "Stored in a field for manual adjustment.",
    )

    def show_hours(self):
        if self.pool.weeks_per_period == 0:
            ret = "{0} hour{1} per semester"
        elif self.pool.weeks_per_period == 1:
            ret = "{0} hour{1} per week"
        else:
            ret = "{{0}} hour{{1}} per {0} weeks".format(self.pool.weeks_per_period)
        return ret.format(
            self.hours, "s" if self.hours != 1 else "",
            )

class WorkshiftProfile(models.Model):
    ''' A workshift profile for a user for a given semester. '''
    user = models.ForeignKey(
        User,
        help_text="The user for this workshift profile.",
        )
    semester = models.ForeignKey(
        Semester,
        help_text="The semester for this workshift profile.",
        )
    note = models.TextField(
        null=True,
        blank=True,
        help_text="Note for this profile. For communication between the "
        "workshifter and the workshift manager(s).",
        )
    preference_save_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The time this member first saved their preferences.",
        )
    time_blocks = models.ManyToManyField(
        TimeBlock,
        blank=True,
        help_text="The time blocks for this workshift profile.",
        )
    ratings = models.ManyToManyField(
        WorkshiftRating,
        blank=True,
        help_text="The workshift ratings for this workshift profile.",
        )
    pool_hours = models.ManyToManyField(
        PoolHours,
        blank=True,
        help_text="Hours required for each workshift pool for this profile.",
        )

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        ret = self.user.get_full_name()
        if UserProfile.objects.get(user=self.user).status == UserProfile.BOARDER:
            ret += " (Boarder)"
        return ret

    class Meta:
        unique_together = ("user", "semester")

    def is_workshift_profile(self):
        return True

    def get_first(self):
        return self.user.first_name

    def get_last(self):
        return self.user.last_name

    def get_user(self):
        return self.user.username

    def get_full_name(self):
        return self.user.get_full_name()

    def get_view_url(self):
        return wurl(
            "workshift:profile",
            targetUsername=self.user.username,
            sem_url=self.semester.sem_url,
        )

    def get_edit_url(self):
        return wurl(
            "workshift:edit_profile",
            targetUsername=self.user.username,
            sem_url=self.semester.sem_url,
        )

class RegularWorkshift(models.Model):
    '''
    A weekly workshift for a semester.
    Used to generate individual instances of workshifts.
    '''
    workshift_type = models.ForeignKey(
        WorkshiftType,
        help_text="The workshift type for this weekly workshift.",
    )
    pool = models.ForeignKey(
        WorkshiftPool,
        help_text="The workshift pool for this shift.",
    )
    day = DayField(
        null=True,
        blank=True,
        help_text="The day of the week when this workshift takes place.",
    )
    count = models.PositiveSmallIntegerField(
        max_length=4,
        default=1,
        help_text="Number of instances to create with each occurrence.",
    )
    hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=settings.DEFAULT_WORKSHIFT_HOURS,
        help_text="Number of hours for this shift.",
    )
    active = models.BooleanField(
        default=True,
        help_text="Whether this shift is actively being used currently "
        "(displayed in list of shifts, given hours, etc.).",
    )
    current_assignees = models.ManyToManyField(
        WorkshiftProfile,
        blank=True,
        help_text="The workshifter currently assigned to this weekly "
        "workshift.",
    )
    start_time = models.TimeField(
        help_text="Start time for this workshift.",
        null=True,
        blank=True,
    )
    end_time = models.TimeField(
        help_text="End time for this workshift.",
        null=True,
        blank=True,
    )
    verify = models.CharField(
        default=OTHER_VERIFY,
        choices=VERIFY_CHOICES,
        max_length=1,
        help_text="Who is able to mark this shift as completed.",
    )
    week_long = models.BooleanField(
        default=False,
        help_text="If this shift is for the entire week.",
    )
    addendum = models.TextField(
        default='',
        blank=True,
        null=True,
        help_text="Addendum to the description for this workshift.",
    )
    is_manager_shift = models.BooleanField(
        default=False,
        help_text="If this shift was automatically generated from the managers module",
    )

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        if self.day:
            return "{0}:{1}".format(
                self.workshift_type.title,
                self.get_day_display(),
                )
        else:
            return self.workshift_type.title

    def get_view_url(self):
        return wurl("workshift:view_shift", pk=self.pk, sem_url=self.pool.semester.sem_url)

    def get_edit_url(self):
        return wurl("workshift:edit_shift", pk=self.pk, sem_url=self.pool.semester.sem_url)

    def display_time(self):
        if self.day is not None:
            ret = self.get_day_display()
        else:
            ret = "Week long"
        ret += " " + self.get_time_range()
        return ret

    def get_start_time(self):
        if self.start_time is None:
            return ""
        return time_format(self.start_time, "P")

    def get_end_time(self):
        if self.end_time is None:
            return ""
        return time_format(self.end_time, "P")

    def get_time_range(self):
        return "{}{}{}".format(
            self.get_start_time(),
            " - " if self.start_time is not None and self.end_time is not None else "",
            self.get_end_time(),
        )

    def is_regular_workshift(self):
        return True

class ShiftLogEntry(models.Model):
    ''' Entries for sign-ins, sign-outs, and verification. '''
    person = models.ForeignKey(
        WorkshiftProfile,
        blank=True,
        null=True,
        help_text="Person who made this entry.",
        )
    entry_time = models.DateTimeField(
        auto_now_add=True,
        help_text="Time this entry was made."
        )
    hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Hours associated with a change in workshift credit.",
        )
    note = models.TextField(
        blank=True,
        null=True,
        help_text="Message to the workshift manager. "
        "(e.g. 'Can't cook because of flu')",
        )
    ASSIGNED = 'A'
    BLOWN = 'B'
    SIGNIN = 'I'
    SIGNOUT = 'O'
    VERIFY = 'V'
    SELL = 'S'
    MODIFY_HOURS = "M"
    ENTRY_CHOICES = (
        (ASSIGNED, 'Assigned'),
        (BLOWN, 'Blown'),
        (SIGNIN, 'Sign In'),
        (SIGNOUT, 'Sign Out'),
        (VERIFY, 'Verify'),
        (MODIFY_HOURS, "Modify Hours"),
        (SELL, 'Sell'),
    )
    entry_type = models.CharField(
        max_length=1,
        choices=ENTRY_CHOICES,
        default=VERIFY,
        )

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return "<{0}, {1}>".format(
            self.person,
            self.entry_type,
            )

    class Meta:
        ordering = ['-entry_time']

class InstanceInfo(models.Model):
    """
    The info associated with a WorkshiftInstance for a non-recurring task.
    """
    title = models.CharField(
        null=True,
        blank=True,
        max_length=255,
        help_text="Title for this shift.",
        )
    description = models.TextField(
        null=True,
        blank=True,
        help_text="Description of the shift.",
        )
    pool = models.ForeignKey(
        WorkshiftPool,
        null=True,
        blank=True,
        help_text="The workshift pool for this shift.",
        )
    verify = models.CharField(
        default=OTHER_VERIFY,
        choices=VERIFY_CHOICES,
        max_length=1,
        help_text="Who is able to mark this shift as completed.",
        )
    start_time = models.TimeField(
        help_text="Start time for this workshift.",
        null=True,
        blank=True,
        )
    end_time = models.TimeField(
        help_text="End time for this workshift.",
        null=True,
        blank=True,
        )
    week_long = models.BooleanField(
        default=False,
        help_text="If this shift is for the entire week.",
        )

class WorkshiftInstance(models.Model):
    ''' An instance of a workshift. '''
    semester = models.ForeignKey(
        Semester,
        help_text="The semester for this workshift.",
        )
    weekly_workshift = models.ForeignKey(
        RegularWorkshift,
        null=True,
        blank=True,
        help_text="The weekly workshift of which this is an instance.",
        )
    info = models.ForeignKey(
        InstanceInfo,
        null=True,
        blank=True,
        help_text="The weekly workshift of which this is an instance.",
        )
    date = models.DateField(
        help_text="Date of this workshift.",
        )
    workshifter = models.ForeignKey(
        WorkshiftProfile,
        null=True,
        blank=True,
        related_name="instance_workshifter",
        help_text="Workshifter who was signed into this shift at the time "
        "it started.",
        )
    liable = models.ForeignKey(
        WorkshiftProfile,
        null=True,
        blank=True,
        related_name="instance_liable",
        help_text="Workshifter who is liable for this shift if no one else "
        "signs in.",
        )
    verifier = models.ForeignKey(
        WorkshiftProfile,
        null=True,
        blank=True,
        related_name="instance_verifier",
        help_text="Workshifter who verified that this shift was completed.",
        )
    closed = models.BooleanField(
        default=False,
        help_text="If this shift has been completed.",
        )
    blown = models.BooleanField(
        default=False,
        help_text="If this shift has been blown.",
        )
    intended_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=settings.DEFAULT_WORKSHIFT_HOURS,
        help_text="Intended hours given for this shift.",
        )
    hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=settings.DEFAULT_WORKSHIFT_HOURS,
        help_text="Number of hours actually given for this shift.",
        )
    logs = models.ManyToManyField(
        ShiftLogEntry,
        blank=True,
        help_text="The entries for sign ins, sign outs, and verification.",
        )

    def get_info(self):
        return self.weekly_workshift or self.info

    @property
    def title(self):
        if self.weekly_workshift:
            return self.weekly_workshift.workshift_type.title
        else:
            return self.info.title

    @property
    def description(self):
        if self.weekly_workshift:
            return self.weekly_workshift.workshift_type.description
        else:
            return self.info.description

    @property
    def pool(self):
        return self.get_info().pool

    @property
    def verify(self):
        return self.get_info().verify

    @property
    def week_long(self):
        return self.get_info().week_long

    @property
    def start_time(self):
        return self.get_info().start_time

    @property
    def end_time(self):
        return self.get_info().end_time

    def __init__(self, *args, **kwargs):
        if "semester" not in kwargs:
            if "weekly_workshift" in kwargs:
                kwargs["semester"] = kwargs["weekly_workshift"].pool.semester
            elif "info" in kwargs:
                kwargs["semester"] = kwargs["info"].pool.semester

        super(WorkshiftInstance, self).__init__(*args, **kwargs)

        if self.weekly_workshift is not None and self.info is not None:
            raise ValueError("Only one of [weekly_workshift, info] can be set")

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return "{0}, {1}".format(self.title, self.date)

    def display_time(self):
        return "{} {}".format(self.date, self.get_time_range())

    def get_start_time(self):
        if self.start_time is None:
            return ""
        return time_format(self.start_time, "P")

    def get_end_time(self):
        if self.end_time is None:
            return ""
        return time_format(self.end_time, "P")

    def get_time_range(self):
        return "{}{}{}".format(
            self.get_start_time(),
            " - " if self.start_time is not None and self.end_time is not None else "",
            self.get_end_time(),
        )

    def is_workshift_instance(self):
        return True

    def get_view_url(self):
        return wurl("workshift:view_instance", pk=self.pk, sem_url=self.semester.sem_url)

    def get_edit_url(self):
        return wurl("workshift:edit_instance", pk=self.pk, sem_url=self.semester.sem_url)

from workshift import signals
