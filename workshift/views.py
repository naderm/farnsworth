"""
Project: Farnsworth

Authors: Karandeep Singh Nagra and Nader Morshed
"""

from __future__ import division, absolute_import

from datetime import date, timedelta

from django.utils.timezone import now
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext

import inflect
p = inflect.engine()

from utils.variables import MESSAGES, date_formats
from base.models import User
from managers.models import Manager
from workshift.decorators import get_workshift_profile, \
    workshift_manager_required, semester_required
from workshift.models import *
from workshift.forms import *
from workshift import utils
from workshift.templatetags.workshift_tags import wurl

def add_archive_context(request):
    semester_count = Semester.objects.count()
    workshift_profile_count = WorkshiftProfile.objects.count()
    shift_log_entry_count = ShiftLogEntry.objects.count()
    workshift_instance_count = WorkshiftInstance.objects.count()
    nodes = [
        [
            "{} {}".format(semester_count, p.plural("semester", semester_count)),
            "{} workshift {}".format(workshift_profile_count, p.plural("profile", workshift_profile_count)),
            "{} workshift {}".format(workshift_instance_count, p.plural("instance", workshift_instance_count)),
            "{} workshift instance log {}".format(shift_log_entry_count, p.plural("entries", shift_log_entry_count)),
        ]
    ]
    return nodes, []

def _pool_upcoming_vacant_shifts(workshift_pool, workshift_profile):
    """ Given a workshift pool and a workshift profile,
    return all upcoming, vacant shifts along with sign-in forms
    for the profile in that pool. """
    upcoming_shifts = list()
    today = now().today()
    for shift in WorkshiftInstance.objects.filter(
            date__gte=today,
            closed=False,
            blown=False,
            workshifter=None,
            liable=None,
        ):
        if shift.pool == workshift_pool:
            form = SignInForm(
                initial={"pk": shift.pk},
                profile=workshift_profile,
                )
            upcoming_shifts.append((shift, form))
    return upcoming_shifts

def add_workshift_context(request):
    """ Add workshift variables to all dictionaries passed to templates. """
    if not request.user.is_authenticated():
        return {}

    if Semester.objects.count() < 1:
        return {"WORKSHIFT_ENABLED": False}

    # Current semester is for navbar notifications
    try:
        current_semester = Semester.objects.get(current=True)
    except Semester.DoesNotExist:
        current_semester = None
    except Semester.MultipleObjectsReturned:
        current_semester = Semester.objects.filter(current=True).latest("start_date")
        workshift_emails = []
        for pos in Manager.objects.filter(workshift_manager=True, active=True):
            if pos.email:
                workshift_emails.append(pos.email)
            elif pos.incumbent.email_visible and pos.incumbent.user.email:
                workshift_emails.append(pos.incumbent.user.email)
        if workshift_emails:
            workshift_email_str = " ({0})".format(
                ", ".join(["<a href=\"mailto:{0}\">{0}</a>".format(i)
                           for i in workshift_emails])
                )
        else:
            workshift_email_str = ""
        messages.add_message(
            request, messages.WARNING,
            MESSAGES["MULTIPLE_CURRENT_SEMESTERS"].format(
                admin_email=settings.ADMINS[0][1],
                workshift_emails=workshift_email_str,
                ))

    today = now().date()

    days_passed = None
    total_days = None
    semester_percentage = None
    standing = None
    happening_now = None
    workshift_profile = None

    if current_semester:
        # number of days passed in this semester
        days_passed = (today - current_semester.start_date).days

        # total number of days in this semester
        total_days = (current_semester.end_date - current_semester.start_date).days
        semester_percentage = round((days_passed / total_days) * 100, 2)

    # Semester is for populating the current page
    try:
        semester = request.semester
    except AttributeError:
        semester = current_semester

    try:
        workshift_profile = WorkshiftProfile.objects.get(
            semester=semester,
            user=request.user,
            )
    except WorkshiftProfile.DoesNotExist:
        workshift_profile = None

    workshift_manager = utils.can_manage(request.user, semester=semester)

    upcoming_shifts = WorkshiftInstance.objects.filter(
        workshifter=workshift_profile,
        closed=False,
        date__gte=today,
        date__lte=today + timedelta(days=2),
        )

    # TODO: Add a fudge factor of an hour to this?
    time = now().time()
    happening_now = []
    for shift in upcoming_shifts:
        if shift.week_long:
            happening_now.append(shift)
            continue
        if shift.date != today:
            continue
        if shift.start_time is None:
            if shift.end_time is not None:
                if time < shift.end_time:
                    happening_now.append(shift)
            else:
                happening_now.append(shift)
            continue
        if shift.end_time is None:
            if shift.start_time is not None:
                if time > shift.start_time:
                    happening_now.append(shift)
            else:
                happening_now.append(shift)
            continue
        if time > shift.start_time and time < shift.end_time:
            happening_now.append(shift)

    if workshift_profile:
        try:
            standing = workshift_profile.pool_hours.get(pool__is_primary=True).standing
        except (PoolHours.DoesNotExist, PoolHours.MultipleObjectsReturned):
            pass

    return {
        "WORKSHIFT_ENABLED": True,
        "SEMESTER": semester,
        "CURRENT_SEMESTER": current_semester,
        "WORKSHIFT_MANAGER": workshift_manager,
        "WORKSHIFT_PROFILE": workshift_profile,
        "STANDING": standing,
        "DAYS_PASSED": days_passed,
        "TOTAL_DAYS": total_days,
        "SEMESTER_PERCENTAGE": semester_percentage,
        "UPCOMING_SHIFTS": zip(upcoming_shifts, happening_now),
        }

@workshift_manager_required
def start_semester_view(request):
    """
    Initiates a semester"s worth of workshift, with the option to copy workshift
    types from the previous semester.
    """
    page_name = "Start Semester"
    year, season = utils.get_year_season()
    start_date, end_date = utils.get_semester_start_end(year, season)

    semester_form = SemesterForm(
        request.POST or None,
        initial={
            "year": year,
            "season": season,
            "start_date": start_date.strftime(date_formats[0]),
            "end_date": end_date.strftime(date_formats[0]),
        },
        prefix="semester",
    )

    pool_forms = []
    try:
        prev_semester = Semester.objects.order_by("end_date")[0]
    except IndexError:
        pass
    else:
        pools = WorkshiftPool.objects.filter(semester=prev_semester, is_primary=False)
        for pool in pools:
            form = StartPoolForm(
                request.POST or None,
                initial={
                    "title": pool.title,
                    "hours": pool.hours,
                },
                prefix="pool-{0}".format(pool.pk),
            )
            pool_forms.append(form)

    if semester_form.is_valid() and all(i.is_valid() for i in pool_forms):
        # And save this semester
        semester = semester_form.save()
        for pool_form in pool_forms:
            pool_form.save(semester=semester)
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))

    return render_to_response("start_semester.html", {
        "page_name": page_name,
        "semester_form": semester_form,
        "pool_forms": pool_forms,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def semester_view(request, semester, profile=None):
    """
    Displays a table of the workshifts for the week, shift assignments,
    accumulated statistics (Down hours), reminders for any upcoming shifts, and
    links to sign off on shifts. Also links to the rest of the workshift pages.
    """
    template_dict = {}
    season_name = semester.get_season_display()
    template_dict["page_name"] = \
      "Workshift for {0} {1}".format(season_name, semester.year)

    today = now().date()
    template_dict["semester_percentage"] = int(
        (today - semester.start_date).days /
        (semester.end_date - semester.start_date).days * 100
        )

    template_dict["profile"] = profile

    # We want a form for verification, a notification of upcoming shifts, and a
    # chart displaying the entire house's workshift for the day as well as
    # weekly shifts.
    #
    # The chart should have left and right arrows on the sides to switch the
    # day, with a dropdown menu to select the day from a calendar. Ideally,
    # switching days should use AJAX to appear more seemless to users.

    # Recent History
    day = today
    if "day" in request.GET:
        try:
            day = date(*map(int, request.GET["day"].split("-")))
        except (TypeError, ValueError):
            pass

    template_dict["day"] = day
    if day > semester.start_date:
        template_dict["prev_day"] = (day - timedelta(days=1)).strftime("%Y-%m-%d")
    if day < semester.end_date:
        template_dict["next_day"] = (day + timedelta(days=1)).strftime("%Y-%m-%d")

    if Semester.objects.count() > 1:
        switch_form = SwitchSemesterForm(
			request.POST if "switch_semester" in request.POST else None
		)
        template_dict["switch_form"] = switch_form

        if switch_form.is_valid():
            semester = switch_form.save()
            return HttpResponseRedirect(semester.get_view_url())

    # Forms to interact with workshift
    if profile:
        for form in [VerifyShiftForm, BlownShiftForm, SignInForm, SignOutForm]:
            if form.action_name in request.POST:
                f = form(request.POST, profile=profile)
                if f.is_valid():
                    f.save()
                    return HttpResponseRedirect(
                        semester.get_view_url() +
                        "?day={0}".format(day) if "day" in request.GET else ""
                        )
                else:
                    for error in f.errors.values():
                        messages.add_message(request, messages.ERROR, error)

    # Grab the shifts for just today, as well as week-long shifts
    last_sunday = day - timedelta(days=day.weekday() + 1)
    next_sunday = last_sunday + timedelta(weeks=1)

    day_shifts = WorkshiftInstance.objects.filter(date=day)
    day_shifts = [i for i in day_shifts if not i.week_long]
    week_shifts = WorkshiftInstance.objects.filter(
        date__gt=last_sunday, date__lte=next_sunday,
        )
    week_shifts = [i for i in week_shifts if i.week_long]

    template_dict["day_shifts"] = [(shift, _get_forms(profile, shift))
                                   for shift in day_shifts]
    template_dict["week_shifts"] = [(shift, _get_forms(profile, shift))
                                    for shift in week_shifts]

    return render_to_response("semester.html", template_dict,
                              context_instance=RequestContext(request))

@get_workshift_profile
def semester_info_view(request, semester, profile=None):
    page_name = "{} {}".format(semester.get_season_display(), semester.year)
    pools = WorkshiftPool.objects.filter(semester=semester)
    return render_to_response("semester_info.html", {
        "page_name": page_name,
        "semester": semester,
        "pools": pools,
    }, context_instance=RequestContext(request))

def _get_forms(profile, instance, undo=False, prefix=""):
    """
    Gets the forms for profile interacting with an instance of a shift. This
    includes verify shift, mark shift as blown, sign in, and sign out.
    """
    if not profile:
        return []
    ret = []
    if (not instance.closed or undo) and instance.workshifter:
        workshifter = instance.workshifter or instance.liable
        pool = instance.pool
        managers = Manager.objects.filter(incumbent__user=profile.user)
        verify, blow = False, False

        # The many ways a person can be eligible to verify a shift...
        if instance.verify == AUTO_VERIFY:
            pass
        elif instance.verify == SELF_VERIFY:
            verify = True
        elif instance.verify == OTHER_VERIFY and profile != workshifter:
            verify = True
        elif instance.verify == ANY_MANAGER_VERIFY and managers:
            verify = True
        elif instance.verify == POOL_MANAGER_VERIFY and \
          set(managers).intersections(pool.managers):
          verify = True
        elif instance.verify == WORKSHIFT_MANAGER_VERIFY and \
          any(i.workshift_manager for i in managers):
          verify = True

        if verify and not instance.verifier:
            verify_form = VerifyShiftForm(
                initial={"pk": instance.pk},
                profile=profile,
                prefix=prefix,
                undo=undo,
                )
            ret.append(verify_form)

        if pool.any_blown:
            blow = True

        pool_managers = pool.managers.filter(incumbent__user=profile.user)
        if pool_managers.count():
            blow = True

        if blow and not instance.blown:
            blown_form = BlownShiftForm(
                initial={"pk": instance.pk},
                profile=profile,
                prefix=prefix,
                undo=undo,
                )
            ret.append(blown_form)

    if not instance.closed:
        if not instance.workshifter:
            sign_in_form = SignInForm(
                initial={"pk": instance.pk},
                profile=profile,
                prefix=prefix,
            )
            ret.append(sign_in_form)
        elif instance.workshifter == profile:
            sign_out_form = SignOutForm(
                initial={"pk": instance.pk},
                profile=profile,
                prefix=prefix,
            )
            ret.append(sign_out_form)
    return ret

def _is_preferred(instance, profile):
    """
    Check if a user has marked an instance's workshift type as preferred.
    """
    if not instance.weekly_workshift:
        return False
    if profile and profile.ratings.filter(
        workshift_type=instance.weekly_workshift.workshift_type,
        rating=WorkshiftRating.LIKE,
        ).count() == 0:
        return False
    return True

@get_workshift_profile
def open_shifts_view(request, semester, profile=None):
    page_name = "Upcoming Open Shifts"
    shifts = WorkshiftInstance.objects.filter(closed=False).order_by("-date")
    shift_count = shifts.count()
    paginator = Paginator(shifts, 250)

    page = request.GET.get("page")
    try:
        shifts = paginator.page(page)
    except PageNotAnInteger:
        shifts = paginator.page(1)
    except EmptyPage:
        shifts = paginator.page(paginator.num_pages)
    shift_tuples = [
        (instance, _get_forms(profile, instance), _is_preferred(instance, profile))
        for instance in shifts
    ]
    return render_to_response("open_shifts.html", {
        "page_name": page_name,
        "shifts": shifts,
        "shift_count": shift_count,
        "shift_tuples": shift_tuples,
    }, context_instance=RequestContext(request))

@workshift_manager_required
@get_workshift_profile
def edit_profile_view(request, semester, targetUsername, profile=None):
    wprofile = get_object_or_404(
        WorkshiftProfile,
        user__username=targetUsername,
        semester=semester
        )
    note_form = ProfileNoteForm(
        request.POST or None,
        instance=wprofile,
        prefix="note",
        )
    pool_hours = wprofile.pool_hours.all()
    pools_forms = []
    for hours in pool_hours:
        form = WorkshiftPoolHoursForm(
            request.POST or None,
            instance=hours,
            prefix="pool-{0}".format(hours.pk),
            )
        pools_forms.append(form)
    if (note_form is None or note_form.is_valid()) and \
       all(i.is_valid() for i in pools_forms):
        if note_form:
            note_form.save()
        for form in pools_forms:
            form.save()
        return HttpResponseRedirect(wprofile.get_view_url())
    page_name = "Edit {}'s Profile".format(wprofile.user.get_full_name())
    return render_to_response("edit_profile.html", {
        "page_name": page_name,
        "note_form": note_form,
        "pools_tuples": zip(pool_hours, pools_forms),
    }, context_instance=RequestContext(request))

@get_workshift_profile
def profile_view(request, semester, targetUsername, profile=None):
    """
    Show the user their workshift history for the current semester as well as
    upcoming shifts.
    """
    wprofile = get_object_or_404(
        WorkshiftProfile,
        user__username=targetUsername,
        semester=semester
        )
    if wprofile == profile:
        page_name = "My Workshift Profile"
    else:
        page_name = "{0}'s Workshift Profile".format(wprofile.user.get_full_name())
    past_shifts = WorkshiftInstance.objects.filter(workshifter=wprofile, closed=True)
    regular_shifts = RegularWorkshift.objects.filter(
        active=True, current_assignees=wprofile,
    )
    assigned_instances = WorkshiftInstance.objects.filter(
        closed=False, workshifter=wprofile,
    ).exclude(
        weekly_workshift__current_assignees=wprofile,
    )
    first_standing, second_standing, third_standing = \
      any(pool_hours.first_date_standing for pool_hours in wprofile.pool_hours.all()), \
      any(pool_hours.second_date_standing for pool_hours in wprofile.pool_hours.all()), \
      any(pool_hours.third_date_standing for pool_hours in wprofile.pool_hours.all())
    view_note = wprofile == profile or utils.can_manage(request.user, semester=semester)
    return render_to_response("profile.html", {
        "page_name": page_name,
        "profile": wprofile,
        "view_note": view_note,
        "past_shifts": past_shifts,
        "regular_shifts": regular_shifts,
        "assigned_instances": assigned_instances,
        "first_standing": first_standing,
        "second_standing": second_standing,
        "third_standing": third_standing,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def preferences_view(request, semester, targetUsername, profile=None):
    """
    Show the user their preferences for the given semester.
    """
    # TODO: Change template to show descriptions in tooltip / ajax show box?
    wprofile = get_object_or_404(WorkshiftProfile, user__username=targetUsername)

    if wprofile.user != request.user and \
      not utils.can_manage(request.user, semester=semester):
        messages.add_message(request, messages.ERROR,
                             MESSAGES["ADMINS_ONLY"])
        return HttpResponseRedirect(semester.get_view_url())

    rating_forms = []
    for wtype in WorkshiftType.objects.filter(rateable=True):
        try:
            rating = wprofile.ratings.get(workshift_type=wtype)
        except WorkshiftRating.DoesNotExist:
            rating = WorkshiftRating(workshift_type=wtype)
        form = WorkshiftRatingForm(
            request.POST or None,
            prefix="rating-{0}".format(wtype.pk),
            instance=rating,
            profile=wprofile,
        )
        rating_forms.append(form)

    time_formset = TimeBlockFormSet(
        request.POST or None,
        prefix="time",
        profile=wprofile,
    )
    note_form = ProfileNoteForm(
        request.POST or None,
        instance=wprofile,
        prefix="note",
    )

    if all(i.is_valid() for i in rating_forms) and time_formset.is_valid() and \
      note_form.is_valid():
        for form in rating_forms:
            form.save()
        time_formset.save()
        instance = note_form.save()
        if wprofile.preference_save_time is None:
            wprofile.preference_save_time = now()
            wprofile.save()
        messages.add_message(request, messages.INFO, "Preferences saved.")
        return HttpResponseRedirect(wurl("workshift:preferences",
                                         sem_url=semester.sem_url,
                                         targetUsername=request.user.username))

    if wprofile == profile:
        page_name = "My Workshift Preferences"
    else:
        page_name = "{0}'s Workshift Preferences".format(
            wprofile.user.get_full_name(),
        )
    return render_to_response("preferences.html", {
        "page_name": page_name,
        "profile": wprofile,
        "rating_forms": rating_forms,
        "time_formset": time_formset,
        "note_form": note_form,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def profiles_view(request, semester, profile=None):
    page_name = "Workshift Profiles"
    wprofiles = WorkshiftProfile.objects.filter(semester=semester)
    pools = WorkshiftPool.objects.filter(semester=semester)
    pool_hours = [
        [wprofile.pool_hours.get(pool=pool) for pool in pools]
        for wprofile in wprofiles
    ]
    return render_to_response("profiles.html", {
        "page_name": page_name,
        "workshifter_tuples": zip(wprofiles, pool_hours),
        "pools": pools,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def manage_view(request, semester, profile=None):
    """
    View all members' preferences. This view also includes forms to create an
    entire semester's worth of weekly workshifts.
    """
    page_name = "Manage Workshift"
    pools = WorkshiftPool.objects.filter(semester=semester)
    full_management = utils.can_manage(request.user, semester=semester)
    edit_semester_form = None
    close_semester_form = None
    open_semester_form = None

    if not full_management:
        pools = pools.filter(managers__incumbent__user=request.user)
        if not pools.count():
            messages.add_message(request, messages.ERROR,
                                 MESSAGES["ADMINS_ONLY"])
            return HttpResponseRedirect(semester.get_view_url())
    else:
        edit_semester_form = FullSemesterForm(
            request.POST if "edit_semester" in request.POST else None,
            instance=semester,
            )
        if semester.current:
            close_semester_form = CloseSemesterForm(
                request.POST if "close_semester" in request.POST else None,
                semester=semester,
                )
        else:
            open_semester_form = OpenSemesterForm(
                request.POST if "open_semester" in request.POST else None,
                semester=semester
                )


    if edit_semester_form and edit_semester_form.is_valid():
        semester = edit_semester_form.save()
        messages.add_message(request, messages.INFO, "Semester successfully updated.")
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))

    if close_semester_form and close_semester_form.is_valid():
        close_semester_form.save()
        messages.add_message(request, messages.INFO, "Semester closed.")
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))

    if open_semester_form and open_semester_form.is_valid():
        open_semester_form.save()
        messages.add_message(request, messages.INFO, "Semester reopened.")
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))

    pools = pools.order_by("-is_primary", "title")
    workshifters = WorkshiftProfile.objects.filter(semester=semester)
    pool_hours = [workshifter.pool_hours.filter(pool__in=pools)
                  .order_by("-pool__is_primary", "pool__title")
                  for workshifter in workshifters]

    return render_to_response("manage.html", {
        "page_name": page_name,
        "pools": pools,
        "full_management": full_management,
        "edit_semester_form": edit_semester_form,
        "close_semester_form": close_semester_form,
        "open_semester_form": open_semester_form,
        "workshifters": zip(workshifters, pool_hours),
    }, context_instance=RequestContext(request))

@semester_required
@workshift_manager_required
def assign_shifts_view(request, semester):
    """
    View all members' preferences. This view also includes forms to create an
    entire semester's worth of weekly workshifts.
    """
    page_name = "Assign Shifts"

    auto_assign_shifts_form = None
    random_assign_instances_form = None
    clear_assign_form = None

    if WorkshiftPool.objects.filter(semester=semester).count():
        auto_assign_shifts_form = AutoAssignShiftForm(
            request.POST if AutoAssignShiftForm.name in request.POST else None,
            semester=semester,
            )
        random_assign_instances_form = RandomAssignInstancesForm(
            request.POST if RandomAssignInstancesForm.name in request.POST else None,
            semester=semester,
            )
        clear_assign_form = ClearAssignmentsForm(
            request.POST if ClearAssignmentsForm.name in request.POST else None,
            semester=semester,
            )

    forms = [auto_assign_shifts_form, random_assign_instances_form,
             clear_assign_form]

    if auto_assign_shifts_form and auto_assign_shifts_form.is_valid():
        unassigned_profiles = auto_assign_shifts_form.save()
        message = "Assigned workshifters to regular workshifts."
        if unassigned_profiles:
            message += " The following workshifters were not given " \
              "complete assignments: "
            message += ", ".join(i.user.get_full_name() for i in unassigned_profiles)
        messages.add_message(request, messages.INFO, message)
        return HttpResponseRedirect(wurl("workshift:assign_shifts",
                                         sem_url=semester.sem_url))

    if random_assign_instances_form and random_assign_instances_form.is_valid():
        unassigned_profiles, unassigned_shifts = \
          random_assign_instances_form.save()
        message = "Assigned workshifters randomly to instances within {0}." \
          .format(random_assign_instances_form.cleaned_data["pool"])
        if unassigned_profiles:
            message += "The following workshifers were not given " \
              "complete assignments: "
            message += ", ".join(i.user.get_full_name() for i in unassigned_profiles)
        messages.add_message(request, messages.INFO, message)
        return HttpResponseRedirect(wurl("workshift:assign_shifts",
                                         sem_url=semester.sem_url))

    if clear_assign_form and clear_assign_form.is_valid():
        clear_assign_form.save()
        message = "Cleared all workshifters from their regular workshift " \
          "assignments"
        messages.add_message(request, messages.INFO, message)
        return HttpResponseRedirect(wurl("workshift:assign_shifts",
                                         sem_url=semester.sem_url))

    shifts = RegularWorkshift.objects.filter(
        pool__semester=semester,
        active=True,
        ).exclude(
            workshift_type__assignment=WorkshiftType.NO_ASSIGN,
            )

    assign_forms = []
    for shift in shifts:
        form = AssignShiftForm(
            request.POST if "individual_assign" in request.POST else None,
            prefix="shift-{0}".format(shift.pk),
            instance=shift,
            semester=semester,
            )
        assign_forms.append(form)

    if assign_forms and all(i.is_valid() for i in assign_forms):
        for form in assign_forms:
            form.save()
        messages.add_message(request, messages.INFO, "Workshift assignments saved.")
        return HttpResponseRedirect(wurl("workshift:assign_shifts",
                                         sem_url=semester.sem_url))

    workshifters = WorkshiftProfile.objects.filter(semester=semester)
    pool_hours = []
    for workshifter in workshifters:
        hours_owed = [
            pool.hours - pool.assigned_hours
            for pool in workshifter.pool_hours.all().order_by("-pool__is_primary", "pool__title")
        ]

        if any(i > 0 for i in hours_owed):
            pool_hours.append(hours_owed)

    total_pool_hours = [
        sum(pools[i] for pools in pool_hours)
        for i in range(len(pool_hours[0]) if len(pool_hours) > 0 else 0)
    ]

    pools = WorkshiftPool.objects.filter(semester=semester).order_by("-is_primary", "title")
    unassigned_shifts = []
    for pool in pools:
        shifts = RegularWorkshift.objects.filter(pool=pool)
        filtered_shifts, shift_hours = [], []
        for shift in shifts:
            if shift.current_assignees.count() < shift.count:
                filtered_shifts.append(shift)
                shift_hours.append(
                    shift.hours * shift.count - shift.current_assignees.count()
                )

        total_shift_hours = sum(shift_hours)

        if total_shift_hours > 0:
            unassigned_shifts.append((
                pool,
                zip(filtered_shifts, shift_hours),
                total_shift_hours,
            ))

    return render_to_response("assign_shifts.html", {
        "page_name": page_name,
        "forms": forms,
        "assign_forms": assign_forms,
        "unassigned_profiles": zip(workshifters, pool_hours),
        "pools": pools,
        "total_pool_hours": total_pool_hours,
        "unassigned_shifts": unassigned_shifts,
    }, context_instance=RequestContext(request))

@semester_required
@workshift_manager_required
def adjust_hours_view(request, semester):
    """
    Adjust members' workshift hours requirements.
    """
    page_name = "Adjust Hours"

    pools = WorkshiftPool.objects.filter(semester=semester).order_by("-is_primary", "title")
    workshifters = WorkshiftProfile.objects.filter(semester=semester)
    pool_hour_forms = [
        [
            AdjustHoursForm(
                request.POST if request.POST else None,
                prefix="pool_hours-{}".format(hours.pk),
                instance=hours,
            )
            for hours in workshifter.pool_hours.order_by("-pool__is_primary", "pool__title")
        ]
        for workshifter in workshifters
    ]

    if all(
            form.is_valid()
            for workshifter_forms in pool_hour_forms
            for form in workshifter_forms
    ):
        for workshifter_forms in pool_hour_forms:
            for form in workshifter_forms:
                form.save()
        messages.add_message(request, messages.INFO, "Updated hours.")
        return HttpResponseRedirect(wurl("workshift:adjust_hours",
                                         sem_url=semester.sem_url))

    return render_to_response("adjust_hours.html", {
        "page_name": page_name,
        "pools": pools,
        "workshifters_tuples": zip(workshifters, pool_hour_forms),
    }, context_instance=RequestContext(request))

@semester_required
@workshift_manager_required
def add_workshifter_view(request, semester):
    """
    Add a new member workshift profile, for people who join mid-semester.
    """
    page_name = "Add Workshifter"

    existing = [
        i.user.pk for i in WorkshiftProfile.objects.filter(semester=semester)
        ]
    users = User.objects.exclude(pk__in=existing).exclude(is_active=False) \
      .exclude(userprofile__status=UserProfile.ALUMNUS)

    add_workshifter_forms = []
    for user in users:
        form = AddWorkshifterForm(
            request.POST or None,
            prefix="user-{0}".format(user.pk),
            user=user,
            semester=semester,
            )
        add_workshifter_forms.append(form)

    if add_workshifter_forms and \
      all(form.is_valid() for form in add_workshifter_forms):
        for form in add_workshifter_forms:
            form.save()
        messages.add_message(request, messages.INFO, "Workshifters added.")
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))

    return render_to_response("add_workshifter.html", {
        "page_name": page_name,
        "add_workshifter_forms": add_workshifter_forms,
    }, context_instance=RequestContext(request))

@semester_required
@workshift_manager_required
def add_pool_view(request, semester):
    """
    View for the workshift manager to create new workshift pools (i.e. HI Hours).
    """
    page_name = "Add Workshift Pool"
    add_pool_form = PoolForm(
        request.POST or None,
        semester=semester,
        full_management=True,
        )
    if add_pool_form.is_valid():
        add_pool_form.save()
        messages.add_message(request, messages.INFO, "Workshift pool added.")
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))
    return render_to_response("add_pool.html", {
        "page_name": page_name,
        "add_pool_form": add_pool_form,
        }, context_instance=RequestContext(request))

@semester_required
@workshift_manager_required
def fill_shifts_view(request, semester):
    """
    Allows managers to quickly fill in the default workshifts for a few given
    workshift pools.
    """
    page_name = "Fill Shifts"

    fill_regular_shifts_form = None
    fill_social_shifts_form = None
    fill_humor_shifts_form = None
    fill_bathroom_shifts_form = None
    fill_hi_shifts_form = None
    reset_all_shifts_form = None

    managers = Manager.objects.filter(incumbent__user=request.user)
    admin = utils.can_manage(request.user, semester=semester)

    if admin:
        fill_regular_shifts_form = FillRegularShiftsForm(
            request.POST,
            semester=semester,
        )
        fill_humor_shifts_form = FillHumorShiftsForm(
            request.POST,
            semester=semester,
        )
        fill_bathroom_shifts_form = FillBathroomShiftsForm(
            request.POST,
            semester=semester,
        )
        reset_all_shifts_form = ResetAllShiftsForm(
            request.POST,
            semester=semester,
        )
    # XXX: BAD! We should filter by pool owners? By Manager bool flags? By
    # arbitrary django permissions?
    if admin or managers.filter(title="Social Manager"):
        fill_social_shifts_form = FillSocialShiftsForm(
            request.POST,
            semester=semester,
        )
    # XXX: See above
    if admin or managers.filter(title="Maintenance Manager"):
        fill_hi_shifts_form = FillHIShiftsForm(
            request.POST,
            semester=semester,
        )

    fill_forms = [
        fill_regular_shifts_form, fill_social_shifts_form,
        fill_humor_shifts_form, fill_bathroom_shifts_form,
        fill_hi_shifts_form, reset_all_shifts_form,
    ]
    fill_forms = [i for i in fill_forms if i is not None]

    for form in fill_forms:
        if form and form.is_valid():
            count = form.save()
            message = "{} {} {}".format(
                form.message, count, p.plural("workshift", count),
            )
            messages.add_message(request, messages.INFO, message)
            return HttpResponseRedirect(wurl("workshift:fill_shifts",
                                             sem_url=semester.sem_url))

    return render_to_response("fill_shifts.html", {
        "page_name": page_name,
        "forms": fill_forms,
    }, context_instance=RequestContext(request))

@semester_required
@workshift_manager_required
def add_shift_view(request, semester):
    """
    View for the workshift manager to create new types of workshifts.
    """
    page_name = "Add Workshift"
    pools = WorkshiftPool.objects.filter(semester=semester)
    full_management = utils.can_manage(request.user, semester=semester)
    if not full_management:
        pools = pools.filter(managers__incumbent__user=request.user)
        if not pools.count():
            messages.add_message(request, messages.ERROR,
                                 MESSAGES["ADMINS_ONLY"])
            return HttpResponseRedirect(semester.get_view_url())

    if full_management:
        add_type_form = WorkshiftTypeForm(
            request.POST if "add_type" in request.POST else None,
            prefix="type",
            )
        shifts_formset = RegularWorkshiftFormSet(
            request.POST if "add_type" in request.POST else None,
            prefix="shifts",
            queryset=RegularWorkshift.objects.none(),
            pools=pools,
            )

        if add_type_form.is_valid() and shifts_formset.is_valid():
            wtype = add_type_form.save()
            shifts_formset.save(workshift_type=wtype)
            return HttpResponseRedirect(wurl("workshift:manage",
                                             sem_url=semester.sem_url))
    else:
        add_type_form = None
        shifts_formset = None

    add_instance_form = WorkshiftInstanceForm(
        request.POST if "add_instance" in request.POST else None,
        pools=pools,
        semester=semester,
        )
    if add_instance_form.is_valid():
        add_instance_form.save()
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))
    return render_to_response("add_shift.html", {
        "page_name": page_name,
        "add_type_form": add_type_form,
        "shifts_formset": shifts_formset,
        "add_instance_form": add_instance_form,
    }, context_instance=RequestContext(request))

@semester_required
@workshift_manager_required
def fine_date_view(request, semester, profile=None):
    page_name = "Calculate Workshift Fines"

    fine_form = FineDateForm(
        request.POST or None,
        semester=semester,
        )
    if fine_form.is_valid():
        fined_members = fine_form.save(clear="clear" in request.POST)
        messages.add_message(
            request, messages.INFO,
            "Calculated workshift fines, {0} members will be fined."
            .format(len(fined_members)),
        )
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))

    pools = WorkshiftPool.objects.filter(semester=semester)
    pools = pools.order_by("-is_primary", "title")
    workshifters = WorkshiftProfile.objects.filter(semester=semester)
    pool_hours = [workshifter.pool_hours.filter(pool__in=pools)
                  .order_by("-pool__is_primary", "pool__title")
                  for workshifter in workshifters]

    return render_to_response("fine_date.html", {
        "page_name": page_name,
        "fine_form": fine_form,
        "pools": pools,
        "workshifters": zip(workshifters, pool_hours),
    }, context_instance=RequestContext(request))

@get_workshift_profile
def pool_view(request, semester, pk, profile=None):
    pool = get_object_or_404(WorkshiftPool, semester=semester, pk=pk)
    if profile:
        if SignInForm.action_name in request.POST:
            f = SignInForm(request.POST, profile=profile)
            if f.is_valid():
                f.save()
                return HttpResponseRedirect(pool.get_view_url())
            else:
                for error in f.errors.values():
                    messages.add_message(request, messages.ERROR, error)
        upcoming_pool_shifts = _pool_upcoming_vacant_shifts(pool, profile)
    else:
        upcoming_pool_shifts = None
    page_name = "{0} Pool".format(pool.title)
    shifts = RegularWorkshift.objects.filter(pool=pool, active=True)

    return render_to_response("view_pool.html", {
        "page_name": page_name,
        "pool": pool,
        "shifts": shifts,
        "upcoming_pool_shifts": upcoming_pool_shifts,
    }, context_instance=RequestContext(request))

@workshift_manager_required
@get_workshift_profile
def edit_pool_view(request, semester, pk, profile=None):
    pool = get_object_or_404(WorkshiftPool, semester=semester, pk=pk)
    page_name = "Edit " + pool.title
    full_management = utils.can_manage(request.user, semester=semester)
    managers = pool.managers.filter(incumbent__user=request.user)

    if not full_management and managers.count() == 0:
        messages.add_message(request, messages.ERROR,
                             MESSAGES["ADMINS_ONLY"])
        return HttpResponseRedirect(semester.get_view_url())

    # TODO: Link auto-verify / auto-blown / etc to pool view?

    edit_pool_form = PoolForm(
        request.POST or None,
        instance=pool,
        full_management=full_management,
        )
    if "delete" in request.POST:
        pool.delete()
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))
    if edit_pool_form.is_valid():
        edit_pool_form.save()
        messages.add_message(request, messages.INFO,
                             "Workshift pool successfully updated.")
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))

    return render_to_response("edit_pool.html", {
        "page_name": page_name,
        "edit_pool_form": edit_pool_form,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def shift_view(request, semester, pk, profile=None):
    """
    View the details of a particular RegularWorkshift.
    """
    shift = get_object_or_404(RegularWorkshift, pk=pk)
    page_name = shift.workshift_type.title

    president = Manager.objects.filter(incumbent__user=request.user, president=True) \
                .count() > 0
    can_edit = request.user.is_superuser or president

    instances = WorkshiftInstance.objects.filter(
        closed=False,
        weekly_workshift=shift,
    )
    instance_tuples = [
        (instance, _get_forms(profile, instance))
        for instance in instances
    ]

    return render_to_response("view_shift.html", {
        "page_name": page_name,
        "shift": shift,
        "instance_tuples": instance_tuples,
        "can_edit": can_edit,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def edit_shift_view(request, semester, pk, profile=None):
    """
    View for a manager to edit the details of a particular RegularWorkshift.
    """
    shift = get_object_or_404(RegularWorkshift, pk=pk)
    managers = shift.pool.managers.filter(incumbent__user=request.user)

    if shift.is_manager_shift:
        # XXX: Bad way of doing this, we should make manager_shift point to the related
        # Manager object directly
        try:
            manager = Manager.objects.get(title=shift.workshift_type.title)
        except Manager.DoesNotExist:
            pass
        else:
            return HttpResponseRedirect(reverse("managers:edit_manager",
                                                kwargs={"managerTitle": manager.url_title}))

    if not utils.can_manage(request.user, semester=semester) and managers.count() == 0:
        messages.add_message(request, messages.ERROR,
                             MESSAGES["ADMINS_ONLY"])
        return HttpResponseRedirect(semester.get_view_url())

    edit_form = RegularWorkshiftForm(
        request.POST if "edit" in request.POST else None,
        instance=shift,
        semester=semester,
    )

    if "delete" in request.POST:
        # Open instances are deleted automatically
        shift.delete()
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))
    elif edit_form.is_valid():
        shift = edit_form.save()
        return HttpResponseRedirect(shift.get_view_url())

    page_name = "Edit {0}".format(shift)

    return render_to_response("edit_shift.html", {
        "page_name": page_name,
        "shift": shift,
        "edit_form": edit_form,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def instance_view(request, semester, pk, profile=None):
    """
    View the details of a particular WorkshiftInstance.
    """
    instance = get_object_or_404(WorkshiftInstance, pk=pk)
    page_name = instance.title
    interact_forms = _get_forms(
        profile, instance,
        undo=utils.can_manage(request.user, semester),
        prefix="interact",
    )

    note_form = NoteForm(
        request.POST or None,
        prefix="note",
        )

    for form in [VerifyShiftForm, BlownShiftForm, SignInForm, SignOutForm]:
        if form.action_name in request.POST:
            f = form(
                request.POST or None,
                profile=profile,
                prefix="interact",
                undo=utils.can_manage(request.user, semester),
            )
            if f.is_valid() and note_form.is_valid():
                note = note_form.save()
                instance = f.save(note=note)
                return HttpResponseRedirect(instance.get_view_url())
            else:
                for error in f.errors.values():
                    messages.add_message(request, messages.ERROR, error)

    edit_hours_form = None
    if utils.can_manage(request.user, semester=instance.pool.semester) or \
      instance.pool.managers.filter(incumbent__user=request.user):
        edit_hours_form = EditHoursForm(
            request.POST if "edit_hours" in request.POST else None,
            instance=instance,
            profile=profile,
            )
        if edit_hours_form.is_valid():
            edit_hours_form.save()
            messages.add_message(request, messages.INFO, "Updated instance's hours.")
            return HttpResponseRedirect(instance.get_view_url())

    return render_to_response("view_instance.html", {
        "page_name": page_name,
        "instance": instance,
        "interact_forms": interact_forms,
        "note_form": note_form,
        "edit_hours_form": edit_hours_form,
    }, context_instance=RequestContext(request))

@get_workshift_profile
def edit_instance_view(request, semester, pk, profile=None):
    """
    View for a manager to edit the details of a particular WorkshiftInstance.
    """
    instance = get_object_or_404(WorkshiftInstance, pk=pk)
    managers = instance.pool.managers.filter(incumbent__user=request.user)

    if not utils.can_manage(request.user, semester=semester) and managers.count() == 0:
        messages.add_message(request, messages.ERROR,
                             MESSAGES["ADMINS_ONLY"])
        return HttpResponseRedirect(semester.get_view_url())

    page_name = "Edit " + instance.title

    edit_form = WorkshiftInstanceForm(
        request.POST if "edit" in request.POST else None,
        instance=instance,
        semester=semester,
        edit_hours=False,
        )

    if "delete" in request.POST:
        instance.delete()
        return HttpResponseRedirect(wurl("workshift:manage",
                                         sem_url=semester.sem_url))
    elif edit_form.is_valid():
        instance = edit_form.save()
        return HttpResponseRedirect(instance.get_view_url())

    return render_to_response("edit_instance.html", {
        "page_name": page_name,
        "instance": instance,
        "edit_form": edit_form,
    }, context_instance=RequestContext(request))

@login_required
def list_types_view(request):
    """
    View the details of a particular WorkshiftType.
    """
    page_name = "Workshift Types"
    types = WorkshiftType.objects.all()
    shifts = [
        RegularWorkshift.objects.filter(workshift_type=i, pool__semester__current=True)
        for i in types
    ]
    return render_to_response("list_types.html", {
        "page_name": page_name,
        "type_tuples": zip(types, shifts),
        "can_edit": utils.can_manage(request.user),
    }, context_instance=RequestContext(request))

@login_required
def type_view(request, pk):
    """
    View the details of a particular WorkshiftType.
    """
    wtype = get_object_or_404(WorkshiftType, pk=pk)
    page_name = wtype.title
    regular_shifts = RegularWorkshift.objects.filter(
        workshift_type=wtype, pool__semester__current=True,
        )
    return render_to_response("view_type.html", {
        "page_name": page_name,
        "wtype": wtype,
        "regular_shifts": regular_shifts,
        "can_edit": utils.can_manage(request.user),
    }, context_instance=RequestContext(request))

@workshift_manager_required
def edit_type_view(request, pk):
    """
    View for a manager to edit the details of a particular WorkshiftType.
    """
    wtype = get_object_or_404(WorkshiftType, pk=pk)

    if "delete" in request.POST:
        pass

    edit_form = WorkshiftTypeForm(
        request.POST if "edit" in request.POST else None,
        instance=wtype,
        prefix="edit",
        )

    shifts_formset = RegularWorkshiftFormSet(
        request.POST if "edit" in request.POST else None,
        prefix="shifts",
        queryset=RegularWorkshift.objects.filter(
            workshift_type=wtype,
            ),
        )

    if edit_form.is_valid() and shifts_formset.is_valid():
        wtype = edit_form.save()
        shifts_formset.save(wtype)
        return HttpResponseRedirect(wtype.get_view_url())

    page_name = "Edit {0}".format(wtype.title)

    return render_to_response("edit_type.html", {
        "page_name": page_name,
        "shift": wtype,
        "edit_form": edit_form,
        "shifts_formset": shifts_formset,
    }, context_instance=RequestContext(request))
