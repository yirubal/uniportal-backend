from django.db import models


class Student(models.Model):
    SUBSCRIPTION_FREE    = 'free'
    SUBSCRIPTION_PREMIUM = 'premium'
    SUBSCRIPTION_CHOICES = [
        (SUBSCRIPTION_FREE,    'Free'),
        (SUBSCRIPTION_PREMIUM, 'Premium'),
    ]

    PROGRAM_REGULAR   = 'regular'
    PROGRAM_DISTANCE  = 'distance'
    PROGRAM_EXTENSION = 'extension'
    PROGRAM_CHOICES   = [
        (PROGRAM_REGULAR,   'Regular'),
        (PROGRAM_DISTANCE,  'Distance'),
        (PROGRAM_EXTENSION, 'Extension'),
    ]

    telegram_id         = models.BigIntegerField(unique=True)
    first_name          = models.CharField(max_length=255)
    last_name           = models.CharField(max_length=255, blank=True)
    username            = models.CharField(max_length=255, blank=True)
    subscription_status = models.CharField(
        max_length=10,
        choices=SUBSCRIPTION_CHOICES,
        default=SUBSCRIPTION_FREE,
    )
    subscription_expiry  = models.DateTimeField(null=True, blank=True)
    downloads_today      = models.IntegerField(default=0)
    last_download_reset  = models.DateField(auto_now_add=True)
    onboarding_complete  = models.BooleanField(default=False)

    preferred_department = models.ForeignKey(
        'content.Department',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='preferred_by',
    )
    preferred_program = models.CharField(
        max_length=10,
        choices=PROGRAM_CHOICES,
        null=True,
        blank=True,
    )
    preferred_year   = models.IntegerField(null=True, blank=True)
    preferred_period = models.IntegerField(
        null=True,
        blank=True,
        help_text='1 or 2 for semester students. 1,2,3 for distance students.',
    )

    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name         = 'Student'
        verbose_name_plural  = 'Students'
        ordering             = ['-joined_at']

    def __str__(self):
        if self.username:
            return f'@{self.username}'
        return f'{self.first_name} (ID: {self.telegram_id})'

    @property
    def is_premium(self):
        from django.utils import timezone
        if self.subscription_status != self.SUBSCRIPTION_PREMIUM:
            return False
        if self.subscription_expiry is None:
            return False
        return self.subscription_expiry > timezone.now()

    @property
    def days_remaining(self):
        from django.utils import timezone
        if not self.is_premium:
            return 0
        diff = self.subscription_expiry - timezone.now()
        return max(0, diff.days)

    @property
    def is_distance(self):
        return self.preferred_program == self.PROGRAM_DISTANCE

    @property
    def max_periods(self):
        return 4 if self.is_distance else 2

    def reset_daily_quota(self):
        from django.utils import timezone
        today = timezone.now().date()
        if self.last_download_reset < today:
            self.downloads_today     = 0
            self.last_download_reset = today
            self.save(update_fields=['downloads_today', 'last_download_reset'])

    def activate_premium(self, days: int):
        """Activate premium for N days. Extends existing expiry if still active."""
        from django.utils import timezone
        from datetime import timedelta
        base = self.subscription_expiry if self.is_premium else timezone.now()
        self.subscription_status = self.SUBSCRIPTION_PREMIUM
        self.subscription_expiry = base + timedelta(days=days)
        self.save(update_fields=['subscription_status', 'subscription_expiry'])


class SubscriptionPlan(models.Model):
    PLAN_SEMESTER  = 'semester'
    PLAN_EXIT_EXAM = 'exit_exam'
    PLAN_ANNUAL    = 'annual'
    PLAN_CHOICES   = [
        (PLAN_SEMESTER,  'Semester Pass'),
        (PLAN_EXIT_EXAM, 'Exit Exam Pass'),
        (PLAN_ANNUAL,    'Full Year Pass'),
    ]

    plan_id     = models.CharField(max_length=20, choices=PLAN_CHOICES, unique=True)
    name        = models.CharField(max_length=100)
    price       = models.DecimalField(max_digits=10, decimal_places=2)
    days        = models.IntegerField()
    description = models.TextField(blank=True)
    badge       = models.CharField(max_length=50, blank=True)
    is_active   = models.BooleanField(default=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Subscription Plan'
        verbose_name_plural = 'Subscription Plans'
        ordering            = ['price']

    def __str__(self):
        return f'{self.name} — ETB {self.price}'


class SubscriptionRequest(models.Model):
    STATUS_PENDING  = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES  = [
        (STATUS_PENDING,  'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    PAYMENT_TELEBIRR = 'telebirr'
    PAYMENT_CBE      = 'cbe'
    PAYMENT_CHOICES  = [
        (PAYMENT_TELEBIRR, 'Telebirr'),
        (PAYMENT_CBE,      'CBE Bank'),
    ]

    student        = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='subscription_requests',
    )
    plan           = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name='requests',
    )
    reference      = models.CharField(
        max_length=20,
        unique=True,
        help_text='Auto-generated reference code the student includes in payment.',
    )
    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_CHOICES,
        default=PAYMENT_TELEBIRR,
    )
    # Phone number or bank account the student says they paid from
    paid_from      = models.CharField(
        max_length=50,
        blank=True,
        help_text='Phone number or bank account the student paid from.',
    )
    amount         = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text='Amount the student claims to have paid.',
    )
    status         = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    admin_note     = models.TextField(
        blank=True,
        help_text='Internal note from admin (reason for rejection, etc.)',
    )
    # Set when approved
    activated_by   = models.ForeignKey(
        'auth.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='activated_subscriptions',
        help_text='Admin who approved this request.',
    )
    activated_at   = models.DateTimeField(null=True, blank=True)
    requested_at   = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Subscription Request'
        verbose_name_plural = 'Subscription Requests'
        ordering            = ['-requested_at']

    def __str__(self):
        return f'{self.student} — {self.plan.name} — {self.reference} [{self.status}]'


class SiteSettings(models.Model):
    telebirr_number      = models.CharField(
        max_length=20,
        default='0912345678',
        help_text='Telebirr phone number students send payment to.',
    )
    telebirr_name        = models.CharField(
        max_length=100,
        blank=True,
        help_text='Account name shown to students.',
    )
    cbe_account          = models.CharField(
        max_length=50,
        blank=True,
        help_text='CBE bank account number (optional).',
    )
    cbe_name             = models.CharField(
        max_length=100,
        blank=True,
        help_text='CBE account holder name (optional).',
    )
    payment_instructions = models.TextField(
        blank=True,
        help_text='Additional payment instructions shown to students.',
    )
    is_active  = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'Site Settings'
        verbose_name_plural = 'Site Settings'

    def __str__(self):
        return f'Site Settings (updated {self.updated_at.strftime("%Y-%m-%d")})'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj