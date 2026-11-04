from datetime import timedelta
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    ROLE_CHOICES = [
        ('employee', 'Employee'),
        ('technician', 'Technician'),
        ('admin', 'Admin'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')


class Category(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class SLAPolicy(models.Model):
    PRIORITY_CHOICES = [('high', 'High'), ('medium', 'Medium'), ('low', 'Low')]
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, unique=True)
    hours = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.priority}: {self.hours}h"


class Ticket(models.Model):
    PRIORITY_CHOICES = SLAPolicy.PRIORITY_CHOICES
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('assigned', 'Assigned'),
        ('in_progress', 'In Progress'),
        ('waiting', 'Waiting on User'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    ]
    ALLOWED_TRANSITIONS = {
        'open': ['assigned'],
        'assigned': ['in_progress'],
        'in_progress': ['waiting', 'resolved'],
        'waiting': ['in_progress'],
        'resolved': ['closed', 'in_progress'],
        'closed': [],
    }
    DEFAULT_SLA_HOURS = {'high': 4, 'medium': 24, 'low': 72}

    title = models.CharField(max_length=120)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    screenshot = models.ImageField(upload_to='screenshots/', blank=True, null=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name='tickets_created')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='tickets_assigned')
    created_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    def sla_hours(self):
        policy = SLAPolicy.objects.filter(priority=self.priority).first()
        return policy.hours if policy else self.DEFAULT_SLA_HOURS[self.priority]

    def save(self, *args, **kwargs):
        if not self.due_at:
            self.due_at = timezone.now() + timedelta(hours=self.sla_hours())
        super().save(*args, **kwargs)

    def can_move_to(self, new_status):
        return new_status in self.ALLOWED_TRANSITIONS[self.status]

    def next_statuses(self, user):
        """Which statuses this user may move the ticket to."""
        options = self.ALLOWED_TRANSITIONS[self.status]
        if user.role == 'admin' or user.is_superuser:
            return options
        if user.role == 'technician' and self.assigned_to_id == user.id:
            return options
        if self.created_by_id == user.id and self.status in ('resolved', 'waiting'):
            return options
        return []

    def change_status(self, new_status, user):
        if not self.can_move_to(new_status):
            raise ValueError(f'Cannot move from {self.status} to {new_status}.')
        StatusHistory.objects.create(ticket=self, changed_by=user,
                                     old_status=self.status, new_status=new_status)
        self.status = new_status
        if new_status == 'resolved':
            self.resolved_at = timezone.now()
        elif new_status == 'in_progress':
            self.resolved_at = None
        self.save()

    def assign(self, technician, user):
        if technician.role != 'technician':
            raise ValueError('Tickets can only be assigned to technicians.')
        self.assigned_to = technician
        if self.status == 'open':
            self.change_status('assigned', user)  # also saves
        else:
            self.save()

    @property
    def is_overdue(self):
        return self.status not in ('resolved', 'closed') and timezone.now() > self.due_at

    def __str__(self):
        return f"#{self.pk} {self.title}"


class Comment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class StatusHistory(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name='history')
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    old_status = models.CharField(max_length=20, choices=Ticket.STATUS_CHOICES)
    new_status = models.CharField(max_length=20, choices=Ticket.STATUS_CHOICES)
    changed_at = models.DateTimeField(auto_now_add=True)