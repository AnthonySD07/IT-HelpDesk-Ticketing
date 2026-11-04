from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Category, SLAPolicy, Ticket, Comment, StatusHistory

admin.site.register(User, UserAdmin)
UserAdmin.fieldsets += (('Role', {'fields': ('role',)}),)
admin.site.register([Category, SLAPolicy, Ticket, Comment, StatusHistory])