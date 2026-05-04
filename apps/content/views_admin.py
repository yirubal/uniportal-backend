"""
apps/content/views_admin.py

Custom admin view: Course Resource Audit
Shows all courses with resources, their resource list, and allows
deleting duplicate/unwanted resources per course.

URL: /admin/content/course-resource-audit/
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Count, Prefetch
from django.views.decorators.http import require_POST

from .models import Course, Resource, CoursePlacement


@staff_member_required
def course_resource_audit(request):
    """
    Lists all courses that have at least one resource.
    Shows resource count and department placements.
    """
    courses = (
        Course.objects
        .filter(resources__isnull=False)
        .annotate(resource_count=Count('resources'))
        .prefetch_related(
            Prefetch(
                'placements',
                queryset=CoursePlacement.objects.select_related('department').order_by('department__name'),
            )
        )
        .order_by('name')
        .distinct()
    )

    context = {
        'title': 'Course Resource Audit',
        'courses': courses,
        'opts': Course._meta,  # needed for admin breadcrumbs
    }
    return render(request, 'admin/content/course_resource_audit.html', context)


@staff_member_required
def course_resource_detail(request, course_id):
    """
    Shows all resources for a specific course with delete option.
    """
    course = get_object_or_404(Course, id=course_id)
    resources = (
        Resource.objects
        .filter(course=course)
        .order_by('file_type', 'title')
    )

    # Group by file_type to spot duplicates easily
    seen_titles = {}
    resources_with_flags = []
    for r in resources:
        normalized = r.title.lower().strip()
        is_duplicate = normalized in seen_titles
        seen_titles[normalized] = True
        resources_with_flags.append({
            'resource': r,
            'is_duplicate': is_duplicate,
        })

    placements = (
        CoursePlacement.objects
        .filter(course=course)
        .select_related('department')
        .order_by('department__name', 'year', 'period')
    )

    context = {
        'title': f'Resources — {course.name}',
        'course': course,
        'resources_with_flags': resources_with_flags,
        'placements': placements,
        'opts': Course._meta,
        'total': resources.count(),
        'duplicate_count': sum(1 for r in resources_with_flags if r['is_duplicate']),
    }
    return render(request, 'admin/content/course_resource_detail.html', context)


@staff_member_required
@require_POST
def delete_resource(request, resource_id):
    """
    Deletes a single resource and its file from R2.
    Redirects back to the course detail page.
    """
    resource = get_object_or_404(Resource, id=resource_id)
    course_id = resource.course_id
    title = resource.title

    # Delete file from R2
    if resource.file:
        try:
            resource.file.delete(save=False)
        except Exception as e:
            messages.warning(request, f'File could not be deleted from storage: {e}')

    resource.delete()
    messages.success(request, f'Deleted: {title}')
    return redirect('admin:course_resource_detail', course_id=course_id)


@staff_member_required
@require_POST
def delete_duplicate_resources(request, course_id):
    """
    Deletes all duplicate resources for a course
    (keeps the first one by creation date, deletes the rest with same title).
    """
    course = get_object_or_404(Course, id=course_id)
    resources = Resource.objects.filter(course=course).order_by('title', 'created_at')

    seen = {}
    to_delete = []
    for r in resources:
        key = r.title.lower().strip()
        if key in seen:
            to_delete.append(r)
        else:
            seen[key] = r

    deleted = 0
    for r in to_delete:
        try:
            if r.file:
                r.file.delete(save=False)
        except Exception:
            pass
        r.delete()
        deleted += 1

    messages.success(request, f'Deleted {deleted} duplicate resource(s) from {course.name}.')
    return redirect('admin:course_resource_detail', course_id=course_id)