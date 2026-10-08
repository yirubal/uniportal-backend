"""Check the payment uniqueness rule using competing database connections."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.utils import timezone

from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from .models import Student, SubscriptionPlan, SubscriptionRequest


@skipUnlessDBFeature('has_select_for_update')
class ConcurrentSubscriptionRequestTests(TransactionTestCase):
    def test_concurrent_requests_leave_one_pending_request_per_student(self):
        student = Student.objects.create(telegram_id=123456, first_name='Database Test')
        plan = SubscriptionPlan.objects.create(
            plan_id='semester', name='Semester Pass', price=500, days=120,
        )
        barrier = Barrier(2)

        def create_request(reference):
            try:
                barrier.wait(timeout=10)
                with transaction.atomic():
                    SubscriptionRequest.objects.create(
                        student_id=student.pk,
                        plan_id=plan.pk,
                        reference=reference,
                        amount=plan.price,
                    )
                return 'created'
            except IntegrityError:
                return 'duplicate'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create_request, reference) for reference in ('UNI-DB01', 'UNI-DB02')]
            results = [future.result(timeout=15) for future in futures]

        self.assertCountEqual(results, ['created', 'duplicate'])
        self.assertEqual(SubscriptionRequest.objects.filter(student=student, status='pending').count(), 1)

    @patch('apps.accounts.services.notify_subscription_approved')
    @patch('apps.accounts.services.notify_subscription_rejected')
    def test_competing_payment_actions_apply_one_transition(self, rejected, approved):
        from .services import approve_subscription_request, reject_subscription_request
        student = Student.objects.create(telegram_id=123457, first_name='Concurrent Approval')
        plan = SubscriptionPlan.objects.create(plan_id='monthly', name='Monthly', price=100, days=30)
        actor = get_user_model().objects.create_user(username='concurrent-admin')
        for compete_with_rejection in (False, True):
            student.subscription_status = 'free'
            student.subscription_expiry = None
            student.save()
            payment = SubscriptionRequest.objects.create(
                student=student, plan=plan, amount=100, reference=f'UNI-RACE-{compete_with_rejection}',
            )
            barrier = Barrier(2)
            started = timezone.now()

            def transition(reject):
                try:
                    barrier.wait(timeout=10)
                    if reject:
                        return reject_subscription_request(payment.pk)
                    return approve_subscription_request(payment.pk, actor)
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(transition, reject) for reject in (False, compete_with_rejection)]
                results = [future.result(timeout=15) for future in futures]
            self.assertCountEqual(results, [True, False])
            payment.refresh_from_db()
            student.refresh_from_db()
            if payment.status == 'approved':
                self.assertTrue(student.is_premium)
                self.assertGreaterEqual(student.subscription_expiry, started + timedelta(days=30))
                self.assertLess(student.subscription_expiry, timezone.now() + timedelta(days=30))
            else:
                self.assertEqual(payment.status, 'rejected')
                self.assertIsNone(student.subscription_expiry)
        self.assertEqual(approved.call_count + rejected.call_count, 2)
