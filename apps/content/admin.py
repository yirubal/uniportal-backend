
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline
from .models import Department, Course, CourseProgram, Resource, FileInbox


@admin.register(CourseProgram)
class CourseProgramAdmin(ModelAdmin):
    list_display = ['name']


@admin.register(Department)
class DepartmentAdmin(ModelAdmin):
    list_display = ['name', 'code', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'code']
    list_editable = ['is_active']


@admin.register(Course)
class CourseAdmin(ModelAdmin):
    list_display = [
        'name',
        'code',
        'display_departments',
        'display_programs',
        'year',
        'period_type',
        'period',
        'is_active',
    ]
    list_filter = [
        'year',
        'period',
        'period_type',
        'is_active',
        'departments',
        'programs',
    ]
    search_fields = ['name', 'code']
    filter_horizontal = ['departments', 'programs']
    list_editable = ['is_active']

    @admin.display(description='Departments')
    def display_departments(self, obj):
        return ', '.join([d.code for d in obj.departments.all()]) or '—'

    @admin.display(description='Programs')
    def display_programs(self, obj):
        return ', '.join([p.get_name_display() for p in obj.programs.all()]) or '—'


@admin.register(Resource)
class ResourceAdmin(ModelAdmin):
    list_display = [
        'title',
        'course',
        'file_type',
        'access_level',
        'status',
        'downloads_count',
        'created_at',
    ]
    list_filter = [
        'status',
        'file_type',
        'access_level',
        'course__year',
        'course__departments',
    ]
    search_fields = [
        'title',
        'extracted_text',
        'original_caption',
    ]
    readonly_fields = [
        'extracted_text',
        'downloads_count',
        'telegram_message_id',
        'original_caption',
        'created_at',
        'updated_at',
    ]
    list_editable = ['status', 'access_level']
    actions = [
        'publish_selected',
        'reject_selected',
        'mark_as_free',
        'mark_as_premium',
    ]
    fieldsets = (
        ('Resource Info', {
            'fields': (
                'title',
                'file',
                'file_type',
                'course',
            )
        }),
        ('Access & Status', {
            'fields': (
                'access_level',
                'status',
            )
        }),
        ('Extracted Content', {
            'fields': (
                'extracted_text',
            ),
            'classes': ('collapse',),
        }),
        ('Telegram Source', {
            'fields': (
                'telegram_message_id',
                'original_caption',
            ),
            'classes': ('collapse',),
        }),
        ('Stats', {
            'fields': (
                'downloads_count',
                'created_at',
                'updated_at',
            )
        }),
    )

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


@admin.register(FileInbox)
class FileInboxAdmin(ModelAdmin):
    list_display = [
        'original_filename',
        'telegram_caption_preview',
        'posted_date',
        'processing_status',
        'is_assigned',
    ]
    list_filter = [
        'processing_status',
    ]
    search_fields = [
        'original_filename',
        'telegram_caption',
        'extracted_text',
    ]
    readonly_fields = [
        'original_filename',
        'telegram_message_id',
        'telegram_caption',
        'posted_date',
        'processing_status',
        'extracted_text',
        'processing_error',
        'created_at',
    ]
    actions = ['mark_as_processed']
    fieldsets = (
        ('File Info', {
            'fields': (
                'file',
                'original_filename',
                'telegram_message_id',
                'telegram_caption',
                'posted_date',
            )
        }),
        ('Processing', {
            'fields': (
                'processing_status',
                'processing_error',
            )
        }),
        ('Extracted Text', {
            'fields': (
                'extracted_text',
            ),
            'classes': ('collapse',),
        }),
        ('Assignment', {
            'fields': (
                'assigned_resource',
            )
        }),
    )

    @admin.display(description='Caption')
    def telegram_caption_preview(self, obj):
        if obj.telegram_caption:
            return obj.telegram_caption[:60] + '...' if len(obj.telegram_caption) > 60 else obj.telegram_caption
        return '—'

    @admin.display(description='Assigned', boolean=True)
    def is_assigned(self, obj):
        return obj.assigned_resource is not None

    @admin.action(description='Mark selected as processed')
    def mark_as_processed(self, request, queryset):
        queryset.update(processing_status=FileInbox.STATUS_PROCESSED)
        self.message_user(request, f'{queryset.count()} item(s) marked as processed.')