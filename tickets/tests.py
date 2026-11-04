from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User, Category, SLAPolicy, Ticket, StatusHistory


class BaseTestCase(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Hardware')
        self.employee = User.objects.create_user('emp', password='Pass@12345', role='employee')
        self.employee2 = User.objects.create_user('emp2', password='Pass@12345', role='employee')
        self.tech = User.objects.create_user('tech', password='Pass@12345', role='technician')
        self.tech2 = User.objects.create_user('tech2', password='Pass@12345', role='technician')
        self.admin = User.objects.create_user('boss', password='Pass@12345', role='admin')

    def make_ticket(self, user=None, priority='medium', **kwargs):
        return Ticket.objects.create(
            title='Printer is broken', description='It will not print anything.',
            category=self.category, priority=priority,
            created_by=user or self.employee, **kwargs)


class SLATests(BaseTestCase):
    def test_high_priority_due_in_4_hours(self):
        ticket = self.make_ticket(priority='high')
        expected = timezone.now() + timedelta(hours=4)
        self.assertLess(abs((ticket.due_at - expected).total_seconds()), 60)

    def test_low_priority_due_in_72_hours(self):
        ticket = self.make_ticket(priority='low')
        expected = timezone.now() + timedelta(hours=72)
        self.assertLess(abs((ticket.due_at - expected).total_seconds()), 60)

    def test_sla_policy_in_database_overrides_default(self):
        SLAPolicy.objects.create(priority='high', hours=2)
        ticket = self.make_ticket(priority='high')
        expected = timezone.now() + timedelta(hours=2)
        self.assertLess(abs((ticket.due_at - expected).total_seconds()), 60)

    def test_ticket_past_due_is_overdue(self):
        ticket = self.make_ticket(due_at=timezone.now() - timedelta(hours=1))
        self.assertTrue(ticket.is_overdue)

    def test_resolved_ticket_is_never_overdue(self):
        ticket = self.make_ticket(due_at=timezone.now() - timedelta(hours=1), status='resolved')
        self.assertFalse(ticket.is_overdue)


class WorkflowTests(BaseTestCase):
    def test_valid_transition_is_allowed(self):
        ticket = self.make_ticket()
        self.assertTrue(ticket.can_move_to('assigned'))

    def test_invalid_transition_is_rejected(self):
        ticket = self.make_ticket()
        self.assertFalse(ticket.can_move_to('resolved'))
        with self.assertRaises(ValueError):
            ticket.change_status('resolved', self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'open')

    def test_status_change_is_recorded_in_history(self):
        ticket = self.make_ticket()
        ticket.change_status('assigned', self.admin)
        entry = StatusHistory.objects.get(ticket=ticket)
        self.assertEqual((entry.old_status, entry.new_status), ('open', 'assigned'))
        self.assertEqual(entry.changed_by, self.admin)

    def test_resolving_sets_resolved_at(self):
        ticket = self.make_ticket(status='in_progress')
        ticket.change_status('resolved', self.tech)
        self.assertIsNotNone(ticket.resolved_at)

    def test_assigning_open_ticket_moves_it_to_assigned(self):
        ticket = self.make_ticket()
        ticket.assign(self.tech, self.admin)
        ticket.refresh_from_db()
        self.assertEqual(ticket.assigned_to, self.tech)
        self.assertEqual(ticket.status, 'assigned')

    def test_cannot_assign_to_non_technician(self):
        ticket = self.make_ticket()
        with self.assertRaises(ValueError):
            ticket.assign(self.employee2, self.admin)

    def test_status_options_depend_on_role(self):
        ticket = self.make_ticket(status='in_progress', assigned_to=self.tech)
        self.assertEqual(ticket.next_statuses(self.employee), [])
        self.assertEqual(ticket.next_statuses(self.tech2), [])
        self.assertIn('resolved', ticket.next_statuses(self.tech))
        self.assertIn('resolved', ticket.next_statuses(self.admin))


class AccessControlTests(BaseTestCase):
    def test_login_required_for_ticket_list(self):
        response = self.client.get(reverse('ticket_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_employee_only_sees_own_tickets(self):
        mine = self.make_ticket(self.employee)
        theirs = self.make_ticket(self.employee2)
        self.client.force_login(self.employee)
        response = self.client.get(reverse('ticket_list'))
        self.assertIn(mine, response.context['tickets'])
        self.assertNotIn(theirs, response.context['tickets'])

    def test_technician_only_sees_assigned_tickets(self):
        assigned = self.make_ticket(assigned_to=self.tech)
        other = self.make_ticket()
        self.client.force_login(self.tech)
        response = self.client.get(reverse('ticket_list'))
        self.assertIn(assigned, response.context['tickets'])
        self.assertNotIn(other, response.context['tickets'])

    def test_employee_cannot_open_someone_elses_ticket(self):
        ticket = self.make_ticket(self.employee2)
        self.client.force_login(self.employee)
        response = self.client.get(reverse('ticket_detail', args=[ticket.pk]))
        self.assertEqual(response.status_code, 404)

    def test_only_admin_can_view_reports(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('reports')).status_code, 200)

    def test_employee_cannot_assign_tickets(self):
        ticket = self.make_ticket()
        self.client.force_login(self.employee)
        response = self.client.post(reverse('ticket_assign', args=[ticket.pk]),
                                    {'technician': self.tech.pk})
        self.assertEqual(response.status_code, 403)
        ticket.refresh_from_db()
        self.assertIsNone(ticket.assigned_to)

    def test_technician_cannot_create_tickets(self):
        self.client.force_login(self.tech)
        response = self.client.get(reverse('ticket_create'))
        self.assertEqual(response.status_code, 403)

    def test_server_rejects_disallowed_status_change(self):
        ticket = self.make_ticket()
        self.client.force_login(self.employee)
        self.client.post(reverse('ticket_status', args=[ticket.pk]), {'status': 'closed'})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'open')


class ValidationAndSecurityTests(BaseTestCase):
    def test_short_title_is_rejected(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Hi', 'description': 'A long enough description here.',
            'category': self.category.pk, 'priority': 'low'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Ticket.objects.count(), 0)
        self.assertIn('title', response.context['form'].errors)

    def test_valid_ticket_is_created(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse('ticket_create'), {
            'title': 'Monitor flickers', 'description': 'The screen flickers every minute.',
            'category': self.category.pk, 'priority': 'medium'})
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get()
        self.assertEqual(ticket.created_by, self.employee)
        self.assertEqual(ticket.status, 'open')

    def test_passwords_are_stored_hashed(self):
        user = User.objects.get(username='emp')
        self.assertNotEqual(user.password, 'Pass@12345')
        self.assertTrue(user.password.startswith('pbkdf2_'))

    def test_registration_always_creates_employee(self):
        self.client.post(reverse('register'), {
            'username': 'newuser', 'email': 'new@example.com',
            'password1': 'Str0ngPass!234', 'password2': 'Str0ngPass!234',
            'role': 'admin'})
        self.assertEqual(User.objects.get(username='newuser').role, 'employee')