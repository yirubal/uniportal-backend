from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.contrib import messages
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Department,
    Course,
    CoursePlacement,
    Resource,
    FileInbox,
)
from .services import clear_inbox_file, copy_inbox_file_to_resource


# ── Department ────────────────────────────────────────────────────────────────

@admin.register(Department)
class DepartmentAdmin(ModelAdmin):
    list_display  = ['name', 'level', 'is_active', 'created_at']
    list_filter   = ['level', 'is_active']
    search_fields = ['name']
    list_editable = ['is_active']


# ── Course ────────────────────────────────────────────────────────────────────

class CoursePlacementInline(TabularInline):
    model            = CoursePlacement
    extra            = 1
    can_delete       = True
    show_change_link = False
    fields           = ['department', 'program', 'year', 'period']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('department')


@admin.register(Course)
class CourseAdmin(ModelAdmin):
    list_display  = ['name', 'code', 'display_departments', 'display_programs', 'display_years', 'is_active']
    search_fields = ['name', 'code']
    list_filter   = ['is_active', 'placements__department', 'placements__program', 'placements__year']
    list_editable = ['is_active']
    inlines       = [CoursePlacementInline]
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related(
            'placements__department'
        )

    @admin.display(description='Departments')
    def display_departments(self, obj):
        depts = sorted(set(
            p.department.name for p in obj.placements.all() if p.department
        ))
        return ', '.join(depts) if depts else '—'

    @admin.display(description='Programs')
    def display_programs(self, obj):
        programs = sorted(set(p.program for p in obj.placements.all()))
        return ', '.join(programs) if programs else '—'

    @admin.display(description='Years')
    def display_years(self, obj):
        years = sorted(set(p.year for p in obj.placements.all()))
        return ', '.join([f'Y{y}' for y in years]) if years else '—'


# ── Course Placement ──────────────────────────────────────────────────────────

@admin.register(CoursePlacement)
class CoursePlacementAdmin(ModelAdmin):
    list_display  = ['course', 'department', 'program', 'year', 'period']
    list_filter   = ['department', 'program', 'year', 'period']
    search_fields = ['course__name', 'course__code', 'department__name']
    actions       = ['delete_selected']
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('course', 'department')


# ── Resource ──────────────────────────────────────────────────────────────────

@admin.register(Resource)
class ResourceAdmin(ModelAdmin):
    list_display  = ['title', 'course', 'file_type', 'access_level', 'status', 'downloads_count', 'created_at']
    list_filter   = ['status', 'file_type', 'access_level']
    search_fields = ['title', 'extracted_text', 'original_caption', 'course__name', 'course__code']
    readonly_fields = [
        'extracted_text', 'downloads_count', 'telegram_message_id',
        'original_caption', 'created_at', 'updated_at',
    ]
    list_editable = ['status', 'access_level']
    list_per_page = 25
    actions       = ['publish_selected', 'reject_selected', 'mark_as_free', 'mark_as_premium']
    fieldsets = (
        ('Resource Info', {
            'fields': ('title', 'file', 'file_type', 'course')
        }),
        ('Access & Status', {
            'fields': ('access_level', 'status')
        }),
        ('Extracted Content', {
            'fields': ('extracted_text',),
            'classes': ('collapse',),
        }),
        ('Telegram Source', {
            'fields': ('telegram_message_id', 'original_caption'),
            'classes': ('collapse',),
        }),
        ('Stats', {
            'fields': ('downloads_count', 'created_at', 'updated_at')
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('course__department')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'course':
            kwargs['queryset'] = Course.objects.filter(
                is_active=True
            ).order_by('name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

        if db_field.name == 'course':
            kwargs['queryset'] = Course.objects.select_related(
                'placements__department'
            ).filter(is_active=True).order_by('name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


    @admin.action(description='Publish selected resources')
    def publish_selected(self, request, queryset):
        queryset.update(status=Resource.STATUS_PUBLISHED)
        self.message_user(request, f'{queryset.count()} resource(s) published.')

    @admin.action(description='Reject selected resources')
    def reject_selected(self, request, queryset):
        queryset.update(status=Resource.STATUS_REJECTED)
        self.message_user(request, f'{queryset.count()} resource(s) rejected.')

    @admin.action(description='Mark selected as Free')
    def mark_as_free(self, request, queryset):
        queryset.update(access_level=Resource.ACCESS_FREE)
        self.message_user(request, f'{queryset.count()} resource(s) marked as free.')

    @admin.action(description='Mark selected as Premium')
    def mark_as_premium(self, request, queryset):
        queryset.update(access_level=Resource.ACCESS_PREMIUM)
        self.message_user(request, f'{queryset.count()} resource(s) marked as premium.')


# ── File Inbox ────────────────────────────────────────────────────────────────

class AssignmentFilter(SimpleListFilter):
    title            = 'assignment status'
    parameter_name   = 'assigned'

    def lookups(self, request, model_admin):
        return [
            ('unassigned', 'Unassigned (pending)'),
            ('assigned',   'Assigned'),
            ('all',        'All'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'assigned':
            return queryset.filter(assigned_resource__isnull=False)
        if self.value() == 'all':
            return queryset
        return queryset.filter(assigned_resource__isnull=True)


@admin.register(FileInbox)
class FileInboxAdmin(ModelAdmin):
    list_display  = ['original_filename', 'telegram_caption_preview', 'posted_date', 'processing_status', 'is_assigned']
    list_filter   = [AssignmentFilter, 'processing_status']
    search_fields = ['original_filename', 'telegram_caption', 'extracted_text']
    readonly_fields = [
        'original_filename', 'telegram_message_id', 'telegram_caption',
        'posted_date', 'processing_status', 'extracted_text',
        'processing_error', 'created_at',
    ]
    actions       = ['mark_as_processed', 'publish_as_resource', 'extract_questions']
    list_per_page = 25
    fieldsets = (
        ('File Info', {
            'fields': ('file', 'original_filename', 'telegram_message_id', 'telegram_caption', 'posted_date')
        }),
        ('Processing', {
            'fields': ('processing_status', 'processing_error')
        }),
        ('Extracted Text', {
            'fields': ('extracted_text',),
            'classes': ('collapse',),
        }),
        ('Assignment', {
            'fields': ('assigned_resource',)
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('assigned_resource')
        if 'assigned' not in request.GET:
            return qs.filter(assigned_resource__isnull=True)
        return qs

    @admin.display(description='Assigned', boolean=True)
    def is_assigned(self, obj):
        return obj.assigned_resource is not None

    @admin.display(description='Caption')
    def telegram_caption_preview(self, obj):
        if obj.telegram_caption:
            return obj.telegram_caption[:60] + ('...' if len(obj.telegram_caption) > 60 else '')
        return '—'

    @admin.action(description='Mark selected as processed')
    def mark_as_processed(self, request, queryset):
        queryset.update(processing_status=FileInbox.STATUS_PROCESSED)
        self.message_user(request, f'{queryset.count()} item(s) marked as processed.')

    @admin.action(description='Publish selected as Resource — assign course after')
    def publish_as_resource(self, request, queryset):
        created = 0
        failed  = 0
        for item in queryset.filter(
            processing_status=FileInbox.STATUS_PROCESSED,
            assigned_resource__isnull=True,
        ):
            resource = Resource(
                title               = item.original_filename,
                file_type           = Resource.TYPE_LECTURE_NOTE,
                extracted_text      = item.extracted_text,
                access_level        = Resource.ACCESS_PREMIUM,
                status              = Resource.STATUS_PENDING,
                course_id           = 1,
                telegram_message_id = item.telegram_message_id,
                original_caption    = item.telegram_caption,
            )
            try:
                copy_inbox_file_to_resource(item, resource)
                resource.save()
            except Exception as exc:
                failed += 1
                self.message_user(
                    request,
                    f'Could not copy file for {item.original_filename}: {exc}',
                    level=messages.ERROR,
                )
                continue
            item.assigned_resource = resource
            item.save(update_fields=['assigned_resource'])
            clear_inbox_file(item, protected_file_name=resource.file.name)
            created += 1

        self.message_user(
            request,
            f'{created} resource(s) created. {failed} failed. Please update the course for each one.',
            level=messages.WARNING if failed else messages.SUCCESS,
        )

    @admin.action(description='Extract questions from selected files using AI')
    def extract_questions(self, request, queryset):
        from apps.bot.extractor import extract_questions_from_text
        from apps.quiz.models import Question

        eligible = queryset.filter(
            processing_status=FileInbox.STATUS_PROCESSED,
        ).exclude(extracted_text='')

        if not eligible.exists():
            self.message_user(
                request,
                'No eligible files found. Files must be processed and have extracted text.',
                level=messages.WARNING,
            )
            return

        total_created = 0
        for item in eligible:
            questions_data = extract_questions_from_text(item.extracted_text)
            if not questions_data:
                self.message_user(request, f'No questions found in: {item.original_filename}', level=messages.WARNING)
                continue
            for q_data in questions_data:
                Question.objects.create(
                    text           = q_data.get('question', ''),
                    option_a       = q_data.get('option_a', ''),
                    option_b       = q_data.get('option_b', ''),
                    option_c       = q_data.get('option_c', ''),
                    option_d       = q_data.get('option_d', ''),
                    option_e       = q_data.get('option_e', ''),
                    correct_option = q_data.get('correct_option', ''),
                    explanation    = q_data.get('explanation', ''),
                    is_active      = False,
                )
                total_created += 1
            self.message_user(
                request,
                f'Extracted {len(questions_data)} questions from {item.original_filename}.',
                level=messages.SUCCESS,
            )

        self.message_user(
            request,
            f'Total questions created: {total_created}. Go to Quiz > Questions to review.',
            level=messages.SUCCESS,
        )