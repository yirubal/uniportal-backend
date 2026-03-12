from django.db import models

class ExamPaper(models.Model):
    TYPE_FINAL = 'final'
    TYPE_EXIT = 'exit'
    TYPE_CHOICES = [
        (TYPE_FINAL, 'Final Exam'),
        (TYPE_EXIT, 'Exit Exam'),
    ]

    ACCESS_FREE = 'free'
    ACCESS_PREMIUM = 'premium'
    ACCESS_CHOICES = [
        (ACCESS_FREE, 'Free'),
        (ACCESS_PREMIUM, 'Premium'),
    ]

    title = models.CharField(max_length=500)
    course = models.ForeignKey(
        'content.Course',
        on_delete=models.CASCADE,
        related_name='exam_papers',
    )
    exam_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    year = models.IntegerField()

    # These are nullable — unknown until admin fills them in
    # after extraction from the uploaded PDF/image
    duration_minutes = models.IntegerField(
        null=True,
        blank=True,
        help_text='Exam duration in minutes. Fill in after reviewing the paper.',
    )
    instructions = models.TextField(
        blank=True,
        help_text='Official exam instructions shown to students before simulation starts.',
    )

    access_level = models.CharField(
        max_length=10,
        choices=ACCESS_CHOICES,
        default=ACCESS_PREMIUM,
    )
    is_active = models.BooleanField(default=True)
    source_resource = models.ForeignKey(
        'content.Resource',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='exam_papers',
        help_text='The original resource file this exam was extracted from',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Exam Paper'
        verbose_name_plural = 'Exam Papers'
        ordering = ['-year']
        unique_together = ['course', 'exam_type', 'year']

    def __str__(self):
        return f'{self.title} ({self.year})'

    @property
    def total_questions(self):
        return self.questions.filter(is_active=True).count()

    @property
    def is_ready(self):
        """
        An exam is ready for simulation only when:
        - It has questions
        - Duration is set by admin
        """
        return self.total_questions > 0 and self.duration_minutes is not None


class Question(models.Model):
    OPTION_A = 'a'
    OPTION_B = 'b'
    OPTION_C = 'c'
    OPTION_D = 'd'
    OPTION_E = 'e'
    OPTION_CHOICES = [
        (OPTION_A, 'A'),
        (OPTION_B, 'B'),
        (OPTION_C, 'C'),
        (OPTION_D, 'D'),
        (OPTION_E, 'E'),  # some exams have 5 options
    ]

    DIFFICULTY_EASY = 'easy'
    DIFFICULTY_MEDIUM = 'medium'
    DIFFICULTY_HARD = 'hard'
    DIFFICULTY_CHOICES = [
        (DIFFICULTY_EASY, 'Easy'),
        (DIFFICULTY_MEDIUM, 'Medium'),
        (DIFFICULTY_HARD, 'Hard'),
    ]

    ACCESS_FREE = 'free'
    ACCESS_PREMIUM = 'premium'
    ACCESS_CHOICES = [
        (ACCESS_FREE, 'Free'),
        (ACCESS_PREMIUM, 'Premium'),
    ]

    text = models.TextField()

    # Options — e is nullable since not all exams have 5 options
    option_a = models.CharField(max_length=500)
    option_b = models.CharField(max_length=500)
    option_c = models.CharField(max_length=500)
    option_d = models.CharField(max_length=500)
    option_e = models.CharField(
        max_length=500,
        blank=True,
        help_text='Optional 5th choice — only used if exam paper has 5 options',
    )

    correct_option = models.CharField(
        max_length=1,
        choices=OPTION_CHOICES,
        blank=True,
        help_text='Leave blank if correct answer is not yet confirmed',
    )
    explanation = models.TextField(
        blank=True,
        help_text='Explanation shown to students after answering in practice mode',
    )
    course = models.ForeignKey(
        'content.Course',
        on_delete=models.CASCADE,
        related_name='questions',
    )
    exam_paper = models.ForeignKey(
        ExamPaper,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='questions',
    )
    difficulty = models.CharField(
        max_length=10,
        choices=DIFFICULTY_CHOICES,
        default=DIFFICULTY_MEDIUM,
    )
    year_source = models.CharField(
        max_length=10,
        blank=True,
        help_text='Year this question appeared e.g. 2022',
    )
    topic_tags = models.JSONField(
        default=list,
        blank=True,
        help_text='Topics this question covers e.g. ["Data Structures", "OOP"]',
    )
    access_level = models.CharField(
        max_length=10,
        choices=ACCESS_CHOICES,
        default=ACCESS_PREMIUM,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Question'
        verbose_name_plural = 'Questions'
        ordering = ['exam_paper', 'id']

    def __str__(self):
        return f'{self.text[:80]}...'

    @property
    def has_five_options(self):
        return bool(self.option_e)

    @property
    def available_options(self):
        options = {
            'a': self.option_a,
            'b': self.option_b,
            'c': self.option_c,
            'd': self.option_d,
        }
        if self.option_e:
            options['e'] = self.option_e
        return options


class QuizAttempt(models.Model):
    MODE_PRACTICE = 'practice'
    MODE_SIMULATION = 'simulation'
    MODE_TOPIC = 'topic'
    MODE_CHOICES = [
        (MODE_PRACTICE, 'Practice'),
        (MODE_SIMULATION, 'Simulation'),
        (MODE_TOPIC, 'Topic'),
    ]

    student = models.ForeignKey(
        'accounts.Student',
        on_delete=models.CASCADE,
        related_name='quiz_attempts',
    )
    course = models.ForeignKey(
        'content.Course',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='quiz_attempts',
    )
    exam_paper = models.ForeignKey(
        ExamPaper,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='attempts',
    )
    score = models.IntegerField()
    total_questions = models.IntegerField()
    answers = models.JSONField(
        default=dict,
        help_text='Format: {question_id: selected_option} e.g. {"12": "a", "13": "c"}',
    )
    mode = models.CharField(
        max_length=15,
        choices=MODE_CHOICES,
        default=MODE_PRACTICE,
    )
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Quiz Attempt'
        verbose_name_plural = 'Quiz Attempts'
        ordering = ['-completed_at']

    def __str__(self):
        return f'{self.student} — {self.score}/{self.total_questions} ({self.mode})'

    @property
    def percentage(self):
        if self.total_questions == 0:
            return 0
        return round((self.score / self.total_questions) * 100, 1)

    @property
    def passed(self):
        return self.percentage >= 50