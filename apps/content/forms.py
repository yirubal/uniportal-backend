from django import forms
from django.db.models import Q

from .models import Course, Resource


class ResourceReviewForm(forms.ModelForm):
    class Meta:
        model = Resource
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'courses' in self.fields:
            # Keep existing inactive assignments visible when editing an older file.
            available = Q(is_active=True)
            if self.instance.pk:
                available |= Q(resources=self.instance.pk)
            self.fields['courses'].queryset = Course.objects.filter(available).distinct().order_by('name')

    def clean(self):
        data = super().clean()
        if data.get('status') == Resource.STATUS_PUBLISHED:
            if not data.get('file'):
                self.add_error('file', 'Attach a file before publishing.')
            courses = data.get('courses')
            if courses is None or not courses.filter(is_active=True).exists():
                self.add_error('courses', 'Assign at least one active course before publishing.')
        return data
