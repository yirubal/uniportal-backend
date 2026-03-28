from django.core.management.base import BaseCommand
from apps.content.models import Department, Course, CoursePlacement


class Command(BaseCommand):
    help = 'Seeds the database with initial Unity University data'

    def handle(self, *args, **kwargs):
        self.seed_departments()
        self.seed_management_distance_courses()
        self.stdout.write(self.style.SUCCESS('Database seeded successfully.'))

    def seed_departments(self):
        departments = [
            {
                'name': 'Accounting and Finance',
                'level': 'undergraduate',
                'description': (
                    'The Department of Accounting and Finance prepares students with '
                    'strong foundations in financial reporting, auditing, taxation, '
                    'and financial management. Graduates are equipped for careers in '
                    'banking, auditing firms, public institutions, and corporate finance.'
                ),
            },
            {
                'name': 'Economics',
                'level': 'undergraduate',
                'description': (
                    'The Department of Economics offers rigorous training in micro and '
                    'macroeconomic theory, econometrics, development economics, and '
                    'policy analysis. Students develop analytical skills to understand '
                    'and address economic challenges in Ethiopia and beyond.'
                ),
            },
            {
                'name': 'Business Administration',
                'level': 'undergraduate',
                'description': (
                    'The Department of Business Administration equips students with '
                    'comprehensive knowledge of management principles, organizational '
                    'behavior, strategic planning, and business operations. Graduates '
                    'are prepared for leadership roles across all sectors of the economy.'
                ),
            },
            {
                'name': 'Marketing Management',
                'level': 'undergraduate',
                'description': (
                    'The Department of Marketing Management focuses on consumer behavior, '
                    'brand management, digital marketing, market research, and sales '
                    'strategy. Students learn to create and deliver value in competitive '
                    'local and global markets.'
                ),
            },
            {
                'name': 'Management',
                'level': 'undergraduate',
                'description': (
                    'The Department of Management provides students with skills in '
                    'human resource management, operations, project management, and '
                    'organizational leadership. Graduates are equipped to manage teams '
                    'and drive performance in diverse work environments.'
                ),
            },
            {
                'name': 'Sociology and Social Anthropology',
                'level': 'undergraduate',
                'description': (
                    'The Department of Sociology and Social Anthropology explores '
                    'social structures, cultural practices, community dynamics, and '
                    'human behavior in society. Students develop critical thinking '
                    'skills for roles in research, development organizations, and '
                    'public policy.'
                ),
            },
            {
                'name': 'Computer Science',
                'level': 'undergraduate',
                'description': (
                    'The Department of Computer Science provides training in programming, '
                    'algorithms, data structures, software engineering, networking, and '
                    'artificial intelligence. Graduates are prepared for careers in '
                    'software development, systems analysis, and technology innovation '
                    'in Ethiopia and globally.'
                ),
            },
            {
                'name': 'Architecture and Urban Planning',
                'level': 'undergraduate',
                'description': (
                    'The Department of Architecture and Urban Planning trains students '
                    'in architectural design, building technology, urban development, '
                    'and spatial planning. Graduates contribute to shaping sustainable '
                    'cities and well-designed built environments across Ethiopia.'
                ),
            },
            {
                'name': 'Civil Engineering',
                'level': 'undergraduate',
                'description': (
                    'The Department of Civil Engineering covers structural engineering, '
                    'geotechnical engineering, hydraulics, road and transport engineering, '
                    'and construction management. Graduates play a key role in Ethiopia\'s '
                    'infrastructure development and construction sector.'
                ),
            },
            {
                'name': 'Mining Engineering',
                'level': 'undergraduate',
                'description': (
                    'The Department of Mining Engineering prepares students for careers '
                    'in mineral exploration, mine design, extraction technologies, and '
                    'environmental management of mining operations. Ethiopia\'s rich '
                    'mineral resources make this a highly strategic field of study.'
                ),
            },
            {
                'name': 'Construction Technology Management',
                'level': 'undergraduate',
                'description': (
                    'The Department of Construction Technology Management combines '
                    'technical construction knowledge with project management skills. '
                    'Students learn to plan, execute, and oversee construction projects '
                    'efficiently and safely in Ethiopia\'s growing construction industry.'
                ),
            },
            {
                'name': 'Nursing',
                'level': 'undergraduate',
                'description': (
                    'The Department of Nursing trains compassionate and competent nurses '
                    'in clinical practice, patient care, health assessment, and community '
                    'health. Graduates serve in hospitals, health centers, and community '
                    'settings across Ethiopia contributing to improved public health outcomes.'
                ),
            },
            {
                'name': 'Public Health',
                'level': 'undergraduate',
                'description': (
                    'The Department of Public Health focuses on epidemiology, health '
                    'promotion, disease prevention, environmental health, and health '
                    'systems management. Students are prepared to design and implement '
                    'programs that improve the health of communities and populations.'
                ),
            },
            {
                'name': 'Medical Laboratory Sciences',
                'level': 'undergraduate',
                'description': (
                    'The Department of Medical Laboratory Sciences trains students in '
                    'clinical chemistry, microbiology, hematology, immunology, and '
                    'diagnostic techniques. Graduates play a critical role in disease '
                    'diagnosis and monitoring in Ethiopia\'s healthcare system.'
                ),
            },
            {
                'name': 'Business Administration (MBA)',
                'level': 'postgraduate',
                'description': (
                    'The MBA program develops advanced business leadership and management '
                    'competencies in finance, strategy, marketing, and operations. '
                    'Designed for working professionals seeking to accelerate their '
                    'careers and take on senior leadership responsibilities.'
                ),
            },
            {
                'name': 'Development Economics',
                'level': 'postgraduate',
                'description': (
                    'The Department of Development Economics offers advanced study in '
                    'economic development theories, poverty analysis, policy evaluation, '
                    'and international development. Graduates contribute to research '
                    'institutions, government ministries, and development organizations.'
                ),
            },
            {
                'name': 'Project Management',
                'level': 'postgraduate',
                'description': (
                    'The Department of Project Management provides advanced training in '
                    'project planning, risk management, stakeholder engagement, and '
                    'project evaluation methodologies. Graduates lead complex projects '
                    'across government, NGOs, and the private sector.'
                ),
            },
        ]

        for dept_data in departments:
            obj, created = Department.objects.update_or_create(
                name=dept_data['name'],
                defaults={
                    'level': dept_data['level'],
                    'description': dept_data['description'],
                },
            )
            status = 'Created' if created else 'Updated'
            self.stdout.write(f'  {status} department: {obj.name}')

    def seed_management_distance_courses(self):
        management = Department.objects.get(name='Management')

        courses = [
            # YEAR 1 TERM 1
            {
                'name': 'Communicative English Language Skills I',
                'code': 'FLEN1011',
                'year': 1,
                'period': 1,
                'description': (
                    'Develops foundational English language skills in reading, writing, '
                    'listening and speaking. Students build academic vocabulary and '
                    'communication skills needed for university level study.'
                ),
            },
            {
                'name': 'Critical Thinking',
                'code': 'LoCT1011',
                'year': 1,
                'period': 1,
                'description': (
                    'Introduces students to logical reasoning, argument analysis, and '
                    'problem solving techniques. Students learn to evaluate information '
                    'critically and make sound judgments in academic and professional contexts.'
                ),
            },
            {
                'name': 'General Psychology',
                'code': 'Psyc1011',
                'year': 1,
                'period': 1,
                'description': (
                    'Covers the fundamental principles of human behavior and mental processes '
                    'including perception, cognition, emotion, motivation, and personality. '
                    'Provides a foundation for understanding people in social and work settings.'
                ),
            },
            {
                'name': 'Mathematics for Social Science',
                'code': 'Maths1011',
                'year': 1,
                'period': 1,
                'description': (
                    'Introduces mathematical concepts relevant to social science disciplines '
                    'including basic algebra, functions, statistics, and quantitative reasoning. '
                    'Prepares students for data analysis and research methods courses.'
                ),
            },

            # YEAR 1 TERM 2
            {
                'name': 'Communicative English Language Skills II',
                'code': 'FLEN1012',
                'year': 1,
                'period': 2,
                'description': (
                    'Builds on FLEN1011 with advanced academic writing, research skills, '
                    'and oral presentation techniques. Students develop the ability to '
                    'produce well-structured academic essays and reports.'
                ),
            },
            {
                'name': 'Geography of Ethiopia and the Horn',
                'code': 'GES1011',
                'year': 1,
                'period': 2,
                'description': (
                    'Explores the physical and human geography of Ethiopia and the Horn '
                    'of Africa region. Topics include climate, natural resources, population '
                    'distribution, regional development, and geopolitical dynamics.'
                ),
            },
            {
                'name': 'Introduction to Economics',
                'code': 'Econ1011',
                'year': 1,
                'period': 2,
                'description': (
                    'Provides a broad overview of economic principles including supply and '
                    'demand, market structures, national income, inflation, and fiscal policy. '
                    'Lays the groundwork for more advanced economics and business courses.'
                ),
            },
            {
                'name': 'Social Anthropology',
                'code': 'Anth1012',
                'year': 1,
                'period': 2,
                'description': (
                    'Examines human societies and cultures through an anthropological lens. '
                    'Topics include kinship, religion, ritual, social organization, and '
                    'cultural change with emphasis on Ethiopian and African societies.'
                ),
            },

            # YEAR 1 TERM 3
            {
                'name': 'Entrepreneurship',
                'code': 'Mgmt1012',
                'year': 1,
                'period': 3,
                'description': (
                    'Introduces the concepts and practices of entrepreneurship including '
                    'opportunity identification, business model development, and innovation. '
                    'Students develop entrepreneurial mindsets applicable to any career path.'
                ),
            },
            {
                'name': 'Global Trends',
                'code': 'GlTr1012',
                'year': 1,
                'period': 3,
                'description': (
                    'Examines major global trends shaping the world including technological '
                    'change, globalization, climate change, demographic shifts, and geopolitical '
                    'developments. Students analyze implications for business and society.'
                ),
            },
            {
                'name': 'Introduction to Emerging Technology',
                'code': 'EmTe1012',
                'year': 1,
                'period': 3,
                'description': (
                    'Surveys emerging technologies including artificial intelligence, blockchain, '
                    'cloud computing, and the Internet of Things. Students explore how these '
                    'technologies are transforming industries and creating new opportunities.'
                ),
            },
            {
                'name': 'Moral and Civic Education',
                'code': 'MCiE1012',
                'year': 1,
                'period': 3,
                'description': (
                    'Develops ethical reasoning and civic responsibility among students. '
                    'Topics include Ethiopian constitutional rights, civic duties, professional '
                    'ethics, and the role of citizens in democratic governance.'
                ),
            },
            {
                'name': 'Physical Fitness',
                'code': 'SpSc1011',
                'year': 1,
                'period': 3,
                'description': (
                    'Promotes physical health and wellness through structured exercise and '
                    'sports activities. Students develop healthy lifestyle habits and learn '
                    'the importance of physical activity for personal and professional well-being.'
                ),
            },

            # YEAR 2 TERM 1
            {
                'name': 'Basic Writing Skills (Sophomore English)',
                'code': 'Enla201',
                'year': 2,
                'period': 1,
                'description': (
                    'Strengthens academic writing skills with focus on essay structure, '
                    'paragraph development, and research-based writing. Students practice '
                    'writing for academic and professional purposes at an intermediate level.'
                ),
            },
            {
                'name': 'Fundamental of Accounting I',
                'code': 'ACFN201',
                'year': 2,
                'period': 1,
                'description': (
                    'Introduces the basic principles of financial accounting including the '
                    'accounting cycle, journal entries, ledger accounts, trial balance, and '
                    'preparation of basic financial statements for business entities.'
                ),
            },
            {
                'name': 'History of Ethiopia and the Horn',
                'code': 'Hist1012',
                'year': 2,
                'period': 1,
                'description': (
                    'Surveys the history of Ethiopia and the Horn of Africa from ancient '
                    'civilizations to the modern era. Topics include kingdoms, colonialism, '
                    'independence movements, and contemporary political developments.'
                ),
            },
            {
                'name': 'Inclusiveness',
                'code': 'SNIE1012',
                'year': 2,
                'period': 1,
                'description': (
                    'Explores the principles of inclusive development and social equity. '
                    'Students examine issues of gender, disability, ethnicity, and marginalization '
                    'and learn strategies for building inclusive organizations and communities.'
                ),
            },
            {
                'name': 'Introduction to Management',
                'code': 'Mgmt211',
                'year': 2,
                'period': 1,
                'description': (
                    'Provides a comprehensive introduction to management theory and practice. '
                    'Topics include planning, organizing, leading, and controlling within '
                    'organizations along with the historical evolution of management thought.'
                ),
            },

            # YEAR 2 TERM 2
            {
                'name': 'Fundamental of Accounting II',
                'code': 'ACFN202',
                'year': 2,
                'period': 2,
                'description': (
                    'Continues from ACFN201 covering more complex accounting topics including '
                    'inventory valuation, depreciation, receivables, payables, and preparation '
                    'of complete financial statements with adjusting entries.'
                ),
            },
            {
                'name': 'Fundamental of Marketing (General)',
                'code': 'Mrkt212',
                'year': 2,
                'period': 2,
                'description': (
                    'Introduces core marketing concepts including the marketing mix, consumer '
                    'behavior, market segmentation, targeting, and positioning. Students learn '
                    'how organizations create value and communicate it to customers.'
                ),
            },
            {
                'name': 'Introduction to Statistics',
                'code': 'Stat192',
                'year': 2,
                'period': 2,
                'description': (
                    'Covers fundamental statistical concepts including data collection, '
                    'descriptive statistics, probability, sampling distributions, and '
                    'basic hypothesis testing. Prepares students for quantitative research.'
                ),
            },
            {
                'name': 'Microeconomics I',
                'code': 'Econ221',
                'year': 2,
                'period': 2,
                'description': (
                    'Examines the behavior of individual consumers and firms in markets. '
                    'Topics include demand and supply analysis, elasticity, consumer theory, '
                    'production theory, cost analysis, and market structures.'
                ),
            },

            # YEAR 2 TERM 3
            {
                'name': 'Administrative and Business Communication',
                'code': 'Mgmt212',
                'year': 2,
                'period': 3,
                'description': (
                    'Develops professional communication skills for business contexts. '
                    'Topics include business writing, report preparation, meeting management, '
                    'presentation skills, and effective interpersonal communication at work.'
                ),
            },
            {
                'name': 'Introduction to Computer Technology',
                'code': 'Comp105',
                'year': 2,
                'period': 3,
                'description': (
                    'Introduces fundamental computer concepts and practical skills including '
                    'operating systems, word processing, spreadsheets, databases, and internet '
                    'use. Prepares students for technology use in professional environments.'
                ),
            },
            {
                'name': 'Macroeconomics I',
                'code': 'Econ231',
                'year': 2,
                'period': 3,
                'description': (
                    'Analyzes the economy as a whole covering national income accounting, '
                    'economic growth, unemployment, inflation, fiscal policy, monetary policy, '
                    'and the role of government in managing macroeconomic stability.'
                ),
            },
            {
                'name': 'Mathematics for Management',
                'code': 'Mgmt221',
                'year': 2,
                'period': 3,
                'description': (
                    'Applies mathematical techniques to management problems including linear '
                    'programming, matrix algebra, financial mathematics, and optimization. '
                    'Develops quantitative reasoning skills for managerial decision making.'
                ),
            },

            # YEAR 3 TERM 1
            {
                'name': 'Cost and Management Accounting I',
                'code': 'ACFN211',
                'year': 3,
                'period': 1,
                'description': (
                    'Introduces cost accounting systems including job order costing, process '
                    'costing, and cost behavior analysis. Students learn to use cost information '
                    'for managerial planning and control decisions.'
                ),
            },
            {
                'name': 'Management Information Systems',
                'code': 'Mgmt311',
                'year': 3,
                'period': 1,
                'description': (
                    'Examines how information systems support organizational decision making '
                    'and operations. Topics include database management, systems analysis, '
                    'ERP systems, and the strategic use of information technology in business.'
                ),
            },
            {
                'name': 'Managerial Statistics',
                'code': 'Mgmt313',
                'year': 3,
                'period': 1,
                'description': (
                    'Applies statistical methods to managerial decision making. Topics include '
                    'regression analysis, time series forecasting, decision theory, and '
                    'statistical quality control for operations management.'
                ),
            },
            {
                'name': 'Materials Management',
                'code': 'Mgmt323',
                'year': 3,
                'period': 1,
                'description': (
                    'Covers the planning and control of materials in organizations including '
                    'procurement, inventory management, warehousing, and supply chain '
                    'coordination. Students learn techniques for optimizing material flows.'
                ),
            },

            # YEAR 3 TERM 2
            {
                'name': 'Cost and Management Accounting II',
                'code': 'ACFN212',
                'year': 3,
                'period': 2,
                'description': (
                    'Advances cost accounting topics including standard costing, variance '
                    'analysis, activity based costing, budgeting, and performance measurement. '
                    'Focuses on using accounting data for strategic management decisions.'
                ),
            },
            {
                'name': 'Intermediate Financial Accounting',
                'code': 'Acct231',
                'year': 3,
                'period': 2,
                'description': (
                    'Covers intermediate level financial accounting topics including '
                    'revenue recognition, long term assets, liabilities, equity transactions, '
                    'and preparation of comprehensive financial statements under IFRS standards.'
                ),
            },
            {
                'name': 'Leadership and Change Management',
                'code': 'Mgmt325',
                'year': 3,
                'period': 2,
                'description': (
                    'Examines leadership theories, styles, and practices in organizational '
                    'contexts. Students learn how to lead teams effectively, manage resistance '
                    'to change, and drive organizational transformation successfully.'
                ),
            },
            {
                'name': 'Organizational Behavior',
                'code': 'Mgmt226',
                'year': 3,
                'period': 2,
                'description': (
                    'Studies human behavior in organizational settings at individual, group, '
                    'and organizational levels. Topics include motivation, group dynamics, '
                    'conflict resolution, organizational culture, and workplace diversity.'
                ),
            },

            # YEAR 3 TERM 3
            {
                'name': 'Basic Financial Management',
                'code': 'Mgmt413',
                'year': 3,
                'period': 3,
                'description': (
                    'Introduces corporate financial management including time value of money, '
                    'capital budgeting, cost of capital, working capital management, and '
                    'basic financial analysis for business investment decisions.'
                ),
            },
            {
                'name': 'Business Ethics and Social Responsibility',
                'code': 'Mgmt412',
                'year': 3,
                'period': 3,
                'description': (
                    'Explores ethical frameworks and their application to business decision '
                    'making. Topics include corporate social responsibility, stakeholder theory, '
                    'sustainability, and ethical leadership in Ethiopian and global contexts.'
                ),
            },
            {
                'name': 'Development Economics',
                'code': 'Econ365',
                'year': 3,
                'period': 3,
                'description': (
                    'Analyzes theories and policies related to economic development in '
                    'developing countries. Topics include poverty, inequality, agricultural '
                    'development, industrialization, and Ethiopia\'s development strategies.'
                ),
            },
            {
                'name': 'Global Marketing Management',
                'code': 'Mgmt326',
                'year': 3,
                'period': 3,
                'description': (
                    'Examines marketing strategies in international and global contexts. '
                    'Topics include market entry strategies, cross cultural consumer behavior, '
                    'global branding, pricing, and distribution in international markets.'
                ),
            },
            {
                'name': 'Operations Research',
                'code': 'Mgmt411',
                'year': 3,
                'period': 3,
                'description': (
                    'Applies quantitative methods to organizational decision problems. '
                    'Topics include linear programming, transportation models, network analysis, '
                    'queuing theory, and simulation for operations management decisions.'
                ),
            },

            # YEAR 4 TERM 1
            {
                'name': 'Business Research Methods',
                'code': 'Mgmt324',
                'year': 4,
                'period': 1,
                'description': (
                    'Covers the principles and methods of business research including research '
                    'design, data collection, qualitative and quantitative analysis, and '
                    'research report writing. Prepares students for the senior essay.'
                ),
            },
            {
                'name': 'Managerial Economics',
                'code': 'Mgmt414',
                'year': 4,
                'period': 1,
                'description': (
                    'Applies microeconomic theory to managerial decision making. Topics include '
                    'demand analysis, production and cost optimization, pricing strategies, '
                    'market analysis, and economic forecasting for business managers.'
                ),
            },
            {
                'name': 'Strategic Management',
                'code': 'Mgmt422',
                'year': 4,
                'period': 1,
                'description': (
                    'Examines how organizations formulate and implement competitive strategies. '
                    'Topics include environmental analysis, competitive advantage, business '
                    'level strategy, corporate strategy, and strategic leadership.'
                ),
            },
            {
                'name': 'System Analysis and Design',
                'code': 'Mgmt421',
                'year': 4,
                'period': 1,
                'description': (
                    'Covers methodologies for analyzing and designing information systems in '
                    'organizations. Students learn requirements gathering, process modeling, '
                    'system design, and project management for system development.'
                ),
            },

            # YEAR 4 TERM 2
            {
                'name': 'Financial Markets and Institutions',
                'code': 'ACFN423',
                'year': 4,
                'period': 2,
                'description': (
                    'Examines the structure and functions of financial markets and institutions. '
                    'Topics include money markets, capital markets, banking, insurance, '
                    'and the role of the National Bank of Ethiopia in the financial system.'
                ),
            },
            {
                'name': 'Operations Management',
                'code': 'Mgmt423',
                'year': 4,
                'period': 2,
                'description': (
                    'Covers the design and management of production and service operations. '
                    'Topics include process design, capacity planning, quality management, '
                    'supply chain management, and lean production techniques.'
                ),
            },
            {
                'name': 'Project Management',
                'code': 'Mgmt425',
                'year': 4,
                'period': 2,
                'description': (
                    'Provides comprehensive training in project planning, scheduling, '
                    'budgeting, risk management, and project control. Students apply '
                    'project management tools and techniques to real world scenarios.'
                ),
            },
            {
                'name': 'Senior Essay in Management',
                'code': 'Mgmt426',
                'year': 4,
                'period': 2,
                'description': (
                    'A capstone research project where students independently investigate '
                    'a management problem of their choice. Students demonstrate mastery of '
                    'research methods and management theory through a written thesis.'
                ),
            },

            # YEAR 4 TERM 3
            {
                'name': 'Advanced Entrepreneurship and Enterprise Management',
                'code': 'Mgmt424',
                'year': 4,
                'period': 3,
                'description': (
                    'Advances entrepreneurship concepts with focus on venture creation, '
                    'business plan development, financing new ventures, scaling businesses, '
                    'and managing growing enterprises in the Ethiopian business environment.'
                ),
            },
            {
                'name': 'Business Law',
                'code': 'Law201',
                'year': 4,
                'period': 3,
                'description': (
                    'Introduces the legal framework governing business activities in Ethiopia. '
                    'Topics include contract law, commercial law, company law, employment law, '
                    'and dispute resolution mechanisms relevant to business operations.'
                ),
            },
            {
                'name': 'Human Resource Management',
                'code': 'Mgmt322',
                'year': 4,
                'period': 3,
                'description': (
                    'Covers the management of human resources in organizations including '
                    'recruitment, selection, training, performance appraisal, compensation, '
                    'and employee relations in the Ethiopian employment context.'
                ),
            },
            {
                'name': 'Risk Management and Insurance',
                'code': 'Mgmt321',
                'year': 4,
                'period': 3,
                'description': (
                    'Examines risk identification, assessment, and mitigation strategies '
                    'for organizations. Topics include insurance principles, risk financing, '
                    'enterprise risk management, and the Ethiopian insurance industry.'
                ),
            },
        ]


        for data in courses:
            course, course_created = Course.objects.update_or_create(
                code=data['code'],
                defaults={'name': data['name']},
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