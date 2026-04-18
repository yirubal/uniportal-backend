from django.db import models


class ExamPaper(models.Model):
    TYPE_FINAL      = 'final'
    TYPE_EXIT_REAL  = 'exit_real'
    TYPE_EXIT_MODEL = 'exit_model'
    TYPE_QUIZ       = 'quiz'
    TYPE_CHOICES = [
        (TYPE_FINAL,      'Final Exam'),
        (TYPE_EXIT_REAL,  'Exit Exam — Official'),
        (TYPE_EXIT_MODEL, 'Exit Exam — Model'),
        (TYPE_QUIZ,       'Team Quiz'),
    ]

    ACCESS_FREE    = 'free'
    ACCESS_PREMIUM = 'premium'
    ACCESS_CHOICES = [
        (ACCESS_FREE,    'Free'),
        (ACCESS_PREMIUM, 'Premium'),
    ]

    title = models.CharField(max_length=500)
    course = models.ForeignKey(
        'content.Course',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='exam_papers',
        help_text='Required for Final Exam and Team Quiz. Leave blank for Exit Exams.',
    )
    department = models.ForeignKey(
        'content.Department',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='exam_papers',
        help_text='Required for Exit Exams. Leave blank for Final Exam and Team Quiz.',
    )
    exam_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    year = models.IntegerField()
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
        help_text='The original resource file this exam was extracted from.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Exam Paper'
        verbose_name_plural = 'Exam Papers'
        ordering = ['-year']
        unique_together = ['course', 'department', 'exam_type', 'year']

    def __str__(self):
        return f'{self.title} ({self.year})'

    @property
    def total_questions(self):
        return self.questions.filter(is_active=True).count()

    @property
    def is_ready(self):
        return self.total_questions > 0 and self.duration_minutes is not None

    @property
    def is_exit_exam(self):
        return self.exam_type in [self.TYPE_EXIT_REAL, self.TYPE_EXIT_MODEL]


class Question(models.Model):

    # ── Question Types ────────────────────────────────────────────────────────
    TYPE_MCQ        = 'mcq'
    TYPE_TRUE_FALSE = 'true_false'
    TYPE_FILL_BLANK = 'fill_blank'
    TYPE_MATCHING   = 'matching'
    TYPE_ESSAY      = 'essay'
    TYPE_CHOICES = [
        (TYPE_MCQ,        'Multiple Choice'),
        (TYPE_TRUE_FALSE, 'True / False'),
        (TYPE_FILL_BLANK, 'Fill in the Blank'),
        (TYPE_MATCHING,   'Matching'),
        (TYPE_ESSAY,      'Essay / Short Answer'),
    ]

    DIFFICULTY_EASY   = 'easy'
    DIFFICULTY_MEDIUM = 'medium'
    DIFFICULTY_HARD   = 'hard'
    DIFFICULTY_CHOICES = [
        (DIFFICULTY_EASY,   'Easy'),
        (DIFFICULTY_MEDIUM, 'Medium'),
        (DIFFICULTY_HARD,   'Hard'),
    ]

    text = models.TextField()

    question_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_MCQ,
        help_text=(
            'MCQ: options A–E with correct_option. '
            'True/False: option_a=True, option_b=False. '
            'Fill blank: correct_option holds the answer text. '
            'Matching: each option is a "Term → Answer" pair. '
            'Essay: no options, open-ended answer.'
        ),
    )

    exam_paper = models.ForeignKey(
        ExamPaper,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='questions',
        help_text='Every question must be assigned to an exam paper.',
    )

    # Options — interpretation depends on question_type (see help_text above)
    option_a = models.CharField(max_length=500, blank=True)
    option_b = models.CharField(max_length=500, blank=True)
    option_c = models.CharField(max_length=500, blank=True)
    option_d = models.CharField(max_length=500, blank=True)
    option_e = models.CharField(
        max_length=500,
        blank=True,
        help_text='5th MCQ option only. Leave blank for other question types.',
    )
    correct_option = models.CharField(
        max_length=100,
        blank=True,
        help_text=(
            'MCQ/True-False: single letter a–e. '
            'Fill blank: the correct answer text. '
            'Matching/Essay: leave blank.'
        ),
    )
    explanation = models.TextField(
        blank=True,
        help_text='Explanation shown to students after answering in practice mode.',
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
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Question'
        verbose_name_plural = 'Questions'
        ordering = ['exam_paper', 'id']

    def __str__(self):
        return f'[{self.get_question_type_display()}] {self.text[:80]}'

    # ── Type helpers ──────────────────────────────────────────────────────────

    @property
    def is_mcq(self):
        return self.question_type == self.TYPE_MCQ

    @property
    def is_true_false(self):
        return self.question_type == self.TYPE_TRUE_FALSE

    @property
    def is_fill_blank(self):
        return self.question_type == self.TYPE_FILL_BLANK

    @property
    def is_matching(self):
        return self.question_type == self.TYPE_MATCHING

    @property
    def is_essay(self):
        return self.question_type == self.TYPE_ESSAY

    @property
    def is_auto_gradable(self):
        """Essay questions cannot be auto-graded."""
        return self.question_type != self.TYPE_ESSAY

    @property
    def has_five_options(self):
        return bool(self.option_e) and self.question_type == self.TYPE_MCQ

    @property
    def available_options(self):
        """Returns populated options dict. Only meaningful for MCQ, true_false, matching."""
        if self.question_type in (self.TYPE_ESSAY, self.TYPE_FILL_BLANK):
            return {}
        options = {'a': self.option_a, 'b': self.option_b}
        if self.question_type in (self.TYPE_MCQ, self.TYPE_MATCHING):
            options['c'] = self.option_c
            options['d'] = self.option_d
            if self.option_e:
                options['e'] = self.option_e
        return {k: v for k, v in options.items() if v}

    # ── Shortcuts through exam_paper ──────────────────────────────────────────
    # department, course, access_level are not stored on Question directly.
    # Always access them via the exam paper.

    @property
    def department(self):
        return self.exam_paper.department if self.exam_paper else None

    @property
    def course(self):
        return self.exam_paper.course if self.exam_paper else None

    @property
    def access_level(self):
        return self.exam_paper.access_level if self.exam_paper else None


class QuizAttempt(models.Model):
    MODE_PRACTICE   = 'practice'
    MODE_SIMULATION = 'simulation'
    MODE_TOPIC      = 'topic'
    MODE_CHOICES = [
        (MODE_PRACTICE,   'Practice'),
        (MODE_SIMULATION, 'Simulation'),
        (MODE_TOPIC,      'Topic'),
    ]

    student = models.ForeignKey(
        'accounts.Student',
        on_delete=models.CASCADE,
        related_name='quiz_attempts',
    )
    exam_paper = models.ForeignKey(
        ExamPaper,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='attempts',
        help_text='For exit exam and final exam attempts.',
    )
    course = models.ForeignKey(
        'content.Course',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='quiz_attempts',
        help_text='For team quiz attempts.',
    )
    department = models.ForeignKey(
        'content.Department',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='quiz_attempts',
        help_text='For department-level quiz attempts.',
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