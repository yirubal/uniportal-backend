"""
apps/content/views_admin.py

Custom admin views: Course Resource Audit Dashboard
"""

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Count, Q, Prefetch
from django.views.decorators.http import require_POST

from .models import Course, Resource, CoursePlacement, Department


def course_resource_audit_context(request) -> dict:
    """
    Builds and returns the context dict for the Course Resource Audit dashboard.
    Rendering is done by CourseAdmin.audit_view so that self.admin_site.each_context()
    (which provides Unfold theme variables) can be merged in first.
    """

    # ── Overall stats ─────────────────────────────────────────────────────────
    total_courses    = Course.objects.filter(is_active=True).count()
    total_resources  = Resource.objects.count()
    published_resources = Resource.objects.filter(status=Resource.STATUS_PUBLISHED).count()
    pending_resources   = Resource.objects.filter(status=Resource.STATUS_PENDING).count()

    courses_with_resources = (
        Course.objects.filter(is_active=True, resources__isnull=False)
        .distinct().count()
    )
    courses_without_resources = total_courses - courses_with_resources

    # ── Per-department breakdown ───────────────────────────────────────────────
    departments = Department.objects.filter(is_active=True).prefetch_related(
        Prefetch(
            'course_placements',
            queryset=CoursePlacement.objects.select_related('course').filter(
                program='distance'
            ),
        )
    ).order_by('name')

    dept_stats = []
    for dept in departments:
        placements = dept.course_placements.all()
        dept_courses = [p.course for p in placements]
        dept_total   = len(dept_courses)
        if dept_total == 0:
            continue

        course_ids = [c.id for c in dept_courses]
        dept_with_resources = (
            Course.objects.filter(id__in=course_ids, resources__isnull=False)
            .distinct().count()
        )
        dept_without = dept_total - dept_with_resources
        dept_resource_count = Resource.objects.filter(course_id__in=course_ids).count()
        coverage_pct = round((dept_with_resources / dept_total) * 100) if dept_total else 0

        dept_stats.append({
            'department':      dept,
            'total_courses':   dept_total,
            'with_resources':  dept_with_resources,
            'without':         dept_without,
            'resource_count':  dept_resource_count,
            'coverage_pct':    coverage_pct,
        })

    # ── Courses WITHOUT resources ─────────────────────────────────────────────
    courses_missing = (
        Course.objects.filter(is_active=True, resources__isnull=True)
        .prefetch_related(
            Prefetch(
                'placements',
                queryset=CoursePlacement.objects.select_related('department').filter(
                    program='distance'
                ).order_by('year', 'period'),
            )
        )
        .order_by('name')
        .distinct()
    )

    # ── Courses WITH resources ────────────────────────────────────────────────
    courses_covered = (
        Course.objects.filter(is_active=True, resources__isnull=False)
        .annotate(
            resource_count=Count('resources'),
            published_count=Count('resources', filter=Q(resources__status='published')),
            pending_count=Count('resources', filter=Q(resources__status='pending')),
        )
        .prefetch_related(
            Prefetch(
                'placements',
                queryset=CoursePlacement.objects.select_related('department').filter(
                    program='distance'
                ).order_by('year', 'period'),
            )
        )
        .order_by('-resource_count')
        .distinct()
    )

    # ── Filter by department (optional) ──────────────────────────────────────
    dept_filter = request.GET.get('department')
    try:
        dept_filter = int(dept_filter) if dept_filter else None
    except (ValueError, TypeError):
        dept_filter = None

    if dept_filter:
        courses_missing = courses_missing.filter(
            placements__department_id=dept_filter,
            placements__program='distance',
        )
        courses_covered = courses_covered.filter(
            placements__department_id=dept_filter,
            placements__program='distance',
        )

    # ── Search ────────────────────────────────────────────────────────────────
    search = request.GET.get('q', '').strip()
    if search:
        courses_missing = courses_missing.filter(
            Q(name__icontains=search) | Q(code__icontains=search)
        )
        courses_covered = courses_covered.filter(
            Q(name__icontains=search) | Q(code__icontains=search)
        )

    return {
        'title': 'Course Resource Audit',
        'opts':  Course._meta,

        # Overall stats
        'total_courses':             total_courses,
        'total_resources':           total_resources,
        'published_resources':       published_resources,
        'pending_resources':         pending_resources,
        'courses_with_resources':    courses_with_resources,
        'courses_without_resources': courses_without_resources,
        'overall_coverage_pct':      round((courses_with_resources / total_courses) * 100) if total_courses else 0,

        # Department breakdown
        'dept_stats': dept_stats,

        # Course lists
        'courses_missing': courses_missing,
        'courses_covered': courses_covered,

        # Filter state
        'departments': Department.objects.filter(is_active=True).order_by('name'),
        'dept_filter': dept_filter,
        'search':      search,
        'active_tab':  request.GET.get('tab', 'overview'),
    }



@staff_member_required
def course_resource_detail(request, course_id):
    course = get_object_or_404(Course, id=course_id)
    resources = (
        Resource.objects
        .filter(course=course)
        .order_by('file_type', 'title')
    )

    seen_titles = {}
    resources_with_flags = []
    for r in resources:
        normalized = r.title.lower().strip()
        is_duplicate = normalized in seen_titles
        seen_titles[normalized] = True
        resources_with_flags.append({
            'resource':      r,
            'is_duplicate':  is_duplicate,
        })

    placements = (
        CoursePlacement.objects
        .filter(course=course)
        .select_related('department')
        .order_by('department__name', 'year', 'period')
    )

    total           = resources.count()
    duplicate_count = sum(1 for r in resources_with_flags if r['is_duplicate'])
    published_count = resources.filter(status=Resource.STATUS_PUBLISHED).count()
    pending_count   = resources.filter(status=Resource.STATUS_PENDING).count()

    context = {
        'title':               f'Resources — {course.name}',
        'course':              course,
        'resources_with_flags': resources_with_flags,
        'placements':          placements,
        'opts':                Course._meta,
        'total':               total,
        'duplicate_count':     duplicate_count,
        'published_count':     published_count,
        'pending_count':       pending_count,
    }
    return render(request, 'admin/content/course_resource_detail.html', context)


@staff_member_required
@require_POST
def delete_resource(request, resource_id):
    resource  = get_object_or_404(Resource, id=resource_id)
    course_id = resource.course_id
    title     = resource.title

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
    course    = get_object_or_404(Course, id=course_id)
    resources = Resource.objects.filter(course=course).order_by('title', 'created_at')

    seen      = {}
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