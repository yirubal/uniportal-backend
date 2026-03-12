from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import ExamPaper, Question, QuizAttempt


class QuestionInline(TabularInline):
    model = Question
    extra = 0
    fields = [
        'text',
        'option_a',
        'option_b',
        'option_c',
        'option_d',
        'option_e',
        'correct_option',
        'difficulty',
        'access_level',
        'is_active',
    ]
    show_change_link = True


@admin.register(ExamPaper)
class ExamPaperAdmin(ModelAdmin):
    list_display = [
        'title',
        'course',
        'exam_type',
        'year',
        'duration_minutes',
        'total_questions',
        'is_ready',
        'access_level',
        'is_active',
    ]
    list_filter = [
        'exam_type',
        'access_level',
        'is_active',
        'course__departments',
    ]
    search_fields = ['title']
    readonly_fields = [
        'total_questions',
        'is_ready',
        'created_at',
        'updated_at',
    ]
    list_editable = ['access_level', 'is_active']
    inlines = [QuestionInline]
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
            'description': 'Fill these in after reviewing the extracted exam paper.',
            'fields': (
                'duration_minutes',
                'instructions',
                'access_level',
                'is_active',
            )
        }),
        ('Stats', {
            'fields': (
                'total_questions',
                'is_ready',
                'source_resource',
                'created_at',
                'updated_at',
            )
        }),
    )

    @admin.display(description='Ready?', boolean=True)
    def is_ready(self, obj):
        return obj.is_ready


@admin.register(Question)
class QuestionAdmin(ModelAdmin):
    list_display = [
        'text_preview',
        'course',
        'exam_paper',
        'correct_option',
        'difficulty',
        'access_level',
        'year_source',
        'is_active',
    ]
    list_filter = [
        'difficulty',
        'access_level',
        'is_active',
        'course__departments',
        'exam_paper__exam_type',
    ]
    search_fields = [
        'text',
        'option_a',
        'option_b',
        'option_c',
        'option_d',
        'explanation',
    ]
    list_editable = ['correct_option', 'difficulty', 'access_level', 'is_active']
    fieldsets = (
        ('Question', {
            'fields': (
                'text',
                'course',
                'exam_paper',
                'year_source',
                'topic_tags',
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
        ('Meta', {
            'fields': (
                'explanation',
                'difficulty',
                'access_level',
                'is_active',
            )
        }),
    )
    actions = [
        'mark_as_free',
        'mark_as_premium',
        'activate_questions',
        'deactivate_questions',
    ]

    @admin.display(description='Question')
    def text_preview(self, obj):
        return obj.text[:70] + '...' if len(obj.text) > 70 else obj.text

    @admin.action(description='Mark selected as Free')
    def mark_as_free(self, request, queryset):
        queryset.update(access_level=Question.ACCESS_FREE)
        self.message_user(request, f'{queryset.count()} question(s) marked as free.')

    @admin.action(description='Mark selected as Premium')
    def mark_as_premium(self, request, queryset):
        queryset.update(access_level=Question.ACCESS_PREMIUM)
        self.message_user(request, f'{queryset.count()} question(s) marked as premium.')

    @admin.action(description='Activate selected questions')
    def activate_questions(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f'{queryset.count()} question(s) activated.')

    @admin.action(description='Deactivate selected questions')
    def deactivate_questions(self, request, queryset):
        queryset.update(is_active=False)
        self.message_user(request, f'{queryset.count()} question(s) deactivated.')


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
        'course__departments',
    ]
    search_fields = [
        'student__username',
        'student__first_name',
        'student__telegram_id',
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
    ]

    @admin.display(description='Score %')
    def percentage(self, obj):
        return f'{obj.percentage}%'