from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import ExamPaper, Question, QuizAttempt


@admin.register(ExamPaper)
class ExamPaperAdmin(ModelAdmin):
    list_display = [
        'title',
        'course',
        'exam_type',
        'year',
        'duration_minutes',
        'total_questions',
        'access_level',
        'is_active',
    ]
    list_filter = [
        'exam_type',
        'access_level',
        'is_active',

    ]
    search_fields = [
        'title',
        'course__name',
    ]
    readonly_fields = [
        'total_questions',
        'is_ready',
        'created_at',
        'updated_at',
    ]
    list_editable = ['access_level', 'is_active']
    fieldsets = (
        ('Exam Info', {
            'fields': (
                'title',
                'course',
                'exam_type',
                'year',
            )
        }),
        ('Configuration', {
            'fields': (
                'duration_minutes',
                'instructions',
                'access_level',
                'is_active',
            )
        }),
        ('Source', {
            'fields': (
                'source_resource',
            )
        }),
        ('Stats', {
            'fields': (
                'total_questions',
                'is_ready',
                'created_at',
                'updated_at',
            )
        }),
    )


@admin.register(Question)
class QuestionAdmin(ModelAdmin):
    list_display = [
        'short_text',
        'course',
        'exam_paper',
        'difficulty',
        'year_source',
        'access_level',
        'is_active',
    ]
    list_filter = [
        'difficulty',
        'access_level',
        'is_active',
        'exam_paper__exam_type',

    ]
    search_fields = [
        'text',
        'course__name',
    ]
    list_editable = ['access_level', 'is_active']
    fieldsets = (
        ('Question', {
            'fields': (
                'text',
                'course',
                'exam_paper',
            )
        }),
        ('Options', {
            'fields': (
                'option_a',
                'option_b',
                'option_c',
                'option_d',
                'option_e',
                'correct_option',
            )
        }),
        ('Explanation & Tags', {
            'fields': (
                'explanation',
                'topic_tags',
                'year_source',
                'difficulty',
            )
        }),
        ('Access', {
            'fields': (
                'access_level',
                'is_active',
            )
        }),
    )

    @admin.display(description='Question')
    def short_text(self, obj):
        return obj.text[:80] + '...' if len(obj.text) > 80 else obj.text


@admin.register(QuizAttempt)
class QuizAttemptAdmin(ModelAdmin):
    list_display = [
        'student',
        'course',
        'exam_paper',
        'score',
        'total_questions',
        'percentage',
        'mode',
        'completed_at',
    ]
    list_filter = [
        'mode',

    ]
    search_fields = [
        'student__username',
        'student__first_name',
    ]
    readonly_fields = [
        'student',
        'course',
        'exam_paper',
        'score',
        'total_questions',
        'answers',
        'mode',
        'completed_at',
        'percentage',
        'passed',
    ]