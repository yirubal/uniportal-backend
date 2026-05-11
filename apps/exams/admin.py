from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import ExamRoom, ExamSchedule, ExamSession, ExamTerm, StudentExam


class ExamRoomInline(TabularInline):
    model = ExamRoom
    extra = 1
    fields = ['room_code']


class ExamScheduleInline(TabularInline):
    model = ExamSchedule
    extra = 0
    fields = ['course_name', 'course_code', 'total_students']
    show_change_link = True


class ExamSessionInline(TabularInline):
    model = ExamSession
    extra = 0
    fields = ['session_number', 'date', 'start_time', 'end_time']
    show_change_link = True


@admin.register(ExamTerm)
class ExamTermAdmin(ModelAdmin):
    list_display = ['__str__', 'is_active', 'created_at']
    list_editable = ['is_active']
    inlines = [ExamSessionInline]


@admin.register(ExamSession)
class ExamSessionAdmin(ModelAdmin):
    list_display = ['__str__', 'term', 'date', 'start_time', 'end_time']
    list_filter = ['term']
    inlines = [ExamScheduleInline]


@admin.register(ExamSchedule)
class ExamScheduleAdmin(ModelAdmin):
    list_display = ['course_name', 'course_code', 'total_students', 'session']
    list_filter = ['session__term', 'session__date']
    search_fields = ['course_name', 'course_code']
    inlines = [ExamRoomInline]


@admin.register(StudentExam)
class StudentExamAdmin(ModelAdmin):
    list_display = ['student_name', 'student_id', 'department', 'course_code', 'room_code', 'session']
    list_filter = ['term', 'department', 'session__date']
    search_fields = ['student_name', 'student_id', 'course_code']
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('term', 'session')

