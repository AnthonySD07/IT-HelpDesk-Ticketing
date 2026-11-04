from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from .forms import RegisterForm, TicketForm, CommentForm
from .models import Ticket


def is_admin(user):
    return user.role == 'admin' or user.is_superuser


def visible_tickets(user):
    """Role-based access: each role only sees what it should."""
    if is_admin(user):
        return Ticket.objects.all()
    if user.role == 'technician':
        return Ticket.objects.filter(assigned_to=user)
    return Ticket.objects.filter(created_by=user)


def register(request):
    if request.user.is_authenticated:
        return redirect('ticket_list')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Account created. Welcome!')
        return redirect('ticket_list')
    return render(request, 'registration/register.html', {'form': form})


@login_required
def ticket_list(request):
    tickets = visible_tickets(request.user).select_related(
        'category', 'created_by', 'assigned_to').order_by('-created_at')
    status = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()
    if status:
        tickets = tickets.filter(status=status)
    if q:
        tickets = tickets.filter(title__icontains=q)
    return render(request, 'tickets/ticket_list.html', {
        'tickets': tickets,
        'status_choices': Ticket.STATUS_CHOICES,
        'current_status': status,
        'q': q,
    })


@login_required
def ticket_create(request):
    if request.user.role == 'technician':
        raise PermissionDenied
    form = TicketForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        ticket = form.save(commit=False)
        ticket.created_by = request.user
        ticket.save()
        messages.success(request, f'Ticket #{ticket.pk} created.')
        return redirect('ticket_detail', pk=ticket.pk)
    return render(request, 'tickets/ticket_form.html', {'form': form})


@login_required
def ticket_detail(request, pk):
    # Tickets the user may not see return 404, so their existence isn't leaked
    ticket = get_object_or_404(visible_tickets(request.user), pk=pk)
    form = CommentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        comment = form.save(commit=False)
        comment.ticket = ticket
        comment.author = request.user
        comment.save()
        messages.success(request, 'Comment added.')
        return redirect('ticket_detail', pk=ticket.pk)
    return render(request, 'tickets/ticket_detail.html', {
        'ticket': ticket,
        'form': form,
        'comments': ticket.comments.select_related('author').order_by('created_at'),
        'history': ticket.history.select_related('changed_by').order_by('-changed_at'),
    })