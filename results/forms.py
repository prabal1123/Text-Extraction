from django import forms
from .models import Championship

class ChampionshipUploadForm(forms.ModelForm):
    pdf_file = forms.FileField(label="Championship PDF Communique", widget=forms.ClearableFileInput(attrs={'accept': '.pdf'}))

    class Meta:
        model = Championship
        fields = ['edition', 'year', 'venue', 'source_url']
        widgets = {
            'edition': forms.NumberInput(attrs={'placeholder': 'Auto-detected if left blank'}),
            'year': forms.NumberInput(attrs={'placeholder': 'Auto-detected if left blank'}),
            'venue': forms.TextInput(attrs={'placeholder': 'Optional (e.g., New Delhi)'}),
            'source_url': forms.URLInput(attrs={'placeholder': 'Optional URL'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make metadata fields optional so the user can just upload the PDF
        for field in ['edition', 'year', 'venue', 'source_url']:
            self.fields[field].required = False
