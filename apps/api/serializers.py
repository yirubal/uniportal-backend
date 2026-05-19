from rest_framework import serializers
from apps.accounts.models import Student
from apps.content.models import Department, Course, CoursePlacement, Resource
from apps.quiz.models import Chapter, ExamPaper, Question, QuizAttempt


class StudentSerializer(serializers.ModelSerializer):
    is_premium = serializers.BooleanField(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    subscription_status = serializers.SerializerMethodField()

    def get_subscription_status(self, obj):
        if obj.is_premium:
            return Student.SUBSCRIPTION_PREMIUM
        return Student.SUBSCRIPTION_FREE

    class Meta:
        model = Student
        fields = [
            'id',
            'telegram_id',
            'first_name',
            'last_name',
            'username',
            'subscription_status',
            'subscription_expiry',
            'is_premium',
            'days_remaining',
            'downloads_today',
            'onboarding_complete',
            'preferred_department',
            'preferred_program',
            'preferred_year',
            'preferred_period',
            'joined_at',
        ]
        read_only_fields = [
            'id',
            'telegram_id',
            'first_name',
            'last_name',
            'username',
            'subscription_status',
            'subscription_expiry',
            'is_premium',
            'days_remaining',
            'downloads_today',
            'joined_at',
        ]


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name', 'level', 'description']


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['id', 'name', 'code', 'description']


class CoursePlacementSerializer(serializers.ModelSerializer):
    course = CourseSerializer(read_only=True)

    class Meta:
        model = CoursePlacement
        fields = ['id', 'course', 'year', 'period', 'program']


class ResourceSerializer(serializers.ModelSerializer):
    is_locked = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    course_codes = serializers.SerializerMethodField()
    course_names = serializers.SerializerMethodField()
    file_type_display = serializers.CharField(
        source='get_file_type_display',
        read_only=True,
    )
    source = serializers.CharField()
    source_display = serializers.CharField(
        source='get_source_display',
        read_only=True,
    )

    class Meta:
        model = Resource
        fields = [
            'id',
            'title',
            'file_type',
            'file_type_display',
            'course_codes',
            'course_names',
            'source',
            'source_display',
            'access_level',
            'status',
            'downloads_count',
            'created_at',
            'is_locked',
            'file_url',
        ]

    def get_is_locked(self, obj) -> bool:
        request = self.context.get('request')
        if not request or not hasattr(request, 'student'):
            return True
        if obj.access_level == Resource.ACCESS_FREE:
            return False
        return not request.student.is_premium

    def get_file_url(self, obj) -> str | None:
        request = self.context.get('request')
        if not request or not hasattr(request, 'student'):
            return None
        if obj.access_level == Resource.ACCESS_PREMIUM and not request.student.is_premium:
            return None
        if obj.file:
            return request.build_absolute_uri(obj.file.url)
        return None

    def get_course_codes(self, obj) -> list[str]:
        return list(obj.courses.values_list('code', flat=True))

    def get_course_names(self, obj) -> list[str]:
        return list(obj.courses.values_list('name', flat=True))


class ChapterSerializer(serializers.ModelSerializer):
    question_count = serializers.SerializerMethodField()

    class Meta:
        model = Chapter
        fields = [
            'id',
            'number',
            'title',
            'description',
            'icon',
            'question_count',
        ]

    def get_question_count(self, obj) -> int:
        return obj.questions.filter(is_active=True).count()


class QuestionSerializer(serializers.ModelSerializer):
    """
    Practice mode — includes correct answer, explanation, and question_type.
    Frontend uses question_type to render the correct UI component.
    """
    available_options = serializers.DictField(read_only=True)
    is_auto_gradable = serializers.BooleanField(read_only=True)
    chapter_id = serializers.IntegerField(read_only=True)
    chapter_number = serializers.IntegerField(source='chapter.number', read_only=True)
    chapter_title = serializers.CharField(source='chapter.title', read_only=True)

    class Meta:
        model = Question
        fields = [
            'id',
            'chapter_id',
            'chapter_number',
            'chapter_title',
            'text',
            'question_type',
            'option_a',
            'option_b',
            'option_c',
            'option_d',
            'option_e',
            'correct_option',
            'explanation',
            'difficulty',
            'topic_tags',
            'year_source',
            'available_options',
            'is_auto_gradable',
        ]


class QuestionSimulationSerializer(serializers.ModelSerializer):
    """
    Simulation mode — hides correct answer and explanation.
    Still exposes question_type so frontend renders the right input.
    """
    available_options = serializers.DictField(read_only=True)
    is_auto_gradable = serializers.BooleanField(read_only=True)
    chapter_id = serializers.IntegerField(read_only=True)
    chapter_number = serializers.IntegerField(source='chapter.number', read_only=True)
    chapter_title = serializers.CharField(source='chapter.title', read_only=True)

    class Meta:
        model = Question
        fields = [
            'id',
            'chapter_id',
            'chapter_number',
            'chapter_title',
            'text',
            'question_type',
            'option_a',
            'option_b',
            'option_c',
            'option_d',
            'option_e',
            'available_options',
            'is_auto_gradable',
        ]


class ExamPaperSerializer(serializers.ModelSerializer):
    total_questions = serializers.IntegerField(read_only=True)
    is_ready = serializers.BooleanField(read_only=True)
    is_locked = serializers.SerializerMethodField()
    department = DepartmentSerializer(read_only=True)
    course = CourseSerializer(read_only=True)

    class Meta:
        model = ExamPaper
        fields = [
            'id',
            'title',
            'exam_type',
            'year',
            'duration_minutes',
            'instructions',
            'access_level',
            'total_questions',
            'is_ready',
            'is_locked',
            'department',
            'course',
        ]

    def get_is_locked(self, obj) -> bool:
        request = self.context.get('request')
        if not request or not hasattr(request, 'student'):
            return True
        if obj.access_level == ExamPaper.ACCESS_FREE:
            return False
        return not request.student.is_premium


class QuizAttemptSerializer(serializers.ModelSerializer):
    percentage = serializers.FloatField(read_only=True)
    passed = serializers.BooleanField(read_only=True)
    exam_paper = ExamPaperSerializer(read_only=True)

    class Meta:
        model = QuizAttempt
        fields = [
            'id',
            'exam_paper',
            'score',
            'total_questions',
            'percentage',
            'passed',
            'mode',
            'completed_at',
        ]
