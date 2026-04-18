from django.core.management.base import BaseCommand
from apps.content.models import Department, Course, CoursePlacement


class Command(BaseCommand):
    help = 'Seeds the database with initial Unity University data'

    def handle(self, *args, **kwargs):
        self.seed_departments()
        self.seed_subscription_plans()
        self.seed_site_settings()
        self.seed_management_distance_courses()
        self.stdout.write(self.style.SUCCESS('Database seeded successfully.'))

    def seed_departments(self):
        departments = [
            {'name': 'Accounting and Finance', 'level': 'undergraduate', 'description': 'The Department of Accounting and Finance prepares students with strong foundations in financial reporting, auditing, taxation, and financial management.'},
            {'name': 'Economics', 'level': 'undergraduate', 'description': 'The Department of Economics offers rigorous training in micro and macroeconomic theory, econometrics, development economics, and policy analysis.'},
            {'name': 'Business Administration', 'level': 'undergraduate', 'description': 'The Department of Business Administration equips students with comprehensive knowledge of management principles, organizational behavior, strategic planning, and business operations.'},
            {'name': 'Marketing Management', 'level': 'undergraduate', 'description': 'The Department of Marketing Management focuses on consumer behavior, brand management, digital marketing, market research, and sales strategy.'},
            {'name': 'Management', 'level': 'undergraduate', 'description': 'The Department of Management provides students with skills in human resource management, operations, project management, and organizational leadership.'},
            {'name': 'Sociology and Social Anthropology', 'level': 'undergraduate', 'description': 'The Department of Sociology and Social Anthropology explores social structures, cultural practices, community dynamics, and human behavior in society.'},
            {'name': 'Computer Science', 'level': 'undergraduate', 'description': 'The Department of Computer Science provides training in programming, algorithms, data structures, software engineering, networking, and artificial intelligence.'},
            {'name': 'Architecture and Urban Planning', 'level': 'undergraduate', 'description': 'The Department of Architecture and Urban Planning trains students in architectural design, building technology, urban development, and spatial planning.'},
            {'name': 'Civil Engineering', 'level': 'undergraduate', 'description': 'The Department of Civil Engineering covers structural engineering, geotechnical engineering, hydraulics, road and transport engineering, and construction management.'},
            {'name': 'Mining Engineering', 'level': 'undergraduate', 'description': 'The Department of Mining Engineering prepares students for careers in mineral exploration, mine design, extraction technologies, and environmental management.'},
            {'name': 'Construction Technology Management', 'level': 'undergraduate', 'description': 'The Department of Construction Technology Management combines technical construction knowledge with project management skills.'},
            {'name': 'Nursing', 'level': 'undergraduate', 'description': 'The Department of Nursing trains compassionate and competent nurses in clinical practice, patient care, health assessment, and community health.'},
            {'name': 'Public Health', 'level': 'undergraduate', 'description': 'The Department of Public Health focuses on epidemiology, health promotion, disease prevention, environmental health, and health systems management.'},
            {'name': 'Medical Laboratory Sciences', 'level': 'undergraduate', 'description': 'The Department of Medical Laboratory Sciences trains students in clinical chemistry, microbiology, hematology, immunology, and diagnostic techniques.'},
            {'name': 'Business Administration (MBA)', 'level': 'postgraduate', 'description': 'The MBA program develops advanced business leadership and management competencies in finance, strategy, marketing, and operations.'},
            {'name': 'Development Economics', 'level': 'postgraduate', 'description': 'The Department of Development Economics offers advanced study in economic development theories, poverty analysis, policy evaluation, and international development.'},
            {'name': 'Project Management', 'level': 'postgraduate', 'description': 'The Department of Project Management provides advanced training in project planning, risk management, stakeholder engagement, and project evaluation methodologies.'},
        ]
        for dept_data in departments:
            obj, created = Department.objects.update_or_create(
                name=dept_data['name'],
                defaults={'level': dept_data['level'], 'description': dept_data['description']},
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} department: {obj.name}')

    def seed_subscription_plans(self):
        from apps.accounts.models import SubscriptionPlan
        plans = [
            {'plan_id': 'semester', 'name': 'Semester Pass', 'price': 99, 'days': 120, 'description': 'Full access for one semester. Best for Year 1-3 students.', 'badge': 'Most Popular'},
            {'plan_id': 'exit_exam', 'name': 'Exit Exam Pass', 'price': 149, 'days': 90, 'description': 'Full exit exam archive and simulation. Best for Year 3-4.', 'badge': 'Best for Exit Exam'},
            {'plan_id': 'annual', 'name': 'Full Year Pass', 'price': 199, 'days': 365, 'description': 'Full access for an entire year. Best value.', 'badge': 'Best Value'},
        ]
        for plan_data in plans:
            obj, created = SubscriptionPlan.objects.update_or_create(
                plan_id=plan_data['plan_id'],
                defaults=plan_data,
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} plan: {obj.name} — ETB {obj.price}')

    def seed_site_settings(self):
        from apps.accounts.models import SiteSettings
        obj, created = SiteSettings.objects.get_or_create(id=1)
        status = 'Created' if created else 'Already exists'
        self.stdout.write(f'  {status}: Site Settings')

    def seed_management_distance_courses(self):
        management = Department.objects.get(name='Management')
        courses = [
            # YEAR 1 TERM 1
            {'name': 'Communicative English Language Skills I', 'code': 'FLEN1011', 'year': 1, 'period': 1, 'description': 'Develops foundational English language skills in reading, writing, listening and speaking.'},
            {'name': 'Critical Thinking', 'code': 'LoCT1011', 'year': 1, 'period': 1, 'description': 'Introduces students to logical reasoning, argument analysis, and problem solving techniques.'},
            {'name': 'General Psychology', 'code': 'Psyc1011', 'year': 1, 'period': 1, 'description': 'Covers the fundamental principles of human behavior and mental processes.'},
            {'name': 'Mathematics for Social Science', 'code': 'Maths1011', 'year': 1, 'period': 1, 'description': 'Introduces mathematical concepts relevant to social science disciplines.'},
            # YEAR 1 TERM 2
            {'name': 'Communicative English Language Skills II', 'code': 'FLEN1012', 'year': 1, 'period': 2, 'description': 'Builds on FLEN1011 with advanced academic writing, research skills, and oral presentation techniques.'},
            {'name': 'Geography of Ethiopia and the Horn', 'code': 'GES1011', 'year': 1, 'period': 2, 'description': 'Explores the physical and human geography of Ethiopia and the Horn of Africa region.'},
            {'name': 'Introduction to Economics', 'code': 'Econ1011', 'year': 1, 'period': 2, 'description': 'Provides a broad overview of economic principles including supply and demand and market structures.'},
            {'name': 'Social Anthropology', 'code': 'Anth1012', 'year': 1, 'period': 2, 'description': 'Examines human societies and cultures through an anthropological lens.'},
            # YEAR 1 TERM 3
            {'name': 'Entrepreneurship', 'code': 'Mgmt1012', 'year': 1, 'period': 3, 'description': 'Introduces the concepts and practices of entrepreneurship including opportunity identification and business model development.'},
            {'name': 'Global Trends', 'code': 'GlTr1012', 'year': 1, 'period': 3, 'description': 'Examines major global trends shaping the world including technological change and globalization.'},
            {'name': 'Introduction to Emerging Technology', 'code': 'EmTe1012', 'year': 1, 'period': 3, 'description': 'Surveys emerging technologies including artificial intelligence, blockchain, and cloud computing.'},
            {'name': 'Moral and Civic Education', 'code': 'MCiE1012', 'year': 1, 'period': 3, 'description': 'Develops ethical reasoning and civic responsibility among students.'},
            {'name': 'Physical Fitness', 'code': 'SpSc1011', 'year': 1, 'period': 3, 'description': 'Promotes physical health and wellness through structured exercise and sports activities.'},
            # YEAR 2 TERM 1
            {'name': 'Basic Writing Skills (Sophomore English)', 'code': 'Enla201', 'year': 2, 'period': 1, 'description': 'Strengthens academic writing skills with focus on essay structure and paragraph development.'},
            {'name': 'Fundamental of Accounting I', 'code': 'ACFN201', 'year': 2, 'period': 1, 'description': 'Introduces the basic principles of financial accounting including the accounting cycle and journal entries.'},
            {'name': 'History of Ethiopia and the Horn', 'code': 'Hist1012', 'year': 2, 'period': 1, 'description': 'Surveys the history of Ethiopia and the Horn of Africa from ancient civilizations to the modern era.'},
            {'name': 'Inclusiveness', 'code': 'SNIE1012', 'year': 2, 'period': 1, 'description': 'Explores the principles of inclusive development and social equity.'},
            {'name': 'Introduction to Management', 'code': 'Mgmt211', 'year': 2, 'period': 1, 'description': 'Provides a comprehensive introduction to management theory and practice.'},
            # YEAR 2 TERM 2
            {'name': 'Fundamental of Accounting II', 'code': 'ACFN202', 'year': 2, 'period': 2, 'description': 'Continues from ACFN201 covering more complex accounting topics.'},
            {'name': 'Fundamental of Marketing (General)', 'code': 'Mrkt212', 'year': 2, 'period': 2, 'description': 'Introduces core marketing concepts including the marketing mix and consumer behavior.'},
            {'name': 'Introduction to Statistics', 'code': 'Stat192', 'year': 2, 'period': 2, 'description': 'Covers fundamental statistical concepts including descriptive statistics and probability.'},
            {'name': 'Microeconomics I', 'code': 'Econ221', 'year': 2, 'period': 2, 'description': 'Examines the behavior of individual consumers and firms in markets.'},
            # YEAR 2 TERM 3
            {'name': 'Administrative and Business Communication', 'code': 'Mgmt212', 'year': 2, 'period': 3, 'description': 'Develops professional communication skills for business contexts.'},
            {'name': 'Introduction to Computer Technology', 'code': 'Comp105', 'year': 2, 'period': 3, 'description': 'Introduces fundamental computer concepts and practical skills.'},
            {'name': 'Macroeconomics I', 'code': 'Econ231', 'year': 2, 'period': 3, 'description': 'Analyzes the economy as a whole covering national income accounting and economic growth.'},
            {'name': 'Mathematics for Management', 'code': 'Mgmt221', 'year': 2, 'period': 3, 'description': 'Applies mathematical techniques to management problems.'},
            # YEAR 3 TERM 1
            {'name': 'Cost and Management Accounting I', 'code': 'ACFN211', 'year': 3, 'period': 1, 'description': 'Introduces cost accounting systems including job order costing and process costing.'},
            {'name': 'Management Information Systems', 'code': 'Mgmt311', 'year': 3, 'period': 1, 'description': 'Examines how information systems support organizational decision making and operations.'},
            {'name': 'Managerial Statistics', 'code': 'Mgmt313', 'year': 3, 'period': 1, 'description': 'Applies statistical methods to managerial decision making.'},
            {'name': 'Materials Management', 'code': 'Mgmt323', 'year': 3, 'period': 1, 'description': 'Covers the planning and control of materials in organizations.'},
            # YEAR 3 TERM 2
            {'name': 'Cost and Management Accounting II', 'code': 'ACFN212', 'year': 3, 'period': 2, 'description': 'Advances cost accounting topics including standard costing and variance analysis.'},
            {'name': 'Intermediate Financial Accounting', 'code': 'Acct231', 'year': 3, 'period': 2, 'description': 'Covers intermediate level financial accounting topics including revenue recognition.'},
            {'name': 'Leadership and Change Management', 'code': 'Mgmt325', 'year': 3, 'period': 2, 'description': 'Examines leadership theories, styles, and practices in organizational contexts.'},
            {'name': 'Organizational Behavior', 'code': 'Mgmt226', 'year': 3, 'period': 2, 'description': 'Studies human behavior in organizational settings at individual, group, and organizational levels.'},
            # YEAR 3 TERM 3
            {'name': 'Basic Financial Management', 'code': 'Mgmt413', 'year': 3, 'period': 3, 'description': 'Introduces corporate financial management including time value of money and capital budgeting.'},
            {'name': 'Business Ethics and Social Responsibility', 'code': 'Mgmt412', 'year': 3, 'period': 3, 'description': 'Explores ethical frameworks and their application to business decision making.'},
            {'name': 'Development Economics', 'code': 'Econ365', 'year': 3, 'period': 3, 'description': 'Analyzes theories and policies related to economic development in developing countries.'},
            {'name': 'Global Marketing Management', 'code': 'Mgmt326', 'year': 3, 'period': 3, 'description': 'Examines marketing strategies in international and global contexts.'},
            {'name': 'Operations Research', 'code': 'Mgmt411', 'year': 3, 'period': 3, 'description': 'Applies quantitative methods to organizational decision problems.'},
            # YEAR 4 TERM 1
            {'name': 'Business Research Methods', 'code': 'Mgmt324', 'year': 4, 'period': 1, 'description': 'Covers the principles and methods of business research.'},
            {'name': 'Managerial Economics', 'code': 'Mgmt414', 'year': 4, 'period': 1, 'description': 'Applies microeconomic theory to managerial decision making.'},
            {'name': 'Strategic Management', 'code': 'Mgmt422', 'year': 4, 'period': 1, 'description': 'Examines how organizations formulate and implement competitive strategies.'},
            {'name': 'System Analysis and Design', 'code': 'Mgmt421', 'year': 4, 'period': 1, 'description': 'Covers methodologies for analyzing and designing information systems in organizations.'},
            # YEAR 4 TERM 2
            {'name': 'Financial Markets and Institutions', 'code': 'ACFN423', 'year': 4, 'period': 2, 'description': 'Examines the structure and functions of financial markets and institutions.'},
            {'name': 'Operations Management', 'code': 'Mgmt423', 'year': 4, 'period': 2, 'description': 'Covers the design and management of production and service operations.'},
            {'name': 'Project Management', 'code': 'Mgmt425', 'year': 4, 'period': 2, 'description': 'Provides comprehensive training in project planning, scheduling, budgeting, and risk management.'},
            {'name': 'Senior Essay in Management', 'code': 'Mgmt426', 'year': 4, 'period': 2, 'description': 'A capstone research project where students independently investigate a management problem.'},
            # YEAR 4 TERM 3
            {'name': 'Advanced Entrepreneurship and Enterprise Management', 'code': 'Mgmt424', 'year': 4, 'period': 3, 'description': 'Advances entrepreneurship concepts with focus on venture creation and business plan development.'},
            {'name': 'Business Law', 'code': 'Law201', 'year': 4, 'period': 3, 'description': 'Introduces the legal framework governing business activities in Ethiopia.'},
            {'name': 'Human Resource Management', 'code': 'Mgmt322', 'year': 4, 'period': 3, 'description': 'Covers the management of human resources in organizations.'},
            {'name': 'Risk Management and Insurance', 'code': 'Mgmt321', 'year': 4, 'period': 3, 'description': 'Examines risk identification, assessment, and mitigation strategies for organizations.'},
        ]

        for data in courses:
            course, course_created = Course.objects.update_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'description': data['description'],
                },
            )
            placement, placement_created = CoursePlacement.objects.get_or_create(
                course=course,
                department=management,
                program='distance',
                year=data['year'],
                period=data['period'],
            )
            course_status = 'Created' if course_created else 'Exists'
            placement_status = 'Created' if placement_created else 'Exists'
            self.stdout.write(
                f'  [{course_status}] {course.name} '
                f'| Placement [{placement_status}] '
                f'Y{data["year"]} T{data["period"]}'
            )