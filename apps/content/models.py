from django.db import models


class Department(models.Model):
    LEVEL_UNDERGRADUATE = 'undergraduate'
    LEVEL_POSTGRADUATE = 'postgraduate'
    LEVEL_CHOICES = [
        (LEVEL_UNDERGRADUATE, 'Undergraduate'),
        (LEVEL_POSTGRADUATE, 'Postgraduate'),
    ]

    name = models.CharField(max_length=255, unique=True)
    level = models.CharField(
        max_length=20,
        choices=LEVEL_CHOICES,
        default=LEVEL_UNDERGRADUATE,
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Department'
        verbose_name_plural = 'Departments'
        ordering = ['level', 'name']
        indexes = [
            models.Index(fields=['is_active'], name='dept_active_idx'),
            models.Index(fields=['level', 'is_active'], name='dept_level_active_idx'),
        ]

    def __str__(self):
        return self.name


class Course(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Course'
        verbose_name_plural = 'Courses'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active'], name='course_active_idx'),
            models.Index(fields=['code'], name='course_code_idx'),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'


class CoursePlacement(models.Model):
    YEAR_CHOICES = [(i, f'Year {i}') for i in range(1, 6)]

    PERIOD_CHOICES = [
        (1, 'Semester I / Term I'),
        (2, 'Semester II / Term II'),
        (3, 'Term III'),
    ]

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='placements',
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name='course_placements',
    )
    PROGRAM_REGULAR = 'regular'
    PROGRAM_DISTANCE = 'distance'
    PROGRAM_EXTENSION = 'extension'
    PROGRAM_CHOICES = [
        (PROGRAM_REGULAR, 'Regular'),
        (PROGRAM_DISTANCE, 'Distance'),
        (PROGRAM_EXTENSION, 'Extension'),
    ]

    program = models.CharField(
        max_length=10,
        choices=PROGRAM_CHOICES,
    )
    year = models.IntegerField(choices=YEAR_CHOICES)
    period = models.IntegerField(choices=PERIOD_CHOICES)

    class Meta:
        verbose_name = 'Course Placement'
        verbose_name_plural = 'Course Placements'
        ordering = ['year', 'period', 'course__name']
        unique_together = [
            'course', 'department', 'program', 'year', 'period'
        ]
        indexes = [
            # Primary lookup: "give me all courses for dept X, distance, year 2, term 1"
            models.Index(
                fields=['department', 'program', 'year', 'period'],
                name='placement_dept_prog_yr_pd_idx',
            ),
            # Reverse lookup: "which departments/years is this course in?"
            models.Index(
                fields=['course', 'program'],
                name='placement_course_prog_idx',
            ),
        ]

    def __str__(self):
        return (
            f'{self.course.name} — '
            f'{self.department.name} / '
            f'{self.get_program_display()} / '
            f'Year {self.year} Period {self.period}'
        )


class Resource(models.Model):
    TYPE_LECTURE_NOTE = 'lecture_note'
    TYPE_MODULE = 'module'
    TYPE_WORKSHEET = 'worksheet'
    TYPE_CHOICES = [
        (TYPE_LECTURE_NOTE, 'Lecture Notes'),
        (TYPE_MODULE, 'Course Module'),
        (TYPE_WORKSHEET, 'Worksheet'),
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
        indexes = [
            # Primary student-facing lookup: published resources for a course
            models.Index(
                fields=['course', 'status', 'access_level'],
                name='resource_course_status_acc_idx',
            ),
            # Admin filtering by status
            models.Index(
                fields=['status', 'created_at'],
                name='resource_status_created_idx',
            ),
        ]

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

    file = models.FileField(upload_to='inbox/%Y/%m/', blank=True)
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
        indexes = [
            # Admin default view: unassigned + processing status filter
            models.Index(
                fields=['assigned_resource', 'processing_status'],
                name='inbox_assigned_status_idx',
            ),
            # Duplicate check on harvest
            models.Index(
                fields=['telegram_message_id'],
                name='inbox_telegram_msg_idx',
            ),
        ]

    def __str__(self):
        return f'{self.original_filename} ({self.get_processing_status_display()})'