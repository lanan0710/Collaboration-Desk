from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


User = get_user_model()


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(label="邮箱", required=True)
    requested_admin = forms.BooleanField(label="申请业务管理员权限", required=False)
    admin_request_reason = forms.CharField(
        label="管理员申请理由",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "说明为什么需要管理用户、需求和验收流程",
            }
        ),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "requested_admin", "admin_request_reason")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("该邮箱已被使用。")
        return email

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("requested_admin") and not cleaned_data.get(
            "admin_request_reason", ""
        ).strip():
            self.add_error("admin_request_reason", "申请业务管理员时必须填写理由。")
        return cleaned_data
