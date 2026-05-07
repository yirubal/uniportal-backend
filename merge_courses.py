"""
Run this in the Railway shell:
    railway ssh
    python manage.py shell
    exec(open('merge_courses.py').read())

Or paste the whole thing into the shell.
"""

from apps.content.models import Course, Resource, CoursePlacement

def merge_courses(keep_code, remove_codes):
    """
    Keeps the course with keep_code.
    Moves all resources and placements from remove_codes to it.
    Deletes the remove_codes courses.
    """
    try:
        keep = Course.objects.get(code=keep_code)
    except Course.DoesNotExist:
        print(f'  ⚠️  Keep course not found: {keep_code}')
        return

    for code in remove_codes:
        try:
            remove = Course.objects.get(code=code)
        except Course.DoesNotExist:
            print(f'  ⚠️  Remove course not found: {code} — skipping')
            continue

        # Move resources
        resources = Resource.objects.filter(course=remove)
        r_count = resources.count()
        if r_count:
            resources.update(course=keep)
            print(f'  ✅ Moved {r_count} resource(s) from {code} → {keep_code}')

        # Move placements (only if no conflict)
        for p in CoursePlacement.objects.filter(course=remove):
            conflict = CoursePlacement.objects.filter(
                course=keep,
                department=p.department,
                program=p.program,
                year=p.year,
                period=p.period,
            ).exists()
            if conflict:
                print(f'  ⚠️  Placement conflict — skipping {p.department.name} Y{p.year}T{p.period}')
                p.delete()
            else:
                p.course = keep
                p.save()
                print(f'  ✅ Moved placement: {p.department.name} Y{p.year}T{p.period} → {keep_code}')

        remove.delete()
        print(f'  🗑  Deleted course: {remove.name} ({code})')

print('\n══ Starting course deduplication ══\n')

# ── 1. Business Law ───────────────────────────────────────────────────────────
# Law3012 has 3 resources and placements for Management + Marketing Management
# Law201 has Economics placement, LaW2011 has Accounting & Finance placement
# Keep Law3012, move placements from Law201 and LaW2011 to it
print('1. Business Law')
merge_courses('Law3012', ['Law201', 'LaW2011'])

# ── 2. Business Research Methods ─────────────────────────────────────────────
# Mgmt4022 has 2 resources (Management Y4T2)
# Mgmt3093 has 0 resources (Accounting & Finance Y4T1)
# Keep Mgmt4022, move Accounting & Finance placement to it
print('\n2. Business Research Methods')
merge_courses('Mgmt4022', ['Mgmt3093'])

# ── 3. Cost and Management Accounting II ─────────────────────────────────────
# ACFN3013 has 4 resources (Management Y3T3)
# ACFN212 has 0 resources and no placement — just delete it
print('\n3. Cost and Management Accounting II')
merge_courses('ACFN3013', ['ACFN212'])

# ── 4. Fundamentals of Marketing ─────────────────────────────────────────────
# Mrkt3012 has 1 resource (Economics + Accounting & Finance)
# Mrkt2032 has 0 resources (Management Y2T2)
# Keep Mrkt3012, move Management placement to it
print('\n4. Fundamentals of Marketing')
merge_courses('Mrkt3012', ['Mrkt2032'])

# ── 5. Human Resource Management ─────────────────────────────────────────────
# Mgmt3032 has 5 resources (Marketing Management + Management Y3T2)
# Mgmt4092 has 0 resources (Accounting & Finance Y4T3)
# Keep Mgmt3032, move Accounting & Finance placement to it
print('\n5. Human Resource Management')
merge_courses('Mgmt3032', ['Mgmt4092'])

# ── 6. Inclusiveness ─────────────────────────────────────────────────────────
# SpSc1013 has 3 resources (Economics, Marketing Management, Management)
# SpSc1012 has 0 resources (Accounting & Finance Y2T1)
# Keep SpSc1013, move Accounting & Finance placement to it
print('\n6. Inclusiveness')
merge_courses('SpSc1013', ['SpSc1012'])

# ── 7. Introduction to Computer Technology ───────────────────────────────────
# Comp2013 has 3 resources (Marketing Management, Economics, Management Y2T3)
# Comp105 has 0 resources but Economics Y2T3 — conflicts with Comp2013 placement
# Comp1052 has 0 resources (Accounting & Finance Y2T3)
# Keep Comp2013, remove Comp105 (conflict will be skipped) and Comp1052
print('\n7. Introduction to Computer Technology')
merge_courses('Comp2013', ['Comp105', 'Comp1052'])

# ── 8. Leadership and Change Management ──────────────────────────────────────
# Mgmt3033 has 1 resource (Management Y4T1)
# Mgmt325 has 0 resources and no placement — just delete it
print('\n8. Leadership and Change Management')
merge_courses('Mgmt3033', ['Mgmt325'])

# ── 9. Managerial Statistics ─────────────────────────────────────────────────
# Mgmt3011b has 0 resources (Accounting & Finance + Management Y3T2)
# Mgmt313 has 0 resources and no placement
# Keep Mgmt3011b, delete Mgmt313
print('\n9. Managerial Statistics')
merge_courses('Mgmt3011b', ['Mgmt313'])

# ── 10. Organizational Behavior ──────────────────────────────────────────────
# Mgmt3011 has 2 resources (Marketing Management + Management Y3T1)
# Mgmt226 has 0 resources and no placement — just delete it
print('\n10. Organizational Behavior')
merge_courses('Mgmt3011', ['Mgmt226'])

# ── 11. Physical Fitness ─────────────────────────────────────────────────────
# MCiE1012a has 3 resources (Management Y1T2)
# SpscAF has 0 resources (Accounting & Finance Y2T2)
# SpSc1011 has 0 resources (Marketing Management + Economics Y1T2)
# Keep MCiE1012a, move all placements to it
print('\n11. Physical Fitness')
merge_courses('MCiE1012a', ['SpscAF', 'SpSc1011'])

print('\n══ Deduplication complete ══')
print('\nVerifying — remaining duplicate names:')
from collections import defaultdict
courses = Course.objects.all()
by_name = defaultdict(list)
for c in courses:
    by_name[c.name.strip().lower()].append(c)
remaining = {n: cs for n, cs in by_name.items() if len(cs) > 1}
if remaining:
    for name, cs in sorted(remaining.items()):
        print(f'  Still duplicate: {cs[0].name} — {[c.code for c in cs]}')
else:
    print('  ✅ No duplicate course names remaining!')