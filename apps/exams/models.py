from django.db import models


class ExamTerm(models.Model):
    TERM_1 = 1
    TERM_2 = 2
    TERM_3 = 3
    TERM_CHOICES = [(1, 'Term I'), (2, 'Term II'), (3, 'Term III')]

    year = models.IntegerField(help_text='Ethiopian calendar year e.g. 2018')
    term = models.IntegerField(choices=TERM_CHOICES)
    center = models.CharField(max_length=100, default='Addis Ababa')
    is_active = models.BooleanField(
        default=False,
        help_text='Only one term should be active at a time — this is what students see',
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
    session_number = models.IntegerField(help_text='1=Session I, 2=Session II etc.')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['date', 'start_time']
        unique_together = ['term', 'session_number', 'date']

    def __str__(self):
        return f'Session {self.session_number} — {self.date} {self.start_time}'


class ExamSchedule(models.Model):
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='schedules')
    course_name = models.CharField(max_length=300)
    course_code = models.CharField(max_length=30)
    total_students = models.IntegerField(default=0)

    class Meta:
        ordering = ['course_name']
        indexes = [
            models.Index(fields=['course_code'], name='exam_schedule_code_idx'),
        ]

    def __str__(self):
        return f'{self.course_code} — {self.session}'


class ExamRoom(models.Model):
    schedule = models.ForeignKey(ExamSchedule, on_delete=models.CASCADE, related_name='rooms')
    room_code = models.CharField(max_length=20, help_text='e.g. K-1, J-5')

    def __str__(self):
        return self.room_code


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
        ordering = ['session__date', 'session__start_time']
        indexes = [
            models.Index(fields=['term', 'student_id'], name='student_exam_term_id_idx'),
            models.Index(fields=['term', 'student_name'], name='student_exam_term_name_idx'),
        ]

    def __str__(self):
        return f'{self.student_name} — {self.course_code} — Room {self.room_code}'

