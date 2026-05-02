
"""
apps/content/management/commands/fix_duplicate_courses.py

One-time command to merge old incorrectly coded courses into
the correct ones from the updated seed_data.py.

Usage:
    python manage.py fix_duplicate_courses
    python manage.py fix_duplicate_courses --dry-run
"""

from django.core.management.base import BaseCommand
from apps.content.models import Course, CoursePlacement


OLD_TO_NEW = [
    ('Maths1011', 'Math1011'),
    ('GES1011',   'GeES1012'),
    ('Econ1011',  'Econ1012'),
    ('Mgmt1012',  'MGMT1013'),
    ('GlTr1012',  'GiTr1013'),
    ('EmTe1012',  'EmTel1013'),
    ('Hist1012',  'Hist1013'),
    ('SpSc1011',  'SpSc1013'),
    ('Enla201',   'Enla2013'),
    ('ACFN201',   'ACFN2011'),
    ('ACFN202',   'ACFN2012'),
    ('Mgmt211',   'Mgmt2011'),
    ('Mrkt212',   'Mrkt2032'),
    ('Stat192',   'Stat1092'),
    ('Econ221',   'Econ2011'),
    ('Mgmt212',   'Mgmt2013'),
    ('Comp105',   'Comp2013'),
    ('Econ231',   'Econ2022'),
    ('Mgmt221',   'Mgmt2032'),
    ('SNIE1012',  'SpSc1013'),
    ('Acct231',   'ACFN3122'),
    ('Mgmt413',   'Mgmt4051'),
    ('Mgmt412',   'Mgmt4021'),
    ('Mgmt411',   'Mgmt4011'),
    ('Econ365',   'Econ371'),
    ('Mgmt326',   'Mrkt3033'),
    ('Mgmt324',   'Mgmt4022'),
    ('Mgmt414',   'Mgmt4042'),
    ('Mgmt422',   'Mgmt4012'),
    ('Mgmt421',   'Mgmt4031'),
    ('ACFN423',   'Mgmt4052'),
    ('Mgmt423',   'Mgmt4023'),
    ('Mgmt425',   'Mgmt4043'),
    ('Mgmt426',   'Mgmt4063'),
    ('Mgmt424',   'Mgmt4033'),
    ('Mgmt322',   'Mgmt3032'),
    ('Mgmt321',   'Mgmt3013'),
]


class Command(BaseCommand):
    help = 'Merges old incorrectly coded duplicate courses into the correct ones.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        fixed   = 0
        renamed = 0
        skipped = 0

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY RUN] No changes will be made.\n'))

        for old_code, new_code in OLD_TO_NEW:
            old = Course.objects.filter(code=old_code).first()
            new = Course.objects.filter(code=new_code).first()

            if not old:
                # Old code doesn't exist — nothing to fix
                continue

            if new:
                # Both exist — merge old into new
                placements = CoursePlacement.objects.filter(course=old)
                moved    = 0
                deleted  = 0

                for p in placements:
                    conflict = CoursePlacement.objects.filter(
                        course=new,
                        department=p.department,
                        program=p.program,
                        year=p.year,
                        period=p.period,
                    ).exists()

                    if conflict:
                        # Placement already exists on new course — delete duplicate
                        if not dry_run:
                            p.delete()
                        deleted += 1
                    else:
                        # No conflict — move placement to new course
                        if not dry_run:
                            p.course = new
                            p.save()
                        moved += 1

                if not dry_run:
                    old.delete()

                self.stdout.write(self.style.SUCCESS(
                    f'{"Would fix" if dry_run else "Fixed"}: '
                    f'{old_code} → {new_code} '
                    f'(moved {moved} placements, deleted {deleted} duplicates)'
                ))
                fixed += 1

            else:
                # Old exists but new doesn't — just rename the code
                if not dry_run:
                    old.code = new_code
                    old.save()

                self.stdout.write(self.style.SUCCESS(
                    f'{"Would rename" if dry_run else "Renamed"}: '
                    f'{old_code} → {new_code}'
                ))
                renamed += 1

        self.stdout.write('\n' + '─' * 50)
        self.stdout.write(self.style.SUCCESS(
            f'Done.\n'
            f'  Merged  : {fixed}\n'
            f'  Renamed : {renamed}\n'
            f'  Skipped : {skipped} (already clean)\n'
        ))