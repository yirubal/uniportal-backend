from django.db import models


class ExamTerm(models.Model):
    TERM_CHOICES = [(1, 'Term I'), (2, 'Term II'), (3, 'Term III')]

    year = models.IntegerField(help_text='Ethiopian calendar year e.g. 2018')
    term = models.IntegerField(choices=TERM_CHOICES)
    center = models.CharField(max_length=100, default='Addis Ababa')
    is_active = models.BooleanField(
        default=False,
        help_text='Only one term should be active at a time.',
    )
    exam_start_date = models.DateField(
        null=True,
        blank=True,
        help_text='First exam date — used for notification scheduling',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['year', 'term', 'center']
        ordering = ['-year', '-term']

    def __str__(self):
        return f'{self.year} Term {self.term} — {self.center}'

    def save(self, *args, **kwargs):
        if self.is_active:
            ExamTerm.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class ExamSession(models.Model):
    term = models.ForeignKey(ExamTerm, on_delete=models.CASCADE, related_name='sessions')
    session_number = models.IntegerField()
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['date', 'start_time']
        unique_together = ['term', 'session_number', 'date']

    def __str__(self):
        return (
            f'Session {self.session_number} — '
            f'{self.date.strftime("%b %d")} '
            f'{self.start_time.strftime("%I:%M %p")}'
        )


class ExamScheduleEntry(models.Model):
    """
    One row from the schedule PDF.
    Stores course + session + rooms for reference.
    Not used for student lookup — StudentExam is used for that.
    """

    session = models.ForeignKey(
        ExamSession,
        on_delete=models.CASCADE,
        related_name='schedule_entries',
    )
    course_name = models.CharField(max_length=300)
    course_code = models.CharField(max_length=30)
    total_students = models.IntegerField(default=0)
    rooms = models.CharField(
        max_length=100,
        blank=True,
        help_text='e.g. K-1, K-2, K-3',
    )

    class Meta:
        ordering = ['course_name']

    def __str__(self):
        return f'{self.course_code} — {self.session}'


class StudentExam(models.Model):
    term = models.ForeignKey(ExamTerm, on_delete=models.CASCADE, related_name='student_exams')
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='student_exams')
    student_name = models.CharField(max_length=255)
    student_id = models.CharField(max_length=20, blank=True, db_index=True)
    department = models.CharField(max_length=100, blank=True)
    course_name = models.CharField(max_length=300)
    course_code = models.CharField(max_length=30)
    room_code = models.CharField(max_length=20)

    class Meta:
        ordering = ['session__date', 'session__start_time', 'student_name']
        indexes = [
            models.Index(fields=['term', 'student_id'], name='student_exam_id_idx'),
            models.Index(fields=['term', 'student_name'], name='student_exam_name_idx'),
        ]

    def __str__(self):
        return f'{self.student_name} — {self.course_code} — Room {self.room_code}'


class ExamPDFUpload(models.Model):
    """Tracks all uploaded PDFs for audit and reprocessing."""

    TYPE_SCHEDULE = 'schedule'
    TYPE_ATTENDANCE = 'attendance'
    TYPE_CHOICES = [
        (TYPE_SCHEDULE, 'Schedule PDF (1 per term)'),
        (TYPE_ATTENDANCE, 'Attendance PDF (1 per course/room)'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_PROCESSED = 'processed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSED, 'Processed'),
        (STATUS_FAILED, 'Failed'),
    ]

    # Nullable so the first schedule PDF can create the term automatically.
    term = models.ForeignKey(
        ExamTerm,
        on_delete=models.CASCADE,
        related_name='pdf_uploads',
        null=True,
        blank=True,
    )
    pdf_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    file = models.FileField(upload_to='exam_pdfs/%Y/%m/')
    original_name = models.CharField(max_length=500)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_PENDING)
    records_created = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f'{self.original_name} [{self.pdf_type}] [{self.status}]'


class ExamNotificationLog(models.Model):
    """
    Tracks which students have been notified about upcoming exams.
    Prevents sending duplicate notifications.
    """

    DAYS_15 = 15
    DAYS_7 = 7
    DAYS_3 = 3
    DAYS_CHOICES = [
        (DAYS_15, '15 days before'),
        (DAYS_7, '7 days before'),
        (DAYS_3, '3 days before'),
    ]

    term = models.ForeignKey(ExamTerm, on_delete=models.CASCADE, related_name='notification_logs')
    days_before = models.IntegerField(choices=DAYS_CHOICES)
    sent_at = models.DateTimeField(auto_now_add=True)
    sent_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ['term', 'days_before']

    def __str__(self):
        return f'{self.term} — {self.days_before} days notification'
