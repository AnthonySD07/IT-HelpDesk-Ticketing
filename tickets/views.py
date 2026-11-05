from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Avg, F, Q, ExpressionWrapper, DurationField
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from .forms import RegisterForm, TicketForm, CommentForm, AssignForm
from .models import Ticket, User

CLOSED_STATUSES = ['resolved', 'closed']
FLOW = [('open', 'Open'), ('assigned', 'Assigned'), ('in_progress', 'In progress'),
        ('resolved', 'Resolved'), ('closed', 'Closed')]


def is_admin(user):
    return user.role == 'admin' or user.is_superuser


def visible_tickets(user):
    """Role-based access: each role only sees what it should."""
    if is_admin(user):
        return Ticket.objects.all()
    if user.role == 'technician':
        return Ticket.objects.filter(assigned_to=user)
    return Ticket.objects.filter(created_by=user)


def progress_steps(ticket):
    current = 'in_progress' if ticket.status == 'waiting' else ticket.status
    keys = [k for k, _ in FLOW]
    index = keys.index(current)
    steps = []
    for i, (key, label) in enumerate(FLOW):
        state = 'done' if i < index else 'current' if i == index else 'todo'
        if key == 'closed' and ticket.status == 'closed':
            state = 'done'
        if key == 'in_progress' and ticket.status == 'waiting':
            label = 'Waiting on user'
        steps.append({'label': label, 'state': state})
    return steps


def with_percent(items, key):
    biggest = max([i[key] for i in items], default=0)
    for i in items:
        i['pct'] = round(i[key] * 100 / biggest) if biggest else 0
    return items


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
    base = visible_tickets(request.user)
    active = base.exclude(status__in=CLOSED_STATUSES)
    stats = {
        'total': base.count(),
        'open': active.count(),
        'overdue': active.filter(due_at__lt=timezone.now()).count(),
        'resolved': base.filter(status__in=CLOSED_STATUSES).count(),
    }
    tickets = base.select_related('category', 'created_by', 'assigned_to').order_by('-created_at')
    status = request.GET.get('status', '')
    q = request.GET.get('q', '').strip()
    if status:
        tickets = tickets.filter(status=status)
    if q:
        tickets = tickets.filter(title__icontains=q)
    if is_admin(request.user):
        list_title = 'All tickets'
    elif request.user.role == 'technician':
        list_title = 'Assigned to me'
    else:
        list_title = 'My tickets'
    return render(request, 'tickets/ticket_list.html', {
        'tickets': tickets,
        'stats': stats,
        'list_title': list_title,
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
    ticket = get_object_or_404(visible_tickets(request.user), pk=pk)
    form = CommentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        comment = form.save(commit=False)
        comment.ticket = ticket
        comment.author = request.user
        comment.save()
        messages.success(request, 'Comment added.')
        return redirect('ticket_detail', pk=ticket.pk)

    labels = dict(Ticket.STATUS_CHOICES)
    next_statuses = [(s, labels[s]) for s in ticket.next_statuses(request.user)]
    can_assign = is_admin(request.user) and ticket.status not in ('resolved', 'closed')
    return render(request, 'tickets/ticket_detail.html', {
        'ticket': ticket,
        'form': form,
        'steps': progress_steps(ticket),
        'comments': ticket.comments.select_related('author').order_by('created_at'),
        'history': ticket.history.select_related('changed_by').order_by('-changed_at'),
        'next_statuses': next_statuses,
        'assign_form': AssignForm() if can_assign else None,
    })


@login_required
def ticket_assign(request, pk):
    if not is_admin(request.user):
        raise PermissionDenied
    ticket = get_object_or_404(Ticket, pk=pk)
    if request.method == 'POST':
        form = AssignForm(request.POST)
        if ticket.status in ('resolved', 'closed'):
            messages.error(request, 'This ticket is already resolved.')
        elif form.is_valid():
            ticket.assign(form.cleaned_data['technician'], request.user)
            messages.success(request, f"Assigned to {form.cleaned_data['technician']}.")
        else:
            messages.error(request, 'Choose a technician.')
    return redirect('ticket_detail', pk=pk)


@login_required
def ticket_status(request, pk):
    ticket = get_object_or_404(visible_tickets(request.user), pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in ticket.next_statuses(request.user):
            ticket.change_status(new_status, request.user)
            messages.success(request, f'Status changed to {ticket.get_status_display()}.')
        else:
            messages.error(request, 'That status change is not allowed.')
    return redirect('ticket_detail', pk=pk)


@login_required
def reports(request):
    if not is_admin(request.user):
        raise PermissionDenied

    techs = User.objects.filter(role='technician').annotate(
        open_count=Count('tickets_assigned',
                         filter=~Q(tickets_assigned__status__in=CLOSED_STATUSES))
    ).order_by('-open_count', 'username')
    open_per_tech = with_percent(
        [{'name': t.username, 'count': t.open_count} for t in techs], 'count')

    avg = Ticket.objects.filter(resolved_at__isnull=False).aggregate(
        avg=Avg(ExpressionWrapper(F('resolved_at') - F('created_at'),
                                  output_field=DurationField())))['avg']
    avg_hours = round(avg.total_seconds() / 3600, 1) if avg else None

    categories = Ticket.objects.values('category__name').annotate(
        total=Count('id')).order_by('-total')
    by_category = with_percent(
        [{'name': c['category__name'], 'total': c['total']} for c in categories], 'total')

    active = Ticket.objects.exclude(status__in=CLOSED_STATUSES)
    return render(request, 'tickets/reports.html', {
        'open_per_tech': open_per_tech,
        'avg_hours': avg_hours,
        'by_category': by_category,
        'total_tickets': Ticket.objects.count(),
        'open_tickets': active.count(),
        'overdue_tickets': active.filter(due_at__lt=timezone.now()).count(),
        'unassigned': active.filter(assigned_to__isnull=True).count(),
    })