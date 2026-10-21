from uuid import UUID, uuid4

from django import forms
from django.core import signing
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminTextInputWidget

from .models import Chapter, ExamPaper, Question


class PaperQuestionExtractionForm(forms.Form):
    exam_paper = forms.ModelChoiceField(ExamPaper.objects.filter(is_active=True), widget=UnfoldAdminSelectWidget)
    inbox = forms.ModelChoiceField(queryset=None, required=False, empty_label='Choose an inbox file', widget=UnfoldAdminSelectWidget)
    resource = forms.ModelChoiceField(queryset=None, required=False, empty_label='Choose an existing resource', widget=UnfoldAdminSelectWidget)
    chapter = forms.ModelChoiceField(Chapter.objects.none(), required=False, widget=UnfoldAdminSelectWidget,
        help_text='Optional: assign a chapter only if the entire source belongs to it. Otherwise organize chapters during review.')

    def __init__(self, *args, user, paper=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.content.models import FileInbox, Resource
        can_read = lambda app, model: user.has_perm(f'{app}.view_{model}') or user.has_perm(f'{app}.change_{model}')
        self.fields['inbox'].queryset = (FileInbox.objects.filter(processing_status='processed').exclude(extracted_text='')
            .defer('extracted_text', 'telegram_caption', 'processing_error') if can_read('content', 'fileinbox') else FileInbox.objects.none())
        self.fields['resource'].queryset = (Resource.objects.exclude(extracted_text='').defer('extracted_text')
            if can_read('content', 'resource') else Resource.objects.none())
        if paper:
            self.fields['exam_paper'].queryset = ExamPaper.objects.filter(pk=paper.pk, is_active=True)
            self.fields['exam_paper'].initial = paper.pk
            self.fields['exam_paper'].widget = forms.HiddenInput()
        self.fields['chapter'].queryset = (Chapter.objects.filter(is_active=True).select_related('course')
            if can_read('quiz', 'chapter') else Chapter.objects.none())
        if paper and not paper.course_id:
            self.fields['chapter'].widget = forms.HiddenInput()
        elif paper:
            self.fields['chapter'].queryset = self.fields['chapter'].queryset.filter(course_id=paper.course_id)

    def clean(self):
        data = super().clean()
        if bool(data.get('inbox')) == bool(data.get('resource')):
            raise forms.ValidationError('Choose one inbox file or one existing resource.')
        paper, chapter = data.get('exam_paper'), data.get('chapter')
        if paper and not paper.is_exit_exam and not paper.course_id:
            self.add_error('exam_paper', 'Assign a course to this paper first.')
        if paper and chapter and chapter.course_id != paper.course_id:
            self.add_error('chapter', 'Choose a chapter belonging to the paper course.')
        return data


class PracticePaperGenerationForm(PaperQuestionExtractionForm):
    title = forms.CharField(max_length=500, widget=UnfoldAdminTextInputWidget)
    exam_type = forms.ChoiceField(choices=[('quiz', 'Practice quiz'), ('exit_model', 'Exit exam — model')], widget=UnfoldAdminSelectWidget)
    course = forms.ModelChoiceField(queryset=None, required=False, widget=UnfoldAdminSelectWidget,
                                   help_text='Required for practice quizzes. Leave blank for exit models.')
    department = forms.ModelChoiceField(queryset=None, required=False, widget=UnfoldAdminSelectWidget,
                                       help_text='Required for exit model papers.')
    year = forms.IntegerField(min_value=1, max_value=9999, help_text='Use the same year/calendar convention as your other papers.')
    duration_minutes = forms.IntegerField(min_value=1, max_value=300, initial=30)
    access_level = forms.ChoiceField(choices=ExamPaper.ACCESS_CHOICES, initial='free', widget=UnfoldAdminSelectWidget)
    count = forms.IntegerField(min_value=1, max_value=30, initial=10, label='Number of questions')
    question_type = forms.ChoiceField(choices=Question.TYPE_CHOICES, widget=UnfoldAdminSelectWidget)
    difficulty = forms.ChoiceField(choices=Question.DIFFICULTY_CHOICES, initial='medium', widget=UnfoldAdminSelectWidget)
    focus = forms.CharField(max_length=500, required=False, widget=UnfoldAdminTextInputWidget,
                           help_text='Optional topics to emphasize within the selected source.')
    submission_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, user=user, **kwargs)
        del self.fields['exam_paper']
        from apps.content.models import Course, Department
        for name, model in [('course', Course), ('department', Department)]:
            self.fields[name].queryset = (model.objects.filter(is_active=True)
                if user.has_perm(f'content.view_{name}') or user.has_perm(f'content.change_{name}') else model.objects.none())
        if not self.is_bound:
            self.initial['submission_token'] = signing.dumps({'user': user.pk, 'nonce': str(uuid4())}, salt='admin-paper-generation')
        self.order_fields(['title', 'exam_type', 'course', 'department', 'year', 'duration_minutes',
            'access_level', 'inbox', 'resource', 'chapter', 'count', 'question_type', 'difficulty', 'focus', 'submission_token'])

    def clean_submission_token(self):
        try:
            token = signing.loads(self.cleaned_data['submission_token'], salt='admin-paper-generation', max_age=3600)
            if token['user'] != self.user.pk:
                raise signing.BadSignature
            return UUID(token['nonce'])
        except (signing.BadSignature, ValueError, TypeError, KeyError):
            raise forms.ValidationError('This generation form expired or is invalid. Open a fresh form.') from None

    def clean(self):
        data = super().clean()
        if data.get('exam_type') == 'quiz' and not data.get('course'):
            self.add_error('course', 'Choose a course for the practice quiz.')
        if data.get('exam_type') == 'exit_model':
            if not data.get('department'):
                self.add_error('department', 'Choose a department for the exit model.')
            if data.get('course'):
                self.add_error('course', 'Leave course blank for a department-wide exit model.')
        chapter = data.get('chapter')
        if chapter and chapter.course_id != getattr(data.get('course'), 'pk', None):
            self.add_error('chapter', 'Choose a chapter belonging to the selected course.')
        return data


class QuestionBulkEditForm(forms.Form):
    selection = forms.CharField(widget=forms.HiddenInput)
    exam_paper = forms.ModelChoiceField(
        ExamPaper.objects.filter(is_active=True).select_related('course', 'department'),
        required=False, empty_label='Keep existing paper', widget=UnfoldAdminSelectWidget,
    )
    chapter = forms.ModelChoiceField(
        Chapter.objects.filter(is_active=True).select_related('course'),
        required=False, empty_label='Keep existing chapter', widget=UnfoldAdminSelectWidget,
    )
    clear_chapter = forms.BooleanField(required=False, label='Remove existing chapter assignment')
    year_source = forms.CharField(required=False, max_length=Question._meta.get_field('year_source').max_length,
                                  widget=UnfoldAdminTextInputWidget,
                                  help_text='Blank keeps the current value. Ethiopian calendar labels are supported.')
    difficulty = forms.ChoiceField(required=False, choices=[('', 'Keep existing difficulty'), *Question.DIFFICULTY_CHOICES],
                                   widget=UnfoldAdminSelectWidget)
    is_active = forms.ChoiceField(required=False, label='Visibility', widget=UnfoldAdminSelectWidget,
                                 choices=[('', 'Keep existing visibility'), ('true', 'Active'), ('false', 'Inactive')])

    def __init__(self, *args, user, assignment_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        for name, model in [('exam_paper', ExamPaper), ('chapter', Chapter)]:
            if not (user.has_perm(f'quiz.view_{model._meta.model_name}') or user.has_perm(f'quiz.change_{model._meta.model_name}')):
                self.fields[name].queryset = model.objects.none()
                self.fields[name].help_text = 'You need permission to view this related model before assigning it.'
        if assignment_only:
            self.fields['exam_paper'].required = True
            for field in ('year_source', 'difficulty', 'is_active'):
                del self.fields[field]

    def clean(self):
        data = super().clean()
        if data.get('chapter') and data.get('clear_chapter'):
            self.add_error('chapter', 'Choose a chapter or remove the assignment, not both.')
        return data
