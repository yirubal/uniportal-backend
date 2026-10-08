"""Check the payment uniqueness rule using competing database connections."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

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
