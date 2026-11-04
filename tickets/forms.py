from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import User, Ticket, Comment


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-select'
            else:
                field.widget.attrs['class'] = 'form-control'


class LoginForm(BootstrapMixin, AuthenticationForm):
    pass


class RegisterForm(BootstrapMixin, UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.role = 'employee'  # public sign-up is always an employee
        if commit:
            user.save()
        return user


class TicketForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ['title', 'description', 'category', 'priority', 'screenshot']
        widgets = {'description': forms.Textarea(attrs={'rows': 5})}

    def clean_title(self):
        title = self.cleaned_data['title'].strip()
        if len(title) < 5:
            raise forms.ValidationError('Title must be at least 5 characters.')
        return title

    def clean_description(self):
        description = self.cleaned_data['description'].strip()
        if len(description) < 10:
            raise forms.ValidationError('Please describe the problem in at least 10 characters.')
        return description

    def clean_screenshot(self):
        image = self.cleaned_data.get('screenshot')
        if image and image.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Screenshot must be smaller than 2 MB.')
        return image


class CommentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['text']
        widgets = {'text': forms.Textarea(attrs={'rows': 3})}
        labels = {'text': 'Add a comment'}

    def clean_text(self):
        text = self.cleaned_data['text'].strip()
        if not text:
            raise forms.ValidationError('Comment cannot be empty.')
        return text