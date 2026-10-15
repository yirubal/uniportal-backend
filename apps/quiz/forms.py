from django import forms
from unfold.widgets import UnfoldAdminSelectWidget, UnfoldAdminTextInputWidget

from .models import Chapter, ExamPaper, Question


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
