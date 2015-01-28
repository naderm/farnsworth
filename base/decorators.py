'''
Project: Farnsworth

Author: Karandeep Singh Nagra
'''

from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse

from utils.variables import MESSAGES
from base.redirects import red_home
from base.models import UserProfile
from managers.models import Manager

def profile_required(function=None, redirect_no_user='login', redirect_profile=red_home):
    def real_decorator(view_func):
        def wrap(request, *args, **kwargs):
            ajax_capable = getattr(view_func, 'is_ajax_capable', False)
            if request.is_ajax() and ajax_capable:
                return view_func(request, *args, **kwargs)

            if not request.user.is_authenticated():
                redirect_to = reverse(redirect_no_user)
                if redirect_no_user == "login":
                    redirect_to += "?next=" + request.path
                return HttpResponseRedirect(redirect_to)
            try:
                UserProfile.objects.get(user=request.user)
            except UserProfile.DoesNotExist:
                return redirect_profile(request, MESSAGES['NO_PROFILE'])
            return view_func(request, *args, **kwargs)
        return wrap
    if function:
        return real_decorator(function)
    return real_decorator

def ajax_capable(function=None):
    def real_decorator(view_func):
        function.is_ajax_capable = True
        return function
    if function:
        return real_decorator(function)
    return real_decorator

def admin_required(function=None, redirect_no_user='login', redirect_profile=red_home):
    def real_decorator(view_func):
        def wrap(request, *args, **kwargs):
            if not request.user.is_authenticated():
                redirect_to = reverse(redirect_no_user)
                if redirect_no_user == "login":
                    redirect_to += "?next=" + request.path
                return HttpResponseRedirect(redirect_to)
            try:
                UserProfile.objects.get(user=request.user)
            except UserProfile.DoesNotExist:
                return redirect_profile(request, MESSAGES['NO_PROFILE'])
            if not request.user.is_superuser:
                return redirect_profile(request, MESSAGES['ADMINS_ONLY'])
            return view_func(request, *args, **kwargs)
        return wrap
    if function:
        return real_decorator(function)
    return real_decorator

def president_admin_required(function=None, redirect_no_user='login', redirect_profile=red_home):
    def real_decorator(view_func):
        def wrap(request, *args, **kwargs):
            if not request.user.is_authenticated():
                redirect_to = reverse(redirect_no_user)
                if redirect_no_user == "login":
                    redirect_to += "?next=" + request.path
                return HttpResponseRedirect(redirect_to)
            try:
                UserProfile.objects.get(user=request.user)
            except UserProfile.DoesNotExist:
                return redirect_profile(request, MESSAGES['NO_PROFILE'])
            # whether the user has president privileges
            president = Manager.objects.filter(incumbent__user=request.user, president=True) \
                        .count() > 0
            if (not request.user.is_superuser) and (not president):
                return redirect_profile(request, MESSAGES['PRESIDENTS_ONLY'])
            return view_func(request, *args, **kwargs)
        return wrap
    if function:
        return real_decorator(function)
    return real_decorator
