from django.db import models

class Department(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.code})'


class Course(models.Model):
    YEAR_CHOICES = [(i, f'Year {i}') for i in range(1, 6)]

    PERIOD_TYPE_SEMESTER = 'semester'
    PERIOD_TYPE_TERM = 'term'
    PERIOD_TYPE_CHOICES = [
        (PERIOD_TYPE_SEMESTER, 'Semester'),
        (PERIOD_TYPE_TERM, 'Term'),
    ]

    PERIOD_CHOICES = [
        (1, 'Semester I / Term I'),
        (2, 'Semester II / Term II'),
        (3, 'Term III'),
        (4, 'Term IV'),
    ]

    PROGRAM_REGULAR = 'regular'
    PROGRAM_DISTANCE = 'distance'
    PROGRAM_EXTENSION = 'extension'
    PROGRAM_CHOICES = [
        (PROGRAM_REGULAR, 'Regular'),
        (PROGRAM_DISTANCE, 'Distance'),
        (PROGRAM_EXTENSION, 'Extension'),
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, unique=True)

    # ManyToMany — one course can belong to multiple departments
    departments = models.ManyToManyField(
        Department,
        related_name='courses',
        blank=True,
    )

    # ManyToMany — one course can belong to multiple programs
    # e.g. "Introduction to Statistics" exists in both Regular and Extension
    programs = models.ManyToManyField(
        'CourseProgram',
        related_name='courses',
        blank=True,
        help_text='Which programs offer this course',
    )

    year = models.IntegerField(choices=YEAR_CHOICES)
    period_type = models.CharField(
        max_length=10,
        choices=PERIOD_TYPE_CHOICES,
        default=PERIOD_TYPE_SEMESTER,
        help_text='Semester for regular/extension. Term for distance.',
    )
    period = models.IntegerField(
        choices=PERIOD_CHOICES,
        help_text=(
            'Regular/Extension: 1 or 2 (Semester I or II). '
            'Distance: 1, 2, 3, or 4 (Term I to IV).'
        ),
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Course'
        verbose_name_plural = 'Courses'
        ordering = ['year', 'period', 'name']

    def __str__(self):
        period_label = 'Sem' if self.period_type == self.PERIOD_TYPE_SEMESTER else 'Term'
        return f'{self.name} (Year {self.year} {period_label} {self.period})'


class CourseProgram(models.Model):
    """
    Represents a program type.
    Used as ManyToMany on Course so a course can be offered
    in Regular, Distance, Extension or any combination.
    """
    PROGRAM_REGULAR = 'regular'
    PROGRAM_DISTANCE = 'distance'
    PROGRAM_EXTENSION = 'extension'
    PROGRAM_CHOICES = [
        (PROGRAM_REGULAR, 'Regular'),
        (PROGRAM_DISTANCE, 'Distance'),
        (PROGRAM_EXTENSION, 'Extension'),
    ]

    name = models.CharField(
        max_length=10,
        choices=PROGRAM_CHOICES,
        unique=True,
    )

    class Meta:
        verbose_name = 'Program'
        verbose_name_plural = 'Programs'

    def __str__(self):
        return self.get_name_display()


class Resource(models.Model):
    TYPE_LECTURE_NOTE = 'lecture_note'
    TYPE_WORKSHEET = 'worksheet'
    TYPE_PAST_EXAM = 'past_exam'
    TYPE_EXIT_EXAM = 'exit_exam'
    TYPE_CHOICES = [
        (TYPE_LECTURE_NOTE, 'Lecture Notes'),
        (TYPE_WORKSHEET, 'Worksheet'),
        (TYPE_PAST_EXAM, 'Past Exam'),
        (TYPE_EXIT_EXAM, 'Exit Exam'),
    ]

    ACCESS_FREE = 'free'
    ACCESS_PREMIUM = 'premium'
    ACCESS_CHOICES = [
        (ACCESS_FREE, 'Free'),
        (ACCESS_PREMIUM, 'Premium'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_PUBLISHED = 'published'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending — awaiting admin review'),
        (STATUS_PUBLISHED, 'Published — visible to students'),
        (STATUS_REJECTED, 'Rejected — removed from inbox'),
    ]

    title = models.CharField(max_length=500)
    file = models.FileField(upload_to='resources/%Y/%m/')
    file_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    extracted_text = models.TextField(blank=True)
    access_level = models.CharField(
        max_length=10,
        choices=ACCESS_CHOICES,
        default=ACCESS_PREMIUM,
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='resources',
    )
    telegram_message_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text='Original Telegram message ID this file came from',
    )
    original_caption = models.TextField(
        blank=True,
        help_text='Original caption from the Telegram message',
    )
    downloads_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Resource'
        verbose_name_plural = 'Resources'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} — {self.get_file_type_display()}'

    @property
    def is_worksheet(self):
        return self.file_type == self.TYPE_WORKSHEET

    @property
    def is_exam(self):
        return self.file_type in [self.TYPE_PAST_EXAM, self.TYPE_EXIT_EXAM]


class FileInbox(models.Model):
    STATUS_UNPROCESSED = 'unprocessed'
    STATUS_PROCESSING = 'processing'
    STATUS_PROCESSED = 'processed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_UNPROCESSED, 'Unprocessed'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_PROCESSED, 'Processed — ready for tagging'),
        (STATUS_FAILED, 'Failed — processing error'),
    ]

    file = models.FileField(upload_to='inbox/%Y/%m/')
    original_filename = models.CharField(max_length=500)
    telegram_message_id = models.BigIntegerField(unique=True)
    telegram_caption = models.TextField(
        blank=True,
        help_text='Caption from the original Telegram message',
    )
    posted_date = models.DateTimeField()
    processing_status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default=STATUS_UNPROCESSED,
    )
    extracted_text = models.TextField(blank=True)
    processing_error = models.TextField(blank=True)
    assigned_resource = models.OneToOneField(
        Resource,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='inbox_source',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'File Inbox'
        verbose_name_plural = 'File Inbox'
        ordering = ['-posted_date']

    def __str__(self):
        return f'{self.original_filename} ({self.get_processing_status_display()})'


