from django.core.management.base import BaseCommand
from apps.content.models import Department, Course, CoursePlacement


class Command(BaseCommand):
    help = 'Seeds the database with initial Unity University data'

    def handle(self, *args, **kwargs):
        self.seed_departments()
        self.seed_subscription_plans()
        self.seed_site_settings()
        self.seed_management_distance_courses()
        self.seed_marketing_management_distance_courses()
        self.seed_economics_distance_courses()
        self.seed_accounting_finance_distance_courses()
        self.stdout.write(self.style.SUCCESS('Database seeded successfully.'))

    # ── Helper ────────────────────────────────────────────────────────────────

    def _seed_courses(self, department, courses):
        """Generic helper to seed courses and placements for a department."""
        for data in courses:
            course, course_created = Course.objects.update_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'description': data.get('description', ''),
                },
            )
            placement, placement_created = CoursePlacement.objects.get_or_create(
                course=course,
                department=department,
                program='distance',
                year=data['year'],
                period=data['period'],
            )
            course_status     = 'Created' if course_created     else 'Exists'
            placement_status  = 'Created' if placement_created  else 'Exists'
            self.stdout.write(
                f'  [{course_status}] {course.name} '
                f'| Placement [{placement_status}] '
                f'Y{data["year"]} T{data["period"]}'
            )

    # ── Departments ───────────────────────────────────────────────────────────

    def seed_departments(self):
        departments = [
            {'name': 'Accounting and Finance',          'level': 'undergraduate', 'description': 'The Department of Accounting and Finance prepares students with strong foundations in financial reporting, auditing, taxation, and financial management.'},
            {'name': 'Economics',                        'level': 'undergraduate', 'description': 'The Department of Economics offers rigorous training in micro and macroeconomic theory, econometrics, development economics, and policy analysis.'},
            {'name': 'Business Administration',          'level': 'undergraduate', 'description': 'The Department of Business Administration equips students with comprehensive knowledge of management principles, organizational behavior, strategic planning, and business operations.'},
            {'name': 'Marketing Management',             'level': 'undergraduate', 'description': 'The Department of Marketing Management focuses on consumer behavior, brand management, digital marketing, market research, and sales strategy.'},
            {'name': 'Management',                       'level': 'undergraduate', 'description': 'The Department of Management provides students with skills in human resource management, operations, project management, and organizational leadership.'},
            {'name': 'Sociology and Social Anthropology','level': 'undergraduate', 'description': 'The Department of Sociology and Social Anthropology explores social structures, cultural practices, community dynamics, and human behavior in society.'},
            {'name': 'Computer Science',                 'level': 'undergraduate', 'description': 'The Department of Computer Science provides training in programming, algorithms, data structures, software engineering, networking, and artificial intelligence.'},
            {'name': 'Architecture and Urban Planning',  'level': 'undergraduate', 'description': 'The Department of Architecture and Urban Planning trains students in architectural design, building technology, urban development, and spatial planning.'},
            {'name': 'Civil Engineering',                'level': 'undergraduate', 'description': 'The Department of Civil Engineering covers structural engineering, geotechnical engineering, hydraulics, road and transport engineering, and construction management.'},
            {'name': 'Mining Engineering',               'level': 'undergraduate', 'description': 'The Department of Mining Engineering prepares students for careers in mineral exploration, mine design, extraction technologies, and environmental management.'},
            {'name': 'Construction Technology Management','level': 'undergraduate','description': 'The Department of Construction Technology Management combines technical construction knowledge with project management skills.'},
            {'name': 'Nursing',                          'level': 'undergraduate', 'description': 'The Department of Nursing trains compassionate and competent nurses in clinical practice, patient care, health assessment, and community health.'},
            {'name': 'Public Health',                    'level': 'undergraduate', 'description': 'The Department of Public Health focuses on epidemiology, health promotion, disease prevention, environmental health, and health systems management.'},
            {'name': 'Medical Laboratory Sciences',      'level': 'undergraduate', 'description': 'The Department of Medical Laboratory Sciences trains students in clinical chemistry, microbiology, hematology, immunology, and diagnostic techniques.'},
            {'name': 'Business Administration (MBA)',    'level': 'postgraduate',  'description': 'The MBA program develops advanced business leadership and management competencies in finance, strategy, marketing, and operations.'},
            {'name': 'Development Economics',            'level': 'postgraduate',  'description': 'The Department of Development Economics offers advanced study in economic development theories, poverty analysis, policy evaluation, and international development.'},
            {'name': 'Project Management',               'level': 'postgraduate',  'description': 'The Department of Project Management provides advanced training in project planning, risk management, stakeholder engagement, and project evaluation methodologies.'},
        ]
        for dept_data in departments:
            obj, created = Department.objects.update_or_create(
                name=dept_data['name'],
                defaults={'level': dept_data['level'], 'description': dept_data['description']},
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} department: {obj.name}')

    # ── Subscription plans ────────────────────────────────────────────────────

    def seed_subscription_plans(self):
        from apps.accounts.models import SubscriptionPlan
        plans = [
            {'plan_id': 'semester',  'name': 'Semester Pass',  'price': 99,  'days': 120, 'description': 'Full access for one semester. Best for Year 1-3 students.',  'badge': 'Most Popular'},
            {'plan_id': 'exit_exam', 'name': 'Exit Exam Pass', 'price': 149, 'days': 90,  'description': 'Full exit exam archive and simulation. Best for Year 3-4.',   'badge': 'Best for Exit Exam'},
            {'plan_id': 'annual',    'name': 'Full Year Pass', 'price': 199, 'days': 365, 'description': 'Full access for an entire year. Best value.',                  'badge': 'Best Value'},
        ]
        for plan_data in plans:
            obj, created = SubscriptionPlan.objects.update_or_create(
                plan_id=plan_data['plan_id'],
                defaults=plan_data,
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} plan: {obj.name} — ETB {obj.price}')

    # ── Site settings ─────────────────────────────────────────────────────────

    def seed_site_settings(self):
        from apps.accounts.models import SiteSettings
        obj, created = SiteSettings.objects.get_or_create(id=1)
        status = 'Created' if created else 'Already exists'
        self.stdout.write(f'  {status}: Site Settings')

    # ── Management (Distance) ─────────────────────────────────────────────────

    def seed_management_distance_courses(self):
        self.stdout.write('\n── Management (Distance) ──────────────────────────')
        dept = Department.objects.get(name='Management')
        courses = [
            # YEAR 1 TERM 1
            {'name': 'Communicative English Language Skills I',  'code': 'FLEN1011',  'year': 1, 'period': 1, 'description': 'Develops foundational English language skills in reading, writing, listening and speaking.'},
            {'name': 'Critical Thinking',                         'code': 'LoCT1011',  'year': 1, 'period': 1, 'description': 'Introduces students to logical reasoning, argument analysis, and problem solving techniques.'},
            {'name': 'General Psychology',                        'code': 'Psyc1011',  'year': 1, 'period': 1, 'description': 'Covers the fundamental principles of human behavior and mental processes.'},
            {'name': 'Mathematics for Social Science',            'code': 'Math1011',  'year': 1, 'period': 1, 'description': 'Introduces mathematical concepts relevant to social science disciplines.'},
            # YEAR 1 TERM 2
            {'name': 'Communicative English Language Skills II',  'code': 'FLEN1012',  'year': 1, 'period': 2, 'description': 'Builds on FLEN1011 with advanced academic writing, research skills, and oral presentation techniques.'},
            {'name': 'Geography of Ethiopian and the Horn',       'code': 'GeES1012',  'year': 1, 'period': 2, 'description': 'Explores the physical and human geography of Ethiopia and the Horn of Africa region.'},
            {'name': 'Economics',                                 'code': 'Econ1012',  'year': 1, 'period': 2, 'description': 'Provides a broad overview of economic principles including supply and demand and market structures.'},
            {'name': 'Social Anthropology',                       'code': 'Anth1012',  'year': 1, 'period': 2, 'description': 'Examines human societies and cultures through an anthropological lens.'},
            {'name': 'Physical Fitness',                          'code': 'MCiE1012a', 'year': 1, 'period': 2, 'description': 'Promotes physical health and wellness through structured exercise and sports activities.'},
            # YEAR 1 TERM 3
            {'name': 'Inclusiveness',                             'code': 'SpSc1013',  'year': 1, 'period': 3, 'description': 'Explores the principles of inclusive development and social equity.'},
            {'name': 'Global Trends',                             'code': 'GiTr1013',  'year': 1, 'period': 3, 'description': 'Examines major global trends shaping the world including technological change and globalization.'},
            {'name': 'Introduction to Emerging Technology',       'code': 'EmTel1013', 'year': 1, 'period': 3, 'description': 'Surveys emerging technologies including artificial intelligence, blockchain, and cloud computing.'},
            {'name': 'History of Ethiopia and the Horn',          'code': 'Hist1013',  'year': 1, 'period': 3, 'description': 'Surveys the history of Ethiopia and the Horn of Africa from ancient civilizations to the modern era.'},
            {'name': 'Moral and Civic Education',                 'code': 'MCiE1012',  'year': 1, 'period': 3, 'description': 'Develops ethical reasoning and civic responsibility among students.'},
            # YEAR 2 TERM 1
            {'name': 'Introduction to Management',                'code': 'Mgmt2011',  'year': 2, 'period': 1, 'description': 'Provides a comprehensive introduction to management theory and practice.'},
            {'name': 'Entrepreneurship',                          'code': 'MGMT1013',  'year': 2, 'period': 1, 'description': 'Introduces the concepts and practices of entrepreneurship.'},
            {'name': 'Microeconomics',                            'code': 'Econ2011',  'year': 2, 'period': 1, 'description': 'Examines the behavior of individual consumers and firms in markets.'},
            {'name': 'Fundamentals of Accounting I',              'code': 'ACFN2011',  'year': 2, 'period': 1, 'description': 'Introduces the basic principles of financial accounting.'},
            # YEAR 2 TERM 2
            {'name': 'Fundamentals of Marketing',                 'code': 'Mrkt2032',  'year': 2, 'period': 2, 'description': 'Introduces core marketing concepts including the marketing mix and consumer behavior.'},
            {'name': 'Fundamentals of Accounting II',             'code': 'ACFN2012',  'year': 2, 'period': 2, 'description': 'Continues from ACFN2011 covering more complex accounting topics.'},
            {'name': 'Administrative & Business Communication',   'code': 'Mgmt2021',  'year': 2, 'period': 2, 'description': 'Develops professional communication skills for business contexts.'},
            {'name': 'Macroeconomics',                            'code': 'Econ2022',  'year': 2, 'period': 2, 'description': 'Analyzes the economy as a whole covering national income accounting and economic growth.'},
            # YEAR 2 TERM 3
            {'name': 'Managerial Statistics I',                   'code': 'Mgmt2032',  'year': 2, 'period': 3, 'description': 'Applies statistical methods to managerial decision making.'},
            {'name': 'Mathematics for Management',                'code': 'Mgmt2013',  'year': 2, 'period': 3, 'description': 'Applies mathematical techniques to management problems.'},
            {'name': 'Basic Writing Skills',                      'code': 'Enla2013',  'year': 2, 'period': 3, 'description': 'Strengthens academic writing skills with focus on essay structure and paragraph development.'},
            {'name': 'Introduction to Computer Technology',       'code': 'Comp2013',  'year': 2, 'period': 3, 'description': 'Introduces fundamental computer concepts and practical skills.'},
            # YEAR 3 TERM 1
            {'name': 'Introduction to Business',                  'code': 'Mgmt2043',  'year': 3, 'period': 1, 'description': 'Overview of business operations, environments, and functions.'},
            {'name': 'Cost and Management Accounting I',          'code': 'ACFN3011',  'year': 3, 'period': 1, 'description': 'Introduces cost accounting systems including job order and process costing.'},
            {'name': 'Organizational Behavior',                   'code': 'Mgmt3011',  'year': 3, 'period': 1, 'description': 'Studies human behavior in organizational settings.'},
            {'name': 'Managerial Statistics II',                  'code': 'Mgmt3021',  'year': 3, 'period': 1, 'description': 'Advanced statistical methods for managerial decision making.'},
            # YEAR 3 TERM 2
            {'name': 'Management Information System',             'code': 'Mgmt3011b', 'year': 3, 'period': 2, 'description': 'Examines how information systems support organizational decision making.'},
            {'name': 'Human Resource Management',                 'code': 'Mgmt3032',  'year': 3, 'period': 2, 'description': 'Covers the management of human resources in organizations.'},
            {'name': 'Intermediate Financial Accounting',         'code': 'ACFN3122',  'year': 3, 'period': 2, 'description': 'Covers intermediate level financial accounting topics.'},
            {'name': 'Business Law',                              'code': 'Law3012',   'year': 3, 'period': 2, 'description': 'Introduces the legal framework governing business activities in Ethiopia.'},
            # YEAR 3 TERM 3
            {'name': 'Cost and Management Accounting II',         'code': 'ACFN3013',  'year': 3, 'period': 3, 'description': 'Advanced cost accounting including standard costing and variance analysis.'},
            {'name': 'International Marketing',                   'code': 'Mrkt3033',  'year': 3, 'period': 3, 'description': 'Examines marketing strategies in international and global contexts.'},
            {'name': 'Materials Management',                      'code': 'Mgmt3042',  'year': 3, 'period': 3, 'description': 'Covers the planning and control of materials in organizations.'},
            {'name': 'Risk Management and Insurance',             'code': 'Mgmt3013',  'year': 3, 'period': 3, 'description': 'Examines risk identification, assessment, and mitigation strategies.'},
            # YEAR 4 TERM 1
            {'name': 'Basic Financial Management',                'code': 'Mgmt4051',  'year': 4, 'period': 1, 'description': 'Introduces corporate financial management including capital budgeting.'},
            {'name': 'Operations Research',                       'code': 'Mgmt4011',  'year': 4, 'period': 1, 'description': 'Applies quantitative methods to organizational decision problems.'},
            {'name': 'Business Ethics and Social Responsibility', 'code': 'Mgmt4021',  'year': 4, 'period': 1, 'description': 'Explores ethical frameworks and their application to business decision making.'},
            {'name': 'Leadership and Change Management',          'code': 'Mgmt3033',  'year': 4, 'period': 1, 'description': 'Examines leadership theories, styles, and practices in organizational contexts.'},
            # YEAR 4 TERM 2
            {'name': 'System Analysis and Design',                'code': 'Mgmt4031',  'year': 4, 'period': 2, 'description': 'Covers methodologies for analyzing and designing information systems.'},
            {'name': 'Business Research Methods',                 'code': 'Mgmt4022',  'year': 4, 'period': 2, 'description': 'Covers the principles and methods of business research.'},
            {'name': 'Financial Market & Institution',            'code': 'Mgmt4052',  'year': 4, 'period': 2, 'description': 'Examines the structure and functions of financial markets and institutions.'},
            {'name': 'Operations Management',                     'code': 'Mgmt4023',  'year': 4, 'period': 2, 'description': 'Covers the design and management of production and service operations.'},
            # YEAR 4 TERM 3
            {'name': 'Strategic Management',                      'code': 'Mgmt4012',  'year': 4, 'period': 3, 'description': 'Examines how organizations formulate and implement competitive strategies.'},
            {'name': 'Managerial Economics',                      'code': 'Mgmt4042',  'year': 4, 'period': 3, 'description': 'Applies microeconomic theory to managerial decision making.'},
            {'name': 'Strategic Entrepreneurship',                'code': 'Mgmt4033',  'year': 4, 'period': 3, 'description': 'Advances entrepreneurship concepts with focus on venture creation.'},
            {'name': 'Project Management',                        'code': 'Mgmt4043',  'year': 4, 'period': 3, 'description': 'Comprehensive training in project planning, scheduling, budgeting, and risk management.'},
            {'name': 'Senior Essay in Management',                'code': 'Mgmt4063',  'year': 4, 'period': 3, 'description': 'A capstone research project in management.'},
        ]
        self._seed_courses(dept, courses)

    # ── Marketing Management (Distance) ───────────────────────────────────────

    def seed_marketing_management_distance_courses(self):
        self.stdout.write('\n── Marketing Management (Distance) ───────────────')
        dept = Department.objects.get(name='Marketing Management')
        courses = [
            # YEAR 1 TERM 1
            {'name': 'Communicative English Language Skills I',  'code': 'FLEN1011',  'year': 1, 'period': 1, 'description': 'Develops foundational English language skills.'},
            {'name': 'General Psychology',                        'code': 'Psyc1011',  'year': 1, 'period': 1, 'description': 'Covers the fundamental principles of human behavior and mental processes.'},
            {'name': 'Mathematics for Social Science',            'code': 'Math1011',  'year': 1, 'period': 1, 'description': 'Introduces mathematical concepts relevant to social science disciplines.'},
            {'name': 'Critical Thinking',                         'code': 'LoCT1011',  'year': 1, 'period': 1, 'description': 'Introduces students to logical reasoning and problem solving techniques.'},
            # YEAR 1 TERM 2
            {'name': 'Economics',                                 'code': 'Econ1012',  'year': 1, 'period': 2, 'description': 'Provides a broad overview of economic principles.'},
            {'name': 'Geography of Ethiopian and the Horn',       'code': 'GeES1012',  'year': 1, 'period': 2, 'description': 'Explores the physical and human geography of Ethiopia and the Horn of Africa.'},
            {'name': 'Communicative English Language Skills II',  'code': 'FLEN1012',  'year': 1, 'period': 2, 'description': 'Advanced academic writing, research skills, and oral presentation.'},
            {'name': 'Social Anthropology',                       'code': 'Anth1012',  'year': 1, 'period': 2, 'description': 'Examines human societies and cultures through an anthropological lens.'},
            {'name': 'Physical Fitness',                          'code': 'SpSc1011',  'year': 1, 'period': 2, 'description': 'Promotes physical health and wellness through structured exercise.'},
            # YEAR 1 TERM 3
            {'name': 'Inclusiveness',                             'code': 'SpSc1013',  'year': 1, 'period': 3, 'description': 'Explores the principles of inclusive development and social equity.'},
            {'name': 'Global Trends',                             'code': 'GiTr1013',  'year': 1, 'period': 3, 'description': 'Examines major global trends shaping the world.'},
            {'name': 'Introduction to Emerging Technology',       'code': 'EmTel1013', 'year': 1, 'period': 3, 'description': 'Surveys emerging technologies including AI, blockchain, and cloud computing.'},
            {'name': 'History of Ethiopia and the Horn',          'code': 'Hist1013',  'year': 1, 'period': 3, 'description': 'Surveys the history of Ethiopia and the Horn of Africa.'},
            {'name': 'Moral and Civic Education',                 'code': 'MCiE1012',  'year': 1, 'period': 3, 'description': 'Develops ethical reasoning and civic responsibility among students.'},
            # YEAR 2 TERM 1
            {'name': 'Entrepreneurship',                          'code': 'MGMT1013',  'year': 2, 'period': 1, 'description': 'Introduces entrepreneurship including opportunity identification and business model development.'},
            {'name': 'Introduction to Management',                'code': 'Mgmt2011',  'year': 2, 'period': 1, 'description': 'Provides a comprehensive introduction to management theory and practice.'},
            {'name': 'Microeconomics',                            'code': 'Econ2011',  'year': 2, 'period': 1, 'description': 'Examines the behavior of individual consumers and firms in markets.'},
            {'name': 'Fundamentals of Accounting I',              'code': 'ACFN2011',  'year': 2, 'period': 1, 'description': 'Introduces the basic principles of financial accounting.'},
            # YEAR 2 TERM 2
            {'name': 'Principle of Marketing I',                  'code': 'Mrkt2011',  'year': 2, 'period': 2, 'description': 'Introduces core principles of marketing including the marketing mix.'},
            {'name': 'Fundamentals of Accounting II',             'code': 'ACFN2012',  'year': 2, 'period': 2, 'description': 'Continues from ACFN2011 covering more complex accounting topics.'},
            {'name': 'Managerial Statistics I',                   'code': 'Mgmt2032',  'year': 2, 'period': 2, 'description': 'Covers fundamental statistical concepts for managerial decision making.'},
            {'name': 'Macroeconomics',                            'code': 'Econ2022',  'year': 2, 'period': 2, 'description': 'Analyzes the economy as a whole.'},
            # YEAR 2 TERM 3
            {'name': 'Consumer Behavior',                         'code': 'Mrkt2023',  'year': 2, 'period': 3, 'description': 'Examines how consumers make purchasing decisions.'},
            {'name': 'Mathematics for Management',                'code': 'Mgmt2013',  'year': 2, 'period': 3, 'description': 'Applies mathematical techniques to management problems.'},
            {'name': 'Principle of Marketing II',                 'code': 'Mrkt2012',  'year': 2, 'period': 3, 'description': 'Advanced marketing principles building on Mrkt2011.'},
            {'name': 'Introduction to Computer Technology',       'code': 'Comp2013',  'year': 2, 'period': 3, 'description': 'Introduces fundamental computer concepts and practical skills.'},
            # YEAR 3 TERM 1
            {'name': 'Business/Industrial Marketing',             'code': 'Mrkt3011',  'year': 3, 'period': 1, 'description': 'Covers marketing strategies in business and industrial contexts.'},
            {'name': 'Basic Writing Skills',                      'code': 'Enla2013',  'year': 3, 'period': 1, 'description': 'Strengthens academic writing skills.'},
            {'name': 'Organizational Behavior',                   'code': 'Mgmt3011',  'year': 3, 'period': 1, 'description': 'Studies human behavior in organizational settings.'},
            {'name': 'Managerial Statistics II',                  'code': 'Mgmt3021',  'year': 3, 'period': 1, 'description': 'Advanced statistical methods for managerial decision making.'},
            # YEAR 3 TERM 2
            {'name': 'Agricultural & Commodity Marketing',        'code': 'Mrkt3021',  'year': 3, 'period': 2, 'description': 'Covers marketing of agricultural products and commodities.'},
            {'name': 'Human Resource Management',                 'code': 'Mgmt3032',  'year': 3, 'period': 2, 'description': 'Covers the management of human resources in organizations.'},
            {'name': 'Cost & Managerial Accounting',              'code': 'ACFN3112',  'year': 3, 'period': 2, 'description': 'Covers cost accounting and managerial accounting concepts.'},
            {'name': 'Business Law',                              'code': 'Law3012',   'year': 3, 'period': 2, 'description': 'Introduces the legal framework governing business activities.'},
            # YEAR 3 TERM 3
            {'name': 'Hospitality and Tourism Marketing',         'code': 'Mrkt3022',  'year': 3, 'period': 3, 'description': 'Covers marketing strategies for hospitality and tourism sectors.'},
            {'name': 'International Marketing',                   'code': 'Mrkt3033',  'year': 3, 'period': 3, 'description': 'Examines marketing strategies in international contexts.'},
            {'name': 'Service Marketing & Customer Relationship Management', 'code': 'Mrkt3043', 'year': 3, 'period': 3, 'description': 'Covers service marketing and customer relationship strategies.'},
            {'name': 'Risk Management and Insurance',             'code': 'Mgmt3013',  'year': 3, 'period': 3, 'description': 'Examines risk identification, assessment, and mitigation strategies.'},
            # YEAR 4 TERM 1
            {'name': 'Product and Brand Marketing',               'code': 'Mrkt4041',  'year': 4, 'period': 1, 'description': 'Covers product development and brand management strategies.'},
            {'name': 'Basic Financial Management',                'code': 'Mgmt4051',  'year': 4, 'period': 1, 'description': 'Introduces corporate financial management.'},
            {'name': 'Marketing Research',                        'code': 'Mrkt4011',  'year': 4, 'period': 1, 'description': 'Covers research methods and techniques applied to marketing problems.'},
            {'name': 'Sales Management & Salesmanship',           'code': 'Mrkt3023',  'year': 4, 'period': 1, 'description': 'Covers sales management principles and personal selling techniques.'},
            # YEAR 4 TERM 2
            {'name': 'E-Marketing',                               'code': 'Mrkt4042',  'year': 4, 'period': 2, 'description': 'Covers digital marketing strategies including social media and SEO.'},
            {'name': 'Integrated Marketing Communication',        'code': 'Mrkt4052',  'year': 4, 'period': 2, 'description': 'Covers advertising, promotion, and integrated communication strategies.'},
            {'name': 'Marketing Information System',              'code': 'Mrkt4012',  'year': 4, 'period': 2, 'description': 'Examines information systems used in marketing decision making.'},
            {'name': 'Marketing Channel and Logistic Management', 'code': 'Mrkt4031',  'year': 4, 'period': 2, 'description': 'Covers distribution channels and logistics management.'},
            # YEAR 4 TERM 3
            {'name': 'Social Marketing and Marketing Ethics',     'code': 'Mrkt4022',  'year': 4, 'period': 3, 'description': 'Examines ethical issues and social responsibility in marketing.'},
            {'name': 'Senior Essay in Marketing Management',      'code': 'Mrkt4023',  'year': 4, 'period': 3, 'description': 'A capstone research project in marketing management.'},
            {'name': 'Strategic Marketing Management',            'code': 'Mrkt4033',  'year': 4, 'period': 3, 'description': 'Examines strategic planning and implementation in marketing.'},
            {'name': 'Strategic Entrepreneurship',                'code': 'Mgmt4033',  'year': 4, 'period': 3, 'description': 'Advances entrepreneurship concepts with focus on venture creation.'},
            {'name': 'Operations Management',                     'code': 'Mgmt4023',  'year': 4, 'period': 3, 'description': 'Covers the design and management of production and service operations.'},
        ]
        self._seed_courses(dept, courses)

    # ── Economics (Distance) ──────────────────────────────────────────────────

    def seed_economics_distance_courses(self):
        self.stdout.write('\n── Economics (Distance) ───────────────────────────')
        dept = Department.objects.get(name='Economics')
        courses = [
            # YEAR 1 TERM 1
            {'name': 'Communicative English Language Skills I',  'code': 'FLEN1011',  'year': 1, 'period': 1, 'description': 'Develops foundational English language skills.'},
            {'name': 'General Psychology',                        'code': 'Psyc1011',  'year': 1, 'period': 1, 'description': 'Covers the fundamental principles of human behavior and mental processes.'},
            {'name': 'Mathematics for Social Science',            'code': 'Math1011',  'year': 1, 'period': 1, 'description': 'Introduces mathematical concepts relevant to social science disciplines.'},
            {'name': 'Critical Thinking',                         'code': 'LoCT1011',  'year': 1, 'period': 1, 'description': 'Introduces logical reasoning and problem solving techniques.'},
            # YEAR 1 TERM 2
            {'name': 'Communicative English Language Skills II',  'code': 'FLEN1012',  'year': 1, 'period': 2, 'description': 'Advanced academic writing, research skills, and oral presentation.'},
            {'name': 'Economics',                                 'code': 'Econ1012',  'year': 1, 'period': 2, 'description': 'Broad overview of economic principles including supply and demand.'},
            {'name': 'Geography of Ethiopian and the Horn',       'code': 'GeES1012',  'year': 1, 'period': 2, 'description': 'Explores the physical and human geography of Ethiopia and the Horn.'},
            {'name': 'Social Anthropology',                       'code': 'Anth1012',  'year': 1, 'period': 2, 'description': 'Examines human societies and cultures through an anthropological lens.'},
            {'name': 'Physical Fitness',                          'code': 'SpSc1011',  'year': 1, 'period': 2, 'description': 'Promotes physical health and wellness through structured exercise.'},
            # YEAR 1 TERM 3
            {'name': 'Entrepreneurship',                          'code': 'MGMT1013',  'year': 1, 'period': 3, 'description': 'Introduces entrepreneurship and business model development.'},
            {'name': 'Introduction to Emerging Technology',       'code': 'EmTel1013', 'year': 1, 'period': 3, 'description': 'Surveys emerging technologies including AI, blockchain, and cloud computing.'},
            {'name': 'Moral and Civic Education',                 'code': 'MCiE1012',  'year': 1, 'period': 3, 'description': 'Develops ethical reasoning and civic responsibility.'},
            {'name': 'Global Trends',                             'code': 'GiTr1013',  'year': 1, 'period': 3, 'description': 'Examines major global trends shaping the world.'},
            {'name': 'History of Ethiopia and the Horn',          'code': 'Hist1013',  'year': 1, 'period': 3, 'description': 'Surveys the history of Ethiopia and the Horn of Africa.'},
            # YEAR 2 TERM 1
            {'name': 'Fundamentals of Accounting I',              'code': 'ACFN2011',  'year': 2, 'period': 1, 'description': 'Introduces the basic principles of financial accounting.'},
            {'name': 'Introduction to Management',                'code': 'Mgmt2011',  'year': 2, 'period': 1, 'description': 'Provides a comprehensive introduction to management theory and practice.'},
            {'name': 'Basic Writing Skills',                      'code': 'Enla2013',  'year': 2, 'period': 1, 'description': 'Strengthens academic writing skills.'},
            {'name': 'Inclusiveness',                             'code': 'SpSc1013',  'year': 2, 'period': 1, 'description': 'Explores the principles of inclusive development and social equity.'},
            # YEAR 2 TERM 2
            {'name': 'Fundamentals of Accounting II',             'code': 'ACFN2012',  'year': 2, 'period': 2, 'description': 'Continues from ACFN2011 covering more complex accounting topics.'},
            {'name': 'Introduction to Statistics',                'code': 'Stat1092',  'year': 2, 'period': 2, 'description': 'Covers fundamental statistical concepts and probability.'},
            {'name': 'Microeconomics',                            'code': 'Econ2011',  'year': 2, 'period': 2, 'description': 'Examines the behavior of individual consumers and firms in markets.'},
            {'name': 'Fundamentals of Marketing',                 'code': 'Mrkt3012',  'year': 2, 'period': 2, 'description': 'Introduces core marketing concepts.'},
            # YEAR 2 TERM 3
            {'name': 'Calculus for Economists',                   'code': 'Econ211',   'year': 2, 'period': 3, 'description': 'Applies calculus to economic analysis.'},
            {'name': 'Macroeconomics I',                          'code': 'Econ231',   'year': 2, 'period': 3, 'description': 'Analyzes the economy as a whole covering national income accounting.'},
            {'name': 'Introduction to Computer Technology',       'code': 'Comp105',   'year': 2, 'period': 3, 'description': 'Introduces fundamental computer concepts and practical skills.'},
            {'name': 'Micro-Economics II',                        'code': 'Econ222',   'year': 2, 'period': 3, 'description': 'Advanced microeconomic theory and analysis.'},
            # YEAR 3 TERM 1
            {'name': 'Linear Algebra for Economists',             'code': 'Econ212',   'year': 3, 'period': 1, 'description': 'Covers linear algebra methods applied to economic problems.'},
            {'name': 'Macro-Economics II',                        'code': 'Econ232',   'year': 3, 'period': 1, 'description': 'Advanced macroeconomic theory and policy analysis.'},
            {'name': 'Statistics for Economists',                 'code': 'Econ242',   'year': 3, 'period': 1, 'description': 'Statistical methods and their application in economics.'},
            {'name': 'Research Method for Economists',            'code': 'Econ336',   'year': 3, 'period': 1, 'description': 'Research methodologies and techniques used in economics.'},
            # YEAR 3 TERM 2
            {'name': 'International Economics I',                 'code': 'Econ381',   'year': 3, 'period': 2, 'description': 'Examines theories of international trade and finance.'},
            {'name': 'Econometrics I',                            'code': 'Econ361',   'year': 3, 'period': 2, 'description': 'Applies statistical methods to economic data.'},
            {'name': 'Natural Resource & Environmental Economics','code': 'Econ410',   'year': 3, 'period': 2, 'description': 'Examines economics of natural resources and environmental issues.'},
            {'name': 'Development Economics',                     'code': 'Econ371',   'year': 3, 'period': 2, 'description': 'Analyzes theories and policies related to economic development.'},
            # YEAR 3 TERM 3
            {'name': 'Econometrics II',                           'code': 'Econ362',   'year': 3, 'period': 3, 'description': 'Advanced econometric methods and applications.'},
            {'name': 'Development Economics II',                  'code': 'Econ372',   'year': 3, 'period': 3, 'description': 'Advanced topics in development economics.'},
            {'name': 'International Economics II',                'code': 'Econ382',   'year': 3, 'period': 3, 'description': 'Advanced international trade and finance topics.'},
            {'name': 'Economics of Industry',                     'code': 'Econ312',   'year': 3, 'period': 3, 'description': 'Examines industrial organization, market structure, and competition policy.'},
            # YEAR 4 TERM 1
            {'name': 'Economics of Agriculture',                  'code': 'Econ311',   'year': 4, 'period': 1, 'description': 'Examines the economics of agricultural production and markets.'},
            {'name': 'Labor Economics',                           'code': 'Econ310',   'year': 4, 'period': 1, 'description': 'Studies labor markets, wages, employment, and human capital.'},
            {'name': 'Computer Application in Economics',         'code': 'Econ263',   'year': 4, 'period': 1, 'description': 'Applies computer tools and software to economic analysis.'},
            {'name': 'History of Economic Thought I',             'code': 'Econ441',   'year': 4, 'period': 1, 'description': 'Surveys the history of economic ideas from ancient times to the 19th century.'},
            # YEAR 4 TERM 2
            {'name': 'Development Planning & Project Analysis I', 'code': 'Econ431',   'year': 4, 'period': 2, 'description': 'Covers development planning and project appraisal methods.'},
            {'name': 'Monetary Economics: Theory & Policy',       'code': 'Econ421',   'year': 4, 'period': 2, 'description': 'Examines monetary theory, banking systems, and monetary policy.'},
            {'name': 'Seminar & Senior Project in Economics I',   'code': 'Econ451',   'year': 4, 'period': 2, 'description': 'First part of the senior research project in economics.'},
            {'name': 'History of Economic Thought II',            'code': 'Econ442',   'year': 4, 'period': 2, 'description': 'Surveys modern economic thought from the 20th century to present.'},
            # YEAR 4 TERM 3
            {'name': 'Public Finance',                            'code': 'Econ422',   'year': 4, 'period': 3, 'description': 'Examines government spending, taxation, and public debt.'},
            {'name': 'Development Planning & Project Analysis II','code': 'Econ432',   'year': 4, 'period': 3, 'description': 'Advanced development planning and project evaluation.'},
            {'name': 'Seminar & Senior Project in Economics II',  'code': 'Econ452',   'year': 4, 'period': 3, 'description': 'Completion and presentation of the senior research project.'},
            {'name': 'Business Law',                              'code': 'Law201',    'year': 4, 'period': 3, 'description': 'Introduces the legal framework governing business activities in Ethiopia.'},
        ]
        self._seed_courses(dept, courses)

    # ── Accounting & Finance (Distance) ───────────────────────────────────────

    def seed_accounting_finance_distance_courses(self):
        self.stdout.write('\n── Accounting & Finance (Distance) ───────────────')
        dept = Department.objects.get(name='Accounting and Finance')
        courses = [
            # YEAR 1 TERM 1
            {'name': 'Communicative English Language Skills I',  'code': 'FLEN1011',  'year': 1, 'period': 1, 'description': 'Develops foundational English language skills.'},
            {'name': 'General Psychology',                        'code': 'Psyc1011',  'year': 1, 'period': 1, 'description': 'Covers the fundamental principles of human behavior and mental processes.'},
            {'name': 'Mathematics for Social Science',            'code': 'Math1011',  'year': 1, 'period': 1, 'description': 'Introduces mathematical concepts relevant to social science disciplines.'},
            {'name': 'Critical Thinking',                         'code': 'LoCT1011',  'year': 1, 'period': 1, 'description': 'Introduces logical reasoning and problem solving techniques.'},
            # YEAR 1 TERM 2
            {'name': 'Communicative English Language Skills II',  'code': 'FLEN1012',  'year': 1, 'period': 2, 'description': 'Advanced academic writing, research skills, and oral presentation.'},
            {'name': 'Economics',                                 'code': 'Econ1012',  'year': 1, 'period': 2, 'description': 'Broad overview of economic principles.'},
            {'name': 'Geography of Ethiopian and the Horn',       'code': 'GeES1012',  'year': 1, 'period': 2, 'description': 'Explores the physical and human geography of Ethiopia and the Horn.'},
            {'name': 'Social Anthropology',                       'code': 'Anth1012',  'year': 1, 'period': 2, 'description': 'Examines human societies and cultures through an anthropological lens.'},
            # YEAR 1 TERM 3
            {'name': 'Entrepreneurship',                          'code': 'MGMT1013',  'year': 1, 'period': 3, 'description': 'Introduces entrepreneurship and business model development.'},
            {'name': 'Introduction to Emerging Technology',       'code': 'EmTel1013', 'year': 1, 'period': 3, 'description': 'Surveys emerging technologies including AI, blockchain, and cloud computing.'},
            {'name': 'Moral and Civic Education',                 'code': 'MCiE1012',  'year': 1, 'period': 3, 'description': 'Develops ethical reasoning and civic responsibility.'},
            {'name': 'Global Trends',                             'code': 'GiTr1013',  'year': 1, 'period': 3, 'description': 'Examines major global trends shaping the world.'},
            {'name': 'Microeconomics',                            'code': 'Econ2011',  'year': 1, 'period': 3, 'description': 'Examines the behavior of individual consumers and firms.'},
            # YEAR 2 TERM 1
            {'name': 'Fundamentals of Accounting I',              'code': 'ACFN2011',  'year': 2, 'period': 1, 'description': 'Introduces the basic principles of financial accounting.'},
            {'name': 'Introduction to Management',                'code': 'Mgmt2011',  'year': 2, 'period': 1, 'description': 'Provides a comprehensive introduction to management theory and practice.'},
            {'name': 'Basic Writing Skills',                      'code': 'Enla2013',  'year': 2, 'period': 1, 'description': 'Strengthens academic writing skills.'},
            {'name': 'Inclusiveness',                             'code': 'SpSc1012',  'year': 2, 'period': 1, 'description': 'Explores the principles of inclusive development and social equity.'},
            # YEAR 2 TERM 2
            {'name': 'Fundamentals of Accounting II',             'code': 'ACFN2012',  'year': 2, 'period': 2, 'description': 'Continues from ACFN2011 covering more complex accounting topics.'},
            {'name': 'Physical Fitness',                          'code': 'SpscAF',    'year': 2, 'period': 2, 'description': 'Promotes physical health and wellness.'},
            {'name': 'History of Ethiopian & the Horn',           'code': 'Hist1013',  'year': 2, 'period': 2, 'description': 'Surveys the history of Ethiopia and the Horn of Africa.'},
            {'name': 'Fundamentals of Marketing',                 'code': 'Mrkt3012',  'year': 2, 'period': 2, 'description': 'Introduces core marketing concepts.'},
            # YEAR 2 TERM 3
            {'name': 'Mathematics for Management',                'code': 'Mgmt2013',  'year': 2, 'period': 3, 'description': 'Applies mathematical techniques to management problems.'},
            {'name': 'Macroeconomics',                            'code': 'Econ2022',  'year': 2, 'period': 3, 'description': 'Analyzes the economy as a whole.'},
            {'name': 'Introduction to Computer Technology',       'code': 'Comp1052',  'year': 2, 'period': 3, 'description': 'Introduces fundamental computer concepts and practical skills.'},
            {'name': 'Intermediate Financial Accounting I',       'code': 'ACFN3021',  'year': 2, 'period': 3, 'description': 'Covers intermediate level financial accounting topics.'},
            # YEAR 3 TERM 1
            {'name': 'Cost & Management Accounting I',            'code': 'ACFN3011',  'year': 3, 'period': 1, 'description': 'Introduces cost accounting systems.'},
            {'name': 'Financial Management I',                    'code': 'ACFN3041',  'year': 3, 'period': 1, 'description': 'Covers corporate financial management and capital budgeting.'},
            {'name': 'Introduction to Statistics',                'code': 'Stat1092',  'year': 3, 'period': 1, 'description': 'Covers fundamental statistical concepts and probability.'},
            {'name': 'Intermediate Financial Accounting II',      'code': 'ACFN3022',  'year': 3, 'period': 1, 'description': 'Advanced intermediate financial accounting.'},
            # YEAR 3 TERM 2
            {'name': 'Cost & Management Accounting II',           'code': 'ACFN3012',  'year': 3, 'period': 2, 'description': 'Advanced cost accounting including standard costing.'},
            {'name': 'Accounting Software Applications',          'code': 'ACFN3031',  'year': 3, 'period': 2, 'description': 'Covers accounting software tools used in practice.'},
            {'name': 'Managerial Statistics',                     'code': 'Mgmt3011b', 'year': 3, 'period': 2, 'description': 'Applies statistical methods to managerial decision making.'},
            {'name': 'Financial Management II',                   'code': 'ACFN3042',  'year': 3, 'period': 2, 'description': 'Advanced financial management topics.'},
            # YEAR 3 TERM 3
            {'name': 'Auditing Principles & Practices I',         'code': 'ACFN3072',  'year': 3, 'period': 3, 'description': 'Covers principles and practices of auditing.'},
            {'name': 'Accounting Information System',             'code': 'ACFN3032',  'year': 3, 'period': 3, 'description': 'Covers accounting information systems design and use.'},
            {'name': 'Money & Banking Practices',                 'code': 'ACFN311',   'year': 3, 'period': 3, 'description': 'Examines money, banking systems, and monetary policy.'},
            {'name': 'Government & Non-Profit Accounting',        'code': 'ACFN3052',  'year': 3, 'period': 3, 'description': 'Covers accounting for government and non-profit organizations.'},
            # YEAR 4 TERM 1
            {'name': 'Business Research Methods',                 'code': 'Mgmt3093',  'year': 4, 'period': 1, 'description': 'Covers the principles and methods of business research.'},
            {'name': 'Auditing Principles & Practices II',        'code': 'ACFN3073',  'year': 4, 'period': 1, 'description': 'Advanced auditing principles and practices.'},
            {'name': 'Public Finance & Taxation',                 'code': 'ACFN4031',  'year': 4, 'period': 1, 'description': 'Examines government finance, taxation, and public expenditure.'},
            {'name': 'Investment Analysis & Portfolio Management','code': 'ACFN4041',  'year': 4, 'period': 1, 'description': 'Covers investment analysis and portfolio management strategies.'},
            # YEAR 4 TERM 2
            {'name': 'Project Analysis & Evaluation',             'code': 'ACFN4051',  'year': 4, 'period': 2, 'description': 'Covers project appraisal and evaluation methods.'},
            {'name': 'Federal Government of Ethiopian Accounting','code': 'ACFN4053',  'year': 4, 'period': 2, 'description': 'Covers accounting standards and practices for the Ethiopian government.'},
            {'name': 'Financial Markets & Institutions',          'code': 'ACFN4082',  'year': 4, 'period': 2, 'description': 'Examines the structure and functions of financial markets and institutions.'},
            {'name': 'Advanced Financial Accounting I',           'code': 'ACFN4011',  'year': 4, 'period': 2, 'description': 'Advanced financial accounting topics and standards.'},
            # YEAR 4 TERM 3
            {'name': 'Advanced Financial Accounting II',          'code': 'ACFN4012',  'year': 4, 'period': 3, 'description': 'Advanced financial accounting including consolidation and reporting.'},
            {'name': 'Business Law',                              'code': 'LaW2011',   'year': 4, 'period': 3, 'description': 'Introduces the legal framework governing business activities in Ethiopia.'},
            {'name': 'Human Resource Management',                 'code': 'Mgmt4092',  'year': 4, 'period': 3, 'description': 'Covers the management of human resources in organizations.'},
            {'name': 'Risk Management & Insurance',               'code': 'Mgmt3062',  'year': 4, 'period': 3, 'description': 'Examines risk identification, assessment, and mitigation strategies.'},
            {'name': 'Senior Essay',                              'code': 'ACFN4072',  'year': 4, 'period': 3, 'description': 'A capstone research project in accounting and finance.'},
        ]
        self._seed_courses(dept, courses)